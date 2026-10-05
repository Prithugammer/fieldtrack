# FieldTrack — Development Notes

How the project was planned, how the plan changed, and the main technical decisions. This is
the project-management record behind the finished system (CLO 3).

## 1. The original plan and the pivot

FieldTrack was planned as a three-person, ten-day build, with each member owning one layer of
the system:

| Member | Role | Owned |
|--------|------|-------|
| A | Project manager and backend | Flask API, business rules, authentication, schedule |
| B | Frontend | React admin app and the worker mobile app |
| C | Database and QA | Schema, seed data, test plan and testing |

The plan front-loaded analysis and design (requirements, ERD, data dictionary, Figma
prototype) in Days 1–4, with the three layers built in parallel after that and joined in the
final days for integration and testing.

That plan did not survive contact with the semester. Early in the build both teammates became
unavailable — one through illness and one through family caregiving responsibilities — and
FieldTrack became a solo project. The work of three people across the first four days had to
be compressed into a single day. I re-planned around one principle: get a thin, working slice
through every layer (database → API → screen) first, and only then widen it. A three-layer
plan with hand-offs no longer made sense when one person owned every layer, so I merged the
layers and worked feature by feature instead: the core models and authentication, then the
API rules with tests, then the admin pages that used them.

## 2. Feedback that reshaped the scope

At the mid-project review I showed the first UI showcase. The professor's feedback was direct:
it looked rushed. He asked me to drop the worker mobile app entirely and put the remaining
time into the administrative/dispatcher side, backed by a real working database, within two
days.

That feedback became the scope for the rest of the project:

- **The mobile worker app was deferred to Phase 2.** It is listed in the README under *Known
  limitations and future work*, and the API is shaped so a phone app could use it later.
- **Worker GPS was replaced by a server-side simulation** (`backend/simulation.py`). Without a
  phone there is no live location, but the ideas the app depends on — geofences, flagged
  off-site time, workers moving and arriving on site — still needed to be demonstrable. The
  simulation computes each worker's position from the clock on every request, so the geofence
  and Live Map concepts can be shown without any device.
- **The Figma prototype was repurposed.** It had been the blueprint for both apps; it now
  serves as the interface-design evidence for CLO 7, and its colour and spacing values became
  the design tokens the admin app is styled with.

### The triple constraint in practice

The project is a clear example of the scope–time–cost triangle. **Cost** was fixed at zero:
every tool is free (Python, Flask, SQLite, React, Vite, Leaflet with OpenStreetMap tiles,
Figma's free tier, GitHub). **Time** was compressed — one person instead of three, and one day
for what had been planned as four. With cost and time both fixed, **scope** was the only side
that could move, so it was cut: the mobile app was removed and the administrative side was
built properly instead of two half-finished apps. Quality was protected by keeping the
remaining scope small enough to test: the business rules are covered by an automated test
suite rather than checked by hand.

## 3. Key technical decisions

| Decision | Alternatives | Why |
|----------|--------------|-----|
| **Flask (Python) for the API** | Node/Express | Readable and teachable: a small, explicit framework where each route is a plain function with its rules visible top to bottom, which keeps the business rules easy to read, explain and test with pytest. SQLAlchemy models map one-to-one to the ERD. |
| **SQLite** | PostgreSQL / MySQL | Zero install — a single file created by `seed.py` — so the project runs on any marker's machine, while still being a real SQL database: the schema enforces keys, a unique email, one assignment per worker per day and allowed status values. Because every query goes through the ORM, moving to PostgreSQL is a one-line change to `DATABASE_URL`. |
| **React (Vite) with plain CSS and design tokens** | A component library | The tokens match the Figma design system value for value, so the built app looks like the prototype; there are no hidden library styles to override, and every component is small enough to read. |
| **JWT with the role in the token** | Server sessions | The API stays stateless; `@role_required` checks the role from the token and re-checks the account is still active on every request. |
| **Flag, don't block, off-site time** | Reject entries outside the geofence | GPS drifts and the company must pay for time worked, so a supervisor decides. Captured in the decision table. |
| **Never store hours** | A stored `hours` column | Hours are computed from clock-in/out, so they can never drift out of sync with the times (and shifts across midnight work automatically). |
| **Simulated GPS for the Live Map** | Static mock data; a background job writing positions | Static mock data never moves, so it cannot show traffic delays or arrivals. The simulation is deterministic — the same demo every time — and always shows the right ideas (workers on the road, slowed at junctions, arriving inside a geofence). It is also read-only, testable and safe on a low-memory laptop. See [live-map-design.md](live-map-design.md). |
| **Seed data relative to today** | Fixed dates | The demo always has "today's" jobs, whenever it is run. |

## 4. Finishing phase (4 October 2026)

The last stage turned a working build into a submittable one. Each step was verified before the
next began.

1. **Verification pass.** Fresh seed, full test suite, and the 8-step demo walked through in a
   real browser, including downloading and checking the CSV against the screen. The API spec and
   data dictionary were corrected where they had drifted from the code.
2. **Live Map added** (FR-13). The first design replayed a full 6 AM–6 PM day; measuring it showed
   the map would be still about 80 % of the time, so the window was narrowed to a 75-minute
   morning commute, chosen by measuring 120 simulated days for zero idle minutes.
3. **Exploratory browser testing** found five Live Map issues — zig-zag routes (one at 1.89× the
   direct distance), geofence circles hidden under their pins, the map could be flung out of the
   valley, an abrupt cycle restart, and co-located workers stacking into one dot. All five were
   fixed and re-verified (the 1.3× route rule, smaller pins and a closer opening view, bounded
   panning with a Reset view button, a crossfade with a countdown, and fanned-out markers).
   Later testing showed workers still cut across buildings between landmarks, so routes were
   moved onto the real road network (OpenStreetMap data, routed offline).
4. **Finalisation.** Secrets and CORS moved to environment variables with debug mode off by
   default; tests added for password hashing, token expiry and every role check; a single code
   style applied (black, Prettier); all analysis documents cross-checked against the code; and a
   fresh clone set up by following only the README.

## 5. What I would do differently

- **Plan for losing people.** The original plan gave each layer to one person, so losing two
  people meant losing two whole layers at once. Pairing members across layers, or building a
  thin end-to-end slice in the first days, would have made the plan far less fragile.
- **Show something real earlier.** The rushed first showcase came from spending the early days
  on breadth — two apps and many screens — instead of one working path through the system.
  Earlier feedback on a smaller, working slice would have redirected the scope sooner.
- **Measure, don't guess.** The most useful decisions late in the project came from measuring:
  how often the Live Map was idle, how far routes strayed from a straight line. Applying that
  habit to the schedule (tracking estimates against actual time per feature) would have made
  re-planning easier when the team changed.
- **Treat scope as the lever it is.** With time and cost fixed, cutting the mobile app was the
  right call, and the result is one complete system rather than two incomplete ones. I would
  make that kind of decision deliberately at the start of a project rather than waiting for it
  to be forced.
