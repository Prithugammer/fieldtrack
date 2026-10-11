"""Assignments, time entries, approvals, reports and the dashboard at the API boundary."""

from datetime import date, datetime, timedelta

import pytest

from extensions import db
from models import Assignment, Job, JobSite, LocationPing, TimeEntry, User
from tests.conftest import DAY

SITE_LAT, SITE_LNG = 43.6591, -79.3503  # Riverside Apartments (200 m geofence)


def entry_body(ids, **changes):
    body = {
        "user_id": ids["marcus"],
        "job_id": ids["job_a"],
        "clock_in": f"{DAY}T07:00",
        "in_lat": SITE_LAT,
        "in_lng": SITE_LNG,
    }
    body.update(changes)
    return body


def make_entry(client, headers, ids, **changes):
    res = client.post("/api/time-entries", json=entry_body(ids, **changes), headers=headers)
    assert res.status_code == 201, res.get_json()
    return res.get_json()["time_entry"]


# ---- assignments ---------------------------------------------------------------------------------


def test_listing_assignments_filters_by_job_worker_and_date(client, dispatcher_headers, ids):
    db.session.add(Assignment(job_id=ids["job_b"], user_id=ids["ben"], work_date=DAY))
    db.session.commit()

    def rows(query):
        res = client.get(f"/api/assignments?{query}", headers=dispatcher_headers)
        assert res.status_code == 200
        return res.get_json()["assignments"]

    assert len(rows("")) == 2
    assert [a["user_id"] for a in rows(f"job_id={ids['job_b']}")] == [ids["ben"]]
    assert [a["job_id"] for a in rows(f"user_id={ids['marcus']}")] == [ids["job_a"]]
    assert len(rows(f"work_date={DAY}")) == 2 and rows("work_date=2000-01-01") == []
    assert (
        client.get("/api/assignments?work_date=soon", headers=dispatcher_headers).status_code == 400
    )


def test_assigning_a_worker_succeeds_then_refuses_duplicates_and_double_booking(
    client, dispatcher_headers, ids
):
    ok = client.post(
        "/api/assignments",
        json={"job_id": ids["job_a"], "user_id": ids["ben"]},
        headers=dispatcher_headers,
    )
    assert ok.status_code == 201 and ok.get_json()["assignment"]["work_date"] == str(DAY)
    again = client.post(
        "/api/assignments",
        json={"job_id": ids["job_a"], "user_id": ids["ben"]},
        headers=dispatcher_headers,
    )
    assert again.status_code == 409 and "already on this job" in again.get_json()["error"]
    elsewhere = client.post(
        "/api/assignments",
        json={"job_id": ids["job_b"], "user_id": ids["marcus"]},
        headers=dispatcher_headers,
    )
    assert elsewhere.status_code == 409 and "Level 4 framing" in elsewhere.get_json()["error"]
    assert Assignment.query.count() == 2


def test_only_dispatchers_and_admins_change_assignments(client, supervisor_headers, ids):
    body = {"job_id": ids["job_a"], "user_id": ids["ben"]}
    assert client.post("/api/assignments", json=body, headers=supervisor_headers).status_code == 403
    assignment = Assignment.query.first()
    res = client.delete(f"/api/assignments/{assignment.assignment_id}", headers=supervisor_headers)
    assert res.status_code == 403 and db.session.get(Assignment, assignment.assignment_id)


@pytest.mark.parametrize(
    "mutate,status,field",
    [
        (lambda b, ids: b.update(job_id=999999), 404, "job_id"),
        (lambda b, ids: b.update(user_id=999999), 404, "user_id"),
        (lambda b, ids: b.update(user_id=1), 400, "user_id"),  # an Admin, not a Worker
        (lambda b, ids: b.update(work_date="2030-01-01"), 400, "work_date"),
        (lambda b, ids: b.update(work_date="soon"), 400, "work_date"),
    ],
)
def test_invalid_assignments_are_rejected(client, dispatcher_headers, ids, mutate, status, field):
    body = {"job_id": ids["job_b"], "user_id": ids["ben"]}
    mutate(body, ids)
    before = Assignment.query.count()
    res = client.post("/api/assignments", json=body, headers=dispatcher_headers)
    assert res.status_code == status and res.get_json()["field"] == field
    assert Assignment.query.count() == before


