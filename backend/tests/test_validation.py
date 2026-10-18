"""Input validation at the trust boundary: numeric limits, ids, dates, enums, malformed bodies.

The QA review found two HTTP 500s (a JSON `1e999` and a 23-digit id in a URL). Both came from
numbers the database driver cannot hold, so the helpers and every endpoint that takes an id are
tested here with the exact boundary values.
"""

import math

import pytest

from extensions import db
from models import Assignment, Job, JobSite, LocationPing, TimeEntry, User
from tests.conftest import DAY
from validation import (
    INT64_MAX,
    INT64_MIN,
    ApiError,
    get_or_404,
    one_of,
    parse_bool,
    parse_date,
    parse_datetime,
    parse_float,
    parse_id,
    parse_int,
    require_str,
    validate_email,
    validate_password,
    validate_phone,
)

# ---- parse_int / parse_id: the helper ---------------------------------------------------------


@pytest.mark.parametrize("value", [INT64_MAX, INT64_MIN, 0, 1, -1, "42", " 7 ", 5.0])
def test_parse_int_accepts_values_inside_the_64_bit_range(value):
    assert parse_int(value, "n", "N") == int(value)


@pytest.mark.parametrize(
    "value",
    [
        2**63,
        -(2**63) - 1,
        10**29,  # 30 digits
        -(10**29),
        "9223372036854775808",
        "9" * 30,
        float("inf"),
        float("-inf"),
        float("nan"),
        1e999,  # what json.loads makes of the literal 1e999: infinity
        1e30,  # finite, whole, but far beyond 64 bits
    ],
)
def test_parse_int_rejects_oversized_and_non_finite_numbers(value):
    with pytest.raises(ApiError) as err:
        parse_int(value, "n", "N")
    assert err.value.status == 400 and err.value.field == "n"


@pytest.mark.parametrize("value", [True, False, "abc", "1e999", "1.5", 1.5, [], {}, [1], "0x10"])
def test_parse_int_rejects_non_integers(value):
    with pytest.raises(ApiError):
        parse_int(value, "n", "N")


def test_parse_int_blank_optional_and_required():
    assert parse_int(None, "n", "N", required=False) is None
    assert parse_int("", "n", "N", required=False) is None
    with pytest.raises(ApiError, match="required"):
        parse_int(None, "n", "N")


def test_parse_int_applies_field_bounds_separately_from_the_64_bit_range():
    assert parse_int(5, "n", "N", 1, 5) == 5
    with pytest.raises(ApiError, match="at least 1"):
        parse_int(0, "n", "N", 1, 5)
    with pytest.raises(ApiError, match="at most 5"):
        parse_int(6, "n", "N", 1, 5)


@pytest.mark.parametrize("value", [0, -1, -(2**63), 2**63, "0", 1e999, float("nan")])
def test_parse_id_requires_a_positive_id_in_range(value):
    with pytest.raises(ApiError):
        parse_id(value, "id", "Id")


def test_parse_id_accepts_the_largest_id():
    assert parse_id(INT64_MAX, "id", "Id") == INT64_MAX
    assert parse_id("1", "id", "Id") == 1
    assert parse_id(None, "id", "Id", required=False) is None


def test_parse_float_rejects_non_finite_and_unbounded_overflow():
    for bad in (float("inf"), float("-inf"), float("nan"), "inf", "nan", "1e999", 10**400, True):
        with pytest.raises(ApiError):
            parse_float(bad, "x", "X")
    assert parse_float("2.5", "x", "X") == 2.5
    assert parse_float(None, "x", "X", required=False) is None
    with pytest.raises(ApiError, match="between"):
        parse_float(91, "x", "X", -90, 90)


def test_get_or_404_never_hands_an_out_of_range_id_to_the_database(app):
    for bad in (0, -1, 2**63, 10**23, "7", None):
        with pytest.raises(ApiError) as err:
            get_or_404(User, bad, "User")
        assert err.value.status == 404
    assert get_or_404(User, User.query.first().user_id, "User")


# ---- the other helpers ------------------------------------------------------------------------


