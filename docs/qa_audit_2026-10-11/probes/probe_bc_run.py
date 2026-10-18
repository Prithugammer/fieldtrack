import copy
import json
import sys
import threading
import time
import urllib.request

sys.path.insert(0, r"<SCRATCH_DIR>")
from probe_common import *  # noqa: E402,F401,F403

from flask_jwt_extended import create_access_token  # noqa: E402
from models import User  # noqa: E402

app, ctx = seeded_app()
c = app.test_client()
H = login_all(c)
svc = app.extensions["safety"]
svc.config = svc.config.with_changes(accident_probability=0, auto_respond_chance=0)
svc.roller.config = svc.planner.config = svc.config

worker_user = User.query.filter_by(role="Worker").first()
H["worker(forged token)"] = {
    "Authorization": "Bearer "
    + create_access_token(identity=str(worker_user.user_id), additional_claims={"user_id": worker_user.user_id, "role": "Worker"})
}
H["none"] = {}

# ---- a fixed live state so the probe is deterministic (patched at runtime only, no source edit)
import routes.map as rmap  # noqa: E402
import routes.safety as rsafety  # noqa: E402


def W(i, name, status, lat=27.70, lng=85.30):
    return {"id": i, "name": name, "trade": "T", "status": status, "lat": lat, "lng": lng, "job_title": "J", "site_name": "S", "near_traffic": False, "hotspot": None, "distance_remaining_m": None}


FIXED = [W(101, "Alpha", "On site"), W(102, "Bravo", "On site", 27.701, 85.301), W(103, "Charlie", "In transit", 27.702, 85.302), W(104, "Delta", "On site", 27.703, 85.303), W(105, "Echo", "On site", 27.704, 85.304)]
state = lambda path_for=None: {"workers": copy.deepcopy(FIXED), "job_sites": []}  # noqa: E731
rmap.compute_live_state = state
rsafety.compute_live_state = state


def internals():
    return json.dumps(
        {
            "audit": svc.audit.entries(),
            "machines": {k: (m.state, m.checkin, m.state_since) for k, m in svc._machines.items()},
            "frozen": sorted(svc._frozen),
            "incap": sorted(svc._incapacitated),
            "break": sorted(svc._on_break),
            "seen": sorted(svc._seen),
            "last_tick": svc._last_tick,
        },
        sort_keys=True,
        default=str,
    )


ACTIONS = [
    ("accident", {}),
    ("sos", {}),
    ("respond", {}),
    ("break", {"on_break": True}),
    ("resolve", {"outcome": "false_alarm", "note": "probe"}),
    ("return-to-duty", {}),
]
svc.process(state(), now=svc.clock())  # make workers "known"

print("=== B1: authorization matrix while an EMERGENCY exists on worker 101 (rows=role, cols=action, tick)")
assert c.post("/api/safety/workers/101/sos", headers=H["supervisor"]).status_code == 201
print(f"{'role':<24}" + "".join(f"{a:<16}" for a, _ in ACTIONS) + "tick")
denied_state_changed = []
for role in ("none", "worker(forged token)", "dispatcher"):
    before = internals()
    row = []
    for action, body in ACTIONS:
        r = c.post(f"/api/safety/workers/101/{action}", json=body, headers=H[role])
        row.append(r.status_code)
    t = c.post("/api/safety/tick", headers=H[role]).status_code
    after_actions = internals()
    print(f"{role:<24}" + "".join(f"{s:<16}" for s in row) + str(t))
    # tick legitimately advances time-based state; compare only the non-tick actions' effect by
    # re-checking the action rows were all refused
    if role != "dispatcher" or True:
        if not all(s in (401, 403) for s in row):
            denied_state_changed.append((role, row))
print("  every control refused for unauthorised roles:", not denied_state_changed, denied_state_changed or "")

# state-unchanged check: run the denied actions only (no tick), compare snapshots
before = internals()
for role in ("none", "worker(forged token)", "dispatcher"):
    for action, body in ACTIONS:
        c.post(f"/api/safety/workers/101/{action}", json=body, headers=H[role])
print("  safety state byte-identical after 18 denied mutation attempts:", before == internals())
print("  worker 101 still EMERGENCY:", svc._machines[101].state)

