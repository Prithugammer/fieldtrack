"""Who may change safety state, and the guarantee that GET /api/map/live never does.

Rule under test: every state-changing safety control needs Supervisor or Admin. A Dispatcher can
watch (map, alerts, config, audit log) but not trigger, answer, pause or resolve anything.
"""

import pytest

from models import LocationPing, TimeEntry
from tests.conftest import login
from tests.test_safety import fake_map, fixed, live, quiet_safety, worker  # noqa: F401

CONTROLS = [
    ("accident", {}),
    ("sos", {}),
    ("respond", {}),
    ("break", {"on_break": True}),
    ("resolve", {"outcome": "false_alarm"}),
    ("return-to-duty", {}),
]
BASE = "/api/safety/workers/6"  # fake_map worker 6 is on site (on shift)


def post(client, headers, action, body=None):
    return client.post(f"{BASE}/{action}", json=body or {}, headers=headers)


def snapshot(app):
    """Everything about safety state that a request could change."""
    svc = app.extensions["safety"]
    return (
        svc.audit.entries(),
        {wid: (m.state, m.checkin) for wid, m in svc._machines.items()},
        set(svc._frozen),
        set(svc._incapacitated),
        set(svc._on_break),
    )


@pytest.mark.parametrize("action,body", CONTROLS)
def test_unauthenticated_controls_are_401(client, action, body):
    assert post(client, {}, action, body).status_code == 401


@pytest.mark.parametrize("action,body", CONTROLS)
def test_dispatcher_is_refused_every_control_and_nothing_changes(
    client,
    app,
    fake_map,
    quiet_safety,
    supervisor_headers,
    dispatcher_headers,
    action,
    body,  # noqa: F811
):
    # A real emergency exists, so a 409 "not in an emergency" cannot hide a missing 403.
    assert post(client, supervisor_headers, "sos").status_code == 201
    before = snapshot(app)
    res = post(client, dispatcher_headers, action, body)
    assert res.status_code == 403, (action, res.get_json())
    assert "cannot do this" in res.get_json()["error"]
    assert snapshot(app) == before


def test_dispatcher_cannot_trigger_an_accident_on_a_fresh_system(
    client, app, fake_map, quiet_safety, dispatcher_headers, supervisor_headers  # noqa: F811
):
    res = post(client, dispatcher_headers, "accident")
    assert res.status_code == 403
    assert app.extensions["safety"].audit.entries() == []
    body = client.get("/api/map/live", headers=supervisor_headers).get_json()
    assert all(not w["safety"]["stopped"] for w in body["workers"])


def test_dispatcher_cannot_resolve_an_existing_emergency(
    client, app, fake_map, quiet_safety, supervisor_headers, dispatcher_headers  # noqa: F811
):
    assert post(client, supervisor_headers, "sos").status_code == 201
    res = post(client, dispatcher_headers, "resolve", {"outcome": "false_alarm", "note": "no"})
    assert res.status_code == 403
    state = client.get("/api/map/live", headers=dispatcher_headers).get_json()
    assert next(w for w in state["workers"] if w["id"] == 6)["status"] == "EMERGENCY"
    assert "RESOLVED" not in {e["event"] for e in app.extensions["safety"].audit.entries()}


@pytest.mark.parametrize("email", ["super@test.com", "admin@test.com"])
def test_supervisor_and_admin_can_run_the_whole_flow(
    client, fake_map, quiet_safety, email
):  # noqa: F811
    h = login(client, email)
    assert post(client, h, "sos").status_code == 201
    assert post(client, h, "sos").status_code == 409  # repeated: already an emergency
    assert post(client, h, "return-to-duty").status_code == 409  # not post-incident yet
    real = post(client, h, "resolve", {"outcome": "real_incident", "note": "Minor injury"})
    assert real.status_code == 200
    assert post(client, h, "resolve", {"outcome": "false_alarm"}).status_code == 409  # again
    assert post(client, h, "return-to-duty").status_code == 200
    assert post(client, h, "break", {"on_break": True}).status_code == 200
    assert post(client, h, "break", {"on_break": False}).status_code == 200
    assert post(client, h, "respond").get_json()["cleared"] is False
    assert post(client, h, "accident").status_code == 201
    audit = client.get("/api/safety/audit?worker_id=6", headers=h).get_json()
    role = "Admin" if "admin" in email else "Supervisor"
    resolved = next(e for e in audit if e["event"] == "RESOLVED")
    assert resolved["actor"].endswith(f"({role})")
    assert {"SOS", "RESOLVED", "RETURN_TO_DUTY", "ACCIDENT"} <= {e["event"] for e in audit}


def test_return_to_duty_is_also_restricted(
    client, fake_map, quiet_safety, supervisor_headers, dispatcher_headers  # noqa: F811
):
    post(client, supervisor_headers, "sos")
    post(client, supervisor_headers, "resolve", {"outcome": "real_incident"})
    assert post(client, dispatcher_headers, "return-to-duty").status_code == 403
    assert post(client, supervisor_headers, "return-to-duty").status_code == 200


