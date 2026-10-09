# FieldTrack — Data Dictionary

Types are the SQLAlchemy/SQLite types used in `backend/models.py`. "Size" is the maximum
length for strings. All validation rules are enforced on the server (in the route handlers
and, where noted, by a database constraint).

## users

| Field | Type | Size | Required | Validation rule | Example |
|-------|------|------|----------|-----------------|---------|
| user_id | Integer | — | Yes (PK, auto) | Auto-increment primary key | `5` |
| full_name | String | 100 | Yes | 2–100 characters, trimmed | `Ramesh Karki` |
| email | String | 120 | Yes | 5–120 characters, valid email format; **UNIQUE**; stored lower-case | `ramesh.karki@fieldtrack.com` |
| password_hash | String | 128 | Staff only | bcrypt hash of a password ≥ 8 characters; required for Admin/Dispatcher/Supervisor, NULL for Workers (they do not log in) | `$2b$12$Kx…` |
| phone | String | 20 | No | Digits, spaces, `+ - ( ) .` only; 7–20 characters | `416-555-0142` |
| role | String | 20 | Yes | One of `Admin`, `Dispatcher`, `Supervisor`, `Worker` (CHECK constraint) | `Worker` |
| trade | String | 50 | Workers only | Required when role = Worker; 2–50 characters | `Carpenter` |
| is_active | Boolean | — | Yes | Default `true`; inactive users cannot log in or be assigned | `true` |

## job_sites

| Field | Type | Size | Required | Validation rule | Example |
|-------|------|------|----------|-----------------|---------|
| site_id | Integer | — | Yes (PK, auto) | Auto-increment primary key | `1` |
| site_name | String | 120 | Yes | 2–120 characters | `Kirtipur Campus Expansion` |
| address | String | 200 | Yes | 5–200 characters | `Kirtipur Municipality-3, Kathmandu 44618` |
| latitude | Float | — | Yes | −90.0 to 90.0 | `27.677776` |
| longitude | Float | — | Yes | −180.0 to 180.0 | `85.287895` |
| geofence_radius_m | Integer | — | Yes | 25–5000 metres; **DEFAULT 200** | `200` |

## jobs

| Field | Type | Size | Required | Validation rule | Example |
|-------|------|------|----------|-----------------|---------|
| job_id | Integer | — | Yes (PK, auto) | Auto-increment primary key | `4` |
| site_id | Integer | — | Yes (FK → job_sites) | Must reference an existing site | `1` |
| created_by | Integer | — | Yes (FK → users) | Set from the logged-in user's JWT, never from the request body | `2` |
| title | String | 120 | Yes | 3–120 characters | `Level 4 framing` |
| description | Text | 1000 | No | ≤ 1000 characters | `Frame and sheath north and east walls.` |
| scheduled_date | Date | — | Yes | ISO date `YYYY-MM-DD` | `2026-10-01` |
| crew_size | Integer | — | Yes | 1–50; cannot be reduced below the number of current assignments | `3` |
| status | String | 20 | Yes | One of `Scheduled`, `In progress`, `Completed` (CHECK); default `Scheduled` | `In progress` |

## assignments

| Field | Type | Size | Required | Validation rule | Example |
|-------|------|------|----------|-----------------|---------|
| assignment_id | Integer | — | Yes (PK, auto) | Auto-increment primary key | `12` |
| job_id | Integer | — | Yes (FK → jobs) | Must reference an existing job that is not Completed and whose crew is not full | `4` |
| user_id | Integer | — | Yes (FK → users) | Must be an **active Worker** | `5` |
| work_date | Date | — | Yes | Defaults to the job's `scheduled_date`. **UNIQUE(user_id, work_date)** — the double-booking rule | `2026-10-01` |
| assigned_at | DateTime | — | Yes | Set by the server when the assignment is created | `2026-09-30 14:02:11` |

## time_entries

| Field | Type | Size | Required | Validation rule | Example |
|-------|------|------|----------|-----------------|---------|
| entry_id | Integer | — | Yes (PK, auto) | Auto-increment primary key | `21` |
| user_id | Integer | — | Yes (FK → users) | Active Worker **assigned to `job_id` on the clock-in date** | `5` |
| job_id | Integer | — | Yes (FK → jobs) | Must reference an existing job | `4` |
| clock_in | DateTime | — | Yes | ISO datetime `YYYY-MM-DDTHH:MM`; must not overlap another entry for the worker | `2026-10-01T07:00` |
| clock_out | DateTime | — | No | NULL while clocked in; must be **after** clock_in (may be the next calendar day); shift ≤ 24 h | `2026-10-01T15:30` |
| in_lat | Float | — | Yes | −90.0 to 90.0 | `27.678046` |
| in_lng | Float | — | Yes | −180.0 to 180.0 | `85.287895` |
| out_lat | Float | — | With clock_out | −90.0 to 90.0; required when clock_out is given | `27.677956` |
| out_lng | Float | — | With clock_out | −180.0 to 180.0; required when clock_out is given | `85.287895` |
| is_flagged | Boolean | — | Yes | Set by the server: `true` if clock-in or clock-out distance > site geofence radius | `false` |
| flag_reason | String | 255 | No | Set by the server when flagged | `Clock-in 500 m from site (limit 200 m)` |
| status | String | 20 | Yes | One of `Pending`, `Approved`, `Rejected` (CHECK); default `Pending` | `Approved` |
| approved_by | Integer | — | No (FK → users) | Set by the server to the Supervisor/Admin who decided; NULL while Pending | `4` |
| edit_reason | String | 255 | With decision | 3–255 characters; required when approving or rejecting | `Verified with site foreman` |

**Computed (not stored):** `hours = (clock_out − clock_in)` in hours, rounded to 2 decimals;
`in_distance_m` / `out_distance_m` = haversine distance from the job site.

## location_pings

| Field | Type | Size | Required | Validation rule | Example |
|-------|------|------|----------|-----------------|---------|
| ping_id | Integer | — | Yes (PK, auto) | Auto-increment primary key | `40` |
| user_id | Integer | — | Yes (FK → users) | Worker the coordinate belongs to | `5` |
| latitude | Float | — | Yes | −90.0 to 90.0 | `27.678046` |
| longitude | Float | — | Yes | −180.0 to 180.0 | `85.287895` |
| recorded_at | DateTime | — | Yes | Timestamp of the clock-in or clock-out the ping came from | `2026-10-01T07:00:00` |
