"""SQLAlchemy models — the six FieldTrack tables.

Relationships are declared in both directions with back_populates so you can navigate
e.g. job.assignments and assignment.job.

Hours are NEVER stored. TimeEntry.hours() computes them from clock_in and clock_out each
time they are needed, so they can never drift out of sync with the times.
"""

from datetime import datetime

import bcrypt
from sqlalchemy import CheckConstraint, UniqueConstraint

from extensions import db
from geofence import haversine, should_flag

ROLES = ("Admin", "Dispatcher", "Supervisor", "Worker")
STAFF_ROLES = ("Admin", "Dispatcher", "Supervisor")
JOB_STATUSES = ("Scheduled", "In progress", "Completed")
ENTRY_STATUSES = ("Pending", "Approved", "Rejected")


def _in_list(column, values):
    """Build an SQL CHECK expression like: role IN ('Admin', 'Worker')."""
    quoted = ", ".join("'" + v + "'" for v in values)
    return f"{column} IN ({quoted})"


def _iso(value):
    return value.isoformat() if value else None


class User(db.Model):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint(_in_list("role", ROLES), name="ck_users_role"),)

    user_id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), nullable=False, unique=True)
    # NULL for Workers — they are records only and never log in.
    password_hash = db.Column(db.String(128), nullable=True)
    phone = db.Column(db.String(20))
    role = db.Column(db.String(20), nullable=False)
    trade = db.Column(db.String(50))
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    jobs_created = db.relationship("Job", back_populates="creator")
    assignments = db.relationship("Assignment", back_populates="worker")
    time_entries = db.relationship(
        "TimeEntry", back_populates="worker", foreign_keys="TimeEntry.user_id"
    )
    approved_entries = db.relationship(
        "TimeEntry", back_populates="approver", foreign_keys="TimeEntry.approved_by"
    )
    location_pings = db.relationship("LocationPing", back_populates="user")

    def set_password(self, plain):
        """Store a bcrypt hash of the password (the plain text is never saved)."""
        self.password_hash = bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    def check_password(self, plain):
        if not self.password_hash or plain is None:
            return False
        return bcrypt.checkpw(plain.encode("utf-8"), self.password_hash.encode("utf-8"))

    def can_log_in(self):
        return self.is_active and self.role in STAFF_ROLES and self.password_hash is not None

    def to_dict(self):
        return {
            "user_id": self.user_id,
            "full_name": self.full_name,
            "email": self.email,
            "phone": self.phone,
            "role": self.role,
            "trade": self.trade,
            "is_active": self.is_active,
        }


class JobSite(db.Model):
    __tablename__ = "job_sites"

    site_id = db.Column(db.Integer, primary_key=True)
    site_name = db.Column(db.String(120), nullable=False)
    address = db.Column(db.String(200), nullable=False)
    latitude = db.Column(db.Float, nullable=False)
    longitude = db.Column(db.Float, nullable=False)
    geofence_radius_m = db.Column(db.Integer, nullable=False, default=200, server_default="200")

    jobs = db.relationship("Job", back_populates="site")

    def distance_to(self, lat, lng):
        """Metres from the site centre to a coordinate (haversine)."""
        return haversine(lat, lng, self.latitude, self.longitude)

    def to_dict(self):
        return {
            "site_id": self.site_id,
            "site_name": self.site_name,
            "address": self.address,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "geofence_radius_m": self.geofence_radius_m,
            "job_count": len(self.jobs),
        }


class Job(db.Model):
    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint(_in_list("status", JOB_STATUSES), name="ck_jobs_status"),
        CheckConstraint("crew_size >= 1", name="ck_jobs_crew_size"),
    )

    job_id = db.Column(db.Integer, primary_key=True)
    site_id = db.Column(db.Integer, db.ForeignKey("job_sites.site_id"), nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey("users.user_id"), nullable=False)
    title = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text)
    scheduled_date = db.Column(db.Date, nullable=False)
    crew_size = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(20), nullable=False, default="Scheduled")

    site = db.relationship("JobSite", back_populates="jobs")
    creator = db.relationship("User", back_populates="jobs_created")
    assignments = db.relationship("Assignment", back_populates="job", cascade="all, delete-orphan")
    time_entries = db.relationship("TimeEntry", back_populates="job")

    def assigned_count(self):
        return len(self.assignments)

    def is_full(self):
        return self.assigned_count() >= self.crew_size

    def to_dict(self, include_crew=True):
        data = {
            "job_id": self.job_id,
            "site_id": self.site_id,
            "site_name": self.site.site_name if self.site else None,
            "site_address": self.site.address if self.site else None,
            "created_by": self.created_by,
            "created_by_name": self.creator.full_name if self.creator else None,
            "title": self.title,
            "description": self.description,
            "scheduled_date": _iso(self.scheduled_date),
            "crew_size": self.crew_size,
            "status": self.status,
            "assigned_count": self.assigned_count(),
        }
        if include_crew:
            data["crew"] = [
                {
                    "assignment_id": a.assignment_id,
                    "user_id": a.user_id,
                    "full_name": a.worker.full_name,
                    "trade": a.worker.trade,
                }
                for a in sorted(self.assignments, key=lambda a: a.worker.full_name)
            ]
        return data


