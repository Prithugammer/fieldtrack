"""Jobs: a piece of work at a site on a scheduled date, with a planned crew size."""

from flask import Blueprint, g, jsonify, request

from auth import role_required
from extensions import db
from models import JOB_STATUSES, STAFF_ROLES, Job, JobSite
from validation import (
    ApiError,
    get_json,
    get_or_404,
    one_of,
    parse_date,
    parse_int,
    require_str,
)

jobs_bp = Blueprint("jobs", __name__, url_prefix="/api/jobs")


def _crew_size(value, required=True):
    return parse_int(value, "crew_size", "Crew size", 1, 50, required)


@jobs_bp.get("")
@role_required(*STAFF_ROLES)
def list_jobs():
    """List jobs, filterable by ?date=YYYY-MM-DD, ?status=... and ?site_id=..."""
    query = Job.query
    day = parse_date(request.args.get("date"), "date", "Date", required=False)
    if day:
        query = query.filter(Job.scheduled_date == day)
    status = one_of(request.args.get("status"), "status", "Status", JOB_STATUSES, required=False)
    if status:
        query = query.filter(Job.status == status)
    site_id = parse_int(request.args.get("site_id"), "site_id", "Site", required=False)
    if site_id:
        query = query.filter(Job.site_id == site_id)
    jobs = query.order_by(Job.scheduled_date.desc(), Job.title).all()
    return jsonify({"jobs": [j.to_dict() for j in jobs]})


@jobs_bp.get("/<int:job_id>")
@role_required(*STAFF_ROLES)
def get_job(job_id):
    """Return one job including its assigned crew."""
    return jsonify({"job": get_or_404(Job, job_id, "Job").to_dict()})


@jobs_bp.post("")
@role_required("Dispatcher", "Admin")
def create_job():
    """Create a job. created_by comes from the JWT, never from the request body."""
    data = get_json()
    site_id = parse_int(data.get("site_id"), "site_id", "Job site")
    get_or_404(JobSite, site_id, "Job site", field="site_id")
    job = Job(
        site_id=site_id,
        created_by=g.current_user.user_id,
        title=require_str(data.get("title"), "title", "Title", 3, 120),
        description=require_str(
            data.get("description"), "description", "Description", 1, 1000, required=False
        ),
        scheduled_date=parse_date(data.get("scheduled_date"), "scheduled_date", "Scheduled date"),
        crew_size=_crew_size(data.get("crew_size")),
        status=one_of(data.get("status"), "status", "Status", JOB_STATUSES, required=False)
        or "Scheduled",
    )
    db.session.add(job)
    db.session.commit()
    return jsonify({"job": job.to_dict()}), 201


@jobs_bp.patch("/<int:job_id>")
@role_required("Dispatcher", "Admin")
def update_job(job_id):
    """Edit a job. Crew size can't drop below the number already assigned."""
    job = get_or_404(Job, job_id, "Job")
    data = get_json()

    if "site_id" in data:
        site_id = parse_int(data["site_id"], "site_id", "Job site")
        get_or_404(JobSite, site_id, "Job site", field="site_id")
        job.site_id = site_id
    if "title" in data:
        job.title = require_str(data["title"], "title", "Title", 3, 120)
    if "description" in data:
        job.description = require_str(
            data["description"], "description", "Description", 1, 1000, required=False
        )
    if "scheduled_date" in data:
        new_date = parse_date(data["scheduled_date"], "scheduled_date", "Scheduled date")
        # Assignments are made for the job's date; moving the job would silently move
        # workers to a day they may already be booked on, so we require removing them first.
        if new_date != job.scheduled_date and job.assignments:
            raise ApiError(
                f"Remove the {job.assigned_count()} assigned worker(s) before changing the date.",
                "scheduled_date",
                status=409,
            )
        job.scheduled_date = new_date
    if "crew_size" in data:
        crew_size = _crew_size(data["crew_size"])
        if crew_size < job.assigned_count():
            raise ApiError(
                f"Crew size can't be less than the {job.assigned_count()} worker(s) already assigned.",
                "crew_size",
            )
        job.crew_size = crew_size
    if "status" in data:
        job.status = one_of(data["status"], "status", "Status", JOB_STATUSES)

    db.session.commit()
    return jsonify({"job": job.to_dict()})
