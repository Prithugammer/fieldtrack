"""Safety / emergency escalation: the state machine, the random behaviour and the API.

All times are explicit numbers (seconds), so nothing here sleeps or depends on the wall clock.
The demo preset is used throughout: 15 s idle threshold, three 5 s check-in windows.
"""

import pytest

from safety import BreakZone, MockNotifier, SafetyConfig, SafetyMachine, SafetyService
from safety.audit import AuditLog
from safety.behaviour import AccidentRoller, ReplyPlanner
from safety.machine import EMERGENCY, NORMAL, POST_INCIDENT, WorkerRef

SPOT = (27.70, 85.30)  # open ground, nowhere near a break zone
REST_AREA = BreakZone.circle("Test canteen", 27.71, 85.31, 100)
IN_REST_AREA = (27.71, 85.31)
CFG = SafetyConfig.from_mode("demo", seed=7, break_zones=(REST_AREA,))
IDLE, WINDOW = CFG.idle_threshold_seconds, CFG.checkin_response_window_seconds


def make_machine(config=CFG):
    audit = AuditLog(clock=lambda: 0)
    notifier = MockNotifier(config, clock=lambda: 0)
    return SafetyMachine(WorkerRef(1, "Bishal Neupane"), config, notifier, audit), notifier, audit


def events(audit):
    return [e["event"] for e in audit.entries()]


def watch(m, *times, pos=SPOT, on_shift=True, on_break=False):
    for t in times:
        m.observe(t, pos, on_shift, on_break)


# ---------- escalation ----------


def test_idle_worker_escalates_to_emergency_on_schedule():
    m, notifier, audit = make_machine()
    watch(m, 0, IDLE - 1)
    assert m.state == NORMAL
    watch(m, IDLE)
    assert m.state == "CHECKIN_1"
    assert [(n["channel"], n["level"]) for n in notifier.feed] == [
        ("worker", "info"),
        ("supervisor", "warning"),
    ]
    watch(m, IDLE + WINDOW - 1)
    assert m.state == "CHECKIN_1"
    watch(m, IDLE + WINDOW)
    assert m.state == "CHECKIN_2"
    watch(m, IDLE + 2 * WINDOW)
    assert m.state == "CHECKIN_3"
    assert len([n for n in notifier.feed if n["channel"] == "worker"]) == 3
    watch(m, IDLE + 3 * WINDOW)
    assert m.state == EMERGENCY
    channels = [(n["channel"], n["level"]) for n in notifier.feed]
    assert channels[-2:] == [("supervisor", "critical"), ("emergency_services", "critical")]
    assert "MOCK" in notifier.feed[-1]["text"]
    assert events(audit) == [
        "IDLE_DETECTED",
        "CHECKIN_SENT",
        "SUPERVISOR_ALERT",
        "CHECKIN_UNANSWERED",
        "CHECKIN_SENT",
        "CHECKIN_UNANSWERED",
        "CHECKIN_SENT",
        "CHECKIN_UNANSWERED",
        "EMERGENCY",
        "SUPERVISOR_ALERT",
        "EMERGENCY_CALL",
    ]


def test_emergency_is_locked_and_the_location_stays_tracked():
    m, notifier, _ = make_machine()
    watch(m, 0, IDLE + 3 * WINDOW)
    assert m.state == EMERGENCY
    calls = len(notifier.feed)
    m.observe(500, (27.705, 85.305), True)  # worker moves: still locked
    assert m.state == EMERGENCY and m.position == (27.705, 85.305)
    assert m.respond(501) is False  # worker says OK: still locked
    assert m.state == EMERGENCY
    watch(m, 100000)
    assert len(notifier.feed) == calls  # the call is placed once


def test_long_gap_between_polls_still_records_the_due_times():
    m, _, audit = make_machine()
    watch(m, 0)
    watch(m, 1000)  # nobody polled for ages
    assert m.state == EMERGENCY
    assert m.emergency_at == IDLE + 3 * WINDOW
    assert audit.entries()[0]["t"] == IDLE  # IDLE_DETECTED stamped when it was due


def test_ok_reply_returns_to_normal_and_restarts_the_idle_timer():
    m, _, audit = make_machine()
    watch(m, 0, IDLE + WINDOW)
    assert m.state == "CHECKIN_2"
    assert m.respond(IDLE + WINDOW + 1) is True
    assert m.state == NORMAL
    assert "CHECKIN_RESPONSE" in events(audit)
    watch(m, IDLE + WINDOW + 1 + IDLE - 1)  # not yet idle again
    assert m.state == NORMAL
    watch(m, IDLE + WINDOW + 1 + IDLE)
    assert m.state == "CHECKIN_1"


