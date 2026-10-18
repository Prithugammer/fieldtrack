"""Simulated worker GPS for the Live Map.

There is no mobile app, so worker positions are SIMULATED. Everything here is a pure
calculation from the wall clock: no database writes, no threads, no scheduler. Each call
answers "where would this worker be right now?".

How it works:
  * Every worker assigned to a job today gets a route, generated from a random seed made
    of their user_id and today's date, so it is identical on every request. The route runs
    from a landmark a few km away, through up to 2 landmark waypoints, to their job site,
    and follows the real road network (roads.py) the whole way, ending with a short walk
    from the nearest road onto the site.
  * Real time loops through a simulated morning dispatch window (SIM_DAY_START to
    SIM_DAY_END) every CYCLE_SECONDS. Departure times are picked at random (seeded by the
    date) so that throughout the window nearly every assigned worker is visibly working,
    on the road or on site, while someone is always moving and someone is always on site;
    the rest set off at random moments during the window.
    (A full 6 am-6 pm day with one commute each would leave the map frozen most of the time.)
  * Near a traffic hotspot a worker moves at the hotspot's speed_multiplier, so markers
    visibly bunch up at busy junctions.
  * Workers with no assignment today are "Off duty" and shown greyed out at a fixed point
    near a landmark (their home area). They never move.
"""

import math
import random
import time
from functools import lru_cache
from itertools import combinations

from geofence import haversine
from kathmandu_geo import LANDMARKS, TRAFFIC_HOTSPOTS, random_point_near
from roads import RouteUnavailable, is_routable, road_path, snap

CYCLE_SECONDS = 300  # one simulated window every 5 real minutes
SIM_DAY_START = 6 * 60  # 6:00 AM, in minutes after midnight
SIM_DAY_END = 6 * 60 + 45  # 6:45 AM (short enough that almost everyone is always working)
PIECE_M = 100  # routes are split into pieces this long for the traffic check
UNROUTABLE_STATUS = "Route unavailable"  # worker assigned to a site outside the road network

START_MIN_KM, START_MAX_KM = 2.5, 10.0
MAX_ROUTE_RATIO = 1.3  # waypoints may stretch the line from start to site by at most 30%
MAX_DETOUR = 1.3  # ...and the drive through them by at most 30% over the shortest drive
PLAN_TRIES = 300  # random departure plans tried per day; the best one is kept
WORKING_TARGET = 5  # aim for about this many workers visibly working at every moment
EARLIEST_DEPARTURE = 60  # minutes before the window opens that a commute may start
LATEST_DEPARTURE = 25  # ...and minutes before it closes that the last one may start


def _dist(a, b):
    return haversine(a[0], a[1], b[0], b[1])


def _lerp(a, b, f):
    return (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f)


def _hotspot_at(point):
    """Name of the traffic hotspot covering this point, or None."""
    for name, spot in TRAFFIC_HOTSPOTS.items():
        if _dist(point, LANDMARKS[name]) <= spot["radius_m"]:
            return name
    return None


def _length(points):
    return sum(_dist(a, b) for a, b in zip(points, points[1:]))


@lru_cache(maxsize=512)
def _road_route(user_id, day, site_lat, site_lng):
    try:
        return _build_route(user_id, day, site_lat, site_lng)
    except RouteUnavailable:
        return None  # cached too, so an unsupported site costs one cheap check per request


def build_route(user_id, day, site_lat, site_lng):
    """Deterministic commute for one worker on one day (same inputs -> same route).

    Cached, since road routing is the expensive part and the map polls every second; callers
    get their own copy because plan_departures() writes into it. Returns None when the site is
    outside the road network's coverage (no route can be drawn there).
    """
    route = _road_route(user_id, day, site_lat, site_lng)
    return None if route is None else dict(route)


def _pick_start(rng, end):
    """Where the commute begins: a landmark the right distance from the site, nudged off-centre.

    Returns (landmark name, start point snapped to the road network).
    """
    names = sorted(LANDMARKS)
    starts = [
        n for n in names if START_MIN_KM * 1000 <= _dist(LANDMARKS[n], end) <= START_MAX_KM * 1000
    ]
    start_name = rng.choice(starts or names)
    start = snap(*random_point_near(*LANDMARKS[start_name], 0.4, rng))  # set off from a road
    return start_name, start


