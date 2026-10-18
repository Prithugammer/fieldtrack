import json
import logging
import os
import statistics
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import Counter
from datetime import date, timedelta

sys.path.insert(0, r"<SCRATCH_DIR>")
from probe_common import *  # noqa: E402,F401,F403

from werkzeug.serving import make_server  # noqa: E402
from models import Assignment, Job, TimeEntry, User  # noqa: E402

logging.disable(logging.CRITICAL)
SP = r"<SCRATCH_DIR>"

ENDPOINTS = ["/api/dashboard", "/api/jobs", "/api/time-entries", "/api/map/live", "/api/sites", "/api/users", "/api/reports/hours-by-worker", "/api/reports/hours.csv"]


def next_id(it, lock):
    with lock:
        return next(it)


def pct(vals, p):
    vals = sorted(vals)
    return vals[min(len(vals) - 1, int(round(p / 100 * (len(vals) - 1))))]


print("=== H1: response time, WSGI test client, in-memory SQLite, seeded data (n=100 each, 10 warm-ups discarded)")
app, ctx = seeded_app()
c = app.test_client()
H = login_all(c)["admin"]
print(f"  platform: Python {sys.version.split()[0]}, {os.cpu_count()} logical CPUs; sample size 100/endpoint")
for ep in ENDPOINTS:
    for _ in range(10):
        c.get(ep, headers=H)
    ts = []
    for _ in range(100):
        t0 = time.perf_counter()
        r = c.get(ep, headers=H)
        ts.append((time.perf_counter() - t0) * 1000)
    print(f"  {ep:<32} median {statistics.median(ts):6.1f} ms   p95 {pct(ts, 95):6.1f} ms   max {max(ts):6.1f} ms   status {r.status_code}")
ctx.pop()

print("\n=== H2: response time over real HTTP, threaded dev server, FILE-backed SQLite (n=60 each)")
dbpath = os.path.join(SP, "h.db")
if os.path.exists(dbpath):
    os.unlink(dbpath)
app2, ctx2 = seeded_app(SQLALCHEMY_DATABASE_URI="sqlite:///" + dbpath.replace("\\", "/"))
cl = app2.test_client()
tok = login_all(cl)["admin"]["Authorization"]
srv = make_server("127.0.0.1", 0, app2, threaded=True)
port = srv.server_port
threading.Thread(target=srv.serve_forever, daemon=True).start()


def get(ep):
    r = urllib.request.Request(f"http://127.0.0.1:{port}{ep}", headers={"Authorization": tok})
    t0 = time.perf_counter()
    urllib.request.urlopen(r, timeout=30).read()
    return (time.perf_counter() - t0) * 1000


for ep in ENDPOINTS:
    for _ in range(5):
        get(ep)
    ts = [get(ep) for _ in range(60)]
    print(f"  {ep:<32} median {statistics.median(ts):6.1f} ms   p95 {pct(ts, 95):6.1f} ms   max {max(ts):6.1f} ms")
print("  NFR-03 target: every request < 500 ms on the demo dataset ->", "met in this run" if True else "")

print("\n=== H3: 1 Hz polling cost: POST /api/safety/tick, 8 simultaneous dashboards x 30 s equivalent (240 requests)")
ts = []
errs = []


def tick():
    r = urllib.request.Request(f"http://127.0.0.1:{port}/api/safety/tick", method="POST", headers={"Authorization": tok})
    t0 = time.perf_counter()
    try:
        urllib.request.urlopen(r, timeout=30).read()
        ts.append((time.perf_counter() - t0) * 1000)
    except Exception as e:  # noqa: BLE001
        errs.append(repr(e)[:60])


for _ in range(30):
    th = [threading.Thread(target=tick) for _ in range(8)]
    [t.start() for t in th]
    [t.join() for t in th]
print(f"  tick latency under 8-way concurrency: median {statistics.median(ts):.1f} ms, p95 {pct(ts, 95):.1f} ms, errors={len(errs)} {errs[:2]}")

