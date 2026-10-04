"""Reports: hours by worker, hours by job, flagged entries, and CSV export.

Hours are summed from TimeEntry.hours(), which is computed from clock-in/clock-out.
Only completed entries count toward hours, and Rejected entries are excluded.
"""

import csv
import io
from datetime import date, timedelta

from flask import Blueprint, Response, jsonify, request

from auth import role_required
from models import STAFF_ROLES, TimeEntry
from validation import ApiError, day_bounds, parse_date

reports_bp = Blueprint("reports", __name__, url_prefix="/api/reports")


def _date_range():
    """Read ?from= and ?to= (inclusive). Defaults to the last 7 days including today."""
    today = date.today()
    start = parse_date(request.args.get("from"), "from", "From date", required=False)
    end = parse_date(request.args.get("to"), "to", "To date", required=False)
    end = end or today
    start = start or end - timedelta(days=6)
    if start > end:
        raise ApiError("'From' date must be on or before 'To' date.", "from")
    return start, end


def _entries_in_range(start, end):
    """All entries whose clock-in falls between start 00:00 and end 23:59:59."""
    range_start, _ = day_bounds(start)
    _, range_end = day_bounds(end)
    return (
        TimeEntry.query.filter(TimeEntry.clock_in >= range_start, TimeEntry.clock_in < range_end)
        .order_by(TimeEntry.clock_in)
        .all()
    )


def _counts_toward_hours(entry):
    return entry.clock_out is not None and entry.status != "Rejected"


@reports_bp.get("/hours-by-worker")
@role_required(*STAFF_ROLES)
def hours_by_worker():
    """Total, approved and pending hours per worker for the date range."""
    start, end = _date_range()
    rows = {}
    for e in _entries_in_range(start, end):
        row = rows.setdefault(
            e.user_id,
            {
                "user_id": e.user_id,
                "full_name": e.worker.full_name,
                "trade": e.worker.trade,
                "entries": 0,
                "total_hours": 0.0,
                "approved_hours": 0.0,
                "pending_hours": 0.0,
                "flagged_entries": 0,
            },
        )
        if e.is_flagged:
            row["flagged_entries"] += 1
        if not _counts_toward_hours(e):
            continue
        row["entries"] += 1
        row["total_hours"] += e.hours()
        if e.status == "Approved":
            row["approved_hours"] += e.hours()
        else:
            row["pending_hours"] += e.hours()

    result = sorted(rows.values(), key=lambda r: r["full_name"])
    for r in result:
        for key in ("total_hours", "approved_hours", "pending_hours"):
            r[key] = round(r[key], 2)
    return jsonify(
        {
            "from": start.isoformat(),
            "to": end.isoformat(),
            "rows": result,
            "total_hours": round(sum(r["total_hours"] for r in result), 2),
        }
    )


@reports_bp.get("/hours-by-job")
@role_required(*STAFF_ROLES)
def hours_by_job():
    """Total hours and number of distinct workers per job for the date range."""
    start, end = _date_range()
    rows, workers = {}, {}
    for e in _entries_in_range(start, end):
        if not _counts_toward_hours(e):
            continue
        row = rows.setdefault(
            e.job_id,
            {
                "job_id": e.job_id,
                "title": e.job.title,
                "site_name": e.job.site.site_name,
                "scheduled_date": e.job.scheduled_date.isoformat(),
                "status": e.job.status,
                "entries": 0,
                "total_hours": 0.0,
            },
        )
        row["entries"] += 1
        row["total_hours"] += e.hours()
        workers.setdefault(e.job_id, set()).add(e.user_id)

    result = sorted(rows.values(), key=lambda r: (r["scheduled_date"], r["title"]))
    for r in result:
        r["workers"] = len(workers[r["job_id"]])
        r["total_hours"] = round(r["total_hours"], 2)
    return jsonify(
        {
            "from": start.isoformat(),
            "to": end.isoformat(),
            "rows": result,
            "total_hours": round(sum(r["total_hours"] for r in result), 2),
        }
    )


@reports_bp.get("/flagged")
@role_required(*STAFF_ROLES)
def flagged():
    """Every geofence-flagged entry in the date range, in any status."""
    start, end = _date_range()
    rows = [e.to_dict() for e in _entries_in_range(start, end) if e.is_flagged]
    return jsonify({"from": start.isoformat(), "to": end.isoformat(), "rows": rows})


@reports_bp.get("/hours.csv")
@role_required(*STAFF_ROLES)
def hours_csv():
    """Download every time entry in the date range as CSV (for payroll import)."""
    start, end = _date_range()
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "entry_id",
            "worker",
            "trade",
            "job",
            "site",
            "clock_in",
            "clock_out",
            "hours",
            "status",
            "flagged",
            "flag_reason",
            "approved_by",
            "edit_reason",
        ]
    )
    for e in _entries_in_range(start, end):
        writer.writerow(
            [
                e.entry_id,
                e.worker.full_name,
                e.worker.trade or "",
                e.job.title,
                e.job.site.site_name,
                e.clock_in.isoformat(sep=" "),
                e.clock_out.isoformat(sep=" ") if e.clock_out else "",
                e.hours() if e.hours() is not None else "",
                e.status,
                "Yes" if e.is_flagged else "No",
                e.flag_reason or "",
                e.approver.full_name if e.approver else "",
                e.edit_reason or "",
            ]
        )
    filename = f"fieldtrack-hours-{start.isoformat()}-to-{end.isoformat()}.csv"
    return Response(
        buffer.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
