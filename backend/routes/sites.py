"""Job sites: the geolocated places where jobs happen, each with a geofence radius."""

from flask import Blueprint, current_app, jsonify

from auth import role_required
from extensions import db
from models import STAFF_ROLES, JobSite
from validation import (
    get_json,
    get_or_404,
    parse_int,
    parse_latitude,
    parse_longitude,
    require_str,
)

sites_bp = Blueprint("sites", __name__, url_prefix="/api/sites")

MIN_RADIUS_M = 25
MAX_RADIUS_M = 5000


def _radius(value, required):
    return parse_int(
        value, "geofence_radius_m", "Geofence radius", MIN_RADIUS_M, MAX_RADIUS_M, required
    )


@sites_bp.get("")
@role_required(*STAFF_ROLES)
def list_sites():
    """List all job sites alphabetically, with how many jobs each has."""
    sites = JobSite.query.order_by(JobSite.site_name).all()
    return jsonify({"sites": [s.to_dict() for s in sites]})


@sites_bp.post("")
@role_required("Dispatcher", "Admin")
def create_site():
    """Create a job site. The geofence radius defaults to GEOFENCE_RADIUS_M (200 m)."""
    data = get_json()
    radius = _radius(data.get("geofence_radius_m"), required=False)
    site = JobSite(
        site_name=require_str(data.get("site_name"), "site_name", "Site name", 2, 120),
        address=require_str(data.get("address"), "address", "Address", 5, 200),
        latitude=parse_latitude(data.get("latitude"), "latitude"),
        longitude=parse_longitude(data.get("longitude"), "longitude"),
        geofence_radius_m=radius if radius is not None else current_app.config["GEOFENCE_RADIUS_M"],
    )
    db.session.add(site)
    db.session.commit()
    return jsonify({"site": site.to_dict()}), 201


@sites_bp.patch("/<int:site_id>")
@role_required("Dispatcher", "Admin")
def update_site(site_id):
    """Edit a site's name, address, coordinates or geofence radius."""
    site = get_or_404(JobSite, site_id, "Job site")
    data = get_json()
    if "site_name" in data:
        site.site_name = require_str(data["site_name"], "site_name", "Site name", 2, 120)
    if "address" in data:
        site.address = require_str(data["address"], "address", "Address", 5, 200)
    if "latitude" in data:
        site.latitude = parse_latitude(data["latitude"], "latitude")
    if "longitude" in data:
        site.longitude = parse_longitude(data["longitude"], "longitude")
    if "geofence_radius_m" in data:
        site.geofence_radius_m = _radius(data["geofence_radius_m"], required=True)
    db.session.commit()
    return jsonify({"site": site.to_dict()})
