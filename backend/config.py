"""Application configuration for FieldTrack."""
import os
from datetime import timedelta


class Config:
    # Used by Flask for signing; JWTs are signed with JWT_SECRET_KEY (same value by default).
    # Change these in production by setting environment variables.
    SECRET_KEY = os.environ.get(
        "SECRET_KEY", "fieldtrack-dev-secret-key-change-me-in-production-2026"
    )
    JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY", SECRET_KEY)

    # Flask-SQLAlchemy 3 resolves a relative SQLite path inside the "instance" folder,
    # so the database file lives at backend/instance/fieldtrack.db.
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL", "sqlite:///fieldtrack.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # A staff login lasts one working shift.
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=8)

    # Default geofence radius (metres) for a new job site when none is given.
    GEOFENCE_RADIUS_M = 200

    # The React dev server (Vite) — the only origins allowed to call the API.
    CORS_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]
