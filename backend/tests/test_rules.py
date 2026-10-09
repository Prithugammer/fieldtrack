"""Business-rule tests for FieldTrack.

Run from the backend folder:   pytest -v
"""

import math
from datetime import datetime

from geofence import EARTH_RADIUS_M, haversine, should_flag
from models import Assignment, TimeEntry
from tests.conftest import DAY

SITE_LAT, SITE_LNG = 43.6591, -79.3503  # Riverside Apartments fixture site (radius 200 m)


def north_of_site(metres):
    """Coordinate exactly `metres` due north of the fixture site."""
    return SITE_LAT + math.degrees(metres / EARTH_RADIUS_M), SITE_LNG


def record(client, headers, user_id, job_id, clock_in, lat, lng, **extra):
    body = {
        "user_id": user_id,
        "job_id": job_id,
        "clock_in": clock_in,
        "in_lat": lat,
        "in_lng": lng,
    }
    body.update(extra)
    return client.post("/api/time-entries", json=body, headers=headers)


# ---- 1. Haversine accuracy ------------------------------------------------------------------


def test_haversine_known_city_pair():
    """Paris (48.8566, 2.3522) to London (51.5074, -0.1278) is about 343.5 km."""
    distance = haversine(48.8566, 2.3522, 51.5074, -0.1278)
    assert abs(distance - 343_500) < 1_000


def test_haversine_one_thousandth_degree_latitude():
    """0.001° of latitude is 111.19 m on a sphere of radius 6,371 km."""
    distance = haversine(43.0, -79.0, 43.001, -79.0)
    assert abs(distance - 111.19) < 0.05


def test_haversine_same_point_is_zero():
    assert haversine(SITE_LAT, SITE_LNG, SITE_LAT, SITE_LNG) == 0


# ---- 2. Geofence flag threshold: 199 m vs 201 m ------------------------------------------


def test_should_flag_threshold():
    assert should_flag(199, 200) is False
    assert should_flag(200, 200) is False  # boundary counts as inside
    assert should_flag(201, 200) is True


def test_entry_at_199m_is_not_flagged_and_201m_is_flagged(client, supervisor_headers, ids):
    lat, lng = north_of_site(199)
    res = record(
        client,
        supervisor_headers,
        ids["marcus"],
        ids["job_a"],
        "2026-10-01T07:00",
        lat,
        lng,
        clock_out="2026-10-01T11:00",
        out_lat=lat,
        out_lng=lng,
    )
    assert res.status_code == 201, res.get_json()
    assert res.get_json()["time_entry"]["is_flagged"] is False

    lat, lng = north_of_site(201)
    res = record(
        client, supervisor_headers, ids["marcus"], ids["job_a"], "2026-10-01T12:00", lat, lng
    )
    body = res.get_json()["time_entry"]
    assert res.status_code == 201  # flagged entries are still saved
    assert body["is_flagged"] is True
    assert "Clock-in 201 m from site (limit 200 m)" in body["flag_reason"]


# ---- 3. Shift crossing midnight -------------------------------------------------------------


def test_shift_crossing_midnight_computes_hours(client, supervisor_headers, ids):
    res = record(
        client,
        supervisor_headers,
        ids["marcus"],
        ids["job_a"],
        "2026-10-01T22:00",
        SITE_LAT,
        SITE_LNG,
        clock_out="2026-10-02T06:00",
        out_lat=SITE_LAT,
        out_lng=SITE_LNG,
    )
    assert res.status_code == 201, res.get_json()
    assert res.get_json()["time_entry"]["hours"] == 8.0


def test_midnight_clock_out_via_patch(client, supervisor_headers, ids):
    res = record(
        client,
        supervisor_headers,
        ids["marcus"],
        ids["job_a"],
        "2026-10-01T21:30",
        SITE_LAT,
        SITE_LNG,
    )
    entry_id = res.get_json()["time_entry"]["entry_id"]
    res = client.patch(
        f"/api/time-entries/{entry_id}/clock-out",
        headers=supervisor_headers,
        json={"clock_out": "2026-10-02T05:45", "out_lat": SITE_LAT, "out_lng": SITE_LNG},
    )
    assert res.status_code == 200, res.get_json()
    assert res.get_json()["time_entry"]["hours"] == 8.25


def test_hours_model_method():
    e = TimeEntry(clock_in=datetime(2026, 10, 1, 23, 0), clock_out=datetime(2026, 10, 2, 7, 30))
    assert e.hours() == 8.5


# ---- 4. Double-booking rejection -------------------------------------------------------------


def test_double_booking_is_rejected_with_409(client, dispatcher_headers, ids):
    # Ramesh is already on job A on DAY; booking him on job B the same day must fail.
    res = client.post(
        "/api/assignments",
        headers=dispatcher_headers,
        json={"job_id": ids["job_b"], "user_id": ids["marcus"]},
    )
    assert res.status_code == 409
    body = res.get_json()
    assert body["field"] == "user_id"
    assert "already assigned to 'Level 4 framing'" in body["error"]
    assert Assignment.query.filter_by(user_id=ids["marcus"], work_date=DAY).count() == 1


def test_free_worker_can_be_assigned(client, dispatcher_headers, ids):
    res = client.post(
        "/api/assignments",
        headers=dispatcher_headers,
        json={"job_id": ids["job_b"], "user_id": ids["ben"]},
    )
    assert res.status_code == 201, res.get_json()


