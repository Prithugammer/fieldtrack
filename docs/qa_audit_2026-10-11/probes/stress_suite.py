"""Reproducible reliability / stress suite for FieldTrack. Self-contained and safe to run anywhere.

    cd backend
    .venv\\Scripts\\python.exe ..\\docs\\qa_audit_2026-10-11\\probes\\stress_suite.py  [--skip-real-process]

* Every database is a throw-away SQLite FILE in a fresh temp directory, deleted at the end. The developer
  database (backend/instance/fieldtrack.db) is never opened. DATABASE_URL in your shell is ignored.
* Every network call has a timeout; every section reports request counts, status distribution, latency
  (median / p95 / max) and a database integrity check where it writes.
* Nothing here asserts a performance target (the project's only documented one is NFR-03: < 500 ms).
"""

import contextlib
import copy
import io
import json
import logging
import os
import shutil
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from collections import Counter
from datetime import date

sys.path.insert(0, os.getcwd())
os.environ.pop("DATABASE_URL", None)
logging.disable(logging.CRITICAL)
logging.getLogger("werkzeug").setLevel(logging.ERROR)

from werkzeug.serving import make_server  # noqa: E402

import seed as seeding  # noqa: E402
from app import create_app  # noqa: E402
from extensions import db  # noqa: E402

TMP = tempfile.mkdtemp(prefix="fieldtrack_stress_")
ACCOUNTS = {"admin": ("admin@fieldtrack.com", "Admin123!"), "dispatcher": ("dispatch@fieldtrack.com", "Dispatch123!"), "supervisor": ("supervisor@fieldtrack.com", "Super123!")}
SKIP_REAL = "--skip-real-process" in sys.argv
RESULTS = []


def pct(values, p):
    values = sorted(values)
    return values[min(len(values) - 1, round(p / 100 * (len(values) - 1)))] if values else float("nan")


class Stack:
    """A seeded app on a temp SQLite file, served by a threaded HTTP server."""

    def __init__(self, name, **cfg):
        self.path = os.path.join(TMP, f"{name}.db")
        self.app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///" + self.path.replace("\\", "/"), "BCRYPT_ROUNDS": 4, "LOGIN_RATE_LIMIT_ENABLED": False, **cfg})
        with self.app.app_context(), contextlib.redirect_stdout(io.StringIO()):
            seeding.seed()
        self.httpd = make_server("127.0.0.1", 0, self.app, threaded=True)
        self.port = self.httpd.server_port
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.tokens = {r: self.call("POST", "/api/auth/login", {"email": e, "password": p})[1]["token"] for r, (e, p) in ACCOUNTS.items()}

    def call(self, method, path, body=None, role=None, raw=None, timeout=60, headers=None):
        h = {"Content-Type": "application/json", **(headers or {})}
        if role:
            h["Authorization"] = "Bearer " + self.tokens[role]
        data = raw if raw is not None else (None if body is None else json.dumps(body).encode())
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=data, method=method, headers=h)
        t0 = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                status, payload = r.status, r.read()
        except urllib.error.HTTPError as e:
            status, payload = e.code, e.read()
        except Exception as e:  # noqa: BLE001 - timeouts / resets are reported, not raised
            return "TIMEOUT/ERR", {"error": type(e).__name__}, (time.perf_counter() - t0) * 1000
        try:
            payload = json.loads(payload or b"null")
        except ValueError:
            payload = None
        return status, payload, (time.perf_counter() - t0) * 1000

    def integrity(self):
        con = sqlite3.connect(self.path)
        try:
            return con.execute("PRAGMA integrity_check").fetchone()[0], len(con.execute("PRAGMA foreign_key_check").fetchall())
        finally:
            con.close()

    def close(self):
        self.httpd.shutdown()
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()


def burst(fns, timeout=120):
    out = [None] * len(fns)
    gate = threading.Barrier(len(fns))

    def run(i, f):
        gate.wait()
        out[i] = f()

    ts = [threading.Thread(target=run, args=(i, f)) for i, f in enumerate(fns)]
    [t.start() for t in ts]
    [t.join(timeout) for t in ts]
    return out


