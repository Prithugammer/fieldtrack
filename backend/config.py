"""Application configuration for FieldTrack.

Every setting can be overridden with an environment variable (or a backend/.env file — see
.env.example). The defaults are for running locally; set real secrets anywhere else.
"""
import os
from datetime import timedelta

from dotenv import load_dotenv

# Load backend/.env if present. Variables already set in the environment win.
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))


def _list(value):
    return [item.strip() for item in value.split(",") if item.strip()]


class Config:
    # Signs Flask sessions; JWTs are signed with JWT_SECRET_KEY (same value unless set).
    # The default is only for local development.
    SECRET_KEY = os.environ.get("SECRET_KEY", "fieldtrack-local-dev-secret-change-me")
    JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY", SECRET_KEY)

    # Flask-SQLAlchemy 3 resolves a relative SQLite path inside the "instance" folder,
    # so the default database file lives at backend/instance/fieldtrack.db.
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL", "sqlite:///fieldtrack.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # A staff login lasts one working shift.
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=float(os.environ.get("JWT_EXPIRES_HOURS", "8")))

    # Default geofence radius (metres) for a new job site when none is given.
    GEOFENCE_RADIUS_M = 200

    # Browser origins allowed to call the API (comma-separated). Defaults to the Vite dev server.
    CORS_ORIGINS = _list(
        os.environ.get("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
    )
