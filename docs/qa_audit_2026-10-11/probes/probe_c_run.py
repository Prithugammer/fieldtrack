import copy
import logging
import os
import sys
import threading
import urllib.request
from collections import Counter

sys.path.insert(0, r"<SCRATCH_DIR>")
from probe_common import *  # noqa: E402,F401,F403

import routes.map as rmap  # noqa: E402
import routes.safety as rsafety  # noqa: E402
from werkzeug.serving import make_server  # noqa: E402

logging.getLogger("werkzeug").setLevel(logging.ERROR)
logging.getLogger("fieldtrack.safety").setLevel(logging.ERROR)
SCR = r"<SCRATCH_DIR>"


def W(i, name, status, lat=27.70, lng=85.30):
    return {"id": i, "name": name, "trade": "T", "status": status, "lat": lat, "lng": lng, "job_title": "J", "site_name": "S", "near_traffic": False, "hotspot": None, "distance_remaining_m": None}


FIXED = [W(101, "Alpha", "On site"), W(102, "Bravo", "In transit", 27.701, 85.301), W(103, "Charlie", "On site", 27.702, 85.302)]
state = lambda path_for=None: {"workers": copy.deepcopy(FIXED), "job_sites": []}  # noqa: E731
rmap.compute_live_state = state
rsafety.compute_live_state = state


def file_app(name):
    path = os.path.join(SCR, name)
    if os.path.exists(path):
        os.unlink(path)
    return seeded_app(SQLALCHEMY_DATABASE_URI="sqlite:///" + path.replace("\\", "/"))


def fast(s, **kw):
    s.config = s.config.with_changes(accident_probability=0, auto_respond_chance=0, **kw)
    s.roller.config = s.planner.config = s.config
    for m in s._machines.values():
        m.config = s.config


print("=== C2: GET with accident_probability=1 must not roll accidents; POST tick does")
a, _ctx = file_app("c2.db")
s = a.extensions["safety"]
fast(s)
s.config = s.config.with_changes(accident_probability=1)
s.roller.config = s.config
cl = a.test_client()
hdr = login_all(cl)["supervisor"]
count = lambda: len([e for e in s.audit.entries() if e["event"] == "ACCIDENT"])  # noqa: E731
for _ in range(10):
    cl.get("/api/map/live", headers=hdr)
g = count()
cl.post("/api/safety/tick", headers=hdr)
t = count()
print(f"  ACCIDENT audit entries after 10 GETs = {g}; after 1 POST tick = {t} (the in-transit worker rolled an accident)")

print("\n=== C3: concurrency over a real threaded HTTP server, file-backed SQLite")


def scenario(parallel, tag):
    a, _c = file_app(f"c3_{tag}.db")
    s = a.extensions["safety"]
    fast(s, idle_threshold_seconds=10, checkin_response_window_seconds=5, num_checkins=3)
    T = [10_000.0]
    s.clock = s.audit.clock = s.notifier.clock = lambda: T[0]
    cl = a.test_client()
    token = login_all(cl)["supervisor"]["Authorization"]
    srv = make_server("127.0.0.1", 0, a, threaded=True)
    port = srv.server_port
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    errors = []
    statuses = Counter()

    def tick():
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/safety/tick", method="POST", headers={"Authorization": token})
        try:
            statuses[urllib.request.urlopen(req, timeout=20).status] += 1
        except Exception as e:  # noqa: BLE001
            errors.append(repr(e)[:90])

    n = 8 if parallel else 1
    for _ in range(60):
        T[0] += 1
        ts = [threading.Thread(target=tick) for _ in range(n)]
        [x.start() for x in ts]
        [x.join() for x in ts]
    srv.shutdown()
    events = sorted((e["worker_id"], e["event"], round(e["t"], 3)) for e in s.audit.entries())
    states = {k: (m.state, m.checkin) for k, m in s._machines.items()}
    return events, states, errors, dict(statuses)


seq = scenario(False, "seq")
par = scenario(True, "par")
print(f"  sequential: {len(seq[0])} audit events, request statuses={seq[3]}, errors={len(seq[2])}")
print(f"  parallel (8 simultaneous ticks per simulated second, 480 requests): {len(par[0])} events, statuses={par[3]}, errors={len(par[2])} {par[2][:2]}")
print("  identical event lists (worker, event, due-time):", seq[0] == par[0])
print("  identical final machine states:", seq[1] == par[1])
print("  event counts (parallel):", dict(Counter(e[1] for e in par[0])))
dups = [k for k, v in Counter(par[0]).items() if v > 1]
print("  duplicate events in parallel run:", dups[:5] or "none")

print("\n=== C4: monitoring gap (nobody ticking) - does escalation continue by itself?")
a, _c = file_app("c4.db")
s = a.extensions["safety"]
fast(s, idle_threshold_seconds=10, checkin_response_window_seconds=5, num_checkins=3)
T = [20_000.0]
s.clock = s.audit.clock = s.notifier.clock = lambda: T[0]
cl = a.test_client()
hdr = login_all(cl)["supervisor"]
for sec in range(0, 13):
    T[0] = 20_000.0 + sec
    cl.post("/api/safety/tick", headers=hdr)
print(f"  t=12 s with a dashboard polling: worker 101 state = {s._machines[101].state}")
T[0] = 20_000.0 + 60
cl.post("/api/safety/tick", headers=hdr)
ev = [e["event"] for e in s.audit.entries() if e["worker_id"] == 101]
print(f"  t=60 s, first tick after a 47 s gap (worker stationary the whole time): state = {s._machines[101].state}; events = {ev}")
print("  control: the same worker polled continuously reaches EMERGENCY at:")
a2, _c2 = file_app("c4b.db")
s2 = a2.extensions["safety"]
fast(s2, idle_threshold_seconds=10, checkin_response_window_seconds=5, num_checkins=3)
T2 = [30_000.0]
s2.clock = s2.audit.clock = s2.notifier.clock = lambda: T2[0]
cl2 = a2.test_client()
h2 = login_all(cl2)["supervisor"]
first = None
for sec in range(0, 61):
    T2[0] = 30_000.0 + sec
    cl2.post("/api/safety/tick", headers=h2)
    if first is None and s2._machines[101].state == "EMERGENCY":
        first = sec
print(f"  continuous polling: EMERGENCY declared at t = {first} s (idle 10 + 3 x 5 s windows = 25 s expected)")

print("\n=== C5: the client cannot choose the time (server clock only)")
r = cl.post("/api/safety/tick?now=0&t=0", json={"now": 0, "time": 0}, headers=hdr)
print("  tick with ?now=0 / body now=0 ->", r.status_code, "(ignored; time comes from the server clock)")

