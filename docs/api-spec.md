# FieldTrack — REST API Specification

- **Base URL:** `http://localhost:5000/api`
- **Format:** JSON request and response bodies (`Content-Type: application/json`), except the CSV export.
- **Authentication:** `Authorization: Bearer <JWT>` on every endpoint except login. Tokens expire after 8 hours.
- **Dates:** `YYYY-MM-DD`. **Datetimes:** `YYYY-MM-DDTHH:MM[:SS]` (local site time, no timezone).
- **Staff** below means any of `Admin`, `Dispatcher`, `Supervisor`.
- **CORS:** only the origins in the `CORS_ORIGINS` environment variable may call the API (default: the Vite dev server on port 5173).

## Error format

Every error — validation, auth, not-found, conflict, server — has the same shape:

```json
{ "error": "Crew size must be between 1 and 50.", "field": "crew_size" }
```

`field` names the input that caused the problem, or is `null` for errors that are not
about a single field.

| Code | Meaning |
|------|---------|
| 400 | Validation failed (missing/invalid field). `field` is set. |
| 401 | Missing, invalid or expired token; or wrong email/password on login. |
| 403 | Authenticated, but the role is not allowed (or the account is deactivated). The role is read from the database on every request, so a demotion takes effect immediately. |
| 404 | The referenced record does not exist (including an id too large to exist). |
| 409 | Business-rule conflict: double-booking, crew full, not assigned, overlap, already decided, duplicate email. |
| 429 | Too many failed logins (see *Login throttling*). Carries a `Retry-After` header (seconds). |

## Numbers and ids

Whole numbers and ids are checked before they reach the database:

- Everything must fit a signed 64-bit integer (`-9223372036854775808` to `9223372036854775807`);
  otherwise **400** `"<Field> is out of range."`.
- `NaN`, `Infinity`, `-Infinity` and JSON literals such as `1e999` are not numbers: **400**.
  Booleans, text and fractions (`1.5`) are not whole numbers: **400**.
- Ids (`user_id`, `job_id`, `site_id`, query filters such as `?worker=`, `?route=`) must be **1 or more**.
  An invalid id in a request body or query string is a **400** with `field` set; an id that is valid
  but does not exist is a **404**.
- An id in the URL path (`/jobs/{job_id}`, ...) that is zero, or larger than 64 bits, is a **404**.
- Decimals (latitude, longitude) must be finite and in range. Dates are exactly `YYYY-MM-DD`.
- Passwords are 8-128 characters and at most **72 bytes** (a bcrypt limit); longer is a **400**.

## Login throttling

Only **failed** logins count. After 5 failures for one email (`LOGIN_MAX_FAILURES_PER_ACCOUNT`) or 20
from one client address (`LOGIN_MAX_FAILURES_PER_CLIENT`) within 300 s (`LOGIN_RATE_WINDOW_SECONDS`),
`POST /auth/login` answers **429** `{"error": "Too many failed sign-in attempts. Try again in N seconds.", "field": null}`
with `Retry-After: N` — even for the correct password — until the oldest failure leaves the window.
Blocked attempts are not counted, so a block never extends itself and no account is locked
permanently. A successful login clears that account's failures. Unknown emails are throttled
exactly like real ones. The counters live in the server process (see README, *Deployment notes*).

## Security headers

Every response carries `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`,
`Referrer-Policy: no-referrer`, `Content-Security-Policy: default-src 'none'; frame-ancestors 'none'; base-uri 'none'`
and `Cache-Control: no-store`. `Strict-Transport-Security` is added only when `HSTS_ENABLED=1` **and**
the request arrived over HTTPS.

---

## Health

### GET /health
- **Role:** public (no token)
- **200:** `{ "status": "ok" }` — used to check the API is running.

---

## Auth

### POST /auth/login
- **Role:** public
- **Body:** `{ "email": "admin@fieldtrack.com", "password": "Admin123!" }`
- **200:** `{ "token": "<jwt>", "user": { "user_id": 1, "full_name": "Sunita Sharma", "email": "...", "role": "Admin", ... } }` — JWT claims include `user_id` and `role`.
- **Errors:** 400 (`email`/`password` missing), 401 invalid credentials, 403 account deactivated or Worker account.

### GET /auth/me
- **Role:** Staff (Workers can never obtain a token)
- **200:** `{ "user": { ... } }`
- **Errors:** 401, 403 (deactivated since login)

---

## Users

### GET /users
- **Role:** Staff
- **Query:** `role` (optional, e.g. `Worker`), `active` (`true`/`false`, optional)
- **200:** `{ "users": [ { "user_id", "full_name", "email", "phone", "role", "trade", "is_active" } ] }` — `password_hash` is never returned.

