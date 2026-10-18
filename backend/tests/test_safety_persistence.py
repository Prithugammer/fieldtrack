"""Safety state survives a server restart (disposable file databases only).

A "restart" here is exactly what a real one is: the old app object is thrown away (its in-memory
state is gone) and a NEW app is created on the same database file. Times are explicit so nothing
sleeps. Thresholds: first check-in 10 s after the worker stops, three 5 s windows, so the emergency is
declared at +25 s.
"""

import threading
from collections import Counter

import pytest

from app import create_app
from extensions import db
from models import User
from safety import SafetyConfig, SafetyStore, SafetyTicker
from safety.machine import EMERGENCY, NORMAL, POST_INCIDENT
from safety.store import SafetyAuditRow, SafetyNotificationRow, SafetyWorkerState
from tests.conftest import PASSWORD, _load_fixture_data
from tests.test_safety import live, worker

T0 = 70_000.0
CFG = SafetyConfig.from_mode(
    "demo", seed=11, break_zones=(), accident_probability=0, auto_respond_chance=0,
    idle_threshold_seconds=10, checkin_response_window_seconds=5, num_checkins=3, max_poll_gap_seconds=1e9,
)  # fmt: skip


def crew():
    return live(worker(101, "Alpha", "On site"), worker(102, "Bravo", "On site", 27.71, 85.31))


def start(path, first=False, **cfg):
    """Boot the app on `path` (a restart when the file already holds data)."""
    app = create_app(
        {"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///" + path.as_posix(), "SAFETY_CONFIG": CFG, "BCRYPT_ROUNDS": 4,
         "LOGIN_RATE_LIMIT_ENABLED": False, **cfg}
    )  # fmt: skip
    if first:
        with app.app_context():
            _load_fixture_data()
    return app


def svc_of(app):
    return app.extensions["safety"]


def run(app, seconds, start_at=0):
    ticker = SafetyTicker(app, state_source=crew)
    for sec in range(start_at, start_at + seconds + 1):
        assert ticker.tick_once(now=T0 + sec)
    ticker.stop()  # a graceful shutdown hands the heartbeat lease back (a crash would let it expire instead)
    return ticker


def rows(app, model, **filters):
    with app.app_context():
        found = model.query.filter_by(**filters).all()
        db.session.remove()
        return found


def counts(app, worker_id=101):
    return Counter(r.event for r in rows(app, SafetyAuditRow, worker_id=worker_id))


@pytest.fixture
def dbfile(tmp_path):
    return tmp_path / "safety.db"


def login(app, email):
    res = app.test_client().post("/api/auth/login", json={"email": email, "password": PASSWORD})
    return {"Authorization": "Bearer " + res.get_json()["token"]}


# ---- an open emergency survives a restart -----------------------------------------------------------------


def test_an_emergency_is_saved_and_still_there_after_a_restart(dbfile):
    app = start(dbfile, first=True)
    run(app, 30)  # worker 101 is stationary: emergency at +25 s
    assert svc_of(app)._machines[101].state == EMERGENCY
    saved = rows(app, SafetyWorkerState, worker_id=101)
    assert len(saved) == 1 and saved[0].state == EMERGENCY  # (3) persisted
    before = counts(app)
    assert before["EMERGENCY"] == 1 and before["EMERGENCY_CALL"] == 1

    restarted = start(dbfile)  # (4) stop and start again: a new process memory
    s2 = svc_of(restarted)
    assert (
        s2.restored["workers"] == 2 and s2._machines[101].state == EMERGENCY
    )  # (5) still present, same status
    assert s2._machines[101].emergency_at == pytest.approx(T0 + 25)  # creation time preserved
    assert s2.audit_entries(101)[-1]["event"] == "EMERGENCY_CALL"  # history restored
    body = s2.view(crew(), now=T0 + 31)
    assert [a["worker_id"] for a in body["safety"]["alerts"]] == [101, 102] and body["workers"][0][
        "status"
    ] == "EMERGENCY"

    run(
        restarted, 20, start_at=31
    )  # (6) the heartbeat keeps running: nothing is duplicated or lost
    after = counts(restarted)
    assert after == before  # not one new event for the already-open emergency
    assert s2._machines[101].state == EMERGENCY
    assert len(rows(restarted, SafetyWorkerState, worker_id=101)) == 1


