"""Jobs and sites: create, read, update, filter, role limits and the rules that protect crews."""

from datetime import timedelta

import pytest

from extensions import db
from models import Assignment, Job, JobSite, User
from tests.conftest import DAY


def site_id():
    return JobSite.query.order_by(JobSite.site_id).first().site_id


def job_body(**changes):
    body = {
        "site_id": site_id(),
        "title": "Slab pour",
        "description": "Pour level 2",
        "scheduled_date": str(DAY),
        "crew_size": 3,
    }
    body.update(changes)
    return body


# ---- create --------------------------------------------------------------------------------------


def test_dispatcher_creates_a_job_and_created_by_comes_from_the_token(
    client, dispatcher_headers, ids
):
    res = client.post("/api/jobs", json=job_body(created_by=ids["ben"]), headers=dispatcher_headers)
    assert res.status_code == 201
    job = db.session.get(Job, res.get_json()["job"]["job_id"])
    assert job.status == "Scheduled"
    assert job.creator.email == "dispatch@test.com"  # a client-supplied created_by is ignored


def test_admin_may_create_jobs_but_a_supervisor_may_not(client, admin_headers, supervisor_headers):
    assert client.post("/api/jobs", json=job_body(), headers=admin_headers).status_code == 201
    before = Job.query.count()
    assert client.post("/api/jobs", json=job_body(), headers=supervisor_headers).status_code == 403
    assert Job.query.count() == before


def test_create_needs_an_existing_site(client, dispatcher_headers):
    res = client.post("/api/jobs", json=job_body(site_id=987654), headers=dispatcher_headers)
    assert res.status_code == 404 and res.get_json()["field"] == "site_id"


@pytest.mark.parametrize(
    "changes,field",
    [
        ({"title": "ab"}, "title"),
        ({"title": None}, "title"),
        ({"title": "x" * 121}, "title"),
        ({"description": "x" * 1001}, "description"),
        ({"scheduled_date": "tomorrow"}, "scheduled_date"),
        ({"scheduled_date": None}, "scheduled_date"),
        ({"crew_size": 0}, "crew_size"),
        ({"crew_size": 51}, "crew_size"),
        ({"crew_size": "many"}, "crew_size"),
        ({"status": "Done"}, "status"),
        ({"site_id": None}, "site_id"),
    ],
)
def test_invalid_job_fields_are_rejected(client, dispatcher_headers, changes, field):
    before = Job.query.count()
    res = client.post("/api/jobs", json=job_body(**changes), headers=dispatcher_headers)
    assert res.status_code == 400 and res.get_json()["field"] == field
    assert Job.query.count() == before


def test_a_job_may_be_created_with_an_explicit_status_and_no_description(
    client, dispatcher_headers
):
    body = job_body(status="In progress")
    body.pop("description")
    res = client.post("/api/jobs", json=body, headers=dispatcher_headers)
    job = res.get_json()["job"]
    assert res.status_code == 201 and job["status"] == "In progress"


# ---- read and filter -----------------------------------------------------------------------------


def test_get_one_job_includes_its_crew(client, dispatcher_headers, ids):
    job = client.get(f"/api/jobs/{ids['job_a']}", headers=dispatcher_headers).get_json()["job"]
    assert job["title"] == "Level 4 framing" and len(job["crew"]) == 1


def test_missing_job_is_404_with_the_standard_body(client, dispatcher_headers):
    res = client.get("/api/jobs/424242", headers=dispatcher_headers)
    assert res.status_code == 404 and res.get_json() == {
        "error": "Job #424242 was not found.",
        "field": None,
    }


def test_list_filters_by_date_status_and_site(client, dispatcher_headers, ids):
    other = Job.query.filter_by(job_id=ids["job_b"]).one()
    other.status = "Completed"
    other.scheduled_date = DAY + timedelta(days=1)
    db.session.commit()

    def titles(query):
        res = client.get(f"/api/jobs?{query}", headers=dispatcher_headers)
        assert res.status_code == 200
        return [j["title"] for j in res.get_json()["jobs"]]

    assert len(titles("")) == 2
    assert titles(f"date={DAY}") == ["Level 4 framing"]
    assert titles("status=Completed") == ["Deck pour - Span 2"]
    assert titles(f"site_id={other.site_id}") == ["Deck pour - Span 2"]
    assert titles(f"date={DAY}&status=Completed") == []
    for bad in ("date=nope", "status=Done", "site_id=abc"):
        assert client.get(f"/api/jobs?{bad}", headers=dispatcher_headers).status_code == 400


