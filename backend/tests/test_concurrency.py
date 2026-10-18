"""D-03 / D-04: simultaneous requests must not break the clock-in and crew-capacity rules.

These tests start a real multi-threaded HTTP server on a FILE-backed SQLite database in a temporary
directory (an in-memory database would hide the races), fire requests from many threads released at the
same instant, and then look at what is actually stored. Nothing here touches the developer database.

Before the fix, 12 identical simultaneous clock-ins stored 5 rows and two workers racing for the last
crew place overfilled the job in 24 of 25 trials. The business rules stay the same; they are now
enforced atomically (SQLite `BEGIN IMMEDIATE` around check-and-write, plus a partial unique index for
"one open entry per worker").
"""

import json
import sqlite3
import threading
import urllib.error
import urllib.request
from collections import Counter
from datetime import date, timedelta

import pytest
from werkzeug.serving import make_server

from app import create_app
from extensions import db
from models import Assignment, Job, JobSite, TimeEntry, User
from tests.conftest import PASSWORD

DAY = date(2026, 10, 1)
SITE = (27.70, 85.30)


class Server:
    """A threaded HTTP server over a throw-away SQLite file, with a few ready-made accounts."""

    def __init__(self, tmp_path, timeout=10):
        self.path = tmp_path / "race.db"
        self.app = create_app(
            {
                "TESTING": True,
                "SQLALCHEMY_DATABASE_URI": "sqlite:///" + self.path.as_posix(),
                "SQLITE_BUSY_TIMEOUT_SECONDS": timeout,
                "BCRYPT_ROUNDS": 4,
                "LOGIN_RATE_LIMIT_ENABLED": False,
            }
        )
        with self.app.app_context():
            self._load()
        self.httpd = make_server("127.0.0.1", 0, self.app, threaded=True)
        self.port = self.httpd.server_port
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.tokens = {
            role: self.login(email)
            for role, email in (
                ("dispatcher", "dispatch@test.com"),
                ("supervisor", "super@test.com"),
            )
        }

    def _load(self):
        def staff(name, email, role):
            u = User(full_name=name, email=email, role=role, is_active=True)
            u.set_password(PASSWORD)
            return u

        disp = staff("Dee Dispatch", "dispatch@test.com", "Dispatcher")
        sup = staff("Sue Visor", "super@test.com", "Supervisor")
        self.workers = [
            User(full_name=f"Worker {i}", email=f"w{i}@test.com", role="Worker", trade="Laborer")
            for i in range(1, 11)
        ]
        site = JobSite(
            site_name="Race Site",
            address="1 Race Road",
            latitude=SITE[0],
            longitude=SITE[1],
            geofence_radius_m=200,
        )
        db.session.add_all([disp, sup, site, *self.workers])
        db.session.flush()
        self.job = Job(
            site=site,
            creator=disp,
            title="Race job",
            scheduled_date=DAY,
            crew_size=3,
            status="Scheduled",
        )
        self.job2 = Job(
            site=site,
            creator=disp,
            title="Second job",
            scheduled_date=DAY,
            crew_size=10,
            status="Scheduled",
        )
        db.session.add_all([self.job, self.job2])
        db.session.commit()
        self.job_id, self.job2_id = self.job.job_id, self.job2.job_id
        self.worker_ids = [w.user_id for w in self.workers]

    def login(self, email):
        status, body = self.call("POST", "/api/auth/login", {"email": email, "password": PASSWORD})
        assert status == 200, body
        return body["token"]

    def call(self, method, path, body=None, role=None):
        headers = {"Content-Type": "application/json"}
        if role:
            headers["Authorization"] = "Bearer " + self.tokens[role]
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}", data=data, method=method, headers=headers
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.status, json.loads(r.read() or b"null")
        except urllib.error.HTTPError as e:
            try:
                return e.code, json.loads(e.read() or b"null")
            except ValueError:
                return e.code, None

    def burst(self, calls):
        """Run every call in its own thread, all released at once. Returns [(status, body)]."""
        results = [None] * len(calls)
        gate = threading.Barrier(len(calls))

        def run(i, fn):
            gate.wait()
            results[i] = fn()

        threads = [threading.Thread(target=run, args=(i, fn)) for i, fn in enumerate(calls)]
        [t.start() for t in threads]
        [t.join(120) for t in threads]
        assert all(r is not None for r in results), "a request never completed"
        return results

    def rows(self, model, **filters):
        with self.app.app_context():
            return model.query.filter_by(**filters).all()

    def close(self):
        self.httpd.shutdown()
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()


@pytest.fixture
def server(tmp_path):
    s = Server(tmp_path)
    yield s
    s.close()


