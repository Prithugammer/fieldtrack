# FieldTrack — Live Map Design

The Live Map (FR-13, UC13) shows every job site with its geofence and where each worker is.
This document explains the design decisions behind it. The code is in
`backend/simulation.py`, `backend/kathmandu_geo.py`, `backend/routes/map.py` and
`frontend/src/pages/LiveMap.jsx`, with road routing in `backend/roads.py`.

## 1. Why the positions are simulated

FieldTrack is the **administrative** side of the system. The worker-facing mobile app that
would report real GPS is out of scope for this project (see the README's *Known limitations*).
Without it there is no live location feed, but a dispatcher still needs to see what the map
would look like, and the demo needs to show geofences, traffic and arrival on site.

Four options were considered:

| Option | Problem |
|--------|---------|
| Static mock data (fixed dots) | Nothing moves, so it shows none of the behaviour being demonstrated. |
| Random positions every request | Workers jump around; nothing is repeatable or explainable. |
| A background job that writes positions to the database every few seconds | Adds a thread/scheduler and constant writes. The development laptop ran low on memory during the build, and a stuck background process is a risk in a live demo. |
| **Deterministic simulation computed on each request** (chosen) | — |

The chosen design is a **pure calculation**: every `GET /api/map/live` answers "where would
each worker be right now?" from the server clock. Nothing is written to the database, no
thread runs, and the same inputs always give the same answer, so behaviour is repeatable and
can be unit-tested (`backend/tests/test_map.py`). The page labels it *Simulated time* so no
one mistakes it for real GPS.

## 2. Geography

`kathmandu_geo.py` holds real coordinates so the map is grounded in a real place:

- **Valley bounds** 27.60–27.80 °N, 85.20–85.45 °E.
- **12 landmarks** (Kathmandu, Patan and Bhaktapur Durbar Squares, Boudhanath, Kirtipur,
  Koteshwor, Kalanki, Chabahil, Jawalakhel, Gongabu, Thimi, Sankhu) used as route waypoints and
  as anchors for the seeded job sites.
- **4 traffic hotspots** at real congested junctions — Koteshwor, Kalanki, Chabahil, Gongabu —
  each with a radius (550–700 m) and a speed multiplier (0.25–0.35).
- Seeded job sites sit a few hundred metres from a landmark (fixed random seed, so the
  coordinates are identical every time `seed.py` runs).
- **The road network:** `backend/data/kathmandu_roads.json` holds the valley's main roads
  (motorway down to unclassified, about 1,700 km) from OpenStreetMap. It is built once by
  `backend/tools/build_road_network.py` and committed, so the app routes offline with a small
  A* search (`roads.py`) and no extra packages. Road data © OpenStreetMap contributors (ODbL).

## 3. Routes: deterministic and plausible

Each worker assigned to a job today gets a route generated from a random seed made of their
`user_id` and today's date — stable across requests, different tomorrow.

- **Start:** a landmark 2.5–10 km from the job site, jittered by up to 400 m.
- **Waypoints:** up to two landmarks between start and site, preferring traffic junctions
  (main roads run through them).
- **The 1.3× rule:** the *whole* route (start → waypoints → site) must be at most **1.3 times
  the straight-line distance**. Candidates are tried in a fixed preference order, dropping to
  fewer waypoints (and finally driving direct) until one fits.

  *Why:* checking each waypoint on its own was not enough — two waypoints that are each a
  reasonable detour can still combine into a zig-zag across the city (testing found one route
  at 1.89×). 1.3× is a typical ratio of road distance to straight-line distance in a city,
  so routes look like real commutes.
- **Along the roads:** the worker sets off from the road point nearest their start, drives
  the shortest road path through the waypoints, and finishes with a short walk (under ~200 m
  for the seeded sites) from the nearest road onto the site. If the waypoints make the *drive*
  more than 1.3× the shortest drive (two landmarks can be close as the crow flies but far
  apart by road), the worker drives direct instead.
- **Duration:** distance at the worker's usual speed (15–28 km/h, Kathmandu traffic), kept to
  **8–35 minutes**.

## 4. Traffic model

Routes are split into 100 m pieces. A piece whose midpoint lies inside a hotspot's radius takes
`1 / speed_multiplier` times as long (e.g. 4× at Koteshwor), so markers visibly slow down and
bunch up at junctions. While a worker is inside a hotspot the API reports
`near_traffic: true` with the junction's name, which the UI shows as *Delayed near Chabahil*.

The hotspots are not drawn on the map — circles over the busiest junctions cluttered the view
and drew the eye away from the workers. The slowdown still applies; it shows on the workers
themselves, as a red *Delayed in traffic* marker.

## 5. The simulated clock: 6:00–6:45 AM every 5 minutes

Real time is mapped onto a repeating window: `time.time() % 300` seconds → 6:00–6:45 AM.

*Why this window and not a full 6 AM–6 PM day:* each worker makes one 8–35 minute commute and
then stays on site. Over a 12-hour simulated day, with six workers, someone would be moving only
about 20 % of the time — the map would sit still for most of a demo. A 3-hour window still left
up to 37 % of the time with nobody moving on some days.

The window was first 75 minutes (6:00–7:15) with departures evenly staggered, which kept someone
moving at every minute but left up to four of six workers hidden as *Not started* early in each
cycle — often only two or three workers were visible. The goal was then sharpened to **about five
workers visibly working (on the road or on site) at every moment**. Measuring random departure
plans showed that is out of reach in 75 minutes with one commute each (only about half of days
managed five), but a **45-minute window reaches it on every one of 60 measured days**, still with
zero minutes where nobody is moving and zero where nobody is on site. Markers also move more
slowly and smoothly, since each 5-minute cycle covers less simulated time.

**Departures are picked at random**, seeded by the date so a day replays identically:
300 random plans (each worker leaving between an hour before the window and 25 minutes before
it ends) are scored minute by minute, and the best kept. In order, a plan must have no minute
with nobody moving or nobody on site; then as many workers working at every moment as
possible, up to five; then someone setting off during the window, so a worker appears on the
map mid-cycle; then as much time spent moving as possible. With six assigned, the result is
five working at the start, the sixth showing up at a random moment, and two or three on the
road on average.

## 6. Statuses

| Status | When | On the map |
|--------|------|------------|
| Not started | Assigned today, simulated time is before their departure | Not drawn (counted in the legend) |
| In transit | On the road; `near_traffic` when inside a hotspot | Amber dot; red dot when delayed in traffic |
| On site | Arrived; a fixed spot within ~30 m of the site centre | Green dot inside the geofence |
| Off duty | No assignment today | Grey dot at a fixed point near a landmark; never moves |

## 7. Front-end decisions

- **Base map:** Stadia Maps *Alidade Smooth* (light) and *Alidade Smooth Dark*, following the
  app theme. The standard OpenStreetMap tiles label Kathmandu in Nepali script; these show
  English place names, are muted so the coloured markers stand out, and are served at 2× on
  high-density screens. They are free without a key on `localhost`; a hosted deployment needs
  a free Stadia account registered to its domain.
- **Polling every second** with a CSS transform transition so markers glide rather than jump.
  The glide is a straight line, so the interval is kept short: one second covers about 100 m
  of road, and the marker stays on the road around bends. (At 4 s it cut corners by
  several hundred metres and workers appeared to fly across buildings.)
- **Opening view** frames all job sites (not the whole valley box), so a 200 m geofence is about
  24 px across instead of a few pixels hidden under its pin; site pins are small dots for the
  same reason.
- **Panning is limited** to the valley plus 25 % with a solid edge, and a **Reset view** button
  returns to the opening view — a fast drag can no longer throw the map out of the valley.
- **Cycle restart:** old markers fade out while the new cycle fades in, and a *New cycle in m:ss*
  countdown with a thin progress bar shows when the restart is coming.
- **Route on click:** clicking an in-transit worker opens their popup (job, **km left** to the
  site) and draws the rest of their route as a **white line along the roads** to the site. While
  the popup is open, each poll asks `GET /map/live?route=<id>`, which returns that worker's
  remaining route as `path`, so the line shortens as they drive and disappears when they
  arrive or the popup is closed. Only the selected worker's path is sent, keeping the
  once-a-second poll small. The line has a thin dark edge so it reads on the light map too.
- **Shared sites:** on-site workers at the same site fan out on a small ring around the site dot
  (in screen pixels, so they stay apart at every zoom; API coordinates are unchanged).

## 8. Limitations

- Positions are not real; the map demonstrates the interface a real GPS feed would drive.
- Routing ignores one-way streets and road class (a lane counts the same as a highway), and
  the road network is a snapshot: rebuild it with `tools/build_road_network.py` to refresh.
- Every worker makes one commute per cycle; there are no lunch trips or site-to-site moves.
- The map shows assignments for today's date only.

## Sites outside the road network

Routing uses the committed road file (latitude 27.59-27.84, longitude 85.16-85.48). `roads.nearest_node` snaps a
point to the closest road point but **gives up** (returns `None`) when the point is outside the file's bounding box
widened by 5 km (`MAX_SNAP_M`) or no road point lies within 5 km. Before this limit existed the search kept
widening forever: a site in Pokhara made the first map request take 13.5 s and a site at (0, 0) never returned,
which also froze the safety controls (they share the simulation). Now such a site is reported as `routable: false`,
its workers appear as "Route unavailable" (no position), the map shows a warning, and everything else keeps working.
The 5 km figure is a documented engineering choice, not a requirement: it comfortably covers the Valley and its
edges while bounding the work to a few hundred grid cells.