def _candidate_waypoints(start_name, start, end):
    """Landmarks worth driving through, best first (busy junctions before quiet ones).

    A waypoint must be clear of both ends and must not make the trip much longer than direct.
    """
    direct = _dist(start, end)

    def detour(n):
        p = LANDMARKS[n]
        return (_dist(start, p) + _dist(p, end)) / direct

    vias = [
        n
        for n in sorted(LANDMARKS)
        if n != start_name
        and _dist(LANDMARKS[n], end) > 600
        and _dist(LANDMARKS[n], start) > 600
        and detour(n) <= MAX_ROUTE_RATIO
    ]
    # Main roads run through the busy junctions, so prefer those as waypoints.
    vias.sort(key=lambda n: (n not in TRAFFIC_HOTSPOTS, detour(n)))
    return vias


def _choose_waypoints(start, end, vias, spots, want):
    """The first waypoint combination whose WHOLE route stays within MAX_ROUTE_RATIO.

    Each waypoint can pass on its own and still zig-zag together with another, so judge the
    route as a whole: try `want` waypoints (in preference order), then fewer. Returns
    (chosen landmark names, route points); no waypoints and a straight line if none fits.
    """
    direct = _dist(start, end)
    for size in [2, 1] if want == 2 else [1]:
        for combo in combinations(vias, size):
            ordered = sorted(combo, key=lambda n: _dist(start, LANDMARKS[n]))
            candidate = [start] + [spots[n] for n in ordered] + [end]
            if _length(candidate) <= MAX_ROUTE_RATIO * direct:
                return ordered, candidate
    return [], [start, end]


def _split_into_pieces(points, base_minutes):
    """Cut the route into short pieces and time each; a piece in a traffic hotspot is slowed.

    Returns (pieces, total length in metres).
    """
    pieces = []
    for seg, (a, b) in enumerate(zip(points, points[1:])):
        n = max(1, math.ceil(_dist(a, b) / PIECE_M))
        for i in range(n):
            p, q = _lerp(a, b, i / n), _lerp(a, b, (i + 1) / n)
            pieces.append(
                {
                    "a": p,
                    "b": q,
                    "seg": seg,  # which stretch of `points` this piece lies on
                    "length_m": _dist(p, q),
                    "hotspot": _hotspot_at(_lerp(p, q, 0.5)),
                }
            )
    total_m = sum(pc["length_m"] for pc in pieces) or 1.0
    for pc in pieces:
        minutes = base_minutes * pc["length_m"] / total_m
        if pc["hotspot"]:
            minutes /= TRAFFIC_HOTSPOTS[pc["hotspot"]]["speed_multiplier"]
        pc["minutes"] = minutes
    return pieces, total_m


def _build_route(user_id, day, site_lat, site_lng):
    # The order of the random draws below is part of the contract: it makes a worker's route on
    # a given day identical on every run, so do not reorder them.
    rng = random.Random(f"route:{user_id}:{day.isoformat()}")
    end = (site_lat, site_lng)

    start_name, start = _pick_start(rng, end)
    vias = _candidate_waypoints(start_name, start, end)
    want = rng.randint(1, 2)
    spots = {n: random_point_near(*LANDMARKS[n], 0.08, rng) for n in vias}
    chosen, points = _choose_waypoints(start, end, vias, spots, want)

    # Drive along the roads. If the waypoints make the drive much longer than the shortest
    # one (two landmarks can be close as the crow flies but far apart by road), go direct.
    road = road_path(points)
    direct_road = road_path([start, end])
    if chosen and _length(road) > MAX_DETOUR * _length(direct_road):
        chosen, road = [], direct_road
    points = road + [end]  # ...then walk from the nearest road onto the site

    # Commute time without traffic: distance at this worker's usual speed through the valley,
    # kept within 8-35 minutes.
    length_km = _length(points) / 1000
    base_minutes = min(35, max(8, round(length_km / rng.uniform(15, 28) * 60)))

    pieces, total_m = _split_into_pieces(points, base_minutes)
    return {
        "user_id": user_id,
        "start_name": start_name,
        "via_names": chosen,
        "points": points,  # road points from start to the nearest road, then the site
        "pieces": pieces,
        "length_m": total_m,
        "base_minutes": base_minutes,
        "duration_minutes": sum(pc["minutes"] for pc in pieces),  # including traffic delays
        "departure": None,  # set by plan_departures()
        "site_spot": random_point_near(site_lat, site_lng, 0.03, rng),  # where they stand on site
    }