def lat_line(label, results):
    ms = [r[2] for r in results if isinstance(r[2], float)]
    dist = dict(Counter(r[0] for r in results))
    print(f"  {label:<46} n={len(results):<4} statuses={dist}  median {statistics.median(ms):7.1f} ms  p95 {pct(ms, 95):7.1f}  max {max(ms):7.1f}")
    return dist, ms


def section(title):
    print(f"\n=== {title}")


def record(name, ok, detail=""):
    RESULTS.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name} {detail}")


print(f"FieldTrack stress suite | Python {sys.version.split()[0]} | {os.cpu_count()} logical CPUs | temp dir {TMP}")
print("Every request has a timeout; no data outside the temp dir is touched.\n")

# --------------------------------------------------------------------------------------------- 1 live map
section("1. Live Map: normal site vs unsupported sites, and isolation of everything else")
s = Stack("map")
jobs_today = s.call("GET", f"/api/jobs?date={date.today().isoformat()}", role="dispatcher")[1]["jobs"]
site_id = jobs_today[0]["site_id"]
orig = next(x for x in s.call("GET", "/api/sites", role="dispatcher")[1]["sites"] if x["site_id"] == site_id)
for label, (lat, lng) in {"normal (Kirtipur area)": (orig["latitude"], orig["longitude"]), "Pokhara (~140 km, valid input)": (28.2096, 83.9856), "lat 0 / lng 0": (0.0, 0.0), "south-east corner (-90, 180)": (-90.0, 180.0)}.items():
    assert s.call("PATCH", f"/api/sites/{site_id}", {"latitude": lat, "longitude": lng}, "dispatcher")[0] == 200
    first = s.call("GET", "/api/map/live", role="supervisor", timeout=30)
    rest = [s.call("GET", "/api/map/live", role="supervisor", timeout=30) for _ in range(100)]
    dist, ms = lat_line(f"GET /api/map/live, {label}", [first] + rest)
    record(f"map: {label} terminates quickly, no 5xx", all(r[0] == 200 for r in [first] + rest) and first[2] < 2000, f"first request {first[2]:.0f} ms")
assert s.call("PATCH", f"/api/sites/{site_id}", {"latitude": 0.0, "longitude": 0.0}, "dispatcher")[0] == 200
unrelated = ["/api/users", "/api/safety/config", "/api/sites", "/api/dashboard"]
stop = threading.Event()
load = []


def hammer():
    while not stop.is_set():
        load.append(s.call("GET", "/api/map/live", role="supervisor", timeout=30))


workers = [threading.Thread(target=hammer, daemon=True) for _ in range(6)]
[w.start() for w in workers]
time.sleep(0.3)
others = [s.call("GET", u, role="supervisor", timeout=30) for u in unrelated for _ in range(15)]
actions = [s.call("POST", "/api/safety/tick", role="supervisor", timeout=30) for _ in range(15)]
actions += [s.call("POST", "/api/safety/workers/12/sos", {}, "supervisor", timeout=30) for _ in range(5)]
stop.set()
[w.join(5) for w in workers]
lat_line("while 6 threads hammer the map (site at 0,0): API", others)
lat_line("while 6 threads hammer the map: safety tick/SOS", actions)
record("isolation: unrelated API calls and safety endpoints answered under map load", all(r[0] in (200, 201, 409) for r in others + actions) and max(r[2] for r in others + actions) < 2000, f"max {max(r[2] for r in others + actions):.0f} ms; {len(load)} map requests served meanwhile")
record("isolation: no map request failed or timed out", all(r[0] == 200 for r in load))
ok, fk = s.integrity()
record("database integrity after the map section", ok == "ok" and fk == 0, f"integrity_check={ok}, foreign_key_check rows={fk}")
s.close()

# --------------------------------------------------------------------------------------------- 2 races
section("2. Race conditions: simultaneous clock-ins and crew assignments")
s = Stack("race", SQLITE_BUSY_TIMEOUT_SECONDS=20)
from models import Assignment, Job, TimeEntry, User  # noqa: E402

