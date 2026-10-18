"""D-05, D-06, D-07, D-09: hostile or extreme input must be refused with a 4xx, never a 500.

Each case below crashed (HTTP 500) before the fix:
  * JSON nested ~3,000 levels deep         -> RecursionError inside the JSON parser
  * lone Unicode surrogates ("\\ud800")     -> UnicodeEncodeError when SQLite received the text
  * date 9999-12-31 in filters and reports -> OverflowError in `date + 1 day`
  * a 5 MB body                             -> read and parsed in full before being rejected
Server-side diagnostics for genuinely unexpected errors are kept: see `test_real_server_errors_*`.
"""

import json
import logging
from datetime import date, timedelta

import pytest

from extensions import db
from models import Assignment, Job, JobSite, TimeEntry, User

NEST = {
    "array-3000-unclosed": "[" * 3000,
    "array-60000-unclosed": "[" * 60000,
    "object-3000-unclosed": '{"a":' * 3000,
    "array-3000-closed": "[" * 3000 + "]" * 3000,
}

ENDPOINTS_WITH_BODY = [
    ("post", "/api/auth/login", None),
    ("post", "/api/users", "admin"),
    ("patch", "/api/users/1", "admin"),
    ("post", "/api/sites", "dispatcher"),
    ("patch", "/api/sites/1", "dispatcher"),
    ("post", "/api/jobs", "dispatcher"),
    ("patch", "/api/jobs/1", "dispatcher"),
    ("post", "/api/assignments", "dispatcher"),
    ("post", "/api/time-entries", "supervisor"),
    ("patch", "/api/time-entries/{entry}/clock-out", "supervisor"),
    ("patch", "/api/time-entries/{entry}/approve", "supervisor"),
    ("post", "/api/safety/workers/4/resolve", "supervisor"),
    ("post", "/api/safety/workers/4/break", "supervisor"),
]


@pytest.fixture
def entry_id(app, ids):
    """An open (not yet clocked-out) time entry, so /time-entries/<id>/... routes get as far as reading the body."""
    from datetime import datetime

    e = TimeEntry(user_id=ids["marcus"], job_id=ids["job_a"], clock_in=datetime(2026, 10, 1, 7), 
                  in_lat=43.6591, in_lng=-79.3503,   is_flagged=False, status="Pending")  # fmt: skip
    db.session.add(e)
    db.session.commit()
    return e.entry_id


@pytest.fixture
def headers(admin_headers, dispatcher_headers, supervisor_headers):
    return {
        "admin": admin_headers,
        "dispatcher": dispatcher_headers,
        "supervisor": supervisor_headers,
        None: {},
    }


def snapshot():
    return (
        User.query.count(),
        JobSite.query.count(),
        Job.query.count(),
        Assignment.query.count(),
        TimeEntry.query.count(),
    )


# ---- nested JSON --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("body", NEST.values(), ids=NEST.keys())
@pytest.mark.parametrize("method,url,role", ENDPOINTS_WITH_BODY)
def test_deeply_nested_json_is_a_400_everywhere(client, headers, entry_id, method, url, role, body):
    url = url.format(entry=entry_id)
    before = snapshot()
    res = getattr(client, method)(
        url, data=body, content_type="application/json", headers=headers[role]
    )
    assert res.status_code == 400, (method, url, res.status_code)
    error = res.get_json()["error"]
    assert res.get_json()["field"] is None
    assert (
        "nested too deeply" in error or "JSON object" in error
    )  # unclosed brackets are plain bad JSON
    assert snapshot() == before


def test_moderately_nested_valid_json_is_still_accepted(client, dispatcher_headers):
    """Unknown extra keys are ignored, so a (reasonably) nested value must not be rejected as such."""
    deep = {"x": 1}
    for _ in range(50):
        deep = {"x": deep}
    res = client.post(
        "/api/jobs",
        json={
            "site_id": 1,
            "title": "Nested ok",
            "scheduled_date": "2026-10-01",
            "crew_size": 2,
            "extra": deep,
        },
        headers=dispatcher_headers,
    )
    assert res.status_code == 201


def test_the_nesting_limit_error_names_the_problem(client):
    """Python <= 3.11 (and Windows 3.13) raise RecursionError for 5,000 levels, which we turn into the
    'nested too deeply' message; Python 3.12+ on Linux parses it fine, finds a list, and says it is
    not a JSON object. Both are the same clean 400 with no crash."""
    res = client.post(
        "/api/auth/login", data="[" * 5000 + "]" * 5000, content_type="application/json"
    )
    assert res.status_code == 400 and res.get_json()["field"] is None
    assert res.get_json()["error"] in (
        "Request body is nested too deeply.",
        "Request body must be a JSON object.",
    )


