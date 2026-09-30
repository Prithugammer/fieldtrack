# FieldTrack — Dispatch & Time Tracking

FieldTrack is the **administrative (office) side** of a dispatch and time-tracking system for a
construction services company. Dispatchers schedule jobs at geolocated job sites and assign
crews; supervisors record GPS-stamped time entries, which are **automatically flagged when the
clock-in/out location is outside the job site's geofence**, and approve or reject them with a
reason. Reports summarise hours by worker and by job, with CSV export for payroll.

Built for **PRG 100 — Systems Analysis & Design**.

| Key rule | Where it lives |
|----------|----------------|
| **Geofence** — distance > site radius ⇒ entry is saved *and* flagged | `backend/geofence.py`, `TimeEntry.apply_geofence()` in `backend/models.py` |
| **Double-booking** — one assignment per worker per day, else HTTP 409 | `backend/routes/assignments.py` + `UNIQUE(user_id, work_date)` in `models.py` |
| **Assignment rule** — time can only be recorded on a job the worker is assigned to that day | `backend/routes/time_entries.py` |
| **Computed hours** — never stored; `clock_out − clock_in` (works across midnight) | `TimeEntry.hours()` in `models.py` |

## Stack

| Layer | Technology |
|-------|------------|
| Backend | Python 3, Flask, Flask-SQLAlchemy, Flask-CORS, Flask-JWT-Extended, bcrypt, SQLite, pytest |
| Frontend | React 19 via Vite (JavaScript), react-router-dom, plain CSS with design tokens (no UI library) |
| Docs | Markdown + Mermaid diagrams in `docs/` |

The API runs on **http://localhost:5000**, the UI on **http://localhost:5173** (CORS allows only the UI origin).

## Project structure

```
FieldTrack/
├── docs/                   Analysis & design artifacts (requirements, DFD, use cases, ERD,
│                           data dictionary, class diagram, decision table, API spec)
├── backend/
│   ├── app.py              Flask app factory, blueprints, JSON error handlers
│   ├── config.py           SECRET_KEY, database URI, JWT expiry, GEOFENCE_RADIUS_M
│   ├── models.py           6 SQLAlchemy models
│   ├── auth.py             login, /me, @role_required decorator
│   ├── geofence.py         haversine() and should_flag() — pure functions
│   ├── validation.py       server-side input validation helpers
│   ├── routes/             users, sites, jobs, assignments, time_entries, reports, dashboard
│   ├── seed.py             resets the DB and loads demo data (dates relative to today)
│   └── tests/test_rules.py pytest business-rule tests
└── frontend/
    └── src/
        ├── api/client.js   one fetch wrapper (prefix /api, JWT, errors carry server message)
        ├── context/        AuthContext + ProtectedRoute
        ├── components/     Sidebar, TopBar, KpiCard, StatusChip, DataTable, Modal, FormField…
        ├── pages/          Login, Dashboard, Jobs, JobSites, Crew, TimeEntries, Reports
        └── styles/         tokens.css (design tokens) + global.css
```

## Setup

Requires **Python 3.10+** and **Node.js 20+**. Use two terminals.

### Terminal 1 — backend

**Windows (PowerShell):**
```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python seed.py
python app.py
```

**macOS / Linux:**
```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python seed.py
python app.py
```

The API is now on http://localhost:5000 (health check: http://localhost:5000/api/health).
The SQLite file is created at `backend/instance/fieldtrack.db`.

### Terminal 2 — frontend

```bash
cd frontend
npm install
npm run dev
```

Open **http://localhost:5173**.

### Run the tests

```bash
cd backend
pytest -v
```

19 tests cover: haversine accuracy against a known city pair, flagging at 199 m vs 201 m, a
shift crossing midnight, double-booking rejection, clock-out before clock-in rejection, the
role decorator blocking the wrong role, and a few more rules used in the demo.

### Reset the demo data

`python seed.py` (from `backend/`, with the venv active) wipes and reloads everything. Seed
dates are **relative to today** (jobs run yesterday, today and tomorrow), so **run it again
on the morning of the demo**.

## Demo logins

Login page has click-to-fill buttons for these.