def test_assignment_rules_for_inactive_workers_completed_jobs_and_full_crews(
    client, dispatcher_headers, ids
):
    User.query.filter_by(user_id=ids["ben"]).one().is_active = False
    db.session.commit()
    body = {"job_id": ids["job_b"], "user_id": ids["ben"]}
    res = client.post("/api/assignments", json=body, headers=dispatcher_headers)
    assert res.status_code == 400 and "deactivated" in res.get_json()["error"]

    User.query.filter_by(user_id=ids["ben"]).one().is_active = True
    job = db.session.get(Job, ids["job_b"])
    job.status = "Completed"
    db.session.commit()
    res = client.post("/api/assignments", json=body, headers=dispatcher_headers)
    assert res.status_code == 409 and res.get_json()["field"] == "job_id"

    job.status = "Scheduled"
    job.crew_size = 1
    db.session.add(
        Assignment(job_id=ids["job_b"], user_id=ids["marcus"], work_date=DAY - timedelta(days=1))
    )
    db.session.commit()  # one worker already fills the crew of one (on an earlier day's row)
    Assignment.query.filter_by(user_id=ids["marcus"], work_date=DAY).delete()
    db.session.commit()
    db.session.add(Assignment(job_id=ids["job_b"], user_id=ids["marcus"], work_date=DAY))
    db.session.commit()
    res = client.post("/api/assignments", json=body, headers=dispatcher_headers)
    assert res.status_code == 409 and "full" in res.get_json()["error"]


def test_removing_an_assignment_works_unless_time_was_recorded(
    client, dispatcher_headers, supervisor_headers, ids
):
    make_entry(client, supervisor_headers, ids)
    blocked = Assignment.query.filter_by(user_id=ids["marcus"]).one()
    res = client.delete(f"/api/assignments/{blocked.assignment_id}", headers=dispatcher_headers)
    assert res.status_code == 409 and "Time has already been recorded" in res.get_json()["error"]

    fresh = Assignment(job_id=ids["job_b"], user_id=ids["ben"], work_date=DAY)
    db.session.add(fresh)
    db.session.commit()
    gone = client.delete(f"/api/assignments/{fresh.assignment_id}", headers=dispatcher_headers)
    assert gone.status_code == 200 and db.session.get(Assignment, fresh.assignment_id) is None
    assert client.delete("/api/assignments/424242", headers=dispatcher_headers).status_code == 404


# ---- creating time entries -----------------------------------------------------------------------


def test_a_clock_in_inside_the_geofence_is_saved_unflagged_with_a_ping(
    client, supervisor_headers, ids
):
    entry = make_entry(client, supervisor_headers, ids)
    assert (
        entry["is_flagged"] is False and entry["status"] == "Pending" and entry["clock_out"] is None
    )
    assert LocationPing.query.count() == 1


def test_a_clock_in_outside_the_geofence_is_saved_and_flagged(client, supervisor_headers, ids):
    entry = make_entry(client, supervisor_headers, ids, in_lat=SITE_LAT + 0.01)
    assert entry["is_flagged"] is True and "Clock-in" in entry["flag_reason"]
    assert TimeEntry.query.count() == 1


def test_a_night_shift_across_midnight_counts_its_full_length(client, supervisor_headers, ids):
    entry = make_entry(
        client,
        supervisor_headers,
        ids,
        clock_in=f"{DAY}T22:00",
        clock_out=f"{DAY + timedelta(days=1)}T06:30",
        out_lat=SITE_LAT,
        out_lng=SITE_LNG,
    )
    assert entry["hours"] == 8.5 and LocationPing.query.count() == 2


@pytest.mark.parametrize(
    "changes,status,field",
    [
        ({"user_id": 999999}, 404, "user_id"),
        ({"job_id": 999999}, 404, "job_id"),
        ({"job_id": "job_b"}, 400, "job_id"),
        ({"clock_in": "07:00"}, 400, "clock_in"),
        ({"clock_in": None}, 400, "clock_in"),
        ({"in_lat": 91}, 400, "in_lat"),
        ({"in_lng": "west"}, 400, "in_lng"),
        ({"clock_out": f"{DAY}T06:00", "out_lat": SITE_LAT, "out_lng": SITE_LNG}, 400, "clock_out"),
        ({"clock_out": f"{DAY}T09:00"}, 400, "out_lat"),
        (
            {
                "clock_out": f"{DAY + timedelta(days=2)}T09:00",
                "out_lat": SITE_LAT,
                "out_lng": SITE_LNG,
            },
            400,
            "clock_out",
        ),
        ({"clock_in": f"{DAY + timedelta(days=3)}T07:00"}, 409, "user_id"),  # not assigned that day
    ],
)
def test_invalid_time_entries_are_rejected_and_not_saved(
    client, supervisor_headers, ids, changes, status, field
):
    if changes.get("job_id") == "job_b":
        changes["job_id"] = "x"
    res = client.post(
        "/api/time-entries", json=entry_body(ids, **changes), headers=supervisor_headers
    )
    assert res.status_code == status and res.get_json()["field"] == field
    assert TimeEntry.query.count() == 0 and LocationPing.query.count() == 0


