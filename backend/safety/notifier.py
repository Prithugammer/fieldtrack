"""Notifications: an interface, plus a MOCK that never contacts anyone.

To go live, subclass Notifier (for example a TwilioNotifier that sends an SMS in send_checkin
and places a call in call_emergency_services) and hand it to SafetyService(notifier=...).
Nothing else in the safety code needs to change.
"""

import logging
import sys
import time
from abc import ABC, abstractmethod
from collections import deque
from datetime import datetime, timezone

log = logging.getLogger("fieldtrack.safety")
if not log.handlers:
    _handler = logging.StreamHandler(sys.stdout)
    _handler.setFormatter(logging.Formatter("%(asctime)s [SAFETY] %(message)s", "%H:%M:%S"))
    log.addHandler(_handler)
    log.setLevel(logging.INFO)
    log.propagate = False


class Notifier(ABC):
    """What the escalation needs to be able to do. `worker` has .id and .name."""

    @abstractmethod
    def send_checkin(self, worker, n, at=None):
        """Message the worker: check-in number `n` ("are you OK?")."""

    @abstractmethod
    def alert_supervisor(self, worker, level, message=None, at=None):
        """Alert the supervisor/dispatcher. `level` is "warning" or "critical"."""

    @abstractmethod
    def call_emergency_services(self, worker, location, at=None):
        """Place the call to emergency services. `location` is (lat, lng) or None."""


class MockNotifier(Notifier):
    """Writes every notification to an in-app feed and to the console. Calls nobody."""

    def __init__(self, config, max_items=300, clock=time.time):
        self.config = config
        self.clock = clock
        self.feed = deque(maxlen=max_items)
        self._next_id = 1

    def _emit(self, channel, level, worker, text, at):
        ts = self.clock() if at is None else at
        item = {
            "id": self._next_id,
            "t": ts,
            "time": datetime.fromtimestamp(ts, timezone.utc).isoformat(),
            "channel": channel,  # "worker", "supervisor" or "emergency_services"
            "level": level,
            "worker_id": worker.id,
            "worker_name": worker.name,
            "text": text,
        }
        self._next_id += 1
        self.feed.append(item)
        log.info("%s -> %s [%s] %s", worker.name, channel, level, text)
        return item

    def send_checkin(self, worker, n, at=None):
        cfg = self.config
        text = (
            f"Safety check-in {n} of {cfg.num_checkins}: you have not moved for "
            f'{cfg.idle_threshold_seconds:g} s while on shift. Are you OK? Reply "I\'m OK" '
            f"within {cfg.checkin_response_window_seconds:g} s or your supervisor will be alerted."
        )
        return self._emit("worker", "info", worker, text, at)

    def alert_supervisor(self, worker, level, message=None, at=None):
        default = (
            f"{worker.name} has been stationary and has not answered a safety check-in."
            if level == "warning"
            else f"EMERGENCY: {worker.name} needs help."
        )
        return self._emit("supervisor", level, worker, message or default, at)

    def call_emergency_services(self, worker, location, at=None):
        where = f"{location[0]:.5f}, {location[1]:.5f}" if location else "unknown location"
        text = (
            f"[MOCK - no real call placed] Calling emergency services for {worker.name} at {where}."
        )
        return self._emit("emergency_services", "critical", worker, text, at)

    def since(self, last_id):
        return [i for i in self.feed if i["id"] > last_id]

    def load(self, items):
        self.feed.extend(dict(i) for i in items)
        if items:
            self._next_id = max(self._next_id, max(i["id"] for i in items) + 1)

    def drop_after(self, last_id):
        while self.feed and self.feed[-1]["id"] > last_id:
            self.feed.pop()
        self._next_id = last_id + 1

    def last_id(self):
        return self._next_id - 1

    def recent(self, limit=60):
        """Newest first."""
        return list(self.feed)[::-1][:limit]
