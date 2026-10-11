"""Crew assignments: which worker is on which job on which day."""

from flask import Blueprint, jsonify, request
from sqlalchemy.exc import IntegrityError

from auth import role_required
from extensions import db
from models import STAFF_ROLES, Assignment, Job, TimeEntry, User
from validation import ApiError, day_bounds, get_json, get_or_404, parse_date, parse_id

assignments_bp = Blueprint("assignments", __name__, url_prefix="/api/assignments")


def _double_booking_message(worker, existing):
    """Build the 409 message shown in the Assign Worker modal."""
    return (
        f"{worker.full_name} is already assigned to '{existing.job.title}' at "
        f"{existing.job.site.site_name} on {existing.work_date.isoformat()}. "
        f"A worker can only be booked on one job per day."
    )


@assignments_bp.get("")
@role_required(*STAFF_ROLES)
def list_assignments():
    """List assignments, filterable by ?job_id=, ?user_id= and ?work_date=."""
    query = Assignment.query
    job_id = parse_id(request.args.get("job_id"), "job_id", "Job", required=False)
    if job_id:
        query = query.filter(Assignment.job_id == job_id)
    user_id = parse_id(request.args.get("user_id"), "user_id", "Worker", required=False)
    if user_id:
        query = query.filter(Assignment.user_id == user_id)
    work_date = parse_date(request.args.get("work_date"), "work_date", "Work date", required=False)
    if work_date:
        query = query.filter(Assignment.work_date == work_date)
    rows = query.order_by(Assignment.work_date.desc(), Assignment.assignment_id).all()
    return jsonify({"assignments": [a.to_dict() for a in rows]})


@assignments_bp.post("")
@role_required("Dispatcher", "Admin")
def create_assignment():
    """Assign a worker to a job for the job's date.

    Rules checked in this order:
      1. The job and worker exist, and the worker is an active Worker.
      2. The work date is the job's scheduled date, and the job isn't Completed.
      3. DOUBLE-BOOKING RULE: the worker has no other assignment on that date -> else 409.
      4. CREW SIZE RULE: the job still has an open spot -> else 409.
    """
    data = get_json()
    job_id = parse_id(data.get("job_id"), "job_id", "Job")
    user_id = parse_id(data.get("user_id"), "user_id", "Worker")
    job = get_or_404(Job, job_id, "Job", field="job_id")
    worker = get_or_404(User, user_id, "Worker", field="user_id")

    if worker.role != "Worker":
        raise ApiError(f"{worker.full_name} is a {worker.role}, not a Worker.", "user_id")
    if not worker.is_active:
        raise ApiError(f"{worker.full_name} is deactivated and can't be assigned.", "user_id")

    work_date = parse_date(data.get("work_date"), "work_date", "Work date", required=False)
    work_date = work_date or job.scheduled_date
    if work_date != job.scheduled_date:
        raise ApiError(
            f"This job is scheduled for {job.scheduled_date.isoformat()}; "
            f"assignments must be for that date.",
            "work_date",
        )
    if job.status == "Completed":
        raise ApiError("This job is already completed.", "job_id", status=409)

    # ---- DOUBLE-BOOKING RULE -------------------------------------------------------------
    # A worker can be in only one place per day, so we look for ANY assignment this worker
    # already has on this date (on any job). If one exists we refuse with HTTP 409 Conflict
    # and a message naming the existing job, so the dispatcher knows exactly why.
    # The UNIQUE(user_id, work_date) constraint in models.py backs this up at DB level.
    existing = Assignment.query.filter_by(user_id=worker.user_id, work_date=work_date).first()
    if existing:
        if existing.job_id == job.job_id:
            message = f"{worker.full_name} is already on this job's crew."
        else:
            message = _double_booking_message(worker, existing)
        raise ApiError(message, "user_id", status=409)

    # ---- CREW SIZE RULE ------------------------------------------------------------------
    if job.is_full():
        raise ApiError(
            f"The crew for '{job.title}' is full ({job.crew_size} of {job.crew_size}).",
            "job_id",
            status=409,
        )

    assignment = Assignment(job_id=job.job_id, user_id=worker.user_id, work_date=work_date)
    db.session.add(assignment)
    try:
        db.session.commit()
    except IntegrityError:
        # Two dispatchers booked the same worker at the same instant; the DB caught it.
        db.session.rollback()
        raise ApiError(
            f"{worker.full_name} was just assigned elsewhere on {work_date.isoformat()}.",
            "user_id",
            status=409,
        )
    return jsonify({"assignment": assignment.to_dict()}), 201


@assignments_bp.delete("/<int:assignment_id>")
@role_required("Dispatcher", "Admin")
def delete_assignment(assignment_id):
    """Remove a worker from a job, unless time has already been recorded against it."""
    assignment = get_or_404(Assignment, assignment_id, "Assignment")
    start, end = day_bounds(assignment.work_date)
    has_time = TimeEntry.query.filter(
        TimeEntry.user_id == assignment.user_id,
        TimeEntry.job_id == assignment.job_id,
        TimeEntry.clock_in >= start,
        TimeEntry.clock_in < end,
    ).first()
    if has_time:
        raise ApiError(
            "Time has already been recorded for this worker on this job, so the "
            "assignment can't be removed.",
            status=409,
        )
    db.session.delete(assignment)
    db.session.commit()
    return jsonify({"message": "Assignment removed."})