def test_only_active_workers_can_have_time_recorded(client, supervisor_headers, ids):
    res = client.post(
        "/api/time-entries", json=entry_body(ids, user_id=1), headers=supervisor_headers
    )
    assert res.status_code == 400 and "not an active worker" in res.get_json()["error"]
    User.query.filter_by(user_id=ids["marcus"]).one().is_active = False
    db.session.commit()
    res = client.post("/api/time-entries", json=entry_body(ids), headers=supervisor_headers)
    assert res.status_code == 400 and res.get_json()["field"] == "user_id"


def test_overlapping_entries_are_refused_but_rejected_ones_do_not_block(
    client, admin_headers, supervisor_headers, ids
):
    first = make_entry(
        client,
        supervisor_headers,
        ids,
        clock_out=f"{DAY}T11:00",
        out_lat=SITE_LAT,
        out_lng=SITE_LNG,
    )
    clash = client.post(
        "/api/time-entries",
        json=entry_body(ids, clock_in=f"{DAY}T10:30"),
        headers=supervisor_headers,
    )
    assert clash.status_code == 409 and "Overlaps entry" in clash.get_json()["error"]
    after = client.post(
        "/api/time-entries",
        json=entry_body(ids, clock_in=f"{DAY}T11:00"),
        headers=supervisor_headers,
    )
    assert after.status_code == 201  # starts exactly when the other ends: allowed
    client.patch(
        f"/api/time-entries/{first['entry_id']}/approve",
        json={"decision": "Rejected", "edit_reason": "Wrong job"},
        headers=admin_headers,
    )
    still_open = TimeEntry.query.filter(TimeEntry.clock_out.is_(None)).one()
    second_open = client.post(
        "/api/time-entries",
        json=entry_body(ids, clock_in=f"{DAY}T12:00"),
        headers=supervisor_headers,
    )
    assert (
        second_open.status_code == 409
        and f"#{still_open.entry_id}" in second_open.get_json()["error"]
    )


def test_only_supervisors_and_admins_record_time(client, dispatcher_headers, admin_headers, ids):
    res = client.post("/api/time-entries", json=entry_body(ids), headers=dispatcher_headers)
    assert res.status_code == 403 and TimeEntry.query.count() == 0
    assert (
        client.post("/api/time-entries", json=entry_body(ids), headers=admin_headers).status_code
        == 201
    )


# ---- clock-out -----------------------------------------------------------------------------------


def test_clock_out_closes_an_open_entry_and_applies_the_geofence_again(
    client, supervisor_headers, ids
):
    entry = make_entry(client, supervisor_headers, ids)
    url = f"/api/time-entries/{entry['entry_id']}/clock-out"
    body = {"clock_out": f"{DAY}T15:30", "out_lat": SITE_LAT + 0.01, "out_lng": SITE_LNG}
    res = client.patch(url, json=body, headers=supervisor_headers)
    out = res.get_json()["time_entry"]
    assert res.status_code == 200 and out["hours"] == 8.5 and out["is_flagged"] is True
    assert "Clock-out" in out["flag_reason"] and LocationPing.query.count() == 2
    again = client.patch(url, json=body, headers=supervisor_headers)
    assert again.status_code == 409 and again.get_json()["field"] == "clock_out"


