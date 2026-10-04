# FieldTrack — Data Flow Diagrams

Notation used below: **rectangles** are external entities, **rounded shapes** are processes,
**cylinders** are data stores (D1–D6, one per database table).

## 1. Context Diagram (Level-0 context)

The whole system is a single process. It shows everything that crosses the system boundary.

```mermaid
flowchart LR
    DISP[Dispatcher]
    SUP[Supervisor]
    ADM[Admin]

    SYS((0<br/>FieldTrack<br/>System))

    DISP -- "job site details, job details,<br/>crew assignments" --> SYS
    SYS -- "job schedule, double-booking warnings,<br/>unassigned workers" --> DISP

    SUP -- "time entries with GPS coordinates,<br/>clock-outs, approval decisions" --> SYS
    SYS -- "flagged entries, pending entries,<br/>hours reports, CSV export" --> SUP

    ADM -- "login credentials, user accounts,<br/>activation changes" --> SYS
    SYS -- "JWT session, user list,<br/>dashboard KPIs, reports" --> ADM
```

## 2. Level-0 DFD

The system decomposed into its six major processes and six data stores.

```mermaid
flowchart LR
    DISP[Dispatcher]
    SUP[Supervisor]
    ADM[Admin]

    P1(["1.0<br/>Manage Jobs"])
    P2(["2.0<br/>Assign Crew"])
    P3(["3.0<br/>Record Time"])
    P4(["4.0<br/>Approve Time"])
    P5(["5.0<br/>Generate Reports"])
    P6(["6.0<br/>Show Live Map"])

    D1[("D1 users")]
    D2[("D2 job_sites")]
    D3[("D3 jobs")]
    D4[("D4 assignments")]
    D5[("D5 time_entries")]
    D6[("D6 location_pings")]

    %% 1.0 Manage Jobs
    DISP -- "site & job details" --> P1
    ADM -- "user accounts, site & job details" --> P1
    P1 -- "user records" --> D1
    P1 -- "new/updated site" --> D2
    P1 -- "new/updated job" --> D3
    D2 -- "site list" --> P1
    P1 -- "job schedule" --> DISP

    %% 2.0 Assign Crew
    DISP -- "worker + job selection" --> P2
    D1 -- "active workers" --> P2
    D3 -- "job date & crew size" --> P2
    D4 -- "existing assignments for date" --> P2
    P2 -- "new assignment" --> D4
    P2 -- "409 double-booking message" --> DISP

    %% 3.0 Record Time
    SUP -- "clock-in/out time + coordinates" --> P3
    D4 -- "assignment check" --> P3
    D2 -- "site coords & geofence radius" --> P3
    P3 -- "time entry (flagged if outside)" --> D5
    P3 -- "coordinate ping" --> D6
    P3 -- "saved entry, distance, flag reason" --> SUP

    %% 4.0 Approve Time
    D5 -- "pending & flagged entries" --> P4
    SUP -- "decision + reason" --> P4
    P4 -- "status, approved_by, edit_reason" --> D5

    %% 5.0 Generate Reports
    ADM -- "date range" --> P5
    SUP -- "date range" --> P5
    D5 -- "entries in range" --> P5
    D1 -- "worker names & trades" --> P5
    D3 -- "job titles" --> P5
    P5 -- "hours by worker/job, flagged list, CSV" --> SUP
    P5 -- "dashboard KPIs, CSV" --> ADM

    %% 6.0 Show Live Map (positions simulated from the clock; nothing is written)
    D2 -- "site coords & geofence radius" --> P6
    D4 -- "today's assignments" --> P6
    D1 -- "active workers" --> P6
    P6 -- "sites + simulated worker positions" --> DISP
    P6 -- "sites + simulated worker positions" --> SUP
```

## 3. Process Descriptions

| Process | Input | Logic | Output |
|---------|-------|-------|--------|
| 1.0 Manage Jobs | Site and job details from the Dispatcher; user accounts from the Admin | Validate fields (coordinates in range, crew size 1–50, valid status, unique email). At level 0, maintaining the people and places that jobs need is treated as part of managing jobs. | Rows in D1 `users`, D2 `job_sites` and D3 `jobs` |
| 2.0 Assign Crew | Worker, job, work date | Worker must be active; crew not full; **worker has no other assignment that date** (double-booking rule) | Row in D4 `assignments`, or a 409 message |
| 3.0 Record Time | Worker, job, times, coordinates | Worker must be **assigned to that job that day**; no overlap; haversine distance to site; flag if distance > radius; always save | Row in D5 `time_entries` + rows in D6 `location_pings` |
| 4.0 Approve Time | Entry id, decision, reason | Entry must be Pending and clocked out; reason required | Updated status/approver in D5 |
| 5.0 Generate Reports | Date range | Sum computed hours (clock_out − clock_in), excluding rejected entries | Report tables and CSV file |
| 6.0 Show Live Map | Server clock | For each worker assigned today, compute a deterministic commute and the position at the current simulated time; read-only | Site pins with geofences and worker markers (no data store is written) |