def test_moving_returns_to_normal_and_logs_it_as_cleared():
    m, _, audit = make_machine()
    watch(m, 0, IDLE + 2 * WINDOW)
    assert m.state == "CHECKIN_3"
    m.observe(IDLE + 2 * WINDOW + 1, (SPOT[0] + 0.001, SPOT[1]), True)  # ~110 m
    assert m.state == NORMAL
    cleared = [e for e in audit.entries() if e["event"] == "CHECKIN_CLEARED"]
    assert len(cleared) == 1 and "moving" in cleared[0]["message"]


def test_gps_jitter_within_tolerance_is_not_movement():
    m, _, _ = make_machine()
    m.observe(0, SPOT, True)
    m.observe(IDLE, (SPOT[0] + 0.00002, SPOT[1]), True)  # ~2 m
    assert m.state == "CHECKIN_1"


# ---------- who is never flagged ----------


@pytest.mark.parametrize(
    "kwargs",
    [
        {"on_shift": False},
        {"on_break": True},
        {"pos": IN_REST_AREA},
    ],
    ids=["off shift", "on break", "in break zone"],
)
def test_no_escalation_when_off_shift_on_break_or_in_a_break_zone(kwargs):
    m, notifier, audit = make_machine()
    watch(m, 0, IDLE, IDLE * 10, **kwargs)
    assert m.state == NORMAL
    assert not notifier.feed and not audit.entries()


def test_entering_a_break_zone_mid_checkin_clears_it():
    m, _, audit = make_machine()
    watch(m, 0, IDLE)
    assert m.state == "CHECKIN_1"
    m.observe(IDLE + 1, IN_REST_AREA, True)
    assert m.state == NORMAL
    assert (
        "Test canteen"
        in [e for e in audit.entries() if e["event"] == "CHECKIN_CLEARED"][0]["message"]
    )


def test_rectangular_break_zone():
    zone = BreakZone.rect("Yard", 27.0, 85.0, 27.1, 85.1)
    assert zone.contains(27.05, 85.05) and not zone.contains(27.2, 85.05)


# ---------- SOS and supervisor resolution ----------


def test_sos_skips_straight_to_emergency():
    m, notifier, audit = make_machine()
    assert m.sos(5, SPOT) is True
    assert m.state == EMERGENCY and m.trigger == "sos"
    assert events(audit)[:2] == ["SOS", "EMERGENCY"]
    assert notifier.feed[-1]["channel"] == "emergency_services"
    assert m.sos(6, SPOT) is False


def emergency_machine():
    m, notifier, audit = make_machine()
    watch(m, 0, IDLE + 3 * WINDOW)
    return m, audit


def test_false_alarm_resolution_returns_to_normal_with_the_note():
    m, audit = emergency_machine()
    assert m.resolve(100, "false_alarm", "Was eating lunch", by="Greg") == NORMAL
    entry = audit.entries()[-1]
    assert entry["event"] == "RESOLVED" and "false alarm" in entry["message"]
    assert "Was eating lunch" in entry["message"] and entry["actor"] == "Greg"
    watch(m, 101, 100 + IDLE - 1)
    assert m.state == NORMAL  # a fresh idle timer, counted from the resolution


def test_real_incident_resolution_is_post_incident_until_returned_to_duty():
    m, audit = emergency_machine()
    assert m.resolve(100, "real_incident") == POST_INCIDENT
    watch(m, 101, 100000)
    assert m.state == POST_INCIDENT  # attended to: not re-escalated
    m.return_to_duty(200, by="Greg")
    assert m.state == NORMAL and "RETURN_TO_DUTY" in events(audit)


def test_resolution_is_refused_unless_in_emergency_and_outcome_is_valid():
    m, _, _ = make_machine()
    with pytest.raises(ValueError):
        m.resolve(1, "false_alarm")
    m2, _ = emergency_machine()
    with pytest.raises(ValueError):
        m2.resolve(1, "whatever")
    with pytest.raises(ValueError):
        m2.return_to_duty(1)


# ---------- accidents (seeded randomness) ----------


