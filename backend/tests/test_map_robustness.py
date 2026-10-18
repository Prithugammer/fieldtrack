"""D-02: a job site outside the road network must not freeze the Live Map or the safety controls.

Before the fix, `roads.nearest_node` searched outward ring by ring with no limit: a site in Pokhara
(~140 km away) made the first `GET /api/map/live` take ~13.5 s, and (0, 0) effectively never returned.
These tests give every call a hard time limit, so a regression fails instead of hanging the suite.
"""

import math
import threading
import time
from datetime import date
from types import SimpleNamespace

import pytest

import roads
import simulation
from extensions import db
from models import Assignment, Job, JobSite, User

TIME_LIMIT = 3.0  # seconds; the bounded search needs milliseconds, the old code needed 13 s or more

KIRTIPUR = (27.6773, 85.2870)
UNSUPPORTED = {
    "Pokhara (~140 km west)": (28.2096, 83.9856),
    "lat 0 / lng 0": (0.0, 0.0),
    "north pole": (90.0, 0.0),
    "south-east corner": (-90.0, 180.0),
    "far east (~100 km)": (27.7172, 86.5),
    "antipode of the Valley": (-27.7, -94.7),
    "Toronto": (43.6591, -79.3503),
}
INVALID = [
    (float("nan"), 85.3),
    (27.7, float("nan")),
    (float("inf"), 85.3),
    (27.7, float("-inf")),
    (91.0, 85.3),
    (-91.0, 85.3),
    (27.7, 181.0),
    (27.7, -181.0),
    (None, 85.3),
    ("27.7", "85.3"),
]


def within(seconds, fn, *args):
    """Run fn(*args) in a daemon thread; fail (instead of hanging) if it exceeds `seconds`."""
    box = {}

    def run():
        try:
            box["value"] = fn(*args)
        except BaseException as exc:  # noqa: BLE001 - re-raised below in the test thread
            box["error"] = exc

    t = threading.Thread(target=run, daemon=True)
    t0 = time.perf_counter()
    t.start()
    t.join(seconds)
    elapsed = time.perf_counter() - t0
    assert not t.is_alive(), f"{fn.__name__}{args} did not finish within {seconds} s"
    if "error" in box:
        raise box["error"]
    return box["value"], elapsed


# ---- road lookup ------------------------------------------------------------------------------


def test_a_supported_point_snaps_to_a_nearby_road_point():
    node, _ = within(TIME_LIMIT, roads.nearest_node, *KIRTIPUR)
    assert isinstance(node, int)
    lat, lng = roads.snap(*KIRTIPUR)
    assert simulation._dist((lat, lng), KIRTIPUR) < 1_000  # metres


@pytest.mark.parametrize("name", list(UNSUPPORTED))
def test_unsupported_points_have_no_node_and_return_fast(name):
    node, elapsed = within(TIME_LIMIT, roads.nearest_node, *UNSUPPORTED[name])
    assert node is None
    assert elapsed < 0.5, f"{name}: {elapsed:.2f} s"
    assert roads.is_routable(*UNSUPPORTED[name]) is False


@pytest.mark.parametrize("lat,lng", INVALID)
def test_invalid_coordinates_have_no_node_and_do_not_raise(lat, lng):
    node, _ = within(TIME_LIMIT, roads.nearest_node, lat, lng)
    assert node is None


def test_the_search_radius_is_bounded_and_documented():
    assert roads.MAX_SNAP_M == 5_000
    south, north, west, east = roads._coverage()
    assert south < 27.59 and north > 27.83 and west < 85.17 and east > 85.48
    # A point just outside the 5 km margin is rejected, one just inside the network is accepted.
    assert roads.nearest_node(north + 0.001, 85.3) is None
    assert roads.nearest_node(27.70, 85.30) is not None


def test_snap_and_road_path_raise_a_clear_error_instead_of_searching():
    far = UNSUPPORTED["Pokhara (~140 km west)"]
    with pytest.raises(roads.RouteUnavailable):
        within(TIME_LIMIT, roads.snap, *far)
    with pytest.raises(roads.RouteUnavailable):
        within(TIME_LIMIT, roads.road_path, [KIRTIPUR, far])
    assert len(roads.road_path([KIRTIPUR, (27.7215, 85.3620)])) > 2  # a normal route still works


# ---- route building ---------------------------------------------------------------------------