def test_string_helpers_enforce_type_and_length():
    assert require_str("  hi  ", "f", "F") == "hi"
    assert require_str("  ", "f", "F", required=False) is None
    for bad in (123, ["a"], {"a": 1}):
        with pytest.raises(ApiError, match="text"):
            require_str(bad, "f", "F")
    with pytest.raises(ApiError, match="at least"):
        require_str("a", "f", "F", min_len=2)
    with pytest.raises(ApiError, match="at most"):
        require_str("a" * 6, "f", "F", max_len=5)


def test_password_limit_is_72_bytes_not_characters():
    assert validate_password("x" * 72) == "x" * 72
    with pytest.raises(ApiError, match="72 bytes"):
        validate_password("x" * 73)
    with pytest.raises(ApiError, match="72 bytes"):
        validate_password("é" * 40)  # 40 characters but 80 bytes
    with pytest.raises(ApiError, match="at least"):
        validate_password("short")


@pytest.mark.parametrize(
    "bad", ["not-a-date", "2026-13-01", "2026-02-30", "", "01/02/2026", 20261001]
)
def test_parse_date_rejects_malformed_dates(bad):
    if bad in ("", None):
        assert parse_date(bad, "d", "D", required=False) is None
        return
    with pytest.raises(ApiError, match="YYYY-MM-DD"):
        parse_date(bad, "d", "D")


def test_parse_datetime_refuses_time_zones_and_garbage():
    assert parse_datetime("2026-10-01T07:00:30.500", "t", "T").isoformat() == "2026-10-01T07:00:30"
    for zoned in ("2026-10-01T07:00:00+05:45", "2026-10-01T07:00:00Z", "2026-10-01T07:00-02:00"):
        with pytest.raises(ApiError, match="time zone"):  # D-11: used to be silently dropped
            parse_datetime(zoned, "t", "T")
    for bad in ("yesterday", "2026-10-01T25:00", "2026-10-01T07:61", 7):
        with pytest.raises(ApiError):
            parse_datetime(bad, "t", "T")


def test_enum_bool_email_and_phone_helpers():
    assert one_of("Admin", "r", "R", ("Admin", "Worker")) == "Admin"
    for bad in ("admin", "'; DROP TABLE users;--", 5, ["Admin"]):
        with pytest.raises(ApiError, match="one of"):
            one_of(bad, "r", "R", ("Admin", "Worker"))
    assert parse_bool("TRUE", "b", "B") is True and parse_bool("0", "b", "B") is False
    for bad in ("yes", 2, [], {}):
        with pytest.raises(ApiError):
            parse_bool(bad, "b", "B")
    assert validate_email(" A@B.CO ") == "a@b.co"
    for bad in ("nope", "a@b", "a b@c.de", "@x.yz"):
        with pytest.raises(ApiError):
            validate_email(bad)
    assert validate_phone("+977-9841-0100") == "+977-9841-0100"
    with pytest.raises(ApiError):
        validate_phone("call me maybe")
    assert not math.isnan(parse_float("1", "x", "X"))


# ---- the two reported 500s, and their relatives, over HTTP -------------------------------------


def _counts():
    return {
        "entries": TimeEntry.query.count(),
        "pings": LocationPing.query.count(),
        "jobs": Job.query.count(),
        "assignments": Assignment.query.count(),
        "users": User.query.count(),
        "sites": JobSite.query.count(),
    }


def _entry_body(ids, **changes):
    body = {
        "user_id": ids["marcus"],
        "job_id": ids["job_a"],
        "clock_in": f"{DAY}T07:00",
        "in_lat": 43.6591,
        "in_lng": -79.3503,
    }
    body.update(changes)
    return body


def test_json_1e999_user_id_is_a_400_not_a_500(client, supervisor_headers, ids):
    before = _counts()
    # Sent as raw JSON text: Python's json parser turns 1e999 into infinity.
    res = client.post(
        "/api/time-entries",
        data='{"user_id": 1e999, "job_id": 1, "clock_in": "2026-10-01T07:00",'
        ' "in_lat": 1, "in_lng": 1}',
        content_type="application/json",
        headers=supervisor_headers,
    )
    assert res.status_code == 400 and res.get_json()["field"] == "user_id"
    assert _counts() == before


