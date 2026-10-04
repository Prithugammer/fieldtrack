"""Live Map simulation: deterministic, read-only, and always showing movement."""
from datetime import date, timedelta
from types import SimpleNamespace

import simulation as sim
from geofence import haversine
from kathmandu_geo import KATHMANDU_VALLEY_BOUNDS, LANDMARKS, TRAFFIC_HOTSPOTS, random_point_near
from models import LocationPing, TimeEntry

DAY = date(2026, 10, 1)
# Six workers at four sites spread across the valley (like the demo seed).
SITES = [LANDMARKS["Kirtipur"], LANDMARKS["Koteshwor"], LANDMARKS["Boudhanath"], LANDMARKS["Gongabu"]]
CREW = [(uid, SITES[uid % 4]) for uid in range(5, 11)]


def plan(day=DAY, crew=CREW):
    routes = {uid: sim.build_route(uid, day, *site) for uid, site in crew}
    sim.plan_departures(list(routes.values()), day)
    return routes


def positions(routes, minute):
    return [sim.get_worker_position(SimpleNamespace(user_id=u), r, minute) for u, r in routes.items()]


def test_random_point_near_stays_within_offset():
    for _ in range(200):
        lat, lng = random_point_near(27.7, 85.3, 0.5)
        assert haversine(lat, lng, 27.7, 85.3) <= 501


def test_routes_are_deterministic_per_worker_and_day():
    a = sim.build_route(7, DAY, *SITES[0])
    assert a == sim.build_route(7, DAY, *SITES[0])
    assert a["points"] != sim.build_route(7, DAY + timedelta(days=1), *SITES[0])["points"]
    assert 8 <= a["base_minutes"] <= 35
    assert a["points"][-1] == SITES[0]


def test_routes_never_zig_zag():
    # Every whole route stays within MAX_ROUTE_RATIO of the straight line, across many
    # workers, dates and sites (not just one crew), and still uses landmark waypoints.
    sites = [LANDMARKS[n] for n in sorted(LANDMARKS)]
    with_waypoints = 0
    for uid in range(1, 31):
        for k in range(0, 60, 3):
            for site in sites:
                r = sim.build_route(uid, DAY + timedelta(days=k), *site)
                direct = haversine(*r["points"][0], *r["points"][-1])
                assert r["length_m"] <= sim.MAX_ROUTE_RATIO * direct + 1, (uid, k, r["via_names"])
                with_waypoints += bool(r["via_names"])
    assert with_waypoints > 0.5 * 30 * 20 * len(sites)


def test_always_someone_moving_and_someone_on_site():
    for k in range(30):
        routes = plan(DAY + timedelta(days=k))
        minute = sim.SIM_DAY_START
        while minute < sim.SIM_DAY_END:
            statuses = {p["status"] for p in positions(routes, minute)}
            assert "In transit" in statuses and "On site" in statuses, (k, minute)
            minute += 1


def test_positions_stay_in_the_valley_and_finish_at_the_site():
    routes = plan()
    b = KATHMANDU_VALLEY_BOUNDS
    for minute in range(sim.SIM_DAY_START - 60, sim.SIM_DAY_END + 60):
        for p in positions(routes, minute):
            if p["lat"] is not None:
                assert b["south"] <= p["lat"] <= b["north"] and b["west"] <= p["lng"] <= b["east"]
    for uid, site in CREW:
        done = sim.get_worker_position(SimpleNamespace(user_id=uid), routes[uid], 24 * 60)
        assert done["status"] == "On site" and haversine(done["lat"], done["lng"], *site) <= 31


def test_traffic_hotspot_slows_the_worker_down():
    # A route that crosses a hotspot takes longer than its free-flow time, and a worker
    # inside the hotspot is reported as near_traffic with the junction's name.
    routes = [r for r in plan().values() if any(pc["hotspot"] for pc in r["pieces"])]
    assert routes
    r = routes[0]
    assert r["duration_minutes"] > r["base_minutes"]
    t, flagged = r["departure"], None
    while t < r["departure"] + r["duration_minutes"] and not flagged:
        p = sim.get_worker_position(SimpleNamespace(user_id=r["user_id"]), r, t)
        flagged = p if p["near_traffic"] else None
        t += 0.25
    assert flagged and flagged["hotspot"] in TRAFFIC_HOTSPOTS


def test_sim_clock_loops_through_the_window():
    assert sim.sim_clock(0)[0] == sim.SIM_DAY_START
    mid, cycle = sim.sim_clock(sim.CYCLE_SECONDS * 7 + sim.CYCLE_SECONDS / 2)
    assert cycle == 7 and mid == (sim.SIM_DAY_START + sim.SIM_DAY_END) / 2
    assert sim.format_clock(6 * 60 + 5) == "6:05 AM" and sim.format_clock(13 * 60) == "1:00 PM"
    assert sim.seconds_to_reset(sim.CYCLE_SECONDS * 3) == sim.CYCLE_SECONDS
    assert sim.seconds_to_reset(sim.CYCLE_SECONDS * 3 + 60) == sim.CYCLE_SECONDS - 60


def test_live_map_endpoint_is_read_only(client, dispatcher_headers):
    before = (TimeEntry.query.count(), LocationPing.query.count())
    res = client.get("/api/map/live", headers=dispatcher_headers)
    assert res.status_code == 200
    data = res.get_json()
    assert data["job_sites"] and {"id", "name", "lat", "lng", "radius_m"} <= set(data["job_sites"][0])
    assert {"id", "name", "trade", "lat", "lng", "status", "job_title", "near_traffic"} <= set(data["workers"][0])
    assert (TimeEntry.query.count(), LocationPing.query.count()) == before
    for path in ("/api/map/sim-clock", "/api/map/bounds"):
        assert client.get(path, headers=dispatcher_headers).status_code == 200
    assert client.get("/api/map/live").status_code == 401
