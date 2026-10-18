"""FieldTrack API — Flask application factory.

Run the development server with:   python app.py      (http://localhost:5000)
Debug mode (auto-reload + interactive tracebacks) is off unless FLASK_DEBUG=1 is set.
"""

import logging
import os

from flask import Flask, jsonify, request
from flask_cors import CORS
from werkzeug.exceptions import HTTPException, RequestEntityTooLarge
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, OperationalError
from werkzeug.middleware.proxy_fix import ProxyFix

from auth import auth_bp
from concurrency import BUSY_MESSAGE, is_busy_error
from config import Config, ConfigError, resolve_secrets
from extensions import db, jwt
from models import OPEN_ENTRY_INDEX, User
from routes.assignments import assignments_bp
from routes.dashboard import dashboard_bp
from routes.jobs import jobs_bp
from routes.map import map_bp
from routes.reports import reports_bp
from routes.safety import safety_bp
from routes.sites import sites_bp
from routes.time_entries import time_entries_bp
from routes.users import users_bp
from safety import SafetyConfig, SafetyService, SafetyStore, start_background_services
from security import LoginRateLimiter, register_security_headers
from validation import ApiError


def create_app(overrides=None):
    """Build and configure the Flask app. `overrides` lets tests use an in-memory DB."""
    app = Flask(__name__)
    app.config.from_object(Config)
    if overrides:
        app.config.update(overrides)
    resolve_secrets(app.config)  # raises ConfigError if production has no strong secret

    if app.config["TRUSTED_PROXY_COUNT"]:
        n = app.config["TRUSTED_PROXY_COUNT"]
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=n, x_proto=n)
    register_security_headers(app)
    if app.config["LOGIN_RATE_LIMIT_ENABLED"]:
        app.extensions["login_limiter"] = LoginRateLimiter(
            app.config["LOGIN_MAX_FAILURES_PER_ACCOUNT"],
            app.config["LOGIN_MAX_FAILURES_PER_CLIENT"],
            app.config["LOGIN_RATE_WINDOW_SECONDS"],
            max_per_account_total=app.config["LOGIN_MAX_FAILURES_PER_ACCOUNT_TOTAL"],
        )

    CORS(app, resources={r"/api/*": {"origins": app.config["CORS_ORIGINS"]}})
    _configure_sqlite(app)
    db.init_app(app)
    jwt.init_app(app)

    for bp in (
        auth_bp,
        users_bp,
        sites_bp,
        jobs_bp,
        assignments_bp,
        time_entries_bp,
        reports_bp,
        dashboard_bp,
        map_bp,
        safety_bp,
    ):
        app.register_blueprint(bp)

    # Safety escalation state lives in memory for the life of the app (tests pass SAFETY_CONFIG).
    app.extensions["safety"] = SafetyService(
        app.config.get("SAFETY_CONFIG") or SafetyConfig.from_env()
    )

    _register_error_handlers(app)

    @app.before_request
    def reject_oversized_bodies():
        """Answer 413 from the Content-Length header alone, before any route reads the body."""
        limit = app.config.get("MAX_CONTENT_LENGTH")
        if limit and request.content_length is not None and request.content_length > limit:
            raise RequestEntityTooLarge()

    with app.app_context():
        import models  # noqa: F401  (make sure every table is registered)

        db.create_all()
        ensure_schema_guards()
        if app.config["SAFETY_PERSISTENCE"]:
            # Restores open emergencies etc. A database error here stops start-up on purpose:
            # starting with an empty safety state would silently drop a real incident.
            app.extensions["safety"].attach_store(SafetyStore())
        User.burn_password_check("")  # build the timing-pad hash now, not during the first login

    @app.get("/api/health")
    def health():
        """Simple liveness check."""
        return jsonify({"status": "ok"})

    return app


