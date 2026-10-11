"""HTTP-level hardening: login throttling and security response headers."""

import math
import threading
import time
from collections import deque

from flask import request


class LoginRateLimiter:
    """Sliding-window limiter for FAILED sign-ins, per account and per client address.

    * Only failures are recorded. Once an account (the submitted email) or a client address has
      `max_*` failures inside `window` seconds, further attempts are refused with a retry delay
      until the oldest failure leaves the window. Refused attempts are NOT recorded, so a block
      never extends itself and an account can never be locked out permanently.
    * The key is the submitted email whether or not the account exists, so the response does not
      reveal which emails are real.
    * State is in this process's memory. With several worker processes each keeps its own
      counters (the effective limit is multiplied by the number of workers) and a restart clears
      them. Use a reverse-proxy limit or a shared store (e.g. Redis) when that matters.
    """

    MAX_KEYS = 10_000  # bounds memory against an attacker spraying random emails

    def __init__(self, max_per_account, max_per_client, window, clock=time.monotonic):
        self.max_per_account = max_per_account
        self.max_per_client = max_per_client
        self.window = window
        self.clock = clock
        self._failures = {}  # ("acct", email) / ("ip", address) -> deque of failure times
        self._lock = threading.Lock()

    @staticmethod
    def _keys(email, client):
        return ("acct", (email or "")[:120].lower()), ("ip", client or "unknown")

    def _live(self, key, now):
        """The still-in-window failure times for `key` (expired ones are dropped)."""
        times = self._failures.get(key)
        if times is None:
            return None
        while times and now - times[0] >= self.window:
            times.popleft()
        if not times:
            del self._failures[key]
            return None
        return times

    def retry_after(self, email, client):
        """Seconds until another attempt is allowed, or 0 if it may go ahead now."""
        now = self.clock()
        acct_key, ip_key = self._keys(email, client)
        wait = 0.0
        with self._lock:
            for key, limit in ((acct_key, self.max_per_account), (ip_key, self.max_per_client)):
                times = self._live(key, now)
                if times is not None and len(times) >= limit:
                    # The block lifts when enough old failures expire to drop below the limit.
                    release = times[len(times) - limit] + self.window - now
                    wait = max(wait, release)
        return max(1, math.ceil(wait)) if wait > 0 else 0

    def record_failure(self, email, client):
        now = self.clock()
        with self._lock:
            for key in self._keys(email, client):
                self._failures.setdefault(key, deque()).append(now)
            if len(self._failures) > self.MAX_KEYS:
                self._evict(now)

    def reset_account(self, email):
        """A correct password clears that account's failures (the client's count stays)."""
        with self._lock:
            self._failures.pop(self._keys(email, None)[0], None)

    def _evict(self, now):
        for key in list(self._failures):
            self._live(key, now)
        while len(self._failures) > self.MAX_KEYS:
            oldest = min(self._failures, key=lambda k: self._failures[k][-1])
            del self._failures[oldest]


def client_address():
    """The caller's address. Behind a proxy, TRUSTED_PROXY_COUNT makes this the real client."""
    return request.remote_addr or "unknown"


# The API only ever returns JSON/CSV, so it can forbid everything a browser might otherwise do
# with a response (scripts, framing, subresources). The React app is served separately and needs
# its own CSP from whatever serves it (see README "Deployment notes").
API_CSP = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"


def register_security_headers(app):
    """Add the standard hardening headers to every response."""

    @app.after_request
    def add_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Content-Security-Policy", API_CSP)
        # Responses carry personal data and live safety state: never let a cache keep them.
        response.headers.setdefault("Cache-Control", "no-store")
        if app.config.get("HSTS_ENABLED") and request.is_secure:
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
        return response