# ---- request size ---------------------------------------------------------------------------------------------


def test_the_default_body_limit_is_one_megabyte(app):
    assert app.config["MAX_CONTENT_LENGTH"] == 1_048_576


@pytest.mark.parametrize("method,url,role", ENDPOINTS_WITH_BODY)
def test_an_oversized_body_is_a_413_before_it_is_parsed(
    client, headers, entry_id, method, url, role
):
    url = url.format(entry=entry_id)
    big = json.dumps({"email": "a" * 1_200_000, "password": "x"})
    res = getattr(client, method)(
        url, data=big, content_type="application/json", headers=headers[role]
    )
    assert res.status_code == 413, (method, url, res.status_code)
    assert res.get_json() == {"error": "The request body is too large.", "field": None}


def test_a_large_but_allowed_body_still_reaches_validation(client):
    res = client.post("/api/auth/login", json={"email": "a" * 900_000, "password": "x"})
    assert (
        res.status_code == 400 and res.get_json()["field"] == "email"
    )  # too long for an email, but read normally


def test_the_limit_is_configurable(tmp_path):
    from app import create_app

    small = create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "MAX_CONTENT_LENGTH": 2048,
            "BCRYPT_ROUNDS": 4,
        }
    )
    c = small.test_client()
    assert (
        c.post("/api/auth/login", json={"email": "x" * 100, "password": "x"}).status_code == 401
    )  # small body: normal handling
    assert c.post("/api/auth/login", json={"email": "x" * 5000, "password": "x"}).status_code == 413


def test_other_hostile_bodies_are_400_not_500(client):
    for raw, ctype in [
        (b"\xff\xfe\x00\x00", "application/json"),
        (b'\xef\xbb\xbf{"email": "a"}', "application/json"),
        (b'{"email": "a", "password": "' + b"9" * 6000 + b'"}', "application/json"),
        (b'{"a": ' + b"9" * 6000 + b"}", "application/json"),
        (b"", "application/json"),
        (b"{}", "text/plain"),
        (b'{"email": 1e999, "password": NaN}', "application/json"),
    ]:
        res = client.post("/api/auth/login", data=raw, content_type=ctype)
        assert 400 <= res.status_code < 500, (raw[:20], res.status_code)


# ---- Unicode ---------------------------------------------------------------------------------------------------

LONE_SURROGATES = ["\ud800", "\udfff", "\ud800\ud800\ud800", "ab\udc00cd", "x" * 5 + "\ud83d"]


@pytest.mark.parametrize("bad", LONE_SURROGATES)
def test_lone_surrogates_in_text_are_a_400_for_every_text_field(
    client, admin_headers, dispatcher_headers, supervisor_headers, entry_id, bad
):
    before = snapshot()
    cases = [
        ("post", "/api/auth/login", None, {"email": bad, "password": "x"}, "email"),
        (
            "post",
            "/api/auth/login",
            None,
            {"email": "admin@test.com", "password": bad + "12345678"},
            "password",
        ),
        (
            "post",
            "/api/users",
            admin_headers,
            {"full_name": bad + "abc", "email": "s@t.com", "role": "Worker", "trade": "Welder"},
            "full_name",
        ),
        (
            "post",
            "/api/users",
            admin_headers,
            {
                "full_name": "Sur Rogate",
                "email": "s2@t.com",
                "role": "Worker",
                "trade": bad + "abc",
            },
            "trade",
        ),
        (
            "post",
            "/api/sites",
            dispatcher_headers,
            {"site_name": bad + "abc", "address": "1 Test Road", "latitude": 1, "longitude": 1},
            "site_name",
        ),
        (
            "post",
            "/api/sites",
            dispatcher_headers,
            {"site_name": "Surrogate", "address": bad + "12345", "latitude": 1, "longitude": 1},
            "address",
        ),
        (
            "post",
            "/api/jobs",
            dispatcher_headers,
            {"site_id": 1, "title": bad + "abc", "scheduled_date": "2026-10-01", "crew_size": 2},
            "title",
        ),
        (
            "post",
            "/api/jobs",
            dispatcher_headers,
            {
                "site_id": 1,
                "title": "Surrogate",
                "description": bad,
                "scheduled_date": "2026-10-01",
                "crew_size": 2,
            },
            "description",
        ),
        (
            "patch",
            "/api/time-entries/{entry}/approve",
            supervisor_headers,
            {"decision": "Approved", "edit_reason": bad + "abc"},
            "edit_reason",
        ),
        (
            "post",
            "/api/safety/workers/4/resolve",
            supervisor_headers,
            {"outcome": "false_alarm", "note": bad},
            "note",
        ),
    ]
    for method, url, hdr, body, field in cases:
        url = url.format(entry=entry_id)
        res = getattr(client, method)(url, json=body, headers=hdr or {})
        assert res.status_code == 400, (url, field, res.status_code)
        assert res.get_json()["field"] == field, (url, res.get_json())
    assert snapshot() == before


