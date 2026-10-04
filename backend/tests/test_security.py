"""Security rules (hashing, tokens, roles) and edge cases a reviewer might try directly
against the API rather than through the UI."""

from datetime import timedelta

import pytest
from flask_jwt_extended import create_access_token

from app import create_app
from extensions import db
from models import Job, JobSite, User
from tests.conftest import DAY, PASSWORD

# ---- Passwords --------------------------------------------------------------------------


def test_passwords_are_stored_only_as_bcrypt_hashes(app):
    user = User.query.filter_by(email="admin@test.com").first()
    assert user.password_hash != PASSWORD
    assert user.password_hash.startswith("$2")  # bcrypt
    assert user.check_password(PASSWORD) and not user.check_password("wrong-password")


def test_wrong_password_is_401_with_the_same_message_as_unknown_email(client):
    wrong = client.post(
        "/api/auth/login", json={"email": "admin@test.com", "password": "nope-nope"}
    )
    unknown = client.post(
        "/api/auth/login", json={"email": "nobody@test.com", "password": PASSWORD}
    )
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.get_json()["error"] == unknown.get_json()["error"]


def test_workers_and_deactivated_staff_cannot_log_in(client, app):
    worker = User.query.filter_by(email="marcus@test.com").first()
    worker.set_password(PASSWORD)
    User.query.filter_by(email="super@test.com").first().is_active = False
    db.session.commit()
    for email in ("marcus@test.com", "super@test.com"):
        res = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
        assert res.status_code == 403, email


# ---- Tokens -------------------------------------------------------------------------------


def _token(app, email, **kwargs):
    user = User.query.filter_by(email=email).first()
    claims = {"user_id": user.user_id, "role": user.role}
    return create_access_token(identity=str(user.user_id), additional_claims=claims, **kwargs)


def test_expired_token_is_401(client, app):
    token = _token(app, "admin@test.com", expires_delta=timedelta(seconds=-1))
    res = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 401 and "expired" in res.get_json()["error"]


def test_tampered_token_is_401(client, app):
    token = _token(app, "admin@test.com")
    res = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token[:-4]}AAAA"})
    assert res.status_code == 401


def test_tokens_expire_after_one_shift_by_default(app):
    assert app.config["JWT_ACCESS_TOKEN_EXPIRES"] == timedelta(hours=8)


