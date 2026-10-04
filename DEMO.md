# FieldTrack — Demo Guide

Everything needed to present FieldTrack live. For what the project is and how it is built, see
[README.md](README.md). First-time setup (virtualenv, `npm install`) is in the README's
*Setup* section; this guide assumes it has been done once.

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

## Demo script (read from this)

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

## Demo logins

The login page has click-to-fill buttons for these.

| Role | Email | Password |
|------|-------|----------|
| Admin | `admin@fieldtrack.com` | `Admin123!` |
| Dispatcher | `dispatch@fieldtrack.com` | `Dispatch123!` |
| Dispatcher | `dispatch2@fieldtrack.com` | `Dispatch123!` |
| Supervisor | `supervisor@fieldtrack.com` | `Super123!` |

## If something goes wrong

- **Login says "Invalid email or password" for a demo account** — the database has not been
  seeded. Stop nothing; just run `python seed.py` in `backend/` and sign in again.
- **Pages show "Cannot reach the FieldTrack server"** — the backend in terminal 1 has stopped;
  start it again with `python app.py`.
- **Live Map looks empty or frozen** — check the *New cycle in* countdown: right after a
  restart most workers have not left yet. Wait 20–30 seconds.
