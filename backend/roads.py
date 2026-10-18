"""Shortest paths along the Kathmandu Valley's real roads, for the Live Map simulation.

The road network is a committed file (data/kathmandu_roads.json, built from OpenStreetMap by
tools/build_road_network.py), so routing needs no network access and no extra packages:
a small A* search over it. Road data © OpenStreetMap contributors (ODbL).
"""

import heapq
import json
import math
import os
from functools import lru_cache

ROADS_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "kathmandu_roads.json"
)
CELL_DEG = 0.005  # nearest-node lookup grid, roughly 500 m squares

# Routing only makes sense near the road network. A point farther than this from every road
# point is "unsupported": it gets no route (RouteUnavailable / None) instead of an open-ended
# search. 5 km comfortably covers every site in and around the Valley (the committed network
# spans roughly lat 27.59-27.84, lng 85.16-85.48) while keeping the lookup to ~20 x 20 cells.
MAX_SNAP_M = 5_000

_KY = 111_195  # metres per degree of latitude
_KX = _KY * math.cos(math.radians(27.7))  # metres per degree of longitude in the valley


class RouteUnavailable(Exception):
    """A point is outside the road network's coverage, so no route can be drawn to or from it."""


def _metres(a, b):
    """Flat-earth distance; accurate to well under 1% across the valley, and fast."""
    return math.hypot((a[0] - b[0]) * _KY, (a[1] - b[1]) * _KX)


def _cell(p):
    return int(p[0] // CELL_DEG), int(p[1] // CELL_DEG)


@lru_cache(maxsize=1)
def _network():
    with open(ROADS_FILE, encoding="utf-8") as f:
        raw = json.load(f)
    flat = raw["nodes"]
    coords = [(flat[i] / 1e5, flat[i + 1] / 1e5) for i in range(0, len(flat), 2)]
    adj = [[] for _ in coords]
    for way in raw["ways"]:
        for a, b in zip(way, way[1:]):
            d = _metres(coords[a], coords[b])
            adj[a].append((b, d))
            adj[b].append((a, d))
    grid = {}
    for i, p in enumerate(coords):
        grid.setdefault(_cell(p), []).append(i)
    return coords, adj, grid


def _usable(lat, lng):
    """True for a pair of finite, in-range numbers (anything else can never be routed)."""
    try:
        return math.isfinite(lat) and math.isfinite(lng) and -90 <= lat <= 90 and -180 <= lng <= 180
    except TypeError:
        return False


@lru_cache(maxsize=1)
def _coverage():
    """Bounding box of the road network, widened by MAX_SNAP_M: (south, north, west, east)."""
    coords = _network()[0]
    lats = [p[0] for p in coords]
    lngs = [p[1] for p in coords]
    return (
        min(lats) - MAX_SNAP_M / _KY,
        max(lats) + MAX_SNAP_M / _KY,
        min(lngs) - MAX_SNAP_M / _KX,
        max(lngs) + MAX_SNAP_M / _KX,
    )


def nearest_node(lat, lng, max_distance_m=MAX_SNAP_M):
    """Index of the road point closest to (lat, lng), or None if none is within max_distance_m.

    The search is bounded in both directions: a point outside the network's (widened) bounding
    box is rejected in O(1), and otherwise at most ~(max_distance_m / cell) rings are scanned,
    so it always terminates quickly whatever the input (far away, NaN, infinite, out of range).
    """
    if not _usable(lat, lng):
        return None
    south, north, west, east = _coverage()
    if not (south <= lat <= north and west <= lng <= east):
        return None
    coords, _, grid = _network()
    ci, cj = _cell((lat, lng))
    max_ring = int(max_distance_m // (CELL_DEG * _KX)) + 2
    best, ring = None, 0
    # Search outward ring by ring; once something is found, one more ring settles ties
    # across cell edges.
    while ring <= max_ring:
        for i in range(ci - ring, ci + ring + 1):
            for j in range(cj - ring, cj + ring + 1):
                if max(abs(i - ci), abs(j - cj)) != ring:
                    continue
                for n in grid.get((i, j), ()):
                    d = _metres(coords[n], (lat, lng))
                    if best is None or d < best[0]:
                        best = (d, n)
        if best and best[0] < ring * CELL_DEG * _KX:
            break
        ring += 1
    if best is None or best[0] > max_distance_m:
        return None
    return best[1]


@lru_cache(maxsize=2048)
def is_routable(lat, lng):
    """True if (lat, lng) is close enough to the road network to be routed to."""
    return nearest_node(lat, lng) is not None


@lru_cache(maxsize=4096)
def path_between(a, b):
    """Road points (lat, lng) on the shortest drive from node a to node b, both included."""
    coords, adj, _ = _network()
    goal = coords[b]
    best = {a: 0.0}
    came = {}
    heap = [(_metres(coords[a], goal), 0.0, a)]
    while heap:
        _, g, n = heapq.heappop(heap)
        if n == b:
            break
        if g > best[n]:
            continue
        for m, d in adj[n]:
            if g + d < best.get(m, math.inf):
                best[m] = g + d
                came[m] = n
                heapq.heappush(heap, (g + d + _metres(coords[m], goal), g + d, m))
    path = [b]
    while path[-1] != a:
        path.append(came[path[-1]])
    return tuple(coords[n] for n in reversed(path))


def road_path(points):
    """Drive through `points` in order along the roads; returns the list of road points.

    Each point is first snapped to its nearest road point, so the result starts and ends on
    a road (callers add any short walk off the road themselves). Raises RouteUnavailable if a
    point is outside the network's coverage.
    """
    nodes = [nearest_node(*p) for p in points]
    if any(n is None for n in nodes):
        raise RouteUnavailable("A route point is outside the supported road network.")
    out = [_network()[0][nodes[0]]]
    for a, b in zip(nodes, nodes[1:]):
        if a != b:
            out += path_between(a, b)[1:]
    return out


def snap(lat, lng):
    """The road point nearest to (lat, lng). Raises RouteUnavailable if there is none nearby."""
    node = nearest_node(lat, lng)
    if node is None:
        raise RouteUnavailable("The point is outside the supported road network.")
    return _network()[0][node]