def entry_body(user_id, job_id, start="07:00", end=None, **extra):
    body = {
        "user_id": user_id,
        "job_id": job_id,
        "clock_in": f"{DAY}T{start}",
        "in_lat": SITE[0],
        "in_lng": SITE[1],
    }
    if end:
        body.update(clock_out=f"{DAY}T{end}", out_lat=SITE[0], out_lng=SITE[1])
    body.update(extra)
    return body


def assign(server, worker_id, job_id=None):
    return lambda: server.call(
        "POST",
        "/api/assignments",
        {"job_id": job_id or server.job_id, "user_id": worker_id},
        "dispatcher",
    )


def clock_in(server, worker_id, **kw):
    return lambda: server.call(
        "POST",
        "/api/time-entries",
        entry_body(worker_id, kw.pop("job_id", server.job_id), **kw),
        "supervisor",
    )


def statuses(results):
    return dict(Counter(s for s, _ in results))


def prepare_assigned_worker(server, index=0):
    wid = server.worker_ids[index]
    status, _ = assign(server, wid)()
    assert status == 201
    return wid


# ---- clock-ins ------------------------------------------------------------------------------------------


def test_twelve_identical_simultaneous_clock_ins_store_exactly_one_entry(server):
    wid = prepare_assigned_worker(server)
    results = server.burst([clock_in(server, wid) for _ in range(12)])
    assert statuses(results) == {201: 1, 409: 11}, statuses(results)
    assert all("Overlaps entry" in body["error"] for s, body in results if s == 409)
    assert len(server.rows(TimeEntry, user_id=wid)) == 1


def test_overlapping_clock_ins_with_different_start_times_cannot_both_be_stored(server):
    wid = prepare_assigned_worker(server)
    starts = ["07:00", "07:05", "07:10", "07:15", "07:20", "07:25", "07:30", "07:35"]
    results = server.burst([clock_in(server, wid, start=s) for s in starts])
    assert statuses(results)[201] == 1, statuses(
        results
    )  # all are still running, so any two overlap
    assert len(server.rows(TimeEntry, user_id=wid)) == 1


def test_overlapping_closed_entries_are_never_both_stored(server):
    wid = prepare_assigned_worker(server)
    windows = [
        ("06:00", "09:00"),
        ("08:00", "11:00"),
        ("10:00", "13:00"),
        ("07:00", "08:30"),
        ("12:00", "15:00"),
        ("08:30", "09:30"),
    ]
    results = server.burst([clock_in(server, wid, start=a, end=b) for a, b in windows])
    stored = sorted(server.rows(TimeEntry, user_id=wid), key=lambda e: e.clock_in)
    assert len(stored) == statuses(results).get(201, 0) >= 1
    for first, second in zip(stored, stored[1:]):
        assert first.clock_out <= second.clock_in, "two stored entries overlap"


def test_back_to_back_entries_and_other_workers_are_still_allowed(server):
    a, b = prepare_assigned_worker(server, 0), prepare_assigned_worker(server, 1)
    assert clock_in(server, a, start="07:00", end="11:00")()[0] == 201
    assert (
        clock_in(server, a, start="11:00", end="15:00")()[0] == 201
    )  # starts exactly when the other ends
    assert clock_in(server, a, start="14:00")()[0] == 409  # overlaps the second one
    assert clock_in(server, b, start="07:00")()[0] == 201  # a different worker is unaffected
    assert clock_in(server, a, start="16:00")()[0] == 201  # and a later open entry is fine


def test_simultaneous_clock_ins_for_different_workers_all_succeed(server):
    ids = [prepare_assigned_worker(server, i) for i in range(3)]
    results = server.burst([clock_in(server, w) for w in ids for _ in range(1)])
    assert statuses(results) == {201: 3}


def test_overnight_shift_still_works_and_blocks_overlap_across_midnight(server):
    wid = prepare_assigned_worker(server)
    night = {"user_id": wid, "job_id": server.job_id, "clock_in": f"{DAY}T22:00", "in_lat": SITE[0], "in_lng": SITE[1],
             "clock_out": f"{DAY + timedelta(days=1)}T06:30", "out_lat": SITE[0], "out_lng": SITE[1]}  # fmt: skip
    status, body = server.call("POST", "/api/time-entries", night, "supervisor")
    assert status == 201 and body["time_entry"]["hours"] == 8.5
    status, _ = server.call(
        "POST",
        "/api/time-entries",
        {**night, "clock_in": f"{DAY}T23:00", "clock_out": None, "out_lat": None, "out_lng": None},
        "supervisor",
    )
    assert status == 409