### POST /users
- **Role:** Admin
- **Body:** `{ "full_name", "email", "phone"?, "role", "trade"?, "password"? }` — `password` (≥ 8 chars) required for staff roles; `trade` required for Workers.
- **201:** `{ "user": { ... } }`
- **Errors:** 400 field validation, 409 email already exists.

### PATCH /users/{user_id}
- **Role:** Admin
- **Body (any subset):** `{ "full_name", "email", "phone", "role", "trade", "is_active", "password" }`
- **200:** `{ "user": { ... } }`
- **Errors:** 400, 404, 409 (email already used by another user; admin tries to deactivate or demote their own account).

---

## Job Sites

### GET /sites
- **Role:** Staff
- **200:** `{ "sites": [ { "site_id", "site_name", "address", "latitude", "longitude", "geofence_radius_m", "job_count" } ] }`

### POST /sites
- **Role:** Dispatcher, Admin
- **Body:** `{ "site_name", "address", "latitude", "longitude", "geofence_radius_m"? }` (radius defaults to 200)
- **201:** `{ "site": { ... } }`
- **Errors:** 400 (e.g. `latitude` outside −90..90, radius outside 25..5000).

### PATCH /sites/{site_id}
- **Role:** Dispatcher, Admin
- **Body:** any subset of the POST fields
- **200:** `{ "site": { ... } }`
- **Errors:** 400, 404

---

## Jobs

### GET /jobs
- **Role:** Staff
- **Query:** `date` (`YYYY-MM-DD`), `status` (`Scheduled` | `In progress` | `Completed`), `site_id` — all optional
- **200:** `{ "jobs": [ { "job_id", "title", "description", "scheduled_date", "crew_size", "status", "site_id", "site_name", "site_address", "created_by", "created_by_name", "assigned_count", "crew": [ { "assignment_id", "user_id", "full_name", "trade" } ] } ] }`
- **Errors:** 400 invalid date/status filter

### GET /jobs/{job_id}
- **Role:** Staff
- **200:** `{ "job": { ... } }` — **404** if missing

### POST /jobs
- **Role:** Dispatcher, Admin
- **Body:** `{ "site_id", "title", "description"?, "scheduled_date", "crew_size", "status"? }` — `created_by` is taken from the JWT.
- **201:** `{ "job": { ... } }`
- **Errors:** 400, 404 site not found

### PATCH /jobs/{job_id}
- **Role:** Dispatcher, Admin
- **Body:** any subset of the POST fields
- **200:** `{ "job": { ... } }`
- **Errors:** 400 (incl. crew_size below current assignments), 404, 409 (changing the date while workers are assigned)

---

## Assignments

### GET /assignments
- **Role:** Staff
- **Query:** `job_id`, `user_id`, `work_date` — all optional
- **200:** `{ "assignments": [ { "assignment_id", "job_id", "job_title", "site_name", "user_id", "full_name", "trade", "work_date", "assigned_at" } ] }`

### POST /assignments
- **Role:** Dispatcher, Admin
- **Body:** `{ "job_id", "user_id", "work_date"? }` — `work_date` defaults to the job's scheduled date and must equal it.
- **201:** `{ "assignment": { ... } }`
- **Errors:**
  - 400 missing/invalid field; worker inactive or not a Worker (`field: "user_id"`)
  - 404 job or user not found
  - **409 double-booking** — `{ "error": "Ramesh Karki is already assigned to 'Level 4 framing' at Kirtipur Campus Expansion on 2026-10-01. A worker can only be booked on one job per day.", "field": "user_id" }`
  - 409 worker already on this job's crew (`field: "user_id"`)
  - 409 crew full / job completed

### DELETE /assignments/{assignment_id}
- **Role:** Dispatcher, Admin
- **200:** `{ "message": "Assignment removed." }`
- **Errors:** 404, 409 if time has already been recorded for that worker on that job and date

---

## Time Entries

Each time entry in a response looks like:

```json
{
  "entry_id": 21, "user_id": 12, "worker_name": "Bishal Neupane", "trade": "Laborer",
  "job_id": 9, "job_title": "Level 4 drywall prep", "site_id": 1, "site_name": "Kirtipur Campus Expansion",
  "clock_in": "2026-10-01T07:00:00", "clock_out": "2026-10-01T11:30:00",
  "in_lat": 27.678046, "in_lng": 85.287895, "out_lat": 27.677956, "out_lng": 85.287895,
  "in_distance_m": 30.0, "out_distance_m": 20.0, "geofence_radius_m": 200,
  "hours": 4.5, "is_flagged": false, "flag_reason": null,
  "status": "Pending", "approved_by": null, "approved_by_name": null, "edit_reason": null
}
```

`hours` and the distances are **computed on every read**, never stored.