@pytest.mark.parametrize(
    "body,field",
    [
        ({"clock_out": f"{DAY}T06:00", "out_lat": SITE_LAT, "out_lng": SITE_LNG}, "clock_out"),
        (
            {
                "clock_out": f"{DAY + timedelta(days=2)}T08:00",
                "out_lat": SITE_LAT,
                "out_lng": SITE_LNG,
            },
            "clock_out",
        ),
        ({"clock_out": "nonsense", "out_lat": SITE_LAT, "out_lng": SITE_LNG}, "clock_out"),
        ({"clock_out": f"{DAY}T09:00", "out_lat": "x", "out_lng": SITE_LNG}, "out_lat"),
        ({"clock_out": f"{DAY}T09:00", "out_lat": SITE_LAT}, "out_lng"),
    ],
)
def test_invalid_clock_outs_leave_the_entry_open(client, supervisor_headers, ids, body, field):
    entry = make_entry(client, supervisor_headers, ids)
    res = client.patch(
        f"/api/time-entries/{entry['entry_id']}/clock-out", json=body, headers=supervisor_headers
    )
    assert res.status_code == 400 and res.get_json()["field"] == field
    db.session.expire_all()
    assert db.session.get(TimeEntry, entry["entry_id"]).clock_out is None


def test_clock_out_of_a_missing_entry_is_404(client, supervisor_headers):
    res = client.patch("/api/time-entries/31337/clock-out", json={}, headers=supervisor_headers)
    assert res.status_code == 404


# ---- approvals -----------------------------------------------------------------------------------


def closed_entry(client, headers, ids):
    return make_entry(
        client, headers, ids, clock_out=f"{DAY}T15:00", out_lat=SITE_LAT, out_lng=SITE_LNG
    )


def test_a_supervisor_approves_with_a_reason_and_is_recorded_as_the_approver(
    client, supervisor_headers, ids
):
    entry = closed_entry(client, supervisor_headers, ids)
    url = f"/api/time-entries/{entry['entry_id']}/approve"
    res = client.patch(
        url,
        json={"decision": "Approved", "edit_reason": "Matches the log"},
        headers=supervisor_headers,
    )
    done = res.get_json()["time_entry"]
    assert res.status_code == 200 and done["status"] == "Approved" and done["approved_by"]
    again = client.patch(
        url,
        json={"decision": "Rejected", "edit_reason": "Changed my mind"},
        headers=supervisor_headers,
    )
    assert again.status_code == 409 and "already approved" in again.get_json()["error"]


@pytest.mark.parametrize(
    "body,field",
    [
        ({"decision": "Maybe", "edit_reason": "because"}, "decision"),
        ({"decision": "Approved"}, "edit_reason"),
        ({"decision": "Approved", "edit_reason": "ok"}, "edit_reason"),  # under 3 characters
        ({"decision": "Pending", "edit_reason": "reset it"}, "decision"),
    ],
)
def test_approval_needs_a_valid_decision_and_reason(client, supervisor_headers, ids, body, field):
    entry = closed_entry(client, supervisor_headers, ids)
    res = client.patch(
        f"/api/time-entries/{entry['entry_id']}/approve", json=body, headers=supervisor_headers
    )
    assert res.status_code == 400 and res.get_json()["field"] == field
    db.session.expire_all()
    assert db.session.get(TimeEntry, entry["entry_id"]).status == "Pending"


def test_an_open_entry_cannot_be_approved(client, supervisor_headers, ids):
    entry = make_entry(client, supervisor_headers, ids)
    res = client.patch(
        f"/api/time-entries/{entry['entry_id']}/approve",
        json={"decision": "Approved", "edit_reason": "looks fine"},
        headers=supervisor_headers,
    )
    assert res.status_code == 400 and "Clock the worker out" in res.get_json()["error"]


def test_dispatchers_cannot_approve_and_missing_entries_are_404(
    client, supervisor_headers, dispatcher_headers, ids
):
    entry = closed_entry(client, supervisor_headers, ids)
    body = {"decision": "Approved", "edit_reason": "trying anyway"}
    res = client.patch(
        f"/api/time-entries/{entry['entry_id']}/approve", json=body, headers=dispatcher_headers
    )
    assert res.status_code == 403
    db.session.expire_all()
    assert db.session.get(TimeEntry, entry["entry_id"]).status == "Pending"
    assert (
        client.patch(
            "/api/time-entries/9999/approve", json=body, headers=supervisor_headers
        ).status_code
        == 404
    )


# ---- listing, reports, dashboard ---------------------------------------------------------------


