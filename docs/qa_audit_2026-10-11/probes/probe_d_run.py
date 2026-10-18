import base64
import json
import logging
import statistics
import subprocess
import sys
import time
from datetime import timedelta

sys.path.insert(0, r"<SCRATCH_DIR>")
from probe_common import *  # noqa: E402,F401,F403

from flask_jwt_extended import create_access_token  # noqa: E402
from models import User  # noqa: E402

logging.getLogger("fieldtrack.safety").setLevel(logging.ERROR)


def post_login(c, email, pw, **kw):
    return c.post("/api/auth/login", json={"email": email, "password": pw}, **kw)


print("=== D1: login outcomes")
app, ctx = seeded_app()
c = app.test_client()
lim = app.extensions["login_limiter"]
clock = {"t": 1000.0}
lim.clock = lambda: clock["t"]
for name, email, pw in [
    ("valid admin", "admin@fieldtrack.com", "Admin123!"),
    ("wrong password", "admin@fieldtrack.com", "nope-nope"),
    ("unknown user", "ghost@fieldtrack.com", "Admin123!"),
    ("worker record (no login)", "ramesh.karki@fieldtrack.com", "Admin123!"),
    ("empty body fields", "", ""),
]:
    r = post_login(c, email, pw)
    print(f"  {name:<28} -> {r.status_code} {r.get_json().get('error', 'token+user issued')[:70]}")
u = User.query.filter_by(email="dispatch2@fieldtrack.com").one()
u.is_active = False
from extensions import db  # noqa: E402

db.session.commit()
r = post_login(c, "dispatch2@fieldtrack.com", "Dispatch123!")
print(f"  {'inactive account (right pw)':<28} -> {r.status_code} {r.get_json()['error'][:70]}")
r = post_login(c, "dispatch2@fieldtrack.com", "wrong")
print(f"  {'inactive account (wrong pw)':<28} -> {r.status_code}  (does not reveal that the account is inactive)")
u.is_active = True
db.session.commit()
lim._failures.clear()

print("\n=== D2: password length / encoding (bcrypt 72-byte limit)")
H = login_all(c)
adm = H["admin"]
tests = [
    ("72 ASCII bytes", "a" * 72),
    ("73 ASCII bytes", "a" * 73),
    ("128 chars (max)", "a" * 128),
    ("129 chars", "a" * 129),
    ("36 x 'Ã©' = 72 bytes", "Ã©" * 36),
    ("37 x 'Ã©' = 74 bytes", "Ã©" * 37),
    ("emoji x18 = 72 bytes", "ðŸ˜€" * 18),
    ("emoji x19 = 76 bytes", "ðŸ˜€" * 19),
    ("contains NUL char", "abcd\u0000efghij"),
    ("8 spaces", " " * 8),
    ("leading/trailing space", "  pass1234  "),
]
for i, (name, pw) in enumerate(tests):
    email = f"pwtest{i}@t.com"
    cr = c.post("/api/users", json={"full_name": "Pw Test", "email": email, "role": "Dispatcher", "password": pw}, headers=adm)
    lg = post_login(c, email, pw) if cr.status_code == 201 else None
    lim._failures.clear()
    print(f"  create {name:<26} -> {cr.status_code} {((cr.get_json() or {}).get('error') or '')[:48]:<48} login-with-same -> {lg.status_code if lg else '-'}")
print("  login attempts with over-long / NUL passwords against a real account:")
for name, pw in [("73 bytes", "a" * 73), ("NUL byte", "Admin\u0000123!"), ("128 chars", "x" * 128)]:
    r = post_login(c, "admin@fieldtrack.com", pw)
    print(f"    {name:<10} -> {r.status_code}")
lim._failures.clear()
print("  truncation check: user with password 'a'*72 must not accept 'a'*72+'X' or 'a'*71")
cr = c.post("/api/users", json={"full_name": "Trunc Test", "email": "trunc@t.com", "role": "Dispatcher", "password": "a" * 72}, headers=adm)
print("   create 72-byte user:", cr.status_code)
for name, pw in [("exact", "a" * 72), ("a*72+X (73 bytes)", "a" * 72 + "X"), ("a*71", "a" * 71)]:
    print(f"   login {name:<20} -> {post_login(c, 'trunc@t.com', pw).status_code}")
    lim._failures.clear()