def test_surrogates_in_the_query_string_and_path_never_crash(client, admin_headers):
    for url in [
        "/api/jobs?status=%ED%A0%80",
        "/api/jobs?date=%ff%fe",
        "/api/users?role=%ED%B0%80",
        "/api/jobs/%ED%A0%80",
        "/api/time-entries?flagged=%ff",
    ]:
        assert client.get(url, headers=admin_headers).status_code in (400, 404), url


@pytest.mark.parametrize(
    "ok",
    ["Prithak Shah", "प्रिथक शाह", "José Müller", "密码测试", "emoji 😀 ok", "tab\tand\nnewline"],
)
def test_valid_unicode_text_is_still_accepted(client, admin_headers, ok):
    res = client.post(
        "/api/users",
        json={
            "full_name": ok,
            "email": f"u{abs(hash(ok))}@t.com",
            "role": "Worker",
            "trade": "Welder",
        },
        headers=admin_headers,
    )
    assert res.status_code == 201 and res.get_json()["user"]["full_name"] == ok.strip()


# ---- extreme dates ---------------------------------------------------------------------------------------------

EXTREME_QUERIES = [
    "/api/time-entries?date=9999-12-31",
    "/api/time-entries?date=0001-01-01",
    "/api/reports/hours-by-worker?to=9999-12-31",
    "/api/reports/hours-by-worker?from=9999-12-31&to=9999-12-31",
    "/api/reports/hours-by-worker?to=0001-01-03",  # the default 7-day window would reach before year 1
    "/api/reports/hours-by-worker?to=0001-01-01",
    "/api/reports/hours-by-job?to=9999-12-31",
    "/api/reports/hours-by-job?from=0001-01-01&to=9999-12-31",
    "/api/reports/flagged?from=0001-01-01&to=9999-12-31",
    "/api/reports/hours.csv?from=0001-01-01&to=9999-12-31",
    "/api/reports/hours.csv?to=9999-12-31",
    "/api/jobs?date=9999-12-31",
    "/api/jobs?date=0001-01-01",
    "/api/assignments?work_date=9999-12-31",
]


@pytest.mark.parametrize("url", EXTREME_QUERIES)
def test_extreme_dates_in_filters_and_reports_are_valid_requests(client, admin_headers, url):
    res = client.get(url, headers=admin_headers)
    assert res.status_code == 200, (url, res.status_code, res.get_json(silent=True))


def test_the_last_day_is_inclusive_and_nothing_is_lost_or_invented(
    client, admin_headers, supervisor_headers, ids
):
    """An entry on 9999-12-31 is found by a 9999-12-31 filter and by a range that ends on that day."""
    day = date(9999, 12, 31)
    dispatcher = User.query.filter_by(role="Dispatcher").one()
    job = Job(
        site=JobSite.query.first(),
        creator=dispatcher,
        title="Last day",
        scheduled_date=day,
        crew_size=2,
        status="Scheduled",
    )
    db.session.add(job)
    db.session.flush()
    db.session.add(Assignment(job=job, user_id=ids["marcus"], work_date=day))
    db.session.commit()
    res = client.post("/api/time-entries", json={"user_id": ids["marcus"], "job_id": job.job_id, "clock_in": "9999-12-31T22:00", "clock_out": "9999-12-31T23:30",
                                                 "in_lat": 43.6591, "in_lng": -79.3503, "out_lat": 43.6591, "out_lng": -79.3503}, headers=supervisor_headers)  # fmt: skip
    assert res.status_code == 201 and res.get_json()["time_entry"]["hours"] == 1.5
    assert (
        len(
            client.get("/api/time-entries?date=9999-12-31", headers=admin_headers).get_json()[
                "time_entries"
            ]
        )
        == 1
    )
    rep = client.get(
        "/api/reports/hours-by-worker?from=9999-12-30&to=9999-12-31", headers=admin_headers
    ).get_json()
    assert rep["total_hours"] == 1.5
    assert (
        client.get("/api/reports/hours.csv?to=9999-12-31&from=9999-12-31", headers=admin_headers)
        .get_data(as_text=True)
        .count("\n")
        >= 2
    )
    assert (
        client.get("/api/time-entries?date=9999-12-30", headers=admin_headers).get_json()[
            "time_entries"
        ]
        == []
    )


