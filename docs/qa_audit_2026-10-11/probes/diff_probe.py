"""Run an identical request list against the backend tree in the CURRENT directory.

Usage (from a backend tree):  python diff_probe.py out.json
Works against both the pre-session commit and the current code; the outputs are then diffed.
"""

import hashlib
import json
import sys
from datetime import date, datetime, time, timedelta

sys.path.insert(0, ".")
from flask_jwt_extended import create_access_token  # noqa: E402

from app import create_app  # noqa: E402
from extensions import db  # noqa: E402
from models import Assignment, Job, JobSite, TimeEntry, User  # noqa: E402

app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:", "BCRYPT_ROUNDS": 4})
today = date.today()
results = []


def token(user):
    return {
        "Authorization": "Bearer "
        + create_access_token(
            identity=str(user.user_id),
            additional_claims={"user_id": user.user_id, "role": user.role},
        )
    }


def mk_staff(name, email, role):
    u = User(full_name=name, email=email, role=role, is_active=True)
    u.set_password("Password123!")
    return u


with app.app_context():
    db.create_all()
    admin = mk_staff("Adm In", "admin@t.com", "Admin")
    disp = mk_staff("Dis Patch", "disp@t.com", "Dispatcher")
    sup = mk_staff("Super Visor", "sup@t.com", "Supervisor")
    w1 = User(full_name="Worker One", email="w1@t.com", role="Worker", trade="Carpenter", is_active=True)
    w2 = User(full_name="Worker Two", email="w2@t.com", role="Worker", trade="Laborer", is_active=True)
    w3 = User(full_name="Worker Three", email="w3@t.com", role="Worker", trade="Plumber", is_active=True)
    site = JobSite(site_name="Site A", address="1 A Road", latitude=27.70, longitude=85.30, geofence_radius_m=200)
    site2 = JobSite(site_name="Site B", address="2 B Road", latitude=27.72, longitude=85.32, geofence_radius_m=300)
    tgt = mk_staff("Target Person", "target@t.com", "Dispatcher")
    db.session.add_all([admin, disp, sup, tgt, w1, w2, w3, site, site2])
    db.session.flush()
    j1 = Job(site=site, creator=disp, title="Job today", scheduled_date=today, crew_size=3, status="In progress")
    j2 = Job(site=site2, creator=disp, title="Job done", scheduled_date=today, crew_size=1, status="Completed")
    j3 = Job(site=site, creator=disp, title="Job tomorrow", scheduled_date=today + timedelta(days=1), crew_size=2, status="Scheduled")
    db.session.add_all([j1, j2, j3])
    db.session.flush()
    db.session.add_all([Assignment(job=j1, worker=w1, work_date=today), Assignment(job=j3, worker=w2, work_date=today + timedelta(days=1))])
    midnight = datetime.combine(today, time.min)
    # an overnight shift still open, a flagged pending entry, and a closed approved one
    e1 = TimeEntry(worker=w1, job=j1, clock_in=midnight - timedelta(hours=2), in_lat=27.70, in_lng=85.30, status="Pending")
    e2 = TimeEntry(worker=w1, job=j1, clock_in=midnight + timedelta(hours=1), clock_out=midnight + timedelta(hours=5), in_lat=27.71, in_lng=85.30, out_lat=27.70, out_lng=85.30, status="Pending")
    e2.apply_geofence(27.71, 85.30, "Clock-in")
    db.session.add_all([e1, e2])
    db.session.commit()
    H = {r: token(u) for r, u in (("admin", admin), ("disp", disp), ("sup", sup))}
    ids = {"admin": admin.user_id, "disp": disp.user_id, "w1": w1.user_id, "w2": w2.user_id, "w3": w3.user_id, "tgt": tgt.user_id, "j1": j1.job_id, "j3": j3.job_id, "site": site.site_id, "site2": site2.site_id, "e1": e1.entry_id, "e2": e2.entry_id}
    c = app.test_client()

    def call(label, method, url, who, body=None, raw=None):
        kw = {"headers": H[who]} if who else {}
        if raw is not None:
            kw.update(data=raw, content_type="application/json")
        elif body is not None:
            kw["json"] = body
        r = c.open(url, method=method, **kw)
        try:
            payload = r.get_json()
        except Exception:
            payload = r.get_data(as_text=True)[:200]
        if isinstance(payload, dict) and "kpis" in payload:
            payload["kpis"]["hours_today"] = None  # depends on the wall clock
        results.append({"label": label, "status": r.status_code, "body": payload})

    # ---- 1. update_user: single and multi-error bodies, in many orders --------------------------
    target = f"/api/users/{ids['tgt']}"
    cases = {
        "empty": {},
        "unknown_field": {"nope": 1},
        "name_ok": {"full_name": "Renamed Dispatcher"},
        "name_short": {"full_name": "A"},
        "phone_bad": {"phone": "abc"},
        "phone_ok": {"phone": "+977-1-5551234"},
        "email_bad": {"email": "bad"},
        "email_clash": {"email": "sup@t.com"},
        "email_clash_case": {"email": "SUP@T.COM"},
        "email_same_case": {"email": "DISP@t.com"},
        "role_bad": {"role": "Boss"},
        "role_worker_no_trade": {"role": "Worker"},
        "role_worker_trade": {"role": "Worker", "trade": "Welder"},
        "trade_short": {"trade": "x"},
        "trade_blank": {"trade": ""},
        "pw_short": {"password": "short"},
        "pw_blank": {"password": ""},
        "pw_ok": {"password": "NewPassw0rd!"},
        "pw_int": {"password": 12345678},
        "active_bad": {"is_active": "maybe"},
        "active_false": {"is_active": False},
        "active_str_true": {"is_active": "true"},
        # several mistakes at once: which one is reported first?
        "multi_name_phone": {"full_name": "A", "phone": "abc"},
        "multi_phone_email": {"phone": "abc", "email": "bad"},
        "multi_email_role": {"email": "bad", "role": "Boss"},
        "multi_role_pw": {"role": "Boss", "password": "short"},
        "multi_pw_active": {"password": "short", "is_active": "maybe"},
        "multi_trade_pw": {"trade": "x", "password": "short"},
        "multi_all": {"full_name": "A", "phone": "abc", "email": "bad", "role": "Boss", "trade": "x", "password": "s", "is_active": "m"},
        "role_staff_no_pw_for_worker": {"role": "Supervisor"},
    }
    for name, body in cases.items():
        call(f"patch_user:{name}", "PATCH", target, "admin", body)
        db.session.expire_all()
    # self-protection
    me = f"/api/users/{ids['admin']}"
    call("self_demote", "PATCH", me, "admin", {"role": "Dispatcher"})
    call("self_deactivate", "PATCH", me, "admin", {"is_active": False})
    call("self_keep_admin", "PATCH", me, "admin", {"role": "Admin", "full_name": "Admin Renamed"})
    call("patch_user:missing", "PATCH", "/api/users/424242", "admin", {})
    call("patch_user:forbidden", "PATCH", target, "disp", {"full_name": "Zzz"})
    call("patch_user:noauth", "PATCH", target, None, {})
    call("patch_user:non_object", "PATCH", target, "admin", raw="[1,2]")
    call("worker_promote_needs_pw", "PATCH", f"/api/users/{ids['w3']}", "admin", {"role": "Dispatcher"})
    call("worker_promote_with_pw", "PATCH", f"/api/users/{ids['w3']}", "admin", {"role": "Dispatcher", "password": "Prom0ted!1"})

    # ---- 2. dashboard (whole payload) ----------------------------------------------------------
    for who in ("admin", "disp", "sup"):
        call(f"dashboard:{who}", "GET", "/api/dashboard", who)

    # ---- 3. CRUD / validation batch on jobs, sites, assignments, time entries --------------------
    d = today.isoformat()
    for i, body in enumerate(
        [
            {"site_id": ids["site"], "title": "New job", "scheduled_date": d, "crew_size": 2},
            {"site_id": ids["site"], "title": "ab", "scheduled_date": d, "crew_size": 2},
            {"site_id": 987654, "title": "New job 2", "scheduled_date": d, "crew_size": 2},
            {"site_id": ids["site"], "title": "New job 3", "scheduled_date": "not-a-date", "crew_size": 2},
            {"site_id": ids["site"], "title": "New job 4", "scheduled_date": d, "crew_size": 0},
            {"site_id": ids["site"], "title": "New job 5", "scheduled_date": d, "crew_size": 51},
            {"site_id": ids["site"], "title": "New job 6", "scheduled_date": d, "crew_size": 2, "status": "Done"},
            {"site_id": None, "title": "New job 7", "scheduled_date": d, "crew_size": 2},
            {"title": "No site", "scheduled_date": d, "crew_size": 2},
        ]
    ):
        call(f"create_job:{i}", "POST", "/api/jobs", "disp", body)
    for i, q in enumerate(["", f"?date={d}", "?status=Completed", f"?site_id={ids['site']}", "?status=Nope", "?date=bad", "?site_id=abc"]):
        call(f"list_jobs:{i}", "GET", "/api/jobs" + q, "disp")
    for i, body in enumerate(
        [
            {"title": "Renamed job"},
            {"crew_size": 1},
            {"scheduled_date": (today + timedelta(days=3)).isoformat()},
            {"status": "Completed"},
            {"status": "Done"},
            {"description": ""},
            {"site_id": ids["site2"]},
            {"site_id": 987654},
        ]
    ):
        call(f"patch_job:{i}", "PATCH", f"/api/jobs/{ids['j1']}", "disp", body)
    call("patch_job:other_site", "PATCH", f"/api/jobs/{ids['j3']}", "disp", {"scheduled_date": (today + timedelta(days=4)).isoformat()})
    call("get_job", "GET", f"/api/jobs/{ids['j1']}", "sup")
    call("get_job_missing", "GET", "/api/jobs/424242", "sup")

    for i, body in enumerate(
        [
            {"site_name": "New Site", "address": "99 New Address", "latitude": 27.7, "longitude": 85.3},
            {"site_name": "N", "address": "99 New Address", "latitude": 27.7, "longitude": 85.3},
            {"site_name": "Edge", "address": "99 New Address", "latitude": 91, "longitude": 85.3},
            {"site_name": "Edge", "address": "99 New Address", "latitude": 27.7, "longitude": 181},
            {"site_name": "Edge", "address": "99 New Address", "latitude": 27.7, "longitude": 85.3, "geofence_radius_m": 24},
            {"site_name": "Edge", "address": "99 New Address", "latitude": 27.7, "longitude": 85.3, "geofence_radius_m": 5000},
            {"site_name": "Edge", "address": "99 New Address", "latitude": "abc", "longitude": 85.3},
        ]
    ):
        call(f"create_site:{i}", "POST", "/api/sites", "disp", body)
    call("patch_site", "PATCH", f"/api/sites/{ids['site']}", "disp", {"geofence_radius_m": 450, "site_name": "Site A2"})
    call("list_sites", "GET", "/api/sites", "sup")

    for i, body in enumerate(
        [
            {"job_id": ids["j1"], "user_id": ids["w2"]},
            {"job_id": ids["j1"], "user_id": ids["w2"]},
            {"job_id": ids["j1"], "user_id": ids["w1"]},
            {"job_id": ids["j3"], "user_id": ids["w1"]},
            {"job_id": ids["j1"], "user_id": ids["admin"]},
            {"job_id": 987654, "user_id": ids["w3"]},
            {"job_id": ids["j1"], "user_id": 987654},
            {"job_id": ids["j1"], "user_id": ids["w3"], "work_date": "2030-01-01"},
            {"job_id": ids["j1"]},
        ]
    ):
        call(f"assign:{i}", "POST", "/api/assignments", "disp", body)
    call("list_assign", "GET", "/api/assignments", "disp")
    call("delete_assign_missing", "DELETE", "/api/assignments/424242", "disp")

    base = {"user_id": ids["w1"], "job_id": ids["j1"], "clock_in": f"{d}T07:00", "in_lat": 27.70, "in_lng": 85.30}
    entries = [
        base,
        {**base, "clock_in": f"{d}T08:00"},
        {**base, "clock_in": f"{d}T12:00", "in_lat": 27.75},
        {**base, "clock_in": f"{d}T13:00", "clock_out": f"{d}T12:30", "out_lat": 27.7, "out_lng": 85.3},
        {**base, "clock_in": f"{d}T14:00", "clock_out": f"{d}T15:00"},
        {**base, "user_id": ids["w3"]},
        {**base, "user_id": ids["admin"]},
        {**base, "job_id": ids["j3"]},
        {**base, "in_lat": 95},
        {**base, "clock_in": "garbage"},
    ]
    for i, body in enumerate(entries):
        call(f"entry:{i}", "POST", "/api/time-entries", "sup", body)
    call("entry_forbidden", "POST", "/api/time-entries", "disp", base)
    for i, q in enumerate(["", "?flagged=true", "?status=Pending", "?status=Bad", f"?worker={ids['w1']}", f"?date={d}", "?flagged=maybe"]):
        call(f"list_entries:{i}", "GET", "/api/time-entries" + q, "admin")
    call("clockout_ok", "PATCH", f"/api/time-entries/{ids['e1']}/clock-out", "sup", {"clock_out": (midnight + timedelta(hours=3)).isoformat(timespec="minutes"), "out_lat": 27.7, "out_lng": 85.3})
    call("clockout_twice", "PATCH", f"/api/time-entries/{ids['e1']}/clock-out", "sup", {"clock_out": (midnight + timedelta(hours=4)).isoformat(timespec="minutes"), "out_lat": 27.7, "out_lng": 85.3})
    call("approve_ok", "PATCH", f"/api/time-entries/{ids['e2']}/approve", "sup", {"decision": "Approved", "edit_reason": "Looks right"})
    call("approve_again", "PATCH", f"/api/time-entries/{ids['e2']}/approve", "sup", {"decision": "Rejected", "edit_reason": "Changed mind"})
    call("approve_forbidden", "PATCH", f"/api/time-entries/{ids['e1']}/approve", "disp", {"decision": "Approved", "edit_reason": "no"})
    call("approve_no_reason", "PATCH", f"/api/time-entries/{ids['e1']}/approve", "sup", {"decision": "Approved"})
    for path in ("hours-by-worker", "hours-by-job", "flagged", "hours.csv"):
        call(f"report:{path}", "GET", f"/api/reports/{path}?from={(today - timedelta(days=2)).isoformat()}&to={(today + timedelta(days=2)).isoformat()}", "admin")
    call("report_bad_range", "GET", "/api/reports/hours-by-worker?from=2026-10-05&to=2026-10-01", "admin")
    call("dashboard_after", "GET", "/api/dashboard", "admin")
    call("users_list", "GET", "/api/users", "admin")
    call("users_filter", "GET", "/api/users?role=Worker&active=true", "disp")
    call("create_user_ok", "POST", "/api/users", "admin", {"full_name": "New Person", "email": "np@t.com", "role": "Dispatcher", "password": "Sup3rSecret!"})
    call("create_user_dup", "POST", "/api/users", "admin", {"full_name": "New Person", "email": "NP@t.com", "role": "Dispatcher", "password": "Sup3rSecret!"})
    call("create_user_worker", "POST", "/api/users", "admin", {"full_name": "New Worker", "email": "nw@t.com", "role": "Worker", "trade": "Welder"})
    call("create_user_worker_no_trade", "POST", "/api/users", "admin", {"full_name": "New Worker", "email": "nw2@t.com", "role": "Worker"})

# ---- 4. route generation: hashes over a wide sample --------------------------------------------
import simulation  # noqa: E402
from kathmandu_geo import LANDMARKS  # noqa: E402

sites = list(LANDMARKS.values())
route_hashes = {}
for user_id in range(1, 41):
    for offset in (-2, 0, 1, 9, 100):
        day = date(2026, 10, 11) + timedelta(days=offset)
        lat, lng = sites[(user_id * 7 + offset) % len(sites)]
        route = simulation._build_route(user_id, day, lat, lng)
        route_hashes[f"{user_id}:{offset}"] = hashlib.sha1(repr(route).encode()).hexdigest()

json.dump({"results": results, "routes": route_hashes}, open(sys.argv[1], "w"), indent=1, sort_keys=True, default=str)
print(f"{len(results)} requests, {len(route_hashes)} routes -> {sys.argv[1]}")
