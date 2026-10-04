"""Dashboard: today's KPIs and the lists a dispatcher/supervisor checks first thing."""

from datetime import date, datetime

from flask import Blueprint, jsonify

from auth import role_required
from models import STAFF_ROLES, Assignment, Job, TimeEntry, User
from validation import day_bounds

dashboard_bp = Blueprint("dashboard", __name__, url_prefix="/api/dashboard")


@dashboard_bp.get("")
@role_required(*STAFF_ROLES)
def dashboard():
    """Return the 4 KPI values plus Jobs Today, Unassigned Workers and Needs Attention."""
    today = date.today()
    now = datetime.now()
    start, end = day_bounds(today)

    jobs_today = Job.query.filter(Job.scheduled_date == today).order_by(Job.title).all()
    open_entries = TimeEntry.query.filter(TimeEntry.clock_out.is_(None)).all()
    todays_entries = TimeEntry.query.filter(
        TimeEntry.clock_in >= start, TimeEntry.clock_in < end, TimeEntry.status != "Rejected"
    ).all()
    flagged_pending = (
        TimeEntry.query.filter(TimeEntry.is_flagged.is_(True), TimeEntry.status == "Pending")
        .order_by(TimeEntry.clock_in.desc())
        .all()
    )

    assigned_today = {a.user_id for a in Assignment.query.filter_by(work_date=today).all()}
    unassigned = [
        w
        for w in User.query.filter_by(role="Worker", is_active=True).order_by(User.full_name)
        if w.user_id not in assigned_today
    ]

    needs_attention = []
    for e in flagged_pending:
        needs_attention.append(
            {
                "type": "flagged_entry",
                "ref_id": e.entry_id,
                "message": f"{e.worker.full_name} · {e.job.title}: {e.flag_reason}",
            }
        )
    for j in jobs_today:
        if j.status != "Completed" and j.assigned_count() < j.crew_size:
            needs_attention.append(
                {
                    "type": "understaffed_job",
                    "ref_id": j.job_id,
                    "message": f"'{j.title}' has {j.assigned_count()} of {j.crew_size} crew assigned.",
                }
            )
    for e in open_entries:
        if e.clock_in < start:
            needs_attention.append(
                {
                    "type": "open_overnight",
                    "ref_id": e.entry_id,
                    "message": f"{e.worker.full_name} still clocked in since "
                    f"{e.clock_in.strftime('%b %d %H:%M')}.",
                }
            )

    return jsonify(
        {
            "date": today.isoformat(),
            "kpis": {
                "active_jobs": sum(1 for j in jobs_today if j.status != "Completed"),
                "workers_clocked_in": len({e.user_id for e in open_entries}),
                "hours_today": round(sum(e.hours_so_far(now) for e in todays_entries), 1),
                "flagged_entries": len(flagged_pending),
            },
            "jobs_today": [j.to_dict() for j in jobs_today],
            "unassigned_workers": [w.to_dict() for w in unassigned],
            "needs_attention": needs_attention,
        }
    )
