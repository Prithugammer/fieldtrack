-- FieldTrack database schema (SQLite)
-- 6 tables, 3rd normal form. Run with: sqlite3 fieldtrack.db < schema.sql
PRAGMA foreign_keys = ON;

DROP VIEW  IF EXISTS v_latest_location;
DROP VIEW  IF EXISTS v_hours_by_worker;
DROP VIEW  IF EXISTS v_hours_by_job;
DROP VIEW  IF EXISTS v_flagged_entries;
DROP TABLE IF EXISTS location_pings;
DROP TABLE IF EXISTS time_entries;
DROP TABLE IF EXISTS assignments;
DROP TABLE IF EXISTS jobs;
DROP TABLE IF EXISTS job_sites;
DROP TABLE IF EXISTS users;

-- One table for all four roles (Admin, Dispatcher, Supervisor, Worker)
CREATE TABLE users (
    user_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name      TEXT    NOT NULL,
    email          TEXT    NOT NULL UNIQUE,
    password_hash  TEXT    NOT NULL,
    phone          TEXT,
    role           TEXT    NOT NULL CHECK (role IN ('Admin','Dispatcher','Supervisor','Worker')),
    trade          TEXT    CHECK (trade IN ('Carpenter','Operator','Laborer')),  -- workers only
    is_active      INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0,1)),
    created_at     TEXT    NOT NULL DEFAULT (datetime('now')),
    CHECK (role = 'Worker' OR trade IS NULL)
);

CREATE TABLE job_sites (
    site_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    site_name          TEXT    NOT NULL UNIQUE,
    address            TEXT    NOT NULL,
    latitude           REAL    NOT NULL CHECK (latitude  BETWEEN  -90 AND  90),
    longitude          REAL    NOT NULL CHECK (longitude BETWEEN -180 AND 180),
    geofence_radius_m  INTEGER NOT NULL DEFAULT 200 CHECK (geofence_radius_m > 0)
);

CREATE TABLE jobs (
    job_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    job_code        TEXT    NOT NULL UNIQUE,                 -- e.g. JOB-1042
    site_id         INTEGER NOT NULL REFERENCES job_sites(site_id),
    created_by      INTEGER NOT NULL REFERENCES users(user_id),   -- Dispatcher/Admin
    supervisor_id   INTEGER REFERENCES users(user_id),
    title           TEXT    NOT NULL,
    description     TEXT,
    scheduled_date  TEXT    NOT NULL,                        -- YYYY-MM-DD
    start_time      TEXT    NOT NULL,                        -- HH:MM
    end_time        TEXT    NOT NULL,                        -- HH:MM
    crew_size       INTEGER NOT NULL CHECK (crew_size > 0),
    status          TEXT    NOT NULL DEFAULT 'Scheduled'
                    CHECK (status IN ('Scheduled','In Progress','Completed')),
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    CHECK (end_time > start_time)
);

-- Resolves the many-to-many between users and jobs.
-- UNIQUE(user_id, work_date) = a worker cannot be double-booked on one day.
CREATE TABLE assignments (
    assignment_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id         INTEGER NOT NULL REFERENCES jobs(job_id)  ON DELETE CASCADE,
    user_id        INTEGER NOT NULL REFERENCES users(user_id),
    work_date      TEXT    NOT NULL,
    assigned_at    TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE (job_id,  user_id),
    UNIQUE (user_id, work_date)
);

CREATE TABLE time_entries (
    entry_id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id               INTEGER NOT NULL REFERENCES users(user_id),
    job_id                INTEGER NOT NULL REFERENCES jobs(job_id),
    clock_in              TEXT    NOT NULL,                  -- ISO datetime
    clock_out             TEXT,                              -- NULL = still clocked in
    in_lat                REAL    NOT NULL,
    in_lng                REAL    NOT NULL,
    out_lat               REAL,
    out_lng               REAL,
    distance_from_site_m  INTEGER NOT NULL CHECK (distance_from_site_m >= 0),
    is_flagged            INTEGER NOT NULL DEFAULT 0 CHECK (is_flagged IN (0,1)),
    status                TEXT    NOT NULL DEFAULT 'Pending'
                          CHECK (status IN ('Pending','Approved','Rejected')),
    approved_by           INTEGER REFERENCES users(user_id),
    approved_at           TEXT,
    edit_reason           TEXT,
    CHECK (clock_out IS NULL OR clock_out > clock_in),
    CHECK (status = 'Pending' OR approved_by IS NOT NULL)    -- decisions need a supervisor
);

CREATE TABLE location_pings (
    ping_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL REFERENCES users(user_id),
    latitude     REAL    NOT NULL,
    longitude    REAL    NOT NULL,
    recorded_at  TEXT    NOT NULL
);

-- Indexes on the columns the dashboard filters/joins by
CREATE INDEX idx_jobs_date        ON jobs(scheduled_date);
CREATE INDEX idx_assign_job       ON assignments(job_id);
CREATE INDEX idx_time_user        ON time_entries(user_id);
CREATE INDEX idx_time_job         ON time_entries(job_id);
CREATE INDEX idx_time_status      ON time_entries(status, is_flagged);
CREATE INDEX idx_ping_user_time   ON location_pings(user_id, recorded_at DESC);

-- Ready-made queries for the dashboard, reports and live map
CREATE VIEW v_flagged_entries AS
SELECT e.entry_id, u.full_name AS worker, j.job_code, s.site_name,
       e.distance_from_site_m, e.clock_in, e.status
FROM time_entries e
JOIN users u     ON u.user_id = e.user_id
JOIN jobs j      ON j.job_id  = e.job_id
JOIN job_sites s ON s.site_id = j.site_id
WHERE e.is_flagged = 1 AND e.status = 'Pending';

CREATE VIEW v_hours_by_worker AS
SELECT u.user_id, u.full_name,
       ROUND(SUM((julianday(e.clock_out) - julianday(e.clock_in)) * 24), 2) AS total_hours
FROM time_entries e JOIN users u ON u.user_id = e.user_id
WHERE e.clock_out IS NOT NULL
GROUP BY u.user_id;

CREATE VIEW v_hours_by_job AS
SELECT j.job_id, j.job_code,
       ROUND(SUM((julianday(e.clock_out) - julianday(e.clock_in)) * 24), 2) AS total_hours
FROM time_entries e JOIN jobs j ON j.job_id = e.job_id
WHERE e.clock_out IS NOT NULL
GROUP BY j.job_id;

CREATE VIEW v_latest_location AS
SELECT p.user_id, p.latitude, p.longitude, p.recorded_at
FROM location_pings p
WHERE p.recorded_at = (SELECT MAX(recorded_at) FROM location_pings WHERE user_id = p.user_id);
