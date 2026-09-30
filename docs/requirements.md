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
| FR-03 | An Admin shall be able to create users, edit their name, phone, role and trade, and activate or deactivate them. Email addresses shall be unique. |
| FR-04 | A Dispatcher or Admin shall be able to create and edit job sites with a name, address, latitude, longitude and geofence radius (default 200 m). |
| FR-05 | A Dispatcher or Admin shall be able to create and edit jobs (site, title, description, scheduled date, crew size, status) and list them filtered by date and status. Job status shall be one of *Scheduled*, *In progress*, *Completed*. |
| FR-06 | A Dispatcher or Admin shall be able to assign an active worker to a job for its work date and remove an assignment. An assignment shall be refused when the job's crew is already full. |
| FR-07 | The system shall prevent double-booking: a worker may hold at most one assignment per work date. A conflicting request shall be rejected with HTTP 409 and a message naming the existing job. |
| FR-08 | A Supervisor or Admin shall be able to record a time entry for a worker, including clock-in time and GPS coordinates. The entry shall be rejected (HTTP 409) if the worker is not assigned to that job on that date, or if it overlaps another entry for the same worker. |
| FR-09 | For every recorded clock-in and clock-out, the system shall compute the distance from the job site using the haversine formula. If the distance exceeds the site's geofence radius the entry shall be saved **and** flagged with a human-readable reason. Entries are never discarded for being outside the geofence. |
| FR-10 | A Supervisor or Admin shall be able to record a clock-out (time and coordinates). Clock-out must be after clock-in; shifts that cross midnight shall be supported. Hours worked shall always be computed from clock-in/clock-out and never stored. |
| FR-11 | A Supervisor or Admin shall be able to approve or reject a completed time entry with a mandatory reason. The system shall record who made the decision. A decided entry cannot be decided again. |
| FR-12 | The system shall provide a dashboard (active jobs, workers clocked in, hours today, flagged entries) and reports of hours by worker, hours by job and flagged entries for a date range, with CSV export of the underlying time entries. |

## 4. Non-Functional Requirements

| ID     | Category        | Requirement |
|--------|-----------------|-------------|
| NFR-01 | Security        | Passwords shall be stored only as bcrypt hashes. API access shall require a JWT that expires after 8 hours. All input shall be validated on the server regardless of client-side checks. |
| NFR-02 | Usability       | Every validation error shall be returned as JSON `{"error": ..., "field": ...}` so the UI can display it inline next to the offending field. Every page shall show loading and empty states. |
| NFR-03 | Performance     | With the demo dataset, every API request shall complete in under 500 ms on a standard laptop. |
| NFR-04 | Data integrity  | The database shall enforce primary keys, foreign keys, unique email, one assignment per worker per day, and allowed status values. Derived values (hours) shall never be stored. |
| NFR-05 | Maintainability | The backend shall be organised into Flask blueprints with a docstring on every route; business rules (geofence, double-booking) shall be isolated and covered by automated pytest tests. |
| NFR-06 | Portability     | The system shall run locally on Windows, macOS or Linux with Python 3 and Node.js, using a file-based SQLite database and any modern browser. |

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
