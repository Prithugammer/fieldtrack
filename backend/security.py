"""HTTP-level hardening: login throttling and security response headers."""

import math
import threading
import time
from collections import deque

from flask import request


class LoginRateLimiter:
    """Sliding-window limiter for FAILED sign-ins.

    Three counters, each over the last `window` seconds:

      * (account, client)  `max_per_account`        5  - stops one machine guessing one password list
      * account (any client) `max_per_account_total` 25 - stops a guesser who rotates addresses
      * client (any account) `max_per_client`       20  - stops one machine spraying many accounts

    Why the pair counter: with a plain per-account counter, anybody could type five wrong passwords for
    your colleague's email and lock the real owner out. Now those five failures only block the
    ATTACKER's address for that account; the owner, at another address, is unaffected. The account-wide
    ceiling is higher (an attacker would need 25 failures from several addresses to lock the owner out
    for a while - temporary, and the owner can still use any address that has not failed).

    Only failures are recorded. Blocked attempts are not, so a block never extends itself and nothing is
    ever locked permanently. The key is the submitted email whether or not the account exists.
    State is in this process's memory (see README, Deployment notes).
    """

    MAX_KEYS = 10_000  # bounds memory against an attacker spraying random emails

    def __init__(
        self,
        max_per_account,
        max_per_client,
        window,
        clock=time.monotonic,
        max_per_account_total=None,
    ):
        self.max_per_account = max_per_account
        self.max_per_client = max_per_client
        self.max_per_account_total = max_per_account_total or max(
            max_per_account * 5, max_per_account
        )
        self.window = window
        self.clock = clock
        self._failures = {}  # key -> deque of failure times
        self._lock = threading.Lock()

    def _keys(self, email, client):
        email = (email or "")[:120].lower().strip()
        client = client or "unknown"
        return (
            (("pair", email, client), self.max_per_account),
            (("acct", email), self.max_per_account_total),
            (("ip", client), self.max_per_client),
        )

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
        wait = 0.0
        with self._lock:
            for key, limit in self._keys(email, client):
                times = self._live(key, now)
                if times is not None and len(times) >= limit:
                    # The block lifts when enough old failures expire to drop below the limit.
                    wait = max(wait, times[len(times) - limit] + self.window - now)
        return max(1, math.ceil(wait)) if wait > 0 else 0

    def record_failure(self, email, client):
        now = self.clock()
        with self._lock:
            for key, _limit in self._keys(email, client):
                self._failures.setdefault(key, deque()).append(now)
            if len(self._failures) > self.MAX_KEYS:
                self._evict(now)

    def reset_account(self, email, client=None):
        """A correct password clears that account's failure counters (the client's spray count stays)."""
        email = (email or "")[:120].lower().strip()
        with self._lock:
            self._failures.pop(("acct", email), None)
            for key in [k for k in self._failures if k[0] == "pair" and k[1] == email]:
                del self._failures[key]

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
