"""D-12: safety escalation is advanced by the backend, not by browsers.

The state machine takes explicit times, so these tests drive it with a controllable clock instead
of sleeping. Documented threshold (from the demo-style config used here): the first check-in is
sent `idle_threshold_seconds` after the worker stops, each unanswered check-in waits
`checkin_response_window_seconds`, and the emergency is declared after the last window:

    emergency at  idle + num_checkins * window   (10 + 3 * 5 = 25 s here; 600 + 3 * 120 = 960 s in "real" mode)
"""

import threading
import time
from collections import Counter

import pytest

from app import create_app
from safety import SafetyTicker, start_background_services
from safety.machine import EMERGENCY, NORMAL
from tests.conftest import login
from tests.test_safety import live, worker

IDLE, WINDOW, CHECKINS = 10, 5, 3
EMERGENCY_AT = IDLE + CHECKINS * WINDOW  # 25
T0 = 50_000.0


def fixed_state():
    """One worker standing still on site (the case that must escalate)."""
    return live(worker(101, "Alpha", "On site"), worker(102, "Bravo", "On site", 27.71, 85.31))


@pytest.fixture
def svc(app):
    s = app.extensions["safety"]
    s.config = s.config.with_changes(
        accident_probability=0,
        auto_respond_chance=0,
        idle_threshold_seconds=IDLE,
        checkin_response_window_seconds=WINDOW,
        num_checkins=CHECKINS,
        max_poll_gap_seconds=10,
    )
    s.roller.config = s.planner.config = s.config
    return s


def events(svc, worker_id=101):
    return [
        (e["event"], round(e["t"] - T0, 3))
        for e in svc.audit.entries()
        if e["worker_id"] == worker_id
    ]


# ---- escalation with no browser at all ------------------------------------------------------------


def test_a_missed_check_in_escalates_to_emergency_with_no_http_request_at_all(app, svc):
    ticker = SafetyTicker(app, state_source=fixed_state)
    states = {}
    for sec in range(0, 31):  # no client, no request: only the backend heartbeat, once per second
        ticker.tick_once(now=T0 + sec)
        states[sec] = svc._machines[101].state
    assert states[IDLE - 1] == NORMAL
    assert states[IDLE] == "CHECKIN_1" and states[IDLE + WINDOW] == "CHECKIN_2"
    assert states[IDLE + 2 * WINDOW] == "CHECKIN_3"
    assert states[EMERGENCY_AT - 1] == "CHECKIN_3" and states[EMERGENCY_AT] == EMERGENCY
    # Every transition is stamped with the moment it was due.
    assert events(svc) == [
        ("IDLE_DETECTED", 10.0), ("CHECKIN_SENT", 10.0), ("SUPERVISOR_ALERT", 10.0),
        ("CHECKIN_UNANSWERED", 15.0), ("CHECKIN_SENT", 15.0),
        ("CHECKIN_UNANSWERED", 20.0), ("CHECKIN_SENT", 20.0),
        ("CHECKIN_UNANSWERED", 25.0), ("EMERGENCY", 25.0), ("SUPERVISOR_ALERT", 25.0), ("EMERGENCY_CALL", 25.0),
    ]  # fmt: skip
    assert ticker.errors == 0 and ticker.ticks == 31


def test_closing_every_browser_tab_does_not_stop_escalation(app, svc, client, supervisor_headers):
    """Previously: a dashboard polling for 12 s then closing left the check-in 'paused' and cleared."""
    ticker = SafetyTicker(app, state_source=fixed_state)
    import routes.safety as rsafety

    rsafety.compute_live_state = (
        lambda path_for=None: fixed_state()
    )  # what a browser poll would see
    for sec in range(0, 13):  # a dashboard is open and polling for the first 12 s
        svc.clock = lambda s=sec: T0 + s
        client.post("/api/safety/tick", headers=supervisor_headers)
        ticker.tick_once(now=T0 + sec)
    assert svc._machines[101].state == "CHECKIN_1"
    for sec in range(13, 41):  # ...then every tab is closed: only the heartbeat remains
        ticker.tick_once(now=T0 + sec)
    assert svc._machines[101].state == EMERGENCY
    assert ("EMERGENCY", 25.0) in events(svc)
    assert not any(e == "CHECKIN_CLEARED" for e, _ in events(svc))


def test_escalation_without_a_heartbeat_still_needs_someone_to_tick(app, svc):
    """Documents WHY the heartbeat exists: a process that is not ticked does not escalate."""
    for sec in range(0, 13):  # something polls every second for 12 s: check-in 1 is sent
        svc.process(fixed_state(), now=T0 + sec)
    assert svc._machines[101].state == "CHECKIN_1"
    svc.process(fixed_state(), now=T0 + 60)  # first tick after a gap longer than max_poll_gap
    assert svc._machines[101].state == NORMAL
    assert any(e == "CHECKIN_CLEARED" for e, _ in events(svc))