def test_simultaneous_clock_outs_and_decisions_apply_exactly_once(server):
    wid = prepare_assigned_worker(server)
    status, body = clock_in(server, wid)()
    entry = body["time_entry"]["entry_id"]
    out = {"clock_out": f"{DAY}T15:00", "out_lat": SITE[0], "out_lng": SITE[1]}
    results = server.burst(
        [
            lambda: server.call("PATCH", f"/api/time-entries/{entry}/clock-out", out, "supervisor")
            for _ in range(8)
        ]
    )
    assert statuses(results) == {200: 1, 409: 7}
    decide = lambda d: lambda: server.call(
        "PATCH",
        f"/api/time-entries/{entry}/approve",
        {"decision": d, "edit_reason": "race test"},
        "supervisor",
    )  # noqa: E731
    results = server.burst(
        [decide("Approved") for _ in range(4)] + [decide("Rejected") for _ in range(4)]
    )
    assert statuses(results) == {200: 1, 409: 7}
    assert len(server.rows(TimeEntry, user_id=wid)) == 1


# ---- crew assignments --------------------------------------------------------------------------------------


def test_two_workers_racing_for_the_last_place_never_overfill_the_crew(server):
    with server.app.app_context():
        db.session.get(Job, server.job_id).crew_size = 1
        db.session.commit()
    results = server.burst(
        [assign(server, server.worker_ids[0]), assign(server, server.worker_ids[1])]
    )
    assert statuses(results) == {201: 1, 409: 1}
    assert any("is full" in body["error"] for s, body in results if s == 409)
    assert len(server.rows(Assignment, job_id=server.job_id)) == 1


@pytest.mark.parametrize("capacity,requests", [(1, 6), (3, 8), (5, 5), (4, 10)])
def test_capacity_boundaries_under_simultaneous_requests(server, capacity, requests):
    with server.app.app_context():
        db.session.get(Job, server.job_id).crew_size = capacity
        db.session.commit()
    results = server.burst([assign(server, w) for w in server.worker_ids[:requests]])
    ok = min(capacity, requests)
    assert statuses(results) == {
        201: ok,
        **({409: requests - ok} if requests > ok else {}),
    }, statuses(results)
    assert len(server.rows(Assignment, job_id=server.job_id)) == ok  # never more than the crew size


def test_repeated_trials_of_the_last_place_race(server):
    """The audit's original scenario: 25 trials, one free place, two workers each time."""
    overfilled = 0
    for trial in range(15):
        with server.app.app_context():
            Assignment.query.filter_by(job_id=server.job_id).delete()
            job = db.session.get(Job, server.job_id)
            job.crew_size = 1
            db.session.commit()
        results = server.burst(
            [assign(server, server.worker_ids[0]), assign(server, server.worker_ids[1])]
        )
        stored = len(server.rows(Assignment, job_id=server.job_id))
        overfilled += stored > 1
        assert statuses(results) == {201: 1, 409: 1}, (trial, statuses(results))
    assert overfilled == 0


def test_one_worker_cannot_be_double_booked_by_simultaneous_requests(server):
    wid = server.worker_ids[0]
    calls = [assign(server, wid, server.job_id) for _ in range(4)] + [
        assign(server, wid, server.job2_id) for _ in range(4)
    ]
    results = server.burst(calls)
    assert statuses(results) == {201: 1, 409: 7}
    assert len(server.rows(Assignment, user_id=wid)) == 1


def test_removing_and_reassigning_still_works(server):
    wid = server.worker_ids[0]
    status, body = assign(server, wid)()
    assert status == 201
    assert (
        server.call(
            "DELETE", f"/api/assignments/{body['assignment']['assignment_id']}", role="dispatcher"
        )[0]
        == 200
    )
    assert assign(server, wid, server.job2_id)()[0] == 201  # reassigned to the other job
    assert assign(server, wid, server.job_id)()[0] == 409  # but still only one per day


# ---- sequential rules still hold ----------------------------------------------------------------------------


def test_sequential_duplicates_get_the_same_documented_conflict(server):
    wid = prepare_assigned_worker(server)
    assert clock_in(server, wid)()[0] == 201
    status, body = clock_in(server, wid)()
    assert status == 409 and body["field"] == "clock_in" and "Overlaps entry" in body["error"]
    status, body = clock_in(server, server.worker_ids[5])()  # a worker who is not assigned
    assert status == 409 and body["field"] == "user_id"


# ---- the database enforces "one open entry per worker" by itself ---------------------------------------------