def accident_sequence(seed, workers=range(1, 6), intervals=range(200)):
    cfg = SafetyConfig.from_mode("demo", accident_probability=0.05)
    roller = AccidentRoller(cfg, seed)
    step = cfg.accident_roll_interval_seconds
    return [roller.roll_if_due(w, i * step) for i in intervals for w in workers]


def test_accident_rolls_are_reproducible_for_a_seed():
    assert accident_sequence(42) == accident_sequence(42)
    assert accident_sequence(42) != accident_sequence(43)


def test_accident_rate_follows_the_configured_probability():
    rolls = accident_sequence(42, workers=range(1, 51), intervals=range(400))
    assert 0.03 < sum(rolls) / len(rolls) < 0.07  # 5% over 20 000 rolls
    for p, expected in ((0, False), (1, True)):
        roller = AccidentRoller(SafetyConfig.from_mode("demo", accident_probability=p), 1)
        assert all(roller.roll_if_due(w, 0) is expected for w in range(50))


def test_a_worker_is_rolled_once_per_interval_not_every_tick():
    cfg = SafetyConfig.from_mode("demo", accident_probability=0.01)
    roller = AccidentRoller(cfg, 3)
    step = cfg.accident_roll_interval_seconds
    assert roller.roll_if_due(1, 10) is not None
    assert [roller.roll_if_due(1, 10 + t) for t in range(1, 50)] == [None] * 49
    assert roller.roll_if_due(1, step + 10) is not None  # next interval: rolled again
    assert cfg.accident_probability == 0.01 and step == 400  # one simulated hour


def test_auto_reply_planner_respects_chance_and_the_window():
    never = ReplyPlanner(SafetyConfig.from_mode("demo", auto_respond_chance=0), 1)
    always = ReplyPlanner(SafetyConfig.from_mode("demo", auto_respond_chance=1), 1)
    assert all(never.plan(w, 1, 100) is None for w in range(20))
    plans = [always.plan(w, 1, 100) for w in range(20)]
    assert all(100 < p < 100 + WINDOW for p in plans)
    assert plans == [always.plan(w, 1, 100) for w in range(20)]


# ---------- the service on a fake Live Map state ----------


def worker(wid, name, status="On site", lat=27.70, lng=85.30):
    return {
        "id": wid,
        "name": name,
        "trade": "Laborer",
        "status": status,
        "lat": lat,
        "lng": lng,
        "job_title": "Job",
        "site_name": "Test site",
        "near_traffic": False,
        "hotspot": None,
        "distance_remaining_m": None,
    }


def live(*workers):
    return {"workers": list(workers), "job_sites": []}


def make_service(**changes):
    cfg = SafetyConfig.from_mode("demo", seed=11, break_zones=(), accident_probability=0, **changes)
    return SafetyService(cfg, clock=lambda: 0)


def fixed(*workers):
    """A Live Map source that reports these workers afresh on every poll (process() edits them)."""
    return lambda: live(*[dict(w) for w in workers])


def run(service, state_fn, start, stop):
    """Poll once a second, like the dashboard does."""
    state = None
    for t in range(start, stop + 1):
        state = service.process(state_fn(), now=t)
    return state


def by_id(state, wid):
    return next(w for w in state["workers"] if w["id"] == wid)


def test_accident_stops_the_worker_and_escalates_to_emergency_without_a_reply():
    svc = make_service(auto_respond_chance=1)  # would reply, but an accident victim cannot
    crew = fixed(
        worker(1, "Ana", "In transit", 27.700, 85.300),
        worker(2, "Bo", "On site", 27.701, 85.301),
        worker(3, "Cy", "On site", 27.760, 85.360),
    )
    run(svc, crew, 0, 2)
    svc.trigger_accident(1, actor="Greg", now=3)
    state = run(svc, crew, 3, 3 + 14)
    assert by_id(state, 1)["safety"]["incapacitated"] and by_id(state, 1)["status"] == "Stopped"
    state = run(svc, crew, 18, 3 + IDLE + 3 * WINDOW)
    victim = by_id(state, 1)
    assert victim["status"] == "EMERGENCY" and victim["safety"]["state"] == EMERGENCY
    assert (victim["lat"], victim["lng"]) == (27.700, 85.300)  # still shown, where it happened
    alert = state["safety"]["alerts"][0]
    assert alert["level"] == "critical" and alert["worker_name"] == "Ana"
    assert alert["location"]["label"].startswith("On the road to Test site")
    assert alert["nearest_coworker"]["name"] == "Bo"  # closer than Cy
    assert any(e["event"] == "ACCIDENT" for e in svc.audit_entries())
    with pytest.raises(Exception, match="already stopped"):
        svc.trigger_accident(1, now=60)


