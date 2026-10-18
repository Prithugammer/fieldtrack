"""Login throttling, production secret enforcement, security headers and token/role freshness."""

import pytest

from app import create_app
import config  # looked up dynamically: other tests reload this module, which replaces its classes
from extensions import db
from models import User
from security import LoginRateLimiter
from tests.conftest import PASSWORD, login

GOOD_SECRET = "k3Jx9" * 8  # 40 characters, not a placeholder
FAKE_PRODUCTION = {
    "APP_ENV": "production",
    "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
    "BCRYPT_ROUNDS": 4,
}


def bad_login(client, email="admin@test.com", **kwargs):
    return client.post(
        "/api/auth/login", json={"email": email, "password": "wrong-password"}, **kwargs
    )


@pytest.fixture
def clock(app):
    """Replace the limiter's clock so throttling is deterministic (no sleeping)."""
    now = {"t": 1000.0}
    app.extensions["login_limiter"].clock = lambda: now["t"]
    return now


# ---- login throttling ---------------------------------------------------------------------------


def test_repeated_wrong_passwords_are_throttled_with_429(client, clock):
    limit = client.application.config["LOGIN_MAX_FAILURES_PER_ACCOUNT"]
    for _ in range(limit):
        assert bad_login(client).status_code == 401
    res = bad_login(client)
    assert res.status_code == 429
    body = res.get_json()
    assert set(body) == {"error", "field"} and "Too many" in body["error"]
    assert int(res.headers["Retry-After"]) >= 1


def test_thirty_consecutive_bad_logins_are_not_all_processed(client, clock):
    statuses = [bad_login(client).status_code for _ in range(30)]
    assert statuses.count(401) == client.application.config["LOGIN_MAX_FAILURES_PER_ACCOUNT"]
    assert statuses.count(429) == 30 - statuses.count(401)


def test_the_correct_password_is_also_refused_while_blocked_then_works_after_the_window(
    client, app, clock
):
    window = app.config["LOGIN_RATE_WINDOW_SECONDS"]
    for _ in range(app.config["LOGIN_MAX_FAILURES_PER_ACCOUNT"]):
        bad_login(client)
    ok = {"email": "admin@test.com", "password": PASSWORD}
    assert client.post("/api/auth/login", json=ok).status_code == 429
    clock["t"] += window - 1  # still inside the window
    assert client.post("/api/auth/login", json=ok).status_code == 429
    clock["t"] += 2  # the failures have aged out: the block is temporary, never permanent
    assert client.post("/api/auth/login", json=ok).status_code == 200


def test_blocked_attempts_do_not_extend_the_block(client, app, clock):
    window = app.config["LOGIN_RATE_WINDOW_SECONDS"]
    for _ in range(app.config["LOGIN_MAX_FAILURES_PER_ACCOUNT"]):
        bad_login(client)
    for _ in range(50):  # hammering while blocked records nothing
        clock["t"] += 1
        bad_login(client)
    clock["t"] = 1000.0 + window + 1
    assert bad_login(client).status_code == 401


def test_retry_after_counts_down(client, clock):
    for _ in range(client.application.config["LOGIN_MAX_FAILURES_PER_ACCOUNT"]):
        bad_login(client)
    first = int(bad_login(client).headers["Retry-After"])
    clock["t"] += 100
    assert int(bad_login(client).headers["Retry-After"]) == first - 100


def test_successful_logins_are_never_throttled(client, clock):
    for _ in range(40):
        assert login(client, "admin@test.com")


def test_a_success_clears_that_accounts_failures(client, app, clock):
    for _ in range(app.config["LOGIN_MAX_FAILURES_PER_ACCOUNT"] - 1):
        bad_login(client)
    login(client, "admin@test.com")
    for _ in range(app.config["LOGIN_MAX_FAILURES_PER_ACCOUNT"]):
        assert bad_login(client).status_code == 401  # a fresh allowance


