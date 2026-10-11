"""Time entries: recording clock-in/clock-out with GPS, geofence flagging, and approval."""

from datetime import timedelta

from flask import Blueprint, g, jsonify, request
from sqlalchemy import or_

from auth import role_required
from extensions import db
from models import ENTRY_STATUSES, STAFF_ROLES, Assignment, Job, LocationPing, TimeEntry, User
from validation import (
    ApiError,
    day_bounds,
    get_json,
    get_or_404,
    one_of,
    parse_bool,
    parse_date,
    parse_datetime,
    parse_id,
    parse_latitude,
    parse_longitude,
    require_str,
)

time_entries_bp = Blueprint("time_entries", __name__, url_prefix="/api/time-entries")

MAX_SHIFT = timedelta(hours=24)


def _validate_shift(clock_in, clock_out):
    """Clock-out must be after clock-in (next calendar day is fine) and within 24 hours."""
    if clock_out <= clock_in:
        raise ApiError("Clock-out must be after clock-in.", "clock_out")
    if clock_out - clock_in > MAX_SHIFT:
        raise ApiError("A shift can't be longer than 24 hours.", "clock_out")


def _check_overlap(user_id, clock_in, clock_out, exclude_entry_id=None):
    """Refuse an entry whose time range overlaps another (non-rejected) entry of the worker.

    Two ranges overlap when each starts before the other ends. An entry with no clock-out
    is treated as still running, so a worker can never be clocked in twice at once.
    """
    query = TimeEntry.query.filter(
        TimeEntry.user_id == user_id,
        TimeEntry.status != "Rejected",
        or_(TimeEntry.clock_out.is_(None), TimeEntry.clock_out > clock_in),
    )
    if clock_out is not None:
        query = query.filter(TimeEntry.clock_in < clock_out)
    if exclude_entry_id is not None:
        query = query.filter(TimeEntry.entry_id != exclude_entry_id)
    clash = query.first()
    if clash:
        end = clash.clock_out.strftime("%Y-%m-%d %H:%M") if clash.clock_out else "still clocked in"
        raise ApiError(
            f"Overlaps entry #{clash.entry_id} for {clash.worker.full_name} "
            f"({clash.clock_in.strftime('%Y-%m-%d %H:%M')} – {end}).",
            "clock_in",
            status=409,
        )


def _record_ping(user_id, lat, lng, when):
    """Every coordinate we capture is also logged to location_pings as an audit trail."""
    db.session.add(LocationPing(user_id=user_id, latitude=lat, longitude=lng, recorded_at=when))


@time_entries_bp.get("")
@role_required(*STAFF_ROLES)
def list_time_entries():
    """List entries newest first. Filters: ?status=, ?flagged=true|false, ?worker=<user_id>,
    ?date=YYYY-MM-DD (clock-in date), ?job_id=."""
    query = TimeEntry.query
    status = one_of(request.args.get("status"), "status", "Status", ENTRY_STATUSES, required=False)
    if status:
        query = query.filter(TimeEntry.status == status)
    flagged = parse_bool(request.args.get("flagged"), "flagged", "Flagged", required=False)
    if flagged is not None:
        query = query.filter(TimeEntry.is_flagged == flagged)
    worker = parse_id(request.args.get("worker"), "worker", "Worker", required=False)
    if worker:
        query = query.filter(TimeEntry.user_id == worker)
    job_id = parse_id(request.args.get("job_id"), "job_id", "Job", required=False)
    if job_id:
        query = query.filter(TimeEntry.job_id == job_id)
    day = parse_date(request.args.get("date"), "date", "Date", required=False)
    if day:
        start, end = day_bounds(day)
        query = query.filter(TimeEntry.clock_in >= start, TimeEntry.clock_in < end)
    entries = query.order_by(TimeEntry.clock_in.desc(), TimeEntry.entry_id.desc()).all()
    return jsonify({"time_entries": [e.to_dict() for e in entries]})


