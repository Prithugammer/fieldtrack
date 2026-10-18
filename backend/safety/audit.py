"""The audit log: one timestamped record for every safety event, exportable as JSON or CSV."""

import csv
import io
import threading
import time
from collections import deque
from datetime import datetime, timezone

CSV_COLUMNS = ["id", "time", "worker_id", "worker_name", "event", "state", "message", "actor"]


class AuditLog:
    def __init__(self, max_items=5000, clock=time.time):
        self.clock = clock
        self._items = deque(maxlen=max_items)
        self._next_id = 1
        self._lock = threading.Lock()

    def record(self, worker, event, message, state=None, actor=None, at=None):
        ts = self.clock() if at is None else at
        item = {
            "id": None,
            "t": ts,
            "time": datetime.fromtimestamp(ts, timezone.utc).isoformat(),
            "worker_id": worker.id,
            "worker_name": worker.name,
            "event": event,
            "state": state,
            "message": message,
            "actor": actor,
        }
        with self._lock:
            item["id"] = self._next_id
            self._next_id += 1
            self._items.append(item)
        return item

    def since(self, last_id):
        """Entries with an id greater than `last_id`, oldest first (what still needs saving)."""
        with self._lock:
            return [i for i in reversed(self._items) if i["id"] > last_id][::-1]

    def load(self, items):
        """Re-fill from saved rows (start-up). Ids continue after the highest one seen."""
        with self._lock:
            self._items.extend(dict(i) for i in items)
            if items:
                self._next_id = max(self._next_id, max(i["id"] for i in items) + 1)

    def reset_ids(self, next_id):
        self._next_id = max(next_id, 1)

    def drop_after(self, last_id):
        """Forget entries newer than `last_id` (an action whose save failed is undone)."""
        with self._lock:
            while self._items and self._items[-1]["id"] > last_id:
                self._items.pop()
            self._next_id = last_id + 1

    def last_id(self):
        with self._lock:
            return self._next_id - 1

    def entries(self, worker_id=None):
        """Oldest first."""
        with self._lock:
            items = list(self._items)
        return [i for i in items if worker_id is None or i["worker_id"] == worker_id]

    def to_csv(self):
        out = io.StringIO()
        writer = csv.DictWriter(out, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(self.entries())
        return out.getvalue()