def test_one_accounts_failures_do_not_block_another(client, clock):
    for _ in range(client.application.config["LOGIN_MAX_FAILURES_PER_ACCOUNT"] + 3):
        bad_login(client, "admin@test.com")
    assert login(client, "dispatch@test.com")


def test_unknown_emails_are_throttled_exactly_like_real_ones(client, clock):
    real = [bad_login(client, "admin@test.com").status_code for _ in range(8)]
    ghost = [bad_login(client, "ghost@test.com").status_code for _ in range(8)]
    assert real == ghost  # nothing reveals which emails exist


def test_per_client_limit_catches_a_password_spray_across_many_accounts(client, app, clock):
    limit = app.config["LOGIN_MAX_FAILURES_PER_CLIENT"]
    results = [bad_login(client, f"user{i}@test.com").status_code for i in range(limit + 3)]
    assert results[:limit] == [401] * limit and results[limit:] == [429] * 3
    # a different client address is unaffected
    other = bad_login(client, "user99@test.com", environ_overrides={"REMOTE_ADDR": "10.9.9.9"})
    assert other.status_code == 401


def test_throttled_login_logs_no_secrets(client, clock, caplog):
    caplog.set_level("WARNING")
    for _ in range(client.application.config["LOGIN_MAX_FAILURES_PER_ACCOUNT"] + 1):
        bad_login(client)
    text = caplog.text
    assert "throttled" in text and "wrong-password" not in text and PASSWORD not in text


def test_rate_limiting_can_be_turned_off_by_configuration():
    app = create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "LOGIN_RATE_LIMIT_ENABLED": False,
        }
    )
    assert "login_limiter" not in app.extensions
    client = app.test_client()
    assert all(bad_login(client).status_code == 401 for _ in range(30))


def test_limiter_unit_behaviour_and_memory_bound():
    now = {"t": 0.0}
    lim = LoginRateLimiter(2, 5, 60, clock=lambda: now["t"])
    assert lim.retry_after("a@x.io", "1.1.1.1") == 0
    lim.record_failure("A@x.io", "1.1.1.1")
    lim.record_failure("a@x.io", "1.1.1.1")  # case-insensitive account key
    assert (
        lim.retry_after("a@x.io", "1.1.1.1") == 60
    )  # the guessing address is blocked for that account
    assert lim.retry_after("a@x.io", "2.2.2.2") == 0  # the owner, elsewhere, is not (D-13)
    assert lim.retry_after("other@x.io", "1.1.1.1") == 0
    now["t"] = 59.2
    assert lim.retry_after("a@x.io", "1.1.1.1") == 1
    now["t"] = 61
    assert lim.retry_after("a@x.io", "1.1.1.1") == 0
    LoginRateLimiter.MAX_KEYS, saved = 50, LoginRateLimiter.MAX_KEYS
    try:
        for i in range(500):
            lim.record_failure(f"spray{i}@x.io", "9.9.9.9")
        assert len(lim._failures) <= 50
    finally:
        LoginRateLimiter.MAX_KEYS = saved


# ---- secrets ------------------------------------------------------------------------------------


def test_production_refuses_to_start_without_a_secret(monkeypatch):
    with pytest.raises(config.ConfigError, match="SECRET_KEY must be set"):
        create_app({**FAKE_PRODUCTION, "SECRET_KEY": None})


@pytest.mark.parametrize(
    "secret",
    [
        config.DEV_SECRET_KEY,
        "change-me",
        "short-secret",
        "x" * 31,
        "Please-CHANGE-ME-" + "a" * 30,
        "",
    ],
)
def test_production_rejects_weak_or_placeholder_secrets(secret):
    with pytest.raises(config.ConfigError) as err:
        create_app({**FAKE_PRODUCTION, "SECRET_KEY": secret})
    assert secret not in str(err.value) or secret == ""  # the message never echoes the key