def test_fine_but_idle_worker_replies_and_the_false_alarm_clears():
    svc = make_service(auto_respond_chance=1)
    crew = fixed(worker(1, "Ana"))
    state = run(svc, crew, 0, 200)
    assert by_id(state, 1)["status"] == "On site"
    events_seen = [e["event"] for e in svc.audit_entries()]
    assert "CHECKIN_RESPONSE" in events_seen and "EMERGENCY" not in events_seen


def test_idle_worker_who_never_replies_reaches_emergency_and_supervisor_resolves():
    svc = make_service(auto_respond_chance=0)
    crew = fixed(worker(1, "Ana"))
    state = run(svc, crew, 0, IDLE + 3 * WINDOW)
    assert by_id(state, 1)["status"] == "EMERGENCY"
    svc.resolve(1, "false_alarm", "Phone was off", actor="Greg", now=40)
    state = run(svc, crew, 40, 41)
    assert by_id(state, 1)["status"] == "On site" and not state["safety"]["alerts"]


def test_sos_freezes_in_place_and_real_incident_keeps_the_marker_flagged():
    svc = make_service()
    crew = fixed(worker(1, "Ana", "In transit"), worker(2, "Bo"))
    run(svc, crew, 0, 2)
    svc.sos(1, actor="Greg", now=3)
    state = run(svc, crew, 3, 4)
    assert by_id(state, 1)["status"] == "EMERGENCY"
    svc.resolve(1, "real_incident", "Ambulance attended", now=5)
    state = run(svc, crew, 5, 6)
    assert by_id(state, 1)["status"] == "Post-incident"
    assert state["safety"]["alerts"][0]["level"] == "info"
    svc.return_to_duty(1, now=7)
    state = run(svc, crew, 7, 8)
    assert by_id(state, 1)["status"] == "In transit" and not state["safety"]["alerts"]


def test_break_flag_suppresses_idle_detection():
    svc = make_service(auto_respond_chance=0)
    crew = fixed(worker(1, "Ana"))
    run(svc, crew, 0, 1)
    svc.set_break(1, True, now=1)
    state = run(svc, crew, 2, 500)
    assert by_id(state, 1)["safety"]["on_break"] and not state["safety"]["alerts"]


def test_off_shift_workers_are_never_flagged():
    svc = make_service(auto_respond_chance=0)
    crew = fixed(worker(1, "Ana", "Off duty"), worker(2, "Bo", "Not started", None, None))
    state = run(svc, crew, 0, 500)
    assert not state["safety"]["alerts"]


def test_a_pause_in_polling_restarts_the_timers_instead_of_raising_alarms():
    svc = make_service(auto_respond_chance=0)
    crew = fixed(worker(1, "Ana"))
    run(svc, crew, 0, IDLE + 1)  # check-in 1 is open
    state = svc.process(crew(), now=5000)  # dashboard was closed for a long time
    assert not state["safety"]["alerts"]
    assert any("paused" in e["message"] for e in svc.audit_entries())


def test_state_and_status_of_unaffected_fields_pass_through():
    svc = make_service()
    state = svc.process(live(worker(1, "Ana", "In transit")), now=0)
    w = by_id(state, 1)
    assert w["status"] == "In transit" and w["sim_status"] == "In transit"
    assert state["safety"]["config"]["mode"] == "demo" and "privacy_note" in state["safety"]


# ---------- config ----------


def test_one_setting_switches_between_the_real_and_demo_presets():
    real = SafetyConfig.from_env({"SAFETY_MODE": "real"})
    demo = SafetyConfig.from_env({"SAFETY_MODE": "demo", "SAFETY_SEED": "5"})
    assert (real.idle_threshold_seconds, real.checkin_response_window_seconds) == (600, 120)
    assert (demo.idle_threshold_seconds, demo.checkin_response_window_seconds) == (15, 5)
    assert demo.seed == 5 and real.num_checkins == 3 and real.accident_probability == 0.01
    assert SafetyConfig.from_env({}).mode == "real"
    assert SafetyConfig.from_env({"SAFETY_AUTO_RESPOND_CHANCE": "0.5"}).auto_respond_chance == 0.5
    with pytest.raises(ValueError):
        SafetyConfig.from_env({"SAFETY_MODE": "nope"})


# ---------- API ----------


