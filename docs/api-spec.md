# FieldTrack — REST API Specification

- **Base URL:** `http://localhost:5000/api`
- **Format:** JSON request and response bodies (`Content-Type: application/json`), except the CSV export.
- **Authentication:** `Authorization: Bearer <JWT>` on every endpoint except login. Tokens expire after 8 hours.
- **Dates:** `YYYY-MM-DD`. **Datetimes:** `YYYY-MM-DDTHH:MM[:SS]` (local site time, no timezone).
- **Staff** below means any of `Admin`, `Dispatcher`, `Supervisor`.

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
| 403 | Authenticated, but the role is not allowed (or the account is deactivated). |
| 404 | The referenced record does not exist. |
| 409 | Business-rule conflict: double-booking, crew full, not assigned, overlap, already decided, duplicate email. |

---

## Auth

### POST /auth/login
- **Role:** public
- **Body:** `{ "email": "admin@fieldtrack.com", "password": "Admin123!" }`
- **200:** `{ "token": "<jwt>", "user": { "user_id": 1, "full_name": "Sarah Mitchell", "email": "...", "role": "Admin", ... } }` — JWT claims include `user_id` and `role`.
- **Errors:** 400 (`email`/`password` missing), 401 invalid credentials, 403 account deactivated or Worker account.

### GET /auth/me
- **Role:** any authenticated user
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
- **Body (any subset):** `{ "full_name", "phone", "role", "trade", "is_active", "password" }`
- **200:** `{ "user": { ... } }`
- **Errors:** 400, 404, 409 (admin tries to deactivate or demote their own account).

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
- **200:** `{ "jobs": [ { "job_id", "title", "description", "scheduled_date", "crew_size", "status", "site_id", "site_name", "created_by", "created_by_name", "assigned_count", "crew": [ { "assignment_id", "user_id", "full_name", "trade" } ] } ] }`
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
  - **409 double-booking** — `{ "error": "Marcus Reyes is already assigned to 'Framing – Level 4 walls' at Riverside Apartments - Phase 2 on 2026-10-01.", "field": "user_id" }`
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
  "entry_id": 21, "user_id": 12, "worker_name": "Ben Okafor", "trade": "Laborer",
  "job_id": 9, "job_title": "Level 4 drywall prep", "site_id": 1, "site_name": "Riverside Apartments - Phase 2",
  "clock_in": "2026-10-01T07:00:00", "clock_out": "2026-10-01T11:30:00",
  "in_lat": 43.6593, "in_lng": -79.35, "out_lat": 43.6592, "out_lng": -79.3501,
  "in_distance_m": 30.6, "out_distance_m": 20.3, "geofence_radius_m": 200,
  "hours": 4.5, "is_flagged": false, "flag_reason": null,
  "status": "Pending", "approved_by": null, "approved_by_name": null, "edit_reason": null
}
```

`hours` and the distances are **computed on every read**, never stored.

### GET /time-entries
- **Role:** Staff
- **Query:** `status` (`Pending`|`Approved`|`Rejected`), `flagged` (`true`/`false`), `worker` (user_id), `date` (clock-in date) — all optional
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
- `active_jobs` = jobs scheduled today that are not Completed; `hours_today` includes open entries up to now.