# What the ORIGINAL code (commit 67d9214) produced for these workers on 2026-10-11: which landmarks the
# route starts from / passes, how many road points and pieces it has, base commute minutes, length in metres
# and duration in minutes. Exact float fingerprints (repr hashes) differed between Windows/Linux and Python
# 3.10/3.12/3.13 (last-bit differences in libm), so the check compares this stable summary instead.
GOLDEN_ROUTES = [
    (8, (27.7215, 85.362), ("Kalanki", ("Chabahil",), 131, 183, 27, 11516, 39.3)),
    (5, (27.6775, 85.3485), ("Boudhanath", ("Chabahil",), 85, 123, 29, 7695, 49.3)),
    (12, (27.736, 85.318), ("Koteshwor", ("Chabahil",), 100, 160, 35, 10531, 53.4)),
    (9, (27.673, 85.3246), ("Boudhanath", ("Koteshwor",), 110, 165, 27, 10124, 40.4)),
    (6, (27.671, 85.4298), ("Sankhu", (), 222, 262, 34, 13653, 34.0)),
    (7, (27.6773, 85.287), ("Kathmandu Durbar Square", (), 88, 110, 18, 6368, 18.0)),
]


def route_summary(r):
    return (
        r["start_name"],
        tuple(r["via_names"]),
        len(r["points"]),
        len(r["pieces"]),
        r["base_minutes"],
        round(r["length_m"]),
        round(r["duration_minutes"], 1),
    )


@pytest.mark.parametrize("user_id,site,summary", GOLDEN_ROUTES)
def test_supported_routes_are_unchanged_by_the_fix(user_id, site, summary):
    route, _ = within(10, simulation._build_route, user_id, date(2026, 10, 11), *site)
    assert route_summary(route) == summary


def test_build_route_returns_none_for_unsupported_sites_and_a_route_otherwise():
    day = date(2026, 10, 11)
    for name, site in UNSUPPORTED.items():
        route, elapsed = within(TIME_LIMIT, simulation.build_route, 1, day, *site)
        assert route is None, name
        assert elapsed < 1
    ok, _ = within(10, simulation.build_route, 1, day, *KIRTIPUR)
    assert ok["pieces"] and ok["duration_minutes"] > 0


# ---- the whole map state ----------------------------------------------------------------------


def _site(site_id, name, lat, lng):
    return SimpleNamespace(
        site_id=site_id,
        site_name=name,
        address="x",
        latitude=lat,
        longitude=lng,
        geofence_radius_m=200,
    )


def _assignment(user_id, title, site):
    return SimpleNamespace(
        user_id=user_id, job=SimpleNamespace(title=title, site=site, site_id=site.site_id)
    )


def _worker(user_id, name):
    return SimpleNamespace(user_id=user_id, full_name=name, trade="Carpenter")


def test_live_state_keeps_working_when_one_site_is_unsupported():
    near = _site(1, "Kirtipur", *KIRTIPUR)
    far = _site(2, "Pokhara", *UNSUPPORTED["Pokhara (~140 km west)"])
    zero = _site(3, "Null Island", 0.0, 0.0)
    assignments = [
        _assignment(5, "Near job", near),
        _assignment(6, "Far job", far),
        _assignment(7, "Zero job", zero),
    ]
    workers = [
        _worker(5, "Near Worker"),
        _worker(6, "Far Worker"),
        _worker(7, "Zero Worker"),
        _worker(8, "Idle Worker"),
    ]
    state, elapsed = within(
        10,
        simulation.get_live_map_state,
        [near, far, zero],
        assignments,
        workers,
        date(2026, 10, 11),
        1_000_000.0,
    )
    assert elapsed < 3
    by_name = {w["name"]: w for w in state["workers"]}
    assert by_name["Far Worker"]["status"] == simulation.UNROUTABLE_STATUS
    assert by_name["Far Worker"]["lat"] is None and by_name["Far Worker"]["job_title"] == "Far job"
    assert by_name["Zero Worker"]["status"] == simulation.UNROUTABLE_STATUS
    assert by_name["Near Worker"]["status"] in ("Not started", "In transit", "On site")
    assert by_name["Idle Worker"]["status"] == "Off duty"
    routable = {s["name"]: s["routable"] for s in state["job_sites"]}
    assert routable == {"Kirtipur": True, "Pokhara": False, "Null Island": False}


def test_a_state_with_only_unsupported_sites_is_still_a_valid_state():
    far = _site(2, "Pokhara", *UNSUPPORTED["Pokhara (~140 km west)"])
    state, _ = within(
        5,
        simulation.get_live_map_state,
        [far],
        [_assignment(6, "Far job", far)],
        [_worker(6, "Far Worker")],
        date(2026, 10, 11),
        1_000_000.0,
    )
    assert [w["status"] for w in state["workers"]] == [simulation.UNROUTABLE_STATUS]
    assert state["job_sites"][0]["routable"] is False


# ---- through the API: no HTTP 500, no freeze, safety stays responsive ------------------------------


