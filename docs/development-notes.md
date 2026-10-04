# FieldTrack — Development Notes

How the project was planned, how the plan changed, and the main technical decisions. This is
the project-management record behind the finished system (CLO 3).

## 1. The original plan and the pivot

> **To complete (author):** describe the original 3-person, 10-day plan — who owned which
> part, the milestones — and what changed when it became a solo build: what was cut, merged or
> re-ordered, and how the schedule was re-planned.

## 2. Feedback that reshaped the scope

> **To complete (author):** summarise the professor's feedback and the scope decisions it led
> to (for example, focusing on the administrative side and leaving the worker mobile app as
> future work).

## 3. Key technical decisions

| Decision | Alternatives | Why |
|----------|--------------|-----|
| **Flask (Python) for the API** | Node/Express | A small, explicit framework: each route is a plain function with its rules visible top to bottom, which keeps the business rules easy to read and to test with pytest. SQLAlchemy models map one-to-one to the ERD. |
| **SQLite** | PostgreSQL / MySQL | Zero setup — a single file created by `seed.py` — so the project runs on any marker's machine. The schema still enforces keys, a unique email, one assignment per worker per day and allowed status values. `DATABASE_URL` allows a server database later. |
| **React (Vite) with plain CSS and design tokens** | A component library | Full control over the look, and every component is small enough to read; no library conventions to learn. |
| **JWT with the role in the token** | Server sessions | The API stays stateless; `@role_required` checks the role from the token and re-checks the account is still active on every request. |
| **Flag, don't block, off-site time** | Reject entries outside the geofence | GPS drifts and the company must pay for time worked, so a supervisor decides. Captured in the decision table. |
| **Never store hours** | A stored `hours` column | Hours are computed from clock-in/out, so they can never drift out of sync with the times (and shifts across midnight work automatically). |
| **Simulated GPS for the Live Map** | Static mock data; a background job writing positions | Deterministic, read-only, testable, and safe on a low-memory laptop. See [live-map-design.md](live-map-design.md). |
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
4. **Finalisation.** Secrets and CORS moved to environment variables with debug mode off by
   default; tests added for password hashing, token expiry and every role check; a single code
   style applied (black, Prettier); all analysis documents cross-checked against the code; and a
   fresh clone set up by following only the README.

## 5. What I would do differently

> **To complete (author):** lessons about planning, estimating and working solo.
