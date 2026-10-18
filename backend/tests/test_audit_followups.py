"""Regression tests for audit findings D-10, D-11 and D-14 (D-13 lives in test_auth_hardening.py)."""

import os
import subprocess
import sys

import pytest
from flask_jwt_extended import create_access_token

from auth import session_claims
from extensions import db
from models import User
from tests.conftest import PASSWORD, login

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ---- D-14: a password reset ends the user's existing sessions ------------------------------------------


def test_resetting_a_password_ends_the_old_sessions_at_once(client, admin_headers):
    old = login(client, "dispatch@test.com")
    assert client.get("/api/jobs", headers=old).status_code == 200
    target = User.query.filter_by(email="dispatch@test.com").one().user_id
    res = client.patch(
        f"/api/users/{target}", json={"password": "BrandNew#12345"}, headers=admin_headers
    )
    assert res.status_code == 200
    stale = client.get("/api/jobs", headers=old)
    assert stale.status_code == 401 and "log in again" in stale.get_json()["error"]
    assert client.get("/api/auth/me", headers=old).status_code == 401
    fresh = client.post(
        "/api/auth/login", json={"email": "dispatch@test.com", "password": "BrandNew#12345"}
    )
    assert fresh.status_code == 200
    assert (
        client.get(
            "/api/jobs", headers={"Authorization": "Bearer " + fresh.get_json()["token"]}
        ).status_code
        == 200
    )


def test_other_users_sessions_and_unrelated_edits_do_not_end_a_session(client, admin_headers):
    dispatcher, supervisor = login(client, "dispatch@test.com"), login(client, "super@test.com")
    target = User.query.filter_by(email="dispatch@test.com").one().user_id
    assert (
        client.patch(
            f"/api/users/{target}", json={"password": "BrandNew#12345"}, headers=admin_headers
        ).status_code
        == 200
    )
    assert client.get("/api/jobs", headers=supervisor).status_code == 200  # someone else: untouched
    for changes in ({"full_name": "Renamed Person"}, {"phone": "+977-1-5551234"}, {"password": ""}):
        assert (
            client.patch(
                f"/api/users/{User.query.filter_by(email='super@test.com').one().user_id}",
                json=changes,
                headers=admin_headers,
            ).status_code
            == 200
        )
        assert client.get("/api/jobs", headers=supervisor).status_code == 200
    assert client.get("/api/jobs", headers=dispatcher).status_code == 401


def test_setting_the_same_password_again_still_ends_old_sessions(client, admin_headers):
    """A new bcrypt salt gives a new hash even for an identical password, so every reset ends sessions."""
    old = login(client, "super@test.com")
    uid = User.query.filter_by(email="super@test.com").one().user_id
    assert (
        client.patch(
            f"/api/users/{uid}", json={"password": PASSWORD}, headers=admin_headers
        ).status_code
        == 200
    )
    assert client.get("/api/jobs", headers=old).status_code == 401


def test_a_token_without_the_session_stamp_is_refused(client, app):
    user = User.query.filter_by(email="admin@test.com").one()
    legacy = create_access_token(
        identity=str(user.user_id), additional_claims={"user_id": user.user_id, "role": user.role}
    )
    res = client.get("/api/auth/me", headers={"Authorization": f"Bearer {legacy}"})
    assert res.status_code == 401
    wrong = create_access_token(
        identity=str(user.user_id), additional_claims={**session_claims(user), "pwv": "0" * 16}
    )
    assert (
        client.get("/api/auth/me", headers={"Authorization": f"Bearer {wrong}"}).status_code == 401
    )
    good = create_access_token(identity=str(user.user_id), additional_claims=session_claims(user))
    assert (
        client.get("/api/auth/me", headers={"Authorization": f"Bearer {good}"}).status_code == 200
    )


def test_the_stamp_does_not_expose_the_password_hash(app):
    user = User.query.filter_by(email="admin@test.com").one()
    assert len(user.session_stamp()) == 16 and user.session_stamp() not in user.password_hash
    assert User(password_hash=None).session_stamp() == User(password_hash=None).session_stamp()