@time_entries_bp.post("")
@role_required("Supervisor", "Admin")
def create_time_entry():
    """Record a time entry (clock-in, optionally clock-out) with GPS coordinates.

    Decision table (docs/decision-table.md), checked in this order:
      1. Validate every field (400 with the offending field).
      2. The worker must be an active Worker.
      3. ASSIGNMENT RULE: the worker must be assigned to THIS job on the clock-in date.
         If not -> 409 and nothing is saved.
      4. The entry must not overlap another entry for the same worker -> else 409.
      5. GEOFENCE RULE: measure the distance from the job site. If it is beyond the site's
         radius the entry is flagged with a reason — but it is ALWAYS saved.
    """
    data = get_json()

    # 1. Field validation
    user_id = parse_id(data.get("user_id"), "user_id", "Worker")
    job_id = parse_id(data.get("job_id"), "job_id", "Job")
    clock_in = parse_datetime(data.get("clock_in"), "clock_in", "Clock-in time")
    in_lat = parse_latitude(data.get("in_lat"), "in_lat", "Clock-in latitude")
    in_lng = parse_longitude(data.get("in_lng"), "in_lng", "Clock-in longitude")
    clock_out = parse_datetime(data.get("clock_out"), "clock_out", "Clock-out time", required=False)
    out_lat = out_lng = None
    if clock_out is not None:
        out_lat = parse_latitude(data.get("out_lat"), "out_lat", "Clock-out latitude")
        out_lng = parse_longitude(data.get("out_lng"), "out_lng", "Clock-out longitude")
        _validate_shift(clock_in, clock_out)

    # 2. Worker and job must exist; worker must be active
    worker = get_or_404(User, user_id, "Worker", field="user_id")
    job = get_or_404(Job, job_id, "Job", field="job_id")
    if worker.role != "Worker" or not worker.is_active:
        raise ApiError(f"{worker.full_name} is not an active worker.", "user_id")

    # 3. ASSIGNMENT RULE — a worker can only log time on a job they were dispatched to that
    #    day. The work date is the calendar date of the clock-in, so a night shift that
    #    starts at 22:00 Monday belongs to Monday's assignment even though it ends Tuesday.
    work_date = clock_in.date()
    assigned = Assignment.query.filter_by(
        user_id=worker.user_id, job_id=job.job_id, work_date=work_date
    ).first()
    if not assigned:
        raise ApiError(
            f"{worker.full_name} is not assigned to '{job.title}' on {work_date.isoformat()}. "
            f"Assign the worker to this job first.",
            "user_id",
            status=409,
        )

    # 4. No overlapping entries for the same worker
    _check_overlap(worker.user_id, clock_in, clock_out)

    entry = TimeEntry(
        worker=worker,
        job=job,
        clock_in=clock_in,
        clock_out=clock_out,
        in_lat=in_lat,
        in_lng=in_lng,
        out_lat=out_lat,
        out_lng=out_lng,
        is_flagged=False,
        status="Pending",
    )
    db.session.add(entry)

    # 5. GEOFENCE RULE — distance from the site centre vs the site's radius.
    #    Outside the circle => flagged for the supervisor; we still save it (see geofence.py).
    entry.apply_geofence(in_lat, in_lng, "Clock-in")
    if clock_out is not None:
        entry.apply_geofence(out_lat, out_lng, "Clock-out")

    _record_ping(worker.user_id, in_lat, in_lng, clock_in)
    if clock_out is not None:
        _record_ping(worker.user_id, out_lat, out_lng, clock_out)
    db.session.commit()
    return jsonify({"time_entry": entry.to_dict()}), 201


@time_entries_bp.patch("/<int:entry_id>/clock-out")
@role_required("Supervisor", "Admin")
def clock_out(entry_id):
    """Record the clock-out time and coordinates for an open entry.

    Clock-out must be after clock-in (crossing midnight is fine). The geofence rule is
    applied again with the clock-out coordinates.
    """
    entry = get_or_404(TimeEntry, entry_id, "Time entry")
    if entry.clock_out is not None:
        raise ApiError("This entry has already been clocked out.", "clock_out", status=409)

    data = get_json()
    out_time = parse_datetime(data.get("clock_out"), "clock_out", "Clock-out time")
    out_lat = parse_latitude(data.get("out_lat"), "out_lat", "Clock-out latitude")
    out_lng = parse_longitude(data.get("out_lng"), "out_lng", "Clock-out longitude")
    _validate_shift(entry.clock_in, out_time)
    _check_overlap(entry.user_id, entry.clock_in, out_time, exclude_entry_id=entry.entry_id)

    entry.clock_out = out_time
    entry.out_lat = out_lat
    entry.out_lng = out_lng
    entry.apply_geofence(out_lat, out_lng, "Clock-out")
    _record_ping(entry.user_id, out_lat, out_lng, out_time)
    db.session.commit()
    return jsonify({"time_entry": entry.to_dict()})


@time_entries_bp.patch("/<int:entry_id>/approve")
@role_required("Supervisor", "Admin")
def approve(entry_id):
    """Approve or reject a completed entry. A reason is always required (audit trail),
    and the deciding user is stored in approved_by."""
    entry = get_or_404(TimeEntry, entry_id, "Time entry")
    data = get_json()
    decision = one_of(data.get("decision"), "decision", "Decision", ("Approved", "Rejected"))
    reason = require_str(data.get("edit_reason"), "edit_reason", "Reason", 3, 255)

    if entry.clock_out is None:
        raise ApiError("Clock the worker out before approving or rejecting this entry.")
    if entry.status != "Pending":
        who = entry.approver.full_name if entry.approver else "someone"
        raise ApiError(f"This entry was already {entry.status.lower()} by {who}.", status=409)

    entry.status = decision
    entry.approved_by = g.current_user.user_id
    entry.edit_reason = reason
    db.session.commit()
    return jsonify({"time_entry": entry.to_dict()})