def _working_counts(deps, durations, minute):
    """(working, moving, on site) at `minute` for these departure times and trip lengths."""
    working = moving = 0
    for dep, dur in zip(deps, durations):
        if dep <= minute:
            working += 1
            moving += minute < dep + dur
    return working, moving, working - moving


@lru_cache(maxsize=64)
def _best_departures(day, durations):
    """The best of PLAN_TRIES random departure plans for these trip lengths (seeded by day).

    A plan is judged minute by minute over the window, in order:
      1. minutes with nobody moving or nobody on site (fewest wins);
      2. the fewest workers visibly working at any moment, up to WORKING_TARGET (most wins);
      3. workers who set off during the window, so someone appears on the map mid-cycle
         (up to however many are left over above WORKING_TARGET);
      4. total time spent moving (most wins, so the map stays busy).
    """
    rng = random.Random(f"plan:{day.isoformat()}")
    minutes = range(SIM_DAY_START, SIM_DAY_END)
    best_score, best = None, None
    for _ in range(PLAN_TRIES):
        deps = tuple(
            rng.uniform(SIM_DAY_START - EARLIEST_DEPARTURE, SIM_DAY_END - LATEST_DEPARTURE)
            for _ in durations
        )
        counts = [_working_counts(deps, durations, m) for m in minutes]
        late = sum(1 for dep in deps if dep > SIM_DAY_START)
        score = (
            -sum(1 for _, moving, on_site in counts if not moving or not on_site),
            min(WORKING_TARGET, min(working for working, _, _ in counts)),
            min(late, max(0, len(durations) - WORKING_TARGET)),
            sum(moving for _, moving, _ in counts),
        )
        if best_score is None or score > best_score:
            best_score, best = score, deps
    return best


def plan_departures(routes, day):
    """Give every route a departure time so the map is always busy.

    Most workers have already left (some arrived) when the window opens, and the rest set
    off at random moments during it, so nearly everyone assigned is visibly working at any
    time while someone is always on the road and someone always on site.
    """
    order = sorted(routes, key=lambda r: r["user_id"])
    if not order:
        return order
    durations = tuple(round(r["duration_minutes"], 3) for r in order)
    for route, dep in zip(order, _best_departures(day, durations)):
        route["departure"] = dep
    return order


def sim_clock(now=None):
    """Map wall-clock time onto the repeating simulated window.

    Returns (simulated minutes after midnight, cycle number).
    """
    now = time.time() if now is None else now
    cycle, into = divmod(now, CYCLE_SECONDS)
    minutes = SIM_DAY_START + (SIM_DAY_END - SIM_DAY_START) * into / CYCLE_SECONDS
    return minutes, int(cycle)


def seconds_to_reset(now=None):
    """Real seconds until the simulated window restarts at SIM_DAY_START."""
    now = time.time() if now is None else now
    return CYCLE_SECONDS - now % CYCLE_SECONDS


def format_clock(minutes):
    h, m = divmod(int(minutes), 60)
    return f"{(h - 1) % 12 + 1}:{m:02d} {'AM' if h < 12 else 'PM'}"


