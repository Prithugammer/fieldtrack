"""FieldTrack API — Flask application factory.

Run the development server with:   python app.py      (http://localhost:5000)
Debug mode (auto-reload + interactive tracebacks) is off unless FLASK_DEBUG=1 is set.
"""

import os

from flask import Flask, jsonify
from flask_cors import CORS
from werkzeug.exceptions import HTTPException

from auth import auth_bp
from config import Config
from extensions import db, jwt
from routes.assignments import assignments_bp
from routes.dashboard import dashboard_bp
from routes.jobs import jobs_bp
from routes.map import map_bp
from routes.reports import reports_bp
from routes.sites import sites_bp
from routes.time_entries import time_entries_bp
from routes.users import users_bp
from validation import ApiError


def create_app(overrides=None):
    """Build and configure the Flask app. `overrides` lets tests use an in-memory DB."""
    app = Flask(__name__)
    app.config.from_object(Config)
    if overrides:
        app.config.update(overrides)

    CORS(app, resources={r"/api/*": {"origins": app.config["CORS_ORIGINS"]}})
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
    ):
        app.register_blueprint(bp)

    _register_error_handlers(app)

    with app.app_context():
        import models  # noqa: F401  (make sure every table is registered)

        db.create_all()

    @app.get("/api/health")
    def health():
        """Simple liveness check."""
        return jsonify({"status": "ok"})

    return app


def _register_error_handlers(app):
    """Make EVERY error a JSON body of the form {"error": "...", "field": ...}."""

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        """Business-rule and validation errors raised by the routes (400/403/404/409)."""
        return jsonify(err.to_dict()), err.status

    @app.errorhandler(HTTPException)
    def handle_http_error(err):
        """Flask's own errors (unknown URL, wrong method) in the same JSON shape."""
        messages = {404: "That resource was not found.", 405: "Method not allowed for this URL."}
        return jsonify({"error": messages.get(err.code, err.description), "field": None}), err.code

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
    create_app().run(
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "5000")),
        debug=os.environ.get("FLASK_DEBUG", "0").lower() in ("1", "true", "yes"),
    )
