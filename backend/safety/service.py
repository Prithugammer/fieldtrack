"""Connects the safety machines to the Live Map.

The map simulation is stateless (a pure function of the clock), but safety needs memory: how long
each worker has been still, which check-in they are on, who has had an accident. This service
holds that memory (in process; it resets when the server restarts) and is driven by `process()`,
which the Live Map calls on every poll with the freshly computed state. It then:

  * rolls for accidents and freezes the worker's marker where it happened,
  * feeds each worker's position to their SafetyMachine,
  * lets simulated workers reply to check-ins, and
  * adds a "safety" block (alerts, notifications) and per-worker safety info to the state.
"""

import threading
import time
from datetime import datetime, timezone

from geofence import haversine
from kathmandu_geo import LANDMARKS

from .audit import AuditLog
from .behaviour import AccidentRoller, ReplyPlanner, resolve_seed
from .config import SafetyConfig
from .machine import EMERGENCY, NORMAL, POST_INCIDENT, SafetyMachine, WorkerRef
from .notifier import MockNotifier

ON_SHIFT = ("In transit", "On site")  # Live Map statuses that count as "on shift"
POST_INCIDENT_STATUS = "Post-incident"
STOPPED_STATUS = "Stopped"

PRIVACY_NOTE = (
    "Privacy: location data is used only to raise safety alerts. A worker is told exactly why "
    "they were flagged (the check-in message states the reason), and every safety event is "
    "recorded in the audit log."
)


class SafetyError(Exception):
    """An action was refused (unknown worker, wrong state...). Carries an HTTP-ish status."""

    def __init__(self, message, status=409):
        super().__init__(message)
        self.status = status


def _iso(t):
    return None if t is None else datetime.fromtimestamp(t, timezone.utc).isoformat()


def _nearest_landmark(lat, lng):
    return min(LANDMARKS, key=lambda n: haversine(lat, lng, *LANDMARKS[n]))


def _where(w):
    """A human description of where a worker is, from their (pre-freeze) Live Map entry."""
    if w["lat"] is None:
        return "Location unknown"
    if w["status"] == "On site":
        return f"On site at {w['site_name']}"
    near = _nearest_landmark(w["lat"], w["lng"])
    if w["status"] == "In transit":
        return f"On the road to {w['site_name']}, near {near}"
    return f"Near {near}"