# ---- 5. Clock-out before clock-in rejected ---------------------------------------------------


def test_clock_out_before_clock_in_is_rejected(client, supervisor_headers, ids):
    res = record(
        client,
        supervisor_headers,
        ids["marcus"],
        ids["job_a"],
        "2026-10-01T07:00",
        SITE_LAT,
        SITE_LNG,
    )
    entry_id = res.get_json()["time_entry"]["entry_id"]
    res = client.patch(
        f"/api/time-entries/{entry_id}/clock-out",
        headers=supervisor_headers,
        json={"clock_out": "2026-10-01T06:30", "out_lat": SITE_LAT, "out_lng": SITE_LNG},
    )
    assert res.status_code == 400
    assert res.get_json() == {"error": "Clock-out must be after clock-in.", "field": "clock_out"}


def test_create_with_clock_out_before_clock_in_is_rejected(client, supervisor_headers, ids):
    res = record(
        client,
        supervisor_headers,
        ids["marcus"],
        ids["job_a"],
        "2026-10-01T15:00",
        SITE_LAT,
        SITE_LNG,
        clock_out="2026-10-01T07:00",
        out_lat=SITE_LAT,
        out_lng=SITE_LNG,
    )
    assert res.status_code == 400
    assert res.get_json()["field"] == "clock_out"
    assert TimeEntry.query.count() == 0


# ---- 6. Role decorator blocks the wrong role -------------------------------------------------


def test_dispatcher_cannot_approve_time(client, dispatcher_headers, supervisor_headers, ids):
    res = record(
        client,
        supervisor_headers,
        ids["marcus"],
        ids["job_a"],
        "2026-10-01T07:00",
        SITE_LAT,
        SITE_LNG,
        clock_out="2026-10-01T15:00",
        out_lat=SITE_LAT,
        out_lng=SITE_LNG,
    )
    entry_id = res.get_json()["time_entry"]["entry_id"]
    res = client.patch(
        f"/api/time-entries/{entry_id}/approve",
        headers=dispatcher_headers,
        json={"decision": "Approved", "edit_reason": "Looks fine"},
    )
    assert res.status_code == 403
    assert "error" in res.get_json()


def test_supervisor_cannot_create_jobs(client, supervisor_headers):
    res = client.post(
        "/api/jobs",
        headers=supervisor_headers,
        json={"site_id": 1, "title": "Sneaky job", "scheduled_date": "2026-10-01", "crew_size": 1},
    )
    assert res.status_code == 403


def test_missing_token_is_401(client):
    res = client.get("/api/jobs")
    assert res.status_code == 401
    assert res.get_json()["error"]


# ---- Extra rules used in the demo -----------------------------------------------------------


def test_unassigned_worker_cannot_record_time(client, supervisor_headers, ids):
    res = record(
        client, supervisor_headers, ids["ben"], ids["job_a"], "2026-10-01T07:00", SITE_LAT, SITE_LNG
    )
    assert res.status_code == 409
    assert "not assigned" in res.get_json()["error"]


def test_approval_requires_reason_and_records_approver(client, supervisor_headers, ids):
    res = record(
        client,
        supervisor_headers,
        ids["marcus"],
        ids["job_a"],
        "2026-10-01T07:00",
        SITE_LAT,
        SITE_LNG,
        clock_out="2026-10-01T15:00",
        out_lat=SITE_LAT,
        out_lng=SITE_LNG,
    )
    entry_id = res.get_json()["time_entry"]["entry_id"]
    url = f"/api/time-entries/{entry_id}/approve"

    res = client.patch(
        url, headers=supervisor_headers, json={"decision": "Approved", "edit_reason": ""}
    )
    assert res.status_code == 400 and res.get_json()["field"] == "edit_reason"

    res = client.patch(
        url, headers=supervisor_headers, json={"decision": "Approved", "edit_reason": "Verified"}
    )
    body = res.get_json()["time_entry"]
    assert res.status_code == 200
    assert body["status"] == "Approved" and body["approved_by_name"] == "Test Supervisor"

    res = client.patch(
        url, headers=supervisor_headers, json={"decision": "Rejected", "edit_reason": "Oops"}
    )
    assert res.status_code == 409


def test_overlapping_entry_is_rejected(client, supervisor_headers, ids):
    record(
        client,
        supervisor_headers,
        ids["marcus"],
        ids["job_a"],
        "2026-10-01T07:00",
        SITE_LAT,
        SITE_LNG,
        clock_out="2026-10-01T11:30",
        out_lat=SITE_LAT,
        out_lng=SITE_LNG,
    )
    res = record(
        client,
        supervisor_headers,
        ids["marcus"],
        ids["job_a"],
        "2026-10-01T11:00",
        SITE_LAT,
        SITE_LNG,
    )
    assert res.status_code == 409 and res.get_json()["field"] == "clock_in"


def test_validation_errors_name_the_field(client, dispatcher_headers):
    res = client.post(
        "/api/sites",
        headers=dispatcher_headers,
        json={"site_name": "Bad", "address": "1 Main St", "latitude": 95, "longitude": -79},
    )
    assert res.status_code == 400
    assert res.get_json()["field"] == "latitude"