def test_jobs_are_listed_newest_date_first(client, dispatcher_headers, ids):
    job = db.session.get(Job, ids["job_b"])
    job.scheduled_date = DAY + timedelta(days=5)
    db.session.commit()
    dates = [
        j["scheduled_date"]
        for j in client.get("/api/jobs", headers=dispatcher_headers).get_json()["jobs"]
    ]
    assert dates == sorted(dates, reverse=True)


# ---- update --------------------------------------------------------------------------------------


def test_update_edits_only_the_fields_sent(client, dispatcher_headers, ids):
    res = client.patch(
        f"/api/jobs/{ids['job_a']}",
        json={"title": "Level 5 framing", "status": "In progress", "description": ""},
        headers=dispatcher_headers,
    )
    job = res.get_json()["job"]
    assert res.status_code == 200 and job["title"] == "Level 5 framing"
    assert job["status"] == "In progress" and job["crew_size"] == 3 and job["description"] is None


def test_update_can_move_a_job_to_another_site(client, dispatcher_headers, ids):
    other = JobSite.query.filter(JobSite.site_id != site_id()).first()
    res = client.patch(
        f"/api/jobs/{ids['job_a']}", json={"site_id": other.site_id}, headers=dispatcher_headers
    )
    assert res.status_code == 200 and res.get_json()["job"]["site_id"] == other.site_id
    missing = client.patch(
        f"/api/jobs/{ids['job_a']}", json={"site_id": 777777}, headers=dispatcher_headers
    )
    assert missing.status_code == 404


def test_update_is_limited_to_dispatchers_and_admins(client, supervisor_headers, ids):
    res = client.patch(
        f"/api/jobs/{ids['job_a']}", json={"title": "Hijacked"}, headers=supervisor_headers
    )
    assert res.status_code == 403
    assert db.session.get(Job, ids["job_a"]).title == "Level 4 framing"


def test_update_of_a_missing_job_is_404(client, dispatcher_headers):
    assert client.patch("/api/jobs/55555", json={}, headers=dispatcher_headers).status_code == 404


def test_the_date_cannot_move_while_workers_are_assigned(client, dispatcher_headers, ids):
    new_day = str(DAY + timedelta(days=2))
    res = client.patch(
        f"/api/jobs/{ids['job_a']}", json={"scheduled_date": new_day}, headers=dispatcher_headers
    )
    assert res.status_code == 409 and res.get_json()["field"] == "scheduled_date"
    same = client.patch(
        f"/api/jobs/{ids['job_a']}", json={"scheduled_date": str(DAY)}, headers=dispatcher_headers
    )
    assert same.status_code == 200  # "moving" to the same day is fine
    free = client.patch(
        f"/api/jobs/{ids['job_b']}", json={"scheduled_date": new_day}, headers=dispatcher_headers
    )
    assert free.status_code == 200 and free.get_json()["job"]["scheduled_date"] == new_day


def test_crew_size_cannot_drop_below_the_workers_already_assigned(client, dispatcher_headers, ids):
    db.session.add(Assignment(job_id=ids["job_a"], user_id=ids["ben"], work_date=DAY))
    db.session.commit()
    low = client.patch(
        f"/api/jobs/{ids['job_a']}", json={"crew_size": 1}, headers=dispatcher_headers
    )
    assert low.status_code == 400 and low.get_json()["field"] == "crew_size"
    assert db.session.get(Job, ids["job_a"]).crew_size == 3
    ok = client.patch(
        f"/api/jobs/{ids['job_a']}", json={"crew_size": 2}, headers=dispatcher_headers
    )
    assert ok.status_code == 200


