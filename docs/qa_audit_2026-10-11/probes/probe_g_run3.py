import json
import logging
import sys
import time
from collections import defaultdict
from datetime import date, timedelta

sys.path.insert(0, r"<SCRATCH_DIR>")
from probe_common import *  # noqa: E402,F401,F403

from models import Assignment, Job, JobSite, TimeEntry, User  # noqa: E402

logging.disable(logging.CRITICAL)
app, ctx = seeded_app()
c = app.test_client()
H = login_all(c)
print("MAX_CONTENT_LENGTH =", app.config.get("MAX_CONTENT_LENGTH"), "| PROPAGATE_EXCEPTIONS =", app.config.get("PROPAGATE_EXCEPTIONS"), "| DEBUG =", app.debug)

today = date.today().isoformat()
tomorrow = (date.today() + timedelta(days=1)).isoformat()
w = User.query.filter_by(role="Worker").all()
job_today = Job.query.filter(Job.scheduled_date == date.today()).first()
site = JobSite.query.first()
entry = TimeEntry.query.first()
asg = Assignment.query.first()
counter = [0]


def uniq():
    counter[0] += 1
    return counter[0]


HOSTILE = [
    None, True, False, 0, -1, 1, 2**31, 2**63, 2**64, -(2**63) - 1, 1.5, 1e308, float("inf"), float("-inf"), float("nan"),
    "", " ", "a", "a" * 10000, "\u0000", "'; DROP TABLE users;--", "<script>alert(1)</script>", "2026-10-01", "2026-13-45", "20261001",
    [], [1], {}, {"a": 1}, "\U0001F600", "\ud800", "\udfff", "‮", "a\u0000b", "\n", "../../etc/passwd", "%s%s%s", "{{7*7}}", "9" * 400,
]

# endpoint: (method, path, role, base-body factory)
EP = [
    ("POST", "/api/users", "admin", lambda: {"full_name": "Fuzz User", "email": f"fz{uniq()}@t.com", "role": "Dispatcher", "password": "Fuzzpass123!", "phone": "+977-1-5551234", "trade": "Welder"}),
    ("PATCH", f"/api/users/{w[0].user_id}", "admin", lambda: {"full_name": "Fuzz Name", "phone": "+977-1-5551234", "email": f"fp{uniq()}@t.com", "role": "Worker", "trade": "Welder", "password": "Fuzzpass123!", "is_active": True}),
    ("POST", "/api/sites", "dispatcher", lambda: {"site_name": "Fuzz Site", "address": "1 Fuzz Road", "latitude": 27.7, "longitude": 85.3, "geofence_radius_m": 200}),
    ("PATCH", f"/api/sites/{site.site_id}", "dispatcher", lambda: {"site_name": "Fuzz Site", "address": "1 Fuzz Road", "latitude": 27.7, "longitude": 85.3, "geofence_radius_m": 200}),
    ("POST", "/api/jobs", "dispatcher", lambda: {"site_id": site.site_id, "title": "Fuzz job", "description": "d", "scheduled_date": today, "crew_size": 2, "status": "Scheduled"}),
    ("PATCH", f"/api/jobs/{job_today.job_id}", "dispatcher", lambda: {"site_id": site.site_id, "title": "Fuzz job", "description": "d", "scheduled_date": today, "crew_size": 3, "status": "In progress"}),
    ("POST", "/api/assignments", "dispatcher", lambda: {"job_id": job_today.job_id, "user_id": w[1].user_id, "work_date": today}),
    ("DELETE", f"/api/assignments/{asg.assignment_id}", "dispatcher", lambda: {}),
    ("POST", "/api/time-entries", "supervisor", lambda: {"user_id": w[2].user_id, "job_id": job_today.job_id, "clock_in": f"{tomorrow}T07:{uniq() % 60:02d}", "in_lat": 27.7, "in_lng": 85.3, "clock_out": f"{tomorrow}T09:00", "out_lat": 27.7, "out_lng": 85.3}),
    ("PATCH", f"/api/time-entries/{entry.entry_id}/clock-out", "supervisor", lambda: {"clock_out": f"{today}T23:59", "out_lat": 27.7, "out_lng": 85.3}),
    ("PATCH", f"/api/time-entries/{entry.entry_id}/approve", "supervisor", lambda: {"decision": "Approved", "edit_reason": "fuzz reason"}),
    ("POST", "/api/auth/login", None, lambda: {"email": "supervisor@fieldtrack.com", "password": "Super123!"}),
] + [("POST", f"/api/safety/workers/{w[3].user_id}/{a}", "supervisor", lambda a=a: {"outcome": "false_alarm", "note": "n", "on_break": True}) for a in ("accident", "sos", "respond", "break", "resolve", "return-to-duty")]

app.extensions["login_limiter"].max_per_account = 10**9
app.extensions["login_limiter"].max_per_client = 10**9

