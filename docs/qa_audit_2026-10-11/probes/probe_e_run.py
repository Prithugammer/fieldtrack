import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

SP = r"<SCRATCH_DIR>"
BACKEND = os.getcwd()
PY = sys.executable
WANT = ["X-Content-Type-Options", "X-Frame-Options", "Referrer-Policy", "Content-Security-Policy", "Cache-Control", "Strict-Transport-Security", "Access-Control-Allow-Origin", "Access-Control-Allow-Methods", "Access-Control-Allow-Headers", "Vary", "Server", "Retry-After", "Content-Type"]


def env(extra):
    e = {k: v for k, v in os.environ.items() if k not in ("DATABASE_URL", "SECRET_KEY", "APP_ENV", "FLASK_DEBUG", "CORS_ORIGINS")}
    e.update(extra)
    return e


db = os.path.join(SP, "e.db").replace("\\", "/")
if os.path.exists(db):
    os.unlink(db)
base_env = {"DATABASE_URL": "sqlite:///" + db, "CORS_ORIGINS": "http://localhost:5174", "PYTHONDONTWRITEBYTECODE": "1"}
subprocess.run([PY, "seed.py"], env=env(base_env), capture_output=True, cwd=BACKEND)


def start(port, extra=None):
    p = subprocess.Popen([PY, "app.py"], env=env({**base_env, "PORT": str(port), **(extra or {})}), cwd=BACKEND, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(40):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1)
            return p
        except Exception:
            time.sleep(0.25)
    raise SystemExit("server did not start")


def req(port, path, method="GET", body=None, headers=None, raw=None):
    h = dict(headers or {})
    data = None
    if raw is not None:
        data = raw.encode()
        h["Content-Type"] = "application/json"
    elif body is not None:
        data = json.dumps(body).encode()
        h["Content-Type"] = "application/json"
    r = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data, method=method, headers=h)
    try:
        resp = urllib.request.urlopen(r, timeout=10)
        return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def show(label, status, headers, body=b""):
    present = {k: headers[k] for k in WANT if k in headers}
    miss = [k for k in WANT[:5] if k not in headers]
    print(f"  {label:<34} {status}  missing-core-headers={miss or 'none'}")
    return present


p1 = start(5056)
try:
    st, h, b = req(5056, "/api/auth/login", "POST", {"email": "supervisor@fieldtrack.com", "password": "Super123!"})
    tok = json.loads(b)["token"]
    A = {"Authorization": "Bearer " + tok}
    print("=== E1: core security headers on every kind of response (real dev server, APP_ENV unset)")
    first = None
    for label, args in [
        ("200 GET /api/health", ("/api/health",)),
        ("200 GET /api/jobs (auth)", ("/api/jobs", "GET", None, A)),
        ("401 GET /api/jobs (no token)", ("/api/jobs",)),
        ("404 unknown URL", ("/api/nope",)),
        ("405 wrong method", ("/api/health", "DELETE")),
        ("400 malformed JSON", ("/api/auth/login", "POST", None, None, "{bad")),
        ("401 wrong password", ("/api/auth/login", "POST", {"email": "supervisor@fieldtrack.com", "password": "x"})),
        ("403 wrong role", ("/api/users", "POST", {}, A)),
        ("409 business conflict", ("/api/safety/workers/99999/sos", "POST", None, A)),
        ("CSV download", ("/api/reports/hours.csv", "GET", None, A)),
    ]:
        st, h, b = req(5056, *args)
        pres = show(label, st, h)
        first = first or pres
    print("  sample header set:", json.dumps({k: v for k, v in first.items() if k not in ("Vary",)}, indent=2).replace("\n", "\n    "))
    print("=== E2: 429 response headers")
    for i in range(7):
        st, h, b = req(5056, "/api/auth/login", "POST", {"email": "admin@fieldtrack.com", "password": "bad"})
    pres = show("429 throttled login", st, h)
    print("  Retry-After:", h.get("Retry-After"), "| body:", b.decode()[:100])
    print("=== E3: CORS")
    for origin in ("http://localhost:5174", "http://evil.example", "http://localhost:5173"):
        st, h, b = req(5056, "/api/jobs", "OPTIONS", headers={"Origin": origin, "Access-Control-Request-Method": "GET", "Access-Control-Request-Headers": "authorization,content-type"})
        print(f"  preflight Origin={origin:<26} -> {st} Allow-Origin={h.get('Access-Control-Allow-Origin')} Allow-Headers={h.get('Access-Control-Allow-Headers')} security-headers-present={'X-Content-Type-Options' in h}")
    st, h, b = req(5056, "/api/jobs", "GET", headers={**A, "Origin": "http://evil.example"})
    print(f"  simple GET with Origin=evil -> {st}, Allow-Origin={h.get('Access-Control-Allow-Origin')} (header absent => browser blocks the response)")
    print("=== E4: error handling / information leakage")
    st, h, b = req(5056, "/api/jobs/1'%20OR%201=1", "GET", headers=A); print(f"  SQL-ish path -> {st} {b.decode()[:80]}")
    st, h, b = req(5056, "/api/auth/login", "POST", raw="{" * 100000); print(f"  100k nested '{{' body -> {st} {b.decode()[:90]}")
    st, h, b = req(5056, "/api/auth/login", "POST", raw='{"email":"' + "a" * 5_000_000 + '","password":"x"}'); print(f"  5 MB email field -> {st} {b.decode()[:90]}")
    st, h, b = req(5056, "/api/jobs", "POST", raw="[" * 50000, headers=A); print(f"  50k nested '[' to POST /api/jobs -> {st} {b.decode()[:90]}")
    print("  Server header:", h.get("Server"))
    st, h, b = req(5056, "/api/auth/login", "POST", body={"email": "supervisor@fieldtrack.com", "password": "Super123!"})
    print("  login 429 now? (limiter blocks the supervisor after probe loops above?)", st)
finally:
    p1.terminate()

print("=== E5: HSTS only when enabled AND request is HTTPS (TRUSTED_PROXY_COUNT=1 lets X-Forwarded-Proto speak)")
p2 = start(5057, {"HSTS_ENABLED": "1", "TRUSTED_PROXY_COUNT": "1"})
try:
    for label, hdrs in [("plain http", {}), ("X-Forwarded-Proto: https", {"X-Forwarded-Proto": "https"})]:
        st, h, b = req(5057, "/api/health", headers=hdrs)
        print(f"  HSTS_ENABLED=1, {label:<26} -> Strict-Transport-Security = {h.get('Strict-Transport-Security')}")
finally:
    p2.terminate()
p3 = start(5058)
try:
    st, h, b = req(5058, "/api/health", headers={"X-Forwarded-Proto": "https"})
    print(f"  HSTS_ENABLED unset, forwarded https -> Strict-Transport-Security = {h.get('Strict-Transport-Security')}")
finally:
    p3.terminate()
