"""Safety / emergency actions and the audit log (see safety/ for how escalation works).

The escalation is advanced by POST /api/safety/tick (the Live Map's 1 s poll calls it); the
read-only GET /api/map/live reports the result under "safety". These routes are the controls:
simulated-worker actions (accident, SOS, "I'm OK", break) and the supervisor's resolution.

Who may do what: every state-changing control is limited to SAFETY_CONTROL_ROLES (Supervisor,
Admin). A Dispatcher can watch (map, alerts, config, audit log) but cannot change safety state.
"""

import json

from flask import Blueprint, Response, current_app, g, jsonify, request

from auth import role_required
from models import STAFF_ROLES
from routes.map import compute_live_state
from safety.machine import OUTCOMES
from safety.service import SafetyError
from validation import ApiError, get_json, one_of, parse_bool, parse_id, require_str

safety_bp = Blueprint("safety", __name__, url_prefix="/api/safety")

# Roles that may change safety state (trigger, respond, break, resolve, return to duty).
SAFETY_CONTROL_ROLES = ("Supervisor", "Admin")


def _service():
    """The safety service, brought up to date with the current simulated positions."""
    service = current_app.extensions["safety"]
    service.process(compute_live_state())
    return service


def _run(action, *args, **kwargs):
    try:
        return action(*args, **kwargs)
    except SafetyError as err:
        raise ApiError(str(err), status=err.status) from err


def _actor():
    return f"{g.current_user.full_name} ({g.current_user.role})"


@safety_bp.get("/config")
@role_required(*STAFF_ROLES)
def config():
    """The active safety settings (mode, thresholds, break zones, random seed)."""
    service = current_app.extensions["safety"]
    return jsonify({**service.config.to_dict(), "seed": service.seed})


@safety_bp.post("/tick")
@role_required(*STAFF_ROLES)
def tick():
    """Advance the escalation to "now" and return the Live Map state with the new safety info.

    This is what GET /api/map/live used to do as a side effect. It only moves time forward
    (idle timers, check-in windows, the configured random accident roll); it cannot start,
    resolve or change an emergency on anyone's say-so, so every staff role may call it.
    ?route=<user_id> adds that worker's remaining route, like the live-map endpoint.
    """
    route = parse_id(request.args.get("route"), "route", "Route", required=False)
    state = compute_live_state(path_for=route)
    return jsonify(current_app.extensions["safety"].process(state))


@safety_bp.post("/workers/<int:user_id>/accident")
@role_required(*SAFETY_CONTROL_ROLES)
def trigger_accident(user_id):
    """Demo control: the worker stops moving and is incapacitated (never answers check-ins)."""
    service = _service()
    _run(service.trigger_accident, user_id, actor=_actor())
    return jsonify({"ok": True}), 201


@safety_bp.post("/workers/<int:user_id>/sos")
@role_required(*SAFETY_CONTROL_ROLES)
def sos(user_id):
    """The worker presses SOS: straight to EMERGENCY."""
    service = _service()
    _run(service.sos, user_id, actor=_actor())
    return jsonify({"ok": True}), 201


@safety_bp.post("/workers/<int:user_id>/respond")
@role_required(*SAFETY_CONTROL_ROLES)
def respond(user_id):
    """The worker answers a check-in with "I'm OK" (from the simulated worker view)."""
    service = _service()
    cleared = _run(service.respond, user_id)
    return jsonify({"ok": True, "cleared": cleared})


@safety_bp.post("/workers/<int:user_id>/break")
@role_required(*SAFETY_CONTROL_ROLES)
def set_break(user_id):
    """Mark a worker on (or back from) a break; idle detection ignores workers on a break."""
    data = get_json()
    on_break = parse_bool(data.get("on_break"), "on_break", "On break")
    service = _service()
    _run(service.set_break, user_id, on_break, actor=_actor())
    return jsonify({"ok": True, "on_break": on_break})


@safety_bp.post("/workers/<int:user_id>/resolve")
@role_required(*SAFETY_CONTROL_ROLES)
def resolve(user_id):
    """Supervisor closes an emergency: outcome "real_incident" or "false_alarm", optional note."""
    data = get_json()
    outcome = one_of(data.get("outcome"), "outcome", "Outcome", tuple(OUTCOMES))
    note = require_str(data.get("note"), "note", "Note", max_len=500, required=False) or ""
    service = _service()
    _run(service.resolve, user_id, outcome, note.strip(), actor=_actor())
    return jsonify({"ok": True})


@safety_bp.post("/workers/<int:user_id>/return-to-duty")
@role_required(*SAFETY_CONTROL_ROLES)
def return_to_duty(user_id):
    """Clear a post-incident worker back to normal monitoring."""
    service = _service()
    _run(service.return_to_duty, user_id, actor=_actor())
    return jsonify({"ok": True})


@safety_bp.get("/audit")
@role_required(*STAFF_ROLES)
def audit():
    """The audit log, oldest first. ?format=csv downloads it; ?worker_id= filters one worker."""
    service = current_app.extensions["safety"]
    worker_id = parse_id(request.args.get("worker_id"), "worker_id", "Worker", required=False)
    if request.args.get("format") == "csv":
        body = service.audit.to_csv()
        return Response(
            body,
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment; filename=safety-audit-log.csv"},
        )
    entries = service.audit_entries(worker_id)
    if request.args.get("format") == "json-file":
        return Response(
            json.dumps(entries, indent=2),
            mimetype="application/json",
            headers={"Content-Disposition": "attachment; filename=safety-audit-log.json"},
        )
    return jsonify(entries)
