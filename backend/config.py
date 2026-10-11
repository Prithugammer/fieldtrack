"""Application configuration for FieldTrack.

Every setting can be overridden with an environment variable (or a backend/.env file — see
.env.example). The defaults are for running locally; set real secrets anywhere else.

APP_ENV selects the mode: "development" (the default, so a fresh checkout just runs), "test", or
"production". Production refuses to start without a strong SECRET_KEY (see resolve_secrets).
"""

import os
from datetime import timedelta

from dotenv import load_dotenv

# Load backend/.env if present. Variables already set in the environment win.
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

APP_ENVS = ("development", "test", "production")

# Used ONLY outside production, so a fresh checkout runs without any setup. Never a secret.
DEV_SECRET_KEY = "fieldtrack-local-dev-secret-change-me"
MIN_SECRET_LENGTH = 32
_PLACEHOLDER_MARKERS = ("change-me", "changeme", "change_me", "replace-me", "your-secret")


class ConfigError(RuntimeError):
    """The configuration is unsafe or invalid; the app refuses to start."""


def _list(value):
    return [item.strip() for item in value.split(",") if item.strip()]


def _bool(name, default):
    return os.environ.get(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


def _int(name, default, minimum=0):
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ConfigError(f"{name} must be a whole number.") from None
    if value < minimum:
        raise ConfigError(f"{name} must be at least {minimum}.")
    return value


class Config:
    # "development" | "test" | "production" (anything else is rejected at startup, so a typo can
    # never silently fall back to the development defaults).
    APP_ENV = os.environ.get("APP_ENV", "development").strip().lower()

    # Signs Flask sessions; JWTs are signed with JWT_SECRET_KEY (same value unless set).
    # None here means "not supplied": resolve_secrets() applies the development fallback or,
    # in production, refuses to start.
    SECRET_KEY = os.environ.get("SECRET_KEY") or None
    JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY") or None

    # Flask-SQLAlchemy 3 resolves a relative SQLite path inside the "instance" folder,
    # so the default database file lives at backend/instance/fieldtrack.db.
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL", "sqlite:///fieldtrack.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # A staff login lasts one working shift.
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=float(os.environ.get("JWT_EXPIRES_HOURS", "8")))

    # bcrypt cost factor for new password hashes (tests lower it to stay fast).
    BCRYPT_ROUNDS = _int("BCRYPT_ROUNDS", 12, minimum=4)

    # Default geofence radius (metres) for a new job site when none is given.
    GEOFENCE_RADIUS_M = 200

    # Browser origins allowed to call the API (comma-separated). Defaults to the Vite dev server.
    CORS_ORIGINS = _list(
        os.environ.get("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
    )

    # ---- Login throttling (see security.LoginRateLimiter) -------------------------------------
    # Only FAILED attempts count. After the limit, further attempts get HTTP 429 until the oldest
    # failure leaves the window, so a lock-out is always temporary.
    LOGIN_RATE_LIMIT_ENABLED = _bool("LOGIN_RATE_LIMIT_ENABLED", True)
    LOGIN_MAX_FAILURES_PER_ACCOUNT = _int("LOGIN_MAX_FAILURES_PER_ACCOUNT", 5, minimum=1)
    LOGIN_MAX_FAILURES_PER_CLIENT = _int("LOGIN_MAX_FAILURES_PER_CLIENT", 20, minimum=1)
    LOGIN_RATE_WINDOW_SECONDS = _int("LOGIN_RATE_WINDOW_SECONDS", 300, minimum=1)

    # ---- HTTP hardening ------------------------------------------------------------------------
    # Send Strict-Transport-Security. Turn on ONLY when the API is served over HTTPS.
    HSTS_ENABLED = _bool("HSTS_ENABLED", False)
    # Number of reverse proxies in front of the app (0 = none). When > 0, X-Forwarded-For/-Proto
    # from that many hops are trusted, so rate limiting sees the real client address.
    TRUSTED_PROXY_COUNT = _int("TRUSTED_PROXY_COUNT", 0, minimum=0)


def _require_strong(name, value):
    if not value:
        raise ConfigError(
            f"{name} must be set in production. Generate one with: "
            'python -c "import secrets; print(secrets.token_hex(32))"'
        )
    lowered = value.strip().lower()
    if value == DEV_SECRET_KEY or any(marker in lowered for marker in _PLACEHOLDER_MARKERS):
        raise ConfigError(f"{name} is a placeholder value; set a real random secret in production.")
    if len(value) < MIN_SECRET_LENGTH:
        raise ConfigError(f"{name} must be at least {MIN_SECRET_LENGTH} characters in production.")


def resolve_secrets(cfg):
    """Validate APP_ENV and settle SECRET_KEY / JWT_SECRET_KEY in the config mapping `cfg`.

    Production: both keys must be supplied, at least 32 characters and not a placeholder, or
    ConfigError is raised (the message never contains the key). Any other mode falls back to a
    fixed development key so local work needs no setup.
    """
    env = cfg.get("APP_ENV")
    if env not in APP_ENVS:
        raise ConfigError(f"APP_ENV must be one of: {', '.join(APP_ENVS)}.")
    secret = cfg.get("SECRET_KEY")
    jwt_secret = cfg.get("JWT_SECRET_KEY") or secret
    if env == "production":
        _require_strong("SECRET_KEY", secret)
        _require_strong("JWT_SECRET_KEY", jwt_secret)
    else:
        secret = secret or DEV_SECRET_KEY
        jwt_secret = jwt_secret or secret
    cfg["SECRET_KEY"] = secret
    cfg["JWT_SECRET_KEY"] = jwt_secret