def test_production_checks_a_separate_jwt_key_too():
    with pytest.raises(config.ConfigError, match="JWT_SECRET_KEY"):
        create_app({**FAKE_PRODUCTION, "SECRET_KEY": GOOD_SECRET, "JWT_SECRET_KEY": "weak"})


def test_production_starts_with_a_strong_secret_and_signs_tokens_with_it():
    app = create_app({**FAKE_PRODUCTION, "SECRET_KEY": GOOD_SECRET})
    assert app.config["SECRET_KEY"] == GOOD_SECRET == app.config["JWT_SECRET_KEY"]
    assert "login_limiter" in app.extensions


def test_development_keeps_working_without_any_secret():
    app = create_app(
        {
            "APP_ENV": "development",
            "SECRET_KEY": None,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        }
    )
    assert app.config["SECRET_KEY"] == config.DEV_SECRET_KEY


def test_a_mistyped_environment_name_does_not_fall_back_to_development():
    with pytest.raises(config.ConfigError, match="APP_ENV"):
        create_app({"APP_ENV": "prod", "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})


def test_config_numbers_from_the_environment_are_validated(monkeypatch):
    import importlib

    monkeypatch.setenv("LOGIN_MAX_FAILURES_PER_ACCOUNT", "notanumber")
    with pytest.raises(RuntimeError, match="LOGIN_MAX_FAILURES_PER_ACCOUNT"):
        importlib.reload(config)
    monkeypatch.setenv("LOGIN_MAX_FAILURES_PER_ACCOUNT", "0")
    with pytest.raises(RuntimeError, match="at least 1"):  # ConfigError is a RuntimeError
        importlib.reload(config)
    monkeypatch.setenv("LOGIN_MAX_FAILURES_PER_ACCOUNT", "7")
    monkeypatch.setenv("HSTS_ENABLED", "yes")
    reloaded = importlib.reload(config)
    assert reloaded.Config.LOGIN_MAX_FAILURES_PER_ACCOUNT == 7 and reloaded.Config.HSTS_ENABLED
    monkeypatch.undo()
    importlib.reload(config)


# ---- security headers ---------------------------------------------------------------------------


def test_every_response_carries_the_security_headers(client, admin_headers):
    for res in (
        client.get("/api/health"),
        client.get("/api/jobs", headers=admin_headers),
        client.get("/api/jobs"),  # a 401
        client.get("/api/nope"),  # a 404
        bad_login(client),
    ):
        h = res.headers
        assert h["X-Content-Type-Options"] == "nosniff"
        assert h["X-Frame-Options"] == "DENY"
        assert h["Referrer-Policy"] == "no-referrer"
        assert "frame-ancestors 'none'" in h["Content-Security-Policy"]
        assert h["Cache-Control"] == "no-store"
        assert "Strict-Transport-Security" not in h


def test_hsts_is_sent_only_when_enabled_and_served_over_https():
    app = create_app(
        {"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:", "HSTS_ENABLED": True}
    )
    client = app.test_client()
    assert "Strict-Transport-Security" not in client.get("/api/health").headers
    secure = client.get("/api/health", base_url="https://localhost")
    assert secure.headers["Strict-Transport-Security"].startswith("max-age=")


def test_csv_download_keeps_its_own_headers(client, admin_headers):
    res = client.get("/api/safety/audit?format=csv", headers=admin_headers)
    assert res.mimetype == "text/csv" and "attachment" in res.headers["Content-Disposition"]
    assert res.headers["X-Content-Type-Options"] == "nosniff"


def test_trusted_proxy_count_makes_the_forwarded_address_the_client(app):
    proxied = create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "TRUSTED_PROXY_COUNT": 1,
            "BCRYPT_ROUNDS": 4,
        }
    ).test_client()
    for i in range(30):
        res = bad_login(proxied, f"u{i}@test.com", headers={"X-Forwarded-For": "203.0.113.5"})
    assert res.status_code == 429  # all 30 counted against one real client address
    other = bad_login(proxied, "z@test.com", headers={"X-Forwarded-For": "203.0.113.77"})
    assert other.status_code == 401