@pytest.mark.parametrize(
    "changes,field",
    [
        ({"title": "ab"}, "title"),
        ({"scheduled_date": "x"}, "scheduled_date"),
        ({"crew_size": 0}, "crew_size"),
        ({"status": "Done"}, "status"),
        ({"description": "x" * 1001}, "description"),
    ],
)
def test_invalid_job_updates_are_400_and_change_nothing(
    client, dispatcher_headers, ids, changes, field
):
    res = client.patch(f"/api/jobs/{ids['job_a']}", json=changes, headers=dispatcher_headers)
    assert res.status_code == 400 and res.get_json()["field"] == field
    db.session.expire_all()
    job = db.session.get(Job, ids["job_a"])
    assert (job.title, job.crew_size, job.status) == ("Level 4 framing", 3, "Scheduled")


def test_there_is_no_delete_route_for_jobs(client, admin_headers, ids):
    assert client.delete(f"/api/jobs/{ids['job_a']}", headers=admin_headers).status_code == 405
    assert db.session.get(Job, ids["job_a"]) is not None


# ---- sites ---------------------------------------------------------------------------------------


def site_body(**changes):
    body = {
        "site_name": "New Depot",
        "address": "12 Ring Road, Kathmandu",
        "latitude": 27.7,
        "longitude": 85.3,
        "geofence_radius_m": 300,
    }
    body.update(changes)
    return body


def test_site_creation_defaults_the_radius_and_lists_alphabetically(
    client, dispatcher_headers, supervisor_headers
):
    body = site_body(site_name="Aardvark Yard")
    body.pop("geofence_radius_m")
    res = client.post("/api/sites", json=body, headers=dispatcher_headers)
    assert res.status_code == 201 and res.get_json()["site"]["geofence_radius_m"] == 200
    names = [
        s["site_name"]
        for s in client.get("/api/sites", headers=supervisor_headers).get_json()["sites"]
    ]
    assert names == sorted(names) and names[0] == "Aardvark Yard"


def test_supervisors_cannot_edit_sites(client, supervisor_headers):
    assert (
        client.post("/api/sites", json=site_body(), headers=supervisor_headers).status_code == 403
    )
    assert client.patch("/api/sites/1", json={}, headers=supervisor_headers).status_code == 403


def test_site_update_changes_fields_and_validates_each(client, dispatcher_headers):
    sid = site_id()
    res = client.patch(
        f"/api/sites/{sid}",
        json={
            "site_name": "Renamed Site",
            "address": "99 New Address",
            "latitude": 27.71,
            "longitude": 85.31,
            "geofence_radius_m": 450,
        },
        headers=dispatcher_headers,
    )
    site = res.get_json()["site"]
    assert res.status_code == 200 and (site["site_name"], site["geofence_radius_m"]) == (
        "Renamed Site",
        450,
    )
    for changes, field in (
        ({"site_name": "x"}, "site_name"),
        ({"address": "abc"}, "address"),
        ({"latitude": 100}, "latitude"),
        ({"longitude": -200}, "longitude"),
    ):
        bad = client.patch(f"/api/sites/{sid}", json=changes, headers=dispatcher_headers)
        assert bad.status_code == 400 and bad.get_json()["field"] == field
    assert client.patch("/api/sites/31337", json={}, headers=dispatcher_headers).status_code == 404


def test_site_creation_validates_text_fields(client, dispatcher_headers):
    for changes, field in (
        ({"site_name": ""}, "site_name"),
        ({"address": "abc"}, "address"),
        ({"site_name": "x" * 121}, "site_name"),
    ):
        res = client.post("/api/sites", json=site_body(**changes), headers=dispatcher_headers)
        assert res.status_code == 400 and res.get_json()["field"] == field


def test_inactive_workers_are_not_part_of_the_job_fixture_rules(client, dispatcher_headers, ids):
    """Deactivating a user does not rewrite history: their assignments stay on the job."""
    User.query.filter_by(user_id=ids["marcus"]).one().is_active = False
    db.session.commit()
    job = client.get(f"/api/jobs/{ids['job_a']}", headers=dispatcher_headers).get_json()["job"]
    assert len(job["crew"]) == 1
