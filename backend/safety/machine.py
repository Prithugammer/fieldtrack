"""The per-worker escalation state machine. It does no I/O of its own and never reads the clock:
every method is told the time (`now`), the worker's position and whether they are on shift, and
it reports through the injected `notifier` and `audit` objects. That keeps it unit-testable.

    NORMAL -> CHECKIN_1 -> CHECKIN_2 -> ... -> CHECKIN_n -> EMERGENCY
                 ^ back to NORMAL when the worker replies "I'm OK" or starts moving

  * NORMAL:   watching. The worker has been still for less than the idle threshold (or is
              moving, clocked out, on a break, or inside a break zone).
  * CHECKIN_k: still for the idle threshold. Check-in k was sent; each unanswered window moves
              to the next check-in, and an unanswered last one declares the emergency.
  * EMERGENCY: locked until a supervisor resolves it. The worker is still tracked and shown.
  * POST_INCIDENT: after a supervisor resolves a REAL incident. Marked on the map, not watched
              for idleness (they are being attended to) until a supervisor returns them to duty.
              A resolved FALSE ALARM goes straight back to NORMAL.

Timestamps of automatic transitions are the moment they were *due* (e.g. idle start + threshold),
not the moment we noticed, so the log is right even if nobody polled for a while.
"""

from collections import namedtuple

from geofence import haversine

NORMAL = "NORMAL"
EMERGENCY = "EMERGENCY"
POST_INCIDENT = "POST_INCIDENT"

OUTCOMES = {"false_alarm": "Resolved - false alarm", "real_incident": "Resolved - real incident"}

WorkerRef = namedtuple("WorkerRef", "id name")


def checkin_state(n):
    return f"CHECKIN_{n}"


