import sys

sys.path.insert(0, r"<SCRATCH_DIR>")
from probe_common import *  # noqa: E402,F401,F403

app, ctx = seeded_app(LOGIN_RATE_LIMIT_ENABLED=False)
c = app.test_client()
adm = login_all(c)["admin"]
E = "é"  # e-acute: 2 bytes in UTF-8
J = "\U0001F600"  # emoji: 4 bytes
CJK = "密"  # 3 bytes
cases = [
    ("36 x e-acute  (36 chars, 72 bytes)", E * 36),
    ("37 x e-acute  (37 chars, 74 bytes)", E * 37),
    ("18 x emoji    (18 chars, 72 bytes)", J * 18),
    ("19 x emoji    (19 chars, 76 bytes)", J * 19),
    ("24 x CJK char (24 chars, 72 bytes)", CJK * 24),
    ("NFC vs NFD 'e'+combining acute (9 chars)", "caf" + "é" + "pass12"),
    ("leading/trailing spaces '  pass1234  '", "  pass1234  "),
]
for i, (name, pw) in enumerate(cases):
    email = f"uni{i}@t.com"
    r = c.post("/api/users", json={"full_name": "Uni Test", "email": email, "role": "Dispatcher", "password": pw}, headers=adm)
    lg = c.post("/api/auth/login", json={"email": email, "password": pw}).status_code if r.status_code == 201 else "-"
    extra = ""
    if r.status_code == 201 and i == 5:
        nfc = "cafépass12"
        extra = f" | login with precomposed (NFC) form -> {c.post('/api/auth/login', json={'email': email, 'password': nfc}).status_code}"
    if r.status_code == 201 and i == 6:
        extra = f" | login with trimmed 'pass1234' -> {c.post('/api/auth/login', json={'email': email, 'password': 'pass1234'}).status_code} (password is silently trimmed)"
    print(f"  {name:<44} create={r.status_code} login(same)={lg}{extra}  {(r.get_json() or {}).get('error','')[:40] if r.status_code!=201 else ''}")