def test_roles_still_follow_the_database_not_the_token(client, admin_headers):
    token = login(client, "dispatch@test.com")
    User.query.filter_by(email="dispatch@test.com").one().role = "Supervisor"
    db.session.commit()
    assert (
        client.post("/api/safety/workers/4/accident", headers=token).status_code != 403
    )  # now allowed
    User.query.filter_by(email="dispatch@test.com").one().role = "Dispatcher"
    db.session.commit()
    assert client.post("/api/safety/workers/4/accident", headers=token).status_code == 403


# ---- D-11: time zones in clock times -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "stamp", ["2026-10-01T07:00:00Z", "2026-10-01T07:00:00+05:45", "2026-10-01T07:00-02:00"]
)
def test_clock_times_with_a_zone_are_rejected_not_silently_shifted(
    client, supervisor_headers, ids, stamp
):
    body = {
        "user_id": ids["marcus"],
        "job_id": ids["job_a"],
        "clock_in": stamp,
        "in_lat": 43.6591,
        "in_lng": -79.3503,
    }
    res = client.post("/api/time-entries", json=body, headers=supervisor_headers)
    assert (
        res.status_code == 400
        and res.get_json()["field"] == "clock_in"
        and "time zone" in res.get_json()["error"]
    )


def test_zone_free_times_still_work_with_t_or_space_and_seconds(client, supervisor_headers, ids):
    for stamp in ("2026-10-01T07:00", "2026-10-01 07:00:00"):
        body = {
            "user_id": ids["marcus"],
            "job_id": ids["job_a"],
            "clock_in": stamp,
            "in_lat": 43.6591,
            "in_lng": -79.3503,
        }
        res = client.post("/api/time-entries", json=body, headers=supervisor_headers)
        assert res.status_code in (201, 409)  # 409 only for the overlap with the first one
        assert res.status_code == 201 or "Overlaps" in res.get_json()["error"]


# ---- D-10: the seed command checks the database BEFORE it connects -----------------------------------------------


def run_seed(args, url, extra_env=None):
    env = {
        k: v for k, v in os.environ.items() if k not in ("DATABASE_URL", "APP_ENV", "SECRET_KEY")
    }
    env.update({"DATABASE_URL": url, "PYTHONDONTWRITEBYTECODE": "1", **(extra_env or {})})
    p = subprocess.run(
        [sys.executable, "seed.py", *args],
        cwd=BACKEND,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        input="",
    )
    return p.returncode, (p.stdout + p.stderr)


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://user:hunter2secret@127.0.0.1:5432/other",
        "mysql://user:hunter2secret@127.0.0.1/other",
    ],
)
def test_reset_of_a_foreign_database_is_refused_cleanly_before_any_connection(url):
    code, out = run_seed(["--reset", "--yes"], url)
    assert code == 1 and "Refusing to reset" in out
    assert (
        "Traceback" not in out and "hunter2secret" not in out and "ModuleNotFoundError" not in out
    )


def test_an_unreachable_database_gives_a_one_line_error_without_the_url(tmp_path):
    missing = (tmp_path / "no" / "such" / "dir" / "x.db").as_posix()
    for args in ([], ["--reset", "--yes"]):
        code, out = run_seed(args, "sqlite:///" + missing)
        assert code == 1 and "Could not open or write the database" in out
        assert "Traceback" not in out and "such" not in out


def test_ordinary_seeding_of_a_missing_driver_is_also_a_clean_error():
    code, out = run_seed([], "postgresql://user:hunter2secret@127.0.0.1:5432/other")
    assert (
        code == 1
        and "Could not open or write the database" in out
        and "hunter2secret" not in out
        and "Traceback" not in out
    )


def test_production_reset_is_refused_before_the_app_is_built():
    code, out = run_seed(["--reset", "--yes"], "sqlite:///:memory:", {"APP_ENV": "production"})
    assert (
        code == 1 and "APP_ENV=production" in out and "SECRET_KEY" not in out
    )  # refused before the secret check


def test_a_normal_seed_and_reset_still_work_on_a_temporary_file(tmp_path):
    url = "sqlite:///" + (tmp_path / "ok.db").as_posix()
    assert run_seed([], url)[0] == 0
    code, out = run_seed([], url)
    assert code == 0 and "nothing was changed" in out
    code, out = run_seed(["--reset", "--yes"], url)
    assert code == 0 and "Seeded:" in out
