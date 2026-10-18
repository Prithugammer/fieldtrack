import logging
import sys
from datetime import date

sys.path.insert(0, r"<SCRATCH_DIR>")
from probe_common import *  # noqa: E402,F401,F403

from models import Job, User  # noqa: E402

logging.disable(logging.CRITICAL)
app, ctx = seeded_app(LOGIN_RATE_LIMIT_ENABLED=False)
c = app.test_client()
H = login_all(c)
adm, dis, sup = H["admin"], H["dispatcher"], H["supervisor"]

print("=== I1: extreme dates in filters (documented format is valid for any real calendar date)")
for name, url in [
    ("time-entries ?date=9999-12-31", "/api/time-entries?date=9999-12-31"),
    ("time-entries ?date=0001-01-01", "/api/time-entries?date=0001-01-01"),
    ("reports hours-by-worker ?to=9999-12-31", "/api/reports/hours-by-worker?to=9999-12-31"),
    ("reports hours-by-worker ?from=9999-12-31", "/api/reports/hours-by-worker?from=9999-12-31"),
    ("reports flagged ?from=0001-01-01&to=9999-12-31", "/api/reports/flagged?from=0001-01-01&to=9999-12-31"),
    ("reports hours.csv ?to=9999-12-31", "/api/reports/hours.csv?to=9999-12-31"),
    ("assignments ?work_date=9999-12-31", "/api/assignments?work_date=9999-12-31"),
    ("jobs ?date=9999-12-31", "/api/jobs?date=9999-12-31"),
]:
    r = c.get(url, headers=adm)
    print(f"  {name:<52} -> {r.status_code}  {'<-- 500' if r.status_code >= 500 else ''}")

print("\n=== I2: lone surrogate / deep nesting on text fields that clear the minimum-length rules")
S3 = "\ud800\ud800\ud800"
for name, method, url, who, body in [
    ("job title", "post", "/api/jobs", dis, {"site_id": 1, "title": S3, "scheduled_date": date.today().isoformat(), "crew_size": 2}),
    ("site name", "post", "/api/sites", dis, {"site_name": S3, "address": "1 Test Road", "latitude": 27.7, "longitude": 85.3}),
    ("user full_name", "post", "/api/users", adm, {"full_name": S3, "email": "s@t.com", "role": "Worker", "trade": "Welder"}),
    ("user trade", "post", "/api/users", adm, {"full_name": "Sur Rogate", "email": "s2@t.com", "role": "Worker", "trade": S3}),
    ("approve edit_reason", "patch", "/api/time-entries/1/approve", sup, {"decision": "Approved", "edit_reason": S3}),
    ("login email", "post", "/api/auth/login", None, {"email": "\ud800", "password": "x"}),
    ("safety resolve note", "post", "/api/safety/workers/8/resolve", sup, {"outcome": "false_alarm", "note": S3}),
]:
    r = getattr(c, method)(url, json=body, headers=who or {})
    print(f"  {name:<22} -> {r.status_code}  {'<-- 500 (unauthenticated!)' if r.status_code >= 500 and who is None else ('<-- 500' if r.status_code >= 500 else '')}")
r = c.post("/api/auth/login", data="[" * 60000, content_type="application/json")
print(f"  login, 60,000 nested '[' (unauthenticated)  -> {r.status_code}")
r = c.post("/api/auth/login", data="[" * 3000, content_type="application/json")
print(f"  login, 3,000 nested '['                      -> {r.status_code}")
r = c.post("/api/auth/login", data="[" * 400, content_type="application/json")
print(f"  login, 400 nested '['                        -> {r.status_code}")

print("\n=== I3: valid creation proof for numeric-string / float ids (regression check for preserved client behavior)")
from datetime import timedelta  # noqa: E402

tmr = (date.today() + timedelta(days=1)).isoformat()
worker = User.query.filter_by(email="suresh.magar@fieldtrack.com").one()
job = Job.query.filter(Job.scheduled_date == date.today() + timedelta(days=1)).first()
body = {"user_id": str(worker.user_id), "job_id": f"{job.job_id}.0", "clock_in": f"{tmr}T07:00", "in_lat": "27.70", "in_lng": "85.30"}
r = c.post("/api/time-entries", json=body, headers=sup)
print(f"  user_id as string, job_id as '<n>.0' (string), lat/lng as strings -> {r.status_code} {(r.get_json() or {}).get('error','created entry #' + str((r.get_json() or {}).get('time_entry', {}).get('entry_id')))}")