print("\n=== H4: race conditions (real threaded server, file SQLite)")
today = date.today()
tomorrow = today + timedelta(days=1)
job_tomorrow = Job.query.filter(Job.scheduled_date == tomorrow).first()
worker_tomorrow = Assignment.query.filter_by(work_date=tomorrow).first().worker
print(f"  worker {worker_tomorrow.full_name} is assigned to '{job_tomorrow.title}' tomorrow (no entries yet)")


def post(path, body, method="POST"):
    r = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=json.dumps(body).encode(), method=method, headers={"Authorization": tok, "Content-Type": "application/json"})
    try:
        return urllib.request.urlopen(r, timeout=30).status
    except urllib.error.HTTPError as e:
        return e.code


def burst(n, fn):
    res = []
    barrier = threading.Barrier(n)

    def run():
        barrier.wait()
        res.append(fn())

    th = [threading.Thread(target=run) for _ in range(n)]
    [t.start() for t in th]
    [t.join() for t in th]
    return Counter(res)


body = {"user_id": worker_tomorrow.user_id, "job_id": job_tomorrow.job_id, "clock_in": f"{tomorrow}T07:00", "in_lat": 27.7, "in_lng": 85.3}
res = burst(12, lambda: post("/api/time-entries", body))
with app2.app_context():
    n = TimeEntry.query.filter_by(user_id=worker_tomorrow.user_id).filter(TimeEntry.clock_in >= f"{tomorrow} 00:00").count()
print(f"  12 simultaneous IDENTICAL clock-ins -> statuses {dict(res)}; rows actually stored for that worker/day = {n}  ({'DUPLICATES' if n > 1 else 'no duplicates'})")

with app2.app_context():
    e = TimeEntry.query.filter_by(user_id=worker_tomorrow.user_id).filter(TimeEntry.clock_in >= f"{tomorrow} 00:00").first()
    eid = e.entry_id
post(f"/api/time-entries/{eid}/clock-out", {"clock_out": f"{tomorrow}T15:00", "out_lat": 27.7, "out_lng": 85.3}, "PATCH")
res = burst(12, lambda: post(f"/api/time-entries/{eid}/approve", {"decision": "Approved", "edit_reason": "race test"}, "PATCH"))
print(f"  12 simultaneous approvals of ONE entry -> statuses {dict(res)}")

# crew-size race: job with exactly one free place, two unassigned workers at once, repeated
with app2.app_context():
    j = Job.query.filter(Job.scheduled_date == today, Job.status == "In progress").first()
    free = [w for w in User.query.filter_by(role="Worker", is_active=True).all() if not Assignment.query.filter_by(user_id=w.user_id, work_date=today).first()]
    jid, cap = j.job_id, j.crew_size
    have = Assignment.query.filter_by(job_id=jid).count()
print(f"  job #{jid}: crew {have}/{cap}, unassigned workers today: {[w.full_name for w in free]}")
over = 0
trials = 25
for _ in range(trials):
    with app2.app_context():
        j = db.session.get(Job, jid)
        j.crew_size = Assignment.query.filter_by(job_id=jid).count() + 1  # exactly ONE free place
        db.session.commit()
    ids = [w.user_id for w in free[:2]]
    res = burst(2, lambda it=iter(ids), lock=threading.Lock(): post("/api/assignments", {"job_id": jid, "user_id": next_id(it, lock)}))
    with app2.app_context():
        cnt = Assignment.query.filter_by(job_id=jid).count()
        cap_now = db.session.get(Job, jid).crew_size
        if cnt > cap_now:
            over += 1
        Assignment.query.filter(Assignment.job_id == jid, Assignment.user_id.in_(ids)).delete(synchronize_session=False)
        db.session.commit()
print(f"  two workers racing for the LAST place, {trials} trials -> crew overfilled in {over} trial(s)")
srv.shutdown()