class SafetyService:
    def __init__(self, config=None, notifier=None, clock=time.time):
        self.config = config or SafetyConfig.from_env()
        self.seed = resolve_seed(self.config.seed)
        self.clock = clock
        self.audit = AuditLog(clock=clock)
        self.notifier = notifier or MockNotifier(self.config, clock=clock)
        self.roller = AccidentRoller(self.config, self.seed)
        self.planner = ReplyPlanner(self.config, self.seed)
        self._lock = threading.RLock()
        self._machines = {}
        self._incapacitated = set()  # accident victims: never answer a check-in
        self._frozen = {}  # worker_id -> {"pos": (lat, lng), "where": str}: stopped markers
        self._on_break = set()
        self._plans = {}  # worker_id -> (checkin key, reply time or None)
        self._seen = {}  # worker_id -> latest pre-freeze Live Map entry
        self._last_tick = None

    # ----- the poll -----

    def process(self, state, now=None):
        """Advance every worker's safety state from this Live Map `state`, and annotate it."""
        now = self.clock() if now is None else now
        with self._lock:
            self._check_poll_gap(now)
            for w in state["workers"]:
                self._tick_worker(w, now)
            self._annotate(state, now)
            self._last_tick = now
        return state

    def _check_poll_gap(self, now):
        if self._last_tick is None or now - self._last_tick <= self.config.max_poll_gap_seconds:
            return
        for m in self._machines.values():
            m.reset_watch(now, "monitoring was paused (no dashboard was open)")
        self._plans.clear()

    def _machine(self, ref):
        if ref.id not in self._machines:
            self._machines[ref.id] = SafetyMachine(ref, self.config, self.notifier, self.audit)
        return self._machines[ref.id]

    def _tick_worker(self, w, now):
        wid = w["id"]
        ref = WorkerRef(wid, w["name"])
        machine = self._machine(ref)
        self._seen[wid] = dict(w)  # the simulation's own view, before any override
        sim_pos = None if w["lat"] is None else (w["lat"], w["lng"])

        # Accident roll: active, moving (on the road), not already being handled.
        if (
            w["status"] == "In transit"
            and wid not in self._frozen
            and wid not in self._on_break
            and machine.state == NORMAL
            and self.roller.roll_if_due(wid, now)
        ):
            self._start_accident(ref, w, now, actor=None, source="random roll")

        frozen = self._frozen.get(wid)
        position = frozen["pos"] if frozen else sim_pos
        on_shift = bool(frozen) or w["status"] in ON_SHIFT

        # A simulated worker's reply, if it has come due, lands before we look at the clock.
        self._deliver_reply(machine, now)
        machine.observe(now, position, on_shift, on_break=wid in self._on_break)
        self._plan_reply(machine, wid)
        self._deliver_reply(machine, now)

    def _plan_reply(self, machine, wid):
        if not machine.in_checkin:
            self._plans.pop(wid, None)
            return
        key = (machine.checkin, machine.state_since)
        if wid in self._plans and self._plans[wid][0] == key:
            return
        reply_at = None
        if wid not in self._incapacitated:
            reply_at = self.planner.plan(wid, machine.checkin, machine.state_since)
        self._plans[wid] = (key, reply_at)

    def _deliver_reply(self, machine, now):
        plan = self._plans.get(machine.worker.id)
        if not plan or not machine.in_checkin:
            return
        key, reply_at = plan
        if (
            reply_at is not None
            and reply_at <= now
            and key == (machine.checkin, machine.state_since)
        ):
            machine.respond(reply_at)

    def _annotate(self, state, now):
        workers = state["workers"]
        for w in workers:
            wid = w["id"]
            machine = self._machines[wid]
            frozen = self._frozen.get(wid)
            w["sim_status"] = w["status"]
            if frozen:
                w.update(
                    lat=frozen["pos"][0],
                    lng=frozen["pos"][1],
                    near_traffic=False,
                    hotspot=None,
                    distance_remaining_m=None,
                    status=STOPPED_STATUS,
                )
                w.pop("path", None)
            if machine.state == EMERGENCY:
                w["status"] = "EMERGENCY"
            elif machine.state == POST_INCIDENT:
                w["status"] = POST_INCIDENT_STATUS
            zone = None if w["lat"] is None else self.config.break_zone_at(w["lat"], w["lng"])
            w["safety"] = {
                **machine.snapshot(now),
                "incident_started_at": _iso(machine.incident_started_at),
                "emergency_at": _iso(machine.emergency_at),
                "incapacitated": wid in self._incapacitated,
                "stopped": wid in self._frozen,
                "on_break": wid in self._on_break,
                "break_zone": zone.name if zone else None,
            }
        state["safety"] = {
            "config": self.config.to_dict(),
            "seed": self.seed,
            "privacy_note": PRIVACY_NOTE,
            "alerts": self._alerts(workers, now),
            "notifications": self.notifier.recent(60),
        }

    # ----- alerts -----

    def _alerts(self, workers, now):
        by_id = {w["id"]: w for w in workers}
        out = []
        for wid, m in self._machines.items():
            w = by_id.get(wid)
            if w is None or m.state == NORMAL:
                continue
            frozen = self._frozen.get(wid)
            pos = frozen["pos"] if frozen else m.position
            where = frozen["where"] if frozen else _where(self._seen.get(wid, w))
            if m.state == EMERGENCY:
                level, stage = "critical", "EMERGENCY"
            elif m.state == POST_INCIDENT:
                level, stage = "info", "Post-incident"
            else:
                level, stage = "warning", f"Check-in {m.checkin} of {self.config.num_checkins}"
            snap = m.snapshot(now)
            out.append(
                {
                    "worker_id": wid,
                    "worker_name": w["name"],
                    "state": m.state,
                    "stage": stage,
                    "level": level,
                    "trigger": m.trigger,
                    "incapacitated": wid in self._incapacitated,
                    "started_at": _iso(m.incident_started_at),
                    "elapsed_s": snap["elapsed_s"],
                    "window_remaining_s": snap["window_remaining_s"],
                    "location": {
                        "lat": pos[0] if pos else None,
                        "lng": pos[1] if pos else None,
                        "label": where,
                    },
                    "nearest_coworker": self._nearest_coworker(wid, pos, workers),
                    "resolution": m.resolution,
                }
            )
        order = {"critical": 0, "warning": 1, "info": 2}
        return sorted(out, key=lambda a: (order[a["level"]], a["started_at"] or ""))

    def _nearest_coworker(self, wid, pos, workers):
        """The closest co-worker who is on shift and free: not stopped, on break or in an incident."""
        if pos is None:
            return None
        best = None
        for w in workers:
            m = self._machines.get(w["id"])
            if (
                w["id"] == wid
                or w["lat"] is None
                or w["sim_status"] not in ON_SHIFT
                or w["id"] in self._frozen
                or w["id"] in self._on_break
                or (m and m.state in (EMERGENCY, POST_INCIDENT))
            ):
                continue
            d = haversine(pos[0], pos[1], w["lat"], w["lng"])
            if best is None or d < best["distance_m"]:
                best = {
                    "id": w["id"],
                    "name": w["name"],
                    "trade": w.get("trade"),
                    "distance_m": round(d),
                    "status": w["sim_status"],
                }
        return best

    # ----- actions (the supervisor's and the demo's controls) -----

    def _known(self, worker_id):
        w = self._seen.get(worker_id)
        if w is None:
            raise SafetyError("That worker was not found.", status=404)
        return w

    def _start_accident(self, ref, w, now, actor, source):
        pos = (w["lat"], w["lng"])
        self._incapacitated.add(ref.id)
        self._frozen[ref.id] = {"pos": pos, "where": _where(w)}
        self.audit.record(
            ref,
            "ACCIDENT",
            f"Accident ({source}): the worker stopped moving and cannot respond.",
            state=self._machines[ref.id].state,
            actor=actor,
            at=now,
        )
        self._plans.pop(ref.id, None)  # an open check-in will now go unanswered
        if self._machines[ref.id].state == NORMAL:
            # Idle timing starts from the accident, not from whenever the worker last moved.
            self._machines[ref.id].reset_watch(now, "accident")

    def trigger_accident(self, worker_id, actor=None, now=None):
        now = self.clock() if now is None else now
        with self._lock:
            w = self._known(worker_id)
            if worker_id in self._frozen:
                raise SafetyError(f"{w['name']} has already stopped.")
            if w["status"] not in ON_SHIFT:
                raise SafetyError(f"{w['name']} is not on shift ({w['status']}).")
            self._start_accident(WorkerRef(worker_id, w["name"]), w, now, actor, "manual trigger")

    def sos(self, worker_id, actor=None, now=None):
        now = self.clock() if now is None else now
        with self._lock:
            w = self._known(worker_id)
            machine = self._machines[worker_id]
            if machine.state == EMERGENCY:
                raise SafetyError(f"{w['name']} is already in an emergency.")
            if worker_id not in self._frozen:
                if w["status"] not in ON_SHIFT:
                    raise SafetyError(f"{w['name']} is not on shift ({w['status']}).")
                self._frozen[worker_id] = {"pos": (w["lat"], w["lng"]), "where": _where(w)}
            machine.sos(now, self._frozen[worker_id]["pos"])

    def respond(self, worker_id, now=None):
        """The worker answers "I'm OK" from the worker view. Returns True if it cleared a check-in."""
        now = self.clock() if now is None else now
        with self._lock:
            w = self._known(worker_id)
            if worker_id in self._incapacitated:
                raise SafetyError(f"{w['name']} is incapacitated and cannot reply.")
            return self._machines[worker_id].respond(now)

    def set_break(self, worker_id, on_break, actor=None, now=None):
        now = self.clock() if now is None else now
        with self._lock:
            w = self._known(worker_id)
            if on_break == (worker_id in self._on_break):
                return
            ref = WorkerRef(worker_id, w["name"])
            machine = self._machines[worker_id]
            if on_break:
                self._on_break.add(worker_id)
                self.audit.record(
                    ref, "BREAK_STARTED", "Worker marked on break.", machine.state, actor, now
                )
            else:
                self._on_break.discard(worker_id)
                self.audit.record(
                    ref, "BREAK_ENDED", "Worker back from break.", machine.state, actor, now
                )
            machine.reset_watch(now, "worker started or ended a break")

    def resolve(self, worker_id, outcome, note="", actor=None, now=None):
        now = self.clock() if now is None else now
        with self._lock:
            self._known(worker_id)
            try:
                new_state = self._machines[worker_id].resolve(now, outcome, note, actor)
            except ValueError as err:
                raise SafetyError(str(err)) from err
            if new_state == NORMAL:  # false alarm: the worker carries on
                self._release(worker_id)

    def return_to_duty(self, worker_id, actor=None, now=None):
        now = self.clock() if now is None else now
        with self._lock:
            self._known(worker_id)
            try:
                self._machines[worker_id].return_to_duty(now, actor)
            except ValueError as err:
                raise SafetyError(str(err)) from err
            self._release(worker_id)

    def _release(self, worker_id):
        self._incapacitated.discard(worker_id)
        self._frozen.pop(worker_id, None)
        self._plans.pop(worker_id, None)

    def audit_entries(self, worker_id=None):
        return self.audit.entries(worker_id)