### GET /time-entries
- **Role:** Staff
- **Query:** `status` (`Pending`|`Approved`|`Rejected`), `flagged` (`true`/`false`), `worker` (user_id), `job_id`, `date` (clock-in date) — all optional
- **200:** `{ "time_entries": [ ... ] }` newest first

### POST /time-entries
- **Role:** Supervisor, Admin
- **Body:** `{ "user_id", "job_id", "clock_in", "in_lat", "in_lng", "clock_out"?, "out_lat"?, "out_lng"? }`
- **Rules (in order):** validate fields → worker active → **assigned to the job on the clock-in date** → no overlap → haversine distance to site → flag if beyond radius → **always save**.
- **201:** `{ "time_entry": { ... } }` (check `is_flagged` / `flag_reason`)
- **Errors:** 400 (`field` set), 404 worker/job, **409 not assigned** (`field: "user_id"`), 409 overlap (`field: "clock_in"`)

### PATCH /time-entries/{entry_id}/clock-out
- **Role:** Supervisor, Admin
- **Body:** `{ "clock_out", "out_lat", "out_lng" }`
- **200:** `{ "time_entry": { ... } }` — may now be flagged if clock-out was outside the geofence.
- **Errors:** 400 `clock_out` not after clock-in or shift > 24 h, 404, 409 already clocked out / overlaps next entry

### PATCH /time-entries/{entry_id}/approve
- **Role:** Supervisor, Admin
- **Body:** `{ "decision": "Approved" | "Rejected", "edit_reason": "Verified with foreman" }`
- **200:** `{ "time_entry": { ... } }` with `status`, `approved_by`, `edit_reason` set
- **Errors:** 400 invalid decision / missing reason / entry still open, 404, 409 already decided

---

## Reports

All report endpoints take optional `from` and `to` (`YYYY-MM-DD`, inclusive, filtering on
clock-in date; default = last 7 days through today). Only completed entries (with a clock-out)
count toward hours, and **Rejected entries are excluded**.

### GET /reports/hours-by-worker
- **Role:** Staff
- **200:** `{ "from", "to", "rows": [ { "user_id", "full_name", "trade", "entries", "total_hours", "approved_hours", "pending_hours", "flagged_entries" } ], "total_hours" }`
- `entries` counts only the entries that count toward hours; `flagged_entries` counts every flagged entry in range (any status, open or closed).

### GET /reports/hours-by-job
- **Role:** Staff
- **200:** `{ "from", "to", "rows": [ { "job_id", "title", "site_name", "scheduled_date", "status", "workers", "entries", "total_hours" } ], "total_hours" }`

### GET /reports/flagged
- **Role:** Staff
- **200:** `{ "from", "to", "rows": [ <time entry> ... ] }` — all flagged entries in range, any status.

### GET /reports/hours.csv
- **Role:** Staff
- **200:** `text/csv` attachment `fieldtrack-hours-<from>-to-<to>.csv` with columns
  `entry_id, worker, trade, job, site, clock_in, clock_out, hours, status, flagged, flag_reason, approved_by, edit_reason`

**Errors (all reports):** 400 invalid date, or `from` after `to`.

---

## Dashboard

### GET /dashboard
- **Role:** Staff
- **200:**
```json
{
  "date": "2026-10-01",
  "kpis": { "active_jobs": 3, "workers_clocked_in": 7, "hours_today": 31.5, "flagged_entries": 3 },
  "jobs_today": [ <job> ... ],
  "unassigned_workers": [ <user> ... ],
  "needs_attention": [ { "type": "flagged_entry" | "understaffed_job" | "open_overnight", "message": "...", "ref_id": 17 } ]
}
```
- `active_jobs` = jobs scheduled today that are not Completed; `workers_clocked_in` = workers with an open entry (no clock-out);
  `hours_today` includes open entries up to now and excludes Rejected; `flagged_entries` counts flagged entries that are still **Pending**
  (approved/rejected ones drop off), and `needs_attention` lists those same entries.

---

## Live Map (simulated GPS)

There is no mobile app yet, so worker positions are **simulated** (`backend/simulation.py`).
Every response is computed from the server clock: nothing is written to the database and no
background thread runs. Real time loops through a simulated **6:00–6:45 AM** commute window
every **5 real minutes**. Each worker assigned to a job today follows a fixed route for the
day (seeded by user_id + date) from a landmark a few km away, through up to 2 landmark
waypoints, to their job site, along the real road network. Near a traffic hotspot (Koteshwor,
Kalanki, Chabahil, Gongabu) they move at that junction's `speed_multiplier`. Departure times are
chosen (seeded by the date) so that about five workers are on the road or on site at every
moment, with the rest setting off during the window.