with s.app.app_context():
    tomorrow_job = Job.query.filter(Job.scheduled_date > date.today()).first()
    worker_tomorrow = Assignment.query.filter_by(job_id=tomorrow_job.job_id).first().user_id
    tmr = tomorrow_job.scheduled_date.isoformat()
    tomorrow_job_id = tomorrow_job.job_id
    j_today = Job.query.filter(Job.scheduled_date == date.today(), Job.status != "Completed").first()
    jid = j_today.job_id
    extra = [User(full_name=f"Stress Worker {i}", email=f"stress{i}@example.test", role="Worker", trade="Laborer") for i in range(12)]
    db.session.add_all(extra)  # the seed leaves only 2 workers unassigned; the capacity tests need up to 10
    db.session.commit()
    free_workers = [w.user_id for w in User.query.filter_by(role="Worker").all() if not Assignment.query.filter_by(user_id=w.user_id, work_date=date.today()).first()]
    jid = j_today.job_id
body = {"user_id": worker_tomorrow, "job_id": tomorrow_job_id, "clock_in": f"{tmr}T07:00", "in_lat": 27.7, "in_lng": 85.3}
res = burst([lambda: s.call("POST", "/api/time-entries", body, "supervisor") for _ in range(12)])
with s.app.app_context():
    stored = TimeEntry.query.filter_by(user_id=worker_tomorrow).filter(TimeEntry.clock_in >= f"{tmr} 00:00:00").count()
dist, ms = lat_line("12 simultaneous identical clock-ins", res)
record("clock-in race: exactly one stored", stored == 1 and dist.get(201) == 1, f"201x{dist.get(201)}, rows stored={stored}")
trials = 20
over = 0
for _ in range(trials):
    with s.app.app_context():
        Assignment.query.filter_by(job_id=jid).delete()
        db.session.get(Job, jid).crew_size = 1
        db.session.commit()
    burst([lambda w=w: s.call("POST", "/api/assignments", {"job_id": jid, "user_id": w}, "dispatcher") for w in free_workers[:2]])
    with s.app.app_context():
        over += Assignment.query.filter_by(job_id=jid).count() > 1
record(f"crew race: {trials} trials, two workers for the last place", over == 0, f"overfilled in {over} trial(s)")
for cap, n in [(3, 8), (4, 10)]:
    with s.app.app_context():
        Assignment.query.filter_by(job_id=jid).delete()
        db.session.get(Job, jid).crew_size = cap
        db.session.commit()
    res = burst([lambda w=w: s.call("POST", "/api/assignments", {"job_id": jid, "user_id": w}, "dispatcher") for w in free_workers[:n]])
    with s.app.app_context():
        stored = Assignment.query.filter_by(job_id=jid).count()
    lat_line(f"crew capacity {cap}, {n} simultaneous assignments", res)
    record(f"capacity boundary {cap}/{n}", stored == min(cap, n), f"stored {stored}, 201x{Counter(r[0] for r in res).get(201, 0)}")
ok, fk = s.integrity()
record("database integrity after the race section", ok == "ok" and fk == 0, f"integrity_check={ok}, foreign_key_check rows={fk}")
s.close()

# --------------------------------------------------------------------------------------------- 3 ticks
section("3. Concurrent ticks + heartbeat: no event is advanced twice")
from safety import SafetyTicker  # noqa: E402
from routes import map as rmap, safety as rsafety  # noqa: E402


def W(i, status="On site", lat=27.70, lng=85.30):
    return {"id": i, "name": f"W{i}", "trade": "T", "status": status, "lat": lat, "lng": lng, "job_title": "J", "site_name": "S", "near_traffic": False, "hotspot": None, "distance_remaining_m": None}


FIXED = [W(101), W(102, lat=27.71, lng=85.31), W(103, "In transit", 27.72, 85.32)]


def run_scenario(parallel):
    st = Stack("ticks_par" if parallel else "ticks_seq")
    sv = st.app.extensions["safety"]
    sv.config = sv.config.with_changes(accident_probability=0, auto_respond_chance=0, idle_threshold_seconds=10, checkin_response_window_seconds=5, num_checkins=3, max_poll_gap_seconds=1e9)
    sv.roller.config = sv.planner.config = sv.config
    clock = [100_000.0]
    sv.clock = sv.audit.clock = sv.notifier.clock = lambda: clock[0]
    step = [0]

    def src(path_for=None):
        workers = copy.deepcopy(FIXED)
        step[0] += 1
        workers[2]["lat"] += 0.001 * step[0]  # worker 103 keeps moving (~110 m per call), so it is never idle
        return {"workers": workers, "job_sites": []}

    rmap.compute_live_state = src
    rsafety.compute_live_state = src
    beat = SafetyTicker(st.app, state_source=lambda: src())
    reqs = []
    for _ in range(60):
        clock[0] += 1
        fns = [lambda: reqs.append(st.call("POST", "/api/safety/tick", role="supervisor")) or 0 for _ in range(8 if parallel else 1)]
        if parallel:
            fns.append(lambda: beat.tick_once() and 0)
        burst(fns)
    events = sorted((e["worker_id"], e["event"], round(e["t"], 3)) for e in sv.audit.entries())
    states = {k: m.state for k, m in sv._machines.items()}
    st.close()
    return events, states, reqs


