import json
import sys

sys.path.insert(0, r"<SCRATCH_DIR>")
from probe_common import *  # noqa: E402,F401,F403

app, ctx = seeded_app()
c = app.test_client()
H = login_all(c)
sup, adm, dis = H["supervisor"], H["admin"], H["dispatcher"]

from models import Job, TimeEntry, User  # noqa: E402
from datetime import date  # noqa: E402

today = date.today().isoformat()
worker = User.query.filter_by(role="Worker").first()
job = Job.query.filter(Job.scheduled_date == date.today()).first()
base = {"user_id": worker.user_id, "job_id": job.job_id, "clock_in": f"{today}T07:00", "in_lat": 27.7, "in_lng": 85.3}


def raw_body(**over):
    """JSON text with python-style numeric literals so 1e999 / NaN reach the server unchanged."""
    d = dict(base)
    d.update(over)
    parts = []
    for k, v in d.items():
        parts.append(f'"{k}": {v if isinstance(v, str) and v.startswith("@") is False and False else ""}')
    return None


def send(field, literal, who=sup, url="/api/time-entries"):
    """POST with `field` set to a raw JSON literal (e.g. 1e999, NaN, 9223372036854775808)."""
    items = []
    for k, v in base.items():
        items.append(f'"{k}": {literal if k == field else json.dumps(v)}')
    body = "{" + ", ".join(items) + "}"
    r = c.post(url, data=body, content_type="application/json", headers=who)
    return r.status_code, (r.get_json() or {}).get("field"), (r.get_json() or {}).get("error")


print("=== A1: POST /api/time-entries, bad value in user_id / job_id (raw JSON literals)")
literals = [
    ("2**63-1 (valid range, no such row)", "9223372036854775807"),
    ("2**63", "9223372036854775808"),
    ("-(2**63)", "-9223372036854775808"),
    ("-(2**63)-1", "-9223372036854775809"),
    ("30-digit int", "123456789012345678901234567890"),
    ("1e999", "1e999"),
    ("-1e999", "-1e999"),
    ("NaN literal", "NaN"),
    ("Infinity literal", "Infinity"),
    ("-Infinity literal", "-Infinity"),
    ("zero", "0"),
    ("negative", "-5"),
    ("null", "null"),
    ("string 'abc'", '"abc"'),
    ("string '5' (numeric string)", f'"{worker.user_id}"'),
    ("string '9'*30", '"' + "9" * 30 + '"'),
    ("string '1e999'", '"1e999"'),
    ("string '1.5'", '"1.5"'),
    ("float 5.0", f"{worker.user_id}.0"),
    ("float 1.5", "1.5"),
    ("true", "true"),
    ("[1]", "[1]"),
    ("{}", "{}"),
    ("5000-digit int", "9" * 5000),
]
before = db_fingerprint()
bad500 = 0
for field in ("user_id", "job_id"):
    for name, lit in literals:
        st, fld, err = send(field, lit)
        flag = "500!!" if st >= 500 else ""
        bad500 += st >= 500
        print(f"  {field:<8} {name:<34} -> {st} field={fld} {flag}")
after = db_fingerprint()
line("A1", "PASS" if bad500 == 0 else "FAIL", f"500s={bad500}; DB fingerprint unchanged by invalid requests: {before == after or 'CHANGED (valid rows may have been created: see below)'}")

print("=== A1b: the numeric-string / float forms that ARE valid must still work")
st = c.post("/api/time-entries", json={**base, "user_id": str(worker.user_id)}, headers=sup).status_code
print(f"  user_id as numeric string '{worker.user_id}' -> {st} (201 expected: preserved client behavior)")
r = c.post("/api/time-entries", data=json.dumps(base).replace(f'"user_id": {worker.user_id}', f'"user_id": {worker.user_id}.0'), content_type="application/json", headers=sup)
print(f"  user_id as float {worker.user_id}.0 -> {r.status_code} (409 overlap with previous is fine; 400/500 would be a regression) {r.get_json().get('error','')[:60]}")

print("=== A2: URL path ids")
for name, path in [
    ("23-digit", "99999999999999999999999"),
    ("2**63", "9223372036854775808"),
    ("2**63-1", "9223372036854775807"),
    ("zero", "0"),
    ("negative", "-1"),
    ("letters", "abc"),
    ("float", "1.5"),
    ("5000 digits", "9" * 5000),
]:
    out = []
    for method, url in [("GET", "/api/jobs/%s"), ("PATCH", "/api/jobs/%s"), ("PATCH", "/api/users/%s"), ("PATCH", "/api/sites/%s"), ("DELETE", "/api/assignments/%s"), ("PATCH", "/api/time-entries/%s/clock-out"), ("PATCH", "/api/time-entries/%s/approve"), ("POST", "/api/safety/workers/%s/accident")]:
        r = c.open(url % path, method=method, json={} if method != "GET" else None, headers=adm)
        out.append(r.status_code)
    print(f"  {name:<12} statuses for 8 endpoints: {out}  {'<-- 500!' if any(s >= 500 for s in out) else ''}")