def get_worker_position(worker, route, sim_clock_minutes, with_path=False):
    """Where `worker` is at `sim_clock_minutes` on their `route`.

    Returns a dict with status "Not started" (no position), "In transit" or "On site".
    With `with_path`, an in-transit worker also gets "path": the rest of their route from
    where they are now to the site, as [[lat, lng], ...], for drawing the line they will follow.
    """
    base = {
        "user_id": worker.user_id,
        "near_traffic": False,
        "hotspot": None,
        "distance_remaining_m": None,
    }
    elapsed = sim_clock_minutes - route["departure"]
    if elapsed < 0:
        return {**base, "status": "Not started", "lat": None, "lng": None}
    if elapsed >= route["duration_minutes"]:
        lat, lng = route["site_spot"]
        return {**base, "status": "On site", "lat": lat, "lng": lng, "distance_remaining_m": 0}

    # Walk the pieces until the elapsed time runs out, then interpolate inside that piece.
    travelled = 0.0
    for i, pc in enumerate(route["pieces"]):
        if elapsed <= pc["minutes"] or i == len(route["pieces"]) - 1:
            f = min(1.0, elapsed / pc["minutes"]) if pc["minutes"] else 1.0
            lat, lng = _lerp(pc["a"], pc["b"], f)
            remaining = route["length_m"] - travelled - pc["length_m"] * f
            path = {}
            if with_path:
                ahead = [(lat, lng)] + route["points"][pc["seg"] + 1 :]
                path = {"path": [[round(a, 5), round(b, 5)] for a, b in ahead]}
            return {
                **base,
                "status": "In transit",
                "lat": round(lat, 6),
                "lng": round(lng, 6),
                "near_traffic": pc["hotspot"] is not None,
                "hotspot": pc["hotspot"],
                "distance_remaining_m": round(max(0.0, remaining)),
                **path,
            }
        elapsed -= pc["minutes"]
        travelled += pc["length_m"]


def off_duty_spot(user_id, day):
    """A fixed, deterministic point near a landmark for a worker who isn't working today."""
    rng = random.Random(f"home:{user_id}:{day.isoformat()}")
    return random_point_near(*LANDMARKS[rng.choice(sorted(LANDMARKS))], 0.5, rng)


def get_live_map_state(sites, assignments, workers, day, now=None, path_for=None):
    """Compute the whole map from plain inputs (no queries, no writes).

    sites:        JobSite rows
    assignments:  today's Assignment rows (with .job and .job.site)
    workers:      active Worker rows
    path_for:     user_id of a worker whose remaining route to include (the one selected on
                  the map), so the route is only sent while someone is looking at it
    """
    minutes, cycle = sim_clock(now)
    by_user = {a.user_id: a for a in assignments}
    routes = {}
    unroutable = set()  # workers whose site is outside the road network: shown, but not simulated
    for a in assignments:
        route = build_route(a.user_id, day, a.job.site.latitude, a.job.site.longitude)
        if route is None:
            unroutable.add(a.user_id)
        else:
            routes[a.user_id] = route
    plan_departures(list(routes.values()), day)

    out = []
    for w in workers:
        info = {"id": w.user_id, "name": w.full_name, "trade": w.trade}
        a = by_user.get(w.user_id)
        if a is None:
            lat, lng = off_duty_spot(w.user_id, day)
            out.append(
                {
                    **info,
                    "status": "Off duty",
                    "lat": lat,
                    "lng": lng,
                    "job_title": None,
                    "site_name": None,
                    "near_traffic": False,
                    "hotspot": None,
                    "distance_remaining_m": None,
                }
            )
            continue
        if w.user_id in unroutable:
            out.append(
                {
                    **info,
                    "status": UNROUTABLE_STATUS,
                    "lat": None,
                    "lng": None,
                    "job_title": a.job.title,
                    "site_name": a.job.site.site_name,
                    "near_traffic": False,
                    "hotspot": None,
                    "distance_remaining_m": None,
                }
            )
            continue
        pos = get_worker_position(w, routes[w.user_id], minutes, with_path=w.user_id == path_for)
        pos.pop("user_id")
        out.append({**info, **pos, "job_title": a.job.title, "site_name": a.job.site.site_name})

    jobs_by_site = {}
    for a in assignments:
        jobs_by_site.setdefault(a.job.site_id, set()).add(a.job.title)
    return {
        "sim_time": format_clock(minutes),
        "cycle": cycle,
        "job_sites": [
            {
                "id": s.site_id,
                "name": s.site_name,
                "address": s.address,
                "lat": s.latitude,
                "lng": s.longitude,
                "radius_m": s.geofence_radius_m,
                "jobs_today": sorted(jobs_by_site.get(s.site_id, ())),
                # False = outside the supported road network: its workers get no simulated route
                "routable": is_routable(s.latitude, s.longitude),
            }
            for s in sites
        ],
        "workers": out,
    }