def test_a_restart_in_the_middle_of_an_escalation_continues_it_on_schedule(dbfile):
    app = start(dbfile, first=True)
    run(app, 17)  # check-in 2 has just been sent (+15 s)
    assert svc_of(app)._machines[101].state == "CHECKIN_2"
    restarted = start(dbfile)
    assert svc_of(restarted)._machines[101].state == "CHECKIN_2"
    run(
        restarted, 12, start_at=18
    )  # nobody told the worker anything new; the due times still apply
    events = [(r.event, round(r.t - T0)) for r in rows(restarted, SafetyAuditRow, worker_id=101)]
    assert ("EMERGENCY", 25) in events and ("CHECKIN_CLEARED", 17) not in events
    assert not any(
        e == "CHECKIN_CLEARED" for e, _ in events
    )  # the restart did not cancel the alert
    assert counts(restarted)["CHECKIN_SENT"] == 3 and counts(restarted)["EMERGENCY"] == 1


def test_several_restarts_in_a_row_never_duplicate_the_incident(dbfile):
    app = start(dbfile, first=True)
    run(app, 30)
    for n in range(4):
        app = start(dbfile)
        run(app, 5, start_at=31 + n * 10)
    c = counts(app)
    assert c["EMERGENCY"] == 1 and c["EMERGENCY_CALL"] == 1 and c["SUPERVISOR_ALERT"] == 2


def test_audit_log_and_message_feed_continue_with_the_same_ids(dbfile):
    app = start(dbfile, first=True)
    run(app, 12)
    last = svc_of(app).audit.last_id()
    notes = svc_of(app).notifier.last_id()
    assert last > 0 and notes > 0
    restarted = start(dbfile)
    s2 = svc_of(restarted)
    assert s2.audit.last_id() == last and s2.notifier.last_id() == notes
    run(restarted, 20, start_at=13)
    ids = [r.id for r in rows(restarted, SafetyAuditRow)]
    assert ids == sorted(set(ids)) and ids[-1] > last  # strictly increasing, no reuse
    assert len(svc_of(restarted).notifier.recent(300)) == len(
        rows(restarted, SafetyNotificationRow)
    )


# ---- every lifecycle step is durable ----------------------------------------------------------------------


def test_acknowledging_a_check_in_is_saved(dbfile):
    app = start(dbfile, first=True)
    run(app, 11)
    assert svc_of(app)._machines[101].state == "CHECKIN_1"
    assert rows(app, SafetyWorkerState, worker_id=101)[0].state == "CHECKIN_1"
    with app.app_context():
        assert svc_of(app).respond(101, now=T0 + 12) is True  # "I'm OK"
    assert rows(app, SafetyWorkerState, worker_id=101) == []  # back to normal: no open row
    assert counts(app)["CHECKIN_RESPONSE"] == 1
    restarted = start(dbfile)
    assert (
        101 not in svc_of(restarted)._machines or svc_of(restarted)._machines[101].state == NORMAL
    )


@pytest.mark.parametrize(
    "outcome,state_after,row_after",
    [("false_alarm", NORMAL, 0), ("real_incident", POST_INCIDENT, 1)],
)
def test_resolution_is_saved_and_survives_a_restart(dbfile, outcome, state_after, row_after):
    app = start(dbfile, first=True)
    run(app, 30)
    with app.app_context():
        svc_of(app).resolve(
            101, outcome, "checked on site", actor="Sue Visor (Supervisor)", now=T0 + 31
        )
    assert len(rows(app, SafetyWorkerState, worker_id=101)) == row_after
    restarted = start(dbfile)
    s2 = svc_of(restarted)
    machine = s2._machines.get(101)
    assert (machine.state if machine else NORMAL) == state_after
    resolved = [e for e in s2.audit_entries(101) if e["event"] == "RESOLVED"]
    assert (
        len(resolved) == 1
        and "checked on site" in resolved[0]["message"]
        and resolved[0]["actor"].startswith("Sue Visor")
    )
    if outcome == "real_incident":
        assert (
            machine.resolution["outcome"] == "real_incident"
            and machine.resolution["note"] == "checked on site"
        )
        with restarted.app_context():
            svc_of(restarted).return_to_duty(101, actor="Sue Visor (Supervisor)", now=T0 + 40)
        assert rows(restarted, SafetyWorkerState, worker_id=101) == []
        assert counts(restarted)["RETURN_TO_DUTY"] == 1
        final = start(dbfile)
        assert (svc_of(final)._machines.get(101) is None) or svc_of(final)._machines[
            101
        ].state == NORMAL