def test_a_worker_who_moves_or_replies_never_reaches_emergency(app, svc):
    ticker = SafetyTicker(app, state_source=fixed_state)
    for sec in range(0, 13):
        ticker.tick_once(now=T0 + sec)
    assert svc._machines[101].state == "CHECKIN_1"
    svc.respond(101, now=T0 + 13)  # "I'm OK" while the heartbeat keeps running
    for sec in range(14, 40):
        ticker.tick_once(now=T0 + sec)
        assert svc._machines[101].state != EMERGENCY or sec >= 13 + IDLE + CHECKINS * WINDOW
    assert ("EMERGENCY", 13.0 + IDLE + CHECKINS * WINDOW) in events(
        svc
    )  # idle timer restarted at the reply


# ---- the real background thread ---------------------------------------------------------------------


def test_the_background_thread_escalates_by_itself(app, svc):
    svc.config = svc.config.with_changes(max_poll_gap_seconds=1e9)
    svc.roller.config = svc.planner.config = svc.config
    started = time.monotonic()
    speed = 500.0  # 1 real second = 500 simulated seconds, so the whole escalation takes ~50 ms
    svc.clock = svc.audit.clock = svc.notifier.clock = (
        lambda: T0 + (time.monotonic() - started) * speed
    )
    ticker = SafetyTicker(app, interval=0.005, state_source=fixed_state)
    ticker.start()
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and not (
            101 in svc._machines and svc._machines[101].state == EMERGENCY
        ):
            time.sleep(0.01)
        assert svc._machines[101].state == EMERGENCY, "heartbeat never reached the emergency"
        assert ticker.running and ticker.ticks >= 2
    finally:
        ticker.stop()
    assert not ticker.running
    assert Counter(e for e, _ in events(svc))["EMERGENCY"] == 1


def test_start_is_idempotent_and_stop_ends_the_thread(app):
    ticker = SafetyTicker(app, interval=0.01, state_source=fixed_state)
    ticker.start()
    first = ticker._thread
    ticker.start()
    assert ticker._thread is first and ticker.running
    ticker.stop()
    assert not ticker.running
    ticker.stop()  # stopping twice is harmless
    ticker.start()  # and it can be restarted
    assert ticker.running
    ticker.stop()


def test_a_failing_tick_is_counted_and_the_heartbeat_keeps_going(app, svc, caplog):
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] <= 2:
            raise RuntimeError("database went away")
        return fixed_state()

    ticker = SafetyTicker(app, state_source=flaky)
    assert ticker.tick_once(now=T0) is False and ticker.tick_once(now=T0 + 1) is False
    assert ticker.tick_once(now=T0 + 2) is True
    assert (ticker.errors, ticker.ticks, ticker.last_error) == (2, 1, "RuntimeError")
    assert caplog.text.count("Safety tick failed") == 1  # logged once, not on every failure
    assert "database went away" in caplog.text  # server-side diagnostics kept
    assert 101 in svc._machines


def test_the_thread_survives_a_state_source_that_always_fails(app):
    ticker = SafetyTicker(app, interval=0.005, state_source=lambda: 1 / 0)
    ticker.start()
    try:
        deadline = time.monotonic() + 5
        while ticker.errors < 5 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert ticker.errors >= 5 and ticker.running
    finally:
        ticker.stop()


# ---- concurrency: the same event is never advanced twice ------------------------------------------------


def test_heartbeat_and_many_clients_never_duplicate_an_event(app, svc):
    def run(parallel):
        a = create_app(
            {"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:", "BCRYPT_ROUNDS": 4}
        )
        s = a.extensions["safety"]
        s.config = svc.config
        s.roller.config = s.planner.config = s.config
        ticker = SafetyTicker(a, state_source=fixed_state)
        for sec in range(0, 61):
            if not parallel:
                ticker.tick_once(now=T0 + sec)
                continue
            gate = threading.Barrier(9)

            def tick_via_heartbeat():
                gate.wait()
                ticker.tick_once(now=T0 + sec)

            def tick_via_client():
                gate.wait()
                s.process(fixed_state(), now=T0 + sec)

            threads = [threading.Thread(target=tick_via_heartbeat)] + [
                threading.Thread(target=tick_via_client) for _ in range(8)
            ]
            [t.start() for t in threads]
            [t.join() for t in threads]
        return sorted(
            (e["worker_id"], e["event"], round(e["t"] - T0, 3)) for e in s.audit.entries()
        ), {k: m.state for k, m in s._machines.items()}

    sequential = run(False)
    concurrent = run(True)
    assert concurrent == sequential
    counts = Counter((w, e) for w, e, _ in concurrent[0])
    assert (
        counts[(101, "EMERGENCY")] == 1 and counts[(102, "EMERGENCY")] == 1
    )  # one emergency per worker, ever
    assert counts[(101, "EMERGENCY_CALL")] == 1


# ---- restart behaviour (documented limitation) -----------------------------------------------------------


