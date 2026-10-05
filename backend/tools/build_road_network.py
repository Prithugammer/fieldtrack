"""Build backend/data/kathmandu_roads.json, the road network the Live Map routes along.

Run once (the output is committed, so the app never needs the network):

    python tools/build_road_network.py                 # download from OpenStreetMap Overpass
    python tools/build_road_network.py raw.json        # or reuse a saved Overpass response

It keeps the Kathmandu Valley's main roads (motorway down to unclassified), splits them at
junctions, simplifies each stretch to within SIMPLIFY_M metres of the real road, keeps only
the largest connected piece (so every point can reach every other), and writes:

    {"nodes": [lat_e5, lng_e5, lat_e5, lng_e5, ...],   # coordinates x 100,000
     "ways":  [[node, node, ...], ...]}                 # polylines over node indices

Road data © OpenStreetMap contributors, available under the Open Database License (ODbL).
"""

import json
import os
import sys
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from geofence import haversine  # noqa: E402
from kathmandu_geo import KATHMANDU_VALLEY_BOUNDS as B  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
]
HIGHWAYS = "motorway|trunk|primary|secondary|tertiary|unclassified"
SIMPLIFY_M = 4


def download():
    query = (
        f'[out:json][timeout:180];way["highway"~"^({HIGHWAYS})(_link)?$"]'
        f"({B['south']},{B['west']},{B['north']},{B['east']});(._;>;);out skel qt;"
    )
    body = urllib.parse.urlencode({"data": query}).encode()
    for url in OVERPASS_URLS:
        req = urllib.request.Request(url, body, {"User-Agent": "FieldTrack road builder"})
        try:
            with urllib.request.urlopen(req, timeout=240) as res:
                return json.load(res)
        except OSError as err:
            print(f"{url}: {err}", file=sys.stderr)
    sys.exit("Every Overpass server failed; try again later.")


def _offset_m(p, a, b):
    """Distance in metres from p to segment a-b (flat approximation, fine at this scale)."""
    ky = 111_195
    kx = ky * 0.885  # cos(27.7 degrees)
    ax, ay, bx, by, px, py = a[1] * kx, a[0] * ky, b[1] * kx, b[0] * ky, p[1] * kx, p[0] * ky
    dx, dy = bx - ax, by - ay
    t = (
        0.0
        if dx == dy == 0
        else max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    )
    return ((px - ax - t * dx) ** 2 + (py - ay - t * dy) ** 2) ** 0.5


def simplify(chain, coords):
    """Douglas-Peucker: drop points that sit within SIMPLIFY_M of the line between neighbours."""
    if len(chain) < 3:
        return chain
    a, b = coords[chain[0]], coords[chain[-1]]
    worst, i = max((_offset_m(coords[n], a, b), i) for i, n in enumerate(chain[1:-1], 1))
    if worst <= SIMPLIFY_M:
        return [chain[0], chain[-1]]
    return simplify(chain[: i + 1], coords)[:-1] + simplify(chain[i:], coords)


def build(raw):
    coords = {e["id"]: (e["lat"], e["lon"]) for e in raw["elements"] if e["type"] == "node"}
    ways = [e["nodes"] for e in raw["elements"] if e["type"] == "way" and len(e["nodes"]) > 1]

    # A junction is any node used more than once (shared by two ways, or a way's ends).
    uses = {}
    for w in ways:
        for n in w:
            uses[n] = uses.get(n, 0) + 1
        uses[w[0]] += 1
        uses[w[-1]] += 1

    chains = []
    for w in ways:
        start = 0
        for i in range(1, len(w)):
            if uses[w[i]] > 1 or i == len(w) - 1:
                chains.append(simplify(w[start : i + 1], coords))
                start = i

    # Keep the largest connected component.
    adj = {}
    for c in chains:
        adj.setdefault(c[0], set()).add(c[-1])
        adj.setdefault(c[-1], set()).add(c[0])
    best, seen = set(), set()
    for root in adj:
        if root in seen:
            continue
        comp, stack = {root}, [root]
        while stack:
            for m in adj[stack.pop()]:
                if m not in comp:
                    comp.add(m)
                    stack.append(m)
        seen |= comp
        best = max(best, comp, key=len)
    chains = [c for c in chains if c[0] in best]

    index, nodes, out_ways = {}, [], []
    for c in chains:
        for n in c:
            if n not in index:
                index[n] = len(index)
                nodes += [round(coords[n][0] * 1e5), round(coords[n][1] * 1e5)]
        out_ways.append([index[n] for n in c])
    km = sum(haversine(*coords[a], *coords[b]) for c in chains for a, b in zip(c, c[1:])) / 1000
    print(f"{len(index)} nodes, {len(out_ways)} road stretches, {km:.0f} km of road")
    return {"nodes": nodes, "ways": out_ways}


if __name__ == "__main__":
    raw = json.load(open(sys.argv[1], encoding="utf-8")) if len(sys.argv) > 1 else download()
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "kathmandu_roads.json"), "w", encoding="utf-8") as f:
        json.dump(build(raw), f, separators=(",", ":"))