@pytest.mark.parametrize("path", ["/api/jobs/", "/api/safety/workers/"])
def test_huge_resource_id_in_the_url_is_404(client, supervisor_headers, path):
    suffix = "" if path == "/api/jobs/" else "/accident"
    for huge in ("99999999999999999999999", str(2**63), str(2**63 - 1), "0"):
        url = f"{path}{huge}{suffix}"
        method = "post" if suffix else "get"
        res = getattr(client, method)(url, headers=supervisor_headers)
        assert res.status_code == 404, (url, res.status_code)


def test_huge_id_in_every_item_url_is_404(client, admin_headers):
    huge = "99999999999999999999999"
    for method, url in (
        ("get", f"/api/jobs/{huge}"),
        ("patch", f"/api/jobs/{huge}"),
        ("patch", f"/api/users/{huge}"),
        ("patch", f"/api/sites/{huge}"),
        ("delete", f"/api/assignments/{huge}"),
        ("patch", f"/api/time-entries/{huge}/clock-out"),
        ("patch", f"/api/time-entries/{huge}/approve"),
    ):
        res = getattr(client, method)(url, json={}, headers=admin_headers)
        assert res.status_code == 404, (method, url, res.status_code)
        assert res.get_json()["error"]


@pytest.mark.parametrize(
    "value",
    [2**63, -(2**63), 0, -1, "9" * 30, 1e999, -1e999, "abc", 1.5, True, [], {}],
)
@pytest.mark.parametrize("field", ["user_id", "job_id"])
def test_bad_ids_in_a_time_entry_body_are_400(client, supervisor_headers, ids, field, value):
    before = _counts()
    res = client.post(
        "/api/time-entries", json=_entry_body(ids, **{field: value}), headers=supervisor_headers
    )
    assert res.status_code == 400, (field, value, res.get_json())
    assert res.get_json()["field"] == field
    assert _counts() == before


def test_the_largest_valid_id_that_does_not_exist_is_404(client, supervisor_headers, ids):
    res = client.post(
        "/api/time-entries",
        json=_entry_body(ids, user_id=INT64_MAX),
        headers=supervisor_headers,
    )
    assert res.status_code == 404 and res.get_json()["field"] == "user_id"


@pytest.mark.parametrize("value", [2**63, "9" * 30, 0, -5, "x", 1e999])
@pytest.mark.parametrize(
    "path,param",
    [
        ("/api/jobs", "site_id"),
        ("/api/assignments", "job_id"),
        ("/api/assignments", "user_id"),
        ("/api/time-entries", "worker"),
        ("/api/time-entries", "job_id"),
        ("/api/safety/audit", "worker_id"),
        ("/api/map/live", "route"),
    ],
)
def test_bad_ids_in_query_filters_are_400(client, admin_headers, path, param, value):
    res = client.get(path, query_string={param: str(value)}, headers=admin_headers)
    assert res.status_code == 400, (path, param, value)
    assert res.get_json()["field"] == param


def test_valid_query_filters_still_work(client, admin_headers, ids):
    assert client.get(f"/api/jobs?site_id={JobSite.query.first().site_id}", headers=admin_headers)
    res = client.get(f"/api/time-entries?worker={ids['marcus']}", headers=admin_headers)
    assert res.status_code == 200
    res = client.get(f"/api/assignments?job_id={ids['job_a']}", headers=admin_headers)
    assert len(res.get_json()["assignments"]) == 1


@pytest.mark.parametrize("value", [2**63, "9" * 30, 0, -1, 1e999, "1e999", 2.5, "abc", None])
def test_bad_foreign_keys_when_creating_and_editing_jobs(client, dispatcher_headers, ids, value):
    before = _counts()
    body = {"title": "Concrete", "scheduled_date": str(DAY), "crew_size": 2, "site_id": value}
    res = client.post("/api/jobs", json=body, headers=dispatcher_headers)
    assert res.status_code in (400, 404), res.get_json()
    res = client.patch(
        f"/api/jobs/{ids['job_a']}", json={"site_id": value}, headers=dispatcher_headers
    )
    assert res.status_code in (400, 404), res.get_json()
    assert _counts() == before
    assert db.session.get(Job, ids["job_a"]).site_id == JobSite.query.first().site_id


