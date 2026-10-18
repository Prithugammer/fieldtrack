"""Shared pytest fixtures: a fresh in-memory database with a small known dataset."""

from datetime import date

import sqlite3

import pytest
from sqlalchemy import event
from sqlalchemy.engine import Engine

from app import create_app
from extensions import db
from models import Assignment, Job, JobSite, User

PASSWORD = "Password123!"
DAY = date(2026, 10, 1)


@pytest.fixture
def app():
    app = create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "BCRYPT_ROUNDS": 4,  # the minimum cost: keeps the many logins in the suite fast
        }
    )
    with app.app_context():
        db.drop_all()
        db.create_all()
        _load_fixture_data()
        yield app
        db.session.remove()
        db.drop_all()
        db.engine.dispose()  # close the in-memory connection so it is not left to the GC


@pytest.fixture
def client(app):
    return app.test_client()


def _load_fixture_data():
    def staff(name, email, role):
        u = User(full_name=name, email=email, role=role, is_active=True)
        u.set_password(PASSWORD)
        return u

    admin = staff("Test Admin", "admin@test.com", "Admin")
    dispatcher = staff("Test Dispatcher", "dispatch@test.com", "Dispatcher")
    supervisor = staff("Test Supervisor", "super@test.com", "Supervisor")
    w1 = User(full_name="Ramesh Karki", email="marcus@test.com", role="Worker", trade="Carpenter")
    w2 = User(full_name="Bishal Neupane", email="ben@test.com", role="Worker", trade="Laborer")
    site = JobSite(
        site_name="Riverside Apartments - Phase 2",
        address="720 Queen St E, Toronto",
        latitude=43.6591,
        longitude=-79.3503,
        geofence_radius_m=200,
    )
    other_site = JobSite(
        site_name="Tanner Bridge Deck Pour",
        address="Tanner Rd, Markham",
        latitude=43.8573,
        longitude=-79.3395,
        geofence_radius_m=250,
    )
    db.session.add_all([admin, dispatcher, supervisor, w1, w2, site, other_site])
    db.session.flush()

    job_a = Job(
        site=site,
        creator=dispatcher,
        title="Level 4 framing",
        scheduled_date=DAY,
        crew_size=3,
        status="Scheduled",
    )
    job_b = Job(
        site=other_site,
        creator=dispatcher,
        title="Deck pour - Span 2",
        scheduled_date=DAY,
        crew_size=3,
        status="Scheduled",
    )
    db.session.add_all([job_a, job_b])
    db.session.flush()
    # Ramesh is assigned to job A on DAY. Bishal is not assigned to anything yet.
    db.session.add(Assignment(job=job_a, worker=w1, work_date=DAY))
    db.session.commit()


def login(client, email):
    res = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert res.status_code == 200, res.get_json()
    return {"Authorization": f"Bearer {res.get_json()['token']}"}


@pytest.fixture
def admin_headers(client):
    return login(client, "admin@test.com")


@pytest.fixture
def dispatcher_headers(client):
    return login(client, "dispatch@test.com")


@pytest.fixture
def supervisor_headers(client):
    return login(client, "super@test.com")


@pytest.fixture
def ids(app):
    """Primary keys of the fixture rows, looked up by name."""
    return {
        "marcus": User.query.filter_by(email="marcus@test.com").one().user_id,
        "ben": User.query.filter_by(email="ben@test.com").one().user_id,
        "job_a": Job.query.filter_by(title="Level 4 framing").one().job_id,
        "job_b": Job.query.filter_by(title="Deck pour - Span 2").one().job_id,
    }


# ---- close every SQLite connection a test opened (audit D-16) ---------------------------------------
# Many tests build their own throw-away apps; their pooled connections used to be closed only when the
# garbage collector got to them, which produced "ResourceWarning: unclosed database" noise.
_open_connections = []


@event.listens_for(Engine, "connect")
def _remember_connection(dbapi_connection, connection_record):
    if isinstance(dbapi_connection, sqlite3.Connection):
        _open_connections.append(dbapi_connection)


@pytest.fixture(autouse=True)
def _close_sqlite_connections():
    yield
    for connection in list(_open_connections):
        try:
            connection.close()
        except Exception:  # noqa: BLE001 - already closed or owned by a finished thread
            pass
    _open_connections.clear()