def test_authorization_is_checked_before_the_body_is_validated(client, dispatcher_headers):
    # A dispatcher gets 403, never a 400 that would reveal how the endpoint validates.
    assert post(client, dispatcher_headers, "resolve", {"outcome": "bogus"}).status_code == 403
    assert post(client, dispatcher_headers, "break", {}).status_code == 403


def test_dispatcher_can_still_watch(
    client, fake_map, quiet_safety, dispatcher_headers
):  # noqa: F811
    for url in ("/api/safety/config", "/api/safety/audit", "/api/map/live", "/api/map/bounds"):
        assert client.get(url, headers=dispatcher_headers).status_code == 200, url
    assert client.post("/api/safety/tick", headers=dispatcher_headers).status_code == 200


def test_a_demoted_user_loses_safety_control_immediately(
    client, app, fake_map, quiet_safety, admin_headers  # noqa: F811
):
    """The role is read from the database, not trusted from a token issued before the change."""
    sup_headers = login(client, "super@test.com")
    assert post(client, sup_headers, "sos").status_code == 201
    from extensions import db
    from models import User

    User.query.filter_by(email="super@test.com").one().role = "Dispatcher"
    db.session.commit()
    assert post(client, sup_headers, "resolve", {"outcome": "false_alarm"}).status_code == 403


# ---- GET /api/map/live is read-only -----------------------------------------------------------


def test_repeated_live_map_polls_change_no_safety_state(
    client, app, fake_map, quiet_safety, supervisor_headers  # noqa: F811
):
    svc = app.extensions["safety"]
    before = snapshot(app)
    db_before = (TimeEntry.query.count(), LocationPing.query.count())
    first = client.get("/api/map/live", headers=supervisor_headers).get_json()
    for _ in range(25):
        assert client.get("/api/map/live", headers=supervisor_headers).status_code == 200
    assert snapshot(app) == before
    assert svc._machines == {} and svc._seen == {} and svc._last_tick is None
    assert (TimeEntry.query.count(), LocationPing.query.count()) == db_before
    # Same response shape as before the change, for every worker, even though no one was ticked.
    assert first["safety"]["alerts"] == [] and first["safety"]["config"]["mode"]
    for w in first["workers"]:
        assert w["safety"]["state"] == "NORMAL" and w["sim_status"] == w["status"]


def test_live_map_does_not_roll_accidents_or_advance_escalation(
    client, app, fake_map, supervisor_headers  # noqa: F811
):
    svc = app.extensions["safety"]
    svc.config = svc.config.with_changes(accident_probability=1)  # every roll is an accident
    svc.roller.config = svc.config
    for _ in range(5):
        body = client.get("/api/map/live", headers=supervisor_headers).get_json()
    assert svc.audit.entries() == [] and not svc._frozen
    assert all(not w["safety"]["stopped"] for w in body["workers"])

    # Only the explicit POST advances time: now the in-transit worker (5) has the accident.
    ticked = client.post("/api/safety/tick", headers=supervisor_headers).get_json()
    assert next(w for w in ticked["workers"] if w["id"] == 5)["safety"]["stopped"] is True
    assert "ACCIDENT" in {e["event"] for e in svc.audit.entries()}


def test_live_map_reports_state_made_by_the_controls(
    client, fake_map, quiet_safety, supervisor_headers  # noqa: F811
):
    post(client, supervisor_headers, "sos")
    for _ in range(3):
        body = client.get("/api/map/live", headers=supervisor_headers).get_json()
    assert [a["worker_id"] for a in body["safety"]["alerts"]] == [6]
    assert next(w for w in body["workers"] if w["id"] == 6)["status"] == "EMERGENCY"


def test_tick_advances_the_escalation_and_get_only_reports_it(
    client, app, quiet_safety, monkeypatch, supervisor_headers  # noqa: F811
):
    """A stationary worker escalates under POST /tick polling, never under GET polling."""
    crew = lambda: live(worker(5, "Ramesh Karki", "On site"))  # noqa: E731
    monkeypatch.setattr("routes.map.compute_live_state", lambda path_for=None: crew())
    monkeypatch.setattr("routes.safety.compute_live_state", lambda path_for=None: crew())
    svc = app.extensions["safety"]
    clock = {"t": 1000.0}
    svc.clock = svc.audit.clock = svc.notifier.clock = lambda: clock["t"]
    svc.config = svc.config.with_changes(
        idle_threshold_seconds=10, checkin_response_window_seconds=5, num_checkins=1
    )
    for m in svc._machines.values():
        m.config = svc.config

    for _ in range(40):  # GET polling alone: time passes, nothing escalates
        clock["t"] += 1
        client.get("/api/map/live", headers=supervisor_headers)
    assert svc.audit.entries() == []

    for _ in range(40):  # POST polling: idle -> check-in -> emergency
        clock["t"] += 1
        state = client.post("/api/safety/tick", headers=supervisor_headers).get_json()
    assert state["safety"]["alerts"][0]["state"] == "EMERGENCY"


def test_tick_requires_a_login_and_validates_route(client, supervisor_headers):
    assert client.post("/api/safety/tick").status_code == 401
    bad = client.post("/api/safety/tick?route=abc", headers=supervisor_headers)
    assert bad.status_code == 400 and bad.get_json()["field"] == "route"
    assert client.get("/api/safety/tick", headers=supervisor_headers).status_code == 405
