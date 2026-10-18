"""REAL-process restart test for safety persistence (REM-04). Disposable database; nothing else is touched.

    cd backend
    .venv\\Scripts\\python.exe ..\\docs\\qa_audit_2026-10-11\\probes\\restart_e2e.py

Steps (demo thresholds: idle 15 s + 3 x 5 s windows = 30 s):
 1 start the backend (python app.py) on a temp SQLite file, seeded
 2 wait with NO client for an EMERGENCY to be raised by the heartbeat
 3 read the database file directly: the emergency row must be there
 4 KILL the process (hard kill, no graceful shutdown) and start it again on the same file
 5 the emergency must still be there with the same status; the heartbeat must not create a second one
 6 a Dispatcher is refused (403); a Supervisor resolves it; the final state is saved
 7 kill + restart again: the resolution is still there and nothing re-escalated
"""

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections import Counter

PORT = "5078"
BASE = f"http://127.0.0.1:{PORT}/api"
TMP = tempfile.mkdtemp(prefix="fieldtrack_restart_")
DB = os.path.join(TMP, "restart.db")
ENV = {k: v for k, v in os.environ.items() if k not in ("DATABASE_URL", "SECRET_KEY", "APP_ENV", "FLASK_DEBUG")}
ENV.update(
    DATABASE_URL="sqlite:///" + DB.replace("\\", "/"), PORT=PORT, SAFETY_MODE="demo", SAFETY_SEED="3",
    SAFETY_AUTO_RESPOND_CHANCE="0", SAFETY_ACCIDENT_PROBABILITY="0", PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8",
)  # fmt: skip
results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name} {detail}")


def api(method, path, token=None, body=None):
    req = urllib.request.Request(BASE + path, data=None if body is None else json.dumps(body).encode(), method=method,
                                 headers={"Content-Type": "application/json", **({"Authorization": "Bearer " + token} if token else {})})  # fmt: skip
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"null")


def login(email, password):
    return api("POST", "/auth/login", body={"email": email, "password": password})[1]["token"]


def start():
    log = open(os.path.join(TMP, "server.log"), "a")
    proc = subprocess.Popen([sys.executable, "-u", "app.py"], env=ENV, stdout=log, stderr=subprocess.STDOUT)
    for _ in range(60):
        try:
            urllib.request.urlopen(BASE + "/health", timeout=1)
            return proc
        except Exception:  # noqa: BLE001
            time.sleep(0.3)
    raise SystemExit("server did not start")


def kill(proc):
    proc.kill()  # TerminateProcess / SIGKILL: no shutdown hooks run, like a crash or power cut
    proc.wait(10)


def db_rows():
    con = sqlite3.connect(DB)
    try:
        workers = con.execute("SELECT worker_id, state FROM safety_worker_state ORDER BY worker_id").fetchall()
        events = Counter(r[0] for r in con.execute("SELECT event FROM safety_audit"))
        per_worker = Counter((r[0], r[1]) for r in con.execute("SELECT worker_id, event FROM safety_audit"))
        return workers, events, per_worker
    finally:
        con.close()


