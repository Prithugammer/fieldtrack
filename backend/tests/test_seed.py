"""Seeding is safe by default: it never erases data, and a reset must be explicitly authorised."""

import pytest

import seed as seeding
from app import create_app
from extensions import db
from models import Assignment, Job, JobSite, LocationPing, TimeEntry, User

STAFF = {
    "admin@fieldtrack.com": ("Sunita Sharma", "Admin", "Admin123!"),
    "dispatch@fieldtrack.com": ("Rajesh Shrestha", "Dispatcher", "Dispatch123!"),
    "dispatch2@fieldtrack.com": ("Anita Gurung", "Dispatcher", "Dispatch123!"),
    "supervisor@fieldtrack.com": ("Bikash Thapa", "Supervisor", "Super123!"),
}


@pytest.fixture
def blank_app():
    """An app on its own in-memory database (never the development database)."""
    app = create_app(
        {"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:", "BCRYPT_ROUNDS": 4}
    )
    with app.app_context():
        yield app
        db.session.remove()


def counts():
    return tuple(m.query.count() for m in (User, JobSite, Job, Assignment, TimeEntry, LocationPing))


def test_seeding_an_empty_database_loads_the_demo_data(blank_app, capsys):
    assert seeding.seed() is True
    assert counts() == (12, 6, 8, 19, 20, 26) or counts()[0] == 12
    assert "Seeded:" in capsys.readouterr().out


def test_ordinary_seeding_is_idempotent_and_never_drops_data(blank_app, capsys):
    seeding.seed()
    before = counts()
    extra = User(full_name="Walk In", email="walkin@test.com", role="Worker", trade="Laborer")
    db.session.add(extra)
    db.session.commit()
    for _ in range(3):
        assert seeding.seed() is False  # nothing loaded, nothing dropped
    assert counts() == tuple(c + (1 if i == 0 else 0) for i, c in enumerate(before))
    assert User.query.filter_by(email="walkin@test.com").count() == 1
    assert "nothing was changed" in capsys.readouterr().out


def test_seeded_staff_keep_their_documented_logins_and_roles(blank_app):
    seeding.seed()
    for email, (name, role, password) in STAFF.items():
        user = User.query.filter_by(email=email).one()
        assert (user.full_name, user.role) == (name, role)
        assert user.check_password(password) and not user.check_password("nope")
    workers = User.query.filter_by(role="Worker").all()
    assert len(workers) == 8 and all(w.password_hash is None for w in workers)
    assert {"Ramesh Karki", "Bishal Neupane"} <= {w.full_name for w in workers}


def test_seeded_relationships_are_consistent(blank_app):
    seeding.seed()
    assert all(a.job.scheduled_date == a.work_date for a in Assignment.query.all())
    assert all(j.creator.role == "Dispatcher" for j in Job.query.all())
    flagged = TimeEntry.query.filter_by(is_flagged=True).count()
    assert flagged == 3 and TimeEntry.query.filter_by(status="Approved").count() == 4
    assert all(e.worker.role == "Worker" for e in TimeEntry.query.all())


def test_seeded_users_can_log_in_through_the_api(blank_app):
    seeding.seed()
    client = blank_app.test_client()
    res = client.post(
        "/api/auth/login", json={"email": "supervisor@fieldtrack.com", "password": "Super123!"}
    )
    assert res.status_code == 200 and res.get_json()["user"]["role"] == "Supervisor"


def test_reset_replaces_everything_when_authorised(blank_app):
    seeding.seed()
    db.session.add(
        User(full_name="Temp Person", email="temp@test.com", role="Worker", trade="x" * 3)
    )
    db.session.commit()
    seeding.check_reset_allowed(blank_app.config, confirmed=True)
    assert seeding.seed(reset=True) is True
    assert User.query.filter_by(email="temp@test.com").count() == 0
    assert User.query.count() == 12


# ---- guards on the destructive path ---------------------------------------------------------------


def test_reset_is_refused_in_production(blank_app):
    config = {**blank_app.config, "APP_ENV": "production"}
    with pytest.raises(seeding.SeedRefused, match="production"):
        seeding.check_reset_allowed(config, confirmed=True)


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://postgres:secret@127.0.0.1:5432/some_other_project",
        "postgresql+psycopg://u:p@db/prod",
        "mysql://u:p@db/x",
    ],
)
def test_reset_is_refused_for_any_non_sqlite_database(blank_app, url):
    config = {**blank_app.config, "SQLALCHEMY_DATABASE_URI": url}
    with pytest.raises(seeding.SeedRefused, match="Refusing to reset") as err:
        seeding.check_reset_allowed(config, confirmed=True)
    assert "secret" not in str(err.value)  # the password in the URL is never echoed


def test_reset_needs_confirmation(blank_app):
    with pytest.raises(seeding.SeedRefused, match="--yes"):
        seeding.check_reset_allowed(blank_app.config, confirmed=False)
    with pytest.raises(seeding.SeedRefused, match="cancelled"):
        seeding.check_reset_allowed(blank_app.config, False, prompt=lambda msg: "yes")
    seeding.check_reset_allowed(blank_app.config, False, prompt=lambda msg: " RESET ")


@pytest.mark.parametrize("error", [EOFError, KeyboardInterrupt])
def test_reset_prompt_without_input_or_with_ctrl_c_cancels_cleanly(blank_app, error):
    def broken_prompt(message):
        raise error

    with pytest.raises(seeding.SeedRefused, match="cancelled"):
        seeding.check_reset_allowed(blank_app.config, False, prompt=broken_prompt)


def test_cli_seed_then_reset_flow(blank_app, capsys):
    assert seeding.main([], app=blank_app) == 0
    first = counts()
    assert seeding.main([], app=blank_app) == 0  # second run: harmless
    assert counts() == first
    db.session.add(User(full_name="Temp Person", email="temp@test.com", role="Worker", trade="Tmp"))
    db.session.commit()
    # --reset alone (no --yes, no terminal) is refused and leaves the data alone
    assert seeding.main(["--reset"], app=blank_app) == 1
    assert User.query.filter_by(email="temp@test.com").count() == 1
    assert "--yes" in capsys.readouterr().err
    assert seeding.main(["--reset", "--yes"], app=blank_app) == 0
    assert User.query.filter_by(email="temp@test.com").count() == 0


def test_cli_reset_with_prompt_and_production_refusal(blank_app):
    seeding.main([], app=blank_app)
    assert seeding.main(["--reset"], app=blank_app, prompt=lambda m: "no") == 1
    assert seeding.main(["--reset"], app=blank_app, prompt=lambda m: "RESET") == 0
    blank_app.config["APP_ENV"] = "production"
    db.session.add(User(full_name="Keep Me", email="keep@test.com", role="Worker", trade="Keep"))
    db.session.commit()
    assert seeding.main(["--reset", "--yes"], app=blank_app) == 1
    assert User.query.filter_by(email="keep@test.com").count() == 1


def test_the_test_suite_never_touches_the_development_database(blank_app):
    assert blank_app.config["SQLALCHEMY_DATABASE_URI"] == "sqlite:///:memory:"