print("\n=== D3: login throttling (fake clock; defaults 5/acct, 20/client, 300 s)")
lim._failures.clear()
clock["t"] = 5000.0
codes = [post_login(c, "admin@fieldtrack.com", "bad").status_code for _ in range(8)]
r = post_login(c, "admin@fieldtrack.com", "bad")
print("  8 bad attempts:", codes, "| 9th:", r.status_code, "Retry-After:", r.headers.get("Retry-After"))
print("  429 body:", r.get_json())
print("  429 carries security headers:", all(h in r.headers for h in ("X-Content-Type-Options", "X-Frame-Options", "Referrer-Policy", "Content-Security-Policy")))
print("  correct password while blocked:", post_login(c, "admin@fieldtrack.com", "Admin123!").status_code)
clock["t"] += 299
print("  +299 s (still inside window):", post_login(c, "admin@fieldtrack.com", "Admin123!").status_code)
clock["t"] += 2
print("  +301 s (window expired), correct password:", post_login(c, "admin@fieldtrack.com", "Admin123!").status_code)
print("  immediately after success, 5 fresh failures allowed:", [post_login(c, "admin@fieldtrack.com", "bad").status_code for _ in range(5)])
lim._failures.clear()
print("  case/whitespace variants share ONE counter:", [post_login(c, e, "bad").status_code for e in ("admin@fieldtrack.com", "ADMIN@fieldtrack.com", " Admin@FieldTrack.com ", "admin@fieldtrack.com", "ADMIN@FIELDTRACK.COM", "admin@fieldtrack.com")])
lim._failures.clear()
print("  X-Forwarded-For rotation ignored when TRUSTED_PROXY_COUNT=0:", [post_login(c, "admin@fieldtrack.com", "bad", headers={"X-Forwarded-For": f"10.0.0.{i}"}).status_code for i in range(7)])
lim._failures.clear()
print("  attacker locks a victim out (5 bad attempts from another address), victim then tries the right password:")
for i in range(5):
    post_login(c, "supervisor@fieldtrack.com", "guess", environ_overrides={"REMOTE_ADDR": "203.0.113.9"})
print("   victim from own address ->", post_login(c, "supervisor@fieldtrack.com", "Super123!", environ_overrides={"REMOTE_ADDR": "198.51.100.4"}).status_code, "(429 = per-account throttle is a temporary denial-of-service vector)")
lim._failures.clear()
print("  per-client cap: 25 different unknown emails from one address:", Counter_ := None)
from collections import Counter  # noqa: E402

print("   ", dict(Counter(post_login(c, f"nobody{i}@x.com", "bad").status_code for i in range(25))))
lim._failures.clear()
print("  limiter memory bound (MAX_KEYS=10000): 12000 distinct emails ->", end=" ")
for i in range(12000):
    lim.record_failure(f"spray{i}@x.com", "9.9.9.9")
print(len(lim._failures), "keys retained")
lim._failures.clear()

print("\n=== D4: user-enumeration by response time (bcrypt cost 12, 12 samples each, limiter off)")
app12, ctx12 = seeded_app(BCRYPT_ROUNDS=12, LOGIN_RATE_LIMIT_ENABLED=False)
c12 = app12.test_client()
def timed(email):
    t0 = time.perf_counter()
    post_login(c12, email, "wrong-password")
    return (time.perf_counter() - t0) * 1000
known = [timed("admin@fieldtrack.com") for _ in range(12)]
unknown = [timed("ghost@fieldtrack.com") for _ in range(12)]
print(f"  known email (wrong pw):   median {statistics.median(known):7.1f} ms  min {min(known):7.1f}")
print(f"  unknown email:            median {statistics.median(unknown):7.1f} ms  max {max(unknown):7.1f}")
print("  => distinguishable by timing:", statistics.median(known) > 5 * statistics.median(unknown))
ctx12.pop()

print("\n=== D5: tokens")
app, ctx = seeded_app()
c = app.test_client()
H = login_all(c)
sup_user = User.query.filter_by(email="supervisor@fieldtrack.com").one()
def hdr(tok):
    return {"Authorization": "Bearer " + tok}
good = H["supervisor"]["Authorization"].split()[1]
claims = {"user_id": sup_user.user_id, "role": "Supervisor"}
expired = create_access_token(identity=str(sup_user.user_id), additional_claims=claims, expires_delta=timedelta(seconds=-5))
def b64(d):
    return base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()
alg_none = b64({"alg": "none", "typ": "JWT"}) + "." + b64({"sub": "1", "user_id": 1, "role": "Admin", "type": "access", "exp": 9999999999, "jti": "x", "fresh": False, "iat": 1}) + "."
head, pay, sig = good.split(".")
forged_pay = json.loads(base64.urlsafe_b64decode(pay + "=" * (-len(pay) % 4)))
forged_pay["role"] = "Admin"; forged_pay["user_id"] = 1
tampered_claims = head + "." + b64(forged_pay) + "." + sig
wrong_key = None
try:
    import jwt as pyjwt  # noqa: E402
    wrong_key = pyjwt.encode({**forged_pay, "sub": "1"}, "some-other-secret-value-0123456789abcdef", algorithm="HS256")
except Exception as e:  # noqa: BLE001
    wrong_key = None
