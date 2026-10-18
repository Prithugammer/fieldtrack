"""Durable storage for safety state, so an emergency survives a server restart.

Four small tables, created by `db.create_all()` (non-destructively, next to the existing ones):

  safety_worker_state  one row per worker that is NOT simply "normal": an open check-in, an EMERGENCY,
                       a post-incident hold, a frozen (stopped) marker, a break. JSON snapshot of the
                       state machine plus the service flags. A worker who returns to normal has no row.
  safety_audit         the append-only audit log (every event, with the id the UI shows).
  safety_notification  the in-app message feed (check-ins, supervisor alerts, the MOCK emergency call).
  safety_lease         which process currently owns the background heartbeat (see ticker.py).

Nothing here decides anything; SafetyService calls `load()` once at start-up and `save()` after every
change, inside one database transaction (all rows or none).
"""

import json
import logging
import time
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from extensions import db

log = logging.getLogger("fieldtrack.safety.store")


class SafetyWorkerState(db.Model):
    __tablename__ = "safety_worker_state"

    worker_id = db.Column(
        db.Integer, primary_key=True
    )  # same id space as users.user_id (no FK: history outlives users)
    worker_name = db.Column(db.String(100), nullable=False)
    state = db.Column(db.String(20), nullable=False, index=True)
    data = db.Column(db.Text, nullable=False)  # JSON, see SafetyService._encode
    updated_at = db.Column(db.Float, nullable=False)


class SafetyAuditRow(db.Model):
    __tablename__ = "safety_audit"

    id = db.Column(db.Integer, primary_key=True, autoincrement=False)
    t = db.Column(db.Float, nullable=False)
    worker_id = db.Column(db.Integer, nullable=False, index=True)
    worker_name = db.Column(db.String(100), nullable=False)
    event = db.Column(db.String(40), nullable=False)
    state = db.Column(db.String(20))
    message = db.Column(db.Text, nullable=False)
    actor = db.Column(db.String(160))


class SafetyNotificationRow(db.Model):
    __tablename__ = "safety_notification"

    id = db.Column(db.Integer, primary_key=True, autoincrement=False)
    t = db.Column(db.Float, nullable=False)
    channel = db.Column(db.String(30), nullable=False)
    level = db.Column(db.String(20), nullable=False)
    worker_id = db.Column(db.Integer, nullable=False)
    worker_name = db.Column(db.String(100), nullable=False)
    text = db.Column(db.Text, nullable=False)


class SafetyLease(db.Model):
    __tablename__ = "safety_lease"

    name = db.Column(db.String(40), primary_key=True)
    holder = db.Column(db.String(80), nullable=False)
    expires_at = db.Column(db.Float, nullable=False)


AUDIT_FIELDS = ("id", "t", "worker_id", "worker_name", "event", "state", "message", "actor")
NOTE_FIELDS = ("id", "t", "channel", "level", "worker_id", "worker_name", "text")


class SafetyStore:
    """Reads and writes the tables above through the app's database session.

    Must be used inside an application context (the caller removes the session when it is done). Every method either completes or raises; `save` rolls
    the whole transaction back on any error so a half-written state is never visible.
    """

    def __init__(self, audit_load=5000, notes_load=300):
        self.audit_load = audit_load
        self.notes_load = notes_load

    # ----- start-up -----

    def load(self):
        workers = {}
        for row in SafetyWorkerState.query.all():
            try:
                workers[row.worker_id] = (row.worker_name, json.loads(row.data))
            except ValueError:
                # A damaged row must not stop the server (and must not be silently dropped either).
                log.error("Safety state for worker %s is unreadable and was skipped", row.worker_id)
        audit = SafetyAuditRow.query.order_by(SafetyAuditRow.id.desc()).limit(self.audit_load).all()
        notes = (
            SafetyNotificationRow.query.order_by(SafetyNotificationRow.id.desc())
            .limit(self.notes_load)
            .all()
        )

        def with_time(row, fields):
            item = {k: getattr(row, k) for k in fields}
            item["time"] = datetime.fromtimestamp(row.t, timezone.utc).isoformat()
            return item

        return {
            "workers": workers,
            "audit": [with_time(r, AUDIT_FIELDS) for r in reversed(audit)],
            "notifications": [with_time(r, NOTE_FIELDS) for r in reversed(notes)],
            "max_audit_id": db.session.query(db.func.max(SafetyAuditRow.id)).scalar() or 0,
            "max_note_id": db.session.query(db.func.max(SafetyNotificationRow.id)).scalar() or 0,
        }

    # ----- every change -----

    def save(self, changed, removed, audit_rows, note_rows, now=None):
        """Write everything in one transaction. `changed` is {worker_id: (name, state, json_text)}."""
        now = time.time() if now is None else now
        try:
            for wid, (name, state, data) in changed.items():
                row = db.session.get(SafetyWorkerState, wid)
                if row is None:
                    db.session.add(
                        SafetyWorkerState(
                            worker_id=wid, worker_name=name, state=state, data=data, updated_at=now
                        )
                    )
                else:
                    row.worker_name, row.state, row.data, row.updated_at = name, state, data, now
            for wid in removed:
                row = db.session.get(SafetyWorkerState, wid)
                if row is not None:
                    db.session.delete(row)
            for r in audit_rows:
                db.session.merge(SafetyAuditRow(**{k: r[k] for k in AUDIT_FIELDS}))
            for r in note_rows:
                db.session.merge(SafetyNotificationRow(**{k: r[k] for k in NOTE_FIELDS}))
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise

    # ----- heartbeat ownership -----

    def acquire_lease(self, name, holder, ttl, now=None):
        """Atomically take or renew the lease. True if `holder` owns it afterwards."""
        now = time.time() if now is None else now
        try:
            db.session.execute(
                (
                    text(
                        "INSERT OR IGNORE INTO safety_lease (name, holder, expires_at) VALUES (:n, :h, :e)"
                    )
                    if db.engine.dialect.name == "sqlite"
                    else text(
                        "INSERT INTO safety_lease (name, holder, expires_at) VALUES (:n, :h, :e)"
                    )
                ),
                {"n": name, "h": holder, "e": now + ttl},
            )
            db.session.execute(
                text(
                    "UPDATE safety_lease SET holder = :h, expires_at = :e WHERE name = :n AND (holder = :h OR expires_at < :now)"
                ),
                {"n": name, "h": holder, "e": now + ttl, "now": now},
            )
            owner = db.session.execute(
                text("SELECT holder FROM safety_lease WHERE name = :n"), {"n": name}
            ).scalar()
            db.session.commit()
            return owner == holder
        except IntegrityError:
            db.session.rollback()
            return False
        except Exception:
            db.session.rollback()
            raise

    def release_lease(self, name, holder):
        try:
            db.session.execute(
                text("DELETE FROM safety_lease WHERE name = :n AND holder = :h"),
                {"n": name, "h": holder},
            )
            db.session.commit()
        except Exception:
            db.session.rollback()
