# FieldTrack — Dispatch & Time Tracking

## Day-of checklist

1. **Run `python seed.py` the morning of the demo** (it's in step 2). Seed dates are relative to
   today, so an older seed won't have today's jobs.
2. **Start the backend** (PowerShell, terminal 1, from the project folder):
   ```powershell
   cd backend
   .venv\Scripts\Activate.ps1
   python seed.py
   python app.py
   ```
   If activation is blocked, skip it and run `.venv\Scripts\python.exe seed.py` then
   `.venv\Scripts\python.exe app.py`.
3. **Start the frontend** (PowerShell, terminal 2, from the project folder):
   ```powershell
   cd frontend
   npm run dev
   ```
4. **Open:** app **http://localhost:5173**, API health check **http://localhost:5000/api/health**.
   The login page has click-to-fill buttons for every demo account.

### Demo script (read from this)

On a fresh seed, **Ben Okafor** is unassigned today and **Marcus Reyes** is already on
*Level 4 framing* today.

1. **Log in as Dispatcher.** Click the *Dispatcher* demo button → **Sign in**.
2. **Create a job.** **Jobs → New job**. Optional: click **Create job** empty first to show the
   inline *"Job site is required."* Then set site *Kirtipur Campus Expansion*, title
   *Level 4 drywall prep*, date **today**, crew size **2** → **Create job**.
3. **Assign a worker.** On *Level 4 drywall prep* click **Assign worker** → **Ben Okafor** →
   **Assign to job**. Ben appears under *Current crew*. Click **Done**.
4. **Double-booking (409).** On *Level 4 framing* (also today) click **Assign worker** →
   **Ben Okafor** → **Assign to job**. Under the Worker field: *"Ben Okafor is already assigned
   to 'Level 4 drywall prep' … A worker can only be booked on one job per day."*
   (Alternative: Marcus Reyes on the new job names *Level 4 framing* instead.)
5. **Inside the geofence.** **Sign out** → *Supervisor* → **Sign in**. **Time Entries → Record
   time entry**: Ben Okafor, clock-in **today 07:00**, job *Level 4 drywall prep*. Click **On site
   (30 m)**, set clock-out **today 11:30**, click the second **On site (30 m)** → **Save entry**.
   Green banner: *"Clock-in was 30 m from … (inside the 200 m geofence)"*. The row is not flagged.
6. **500 m away.** **Record time entry**: Ben Okafor, clock-in **today 12:00**, same job, click
   **500 m away**; clock-out **today 15:30**, **On site (30 m)** → **Save entry**. Amber banner:
   *"FLAGGED for review — Clock-in 500 m from site (limit 200 m)"*. The entry is still saved.
7. **Review and approve.** Set **Geofence → Flagged only**: 4 amber rows. On Ben's 12:00 row
   click **Approve**, then **Approve** with no reason: *"A reason is required for the audit
   trail."* Type *"Foreman confirmed Ben was at the lay-down yard"* → **Approve**. The row shows
   *Approved* plus *Greg Hanson: "…"*.
8. **Reports and CSV.** **Reports**: *Hours by worker* shows Ben with **3.50 h** approved, *Hours
   by job* shows *Level 4 drywall prep* at **8.00 h** (1 worker, 2 entries), and *Flagged
   entries* lists 4. Click **Download CSV** and open it. It has the same entries, hours and
   approvals.
9. **Live Map.** Click **Live Map**. Point out the *Simulated time* label at the top right:
   this stands in for the mobile app's live GPS, replaying a compressed 6:00–7:15 AM commute
   every 5 minutes. The *New cycle in m:ss* countdown next to it shows when the morning
   restarts. If it's under ~0:30, wait for the restart (markers fade out and back in) before
   pointing things out. Point at an amber worker gliding toward a site, and click it to show
   the job and distance left (slow workers in traffic are easier to click than fast ones). If a
   worker has an orange ring, click it to show *"Delayed near Chabahil"* (or another junction):
   traffic hotspots slow workers down. Each site is a small dot inside its orange geofence
   circle. Green workers are on site, and when several share a site they fan out around its dot
   so each can be clicked. Ben, assigned in step 3, is no longer Off duty: he now has a route
   to Kirtipur. If you zoom or drag too far, **Reset view** (top right of the map) brings it back.

**Bonus talking points:** as Dispatcher there is no Approve button, and the API returns 403
(`@role_required`). *Culvert excavation & shoring (night)* has Jamal's 8.50 h shift from 19:00
to 03:30 the next day (hours computed across midnight).

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
│   ├── kathmandu_geo.py    valley bounds, landmarks, traffic hotspots for the Live Map
│   ├── simulation.py       simulated worker GPS (pure, clock-based: no writes, no threads)
│   ├── validation.py       server-side input validation helpers
│   ├── routes/             users, sites, jobs, assignments, time_entries, reports, dashboard, map
│   ├── seed.py             resets the DB and loads demo data (dates relative to today)
│   └── tests/              test_rules.py (business rules), test_map.py (Live Map simulation)
└── frontend/
    └── src/
        ├── api/client.js   one fetch wrapper (prefix /api, JWT, errors carry server message)
        ├── context/        AuthContext + ProtectedRoute
        ├── components/     Sidebar, TopBar, KpiCard, StatusChip, DataTable, Modal, FormField…
        ├── pages/          Login, Dashboard, Jobs, LiveMap, JobSites, Crew, TimeEntries, Reports
        └── styles/         tokens.css (design tokens) + global.css + live-map.css
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

26 tests cover: haversine accuracy against a known city pair, flagging at 199 m vs 201 m, a
shift crossing midnight, double-booking rejection, clock-out before clock-in rejection, the
role decorator blocking the wrong role, a few more rules used in the demo, and the Live Map
simulation (repeatable routes, someone always moving, traffic slowdown, read-only endpoint).

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

The 8-step demo script is in the [Day-of checklist](#day-of-checklist) at the top of this file.

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