def test_time_entry_list_filters(client, supervisor_headers, admin_headers, ids):
    closed_entry(client, supervisor_headers, ids)
    flagged = make_entry(
        client, supervisor_headers, ids, clock_in=f"{DAY}T16:00", in_lat=SITE_LAT + 0.02
    )

    def rows(query):
        res = client.get(f"/api/time-entries?{query}", headers=admin_headers)
        assert res.status_code == 200
        return res.get_json()["time_entries"]

    assert len(rows("")) == 2
    assert [e["entry_id"] for e in rows("flagged=true")] == [flagged["entry_id"]]
    assert len(rows("flagged=false")) == 1 and len(rows("status=Pending")) == 2
    assert rows("status=Approved") == [] and len(rows(f"worker={ids['marcus']}")) == 2
    assert rows(f"worker={ids['ben']}") == [] and len(rows(f"job_id={ids['job_a']}")) == 2
    assert len(rows(f"date={DAY}")) == 2 and rows("date=2000-01-01") == []
    assert rows("")[0]["entry_id"] == flagged["entry_id"]  # newest first
    for bad in ("status=Done", "flagged=perhaps", "date=x"):
        assert client.get(f"/api/time-entries?{bad}", headers=admin_headers).status_code == 400


def test_reports_summarise_approved_and_pending_hours(
    client, supervisor_headers, admin_headers, ids
):
    entry = closed_entry(client, supervisor_headers, ids)
    client.patch(
        f"/api/time-entries/{entry['entry_id']}/approve",
        json={"decision": "Approved", "edit_reason": "Verified"},
        headers=supervisor_headers,
    )
    make_entry(
        client,
        supervisor_headers,
        ids,
        clock_in=f"{DAY}T16:00",
        clock_out=f"{DAY}T17:30",
        out_lat=SITE_LAT,
        out_lng=SITE_LNG,
    )
    window = f"from={DAY}&to={DAY}"
    by_worker = client.get(f"/api/reports/hours-by-worker?{window}", headers=admin_headers)
    assert by_worker.status_code == 200
    body = by_worker.get_json()
    row = next(r for r in body["rows"] if r["user_id"] == ids["marcus"])
    assert row["approved_hours"] == 8.0 and row["pending_hours"] == 1.5
    assert body["total_hours"] == 9.5
    by_job = client.get(f"/api/reports/hours-by-job?{window}", headers=admin_headers)
    job_rows = by_job.get_json()["rows"]
    assert (
        by_job.status_code == 200
        and job_rows[0]["workers"] == 1
        and job_rows[0]["total_hours"] == 9.5
    )
    assert client.get(f"/api/reports/flagged?{window}", headers=admin_headers).status_code == 200
    csv_res = client.get(f"/api/reports/hours.csv?{window}", headers=admin_headers)
    text = csv_res.get_data(as_text=True)
    assert csv_res.mimetype == "text/csv" and "Ramesh Karki" in text
    assert (
        client.get(
            "/api/reports/hours-by-worker?from=2026-10-05&to=2026-10-01", headers=admin_headers
        ).status_code
        == 400
    )


def test_dashboard_reports_open_overnight_and_understaffed_jobs(
    client, supervisor_headers, admin_headers
):
    today = date.today()
    site = JobSite.query.first()
    creator = User.query.filter_by(role="Dispatcher").first()
    worker = User.query.filter_by(email="marcus@test.com").one()
    job = Job(
        site=site,
        creator=creator,
        title="Today job",
        scheduled_date=today,
        crew_size=3,
        status="In progress",
    )
    db.session.add(job)
    db.session.flush()
    db.session.add(Assignment(job=job, worker=worker, work_date=today))
    yesterday_night = datetime.combine(today - timedelta(days=1), datetime.min.time()).replace(
        hour=22
    )
    entry = TimeEntry(
        worker=worker,
        job=job,
        clock_in=yesterday_night,
        in_lat=site.latitude,
        in_lng=site.longitude,
        status="Pending",
        is_flagged=True,
    )
    entry.add_flag("Clock-in was 500 m from the site")
    db.session.add(entry)
    db.session.commit()

    data = client.get("/api/dashboard", headers=admin_headers).get_json()
    kinds = {item["type"] for item in data["needs_attention"]}
    assert {"flagged_entry", "understaffed_job", "open_overnight"} <= kinds
    assert data["kpis"]["active_jobs"] == 1 and data["kpis"]["flagged_entries"] == 1
    assert data["kpis"]["workers_clocked_in"] == 1
    assert [w["email"] for w in data["unassigned_workers"]] == ["ben@test.com"]
    assert data["date"] == today.isoformat() and len(data["jobs_today"]) == 1
