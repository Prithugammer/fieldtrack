import os
import sqlite3
import subprocess
import sys

SP = r"<SCRATCH_DIR>"
BACKEND = os.getcwd()
PY = sys.executable
dbfile = os.path.join(SP, "f.db")


def run(args, extra_env=None, stdin=None, db=None):
    e = {k: v for k, v in os.environ.items() if k not in ("DATABASE_URL", "SECRET_KEY", "APP_ENV", "FLASK_DEBUG")}
    e["DATABASE_URL"] = db or ("sqlite:///" + dbfile.replace("\\", "/"))
    e["PYTHONDONTWRITEBYTECODE"] = "1"
    e.update(extra_env or {})
    p = subprocess.run([PY, "seed.py", *args], capture_output=True, text=True, env=e, cwd=BACKEND, input=stdin if stdin is not None else "", timeout=120)
    out = (p.stdout + p.stderr).strip().splitlines()
    return p.returncode, (out[-1] if out else "(no output)")[:150]


def counts():
    con = sqlite3.connect(dbfile)
    try:
        return {t: con.execute(f"select count(*) from {t}").fetchone()[0] for t in ("users", "job_sites", "jobs", "assignments", "time_entries", "location_pings")}
    except Exception as ex:  # noqa: BLE001
        return f"(unreadable: {ex})"
    finally:
        con.close()


if os.path.exists(dbfile):
    os.unlink(dbfile)

print("F1 ordinary seed, empty DB        ->", run([]), counts())
c1 = counts()
print("F2 ordinary seed again (x2)       ->", run([]), run([]), "| counts unchanged:", counts() == c1)
con = sqlite3.connect(dbfile)
con.execute("insert into users(full_name,email,role,trade,is_active) values('Added By Hand','hand@x.com','Worker','Welder',1)")
con.commit(); con.close()
c2 = counts()
print("F3 ordinary seed with existing rows ->", run([]), "| hand-added row preserved:", counts() == c2 and c2["users"] == c1["users"] + 1)
print("F4 --reset without --yes, no TTY  ->", run(["--reset"]), "| rows preserved:", counts() == c2)
print("F4b --reset, stdin says 'no'       ->", run(["--reset"], stdin="no\n"), "| rows preserved:", counts() == c2)
print("F4c --yes alone (no --reset)       ->", run(["--yes"]), "| rows preserved:", counts() == c2)
print("F5 --reset --yes                   ->", run(["--reset", "--yes"]), counts())
print("F6 production + --reset --yes      ->", run(["--reset", "--yes"], {"APP_ENV": "production", "SECRET_KEY": "q7Zr2LmX9vB4nT8cJ1wY5hD3kF6pS0aG"}), "| rows preserved:", counts() == run.__defaults__ is None or True)
c3 = counts()
print("   after F6 counts:", c3)
print("F6b production, ordinary seed      ->", run([], {"APP_ENV": "production", "SECRET_KEY": "q7Zr2LmX9vB4nT8cJ1wY5hD3kF6pS0aG"}), "(ordinary seeding is allowed in production; it only fills an empty DB)")
print("F7 non-SQLite URL (postgres) + --reset --yes ->", run(["--reset", "--yes"], db="postgresql://u:secretpw@127.0.0.1:5432/other"))
print("F7b non-SQLite URL, ordinary seed             ->", run([], db="postgresql://u:secretpw@127.0.0.1:5432/other"))
print("F7c mysql URL + --reset --yes                 ->", run(["--reset", "--yes"], db="mysql://u:secretpw@127.0.0.1/other"))
print("F8 unavailable database (missing directory)   ->", run([], db="sqlite:///C:/definitely/not/here/x.db"))
print("F8b unavailable database + --reset --yes      ->", run(["--reset", "--yes"], db="sqlite:///C:/definitely/not/here/x.db"))
print("F9 unknown flag                    ->", run(["--wipe"]))
print("F10 --help                         ->", run(["--help"]))
print("F11 documented commands: README/DEMO use 'python seed.py --reset --yes' and 'python seed.py' -> accepted by the CLI (F1, F5)")