@pytest.fixture
def fake_map(monkeypatch):
    """Pin the Live Map to a known state (the real one depends on the wall clock)."""
    state = fixed(
        worker(5, "Ramesh Karki", "In transit", 27.700, 85.300),
        worker(6, "Bishal Neupane", "On site", 27.701, 85.301),
    )
    monkeypatch.setattr("routes.map.compute_live_state", lambda path_for=None: state())
    monkeypatch.setattr("routes.safety.compute_live_state", lambda path_for=None: state())


@pytest.fixture
def quiet_safety(app):
    """No random accidents or auto-replies, so API tests are deterministic."""
    svc = app.extensions["safety"]
    svc.config = svc.config.with_changes(accident_probability=0, auto_respond_chance=0)
    svc.roller.config = svc.planner.config = svc.config
    return svc


def test_safety_routes_require_a_staff_login(client):
    assert client.post("/api/safety/workers/5/accident").status_code == 401
    assert client.get("/api/safety/audit").status_code == 401


def test_live_map_response_carries_safety_info(client, supervisor_headers, fake_map):
    body = client.get("/api/map/live", headers=supervisor_headers).get_json()
    assert body["safety"]["config"]["mode"] in ("real", "demo")
    assert body["workers"][0]["safety"]["state"] == NORMAL and body["safety"]["alerts"] == []


def test_trigger_accident_then_resolve_over_http(
    client, supervisor_headers, fake_map, quiet_safety
):
    h = supervisor_headers
    assert client.post("/api/safety/workers/5/accident", headers=h).status_code == 201
    assert client.post("/api/safety/workers/5/accident", headers=h).status_code == 409
    assert client.post("/api/safety/workers/99/accident", headers=h).status_code == 404
    resolve = "/api/safety/workers/5/resolve"
    # not an emergency yet: the idle threshold has not passed
    early = client.post(resolve, headers=h, json={"outcome": "false_alarm"})
    assert early.status_code == 409

    # Let the escalation run its course (the service takes explicit timestamps).
    cfg = quiet_safety.config
    t0 = quiet_safety.clock()
    done = t0 + cfg.idle_threshold_seconds + cfg.num_checkins * cfg.checkin_response_window_seconds
    crew = live(worker(5, "Ramesh Karki", "In transit"), worker(6, "Bishal Neupane"))
    for t in range(int(t0) + 1, int(done) + 3):  # polled every second, as the dashboard does
        state = quiet_safety.process(crew, now=t)
    assert state["safety"]["alerts"][0]["state"] == EMERGENCY

    assert client.post(resolve, headers=h, json={}).get_json()["field"] == "outcome"
    bad = client.post(resolve, headers=h, json={"outcome": "x"})
    assert bad.status_code == 400 and bad.get_json()["field"] == "outcome"
    ok = client.post(resolve, headers=h, json={"outcome": "false_alarm", "note": "Tied a bootlace"})
    assert ok.status_code == 200
    log = client.get("/api/safety/audit?worker_id=5", headers=h).get_json()
    assert log[-1]["event"] == "RESOLVED" and "Tied a bootlace" in log[-1]["message"]
    assert log[-1]["actor"] == "Test Supervisor (Supervisor)"


def test_sos_respond_break_and_audit_export(client, supervisor_headers, fake_map, quiet_safety):
    h = supervisor_headers
    assert client.post("/api/safety/workers/6/sos", headers=h).status_code == 201
    assert client.post("/api/safety/workers/6/sos", headers=h).status_code == 409
    assert client.post("/api/safety/workers/5/respond", headers=h).get_json()["cleared"] is False
    res = client.post("/api/safety/workers/5/break", headers=h, json={"on_break": True})
    assert res.status_code == 200
    body = client.get("/api/map/live", headers=h).get_json()
    sos_worker = next(w for w in body["workers"] if w["id"] == 6)
    assert sos_worker["status"] == "EMERGENCY"

    log = client.get("/api/safety/audit", headers=h).get_json()
    kinds = {e["event"] for e in log}
    assert {"SOS", "EMERGENCY", "EMERGENCY_CALL", "BREAK_STARTED"} <= kinds
    assert all(e["time"] and e["worker_name"] for e in log)
    csv_res = client.get("/api/safety/audit?format=csv", headers=h)
    assert csv_res.mimetype == "text/csv" and csv_res.get_data(as_text=True).startswith("id,time")
    assert client.get("/api/safety/audit?worker_id=5", headers=h).get_json()[0]["worker_id"] == 5