try:
    subprocess.run([sys.executable, "seed.py", "--reset", "--yes"], env=ENV, capture_output=True, timeout=120, check=True)
    print("1. start the backend; no client will talk to it")
    p1 = start()
    time.sleep(38)  # heartbeat: idle at +15 s, emergency at +30 s
    print("2/3. the heartbeat raised an emergency by itself and saved it (read straight from the file)")
    workers, events, per_worker = db_rows()
    emergencies = [w for w, s in workers if s == "EMERGENCY"]
    check("an EMERGENCY row exists in the database", len(emergencies) >= 1, f"workers={workers}")
    check("exactly one EMERGENCY audit event per emergency worker", all(per_worker[(w, "EMERGENCY")] == 1 for w in emergencies), str(dict(events)))
    wid = emergencies[0]
    before_events = dict(events)

    print("4. hard-kill the process and start it again on the same file")
    kill(p1)
    workers_dead, _, _ = db_rows()
    check("the emergency is still in the file while the server is dead", (wid, "EMERGENCY") in workers_dead)
    p2 = start()
    sup = login("supervisor@fieldtrack.com", "Super123!")
    dis = login("dispatch@fieldtrack.com", "Dispatch123!")
    live = api("GET", "/map/live", sup)[1]
    alert_ids = [a["worker_id"] for a in live["safety"]["alerts"]]
    status = next(w for w in live["workers"] if w["id"] == wid)["status"]
    check("5. after the restart the API shows the same emergency", wid in alert_ids and status == "EMERGENCY", f"alerts={alert_ids} status={status}")
    audit = api("GET", f"/safety/audit?worker_id={wid}", sup)[1]
    check("   history from before the kill is still in the audit log", any(e["event"] == "EMERGENCY" for e in audit))
    time.sleep(12)  # the new heartbeat runs; the existing emergency must not be raised again
    workers2, events2, pw2 = db_rows()
    check("   no second emergency or duplicate events were created", pw2[(wid, "EMERGENCY")] == 1 and pw2[(wid, "EMERGENCY_CALL")] == 1 and pw2[(wid, "IDLE_DETECTED")] == 1, f"worker {wid}: " + str({e: n for (w, e), n in pw2.items() if w == wid}))
    check("   monitoring reports persistence ok and the heartbeat running", (lambda m: m["background"] and m["persistence"]["ok"])(api("GET", "/map/live", sup)[1]["safety"]["monitoring"]))

    print("6. permissions and resolution after the restart")
    check("   Dispatcher cannot resolve it (403)", api("POST", f"/safety/workers/{wid}/resolve", dis, {"outcome": "false_alarm"})[0] == 403)
    check("   no token: 401", api("POST", f"/safety/workers/{wid}/resolve", None, {"outcome": "false_alarm"})[0] == 401)
    st, _ = api("POST", f"/safety/workers/{wid}/resolve", sup, {"outcome": "real_incident", "note": "restart e2e"})
    check("   Supervisor resolves it (real incident)", st == 200)
    workers3, events3, pw3 = db_rows()
    check("   the resolution is saved (state POST_INCIDENT, RESOLVED event)", (wid, "POST_INCIDENT") in workers3 and pw3[(wid, "RESOLVED")] == 1, f"{workers3}")

    print("7. kill again: the resolved state must persist and nothing re-escalates")
    kill(p2)
    p3 = start()
    time.sleep(40)  # long enough to re-escalate if state were lost (the worker is still standing still)
    workers4, events4, pw4 = db_rows()
    sup = login("supervisor@fieldtrack.com", "Super123!")
    status = next(w for w in api("GET", "/map/live", sup)[1]["workers"] if w["id"] == wid)["status"]
    check("   still POST-incident after the second restart", status == "Post-incident" and (wid, "POST_INCIDENT") in workers4, f"status={status}")
    check("   the resolved worker did not re-escalate (EMERGENCY events for it unchanged)", pw4[(wid, "EMERGENCY")] == pw3[(wid, "EMERGENCY")] == 1 and pw4[(wid, "IDLE_DETECTED")] == 1, f"worker {wid} EMERGENCY events {pw3[(wid, 'EMERGENCY')]} -> {pw4[(wid, 'EMERGENCY')]}")
    st, _ = api("POST", f"/safety/workers/{wid}/return-to-duty", sup)
    check("   return-to-duty works and removes the saved row", st == 200 and all(w != wid for w, _ in db_rows()[0]))
    kill(p3)
finally:
    for p in ("p1", "p2", "p3"):
        proc = globals().get(p)
        if proc and proc.poll() is None:
            proc.kill()
    shutil.rmtree(TMP, ignore_errors=True)

print(f"\nSUMMARY: {sum(results)} passed, {len(results) - sum(results)} failed (temp dir removed)")
sys.exit(0 if all(results) else 1)