def test_the_first_day_also_works_end_to_end(client, admin_headers, supervisor_headers, ids):
    day = date(1, 1, 1)
    dispatcher = User.query.filter_by(role="Dispatcher").one()
    job = Job(
        site=JobSite.query.first(),
        creator=dispatcher,
        title="First day",
        scheduled_date=day,
        crew_size=2,
        status="Scheduled",
    )
    db.session.add(job)
    db.session.flush()
    db.session.add(Assignment(job=job, user_id=ids["marcus"], work_date=day))
    db.session.commit()
    body = {"user_id": ids["marcus"], "job_id": job.job_id, "clock_in": "0001-01-01T08:00", "clock_out": "0001-01-01T09:00", "in_lat": 43.6591, "in_lng": -79.3503, "out_lat": 43.6591, "out_lng": -79.3503}  # fmt: skip
    assert (
        client.post("/api/time-entries", json=body, headers=supervisor_headers).status_code == 201
    )
    assert (
        client.post(
            "/api/time-entries",
            json={**body, "clock_out": None, "clock_in": "0001-01-01T08:30"},
            headers=supervisor_headers,
        ).status_code
        == 409
    )  # overlap message formats year 1
    for url in (
        "/api/time-entries?date=0001-01-01",
        "/api/reports/hours.csv?from=0001-01-01&to=0001-01-01",
        "/api/reports/hours-by-job?from=0001-01-01&to=0001-01-01",
        "/api/dashboard",
    ):
        assert client.get(url, headers=admin_headers).status_code == 200, url


def test_the_default_report_window_never_underflows(client, admin_headers):
    res = client.get("/api/reports/hours-by-worker?to=0001-01-02", headers=admin_headers)
    body = res.get_json()
    assert res.status_code == 200 and body["from"] == "0001-01-01" and body["to"] == "0001-01-02"


@pytest.mark.parametrize(
    "bad", ["0000-01-01", "10000-01-01", "2026-13-01", "2026-02-30", "99999999-12-31", "٢٠٢٦-١٠-٠١"]
)
def test_impossible_dates_stay_400(client, admin_headers, bad):
    assert client.get(f"/api/time-entries?date={bad}", headers=admin_headers).status_code == 400


# ---- genuine server errors keep their diagnostics ------------------------------------------------------------------


def test_real_server_errors_are_still_500_logged_and_generic(caplog):
    """We must not turn every exception into a 400: an unexpected bug stays a 500 with a log entry."""
    from app import create_app

    broken = create_app(
        {"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:", "BCRYPT_ROUNDS": 4}
    )

    @broken.get("/api/_boom")
    def boom():
        raise ZeroDivisionError("secret internal detail /srv/app/db.py")

    caplog.set_level(logging.ERROR)
    res = broken.test_client().get("/api/_boom")
    assert res.status_code == 500
    assert res.get_json() == {"error": "Something went wrong on the server.", "field": None}
    assert "secret internal detail" not in res.get_data(as_text=True)  # nothing leaks to the client
    assert "ZeroDivisionError" in caplog.text  # ...but the stack is in the server log


# ---- the new error responses carry the same security headers as every other response ----------------


def test_413_and_503_responses_have_the_security_headers(client, tmp_path):
    import sqlite3

    big = client.post("/api/auth/login", data=b"x" * 1_200_000, content_type="application/json")
    assert big.status_code == 413
    for header in (
        "X-Content-Type-Options",
        "X-Frame-Options",
        "Referrer-Policy",
        "Content-Security-Policy",
        "Cache-Control",
    ):
        assert header in big.headers, header

    from app import create_app

    path = tmp_path / "busy.db"
    busy = create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///" + path.as_posix(),
            "SQLITE_BUSY_TIMEOUT_SECONDS": 0.2,
            "BCRYPT_ROUNDS": 4,
        }
    )
    with busy.app_context():
        db.session.add(
            User(
                full_name="Dee Dispatch",
                email="d@test.com",
                role="Dispatcher",
                is_active=True,
                password_hash=None,
            )
        )
        db.session.commit()
        from flask_jwt_extended import create_access_token

        user = User.query.filter_by(email="d@test.com").one()
        from auth import session_claims

        token = create_access_token(
            identity=str(user.user_id), additional_claims=session_claims(user)
        )
    blocker = sqlite3.connect(path, timeout=1, isolation_level=None)
    blocker.execute("BEGIN IMMEDIATE")
    try:
        res = busy.test_client().post(
            "/api/assignments",
            json={"job_id": 1, "user_id": 1},
            headers={"Authorization": f"Bearer {token}"},
        )
    finally:
        blocker.execute("ROLLBACK")
        blocker.close()
    assert res.status_code == 503 and res.headers["Retry-After"] == "1"
    assert (
        res.headers["X-Content-Type-Options"] == "nosniff"
        and "frame-ancestors 'none'" in res.headers["Content-Security-Policy"]
    )