def _configure_sqlite(app):
    """How long a writer waits for another writer before giving up (then HTTP 503, see concurrency.py)."""
    if not app.config["SQLALCHEMY_DATABASE_URI"].startswith("sqlite"):
        return
    options = dict(app.config.get("SQLALCHEMY_ENGINE_OPTIONS") or {})
    connect_args = dict(options.get("connect_args") or {})
    connect_args.setdefault("timeout", float(app.config["SQLITE_BUSY_TIMEOUT_SECONDS"]))
    options["connect_args"] = connect_args
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = options


def ensure_schema_guards():
    """Create the one-open-entry-per-worker index on databases that predate it (idempotent).

    `create_all()` only creates missing TABLES, so a database created before the index existed would
    otherwise never get it. If the data already breaks the rule the index cannot be built; the app
    still starts (the write-lock in concurrency.py protects new writes) and says what to fix.
    """
    if db.engine.dialect.name != "sqlite":
        return
    try:
        db.session.execute(
            text(
                f"CREATE UNIQUE INDEX IF NOT EXISTS {OPEN_ENTRY_INDEX} "
                "ON time_entries (user_id) WHERE clock_out IS NULL"
            )
        )
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        logging.getLogger("fieldtrack").warning(
            "could not create the one-open-entry-per-worker index: some worker already has more than "
            "one time entry without a clock-out. Clock those entries out, then restart."
        )


def _register_error_handlers(app):
    """Make EVERY error a JSON body of the form {"error": "...", "field": ...}."""

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        """Business-rule and validation errors raised by the routes (400/403/404/409)."""
        db.session.rollback()  # a rejected request must never leave half-applied changes behind
        return jsonify(err.to_dict()), err.status, err.headers

    @app.errorhandler(HTTPException)
    def handle_http_error(err):
        """Flask's own errors (unknown URL, wrong method) in the same JSON shape."""
        messages = {
            404: "That resource was not found.",
            405: "Method not allowed for this URL.",
            413: "The request body is too large.",
        }
        return jsonify({"error": messages.get(err.code, err.description), "field": None}), err.code

    @app.errorhandler(OperationalError)
    def handle_database_error(err):
        """A database that stays locked is a retryable 503, not a crash; anything else is a real 500."""
        db.session.rollback()
        if is_busy_error(err):
            return jsonify({"error": BUSY_MESSAGE, "field": None}), 503, {"Retry-After": "1"}
        return handle_unexpected(err)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        """Never leak a stack trace to the browser: log it, roll back, return a generic 500."""
        app.logger.exception(err)
        db.session.rollback()
        return jsonify({"error": "Something went wrong on the server.", "field": None}), 500

    # Flask-JWT-Extended: missing / invalid / expired tokens -> 401 JSON.
    @jwt.unauthorized_loader
    def missing_token(reason):
        """No Authorization header: the UI sends the user to the login page."""
        return jsonify({"error": "Please log in to continue.", "field": None}), 401

    @jwt.invalid_token_loader
    def invalid_token(reason):
        """Malformed or tampered token."""
        return (
            jsonify({"error": "Your session is invalid. Please log in again.", "field": None}),
            401,
        )

    @jwt.expired_token_loader
    def expired_token(header, payload):
        """Token older than JWT_ACCESS_TOKEN_EXPIRES (one shift by default)."""
        return (
            jsonify({"error": "Your session has expired. Please log in again.", "field": None}),
            401,
        )


if __name__ == "__main__":
    debug = os.environ.get("FLASK_DEBUG", "0").lower() in ("1", "true", "yes")
    application = create_app()
    if debug and application.config["APP_ENV"] == "production":
        # The interactive debugger runs arbitrary code for anyone who can reach it.
        raise ConfigError("FLASK_DEBUG must not be enabled when APP_ENV=production.")
    # Safety escalation is driven by a backend thread, not by browsers. With the debug reloader the
    # first process only supervises: the heartbeat belongs to the child that serves requests.
    if not debug or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        start_background_services(application)
    application.run(
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "5000")),
        debug=debug,
    )