# ---- tokens, roles and passwords ------------------------------------------------------------------


def test_a_demoted_admin_loses_admin_rights_immediately(client, app, admin_headers):
    assert client.get("/api/users", headers=admin_headers).status_code == 200
    assert client.post("/api/users", json={}, headers=admin_headers).status_code == 400
    User.query.filter_by(email="admin@test.com").one().role = "Dispatcher"
    db.session.commit()
    assert client.post("/api/users", json={}, headers=admin_headers).status_code == 403


def test_a_role_changed_to_worker_locks_the_old_token_out(client, app, admin_headers):
    User.query.filter_by(email="admin@test.com").one().role = "Worker"
    db.session.commit()
    assert client.get("/api/users", headers=admin_headers).status_code == 403


def test_a_deleted_account_token_is_refused(client, app, supervisor_headers):
    db.session.delete(User.query.filter_by(email="super@test.com").one())
    db.session.commit()
    assert client.get("/api/jobs", headers=supervisor_headers).status_code == 403


def test_overlong_passwords_are_a_401_or_400_never_a_500(client, admin_headers):
    login_res = client.post(
        "/api/auth/login", json={"email": "admin@test.com", "password": "a" * 100}
    )
    assert login_res.status_code == 401
    create = client.post(
        "/api/users",
        json={
            "full_name": "Long Pass",
            "email": "lp@test.com",
            "role": "Admin",
            "password": "a" * 100,
        },
        headers=admin_headers,
    )
    assert create.status_code == 400 and create.get_json()["field"] == "password"
    patch = client.patch("/api/users/1", json={"password": "é" * 50}, headers=admin_headers)
    assert patch.status_code == 400 and patch.get_json()["field"] == "password"
    edge = client.post(
        "/api/users",
        json={
            "full_name": "Edge Pass",
            "email": "ep@test.com",
            "role": "Admin",
            "password": "b" * 72,
        },
        headers=admin_headers,
    )
    assert edge.status_code == 201
    assert (
        client.post(
            "/api/auth/login", json={"email": "ep@test.com", "password": "b" * 72}
        ).status_code
        == 200
    )


def test_set_password_refuses_more_than_72_bytes(app):
    with pytest.raises(ValueError):
        User().set_password("x" * 73)
    assert not User(password_hash=None).check_password("x")


def test_a_stranger_cannot_lock_the_real_owner_out_but_a_distributed_guesser_is_still_stopped(
    client, app, clock
):
    """D-13: failures from one address block that address for the account, not the owner elsewhere."""
    limit = app.config["LOGIN_MAX_FAILURES_PER_ACCOUNT"]
    for _ in range(limit + 2):
        assert bad_login(
            client, "super@test.com", environ_overrides={"REMOTE_ADDR": "203.0.113.9"}
        ).status_code in (401, 429)
    attacker = bad_login(client, "super@test.com", environ_overrides={"REMOTE_ADDR": "203.0.113.9"})
    assert attacker.status_code == 429
    owner = client.post(
        "/api/auth/login",
        json={"email": "super@test.com", "password": PASSWORD},
        environ_overrides={"REMOTE_ADDR": "198.51.100.4"},
    )
    assert owner.status_code == 200  # not locked out
    total = app.config["LOGIN_MAX_FAILURES_PER_ACCOUNT_TOTAL"]
    codes = [
        bad_login(
            client, "dispatch@test.com", environ_overrides={"REMOTE_ADDR": f"192.0.2.{i}"}
        ).status_code
        for i in range(total + 3)
    ]
    assert codes[:total] == [401] * total and set(codes[total:]) == {
        429
    }  # rotating addresses hit the account ceiling