| Role | Email | Password |
|------|-------|----------|
| Admin | `admin@fieldtrack.com` | `Admin123!` |
| Dispatcher | `dispatch@fieldtrack.com` | `Dispatch123!` |
| Dispatcher | `dispatch2@fieldtrack.com` | `Dispatch123!` |
| Supervisor | `supervisor@fieldtrack.com` | `Super123!` |

Workers (e.g. Marcus Reyes, Ben Okafor) are records only and cannot log in.

## Demo script (8 steps)

Run `python seed.py` first. On a fresh seed, **Ben Okafor** and **Jamal Carter** are
unassigned today (they worked last night's culvert shift), and **Marcus Reyes** is already on
*Level 4 framing* today.

1. **Create a job** — Sign in as **Dispatcher**. Go to **Jobs → New job**. Site: *Riverside
   Apartments - Phase 2*, title *Level 4 drywall prep*, date **today**, crew size **2** →
   **Create job**. (Try submitting it empty first to show the inline validation errors.)
2. **Assign** — On the new job click **Assign worker**, pick **Ben Okafor** → **Assign to
   job**. He appears under *Current crew*.
3. **Attempt a double booking** — In the same modal pick **Marcus Reyes** → **Assign to job**.
   The server answers **409** and the message appears under the field: *"Marcus Reyes is
   already assigned to 'Level 4 framing' … A worker can only be booked on one job per day."*
4. **Record an entry inside the geofence** — Sign out, sign in as **Supervisor**. Go to
   **Time Entries → Record time entry**. Worker **Ben Okafor**, clock-in **today 07:00**, job
   *Level 4 drywall prep*. The blue box shows the site is at 43.659100, −79.350300 with a
   200 m geofence. Click **On site (30 m)** (fills 43.659370, −79.350300). Set clock-out
   **today 11:30** and click **On site (30 m)** for the clock-out too → **Save entry**. Green
   banner: *"Clock-in was 30 m from … (inside the 200 m geofence)"*.
5. **Record an entry 500 m away** — **Record time entry** again: Ben Okafor, clock-in **today
   12:00**, same job, click **500 m away** (fills 43.663597, −79.350300); clock-out **today
   15:30**, **On site (30 m)** → **Save entry**. Amber banner: *"FLAGGED for review — Clock-in
   500 m from site (limit 200 m)"*. The row is highlighted amber but **was still saved**.
6. **View flagged** — Set the **Geofence** filter to **Flagged only** (or click *Review →* on
   the Dashboard's *Needs attention* list). All four flagged entries show with their reasons.
7. **Approve** — On Ben's 12:00 entry click **Approve**. Click **Approve** with no reason to
   show *"A reason is required"*, then type *"Foreman confirmed Ben was at the lay-down yard"*
   → **Approve**. The row now shows *Approved* plus the supervisor's name and reason.
8. **Reports + CSV** — Go to **Reports**. *Hours by worker* shows Ben with 3.50 h approved,
   *Hours by job* shows *Level 4 drywall prep* with 8.00 h, and *Flagged entries* lists every
   off-site punch. Change the date range and **Apply range**, then click **Download CSV**.

**Bonus talking points:** sign in as Dispatcher and try to approve — there is no Approve
button, and the API returns 403 (`@role_required`); *Culvert excavation & shoring (night)*
shows an 8.50 h shift from 19:00 to 03:30 the next day (hours computed across midnight).

## How the two key rules work (for explaining out loud)

**Geofence.** Every site has a centre point and a radius (default 200 m). When a time entry is
recorded, `haversine()` measures the distance along the Earth's surface between the worker's
GPS reading and the site centre. `should_flag(distance, radius)` returns `True` when distance
is **greater** than the radius (exactly 200 m counts as inside). A flagged entry is **still
saved**, because GPS drifts and the company must pay for time actually worked. It just gets a
reason like *"Clock-in 500 m from site (limit 200 m)"*, and a supervisor decides.

**Double-booking.** Before creating an assignment the API looks for *any* assignment the
worker already has on that work date. If one exists, it refuses with **HTTP 409 Conflict** and
names the existing job. The database also has a `UNIQUE(user_id, work_date)` constraint, so
the rule holds even if two dispatchers click at the same instant.

## Error format

Every API error is JSON: `{"error": "human-readable message", "field": "crew_size"}`. The UI
shows the message directly under the named field, or as a banner when `field` is `null`.
See `docs/api-spec.md` for every endpoint.
