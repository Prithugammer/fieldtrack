# FieldTrack — Requirements Specification

**Project:** FieldTrack — Administrative Dispatch & Time Tracking
**Course:** PRG 100 — Systems Analysis & Design
**Scope:** Administrative (office) side only. Workers are managed as records; they do not log in.

## 1. Problem Statement

A construction services company dispatches crews to job sites and tracks their hours. The
current software is outdated: it has no idea *where* a worker was when they clocked in, it
allows a worker to be booked on two jobs on the same day, and payroll hours are typed in by
hand. FieldTrack replaces it with a web application that:

- schedules jobs at geolocated job sites,
- assigns workers to jobs while preventing double-booking,
- records time entries with GPS coordinates and automatically **flags** entries recorded
  outside the job site's geofence,
- routes entries through a supervisor approval step, and
- reports hours by worker and by job, with CSV export for payroll.

## 2. Stakeholders and Roles

| Role        | Logs in? | Responsibilities |
|-------------|----------|------------------|
| Admin       | Yes      | Manages user accounts and everything else in the system. |
| Dispatcher  | Yes      | Maintains job sites and jobs, assigns crews. |
| Supervisor  | Yes      | Records time entries, reviews flagged entries, approves/rejects time. |
| Worker      | No       | Field employee. Exists as a record that is assigned and has time recorded. |

## 3. Functional Requirements

| ID    | Requirement |
|-------|-------------|
| FR-01 | The system shall authenticate staff users (Admin, Dispatcher, Supervisor) by email and password and issue a signed JWT that carries the user's id and role. Workers and deactivated users shall be refused. |
| FR-02 | The system shall restrict every API endpoint to the roles permitted for it and return HTTP 403 when a user with the wrong role attempts an action. |
| FR-03 | An Admin shall be able to create users, edit their name, email, phone, role, trade and password, and activate or deactivate them. Email addresses shall be unique. |
| FR-04 | A Dispatcher or Admin shall be able to create and edit job sites with a name, address, latitude, longitude and geofence radius (default 200 m). |
| FR-05 | A Dispatcher or Admin shall be able to create and edit jobs (site, title, description, scheduled date, crew size, status) and list them filtered by date and status. Job status shall be one of *Scheduled*, *In progress*, *Completed*. |
| FR-06 | A Dispatcher or Admin shall be able to assign an active worker to a job for its work date and remove an assignment. An assignment shall be refused when the job's crew is already full. |
| FR-07 | The system shall prevent double-booking: a worker may hold at most one assignment per work date. A conflicting request shall be rejected with HTTP 409 and a message naming the existing job. |
| FR-08 | A Supervisor or Admin shall be able to record a time entry for a worker, including clock-in time and GPS coordinates. The entry shall be rejected (HTTP 409) if the worker is not assigned to that job on that date, or if it overlaps another entry for the same worker. |
| FR-09 | For every recorded clock-in and clock-out, the system shall compute the distance from the job site using the haversine formula. If the distance exceeds the site's geofence radius the entry shall be saved **and** flagged with a human-readable reason. Entries are never discarded for being outside the geofence. |
| FR-10 | A Supervisor or Admin shall be able to record a clock-out (time and coordinates). Clock-out must be after clock-in; shifts that cross midnight shall be supported. Hours worked shall always be computed from clock-in/clock-out and never stored. |
| FR-11 | A Supervisor or Admin shall be able to approve or reject a completed time entry with a mandatory reason. The system shall record who made the decision. A decided entry cannot be decided again. |
| FR-12 | The system shall provide a dashboard (active jobs, workers clocked in, hours today, flagged entries) and reports of hours by worker, hours by job and flagged entries for a date range, with CSV export of the underlying time entries. |
| FR-13 | The system shall show a live map of every job site (with its geofence) and of each worker's position. Until a mobile app supplies real GPS, positions shall be **simulated** deterministically from the server clock and clearly labelled as simulated. |

## 4. Non-Functional Requirements

