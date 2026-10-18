"""Safety / emergency escalation for simulated workers (man-down detection).

Layout (each piece is usable and testable on its own):
  config.py     one SafetyConfig, the "real" and "demo" presets, break zones
  machine.py    the per-worker escalation state machine (no I/O of its own)
  notifier.py   Notifier interface + MockNotifier (in-app feed and console, no real calls)
  audit.py      the audit log of every safety event (JSON / CSV export)
  behaviour.py  simulated-worker behaviour: random accidents and "I'm OK" replies
  service.py    ties them to the live map: one machine per worker, advanced by process()
  store.py      database tables that make safety state survive a restart
  ticker.py     backend heartbeat that calls process() so escalation never needs a browser
"""

from .config import PRESETS, BreakZone, SafetyConfig
from .machine import SafetyMachine
from .notifier import MockNotifier, Notifier
from .service import SafetyService
from .store import SafetyStore
from .ticker import SafetyTicker, start_background_services

__all__ = [
    "PRESETS",
    "BreakZone",
    "MockNotifier",
    "Notifier",
    "SafetyConfig",
    "SafetyMachine",
    "SafetyService",
    "SafetyStore",
    "SafetyTicker",
    "start_background_services",
]