def test_a_resolved_emergency_stays_resolved_after_restart_and_further_ticks(dbfile):
    app = start(dbfile, first=True)
    run(app, 30)
    with app.app_context():
        svc_of(app).resolve(101, "false_alarm", "", actor="x", now=T0 + 31)
    restarted = start(dbfile)
    assert (
        svc_of(restarted)._machines.get(101) is None
        or svc_of(restarted)._machines[101].state == NORMAL
    )
    run(
        restarted, 8, start_at=32
    )  # the worker is still standing there, but only a NEW idle period counts
    assert counts(restarted)["EMERGENCY"] == 1


def test_accident_stop_break_and_incapacity_are_saved(dbfile):
    app = start(dbfile, first=True)
    svc = svc_of(app)
    run(app, 1)
    with app.app_context():
        svc.trigger_accident(101, actor="Sue", now=T0 + 2)
        svc.set_break(102, True, actor="Sue", now=T0 + 2)
    restarted = start(dbfile)
    s2 = svc_of(restarted)
    assert 101 in s2._frozen and 101 in s2._incapacitated and 102 in s2._on_break
    assert s2._frozen[101]["pos"] == pytest.approx((27.70, 85.30))
    body = s2.view(crew(), now=T0 + 3)
    w101 = next(w for w in body["workers"] if w["id"] == 101)
    assert (
        w101["status"] == "Stopped"
        and w101["safety"]["incapacitated"]
        and w101["safety"]["stopped"]
    )
    assert next(w for w in body["workers"] if w["id"] == 102)["safety"]["on_break"]


def test_workers_who_are_simply_normal_have_no_rows(dbfile):
    app = start(dbfile, first=True)
    run(app, 5)  # nobody has been idle for 10 s yet
    assert rows(app, SafetyWorkerState) == []


# ---- failures: nothing is lost and nothing is wrongly closed ------------------------------------------------


