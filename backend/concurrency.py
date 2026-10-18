"""Making "check, then write" rules atomic.

Rules like "no overlapping clock-ins" and "the crew is not full" are checked by reading rows and then
inserting one. With two requests in flight, both can read the same state, both pass the check, and both
write (a classic race). A Python lock would not help: the server may run several threads or processes.
The only thing every writer shares is the database, so the routes take the database's WRITE lock before
they read anything they depend on:

    begin_write()      # SQLite: BEGIN IMMEDIATE  -> other writers wait here until we commit/roll back
    ...checks...       # now nobody can change the rows we just read
    ...insert/update...
    db.session.commit()

Other writers wait up to the busy timeout (config SQLITE_BUSY_TIMEOUT_SECONDS, default 10 s); if the
database stays locked longer the client gets HTTP 503 with `Retry-After: 1` and the request had no effect
(see app.py, which also maps a late "database is locked" to the same answer).

Only SQLite is supported by this project. Other databases would need row locks (SELECT ... FOR UPDATE)
instead; `begin_write()` is a deliberate no-op for them rather than a pretence of safety.
"""

from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from extensions import db
from validation import ApiError

BUSY_MESSAGE = "The server is busy with another change. Please retry in a moment."


def is_busy_error(exc):
    """True if `exc` is SQLite reporting that the database is locked/busy."""
    message = str(getattr(exc, "orig", exc)).lower()
    return (
        "database is locked" in message
        or "database table is locked" in message
        or "busy" in message
    )


def busy_error():
    return ApiError(BUSY_MESSAGE, status=503, headers={"Retry-After": "1"})


def begin_write():
    """Take the write lock now (SQLite) so the checks that follow stay true until we commit."""
    if db.session.get_bind().dialect.name != "sqlite":
        return
    try:
        db.session.execute(text("BEGIN IMMEDIATE"))
    except OperationalError as exc:
        if is_busy_error(exc):
            db.session.rollback()
            raise busy_error() from exc
        if "within a transaction" in str(exc.orig).lower():
            return  # this connection already holds a write transaction, so the lock is ours
        raise