| ID     | Category        | Requirement |
|--------|-----------------|-------------|
| NFR-01 | Security        | Passwords shall be stored only as bcrypt hashes. API access shall require a JWT that expires after 8 hours. All input shall be validated on the server regardless of client-side checks. |
| NFR-02 | Usability       | Every validation error shall be returned as JSON `{"error": ..., "field": ...}` so the UI can display it inline next to the offending field. Every page shall show loading and empty states. |
| NFR-03 | Performance     | With the demo dataset, every API request shall complete in under 500 ms on a standard laptop. |
| NFR-04 | Data integrity  | The database shall enforce primary keys, foreign keys, unique email, one assignment per worker per day, and allowed status values. Derived values (hours) shall never be stored. |
| NFR-05 | Maintainability | The backend shall be organised into Flask blueprints with a docstring on every route; business rules (geofence, double-booking) shall be isolated and covered by automated pytest tests. |
| NFR-06 | Portability     | The system shall run locally on Windows, macOS or Linux with Python 3 and Node.js, using a file-based SQLite database and any modern browser. |
| NFR-07 | Configuration   | Secrets, the database URL, token lifetime and allowed CORS origins shall come from environment variables (with local defaults), and debug mode shall be off unless explicitly enabled. |

## 5. User Stories

| #     | User story |
|-------|------------|
| US-01 | As an **Admin**, I want to create user accounts with a role and trade so that each person has the right access and can be dispatched by skill. |
| US-02 | As an **Admin**, I want to deactivate a user so that people who have left the company can no longer log in or be assigned. |
| US-03 | As a **Dispatcher**, I want to register job sites with GPS coordinates and a geofence radius so that clock-ins can be checked against the real location. |
| US-04 | As a **Dispatcher**, I want to create jobs with a date and crew size so that I can plan each day's work. |
| US-05 | As a **Dispatcher**, I want to filter jobs by date and status so that I can see what is happening on a given day. |
| US-06 | As a **Dispatcher**, I want to assign a worker to a job so that the crew knows where to go. |
| US-07 | As a **Dispatcher**, I want to be warned immediately if a worker is already booked that day so that I never send one person to two sites. |
| US-08 | As a **Supervisor**, I want to record a clock-in with coordinates so that attendance is captured with proof of location. |
| US-09 | As a **Supervisor**, I want entries recorded away from the site to be flagged automatically so that I only have to investigate the suspicious ones. |
| US-10 | As a **Supervisor**, I want to approve or reject time entries with a reason so that payroll only pays verified hours and there is an audit trail. |
| US-11 | As a **Supervisor**, I want to see hours by worker and by job for a date range so that I can check labour cost against the plan. |
| US-12 | As an **Admin**, I want to export hours as CSV so that payroll can import them without re-typing. |
| US-13 | As a **Dispatcher**, I want to see on a map where my crews are and whether anyone is delayed so that I can react before a job falls behind. |

## 6. Traceability (story → requirement)

| Story | Requirement(s) |
|-------|----------------|
| US-01, US-02 | FR-01, FR-02, FR-03 |
| US-03 | FR-04, FR-09 |
| US-04, US-05 | FR-05 |
| US-06 | FR-06 |
| US-07 | FR-07 |
| US-08 | FR-08, FR-10 |
| US-09 | FR-09 |
| US-10 | FR-11 |
| US-11 | FR-12 |
| US-12 | FR-12 |
| US-13 | FR-13 |

## 7. Safety and emergency monitoring (added after the first release)

> **Status of this section.** The safety module was built and documented in the README and API spec before it
> had any entry in these analysis documents. The requirements below were **written down from the implemented,
> tested behaviour** on 2026-10-11 so the analysis matches the system. They have **not** been approved by a
> stakeholder; items marked **DECISION NEEDED** are open product decisions, not agreed requirements.

Scope: workers on shift are watched for inactivity ("man-down"). All worker behaviour is **simulated** (there
is no mobile app), and all notifications are **mock** (nobody is called or texted).

### 7.1 Functional requirements

