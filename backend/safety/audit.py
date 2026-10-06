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