@pytest.mark.parametrize("value", [2**63, "9" * 30, 0, -1, 1e999, "x"])
def test_bad_ids_when_creating_an_assignment(client, dispatcher_headers, ids, value):
    before = _counts()
    for field in ("job_id", "user_id"):
        body = {"job_id": ids["job_b"], "user_id": ids["ben"], field: value}
        res = client.post("/api/assignments", json=body, headers=dispatcher_headers)
        assert res.status_code == 400 and res.get_json()["field"] == field
    assert _counts() == before


@pytest.mark.parametrize("value", [2**63, 1e999, "abc", 0, -1, 2.5, True, "9" * 30])
def test_crew_size_and_geofence_radius_reject_bad_numbers(client, dispatcher_headers, ids, value):
    res = client.patch(
        f"/api/jobs/{ids['job_a']}", json={"crew_size": value}, headers=dispatcher_headers
    )
    assert res.status_code == 400 and res.get_json()["field"] == "crew_size"
    res = client.patch(
        "/api/sites/1", json={"geofence_radius_m": value}, headers=dispatcher_headers
    )
    assert res.status_code == 400 and res.get_json()["field"] == "geofence_radius_m"


@pytest.mark.parametrize("value", [1e999, -1e999, "nan", "inf", 181, -181, "abc", True, None])
def test_latitude_and_longitude_reject_non_finite_and_out_of_range(
    client, dispatcher_headers, value
):
    for field in ("latitude", "longitude"):
        body = {"site_name": "Edge", "address": "1 Test Road", "latitude": 1, "longitude": 1}
        body[field] = value
        res = client.post("/api/sites", json=body, headers=dispatcher_headers)
        assert res.status_code == 400 and res.get_json()["field"] == field


def test_crew_size_has_an_upper_limit(client, dispatcher_headers, ids):
    res = client.patch(
        f"/api/jobs/{ids['job_a']}", json={"crew_size": 51}, headers=dispatcher_headers
    )
    assert res.status_code == 400 and res.get_json()["field"] == "crew_size"


def test_latitude_is_limited_to_90_and_longitude_to_180(client, dispatcher_headers):
    base = {"site_name": "Edge", "address": "1 Test Road", "latitude": 0, "longitude": 0}
    lat = client.post("/api/sites", json={**base, "latitude": 91}, headers=dispatcher_headers)
    lng = client.post("/api/sites", json={**base, "longitude": 91}, headers=dispatcher_headers)
    assert lat.status_code == 400 and lng.status_code == 201


# ---- malformed bodies and odd input ------------------------------------------------------------


@pytest.mark.parametrize("raw", ["", "not json", "[1,2]", '"text"', "null", "{", "42"])
def test_malformed_or_non_object_bodies_are_400(client, admin_headers, raw):
    for method, url in (
        ("post", "/api/users"),
        ("post", "/api/jobs"),
        ("post", "/api/sites"),
        ("post", "/api/assignments"),
        ("post", "/api/time-entries"),
        ("post", "/api/auth/login"),
    ):
        res = getattr(client, method)(
            url, data=raw, content_type="application/json", headers=admin_headers
        )
        assert res.status_code == 400, (url, raw)
        assert res.get_json()["error"]


def test_sql_style_strings_are_data_not_code(client, admin_headers, dispatcher_headers):
    nasty = "Robert'); DROP TABLE users;--"
    res = client.post(
        "/api/users",
        json={"full_name": nasty, "email": "bobby@test.com", "role": "Worker", "trade": nasty},
        headers=admin_headers,
    )
    assert res.status_code == 201 and res.get_json()["user"]["full_name"] == nasty
    assert User.query.count() >= 5
    users = client.get("/api/users?role=Worker' OR '1'='1", headers=admin_headers)
    assert users.status_code == 400
    jobs = client.get("/api/jobs?status=x' OR 1=1 --", headers=dispatcher_headers)
    assert jobs.status_code == 400
    jobs = client.get("/api/jobs?date=2026-10-01' OR 1=1", headers=dispatcher_headers)
    assert jobs.status_code == 400


def test_validation_errors_always_use_the_error_field_shape(client, admin_headers):
    res = client.post("/api/users", json={}, headers=admin_headers)
    body = res.get_json()
    assert res.status_code == 400 and set(body) == {"error", "field"}