### GET /map/live
- **Role:** Staff
- **Query:** `route` (optional user_id) — also return that worker's remaining route as `path`
- **200:**
```json
{
  "sim_time": "6:42 AM",
  "cycle": 5970324,
  "job_sites": [
    { "id": 1, "name": "Kirtipur Campus Expansion", "address": "...", "lat": 27.677776, "lng": 85.287895,
      "radius_m": 200, "jobs_today": ["Level 4 framing"] }
  ],
  "workers": [
    { "id": 6, "name": "Sita Rai", "trade": "Electrician", "status": "In transit",
      "lat": 27.72041, "lng": 85.34712, "job_title": "Level 3 rough-in (electrical & plumbing)",
      "site_name": "Boudha Stupa Plaza Retrofit", "near_traffic": true, "hotspot": "Chabahil",
      "distance_remaining_m": 1240 }
  ]
}
```
- `status` is `Not started` (assigned today, hasn't left yet: `lat`/`lng` are `null`), `In transit`,
  `On site` (within ~30 m of the site centre), or `Off duty` (no assignment today: a fixed point
  near a landmark, shown greyed out and never moving).
- With `?route=<user_id>`, that worker (only) gets `"path": [[lat, lng], ...]` while `In transit`:
  the rest of their route along the roads, from their current position to the site. The map
  draws it as a white line when the worker is selected.
- `cycle` increases each time the simulated window restarts. The UI uses it to reset markers
  instead of animating them back to their start points.

### GET /map/sim-clock
- **Role:** Staff
- **200:** `{ "sim_time": "6:42 AM", "sim_minutes": 402.5, "window_start": "6:00 AM", "window_end": "6:45 AM", "cycle_seconds": 300, "cycle": 5970324, "seconds_to_reset": 137.4 }`
- `seconds_to_reset` = real seconds until the window restarts at 6:00 AM (drives the UI's "New cycle in" countdown).

### GET /map/bounds
- **Role:** Staff
- **200:** `{ "south": 27.6, "west": 85.2, "north": 27.8, "east": 85.45, "traffic_hotspots": [ { "name": "Koteshwor", "lat": 27.6775, "lng": 85.3485, "radius_m": 700, "speed_multiplier": 0.25 }, ... ] }`


## Safety / emergency
`GET /map/live` is **read-only**: it reports the current safety state but never changes it, however
often it is polled. Time-based escalation (idle timers, check-in windows, the configured random
accident roll) is advanced by **`POST /safety/tick`**, which the Live Map page calls once a second; it
returns the same body as `GET /map/live` (and accepts `?route=<user_id>`). Any staff role may tick,
because it only moves time forward. The `GET /map/live` response gains
`workers[].safety` (`state`, `checkin`, `elapsed_s`, `window_remaining_s`, `incapacitated`, `stopped`,
`on_break`, `break_zone`), `workers[].sim_status`, a worker `status` of `EMERGENCY`, `Post-incident` or
`Stopped` when applicable, and a top-level `safety` block: `{ config, seed, privacy_note, alerts[], notifications[] }`.
Each alert has `worker_id`, `worker_name`, `state`, `stage`, `level` (`warning`/`critical`/`info`),
`elapsed_s`, `window_remaining_s`, `location { lat, lng, label }` and `nearest_coworker`.

**Roles.** Reading (`GET /safety/config`, `GET /safety/audit`, `GET /map/live`) and `POST /safety/tick`: any
Staff. Every route that **changes** safety state (`accident`, `sos`, `respond`, `break`, `resolve`,
`return-to-duty`): **Supervisor or Admin only** — a Dispatcher gets **403** (checked before anything
else, so it is 403 even when an emergency exists), no token gets **401**. Errors use the usual
`{error, field}` shape (404 unknown worker, 409 wrong state).

| Route | Purpose |
|-------|---------|
| `GET /safety/config` | Active mode, thresholds, break zones, seed |
| `POST /safety/tick` | Advance the escalation to now; returns the live-map state (Staff) |
| `POST /safety/workers/{user_id}/accident` | Demo: worker stops and cannot reply (201) |
| `POST /safety/workers/{user_id}/sos` | Worker SOS: straight to EMERGENCY (201) |
| `POST /safety/workers/{user_id}/respond` | Worker replies "I'm OK" -> `{ok, cleared}` (409 if incapacitated) |
| `POST /safety/workers/{user_id}/break` | Body `{ "on_break": true }` |
| `POST /safety/workers/{user_id}/resolve` | Body `{ "outcome": "real_incident" \| "false_alarm", "note"?: str }` (409 unless in EMERGENCY) |
| `POST /safety/workers/{user_id}/return-to-duty` | Post-incident -> NORMAL |
| `GET /safety/audit` | Audit log, oldest first; `?worker_id=`, `?format=csv` or `json-file` for a download |