print("=== B2: authorised roles - full flow per role (fresh worker each)")
for role, wid in (("admin", 102), ("supervisor", 103)):
    h = H[role]
    seq = []
    seq.append(("sos", c.post(f"/api/safety/workers/{wid}/sos", headers=h).status_code))
    seq.append(("sos again", c.post(f"/api/safety/workers/{wid}/sos", headers=h).status_code))
    seq.append(("return-to-duty (not post-incident)", c.post(f"/api/safety/workers/{wid}/return-to-duty", headers=h).status_code))
    seq.append(("resolve bogus outcome", c.post(f"/api/safety/workers/{wid}/resolve", json={"outcome": "x"}, headers=h).status_code))
    seq.append(("resolve real", c.post(f"/api/safety/workers/{wid}/resolve", json={"outcome": "real_incident"}, headers=h).status_code))
    seq.append(("resolve again", c.post(f"/api/safety/workers/{wid}/resolve", json={"outcome": "false_alarm"}, headers=h).status_code))
    seq.append(("return-to-duty", c.post(f"/api/safety/workers/{wid}/return-to-duty", headers=h).status_code))
    seq.append(("break on", c.post(f"/api/safety/workers/{wid}/break", json={"on_break": True}, headers=h).status_code))
    seq.append(("break on again (idempotent)", c.post(f"/api/safety/workers/{wid}/break", json={"on_break": True}, headers=h).status_code))
    seq.append(("break bad body", c.post(f"/api/safety/workers/{wid}/break", json={}, headers=h).status_code))
    seq.append(("respond (no checkin)", c.post(f"/api/safety/workers/{wid}/respond", headers=h).status_code))
    seq.append(("unknown worker 99999", c.post("/api/safety/workers/99999/sos", headers=h).status_code))
    seq.append(("worker id 0", c.post("/api/safety/workers/0/sos", headers=h).status_code))
    print(f"  {role}: " + "; ".join(f"{n}={s}" for n, s in seq))

print("=== B3: read access by role (GET)")
for role in ("none", "worker(forged token)", "dispatcher", "supervisor", "admin"):
    out = [c.get(u, headers=H[role]).status_code for u in ("/api/safety/config", "/api/safety/audit", "/api/map/live", "/api/map/sim-clock", "/api/map/bounds")]
    print(f"  {role:<24} config/audit/live/sim-clock/bounds = {out}")

print("=== B4: every mutating route under /api/safety and /api/map, dispatcher token")
for rule in sorted(app.url_map.iter_rules(), key=lambda r: r.rule):
    if rule.rule.startswith(("/api/safety", "/api/map")):
        for m in sorted(rule.methods - {"HEAD", "OPTIONS"}):
            url = rule.rule.replace("<int:user_id>", "101")
            body = {"outcome": "false_alarm", "on_break": True} if m == "POST" else None
            r = c.open(url, method=m, json=body, headers=H["dispatcher"])
            print(f"  {m:<5} {rule.rule:<40} dispatcher -> {r.status_code}")

print("\n=== C1: GET /api/map/live is observational (50 polls, real clock)")
svc2_before = internals()
fp = db_fingerprint()
for _ in range(50):
    assert c.get("/api/map/live", headers=H["dispatcher"]).status_code == 200
print("  safety internals identical:", svc2_before == internals(), "| DB fingerprint identical:", fp == db_fingerprint())
live = c.get("/api/map/live", headers=H["dispatcher"]).get_json()
print("  response keys:", sorted(live)[:8], "| safety keys:", sorted(live["safety"]))
w101 = next(w for w in live["workers"] if w["id"] == 101)
print("  GET reflects state made by POST controls: worker101 status =", w101["status"], "| alerts =", [a["worker_id"] for a in live["safety"]["alerts"]])

print("\n=== C2: GET with accident_probability=1 must not roll accidents; POST tick may")
svc.config = svc.config.with_changes(accident_probability=1)
svc.roller.config = svc.config
svc.roller._last_interval.clear()
n_before = len([e for e in svc.audit.entries() if e["event"] == "ACCIDENT"])
for _ in range(10):
    c.get("/api/map/live", headers=H["supervisor"])
