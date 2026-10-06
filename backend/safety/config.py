"""Every tunable of the safety feature, in one place (no magic numbers elsewhere).

Pick a preset with one setting:  SAFETY_MODE=real | demo   (environment or backend/.env).
Any single field can still be overridden with SAFETY_<FIELD>, e.g. SAFETY_AUTO_RESPOND_CHANCE=0.5.
All durations are real (wall-clock) seconds.
"""

import os
from dataclasses import dataclass, fields, replace

from geofence import haversine
from simulation import CYCLE_SECONDS, SIM_DAY_END, SIM_DAY_START

# The simulation squeezes (SIM_DAY_END - SIM_DAY_START) minutes into CYCLE_SECONDS real seconds,
# so one *simulated* hour lasts this many real seconds.
SIMULATED_HOUR_SECONDS = 60 * CYCLE_SECONDS / (SIM_DAY_END - SIM_DAY_START)


@dataclass(frozen=True)
class BreakZone:
    """A rest area: a worker standing inside it is never treated as idle.

    Build one with BreakZone.circle(name, lat, lng, radius_m) or
    BreakZone.rect(name, south, west, north, east).
    """

    name: str
    kind: str  # "circle" or "rect"
    shape: tuple

    @classmethod
    def circle(cls, name, lat, lng, radius_m):
        return cls(name, "circle", (lat, lng, radius_m))

    @classmethod
    def rect(cls, name, south, west, north, east):
        return cls(name, "rect", (south, west, north, east))

    def contains(self, lat, lng):
        if self.kind == "circle":
            c_lat, c_lng, radius_m = self.shape
            return haversine(lat, lng, c_lat, c_lng) <= radius_m
        south, west, north, east = self.shape
        return south <= lat <= north and west <= lng <= east

    def to_dict(self):
        return {"name": self.name, "kind": self.kind, "shape": list(self.shape)}


# Example rest areas. Add your own here (or pass break_zones=... to SafetyConfig).
DEFAULT_BREAK_ZONES = (
    BreakZone.circle("Thamel tea-house rest area", 27.7154, 85.3123, 120),
    BreakZone.rect("Patan depot canteen", 27.6650, 85.3195, 27.6662, 85.3215),
)


@dataclass(frozen=True)
class SafetyConfig:
    # How long a worker on shift must stay put before check-ins begin.
    idle_threshold_seconds: float = 600
    # Time allowed to answer each check-in before the next one (or the emergency) follows.
    checkin_response_window_seconds: float = 120
    num_checkins: int = 3
    # Chance of an accident, rolled once per worker per accident_roll_interval_seconds.
    accident_probability: float = 0.01
    accident_roll_interval_seconds: float = SIMULATED_HOUR_SECONDS
    # Chance that a fine-but-idle simulated worker answers "I'm OK" to a given check-in.
    auto_respond_chance: float = 0.85
    # Moving less than this counts as stationary (GPS jitter).
    idle_distance_tolerance_m: float = 15
    # Monitoring is driven by the dashboard's polling. If nobody polled for longer than this, the
    # idle timers restart instead of racing through the missed time (which would raise false alarms).
    max_poll_gap_seconds: float = 10
    break_zones: tuple = DEFAULT_BREAK_ZONES
    # Seed for the random generators (accidents, auto-replies). None = a different run each time.
    seed: int | None = None
    mode: str = "custom"

    def __post_init__(self):
        if self.num_checkins < 1:
            raise ValueError("num_checkins must be at least 1")
        if not 0 <= self.accident_probability <= 1 or not 0 <= self.auto_respond_chance <= 1:
            raise ValueError("probabilities must be between 0 and 1")

    def break_zone_at(self, lat, lng):
        """The break zone covering this point, or None."""
        return next((z for z in self.break_zones if z.contains(lat, lng)), None)

    def to_dict(self):
        return {
            "mode": self.mode,
            "idle_threshold_seconds": self.idle_threshold_seconds,
            "checkin_response_window_seconds": self.checkin_response_window_seconds,
            "num_checkins": self.num_checkins,
            "accident_probability": self.accident_probability,
            "accident_roll_interval_seconds": self.accident_roll_interval_seconds,
            "auto_respond_chance": self.auto_respond_chance,
            "idle_distance_tolerance_m": self.idle_distance_tolerance_m,
            "break_zones": [z.to_dict() for z in self.break_zones],
            "seed": self.seed,
        }

    @classmethod
    def from_mode(cls, mode="real", seed=None, **overrides):
        """Build the config for a preset ("real" or "demo"), then apply field overrides."""
        if mode not in PRESETS:
            raise ValueError(f"Unknown SAFETY_MODE {mode!r}; use one of {', '.join(PRESETS)}.")
        return cls(**{**PRESETS[mode], "mode": mode, "seed": seed, **overrides})

    @classmethod
    def from_env(cls, environ=None):
        """SAFETY_MODE (default "real"), SAFETY_SEED, and optional SAFETY_<FIELD> overrides."""
        env = os.environ if environ is None else environ
        seed = env.get("SAFETY_SEED")
        overrides = {}
        for f in fields(cls):
            raw = env.get(f"SAFETY_{f.name.upper()}")
            if raw is None or f.name in ("mode", "seed", "break_zones"):
                continue
            overrides[f.name] = int(raw) if f.name == "num_checkins" else float(raw)
        return cls.from_mode(
            env.get("SAFETY_MODE", "real").strip().lower(),
            seed=int(seed) if seed not in (None, "") else None,
            **overrides,
        )

    def with_changes(self, **changes):
        return replace(self, **changes)


PRESETS = {
    # Believable for a real site: 10 minutes still, then three 2-minute check-ins.
    "real": {"idle_threshold_seconds": 600, "checkin_response_window_seconds": 120},
    # Fast enough for a live demo: 15 s still, then three 5 s check-ins (emergency after ~30 s).
    "demo": {"idle_threshold_seconds": 15, "checkin_response_window_seconds": 5},
}
