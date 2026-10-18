"""D-08: login must not reveal, through response time, whether an email has an account.

Before the fix, `user is None or not user.check_password(...)` skipped bcrypt for unknown emails: at cost 12
a known email took ~213 ms and an unknown one ~0.9 ms. Now every failed password check does one bcrypt
verification (against a dummy hash when there is nothing real to compare with).

Timing is inherently noisy, so the timing tests assert a loose ratio (the old gap was ~250x) and the
deterministic tests count bcrypt calls. Equivalence is NOT claimed to be perfect: see docs.
"""

import statistics
import time

import bcrypt
import pytest

import models
from app import create_app
from extensions import db
from models import User
from tests.conftest import PASSWORD, _load_fixture_data


@pytest.fixture
def bcrypt_calls(monkeypatch):
    """Count real bcrypt verifications."""
    calls = []
    real = bcrypt.checkpw

    def counting(password, hashed):
        calls.append(len(password))
        return real(password, hashed)

    monkeypatch.setattr(models.bcrypt, "checkpw", counting)
    return calls


def login(client, email, password, **kw):
    return client.post("/api/auth/login", json={"email": email, "password": password}, **kw)


def test_every_failed_login_does_exactly_one_bcrypt_verification(app, client, bcrypt_calls):
    worker = User.query.filter_by(email="marcus@test.com").one()
    worker.password_hash = None  # a Worker record: no password at all
    inactive = User.query.filter_by(email="super@test.com").one()
    inactive.is_active = False
    db.session.commit()
    cases = {
        "unknown email": ("nobody@test.com", "wrong-password"),
        "known email, wrong password": ("admin@test.com", "wrong-password"),
        "worker without a password": ("marcus@test.com", "wrong-password"),
        "inactive account, wrong password": ("super@test.com", "wrong-password"),
        "inactive account, right password": ("super@test.com", PASSWORD),
    }
    for name, (email, pw) in cases.items():
        bcrypt_calls.clear()
        res = login(client, email, pw)
        assert len(bcrypt_calls) == 1, (name, len(bcrypt_calls))
        assert res.status_code in (401, 403)
    bcrypt_calls.clear()
    assert login(client, "dispatch@test.com", PASSWORD).status_code == 200
    assert len(bcrypt_calls) == 1  # a successful login is one verification too


def test_overlong_passwords_skip_bcrypt_for_known_and_unknown_emails_alike(
    app, client, bcrypt_calls
):
    for email in ("admin@test.com", "nobody@test.com"):
        bcrypt_calls.clear()
        assert login(client, email, "a" * 100).status_code == 401
        assert bcrypt_calls == []  # >72 bytes can never match; same (fast) path for both


def test_a_throttled_request_costs_no_bcrypt_for_any_email(app, client, bcrypt_calls):
    for _ in range(app.config["LOGIN_MAX_FAILURES_PER_ACCOUNT"]):
        login(client, "admin@test.com", "bad")
    bcrypt_calls.clear()
    assert login(client, "admin@test.com", PASSWORD).status_code == 429
    assert bcrypt_calls == []


def test_all_failure_responses_look_identical_apart_from_the_documented_cases(client):
    unknown = login(client, "nobody@test.com", "wrong-password")
    wrong = login(client, "admin@test.com", "wrong-password")
    assert unknown.status_code == wrong.status_code == 401
    assert (
        unknown.get_json()
        == wrong.get_json()
        == {"error": "Invalid email or password.", "field": "password"}
    )
    assert set(unknown.headers) == set(wrong.headers)
    assert unknown.headers["Content-Length"] == wrong.headers["Content-Length"]


def test_the_dummy_hash_is_cached_per_cost_and_never_matches(app):
    first = User._dummy_hash(app.config["BCRYPT_ROUNDS"])
    assert User._dummy_hash(app.config["BCRYPT_ROUNDS"]) is first
    assert first != User._dummy_hash(5)
    assert not bcrypt.checkpw(PASSWORD.encode(), first)
    assert User.burn_password_check(PASSWORD) is False


def test_the_dummy_check_uses_the_same_cost_as_real_hashes(app):
    assert (
        int(User._dummy_hash(app.config["BCRYPT_ROUNDS"]).split(b"$")[2])
        == app.config["BCRYPT_ROUNDS"]
    )


def _median_ms(client, email, n):
    samples = []
    for _ in range(n):
        t0 = time.perf_counter()
        login(client, email, "wrong-password")
        samples.append((time.perf_counter() - t0) * 1000)
    return statistics.median(samples), max(samples)


def test_unknown_and_known_emails_take_comparable_time():
    """Cost 10 (~60 ms per bcrypt) so the signal clearly beats the noise; old ratio was about 1 : 250."""
    app = create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "BCRYPT_ROUNDS": 10,
            "LOGIN_RATE_LIMIT_ENABLED": False,
        }
    )
    with app.app_context():
        db.create_all()
        _load_fixture_data()
        client = app.test_client()
        for email in ("admin@test.com", "nobody@test.com"):
            login(client, email, "warm-up")  # prime caches
        known, _ = _median_ms(client, "admin@test.com", 9)
        unknown, _ = _median_ms(client, "nobody@test.com", 9)
        no_password, _ = _median_ms(client, "marcus@test.com", 9)  # a Worker record
        db.session.remove()
        db.drop_all()
    assert (
        known > 20
    ), f"bcrypt cost 10 should take well over 20 ms (got {known:.1f}); timing test is not measuring bcrypt"
    assert 0.6 < unknown / known < 1.6, f"known {known:.1f} ms vs unknown {unknown:.1f} ms"
    assert 0.6 < no_password / known < 1.6, f"known {known:.1f} ms vs worker {no_password:.1f} ms"


def test_failed_logins_log_nothing_secret(client, caplog):
    caplog.set_level("DEBUG")
    login(client, "admin@test.com", "super-secret-guess")
    login(client, "nobody@test.com", "another-secret-guess")
    assert "secret-guess" not in caplog.text and PASSWORD not in caplog.text


def test_login_throttling_and_retry_after_are_unchanged(app, client):
    limit = app.config["LOGIN_MAX_FAILURES_PER_ACCOUNT"]
    codes = [login(client, "nobody@test.com", "x").status_code for _ in range(limit + 2)]
    assert codes == [401] * limit + [429, 429]
    blocked = login(client, "nobody@test.com", "x")
    assert blocked.headers["Retry-After"].isdigit() and int(blocked.headers["Retry-After"]) >= 1
    # unknown and real accounts are throttled identically
    real = [login(client, "admin@test.com", "x").status_code for _ in range(limit + 2)]
    assert real == codes