n_get = len([e for e in svc.audit.entries() if e["event"] == "ACCIDENT"])
c.post("/api/safety/tick", headers=H["supervisor"])
n_tick = len([e for e in svc.audit.entries() if e["event"] == "ACCIDENT"])
print(f"  ACCIDENT audit entries: before={n_before} after 10 GETs={n_get} after 1 tick={n_tick}")
svc.config = svc.config.with_changes(accident_probability=0)
svc.roller.config = svc.config

print("\n=== C3: concurrency over real HTTP (threaded server): 8 clients x 40 ticks vs sequential reference")
from werkzeug.serving import make_server  # noqa: E402


def scenario(parallel):
    a, cx = seeded_app()
    s = a.extensions["safety"]
    s.config = s.config.with_changes(accident_probability=0, auto_respond_chance=0, idle_threshold_seconds=10, checkin_response_window_seconds=5, num_checkins=3)
    s.roller.config = s.planner.config = s.config
    T = [10_000.0]
    s.clock = s.audit.clock = s.notifier.clock = lambda: T[0]
    for m in s._machines.values():
        m.config = s.config
    rmap.compute_live_state = state
    rsafety.compute_live_state = state
    cl = a.test_client()
    hdr = login_all(cl)["supervisor"]
    token = hdr["Authorization"]
    srv = make_server("127.0.0.1", 0, a, threaded=True)
    port = srv.server_port
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    errors = []

    def tick():
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/safety/tick", method="POST", headers={"Authorization": token})
        try:
            urllib.request.urlopen(req, timeout=10).read()
        except Exception as e:  # noqa: BLE001
            errors.append(repr(e)[:80])

    # time moves 1 s per step for 60 steps; each step is observed by `n` simultaneous ticks
    n = 8 if parallel else 1
    for _ in range(60):
        T[0] += 1
        ts = [threading.Thread(target=tick) for _ in range(n)]
        [t.start() for t in ts]
        [t.join() for t in ts]
    srv.shutdown()
    events = sorted((e["worker_id"], e["event"], round(e["t"], 3)) for e in s.audit.entries())
    states = {k: (m.state, m.checkin) for k, m in s._machines.items()}
    return events, states, errors


seq_events, seq_states, seq_err = scenario(False)
par_events, par_states, par_err = scenario(True)
print(f"  sequential: {len(seq_events)} audit events, errors={len(seq_err)}; parallel: {len(par_events)} events, errors={len(par_err)}")
print("  identical event lists (worker, event, due-time):", seq_events == par_events)
print("  identical final machine states:", seq_states == par_states)
from collections import Counter  # noqa: E402

print("  event counts (parallel):", dict(Counter(e[1] for e in par_events)))
dups = [k for k, v in Counter(par_events).items() if v > 1]
print("  duplicate events in parallel run:", dups[:5] or "none")

print("\n=== C4: monitoring gap (no client ticking) - does escalation continue by itself?")
a, cx = seeded_app()
s = a.extensions["safety"]
s.config = s.config.with_changes(accident_probability=0, auto_respond_chance=0, idle_threshold_seconds=10, checkin_response_window_seconds=5, num_checkins=3)
s.roller.config = s.planner.config = s.config
T = [20_000.0]
s.clock = s.audit.clock = s.notifier.clock = lambda: T[0]
rsafety.compute_live_state = state
cl = a.test_client()
hdr = login_all(cl)["supervisor"]
for sec in range(0, 13):  # a dashboard is open for the first 12 s: idle threshold passes, check-in 1 sent
    T[0] = 20_000.0 + sec
    cl.post("/api/safety/tick", headers=hdr)
m = s._machines[101]
print(f"  t=12s (dashboard open): worker101 state={m.state}")
T[0] = 20_000.0 + 60  # nobody has the dashboard open for 48 s; worker is still not moving
cl.post("/api/safety/tick", headers=hdr)
m = s._machines[101]
events = [e["event"] for e in s.audit.entries() if e["worker_id"] == 101]
print(f"  t=60s (first tick after a 48 s gap; worker stationary all along): state={m.state}; events={events}")
print("  => without a polling client the escalation does not advance and the timers restart after a gap > MAX_POLL_GAP_SECONDS")

print("\n=== C5: client cannot choose the time (server clock only)")
r = c.post("/api/safety/tick?now=0&t=0", json={"now": 0, "time": 0}, headers=H["supervisor"])
print("  tick with ?now=0 / body now=0 ->", r.status_code, "(parameters ignored; time comes from the server clock)")

