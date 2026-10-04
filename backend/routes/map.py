"""Live Map: job sites plus SIMULATED worker positions (see simulation.py).

Read-only. Positions are computed from the wall clock on every request; nothing is written.
"""
from datetime import date

from flask import Blueprint, jsonify

from auth import role_required
from kathmandu_geo import KATHMANDU_VALLEY_BOUNDS, LANDMARKS, TRAFFIC_HOTSPOTS
from models import STAFF_ROLES, Assignment, JobSite, User
from simulation import (
    CYCLE_SECONDS,
    SIM_DAY_END,
    SIM_DAY_START,
    format_clock,
    get_live_map_state,
    seconds_to_reset,
    sim_clock,
)

map_bp = Blueprint("map", __name__, url_prefix="/api/map")


@map_bp.get("/live")
@role_required(*STAFF_ROLES)
def live():
    """Every job site, and every active worker's simulated position right now."""
    today = date.today()
    sites = JobSite.query.order_by(JobSite.site_name).all()
    assignments = Assignment.query.filter_by(work_date=today).all()
    workers = User.query.filter_by(role="Worker", is_active=True).order_by(User.full_name).all()
    return jsonify(get_live_map_state(sites, assignments, workers, today))


@map_bp.get("/sim-clock")
@role_required(*STAFF_ROLES)
def clock():
    """The simulated time of day, so the UI can show it's a time-compressed simulation."""
    minutes, cycle = sim_clock()
    return jsonify(
        {
            "sim_time": format_clock(minutes),
            "sim_minutes": round(minutes, 1),
            "window_start": format_clock(SIM_DAY_START),
            "window_end": format_clock(SIM_DAY_END),
            "cycle_seconds": CYCLE_SECONDS,
            "cycle": cycle,
            "seconds_to_reset": round(seconds_to_reset(), 1),
        }
    )


@map_bp.get("/bounds")
@role_required(*STAFF_ROLES)
def bounds():
    """Initial map view for the Kathmandu Valley, plus the traffic hotspots."""
    return jsonify(
        {
            **KATHMANDU_VALLEY_BOUNDS,
            "traffic_hotspots": [
                {"name": name, "lat": LANDMARKS[name][0], "lng": LANDMARKS[name][1], **spot}
                for name, spot in TRAFFIC_HOTSPOTS.items()
            ],
        }
    )
