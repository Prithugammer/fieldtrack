"""Simulated worker GPS for the Live Map.

There is no mobile app, so worker positions are SIMULATED. Everything here is a pure
calculation from the wall clock: no database writes, no threads, no scheduler. Each call
answers "where would this worker be right now?".

How it works:
  * Every worker assigned to a job today gets a route, generated from a random seed made
    of their user_id and today's date, so it is identical on every request. The route runs
    from a landmark a few km away, through up to 2 landmark waypoints, to their job site.
  * Real time loops through a simulated morning dispatch window (SIM_DAY_START to
    SIM_DAY_END) every CYCLE_SECONDS. Departures are staggered so commutes overlap: at any
    moment of the window some workers are on the road and some have already arrived.
    (A full 6 am-6 pm day with one commute each would leave the map frozen most of the time.)
  * Near a traffic hotspot a worker moves at the hotspot's speed_multiplier, so markers
    visibly bunch up at busy junctions.
  * Workers with no assignment today are "Off duty" and shown greyed out at a fixed point
    near a landmark (their home area). They never move.
"""
import math
import random
import time
from itertools import combinations

from geofence import haversine
from kathmandu_geo import LANDMARKS, TRAFFIC_HOTSPOTS, random_point_near

CYCLE_SECONDS = 300           # one simulated window every 5 real minutes
SIM_DAY_START = 6 * 60        # 6:00 AM, in minutes after midnight
SIM_DAY_END = 7 * 60 + 15     # 7:15 AM (the morning commute; sized so someone is always moving)
PIECE_M = 100                 # routes are split into pieces this long for the traffic check

START_MIN_KM, START_MAX_KM = 2.5, 10.0
MAX_ROUTE_RATIO = 1.3         # a whole route may be at most 30% longer than the straight line


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


def build_route(user_id, day, site_lat, site_lng):
    """Deterministic commute for one worker on one day (same inputs -> same route)."""
    rng = random.Random(f"route:{user_id}:{day.isoformat()}")
    end = (site_lat, site_lng)

    names = sorted(LANDMARKS)
    starts = [n for n in names if START_MIN_KM * 1000 <= _dist(LANDMARKS[n], end) <= START_MAX_KM * 1000]
    start_name = rng.choice(starts or names)
    start = random_point_near(*LANDMARKS[start_name], 0.4, rng)
    direct = _dist(start, end)

    def detour(n):
        p = LANDMARKS[n]
        return (_dist(start, p) + _dist(p, end)) / direct

    vias = [
        n for n in names
        if n != start_name
        and _dist(LANDMARKS[n], end) > 600 and _dist(LANDMARKS[n], start) > 600
        and detour(n) <= MAX_ROUTE_RATIO
    ]
    # Main roads run through the busy junctions, so prefer those as waypoints.
    vias.sort(key=lambda n: (n not in TRAFFIC_HOTSPOTS, detour(n)))
    want = rng.randint(1, 2)
    spots = {n: random_point_near(*LANDMARKS[n], 0.08, rng) for n in vias}

    # Each waypoint can pass on its own and still zig-zag together with another, so judge the
    # whole route: take the first combination (in preference order, trying fewer waypoints if
    # needed) whose total length stays within MAX_ROUTE_RATIO of the straight line.
    chosen, points = [], [start, end]
    for size in ([2, 1] if want == 2 else [1]):
        for combo in combinations(vias, size):
            ordered = sorted(combo, key=lambda n: _dist(start, LANDMARKS[n]))
            candidate = [start] + [spots[n] for n in ordered] + [end]
            length = sum(_dist(a, b) for a, b in zip(candidate, candidate[1:]))
            if length <= MAX_ROUTE_RATIO * direct:
                chosen, points = ordered, candidate
                break
        if chosen:
            break

    # Commute time without traffic: distance at this worker's usual speed through the valley,
    # kept within 8-35 minutes.
    length_km = sum(_dist(a, b) for a, b in zip(points, points[1:])) / 1000
    base_minutes = min(35, max(8, round(length_km / rng.uniform(15, 28) * 60)))

    # Split into short pieces; a piece whose midpoint is in a hotspot is slowed down.
    pieces = []
    for a, b in zip(points, points[1:]):
        n = max(1, math.ceil(_dist(a, b) / PIECE_M))
        for i in range(n):
            p, q = _lerp(a, b, i / n), _lerp(a, b, (i + 1) / n)
            pieces.append({"a": p, "b": q, "length_m": _dist(p, q), "hotspot": _hotspot_at(_lerp(p, q, 0.5))})
    total_m = sum(pc["length_m"] for pc in pieces) or 1.0
    for pc in pieces:
        minutes = base_minutes * pc["length_m"] / total_m
        if pc["hotspot"]:
            minutes /= TRAFFIC_HOTSPOTS[pc["hotspot"]]["speed_multiplier"]
        pc["minutes"] = minutes

    return {
        "user_id": user_id,
        "start_name": start_name,
        "via_names": chosen,
        "points": points,
        "pieces": pieces,
        "length_m": total_m,
        "base_minutes": base_minutes,
        "duration_minutes": sum(pc["minutes"] for pc in pieces),  # including traffic delays
        "departure": None,                                       # set by plan_departures()
        "site_spot": random_point_near(site_lat, site_lng, 0.03, rng),  # where they stand on site
    }