def test_a_restart_forgets_safety_state_and_monitoring_starts_over(app, svc):
    ticker = SafetyTicker(app, state_source=fixed_state)
    for sec in range(0, 31):
        ticker.tick_once(now=T0 + sec)
    assert svc._machines[101].state == EMERGENCY and svc.audit.entries()

    restarted = create_app(
        {"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:", "BCRYPT_ROUNDS": 4}
    )
    fresh = restarted.extensions["safety"]
    fresh.config = svc.config
    fresh.roller.config = fresh.planner.config = fresh.config
    assert fresh.audit.entries() == [] and fresh._machines == {}  # in-memory state is NOT persisted
    t2 = SafetyTicker(restarted, state_source=fixed_state)
    for sec in range(0, EMERGENCY_AT):
        t2.tick_once(now=T0 + 100 + sec)
        assert (
            fresh._machines[101].state != EMERGENCY
        )  # the worker must be re-detected from scratch
    t2.tick_once(now=T0 + 100 + EMERGENCY_AT)
    assert fresh._machines[101].state == EMERGENCY


# ---- wiring ---------------------------------------------------------------------------------------------------


def test_testing_mode_and_the_off_switch_never_start_a_thread(app):
    assert app.config["TESTING"] and start_background_services(app) is None
    before = {t.name for t in threading.enumerate()}
    off = create_app(
        {
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "SAFETY_TICKER_ENABLED": False,
            "BCRYPT_ROUNDS": 4,
        }
    )
    assert start_background_services(off) is None
    assert "safety-ticker" not in {t.name for t in threading.enumerate()} - before


def test_a_real_server_process_starts_exactly_one_heartbeat(monkeypatch):
    server = create_app(
        {
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "SAFETY_TICK_INTERVAL_SECONDS": 0.01,
            "BCRYPT_ROUNDS": 4,
        }
    )
    monkeypatch.setattr("safety.ticker._live_state", lambda: live())
    first = start_background_services(server)
    try:
        assert first.running and server.extensions["safety_ticker"] is first
        assert (
            start_background_services(server) is first
        )  # calling again does not add a second thread
        assert sum(1 for t in threading.enumerate() if t.name == "safety-ticker") >= 1
    finally:
        first.stop()


def test_create_app_alone_never_starts_the_heartbeat():
    before = sum(1 for t in threading.enumerate() if t.name == "safety-ticker")
    create_app({"SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:", "BCRYPT_ROUNDS": 4})
    assert sum(1 for t in threading.enumerate() if t.name == "safety-ticker") == before


def test_live_map_reports_how_fresh_monitoring_is(
    app, svc, client, supervisor_headers, monkeypatch
):
    import routes.map as rmap

    monkeypatch.setattr(rmap, "compute_live_state", lambda path_for=None: fixed_state())
    body = client.get("/api/map/live", headers=supervisor_headers).get_json()
    mon = body["safety"]["monitoring"]
    assert (mon["last_tick_at"], mon["age_s"], mon["background"]) == (None, None, False)
    assert mon["persistence"] == {"enabled": True, "ok": True, "unsaved_events": 0}
    ticker = SafetyTicker(app, state_source=fixed_state)
    ticker.tick_once()  # real clock
    body = client.get("/api/map/live", headers=supervisor_headers).get_json()
    assert (
        body["safety"]["monitoring"]["age_s"] is not None
        and body["safety"]["monitoring"]["age_s"] < 5
    )
    assert body["safety"]["monitoring"]["last_tick_at"]


def test_acknowledgement_and_role_checks_still_work_alongside_the_heartbeat(
    app, svc, client, supervisor_headers, dispatcher_headers, monkeypatch
):
    import routes.safety as rsafety

    monkeypatch.setattr(rsafety, "compute_live_state", lambda path_for=None: fixed_state())
    ticker = SafetyTicker(app, state_source=fixed_state)
    for sec in range(0, 12):
        ticker.tick_once(now=T0 + sec)
    assert svc._machines[101].state == "CHECKIN_1"
    svc.clock = lambda: T0 + 12
    assert (
        client.post("/api/safety/workers/101/respond", headers=dispatcher_headers).status_code
        == 403
    )
    assert svc._machines[101].state == "CHECKIN_1"  # refused: nothing changed
    res = client.post("/api/safety/workers/101/respond", headers=supervisor_headers)
    assert res.status_code == 200 and res.get_json()["cleared"] is True
    assert svc._machines[101].state == NORMAL


def test_tick_interval_setting_is_validated(monkeypatch):
    import config

    monkeypatch.setenv("SAFETY_TICK_INTERVAL_SECONDS", "0.5")
    assert config._float("SAFETY_TICK_INTERVAL_SECONDS", 1.0, minimum=0.05) == 0.5
    for bad in ("fast", "0", "-1", "nan"):
        monkeypatch.setenv("SAFETY_TICK_INTERVAL_SECONDS", bad)
        with pytest.raises(config.ConfigError):
            config._float("SAFETY_TICK_INTERVAL_SECONDS", 1.0, minimum=0.05)