print("=== A3: query-string filters")
for name, qs in [
    ("jobs ?site_id=2**63", "/api/jobs?site_id=9223372036854775808"),
    ("jobs ?site_id=0", "/api/jobs?site_id=0"),
    ("jobs ?site_id=-1", "/api/jobs?site_id=-1"),
    ("jobs ?site_id=1e999", "/api/jobs?site_id=1e999"),
    ("jobs ?site_id=nan", "/api/jobs?site_id=nan"),
    ("jobs ?site_id=", "/api/jobs?site_id="),
    ("jobs ?site_id=1 (valid)", "/api/jobs?site_id=1"),
    ("entries ?worker=2**63", "/api/time-entries?worker=9223372036854775808"),
    ("entries ?job_id=999..9 (30)", "/api/time-entries?job_id=" + "9" * 30),
    ("entries ?worker=abc", "/api/time-entries?worker=abc"),
    ("assign ?user_id=0", "/api/assignments?user_id=0"),
    ("audit ?worker_id=2**63", "/api/safety/audit?worker_id=9223372036854775808"),
    ("map ?route=2**63", "/api/map/live?route=9223372036854775808"),
    ("map ?route=abc", "/api/map/live?route=abc"),
    ("map ?route=1 (valid)", "/api/map/live?route=1"),
    ("tick ?route=1e999", "/api/safety/tick?route=1e999"),
]:
    meth = "post" if "tick" in qs else "get"
    r = getattr(c, meth)(qs, headers=adm)
    j = r.get_json(silent=True) or {}
    print(f"  {name:<30} -> {r.status_code} field={j.get('field') if isinstance(j, dict) else None}")

print("=== A4: foreign keys in bodies; DB must be unchanged after rejections")
fp = db_fingerprint()
cases = [
    ("POST /api/jobs site_id=2**63", "post", "/api/jobs", dis, {"site_id": 2**63, "title": "Zzz job", "scheduled_date": today, "crew_size": 2}),
    ("POST /api/jobs site_id=99999", "post", "/api/jobs", dis, {"site_id": 99999, "title": "Zzz job", "scheduled_date": today, "crew_size": 2}),
    ("POST /api/assignments job_id=-1", "post", "/api/assignments", dis, {"job_id": -1, "user_id": worker.user_id}),
    ("POST /api/assignments user_id=2**63", "post", "/api/assignments", dis, {"job_id": job.job_id, "user_id": 2**63}),
    ("PATCH /api/jobs/1 site_id=1e30", "patch", f"/api/jobs/{job.job_id}", dis, {"site_id": 1e30}),
]
for name, m, url, who, body in cases:
    r = getattr(c, m)(url, json=body, headers=who)
    print(f"  {name:<40} -> {r.status_code} {(r.get_json() or {}).get('field')}")
print(f"  DB fingerprint unchanged: {fp == db_fingerprint()}")

print("=== A5: crew_size / radius / lat / lng non-finite and huge")
for name, url, field, m in [("crew_size", f"/api/jobs/{job.job_id}", "crew_size", "patch"), ("radius", "/api/sites/1", "geofence_radius_m", "patch")]:
    for lit in ["1e999", "-1e999", "NaN", "9223372036854775808", '"7"', "7.0", "7.5", "null"]:
        r = getattr(c, m)(url, data=f'{{"{field}": {lit}}}', content_type="application/json", headers=dis)
        print(f"  {field:<18} {lit:<24} -> {r.status_code} {(r.get_json() or {}).get('error','')[:60]}")
for lit in ["1e999", "NaN", "-Infinity", '"inf"', '"nan"', '"1e999"']:
    r = c.post("/api/sites", data=f'{{"site_name":"Probe Site","address":"1 Probe Road","latitude":{lit},"longitude":85.3}}', content_type="application/json", headers=dis)
    print(f"  latitude {lit:<12} -> {r.status_code} {(r.get_json() or {}).get('error','')[:60]}")

print("=== A6: dates (parse_date) - documented format is YYYY-MM-DD")
for lit in ["2026-10-01", " 2026-10-01 ", "20261001", "2026-W40-4", "2026-1-1", "2026-10-01T00:00", "2026-02-30", "0000-01-01", "9999-12-31", "Ù¢Ù Ù¢Ù¦-Ù¡Ù -Ù Ù¡", "2026-10-01\\u0000", "null", "20261001", "1234567"]:
    r = c.get(f"/api/jobs?date={lit.replace(chr(92)+'u0000','%00')}", headers=dis)
    print(f"  ?date={lit!r:<26} -> {r.status_code}")
r = c.post("/api/jobs", data='{"site_id":1,"title":"Date int","scheduled_date":20261001,"crew_size":2}', content_type="application/json", headers=dis)
print(f"  body scheduled_date=20261001 (int) -> {r.status_code}")
r = c.post("/api/jobs", json={"site_id": 1, "title": "Date max", "scheduled_date": "9999-12-31", "crew_size": 2}, headers=dis)
print(f"  body scheduled_date=9999-12-31 -> {r.status_code} (accepted far-future date: no business range check)")
r = c.post("/api/jobs", json={"site_id": 1, "title": "Date min", "scheduled_date": "0001-01-01", "crew_size": 2}, headers=dis)
print(f"  body scheduled_date=0001-01-01 -> {r.status_code}")

print("=== A7: datetimes")
for lit in ["2026-10-01T07:00", "2026-10-01 07:00", "2026-10-01T07:00:00Z", "2026-10-01T07:00:00+05:45", "2026-10-01", "20261001T0700", "0001-01-01T00:00", "9999-12-31T23:59", "2026-10-01T24:00"]:
    r = c.post("/api/time-entries", json={**base, "clock_in": lit}, headers=sup)
    print(f"  clock_in={lit!r:<30} -> {r.status_code} {(r.get_json() or {}).get('error', '')[:70]}")

