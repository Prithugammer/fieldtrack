"""Shared helpers for the audit probes. Runs from the backend directory; changes no source."""

import hashlib
import sys

sys.path.insert(0, ".")
from app import create_app  # noqa: E402
from extensions import db  # noqa: E402
import seed as seeding  # noqa: E402

ACCOUNTS = {
    "admin": ("admin@fieldtrack.com", "Admin123!"),
    "dispatcher": ("dispatch@fieldtrack.com", "Dispatch123!"),
    "supervisor": ("supervisor@fieldtrack.com", "Super123!"),
}


def make_app(**overrides):
    cfg = {"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:", "BCRYPT_ROUNDS": 4}
    cfg.update(overrides)
    app = create_app(cfg)
    return app


def seeded_app(**overrides):
    app = make_app(**overrides)
    ctx = app.app_context()
    ctx.push()
    import io
    import contextlib

    with contextlib.redirect_stdout(io.StringIO()):
        seeding.seed()
    return app, ctx


def login_all(client):
    out = {}
    for role, (email, pw) in ACCOUNTS.items():
        r = client.post("/api/auth/login", json={"email": email, "password": pw})
        out[role] = {"Authorization": "Bearer " + r.get_json()["token"]}
    return out


def db_fingerprint():
    """A hash of every row of every table: detects ANY unintended persistent change."""
    h = hashlib.sha1()
    for table in db.metadata.sorted_tables:
        rows = db.session.execute(table.select().order_by(*table.primary_key.columns)).fetchall()
        h.update(table.name.encode())
        h.update(repr(rows).encode())
    return h.hexdigest()[:12]


def line(id_, verdict, detail):
    print(f"{id_:<8} {verdict:<8} {detail}")