def test_deactivating_a_user_locks_out_their_existing_token(client, app):
    token = _token(app, "dispatch@test.com")
    User.query.filter_by(email="dispatch@test.com").first().is_active = False
    db.session.commit()
    res = client.get("/api/jobs", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 403


# ---- Roles: every restricted route refuses the wrong role -------------------------------

RESTRICTED = [
    # (method, path, roles that must be refused)
    ("POST", "/api/users", ["dispatch@test.com", "super@test.com"]),
    ("PATCH", "/api/users/1", ["dispatch@test.com", "super@test.com"]),
    ("POST", "/api/sites", ["super@test.com"]),
    ("PATCH", "/api/sites/1", ["super@test.com"]),
    ("POST", "/api/jobs", ["super@test.com"]),
    ("PATCH", "/api/jobs/1", ["super@test.com"]),
    ("POST", "/api/assignments", ["super@test.com"]),
    ("DELETE", "/api/assignments/1", ["super@test.com"]),
    ("POST", "/api/time-entries", ["dispatch@test.com"]),
    ("PATCH", "/api/time-entries/1/clock-out", ["dispatch@test.com"]),
    ("PATCH", "/api/time-entries/1/approve", ["dispatch@test.com"]),
]


@pytest.mark.parametrize("method,path,refused", RESTRICTED)
def test_wrong_role_gets_403(client, method, path, refused):
    for email in refused:
        res = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
        headers = {"Authorization": f"Bearer {res.get_json()['token']}"}
        res = client.open(path, method=method, json={}, headers=headers)
        assert res.status_code == 403, (method, path, email)


def test_every_api_route_requires_a_token(client, app):
    open_routes = {"/api/auth/login", "/api/health"}
    for rule in app.url_map.iter_rules():
        if not rule.rule.startswith("/api/") or rule.rule in open_routes:
            continue
        path = rule.rule.replace("<int:", "").replace(">", "").replace("job_id", "1")
        path = path.replace("user_id", "1").replace("site_id", "1").replace("assignment_id", "1")
        path = path.replace("entry_id", "1")
        for method in rule.methods - {"HEAD", "OPTIONS"}:
            assert client.open(path, method=method).status_code == 401, (method, path)


# ---- Configuration ------------------------------------------------------------------------


def test_cors_origins_come_from_the_environment(monkeypatch):
    import importlib

    import config

    monkeypatch.setenv("CORS_ORIGINS", "https://a.example, https://b.example")
    assert importlib.reload(config).Config.CORS_ORIGINS == [
        "https://a.example",
        "https://b.example",
    ]
    monkeypatch.delenv("CORS_ORIGINS")
    assert "http://localhost:5173" in importlib.reload(config).Config.CORS_ORIGINS


# ---- Edge cases ---------------------------------------------------------------------------


@pytest.mark.parametrize("radius", [0, -50, 24, 5001])
def test_geofence_radius_outside_25_to_5000_is_rejected(client, dispatcher_headers, radius):
    body = {
        "site_name": "Edge Site",
        "address": "1 Test Road",
        "latitude": 27.7,
        "longitude": 85.3,
        "geofence_radius_m": radius,
    }
    res = client.post("/api/sites", json=body, headers=dispatcher_headers)
    assert res.status_code == 400 and res.get_json()["field"] == "geofence_radius_m"
    res = client.patch(
        "/api/sites/1", json={"geofence_radius_m": radius}, headers=dispatcher_headers
    )
    assert res.status_code == 400 and res.get_json()["field"] == "geofence_radius_m"


def test_clock_out_equal_to_clock_in_is_rejected(client, supervisor_headers):
    marcus = User.query.filter_by(email="marcus@test.com").first()
    job = Job.query.filter_by(title="Level 4 framing").first()
    body = {
        "user_id": marcus.user_id,
        "job_id": job.job_id,
        "clock_in": f"{DAY}T07:00",
        "in_lat": 43.6591,
        "in_lng": -79.3503,
        "clock_out": f"{DAY}T07:00",
        "out_lat": 43.6591,
        "out_lng": -79.3503,
    }
    res = client.post("/api/time-entries", json=body, headers=supervisor_headers)
    assert res.status_code == 400 and res.get_json()["field"] == "clock_out"


def test_job_with_no_crew_and_worker_without_trade_render_everywhere(client, admin_headers, app):
    site = JobSite.query.first()
    db.session.add(
        Job(
            site=site,
            creator=User.query.first(),
            title="Empty crew job",
            scheduled_date=DAY,
            crew_size=2,
            status="Scheduled",
        )
    )
    db.session.add(
        User(full_name="No Trade", email="notrade@test.com", role="Worker", is_active=True)
    )
    db.session.commit()
    for path in (
        "/api/jobs",
        "/api/users",
        "/api/dashboard",
        "/api/map/live",
        f"/api/reports/hours-by-job?from={DAY}&to={DAY}",
        f"/api/reports/hours.csv?from={DAY}&to={DAY}",
    ):
        assert client.get(path, headers=admin_headers).status_code == 200, path
    job = next(
        j
        for j in client.get("/api/jobs", headers=admin_headers).get_json()["jobs"]
        if j["title"] == "Empty crew job"
    )
    assert job["assigned_count"] == 0 and job["crew"] == []


def test_every_read_endpoint_works_on_an_empty_database():
    # Only one admin account exists: no sites, jobs, assignments or time entries.
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})
    with app.app_context():
        db.drop_all()
        db.create_all()
        admin = User(full_name="Only Admin", email="only@test.com", role="Admin", is_active=True)
        admin.set_password(PASSWORD)
        db.session.add(admin)
        db.session.commit()
        client = app.test_client()
        token = client.post(
            "/api/auth/login", json={"email": "only@test.com", "password": PASSWORD}
        ).get_json()["token"]
        headers = {"Authorization": f"Bearer {token}"}
        for path in (
            "/api/dashboard",
            "/api/jobs",
            "/api/sites",
            "/api/users",
            "/api/assignments",
            "/api/time-entries",
            "/api/reports/hours-by-worker",
            "/api/reports/hours-by-job",
            "/api/reports/flagged",
            "/api/reports/hours.csv",
            "/api/map/live",
            "/api/map/sim-clock",
            "/api/map/bounds",
        ):
            assert client.get(path, headers=headers).status_code == 200, path
        live = client.get("/api/map/live", headers=headers).get_json()
        assert live["job_sites"] == [] and live["workers"] == []
        db.session.remove()