five_hundreds = defaultdict(list)
n_req = 0
t0 = time.time()
for method, path, role, mk in EP:
    hdr = H[role] if role else {}
    print('endpoint', method, path, flush=True)
    base = mk()
    # field-by-field
    for field in list(base):
        if method == 'PATCH' and '/sites/' in path and field in ('latitude', 'longitude'):
            continue  # known defect D-02 (far-away site hangs the live-map simulation) - excluded so the sweep can finish
        for val in HOSTILE:
            body = mk()
            body[field] = val
            try:
                data = json.dumps(body, allow_nan=True)
            except (TypeError, ValueError):
                continue
            _t=time.time(); r = c.open(path, method=method, data=data, content_type="application/json", headers=hdr); _d=time.time()-_t; n_req += 1
            if _d > 2: print('SLOW', round(_d,1), 's', method, path, field, repr(val)[:40], flush=True)
            if r.status_code >= 500:
                five_hundreds[(method, path.split("/")[2] if path.count("/") > 1 else path, field)].append(repr(val)[:30])
            db.session.rollback()
    # whole-body hostility
    for raw in ["null", "[]", "[1,2]", '"x"', "42", "true", "{", "", "{}", '{"a": ' * 2000, "[" * 60000, "\x00", '{"a":"\\ud800"}', "{" + '"k":1,' * 50000 + '"z":1}']:
        r = c.open(path, method=method, data=raw, content_type="application/json", headers=hdr)
        n_req += 1
        if r.status_code >= 500:
            five_hundreds[(method, path, "<<body>>")].append(repr(raw)[:30])
    # hostile path ids
for method, url, role in [("GET", "/api/jobs/%s", "dispatcher"), ("PATCH", "/api/users/%s", "admin"), ("DELETE", "/api/assignments/%s", "dispatcher"), ("POST", "/api/safety/workers/%s/sos", "supervisor")]:
    for bad in ["0", "-1", "1.5", "1e9", "abc", "%00", "9" * 5000, "٣", "%E2%80%AE", "1;DROP", "' OR 1=1", "%ff"]:
        r = c.open(url % bad, method=method, json={}, headers=H[role])
        n_req += 1
        if r.status_code >= 500:
            five_hundreds[(method, url, "<<path>>")].append(bad[:20])
print(f"fuzz: {n_req} requests in {time.time() - t0:.0f}s")
print("responses with status >= 500:", sum(len(v) for v in five_hundreds.values()))
for k, v in five_hundreds.items():
    print("  500 at", k, "values:", v[:6])

# hostile query-strings on every GET list endpoint
qs_500 = []
for url in ["/api/jobs", "/api/users", "/api/assignments", "/api/time-entries", "/api/reports/hours-by-worker", "/api/reports/hours-by-job", "/api/reports/flagged", "/api/reports/hours.csv", "/api/safety/audit", "/api/map/live", "/api/dashboard"]:
    for param in ["date", "status", "site_id", "worker", "job_id", "user_id", "work_date", "from", "to", "role", "active", "flagged", "format", "worker_id", "route"]:
        for val in ["", "\x00", "%00", "9" * 400, "\ud800", "a" * 5000, "-1", "1e999", "nan", "' OR 1=1--", "2026-02-30", "💥"]:
            try:
                r = c.get(url, query_string={param: val}, headers=H["admin"])
            except UnicodeEncodeError:
                continue
            if r.status_code >= 500:
                qs_500.append((url, param, repr(val)[:20]))
print("GET query-string fuzz 500s:", len(qs_500), qs_500[:6])

print("\n=== integrity after fuzz")
print("  PRAGMA foreign_key_check rows:", db.session.execute(db.text("PRAGMA foreign_key_check")).fetchall()[:3])
print("  PRAGMA integrity_check:", db.session.execute(db.text("PRAGMA integrity_check")).scalar())

print("\n=== G-GET: no GET endpoint changes persistent or in-memory state")
svc = app.extensions["safety"]
snap = lambda: (db_fingerprint(), json.dumps(svc.audit.entries(), default=str), sorted(svc._machines), sorted(svc._frozen), svc._last_tick)  # noqa: E731
before = snap()
gets = [r.rule for r in app.url_map.iter_rules() if "GET" in r.methods and r.rule.startswith("/api/") and "<" not in r.rule]
for _ in range(3):
    for g in gets:
        c.get(g, headers=H["admin"])
print(f"  {len(gets)} GET routes x3 as Admin; state identical: {before == snap()}")
print("  GET routes:", ", ".join(sorted(gets)))
print("  non-GET routes:", ", ".join(sorted(f"{sorted(r.methods - {'HEAD','OPTIONS'})[0]} {r.rule}" for r in app.url_map.iter_rules() if r.rule.startswith('/api/') and not ('GET' in r.methods))))

print("\n=== G-AUTH: every /api route without a token")
unauth = {}
for rule in app.url_map.iter_rules():
    if not rule.rule.startswith("/api/") or rule.rule in ("/api/auth/login", "/api/health"):
        continue
    path = rule.rule
    for conv in ("<int:user_id>", "<int:job_id>", "<int:site_id>", "<int:assignment_id>", "<int:entry_id>"):
        path = path.replace(conv, "1")
    for m in rule.methods - {"HEAD", "OPTIONS"}:
        unauth[(m, rule.rule)] = c.open(path, method=m).status_code
print("  non-401 responses without token:", {k: v for k, v in unauth.items() if v != 401} or "none", f"({len(unauth)} method/route pairs)")