def test_a_resolution_that_cannot_be_saved_is_refused_and_the_emergency_stays_open(
    dbfile, monkeypatch
):
    app = start(dbfile, first=True)
    run(app, 30)
    supervisor = login(app, "super@test.com")
    svc = svc_of(app)
    events_before = len(svc.audit.entries())

    def broken(*args, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(SafetyStore, "save", broken)
    client = app.test_client()
    res = client.post(
        "/api/safety/workers/101/resolve", json={"outcome": "false_alarm"}, headers=supervisor
    )
    assert res.status_code == 503 and "could not be saved" in res.get_json()["error"]
    assert svc._machines[101].state == EMERGENCY  # not reported resolved
    assert len(svc.audit.entries()) == events_before  # the RESOLVED entry was undone
    assert svc.persist_errors >= 1
    monkeypatch.undo()
    assert (
        rows(app, SafetyWorkerState, worker_id=101)[0].state == EMERGENCY
    )  # the database still says open
    ok = client.post(
        "/api/safety/workers/101/resolve", json={"outcome": "false_alarm"}, headers=supervisor
    )
    assert (
        ok.status_code == 200 and rows(app, SafetyWorkerState, worker_id=101) == []
    )  # retry works


def test_every_operator_action_is_undone_when_it_cannot_be_saved(dbfile, monkeypatch):
    app = start(dbfile, first=True)
    run(app, 1)
    svc = svc_of(app)
    monkeypatch.setattr(
        SafetyStore, "save", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db down"))
    )
    from safety.service import SafetyError

    with app.app_context():
        for call in (
            lambda: svc.trigger_accident(101, actor="x", now=T0 + 2),
            lambda: svc.sos(101, actor="x", now=T0 + 2),
            lambda: svc.set_break(101, True, actor="x", now=T0 + 2),
        ):
            with pytest.raises(SafetyError) as err:
                call()
            assert err.value.status == 503
    assert (
        svc._machines[101].state == NORMAL
        and not svc._frozen
        and not svc._on_break
        and not svc._incapacitated
    )
    assert svc.audit.entries() == []


def test_a_failed_heartbeat_save_keeps_the_emergency_in_memory_and_is_retried(dbfile, monkeypatch):
    app = start(dbfile, first=True)
    real_save = SafetyStore.save
    state = {"fail": True}

    def flaky(self, *args, **kwargs):
        if state["fail"]:
            raise RuntimeError("database is down")
        return real_save(self, *args, **kwargs)

    monkeypatch.setattr(SafetyStore, "save", flaky)
    ticker = SafetyTicker(app, state_source=crew)
    for sec in range(0, 31):
        ticker.tick_once(now=T0 + sec)
    svc = svc_of(app)
    assert svc._machines[101].state == EMERGENCY  # escalation itself is not blocked by the database
    assert svc.last_persist_error == "RuntimeError" and svc.persist_errors > 0
    assert rows(app, SafetyWorkerState) == []  # nothing saved yet...
    mon = svc.view(crew(), now=T0 + 31)["safety"]["monitoring"]["persistence"]
    assert mon["ok"] is False and mon["unsaved_events"] > 0  # ...and the UI is told

    state["fail"] = False
    ticker.tick_once(now=T0 + 32)  # the database is back: the very next tick saves everything
    assert rows(app, SafetyWorkerState, worker_id=101)[0].state == EMERGENCY
    assert svc.last_persist_error is None
    assert svc.view(crew(), now=T0 + 33)["safety"]["monitoring"]["persistence"] == {
        "enabled": True,
        "ok": True,
        "unsaved_events": 0,
    }
    assert counts(app)["EMERGENCY"] == 1  # saved once, not once per failed attempt


def test_start_up_refuses_a_database_it_cannot_read_instead_of_starting_empty(dbfile, monkeypatch):
    start(dbfile, first=True)
    monkeypatch.setattr(
        SafetyStore, "load", lambda self: (_ for _ in ()).throw(RuntimeError("cannot read"))
    )
    with pytest.raises(RuntimeError, match="cannot read"):
        start(dbfile)


def test_an_unreadable_row_is_skipped_and_logged_not_fatal(dbfile, caplog):
    app = start(dbfile, first=True)
    run(app, 30)
    with app.app_context():
        row = db.session.get(SafetyWorkerState, 101)
        row.data = "{not json"
        db.session.commit()
        db.session.remove()
    restarted = start(dbfile)
    assert 101 not in svc_of(restarted)._machines and 102 in svc_of(restarted)._machines
    assert "unreadable" in caplog.text


def test_persistence_can_be_switched_off(dbfile):
    app = start(dbfile, first=True, SAFETY_PERSISTENCE=False)
    assert svc_of(app).store is None
    run(app, 30)
    assert rows(app, SafetyWorkerState) == []
    assert svc_of(start(dbfile, SAFETY_PERSISTENCE=False))._machines == {}


# ---- concurrency ----------------------------------------------------------------------------------------------


def test_many_threads_ticking_the_same_app_create_exactly_one_emergency(dbfile):
    app = start(dbfile, first=True)
    ticker = SafetyTicker(app, state_source=crew)
    for sec in range(0, 40):
        gate = threading.Barrier(6)

        def go(sec=sec):
            gate.wait()
            ticker.tick_once(now=T0 + sec)

        threads = [threading.Thread(target=go) for _ in range(6)]
        [t.start() for t in threads]
        [t.join() for t in threads]
    c = counts(app)
    assert c["EMERGENCY"] == 1 and c["EMERGENCY_CALL"] == 1
    ids = [r.id for r in rows(app, SafetyAuditRow)]
    assert len(ids) == len(set(ids))


def test_two_server_processes_on_one_database_only_one_runs_the_heartbeat(dbfile):
    a = start(dbfile, first=True)
    b = start(dbfile)
    ta, tb = SafetyTicker(a, state_source=crew), SafetyTicker(b, state_source=crew)
    for sec in range(0, 31):
        ta.tick_once(now=T0 + sec)
        tb.tick_once(now=T0 + sec)
    assert ta.is_leader is True and tb.is_leader is False and tb.skipped == 31 and tb.ticks == 0
    assert counts(a)["EMERGENCY"] == 1  # the second process did not escalate the same worker again
    assert svc_of(b)._machines == {}  # ...and kept no competing state of its own


def test_when_the_leader_stops_the_other_process_takes_over_and_continues(dbfile):
    a = start(dbfile, first=True)
    b = start(dbfile)
    ta, tb = SafetyTicker(a, state_source=crew), SafetyTicker(b, state_source=crew)
    for sec in range(0, 13):  # A leads; check-in 1 is open
        ta.tick_once(now=T0 + sec)
        tb.tick_once(now=T0 + sec)
    assert svc_of(a)._machines[101].state == "CHECKIN_1" and tb.is_leader is False
    ta.stop()  # releases the lease (a crashed leader's lease simply expires)
    for sec in range(13, 32):
        tb.tick_once(now=T0 + sec)
    assert tb.is_leader is True
    assert (
        svc_of(b)._machines[101].state == EMERGENCY
    )  # picked up the open check-in and finished it
    c = counts(b)
    assert c["EMERGENCY"] == 1 and c["CHECKIN_SENT"] == 3 and c["IDLE_DETECTED"] == 1


def test_an_expired_lease_is_taken_over_without_the_old_leader_releasing_it(dbfile):
    app = start(dbfile, first=True)
    with app.app_context():
        store = SafetyStore()
        assert store.acquire_lease("heartbeat", "old-process", ttl=5, now=1000.0)
        assert not store.acquire_lease("heartbeat", "new-process", ttl=5, now=1003.0)  # still valid
        assert store.acquire_lease("heartbeat", "new-process", ttl=5, now=1006.0)  # expired: taken
        assert store.acquire_lease(
            "heartbeat", "new-process", ttl=5, now=1007.0
        )  # renewing is fine
        assert not store.acquire_lease("heartbeat", "old-process", ttl=5, now=1008.0)
        db.session.remove()


# ---- through the HTTP API ------------------------------------------------------------------------------------------


def test_after_a_restart_only_authorised_roles_can_close_the_restored_emergency(dbfile):
    app = start(dbfile, first=True)
    run(app, 30)
    restarted = start(dbfile)
    client = restarted.test_client()
    dispatcher = login(restarted, "dispatch@test.com")
    supervisor = login(restarted, "super@test.com")
    live_before = client.get("/api/map/live", headers=dispatcher)
    assert live_before.status_code == 200
    assert client.get("/api/safety/audit", headers=dispatcher).get_json()[0][
        "event"
    ]  # history is readable after restart
    refused = client.post(
        "/api/safety/workers/101/resolve", json={"outcome": "false_alarm"}, headers=dispatcher
    )
    assert refused.status_code == 403
    assert svc_of(restarted)._machines[101].state == EMERGENCY
    assert (
        client.post(
            "/api/safety/workers/101/resolve", json={"outcome": "false_alarm"}, headers={}
        ).status_code
        == 401
    )
    # The restored worker is "known" only after the first tick; the API tick provides it.
    import routes.safety as rsafety

    rsafety.compute_live_state = lambda path_for=None: crew()
    assert client.post("/api/safety/tick", headers=supervisor).status_code == 200
    ok = client.post(
        "/api/safety/workers/101/resolve",
        json={"outcome": "real_incident", "note": "after restart"},
        headers=supervisor,
    )
    assert ok.status_code == 200
    assert rows(restarted, SafetyWorkerState, worker_id=101)[0].state == POST_INCIDENT
    assert (
        client.post(
            "/api/safety/workers/101/resolve", json={"outcome": "false_alarm"}, headers=supervisor
        ).status_code
        == 409
    )


def test_the_new_tables_are_added_to_an_existing_database_without_touching_its_data(dbfile):
    app = start(dbfile, first=True)
    with app.app_context():
        for table in ("safety_worker_state", "safety_audit", "safety_notification", "safety_lease"):
            db.session.execute(
                db.text(f"DROP TABLE {table}")
            )  # a database from before this feature existed
        db.session.commit()
        users_before = User.query.count()
        db.engine.dispose()
    upgraded = start(dbfile)  # no destroy/recreate: create_all adds only what is missing
    with upgraded.app_context():
        assert User.query.count() == users_before
        names = {
            r[0]
            for r in db.session.execute(
                db.text("SELECT name FROM sqlite_master WHERE type='table'")
            )
        }
        assert {
            "safety_worker_state",
            "safety_audit",
            "safety_notification",
            "safety_lease",
        } <= names
        db.session.remove()
    run(upgraded, 30)
    assert counts(upgraded)["EMERGENCY"] == 1