class SafetyMachine:
    def __init__(self, worker, config, notifier, audit):
        self.worker = worker
        self.config = config
        self.notifier = notifier
        self.audit = audit
        self.state = NORMAL
        self.checkin = 0  # number of the current check-in (0 when not in a check-in)
        self.position = None  # last known (lat, lng)
        self.state_since = None  # when the current state was entered
        self.incident_started_at = None  # idle detected / SOS: start of the current escalation
        self.trigger = None  # "idle" or "sos"
        self.emergency_at = None
        self.resolution = None
        self._anchor = None  # where the worker last "moved to"
        self._anchor_since = None  # ...and since when they have stayed within tolerance of it

    # ----- queries -----

    @property
    def in_checkin(self):
        return self.checkin > 0

    @property
    def active(self):
        return self.state != NORMAL

    def window_deadline(self):
        if not self.in_checkin:
            return None
        return self.state_since + self.config.checkin_response_window_seconds

    def snapshot(self, now):
        deadline = self.window_deadline()
        return {
            "state": self.state,
            "checkin": self.checkin,
            "trigger": self.trigger,
            "incident_started_at": self.incident_started_at,
            "elapsed_s": (
                None
                if self.incident_started_at is None
                else max(0.0, now - self.incident_started_at)
            ),
            "window_remaining_s": None if deadline is None else max(0.0, deadline - now),
            "emergency_at": self.emergency_at,
            "resolution": self.resolution,
        }

    # ----- inputs -----

    def observe(self, now, position, on_shift, on_break=False):
        """Feed the worker's latest position. Call it as often as you like."""
        if position is not None:
            self.position = position
        if self.state in (EMERGENCY, POST_INCIDENT):
            return  # locked / being attended to: keep tracking, never auto-change

        zone = self.config.break_zone_at(*position) if position is not None else None
        if not on_shift or on_break or zone or position is None:
            if self.in_checkin:
                why = (
                    f"worker entered rest area '{zone.name}'"
                    if zone
                    else "worker is off shift or on a break"
                )
                self._clear(now, why)
            self._reset_anchor(now, position)
            return

        tolerance = self.config.idle_distance_tolerance_m
        if self._anchor is None or haversine(*position, *self._anchor) > tolerance:
            if self.in_checkin:
                self._clear(now, "worker started moving")
            self._reset_anchor(now, position)
            return

        # Still stationary. Walk through every transition that has fallen due.
        if self.state == NORMAL:
            idle_at = self._anchor_since + self.config.idle_threshold_seconds
            if now < idle_at:
                return
            self.incident_started_at = idle_at
            self.trigger = "idle"
            self._audit(
                "IDLE_DETECTED",
                f"No movement for {self.config.idle_threshold_seconds:g} s while on shift.",
                idle_at,
            )
            self._enter_checkin(1, idle_at)
        while self.in_checkin and now >= self.window_deadline():
            due = self.window_deadline()
            self._audit(
                "CHECKIN_UNANSWERED", f"Check-in {self.checkin} was not answered in time.", due
            )
            if self.checkin < self.config.num_checkins:
                self._enter_checkin(self.checkin + 1, due)
            else:
                self._declare_emergency(due)

    def reset_watch(self, now, why):
        """Restart idle timing from scratch (monitoring was paused). Locked states are untouched."""
        if self.state in (EMERGENCY, POST_INCIDENT):
            return
        if self.in_checkin:
            self._clear(now, why)
        self._reset_anchor(now, self.position)

    def respond(self, now):
        """The worker replied "I'm OK". Returns True if that cleared an open check-in."""
        if self.in_checkin:
            self._audit("CHECKIN_RESPONSE", 'Worker replied "I\'m OK".', now)
            self._clear(now, 'worker replied "I\'m OK"', log=False)
            self._reset_anchor(now, self.position)
            return True
        if self.state == EMERGENCY:
            self._audit(
                "EMERGENCY_RESPONSE_IGNORED",
                'Worker replied "I\'m OK" but the emergency stays locked until a supervisor '
                "resolves it.",
                now,
            )
        return False

    def sos(self, now, position=None):
        """The worker pressed SOS: straight to EMERGENCY from anywhere. False if already there."""
        if position is not None:
            self.position = position
        if self.state == EMERGENCY:
            return False
        self._audit("SOS", "Worker pressed the SOS button.", now)
        self.incident_started_at = now
        self.trigger = "sos"
        self.checkin = 0
        self._declare_emergency(now)
        return True

    def resolve(self, now, outcome, note="", by=None):
        """A supervisor closes the emergency. Returns the new state."""
        if self.state != EMERGENCY:
            raise ValueError("This worker is not in an emergency.")
        if outcome not in OUTCOMES:
            raise ValueError(f"outcome must be one of: {', '.join(OUTCOMES)}.")
        self.resolution = {"outcome": outcome, "note": note, "by": by, "at": now}
        note_text = f" Note: {note}" if note else ""
        self._audit("RESOLVED", f"{OUTCOMES[outcome]}.{note_text}", now, actor=by)
        self._set_state(POST_INCIDENT if outcome == "real_incident" else NORMAL, now)
        self.checkin = 0
        self.emergency_at = None
        if self.state == NORMAL:
            self.incident_started_at = self.trigger = None
        self._reset_anchor(now, self.position)
        return self.state

    def return_to_duty(self, now, by=None):
        """A supervisor clears a post-incident worker back to normal monitoring."""
        if self.state != POST_INCIDENT:
            raise ValueError("This worker is not marked post-incident.")
        self._audit("RETURN_TO_DUTY", "Worker returned to duty after the incident.", now, actor=by)
        self._set_state(NORMAL, now)
        self.incident_started_at = self.trigger = None
        self._reset_anchor(now, self.position)

    # ----- internals -----

    def _audit(self, event, message, at, actor=None):
        self.audit.record(self.worker, event, message, state=self.state, actor=actor, at=at)

    def _set_state(self, state, at):
        self.state = state
        self.state_since = at

    def _reset_anchor(self, now, position):
        self._anchor = position
        self._anchor_since = now

    def _enter_checkin(self, n, at):
        self.checkin = n
        self._set_state(checkin_state(n), at)
        self.notifier.send_checkin(self.worker, n, at=at)
        self._audit("CHECKIN_SENT", f"Check-in {n} of {self.config.num_checkins} sent.", at)
        if n == 1:
            self.notifier.alert_supervisor(self.worker, "warning", at=at)
            self._audit("SUPERVISOR_ALERT", "Warning sent to the supervisor.", at)

    def _declare_emergency(self, at):
        self.checkin = 0
        self._set_state(EMERGENCY, at)
        self.emergency_at = at
        why = "SOS pressed" if self.trigger == "sos" else "three unanswered check-ins"
        self._audit("EMERGENCY", f"Worker status set to EMERGENCY ({why}).", at)
        self.notifier.alert_supervisor(self.worker, "critical", at=at)
        self._audit("SUPERVISOR_ALERT", "Critical alert sent to the supervisor.", at)
        self.notifier.call_emergency_services(self.worker, self.position, at=at)
        self._audit(
            "EMERGENCY_CALL", "MOCK call placed to emergency services (no real call made).", at
        )

    def _clear(self, now, why, log=True):
        """Back to NORMAL from a check-in: the false alarm is logged as cleared."""
        n = self.checkin
        if log:
            self._audit("CHECKIN_CLEARED", f"Check-in {n} cleared: {why}.", now)
        self.checkin = 0
        self.incident_started_at = self.trigger = None
        self._set_state(NORMAL, now)
