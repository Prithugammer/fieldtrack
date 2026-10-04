# FieldTrack — Live Map Design

The Live Map (FR-13, UC13) shows every job site with its geofence and where each worker is.
This document explains the design decisions behind it. The code is in
`backend/simulation.py`, `backend/kathmandu_geo.py`, `backend/routes/map.py` and
`frontend/src/pages/LiveMap.jsx`.

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
  so routes look like real commutes. Measured over 14,400 routes: worst case exactly 1.30×,
  74 % still use landmark waypoints, 76 % still pass a traffic junction.
- **Duration:** distance at the worker's usual speed (15–28 km/h, Kathmandu traffic), kept to
  **8–35 minutes**.

## 4. Traffic model

Routes are split into 100 m pieces. A piece whose midpoint lies inside a hotspot's radius takes
`1 / speed_multiplier` times as long (e.g. 4× at Koteshwor), so markers visibly slow down and
bunch up at junctions. While a worker is inside a hotspot the API reports
`near_traffic: true` with the junction's name, which the UI shows as *Delayed near Chabahil*.

## 5. The simulated clock: 6:00–7:15 AM every 5 minutes

Real time is mapped onto a repeating window: `time.time() % 300` seconds → 6:00–7:15 AM.

*Why this window and not a full 6 AM–6 PM day:* each worker makes one 8–35 minute commute and
then stays on site. Over a 12-hour simulated day, with six workers, someone would be moving only
about 20 % of the time — the map would sit still for most of a demo. A 3-hour window still left
up to 37 % of the time with nobody moving on some days. The 75-minute morning-dispatch window
was measured over 120 different days with **zero minutes where nobody is moving and zero minutes
where nobody is on site**.

Departures are staggered so commutes overlap: the first worker (in a per-day shuffled order)
arrives just before 6:00, the second is part-way there, and each later worker leaves before the
previous one arrives.

## 6. Statuses

| Status | When | On the map |
|--------|------|------------|
| Not started | Assigned today, simulated time is before their departure | Not drawn (counted in the legend) |
| In transit | On the road; `near_traffic` when inside a hotspot | Amber dot; orange ring when delayed |
| On site | Arrived; a fixed spot within ~30 m of the site centre | Green dot inside the geofence |
| Off duty | No assignment today | Grey dot at a fixed point near a landmark; never moves |

## 7. Front-end decisions

- **Polling every 4 s** with a CSS transform transition so markers glide rather than jump.
- **Opening view** frames all job sites (not the whole valley box), so a 200 m geofence is about
  24 px across instead of a few pixels hidden under its pin; site pins are small dots for the
  same reason.
- **Panning is limited** to the valley plus 25 % with a solid edge, and a **Reset view** button
  returns to the opening view — a fast drag can no longer throw the map out of the valley.
- **Cycle restart:** old markers fade out while the new cycle fades in, and a *New cycle in m:ss*
  countdown with a thin progress bar shows when the restart is coming.
- **Shared sites:** on-site workers at the same site fan out on a small ring around the site dot
  (in screen pixels, so they stay apart at every zoom; API coordinates are unchanged).

## 8. Limitations

- Positions are not real; the map demonstrates the interface a real GPS feed would drive.
- Routes are straight segments between landmarks, not snapped to the road network.
- Every worker makes one commute per cycle; there are no lunch trips or site-to-site moves.
- The map shows assignments for today's date only.