seq_events, seq_states, _ = run_scenario(False)
par_events, par_states, reqs = run_scenario(True)
lat_line("POST /api/safety/tick, 8 clients + heartbeat per second", reqs)
c = Counter(par_events and [(w, e) for w, e, _ in par_events])
record("ticks: audit trail identical to the sequential run", par_events == seq_events and par_states == seq_states, f"{len(par_events)} events, {len(reqs)} concurrent requests")
record("ticks: exactly one EMERGENCY per stationary worker, no duplicates", c[(101, "EMERGENCY")] == 1 and c[(102, "EMERGENCY")] == 1 and c[(103, "EMERGENCY")] == 0, f"101:{c[(101, 'EMERGENCY')]} 102:{c[(102, 'EMERGENCY')]} 103(moving):{c[(103, 'EMERGENCY')]}")

# --------------------------------------------------------------------------------------------- 4 hostile bodies
section("4. Oversized and deeply nested request bodies")
s = Stack("bodies")
cases = {
    "2 MB body (limit 1 MB)": json.dumps({"email": "a" * 2_000_000, "password": "x"}).encode(),
    "3,000-deep array": b"[" * 3000,
    "60,000-deep array": b"[" * 60000,
    "lone surrogate in email": json.dumps({"email": "\ud800", "password": "x"}).encode(),
    "5,000-digit integer": b'{"email": "a@b.cc", "password": ' + b"9" * 5000 + b"}",
}
for label, raw in cases.items():
    res = [s.call("POST", "/api/auth/login", raw=raw) for _ in range(25)]
    dist, ms = lat_line(label + " x25 -> POST /auth/login", res)
    record(f"body: {label} -> 4xx only", all(isinstance(r[0], int) and 400 <= r[0] < 500 for r in res), f"{dist}")
after = [s.call("GET", "/api/health") for _ in range(20)]
record("body: the server is still healthy afterwards", all(r[0] == 200 for r in after))
for url in ["/api/time-entries?date=9999-12-31", "/api/reports/hours-by-worker?to=9999-12-31", "/api/reports/hours.csv?from=0001-01-01&to=9999-12-31"]:
    r = s.call("GET", url, role="admin")
    record(f"extreme date {url}", r[0] == 200, f"-> {r[0]}")
s.close()

# --------------------------------------------------------------------------------------------- 5 login throttle
section("5. Repeated login failures and throttling (window shortened to 3 s so recovery can be shown)")
s = Stack("login", LOGIN_RATE_LIMIT_ENABLED=True, LOGIN_RATE_WINDOW_SECONDS=3)
res = [s.call("POST", "/api/auth/login", {"email": "admin@fieldtrack.com", "password": "wrong"}) for _ in range(30)]
dist, ms = lat_line("30 wrong passwords for one account", res)
record("throttle: 5 x 401 then 429", dist == {401: 5, 429: 25}, f"{dist}")
record("throttle: the right password is also refused while blocked", s.call("POST", "/api/auth/login", {"email": "admin@fieldtrack.com", "password": "Admin123!"})[0] == 429)
time.sleep(3.3)
record("throttle: sign-in works again after the window", s.call("POST", "/api/auth/login", {"email": "admin@fieldtrack.com", "password": "Admin123!"})[0] == 200)
s.close()