for name, tok in [
    ("valid", good), ("expired", expired), ("malformed 'abc'", "abc"), ("empty bearer", ""), ("alg=none forged admin", alg_none),
    ("payload edited (role=Admin), old signature", tampered_claims), ("signed with a different key", wrong_key or "n/a"),
    ("truncated signature", good[:-6]),
]:
    r = c.get("/api/users", headers=hdr(tok))
    print(f"  {name:<44} -> {r.status_code}")
r = c.get("/api/users", headers={"Authorization": "Basic abc"}); print(f"  {'Authorization: Basic abc':<44} -> {r.status_code}")
r = c.get("/api/users?access_token=" + good); print(f"  {'token in query string (should be ignored)':<44} -> {r.status_code}")

print("\n=== D6: role / status changes AFTER a token was issued")
from extensions import db  # noqa: E402
adm_tok = H["admin"]; sup_tok = H["supervisor"]; dis_tok = H["dispatcher"]
print("  baseline  supervisor token on POST /api/safety/workers/1/sos (refusal expected for unknown id):", c.post("/api/safety/workers/1/sos", headers=sup_tok).status_code)
adm_u = User.query.filter_by(email="admin@fieldtrack.com").one()
sup_user.role = "Dispatcher"; db.session.commit()
print("  supervisor demoted to Dispatcher -> old token on safety control:", c.post("/api/safety/workers/101/sos", headers=sup_tok).status_code, "| on time-entry create:", c.post("/api/time-entries", json={}, headers=sup_tok).status_code, "(403 expected)")
sup_user.role = "Supervisor"; db.session.commit()
d_user = User.query.filter_by(email="dispatch@fieldtrack.com").one()
d_user.role = "Admin"; db.session.commit()
print("  dispatcher PROMOTED to Admin -> old (Dispatcher) token on admin route:", c.post("/api/users", json={}, headers=dis_tok).status_code, "(400 = authorised; privileges follow the database, upward as well as downward)")
d_user.role = "Dispatcher"; db.session.commit()
d_user.is_active = False; db.session.commit()
print("  dispatcher deactivated -> old token:", c.get("/api/jobs", headers=dis_tok).status_code, "| login:", post_login(c, "dispatch@fieldtrack.com", "Dispatch123!").status_code)
d_user.is_active = True; db.session.commit()
r = c.patch(f"/api/users/{d_user.user_id}", json={"password": "BrandNewPass1!"}, headers=adm_tok)
print("  admin resets the dispatcher password (", r.status_code, ") -> OLD token still works:", c.get("/api/jobs", headers=dis_tok).status_code, "(200 = no server-side session revocation until the 8 h expiry)")
db.session.delete(User.query.filter_by(email="dispatch2@fieldtrack.com").one()) if False else None

print("\n=== D7: production secret enforcement in a fresh process (APP_ENV=production)")
import os  # noqa: E402

def run(env, code="import app; app.create_app(); print('STARTED')"):
    e = {k: v for k, v in os.environ.items() if k not in ("DATABASE_URL", "SECRET_KEY", "JWT_SECRET_KEY", "APP_ENV", "FLASK_DEBUG")}
    e.update(env); e["DATABASE_URL"] = "sqlite:///:memory:"
    p = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=e, cwd=".")
    last = (p.stdout.strip().splitlines() or p.stderr.strip().splitlines() or ["(no output)"])[-1]
    return p.returncode, last[:130]
secret_ok = "q7Zr2LmX9vB4nT8cJ1wY5hD3kF6pS0aG"  # throwaway 32-char test value
for name, env in [
    ("production, no SECRET_KEY", {"APP_ENV": "production"}),
    ("production, SECRET_KEY=change-me", {"APP_ENV": "production", "SECRET_KEY": "change-me"}),
    ("production, 31-char key", {"APP_ENV": "production", "SECRET_KEY": "x" * 31}),
    ("production, dev default key", {"APP_ENV": "production", "SECRET_KEY": "fieldtrack-local-dev-secret-change-me"}),
    ("production, strong key", {"APP_ENV": "production", "SECRET_KEY": secret_ok}),
    ("production, strong key + weak JWT key", {"APP_ENV": "production", "SECRET_KEY": secret_ok, "JWT_SECRET_KEY": "weak"}),
    ("typo APP_ENV=prod", {"APP_ENV": "prod"}),
    ("APP_ENV unset (development)", {}),
    ("APP_ENV=PRODUCTION (case)", {"APP_ENV": "PRODUCTION"}),
]:
    rc, out = run(env)
    print(f"  {name:<40} exit={rc} {out}")
rc, out = run({"APP_ENV": "production", "SECRET_KEY": secret_ok, "FLASK_DEBUG": "1"}, code="import runpy,sys; sys.argv=['app.py']; runpy.run_path('app.py', run_name='__main__')")
print(f"  {'production + FLASK_DEBUG=1 via python app.py':<40} exit={rc} {out}")
print("  secret value never printed in any message above:", secret_ok not in out)