@pytest.fixture
def far_site_today(app):
    """Today's assignments: one worker at a supported site, one at a site in Pokhara."""
    today = date.today()
    dispatcher = User.query.filter_by(role="Dispatcher").one()
    near = JobSite(
        site_name="Kirtipur test site",
        address="Kirtipur, Kathmandu",
        latitude=KIRTIPUR[0],
        longitude=KIRTIPUR[1],
        geofence_radius_m=200,
    )
    far = JobSite(
        site_name="Pokhara test site",
        address="Pokhara, Gandaki",
        latitude=28.2096,
        longitude=83.9856,
        geofence_radius_m=200,
    )
    db.session.add_all([near, far])
    db.session.flush()
    job_near = Job(
        site=near,
        creator=dispatcher,
        title="Near job",
        scheduled_date=today,
        crew_size=2,
        status="In progress",
    )
    job_far = Job(
        site=far,
        creator=dispatcher,
        title="Far job",
        scheduled_date=today,
        crew_size=2,
        status="In progress",
    )
    db.session.add_all([job_near, job_far])
    db.session.flush()
    w1 = User.query.filter_by(email="marcus@test.com").one()
    w2 = User.query.filter_by(email="ben@test.com").one()
    db.session.add_all(
        [
            Assignment(job=job_near, worker=w1, work_date=today),
            Assignment(job=job_far, worker=w2, work_date=today),
        ]
    )
    db.session.commit()
    return {"near_worker": w1.user_id, "far_worker": w2.user_id, "far_site": far.site_id}


def test_live_map_api_answers_quickly_and_flags_the_unsupported_site(
    client, dispatcher_headers, far_site_today
):
    t0 = time.perf_counter()
    res = client.get("/api/map/live", headers=dispatcher_headers)
    assert time.perf_counter() - t0 < TIME_LIMIT
    assert res.status_code == 200
    body = res.get_json()
    far = next(w for w in body["workers"] if w["id"] == far_site_today["far_worker"])
    assert far["status"] == simulation.UNROUTABLE_STATUS and far["lat"] is None
    assert far["safety"]["state"] == "NORMAL"
    assert {s["name"]: s["routable"] for s in body["job_sites"]}["Pokhara test site"] is False


def test_safety_endpoints_stay_responsive_with_an_unsupported_site(
    client, supervisor_headers, far_site_today
):
    for method, url, body in [
        ("post", "/api/safety/tick", None),
        ("get", "/api/map/live", None),
        ("get", "/api/safety/config", None),
        ("get", "/api/safety/audit", None),
        ("post", f"/api/safety/workers/{far_site_today['near_worker']}/accident", {}),
        ("post", f"/api/safety/workers/{far_site_today['far_worker']}/sos", {}),
        ("post", f"/api/safety/workers/{far_site_today['far_worker']}/break", {"on_break": True}),
        (
            "post",
            f"/api/safety/workers/{far_site_today['far_worker']}/resolve",
            {"outcome": "false_alarm"},
        ),
    ]:
        t0 = time.perf_counter()
        res = getattr(client, method)(url, json=body, headers=supervisor_headers)
        assert time.perf_counter() - t0 < TIME_LIMIT, url
        assert res.status_code < 500, (url, res.status_code, res.get_json())
    # The unrouted worker is not "on shift", so a safety control on them is refused cleanly (409), never a 500.
    res = client.post(
        f"/api/safety/workers/{far_site_today['far_worker']}/sos", headers=supervisor_headers
    )
    assert res.status_code == 409 and "not on shift" in res.get_json()["error"]


def test_moving_a_site_far_away_through_the_api_is_accepted_and_harmless(
    client, dispatcher_headers, supervisor_headers, far_site_today
):
    """The API contract is unchanged (any real coordinates are valid); the map degrades gracefully."""
    for lat, lng in [(0, 0), (28.2096, 83.9856), (-90, 180), (27.7172, 85.3240)]:
        res = client.patch(
            f"/api/sites/{far_site_today['far_site']}",
            json={"latitude": lat, "longitude": lng},
            headers=dispatcher_headers,
        )
        assert res.status_code == 200
        t0 = time.perf_counter()
        live = client.get("/api/map/live", headers=supervisor_headers)
        assert live.status_code == 200 and time.perf_counter() - t0 < TIME_LIMIT, (lat, lng)


@pytest.mark.parametrize("bad", ["nan", "Infinity", 181, -181, "abc", None, ""])
def test_missing_or_nonnumeric_site_coordinates_are_rejected_with_400(
    client, dispatcher_headers, far_site_today, bad
):
    body = {"site_name": "Bad coords", "address": "1 Test Road", "latitude": bad, "longitude": 85.3}
    res = client.post("/api/sites", json=body, headers=dispatcher_headers)
    assert res.status_code == 400 and res.get_json()["field"] == "latitude"
    res = client.patch(
        f"/api/sites/{far_site_today['far_site']}",
        json={"longitude": bad},
        headers=dispatcher_headers,
    )
    assert res.status_code == 400 and res.get_json()["field"] == "longitude"
    assert math.isfinite(db.session.get(JobSite, far_site_today["far_site"]).longitude)
