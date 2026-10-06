"""How SIMULATED workers behave: random accidents, and whether a fine-but-idle one answers.

Every random decision comes from a generator seeded with (seed, worker, moment), so with a fixed
seed a demo or a test plays out identically no matter how often the page polls.
"""

import random
import secrets

# A worker who is going to answer a check-in does so this fraction of the way through the window.
REPLY_DELAY_MIN, REPLY_DELAY_MAX = 0.2, 0.7


def resolve_seed(seed):
    """A fixed seed stays as is; None becomes a random one (reported, so a run can be repeated)."""
    return secrets.randbits(31) if seed is None else seed


class AccidentRoller:
    """Rolls ACCIDENT_PROBABILITY once per worker per accident_roll_interval_seconds."""

    def __init__(self, config, seed):
        self.config = config
        self.seed = seed
        self._last_interval = {}  # worker_id -> the interval index already rolled

    def interval_index(self, now):
        return int(now // self.config.accident_roll_interval_seconds)

    def roll_if_due(self, worker_id, now):
        """True = accident, False = rolled and fine, None = already rolled this interval."""
        index = self.interval_index(now)
        if self._last_interval.get(worker_id) == index:
            return None
        self._last_interval[worker_id] = index
        rng = random.Random(f"{self.seed}:accident:{worker_id}:{index}")
        return rng.random() < self.config.accident_probability

    def forget(self, worker_id):
        self._last_interval.pop(worker_id, None)


class ReplyPlanner:
    """Decides, for each check-in sent to a simulated worker, if and when they answer."""

    def __init__(self, config, seed):
        self.config = config
        self.seed = seed

    def plan(self, worker_id, checkin, sent_at):
        """The time the worker will reply, or None if they will not."""
        rng = random.Random(f"{self.seed}:reply:{worker_id}:{checkin}:{sent_at:.3f}")
        replies = rng.random() < self.config.auto_respond_chance
        delay = rng.uniform(REPLY_DELAY_MIN, REPLY_DELAY_MAX)
        window = self.config.checkin_response_window_seconds
        return sent_at + window * delay if replies else None