class Assignment(db.Model):
    __tablename__ = "assignments"
    # DOUBLE-BOOKING RULE (database backstop): one worker, one assignment per work date.
    # The API checks this first to give a friendly message; this constraint guarantees it
    # even if two requests arrive at the same moment.
    __table_args__ = (
        UniqueConstraint("user_id", "work_date", name="uq_assignment_worker_per_day"),
    )

    assignment_id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.Integer, db.ForeignKey("jobs.job_id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.user_id"), nullable=False)
    work_date = db.Column(db.Date, nullable=False)
    assigned_at = db.Column(db.DateTime, nullable=False, default=datetime.now)

    job = db.relationship("Job", back_populates="assignments")
    worker = db.relationship("User", back_populates="assignments")

    def to_dict(self):
        return {
            "assignment_id": self.assignment_id,
            "job_id": self.job_id,
            "job_title": self.job.title,
            "site_name": self.job.site.site_name,
            "user_id": self.user_id,
            "full_name": self.worker.full_name,
            "trade": self.worker.trade,
            "work_date": _iso(self.work_date),
            "assigned_at": _iso(self.assigned_at),
        }


class TimeEntry(db.Model):
    __tablename__ = "time_entries"
    __table_args__ = (
        CheckConstraint(_in_list("status", ENTRY_STATUSES), name="ck_time_entries_status"),
    )

    entry_id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.user_id"), nullable=False)
    job_id = db.Column(db.Integer, db.ForeignKey("jobs.job_id"), nullable=False)
    clock_in = db.Column(db.DateTime, nullable=False)
    clock_out = db.Column(db.DateTime)  # NULL while the worker is still clocked in
    in_lat = db.Column(db.Float, nullable=False)
    in_lng = db.Column(db.Float, nullable=False)
    out_lat = db.Column(db.Float)
    out_lng = db.Column(db.Float)
    is_flagged = db.Column(db.Boolean, nullable=False, default=False)
    flag_reason = db.Column(db.String(255))
    status = db.Column(db.String(20), nullable=False, default="Pending")
    approved_by = db.Column(db.Integer, db.ForeignKey("users.user_id"), nullable=True)
    edit_reason = db.Column(db.String(255))

    worker = db.relationship("User", back_populates="time_entries", foreign_keys=[user_id])
    job = db.relationship("Job", back_populates="time_entries")
    approver = db.relationship(
        "User", back_populates="approved_entries", foreign_keys=[approved_by]
    )

    def hours(self):
        """Hours worked, computed (never stored). None while still clocked in.

        Subtracting two full datetimes (date + time) means a night shift from
        22:00 Monday to 06:00 Tuesday correctly gives 8.0 hours, not -16.
        """
        if self.clock_out is None:
            return None
        return round((self.clock_out - self.clock_in).total_seconds() / 3600, 2)

    def hours_so_far(self, now):
        """Hours for dashboards: completed hours, or elapsed time up to `now` if still open."""
        end = self.clock_out or now
        return max(0.0, round((end - self.clock_in).total_seconds() / 3600, 2))

    def in_distance_m(self):
        return round(self.job.site.distance_to(self.in_lat, self.in_lng), 1)

    def out_distance_m(self):
        if self.out_lat is None or self.out_lng is None:
            return None
        return round(self.job.site.distance_to(self.out_lat, self.out_lng), 1)

    def add_flag(self, reason):
        """Flag the entry for supervisor review, keeping any earlier reason."""
        self.is_flagged = True
        self.flag_reason = f"{self.flag_reason}; {reason}" if self.flag_reason else reason

    def apply_geofence(self, lat, lng, label):
        """GEOFENCE RULE: measure distance from the job site; flag (but keep) if outside.

        `label` is "Clock-in" or "Clock-out" so the reason says which punch was off-site.
        Returns the distance in metres.
        """
        site = self.job.site
        distance = site.distance_to(lat, lng)
        if should_flag(distance, site.geofence_radius_m):
            self.add_flag(
                f"{label} {round(distance)} m from site (limit {site.geofence_radius_m} m)"
            )
        return distance

    def to_dict(self):
        return {
            "entry_id": self.entry_id,
            "user_id": self.user_id,
            "worker_name": self.worker.full_name,
            "trade": self.worker.trade,
            "job_id": self.job_id,
            "job_title": self.job.title,
            "site_id": self.job.site_id,
            "site_name": self.job.site.site_name,
            "geofence_radius_m": self.job.site.geofence_radius_m,
            "clock_in": _iso(self.clock_in),
            "clock_out": _iso(self.clock_out),
            "in_lat": self.in_lat,
            "in_lng": self.in_lng,
            "out_lat": self.out_lat,
            "out_lng": self.out_lng,
            "in_distance_m": self.in_distance_m(),
            "out_distance_m": self.out_distance_m(),
            "hours": self.hours(),
            "is_flagged": self.is_flagged,
            "flag_reason": self.flag_reason,
            "status": self.status,
            "approved_by": self.approved_by,
            "approved_by_name": self.approver.full_name if self.approver else None,
            "edit_reason": self.edit_reason,
        }


class LocationPing(db.Model):
    __tablename__ = "location_pings"

    ping_id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.user_id"), nullable=False)
    latitude = db.Column(db.Float, nullable=False)
    longitude = db.Column(db.Float, nullable=False)
    recorded_at = db.Column(db.DateTime, nullable=False, default=datetime.now)

    user = db.relationship("User", back_populates="location_pings")

    def to_dict(self):
        return {
            "ping_id": self.ping_id,
            "user_id": self.user_id,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "recorded_at": _iso(self.recorded_at),
        }
