"""A backend-owned heartbeat for safety monitoring.

Escalation (idle detection, check-in windows, emergencies) must keep advancing when nobody has the
dashboard open, so it cannot be driven by browser requests. `SafetyTicker` runs inside the server
process: once per `interval` seconds it computes the current Live Map state and feeds it to the
`SafetyService`, exactly as a dashboard poll used to do.

Why this is safe to run alongside HTTP traffic:
  * `SafetyService.process()` holds one lock for the whole update, and every transition is stamped
    with the moment it was *due* (idle start + threshold, previous deadline + window...), not the
    moment it was noticed. Running it twice, or from several threads, replays the same transitions
    once: the state machine is idempotent for a given time, so a manual `POST /api/safety/tick`, a
    safety action, and this thread can interleave without duplicating an event.
  * A failing tick (database hiccup, simulation error) is logged and counted, never raised, so the
    heartbeat keeps going.

Limits (see docs): state lives in this process's memory and is lost on restart; run exactly one
server process (a second process would keep its own, separate safety state).
"""

import logging
import os
import threading
import uuid

from extensions import db

log = logging.getLogger("fieldtrack.safety.ticker")


def _live_state():
    from routes.map import (
        compute_live_state,
    )  # imported late: routes depend on safety, not vice versa

    return compute_live_state()


class SafetyTicker:
    def __init__(self, app, interval=1.0, state_source=None):
        self.app = app
        self.holder = f"{os.getpid()}-{uuid.uuid4().hex[:8]}"  # who owns the lease (see tick_once)
        self.is_leader = None  # None until the first tick
        self.skipped = 0
        self.interval = interval
        self._state_source = state_source or _live_state
        self._stop = threading.Event()
        self._thread = None
        self._lock = threading.Lock()
        self.ticks = 0
        self.errors = 0
        self.last_error = None  # short description only (no stack, no data)

    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive()

    def tick_once(self, now=None):
        """Advance safety state once. Returns True on success, False if the tick failed."""
        try:
            with self.app.app_context():
                service = self.app.extensions["safety"]
                if service.store is not None and not self._lead(service):
                    self.skipped += 1
                    return True  # another process owns the heartbeat; this one stays idle
                state = self._state_source()
                service.process(state, now=now)
                db.session.remove()
            self.ticks += 1
            return True
        except Exception as exc:  # noqa: BLE001 - the heartbeat must survive any single failure
            self.errors += 1
            self.last_error = type(exc).__name__
            if self.errors == 1 or self.errors % 60 == 0:  # first failure, then once a minute
                log.exception("Safety tick failed (%d failure(s) so far)", self.errors)
            return False

    def _lead(self, service):
        """Hold (or renew) the heartbeat lease. Only one process at a time may advance escalation.

        On taking the lease from another process, reload the state it saved, so that process's
        open emergencies are continued rather than forgotten or repeated.
        """
        ttl = max(3.0, self.interval * 3)  # a crashed leader is replaced after about this long
        owns = service.store.acquire_lease("heartbeat", self.holder, ttl)
        if owns and self.is_leader is False:
            log.warning("Took over the safety heartbeat; reloading saved state")
            service.reload()
        if owns != self.is_leader:
            log.info("Safety heartbeat %s", "acquired" if owns else "held by another process")
        self.is_leader = owns
        return owns

    def _run(self):
        self.tick_once()
        while not self._stop.wait(self.interval):
            self.tick_once()

    def start(self):
        """Start the heartbeat thread (no-op if it is already running)."""
        with self._lock:
            if self.running:
                return
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name="safety-ticker", daemon=True)
            self._thread.start()
            log.info("Safety monitoring started (every %.2f s)", self.interval)

    def stop(self, timeout=5.0):
        with self._lock:
            self._stop.set()
            thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout)
        if self.is_leader:
            try:
                with self.app.app_context():
                    self.app.extensions["safety"].store.release_lease("heartbeat", self.holder)
                    db.session.remove()
            except Exception:  # noqa: BLE001 - best effort; the lease expires by itself
                pass
            self.is_leader = None
            log.info("Safety monitoring stopped")


def start_background_services(app):
    """Start the safety heartbeat for a real server process.

    Not called by `create_app()` itself, so tests, the seed script and one-off tools never get a
    background thread. `app.py` calls it for `python app.py`; `wsgi.py` for a WSGI server.
    Does nothing when SAFETY_TICKER_ENABLED is off or in TESTING mode. Returns the ticker or None.
    """
    if not app.config.get("SAFETY_TICKER_ENABLED") or app.config.get("TESTING"):
        return None
    existing = app.extensions.get("safety_ticker")
    if existing is not None:
        existing.start()
        return existing
    ticker = SafetyTicker(app, interval=app.config["SAFETY_TICK_INTERVAL_SECONDS"])
    app.extensions["safety_ticker"] = ticker
    ticker.start()
    return ticker
