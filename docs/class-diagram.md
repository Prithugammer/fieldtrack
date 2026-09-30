# FieldTrack — Class Diagram

The SQLAlchemy model classes in `backend/models.py`, plus the pure-function `geofence`
module they use. Relationships are declared in both directions (`back_populates`).

```mermaid
classDiagram
    direction LR

    class User {
        +int user_id
        +str full_name
        +str email
        +str password_hash
        +str phone
        +str role
        +str trade
        +bool is_active
        +List~Job~ jobs_created
        +List~Assignment~ assignments
        +List~TimeEntry~ time_entries
        +List~TimeEntry~ approved_entries
        +List~LocationPing~ location_pings
        +set_password(plain) void
        +check_password(plain) bool
        +can_log_in() bool
        +to_dict() dict
    }

    class JobSite {
        +int site_id
        +str site_name
        +str address
        +float latitude
        +float longitude
        +int geofence_radius_m
        +List~Job~ jobs
        +distance_to(lat, lng) float
        +to_dict() dict
    }

    class Job {
        +int job_id
        +int site_id
        +int created_by
        +str title
        +str description
        +date scheduled_date
        +int crew_size
        +str status
        +JobSite site
        +User creator
        +List~Assignment~ assignments
        +List~TimeEntry~ time_entries
        +assigned_count() int
        +is_full() bool
        +to_dict(include_crew) dict
    }

    class Assignment {
        +int assignment_id
        +int job_id
        +int user_id
        +date work_date
        +datetime assigned_at
        +Job job
        +User worker
        +to_dict() dict
    }

    class TimeEntry {
        +int entry_id
        +int user_id
        +int job_id
        +datetime clock_in
        +datetime clock_out
        +float in_lat
        +float in_lng
        +float out_lat
        +float out_lng
        +bool is_flagged
        +str flag_reason
        +str status
        +int approved_by
        +str edit_reason
        +User worker
        +Job job
        +User approver
        +hours() float
        +hours_so_far(now) float
        +in_distance_m() float
        +out_distance_m() float
        +add_flag(reason) void
        +apply_geofence(lat, lng, label) float
        +to_dict() dict
    }

    class LocationPing {
        +int ping_id
        +int user_id
        +float latitude
        +float longitude
        +datetime recorded_at
        +User user
        +to_dict() dict
    }

    class geofence {
        <<module>>
        +haversine(lat1, lng1, lat2, lng2)$ float
        +should_flag(distance_m, radius_m)$ bool
    }

    User "1" --> "0..*" Job : creates
    User "1" --> "0..*" Assignment : is assigned
    User "1" --> "0..*" TimeEntry : works
    User "0..1" --> "0..*" TimeEntry : approves
    User "1" --> "0..*" LocationPing : reports
    JobSite "1" --> "0..*" Job : hosts
    Job "1" --> "0..*" Assignment : staffed by
    Job "1" --> "0..*" TimeEntry : charged to
    JobSite ..> geofence : uses
    TimeEntry ..> geofence : uses
```

## Method notes

| Class | Method | Purpose |
|-------|--------|---------|
| User | `set_password` / `check_password` | bcrypt hash and verify; the plain password is never stored. |
| User | `can_log_in` | True only for active Admin, Dispatcher or Supervisor accounts with a password. |
| JobSite | `distance_to(lat, lng)` | Haversine distance in metres from the site to a coordinate. |
| Job | `assigned_count` / `is_full` | Crew-size check used before creating an assignment. |
| TimeEntry | `hours` | `(clock_out − clock_in)` in hours; `None` while clocked in. Works across midnight because it subtracts full datetimes, not times. |
| TimeEntry | `hours_so_far(now)` | Hours for open entries up to `now` — used for "hours logged today". |
| TimeEntry | `apply_geofence(lat, lng, label)` | **The geofence rule**: haversine distance from the job site; if `should_flag(distance, radius)` it calls `add_flag` with e.g. "Clock-in 500 m from site (limit 200 m)". The entry is always kept. |
| TimeEntry | `add_flag(reason)` | Sets `is_flagged` and appends a reason (clock-in and clock-out can both add one). |
