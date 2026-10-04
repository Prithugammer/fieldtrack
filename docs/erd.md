# FieldTrack — Entity Relationship Diagram

```mermaid
erDiagram
    USERS ||--o{ JOBS : "creates (created_by)"
    USERS ||--o{ ASSIGNMENTS : "is assigned"
    USERS ||--o{ TIME_ENTRIES : "works (user_id)"
    USERS |o--o{ TIME_ENTRIES : "approves (approved_by)"
    USERS ||--o{ LOCATION_PINGS : "reports"
    JOB_SITES ||--o{ JOBS : "hosts"
    JOBS ||--o{ ASSIGNMENTS : "staffed by"
    JOBS ||--o{ TIME_ENTRIES : "charged to"

    USERS {
        int user_id PK
        string full_name
        string email UK
        string password_hash
        string phone
        string role
        string trade
        boolean is_active
    }

    JOB_SITES {
        int site_id PK
        string site_name
        string address
        float latitude
        float longitude
        int geofence_radius_m "DEFAULT 200"
    }

    JOBS {
        int job_id PK
        int site_id FK "-> job_sites"
        int created_by FK "-> users"
        string title
        text description
        date scheduled_date
        int crew_size
        string status "Scheduled | In progress | Completed"
    }

    ASSIGNMENTS {
        int assignment_id PK
        int job_id FK "-> jobs"
        int user_id FK "-> users"
        date work_date "UNIQUE with user_id"
        datetime assigned_at
    }

    TIME_ENTRIES {
        int entry_id PK
        int user_id FK "-> users (worker)"
        int job_id FK "-> jobs"
        datetime clock_in
        datetime clock_out "NULL while clocked in"
        float in_lat
        float in_lng
        float out_lat
        float out_lng
        boolean is_flagged
        string flag_reason
        string status "Pending | Approved | Rejected"
        int approved_by FK "-> users, NULLABLE"
        string edit_reason
    }

    LOCATION_PINGS {
        int ping_id PK
        int user_id FK "-> users"
        float latitude
        float longitude
        datetime recorded_at
    }
```

## Relationship notes

| Relationship | Cardinality | Explanation |
|--------------|-------------|-------------|
| job_sites → jobs | 1 : 0..N | A site can host many jobs over time; every job is at exactly one site. |
| users → jobs (created_by) | 1 : 0..N | The dispatcher/admin who created the job. |
| jobs → assignments | 1 : 0..N | A job is staffed by up to `crew_size` assignments. |
| users → assignments | 1 : 0..N | **At most one per work_date** — enforced by `UNIQUE(user_id, work_date)`; this is the double-booking rule at the database level. |
| users → time_entries (user_id) | 1 : 0..N | The worker whose time it is. |
| users → time_entries (approved_by) | 0..1 : 0..N | The supervisor who approved/rejected; NULL while Pending. |
| jobs → time_entries | 1 : 0..N | The job the time is charged to. |
| users → location_pings | 1 : 0..N | Every coordinate captured at clock-in/clock-out is logged as a ping for audit. |

**Normalisation:** all tables are in 3NF. No derived values are stored — in particular
*hours worked* is computed as `clock_out − clock_in` and *distance from site* is computed from
the stored coordinates on demand.