| ID | Requirement |
|----|-------------|
| FR-14 | The system shall treat a worker as *on shift* while the Live Map shows them *In transit* or *On site*, and shall watch only on-shift workers. A worker on a break, inside a configured rest area, or off shift shall never be flagged. |
| FR-15 | A worker who has not moved more than `idle_distance_tolerance_m` (15 m) for `idle_threshold_seconds` (600 s; demo preset 15 s) shall receive safety check-in 1 and a *warning* shall be raised for supervisors. |
| FR-16 | Each unanswered check-in shall be followed, after `checkin_response_window_seconds` (120 s; demo 5 s), by the next check-in, up to `num_checkins` (3). An unanswered last check-in shall put the worker in **EMERGENCY**. So the emergency is declared `idle + num_checkins × window` after the worker stopped (960 s; demo preset 30 s). Each transition is timestamped with the moment it was *due*. |
| FR-17 | Declaring an EMERGENCY shall alert supervisors at *critical* level and place a **mock** call to emergency services, once. An EMERGENCY shall stay locked (no automatic change) until a Supervisor or Admin resolves it. |
| FR-18 | A worker's reply "I'm OK" (or moving again) during a check-in shall cancel it and restart idle timing. A reply after the emergency is declared shall not clear it. |
| FR-19 | A Supervisor or Admin shall resolve an EMERGENCY as *false alarm* (worker returns to normal) or *real incident* (worker is held *Post-incident*, kept visible and not re-escalated, until a Supervisor or Admin returns them to duty). A note up to 500 characters may be recorded. |
| FR-20 | Every safety event (idle detected, each check-in, replies, accident, SOS, mock call, resolution with note and actor, break start/end) shall be written to an audit log that can be viewed and exported as CSV/JSON. |
| FR-21 | **Escalation shall not depend on any browser being open.** The server advances it by itself (heartbeat, once a second). |
| FR-22 | **Open safety state shall survive a server restart.** Open check-ins, EMERGENCY and Post-incident states, stopped/break flags, the audit log and the message feed are saved in the database after every change and restored at start-up. A restart shall not repeat an event that already happened, nor drop an open emergency. |
| FR-23 | If a Supervisor/Admin action cannot be saved, it shall be **refused** (HTTP 503, nothing changed) rather than appear to succeed. If the heartbeat cannot save, it shall keep the state in memory, retry every second and show a warning on the Live Map. |
| FR-24 | If a job site is outside the supported road network the Live Map shall keep working; its workers are shown as "Route unavailable" and are not monitored (they have no simulated position). |

### 7.2 Roles and permissions (as implemented)

| Action | Admin | Supervisor | Dispatcher | Worker |
|--------|:-----:|:----------:|:----------:|:------:|
| View Live Map, alerts, messages, audit log, safety config | yes | yes | yes | no (cannot sign in) |
| Trigger accident / SOS / "I'm OK" / break (simulation controls) | yes | yes | no | – |
| Resolve an EMERGENCY, return a worker to duty | yes | yes | no | – |
| Run one heartbeat tick on demand (`POST /api/safety/tick`) | yes | yes | yes | – |

**DECISION NEEDED (D-21):** which roles may press the simulation controls was chosen during implementation; only
"a supervisor closes an emergency" appears in the original README. Confirm or change.

### 7.3 Non-functional requirements for the safety module

| ID | Category | Requirement |
|----|----------|-------------|
| NFR-08 | Reliability | Every safety transition is idempotent for a given time: repeated or concurrent ticks never repeat an event. Only one process may run the heartbeat (a database lease); a second process stays idle and takes over if the first stops. |
| NFR-09 | Recoverability | After a restart, escalation continues on its original schedule. Idle time accumulated by a worker who had **not yet** reached check-in 1 is **not** saved (their idle timer restarts). |
| NFR-10 | Observability | `GET /api/map/live` reports `safety.monitoring`: last tick, whether the heartbeat is running, and whether saving works. Failures to save are logged once, then once a minute. |
| NFR-11 | Retention | **DECISION NEEDED:** how long audit and location-related safety records are kept. Currently nothing is deleted (only the most recent 5,000 audit entries and 300 messages are loaded into memory at start-up). |

### 7.4 Failure states and recovery

| Situation | Behaviour |
|-----------|-----------|
| Server stopped or crashed while an EMERGENCY is open | The emergency is in the database; after restart it is shown again with its original timestamps, no second alert or call is made. While the server is down nothing escalates (there is no external watchdog). |
| Database unavailable at start-up | The server refuses to start (starting empty would hide a real incident). |
| Database unavailable while running | Operator actions: 503 and unchanged. Heartbeat: state kept in memory, retried every second, warning shown. A restart *during* that outage loses the unsaved events. |
| Two server processes on one database | Only the lease holder escalates; the other is idle and reloads saved state if it takes over. **Running two processes is still not supported**: the idle one serves stale map data. |
| Saved row unreadable | That worker's state is skipped and logged; the server starts. |