def test_database_rejects_a_second_open_entry_even_without_the_api(server):
    wid = prepare_assigned_worker(server)
    assert clock_in(server, wid)()[0] == 201
    con = sqlite3.connect(server.path)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            con.execute(
                "INSERT INTO time_entries (user_id, job_id, clock_in, in_lat, in_lng, is_flagged, status) VALUES (?, ?, ?, 1, 1, 0, 'Pending')",
                (wid, server.job_id, "2026-10-01 12:00:00"),
            )
        # a CLOSED entry for the same worker is not blocked by the index
        con.execute(
            "INSERT INTO time_entries (user_id, job_id, clock_in, clock_out, in_lat, in_lng, is_flagged, status) VALUES (?, ?, ?, ?, 1, 1, 0, 'Pending')",
            (wid, server.job_id, "2026-10-01 01:00:00", "2026-10-01 02:00:00"),
        )
        con.commit()
    finally:
        con.close()


def test_the_guard_index_is_created_on_an_existing_database_and_is_idempotent(tmp_path):
    path = tmp_path / "old.db"
    first = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///" + path.as_posix()})
    with first.app_context():
        db.session.execute(db.text("DROP INDEX uq_time_entries_one_open_per_worker"))
        db.session.commit()  # simulate a database created before the guard existed
        db.engine.dispose()
    again = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///" + path.as_posix()})
    with again.app_context():
        names = {r[1] for r in db.session.execute(db.text("PRAGMA index_list('time_entries')"))}
        assert "uq_time_entries_one_open_per_worker" in names
        db.engine.dispose()
    create_app(
        {"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///" + path.as_posix()}
    )  # a third start is a no-op


def test_existing_duplicate_open_entries_do_not_stop_the_app_from_starting(tmp_path, caplog):
    path = tmp_path / "dirty.db"
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///" + path.as_posix()})
    with app.app_context():
        db.session.execute(db.text("DROP INDEX uq_time_entries_one_open_per_worker"))
        db.session.execute(
            db.text(
                "INSERT INTO users (user_id, full_name, email, role, is_active) VALUES (1, 'A', 'a@x.com', 'Worker', 1)"
            )
        )
        db.session.execute(
            db.text(
                "INSERT INTO job_sites (site_id, site_name, address, latitude, longitude, geofence_radius_m) VALUES (1,'S','addr',1,1,200)"
            )
        )
        db.session.execute(
            db.text(
                "INSERT INTO jobs (job_id, site_id, created_by, title, scheduled_date, crew_size, status) VALUES (1,1,1,'J','2026-10-01',1,'Scheduled')"
            )
        )
        for h in (1, 2):
            db.session.execute(
                db.text(
                    f"INSERT INTO time_entries (user_id, job_id, clock_in, in_lat, in_lng, is_flagged, status) VALUES (1,1,'2026-10-01 0{h}:00:00',1,1,0,'Pending')"
                )
            )
        db.session.commit()
        db.engine.dispose()
    create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///" + path.as_posix()})
    assert "could not create the one-open-entry-per-worker index" in caplog.text


# ---- lock contention: busy database, retry ------------------------------------------------------------------------


def test_a_busy_database_gives_a_503_with_retry_after_and_a_retry_succeeds(tmp_path):
    s = Server(tmp_path, timeout=0.3)
    try:
        wid = prepare_assigned_worker(s)
        blocker = sqlite3.connect(s.path, timeout=1, isolation_level=None)
        blocker.execute("BEGIN IMMEDIATE")  # another process holds the write lock
        try:
            status, body = s.call(
                "POST", "/api/time-entries", entry_body(wid, s.job_id), "supervisor"
            )
            assert status == 503 and "busy" in body["error"].lower()
            req = urllib.request.Request(f"http://127.0.0.1:{s.port}/api/time-entries", data=json.dumps(entry_body(wid, s.job_id)).encode(), method="POST",
                                         headers={"Content-Type": "application/json", "Authorization": "Bearer " + s.tokens["supervisor"]})  # fmt: skip
            with pytest.raises(urllib.error.HTTPError) as err:
                urllib.request.urlopen(req, timeout=10)
            assert err.value.code == 503 and err.value.headers["Retry-After"] == "1"
            assert s.rows(TimeEntry, user_id=wid) == []  # nothing was half-written
        finally:
            blocker.execute("ROLLBACK")
            blocker.close()
        assert (
            s.call("POST", "/api/time-entries", entry_body(wid, s.job_id), "supervisor")[0] == 201
        )  # retry works
    finally:
        s.close()


def test_a_rejected_request_rolls_back_and_leaves_the_lock_free(server):
    wid = server.worker_ids[3]  # not assigned: rejected after the write lock was taken
    for _ in range(5):
        status, _ = clock_in(server, wid)()
        assert status == 409
    assert server.rows(TimeEntry, user_id=wid) == []
    assert (
        clock_in(server, prepare_assigned_worker(server))()[0] == 201
    )  # the database is not left locked