def plan_departures(routes, day):
    """Stagger departures so commutes overlap across the whole simulated window.

    The first worker (in a per-day shuffled order) arrives just before window start, the
    second is part-way there, and each later worker leaves before the previous one
    arrives, with the overlap sized so the last arrival lands at the end of the window.
    """
    order = sorted(routes, key=lambda r: r["user_id"])
    random.Random(f"order:{day.isoformat()}").shuffle(order)
    if not order:
        return order
    if len(order) == 1:
        order[0]["departure"] = SIM_DAY_START
        return order

    d = [r["duration_minutes"] for r in order]
    order[0]["departure"] = SIM_DAY_START - d[0] - 2   # already on site when the window opens
    order[1]["departure"] = SIM_DAY_START - 0.3 * d[1]
    if len(order) == 2:
        return order
    # `step` = fraction of a trip that passes before the next worker leaves (< 1 = overlap).
    # Solve dep[1] + step * sum(d[1:-1]) + d[-1] = SIM_DAY_END, then clamp so trips overlap.
    span = SIM_DAY_END - order[1]["departure"] - d[-1]
    step = min(0.9, max(0.2, span / sum(d[1:-1])))
    for k in range(2, len(order)):
        order[k]["departure"] = order[k - 1]["departure"] + step * d[k - 1]
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


def get_worker_position(worker, route, sim_clock_minutes):
    """Where `worker` is at `sim_clock_minutes` on their `route`.

    Returns a dict with status "Not started" (no position), "In transit" or "On site".
    """
    base = {"user_id": worker.user_id, "near_traffic": False, "hotspot": None, "distance_remaining_m": None}
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
            return {
                **base,
                "status": "In transit",
                "lat": round(lat, 6),
                "lng": round(lng, 6),
                "near_traffic": pc["hotspot"] is not None,
                "hotspot": pc["hotspot"],
                "distance_remaining_m": round(max(0.0, remaining)),
            }
        elapsed -= pc["minutes"]
        travelled += pc["length_m"]


def off_duty_spot(user_id, day):
    """A fixed, deterministic point near a landmark for a worker who isn't working today."""
    rng = random.Random(f"home:{user_id}:{day.isoformat()}")
    return random_point_near(*LANDMARKS[rng.choice(sorted(LANDMARKS))], 0.5, rng)


def get_live_map_state(sites, assignments, workers, day, now=None):
    """Compute the whole map from plain inputs (no queries, no writes).

    sites:        JobSite rows
    assignments:  today's Assignment rows (with .job and .job.site)
    workers:      active Worker rows
    """
    minutes, cycle = sim_clock(now)
    by_user = {a.user_id: a for a in assignments}
    routes = {
        a.user_id: build_route(a.user_id, day, a.job.site.latitude, a.job.site.longitude)
        for a in assignments
    }
    plan_departures(list(routes.values()), day)

    out = []
    for w in workers:
        info = {"id": w.user_id, "name": w.full_name, "trade": w.trade}
        a = by_user.get(w.user_id)
        if a is None:
            lat, lng = off_duty_spot(w.user_id, day)
            out.append({**info, "status": "Off duty", "lat": lat, "lng": lng, "job_title": None,
                        "site_name": None, "near_traffic": False, "hotspot": None,
                        "distance_remaining_m": None})
            continue
        pos = get_worker_position(w, routes[w.user_id], minutes)
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
            }
            for s in sites
        ],
        "workers": out,
    }