# --------------------------------------------------------------------------------------------- 6 startup
section("6. Backend start-up with valid and invalid production configuration")
base = {k: v for k, v in os.environ.items() if k not in ("DATABASE_URL", "SECRET_KEY", "JWT_SECRET_KEY", "APP_ENV", "FLASK_DEBUG")}
for label, extra, want_ok in [
    ("development, nothing set", {}, True),
    ("production without SECRET_KEY", {"APP_ENV": "production"}, False),
    ("production, placeholder key", {"APP_ENV": "production", "SECRET_KEY": "change-me"}, False),
    ("production, 40-char random key", {"APP_ENV": "production", "SECRET_KEY": "q7Zr2LmX9vB4nT8cJ1wY5hD3kF6pS0aGx9eRtU2i"}, True),
    ("production, strong key, tick interval 0", {"APP_ENV": "production", "SECRET_KEY": "q7Zr2LmX9vB4nT8cJ1wY5hD3kF6pS0aGx9eRtU2i", "SAFETY_TICK_INTERVAL_SECONDS": "0"}, False),
    ("unknown APP_ENV", {"APP_ENV": "prod"}, False),
]:
    p = subprocess.run([sys.executable, "-c", "import app; app.create_app(); print('STARTED')"], capture_output=True, text=True, env={**base, **extra, "DATABASE_URL": "sqlite:///" + os.path.join(TMP, "start.db").replace("\\", "/")}, timeout=60)
    started = p.returncode == 0 and "STARTED" in p.stdout
    last = (p.stderr.strip().splitlines() or p.stdout.strip().splitlines() or [""])[-1][:90]
    record(f"startup: {label}", started == want_ok, f"-> {'starts' if started else 'refuses'}" + ("" if started else f" ({last})"))

# --------------------------------------------------------------------------------------------- 7 real process
if not SKIP_REAL:
    section("7. A REAL server process with no client: does safety escalation still advance? (about 50 s)")
    dbf = os.path.join(TMP, "real.db")
    env = {**base, "DATABASE_URL": "sqlite:///" + dbf.replace("\\", "/"), "PORT": "5077", "SAFETY_MODE": "demo", "SAFETY_SEED": "3", "SAFETY_AUTO_RESPOND_CHANCE": "0", "SAFETY_ACCIDENT_PROBABILITY": "0", "PYTHONDONTWRITEBYTECODE": "1"}
    subprocess.run([sys.executable, "seed.py", "--reset", "--yes"], env=env, capture_output=True, timeout=120)
    log_path = os.path.join(TMP, "real.log")
    with open(log_path, "w") as log:
        srv = subprocess.Popen([sys.executable, "-u", "app.py"], env=env, stdout=log, stderr=subprocess.STDOUT)
    try:
        t_start = time.time()
        while time.time() - t_start < 30:
            try:
                urllib.request.urlopen("http://127.0.0.1:5077/api/health", timeout=1)
                break
            except Exception:  # noqa: BLE001
                time.sleep(0.3)
        time.sleep(40)  # demo thresholds: idle 15 s + 3 x 5 s windows = 30 s. NO client talks to the server meanwhile.
        text = open(log_path, errors="replace").read()
        served = [ln for ln in text.splitlines() if "HTTP/1.1" in ln]
        tok = json.loads(urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:5077/api/auth/login", data=json.dumps({"email": "supervisor@fieldtrack.com", "password": "Super123!"}).encode(), headers={"Content-Type": "application/json"}), timeout=10).read())["token"]
        audit = json.loads(urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:5077/api/safety/audit", headers={"Authorization": "Bearer " + tok}), timeout=10).read())
        kinds = Counter(e["event"] for e in audit)
        record("real process: only /api/health was requested before the audit was read", all("/api/health" in ln for ln in served), f"{len(served)} request(s) logged")
        record("real process: idle detection, 3 check-ins and an EMERGENCY happened with no client connected", kinds["IDLE_DETECTED"] >= 1 and kinds["CHECKIN_SENT"] >= 3 and kinds["EMERGENCY"] >= 1, str(dict(kinds)))
    finally:
        srv.terminate()
        try:
            srv.wait(10)
        except Exception:  # noqa: BLE001
            srv.kill()

shutil.rmtree(TMP, ignore_errors=True)
failed = [r for r in RESULTS if not r[1]]
print(f"\nSUMMARY: {len(RESULTS) - len(failed)} passed, {len(failed)} failed (temp dir removed)")
for name, _, detail in failed:
    print("  FAILED:", name, detail)
sys.exit(1 if failed else 0)
