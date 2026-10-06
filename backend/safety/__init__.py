"""Safety / emergency escalation for simulated workers (man-down detection).

Layout (each piece is usable and testable on its own):
  config.py     one SafetyConfig, the "real" and "demo" presets, break zones
  machine.py    the per-worker escalation state machine (no I/O of its own)
  notifier.py   Notifier interface + MockNotifier (in-app feed and console, no real calls)
  audit.py      the audit log of every safety event (JSON / CSV export)
  behaviour.py  simulated-worker behaviour: random accidents and "I'm OK" replies
  service.py    ties them to the live map: one machine per worker, driven by each poll
"""

from .config import PRESETS, BreakZone, SafetyConfig
from .machine import SafetyMachine
from .notifier import MockNotifier, Notifier
from .service import SafetyService

__all__ = [
    "PRESETS",
    "BreakZone",
    "MockNotifier",
    "Notifier",
    "SafetyConfig",
    "SafetyMachine",
    "SafetyService",
]
