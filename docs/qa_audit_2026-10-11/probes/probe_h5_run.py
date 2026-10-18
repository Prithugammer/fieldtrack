import json
import logging
import os
import sys
import threading
import urllib.error
import urllib.request
from collections import Counter
from datetime import date, timedelta

sys.path.insert(0, r"<SCRATCH_DIR>")
from probe_common import *  # noqa: E402,F401,F403

from werkzeug.serving import make_server  # noqa: E402
from models import Assignment, Job, TimeEntry, User  # noqa: E402

logging.disable(logging.CRITICAL)
logging.getLogger("werkzeug").setLevel(logging.ERROR)
dbpath = os.path.join(r"<SCRATCH_DIR>", "h5.db")
if os.path.exists(dbpath):
    os.unlink(dbpath)
app, ctx = seeded_app(SQLALCHEMY_DATABASE_URI="sqlite:///" + dbpath.replace("\\", "/"), LOGIN_RATE_LIMIT_ENABLED=False)
H = login_all(app.test_client())
sup = H["supervisor"]["Authorization"]
dis = H["dispatcher"]["Authorization"]
srv = make_server("127.0.0.1", 0, app, threaded=True)
port = srv.server_port
threading.Thread(target=srv.serve_forever, daemon=True).start()


def call(path, body, tok, method="POST"):
    r = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=json.dumps(body).encode(), method=method, headers={"Authorization": tok, "Content-Type": "application/json"})
    try:
        return urllib.request.urlopen(r, timeout=30).status
    except urllib.error.HTTPError as e:
        return e.code


def burst(fns):
    res = []
    barrier = threading.Barrier(len(fns))

    def run(f):
        barrier.wait()
        res.append(f())

    th = [threading.Thread(target=run, args=(f,)) for f in fns]
    [t.start() for t in th]
    [t.join() for t in th]
    return dict(Counter(res))


tmr = date.today() + timedelta(days=1)
w = User.query.filter_by(email="suresh.magar@fieldtrack.com").one()
job = Job.query.filter(Job.scheduled_date == tmr).first()
closed = call("/api/time-entries", {"user_id": w.user_id, "job_id": job.job_id, "clock_in": f"{tmr}T06:00", "clock_out": f"{tmr}T10:00", "in_lat": 27.7, "in_lng": 85.3, "out_lat": 27.7, "out_lat": 27.7, "out_lng": 85.3}, sup)
eid = TimeEntry.query.filter_by(user_id=w.user_id).order_by(TimeEntry.entry_id.desc()).first().entry_id
print("setup: closed pending entry created ->", closed, "entry", eid)
res = burst([lambda: call(f"/api/time-entries/{eid}/approve", {"decision": "Approved", "edit_reason": "race A"}, sup, "PATCH") for _ in range(6)] + [lambda: call(f"/api/time-entries/{eid}/approve", {"decision": "Rejected", "edit_reason": "race R"}, sup, "PATCH") for _ in range(6)])
with app.app_context():
    e = db.session.get(TimeEntry, eid)
    print(f"  12 simultaneous decisions (6 Approve, 6 Reject) on ONE entry -> {res}; final status={e.status}  ({'MULTIPLE decisions accepted (FR-11 says a decided entry cannot be decided again)' if res.get(200, 0) > 1 else 'exactly one accepted'})")

# double-booking: UNIQUE(user_id, work_date)
today = date.today()
with app.app_context():
    free = [x for x in User.query.filter_by(role="Worker", is_active=True).all() if not Assignment.query.filter_by(user_id=x.user_id, work_date=today).first()]
    jobs_today = Job.query.filter(Job.scheduled_date == today, Job.status != "Completed").all()
    wid = free[0].user_id
    j1, j2 = jobs_today[0].job_id, jobs_today[1].job_id
    for j in jobs_today[:2]:
        j.crew_size = 20
    db.session.commit()
res = burst([lambda: call("/api/assignments", {"job_id": j1, "user_id": wid}, dis) for _ in range(5)] + [lambda: call("/api/assignments", {"job_id": j2, "user_id": wid}, dis) for _ in range(5)])
with app.app_context():
    n = Assignment.query.filter_by(user_id=wid, work_date=today).count()
print(f"  10 simultaneous assignments of ONE worker to two jobs the same day -> {res}; rows stored = {n}  ({'double-booked' if n > 1 else 'UNIQUE constraint held: exactly one'})")
srv.shutdown()
