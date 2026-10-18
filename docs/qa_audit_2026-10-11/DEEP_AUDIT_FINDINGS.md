# FieldTrack — Deep Audit Findings

**Audit date:** 2026-10-11 · **Method:** independent re-verification; every claim below was
re-tested in this audit (HTTP probes, differential tests, fuzzing, real-server checks) or is
explicitly marked *code inspection* / *UNVERIFIED*. Raw outputs are in [`evidence/`](evidence/),
the probe scripts in [`probes/`](probes/). No application source file was modified.

**Code under audit:** branch `prithugammer`, commit `1fd784e` ("new fixes"), working tree clean,
pushed to `origin/prithugammer`. (The previous summary described branch `main` with uncommitted
changes; that is no longer the case.) The pre-session baseline used for comparisons is commit
`67d9214`.

Severity scale: **Critical** (data loss / remote compromise) · **High** (feature unusable or
safety/availability impact, reproducible) · **Medium** (wrong results or security weakness under
realistic conditions) · **Low** (edge case, hygiene) · **Info**.

---

## 1. Status of every previously reported fix

| # | Claim | Status | Evidence (summary) |
|---|-------|--------|--------------------|
| 1 | `{"user_id": 1e999}` no longer 500 | **VERIFIED FIXED** | A1: 400, `field=user_id`; DB fingerprint unchanged |
| 2 | `GET /api/jobs/99999999999999999999999` no longer 500 | **VERIFIED FIXED** | A2: 404 on 8 endpoints × 8 hostile path ids |
| 3 | inf / -inf / NaN handled | **VERIFIED FIXED** | A1, A5: `Infinity`, `-Infinity`, `NaN`, `1e999` → 400 on ids, crew size, radius, lat/lng |
| 4 | 64-bit range enforced before SQLite | **VERIFIED FIXED** | A1: `2**63-1`→404 (valid, absent); `2**63`, `-(2**63)`, `-(2**63)-1`, 30-digit, 5000-digit → 400 |
| 5 | Zero / negative ids rejected | **VERIFIED FIXED** | A1/A3/A4: 0, -1 → 400 (body/query), 404 (path) |
| 6 | Consistent handling of path/query/body ids | **VERIFIED FIXED** | A2–A4 (16 query cases, 5 FK cases). Oddity: 5000-digit *path* id on `PATCH /api/jobs/…` returns 405, not 404 (Info, D-22) |
| 7 | Valid inputs still accepted (numeric strings, `5.0`, defaults) | **VERIFIED FIXED** | A1b/A5/I3: identical behaviour to pre-session code (201 for numeric-string ids, float `x.0` ids) |
| 8 | `parse_date("20261001")` rejected | **VERIFIED FIXED** | A6: `20261001`, `2026-W40-4`, `2026-1-1`, Unicode digits → 400; `2026-10-01` → 200 |
| 9 | Safety mutations Supervisor/Admin only (backend) | **VERIFIED FIXED** | B1/B4: Dispatcher, forged-Worker token → 403, no token → 401, on all 6 controls; 18 denied attempts leave state byte-identical |
| 10 | Frontend hides controls for non-controlling roles | **UNVERIFIED (browser)** | Code inspection (`LiveMap.jsx:241-242`) + 3 unit tests only |
| 11 | `GET /api/map/live` is read-only | **VERIFIED FIXED** | C1/C2/G: 50 polls change nothing; accident roll with probability 1 happens only on `POST /tick`; 17 GET routes ×3 leave DB + in-memory state identical |
| 12 | `POST /api/safety/tick` correct & safe | **PARTIALLY FIXED** | Auth, validation and concurrency are sound (C3: 480 parallel ticks ≡ sequential run, no duplicates). But escalation only advances while a client polls (D-12) |
| 13 | Login rate limiting + 429 + `Retry-After` | **VERIFIED FIXED** | D3 with caveats D-13 (temporary lock-out of a victim), process-local state |
| 14 | Production `SECRET_KEY` enforcement | **VERIFIED FIXED** | D7: absent/placeholder/31-char/dev-default → refuses to start (exit 1), 32+ random chars → starts; message never contains the key; `FLASK_DEBUG=1` in production refused |
| 15 | Security headers | **VERIFIED FIXED** (API) | E1/E2: present on 200/400/401/403/404/405/429/CSV downloads. HSTS only when enabled **and** HTTPS (E5). SPA CSP is *not* implemented (documented) |
| 16 | >72-byte password no longer 500 | **VERIFIED FIXED** | D2: create → 400 `at most 72 bytes`; login → 401 |
| 17 | No silent bcrypt truncation | **VERIFIED FIXED** | D2: user with `a×72` rejects `a×72+X` and `a×71`; Unicode boundary cases (72 bytes of é / 😀 / 密) accepted, 73+ refused |
| 18 | Token role not trusted after demotion | **VERIFIED FIXED** | D6: demote → 403 immediately; deactivate → 403; promote → effective immediately. Role comes from DB (`auth.py:19 role_required`) |
| 19 | Seed: ordinary seeding never drops data | **VERIFIED FIXED** | F1–F3 (counts identical across repeats; hand-added row preserved) |
| 20 | Seed: reset needs `--reset --yes`; refused in production / non-SQLite | **PARTIALLY FIXED** | F4–F6 pass. F7: for a non-SQLite URL the CLI dies with `ModuleNotFoundError` *before* reaching the guard (D-10) |
| 21 | 3 of 4 complex functions refactored, behaviour preserved | **VERIFIED FIXED** | radon: `_build_route` 26, `update_user` 18, `dashboard` 16 are all now below grade C (≤ 10). Differential test: 125 identical requests, 200 identical routes |
| 22 | `machine.observe` still complex | **CONFIRMED (as stated)** | radon C(18), unchanged |
| 23 | 444 backend tests, 98% coverage | **VERIFIED** | 444 passed; 98.24 % line (CI command) / 97 % line+branch. Excludes `tests/`, `tools/` |
| 24 | 17 frontend tests | **VERIFIED on Node 24 · FAILS on Node 20** | See D-01 |
| 25 | GitHub Actions workflow added | **PARTIALLY FIXED / UNVERIFIED remotely** | File parses; `gh run list` = 0 runs ever (D-01). Frontend job would fail as configured |
| 26 | Bundle 493 kB → 322 kB | **VERIFIED** (raw, like-for-like) | Initial JS 493.48 → 321.64 kB raw, 149.86 → 98.63 kB gzip; Live Map is a 172.19 kB / 50.78 kB gzip on-demand chunk. Total JS is unchanged |
| 27 | Docs updated | **PARTIALLY FIXED** | See D-18 |
| 28 | Worker self-clock-in | **NOT APPLICABLE** | `requirements.md` line 5: "Workers are managed as records; they do not log in." |
| 29 | Dispatcher lost break / "I'm OK" | **Neither defect nor requirement** — see §3 | |

**Totals (rows 1-27; row 22 is an observation, 28-29 are N/A or not a defect):** VERIFIED 20 ·
PARTIALLY FIXED / mixed 5 (#12, #20, #24, #25, #27) · UNVERIFIED 1 (#10) · NOT FIXED 0 · REGRESSION 0
attributable to the fixes (see §5).

---

## 2. Defect register

> **Current status of every item below: see §7 (Remediation record).** The text of this section is the original audit and is unchanged.

Pre-existing = reproduced identically on commit `67d9214`. "Blocks demo" = blocks a coursework
demonstration on the seeded data; "Blocks prod" = should be fixed before real deployment.

### D-01 — CI frontend job cannot pass; CI has never run — **High** (confirmed)
- **Component:** `.github/workflows/ci.yml:39` (`node-version: 20`), `frontend/package.json:26` (`jsdom ^30.1.2`).
- **Evidence:** lockfile resolves `jsdom 30.1.2`, `engines: ^22.22.2 || ^24.15.0 || >=26`. Running
  `vitest run` under Node **20.19.5** (the version CI installs): *all 3 test files fail to load* —
  `TypeError: webidl.util.markAsUncloneable is not a function` (`evidence/frontend_vitest_node20_FAILS.txt`).
  Build and Prettier pass on Node 20. `gh run list` returns `[]`: the workflow triggers only on
  push to `main` and on pull requests, and it exists only on branch `prithugammer`, so it has
  **never executed**. `README.md:86` still advertises "Node.js 20+".
- **Expected:** CI green on a clean checkout. **Actual:** `npm test` step fails.
- **Root cause:** test-runner dependency stack newer than the supported Node floor.
- **Fix:** run CI on Node 22/24 (and update README), or pin `jsdom@26` (supports Node 20); add
  `engines`. **Regression test:** the CI run itself. **Blocks demo:** no. **Blocks prod:** the CI gate, yes.

### D-02 — A job site outside the Kathmandu Valley hangs the Live Map and the safety controls — **High** (confirmed, pre-existing)
- **Component:** `backend/roads.py:50 nearest_node` (unbounded ring search), reached from
  `simulation._build_route` (`simulation.py:166`) → `road_path`.
- **Steps:** Dispatcher `PATCH /api/sites/{id}` with `latitude=28.2096, longitude=83.9856`
  (Pokhara, valid input → HTTP 200); then any `GET /api/map/live`.
- **Actual:** first call takes **13.5 s** (13.6 s on the pre-session code); a site at `(0, 0)` did not
  answer within 60 s (killed). Profile: 46 M iterations inside `nearest_node`. The result is cached
  afterwards, but every call blocks one server thread meanwhile. Safety controls call
  `compute_live_state()` too (`routes/safety.py` `_service()`), so `accident/sos/resolve/…` hang as
  well. Found because the fuzz sweep stalled for 20+ minutes after patching a site's coordinates.
- **Expected:** sites outside the simulated area are ignored or placed statically; the API either
  rejects them or the map stays responsive. **Root cause:** `while True` ring expansion with no
  radius cap. **Fix:** cap the search radius / skip routing beyond N km. **Regression test:** create a
  site at (28.2, 83.99) and assert `GET /api/map/live` < 1 s.
- **Blocks demo:** only if a far site is entered. **Blocks prod:** yes.

### D-03 — Duplicate overlapping time entries under concurrent submission — **Medium** (confirmed, pre-existing)
- **Component:** `routes/time_entries.py:39 _check_overlap`, `:147` (check-then-insert, no DB constraint).
- **Steps:** 12 simultaneous identical `POST /api/time-entries` (threaded server, file SQLite).
- **Actual:** `{201: 5, 409: 7}` — **5 identical overlapping entries stored** (violates FR-08 / NFR-04).
  Realistic trigger: double-click or two supervisors. **Fix:** serialise (transaction with
  `BEGIN IMMEDIATE`) or add a DB-level exclusion; disable the Save button while submitting.
  **Test:** concurrent-POST test asserting one row. **Blocks prod:** yes (payroll data).

### D-04 — Crew size can be exceeded under concurrency — **Medium** (confirmed, pre-existing)
- **Component:** `routes/assignments.py:88 job.is_full()` (check-then-insert).
- **Actual:** two workers racing for the last place, 25 trials → job overfilled in **24**. Violates FR-06.
  (Double-booking *is* safe: `UNIQUE(user_id, work_date)` — 10 racing requests gave exactly one row;
  approval is safe too — 12 racing Approve/Reject gave exactly one 200.) **Fix:** same as D-03.

### D-05 — Deeply nested JSON → HTTP 500, including on the unauthenticated login — **Low/Medium** (confirmed, pre-existing)
- **Component:** `validation.py:40 get_json` → `request.get_json(silent=True)` does not catch `RecursionError`.
- **Evidence:** `POST /api/auth/login` with 400 nested `[` → 400; **3,000 → 500**; 60,000 → 500; same on
  12 of the 17 fuzzed body-parsing endpoints (the rest return before parsing). Body is generic (`Something went wrong`), no leak,
  but each hit logs a stack trace (log-flood amplification). **Fix:** catch `RecursionError` in `get_json`
  and return 400; add `MAX_CONTENT_LENGTH`. (The previous "malformed JSON" tests did not include nesting.)

### D-06 — Lone Unicode surrogates in text → HTTP 500 — **Low/Medium** (confirmed, pre-existing)
- **Evidence:** JSON `"\ud800"` reaches SQLite and raises `UnicodeEncodeError`. 500 on job title,
  site name, user full name, trade (any field whose minimum length it clears) and **unauthenticated**
  `POST /api/auth/login` (`email`). **Fix:** reject strings that are not valid UTF-8 in `require_str`.

### D-07 — `date=9999-12-31` → HTTP 500 on time entries and reports — **Low** (confirmed, pre-existing)
- **Component:** `validation.py:225 day_bounds` (`start + timedelta(days=1)` overflows `date.max`).
- **Evidence (I1):** `GET /api/time-entries?date=9999-12-31`, `/api/reports/hours-by-worker?to=9999-12-31`,
  `/api/reports/flagged?from=0001-01-01&to=9999-12-31`, `/api/reports/hours.csv?to=9999-12-31` → 500.
  A user choosing an "open-ended" range hits it. **Fix:** clamp or catch `OverflowError`.

### D-08 — Login timing reveals which emails have accounts — **Medium** (confirmed, pre-existing)
- **Component:** `auth.py:81` (`user is None or not user.check_password(...)` short-circuits).
- **Evidence (D4, bcrypt cost 12):** known email, wrong password: median **213 ms**; unknown email:
  median **0.9 ms**. Responses are textually identical (and throttled identically), so the leak is purely
  timing. **Fix:** always run a dummy `bcrypt.checkpw`. **Blocks prod:** recommended.

### D-09 — No request-size limit — **Low/Medium** (confirmed)
- `MAX_CONTENT_LENGTH = None` (G): a 5 MB `email` field is fully read and parsed before being rejected.
  Combine with D-05. **Fix:** set e.g. 1 MB.

### D-10 — Seed CLI and startup act on the configured database before the safety guard — **Low/Medium** (confirmed)
- **Component:** `seed.py:372 main` (`app = app or create_app()` precedes `check_reset_allowed`), `app.py:78`
  (`db.create_all()` on every start).
- **Evidence (F7/F8):** `DATABASE_URL=postgresql://…` + `--reset --yes` → `ModuleNotFoundError: psycopg`
  traceback, never the friendly refusal (the guard is unreachable in this environment; it is only
  unit-tested with config dicts). An unreachable SQLite path prints a raw SQLAlchemy traceback. With a
  driver installed, `create_all()` would already have created FieldTrack tables inside a foreign database.
  No data is destroyed. **Fix:** parse `DATABASE_URL` and refuse before `create_app()`.

### D-11 — Datetime offsets are silently discarded; no sanity range on dates — **Low/Medium** (confirmed, pre-existing)
- **Component:** `validation.py:168-169`. `clock_in="…T07:00:00Z"` and `"…T07:00:00+05:45"` are both stored as
  07:00 local (A7). API spec says "no timezone"; the code accepts and drops it. Years 0001 and 9999 are
  accepted for job dates (A6). **Fix:** reject offsets (as documented) or convert.

### D-12 — Safety escalation exists only while a client is polling — **High for real deployment / Info for the simulated coursework scope** (confirmed)
- **Component:** `safety/service.py:109 _check_poll_gap`, `routes/safety.py:56 tick`.
- **Evidence (C4):** stationary worker; dashboard polling until t=12 s (CHECKIN_1 sent). No ticks until
  t=60 s. First tick after the gap: state **NORMAL**, audit shows `CHECKIN_CLEARED` ("monitoring was
  paused") — **no emergency was ever raised**, whereas continuous polling raises it at exactly t=25 s.
  Moving the driver from `GET` to `POST /tick` did not create this limitation (it existed before), and it
  is documented in the README, but it means: closing the tab, a laptop sleeping, or a browser throttling a
  background tab stops monitoring. Browser throttling of background-tab timers is plausible but
  **UNVERIFIED** here. A client cannot manipulate time (C5: server clock only). **Architecture
  recommendation (not implemented, per brief):** a server-side scheduler/worker for ticks.

### D-13 — Login throttle can be abused to lock a victim out temporarily — **Low/Medium** (confirmed, by design)
- D3: five bad attempts for `supervisor@…` from address A → the real supervisor (address B) gets 429 even
  with the right password, for up to 300 s. Not permanent (window expires; blocked attempts don't extend
  it); counters are per-process memory (cleared by restart; multiplied by worker count). Mitigation
  options: per-(account, client) counting, CAPTCHA/backoff, shared store.

### D-14 — Admin password reset does not end existing sessions — **Low/Medium** (confirmed)
- D6: after `PATCH /api/users/{id}` with a new password, the user's old token still returns 200 until
  expiry (8 h). Deactivation, demotion and deletion *do* take effect immediately. No server-side logout
  or token revocation exists.

### D-15 — Passwords are silently trimmed / not Unicode-normalised — **Info/Low** (confirmed)
- `require_str` strips whitespace, so `"  pass1234  "` is stored and verified as `pass1234`. NFC vs NFD
  forms of the same visible password do not match (401). Consistent on set and login, so it works, but
  surprising.

### D-16 — Test hygiene: 22 `ResourceWarning`s (unclosed SQLite connections) — **Low**
- Unclosed in-memory SQLite connections left to the garbage collector (likely the ad-hoc `create_app()` calls in the new tests; the exact source was not isolated).

### D-17 — Generated file tracked in git — **Low**
- `backend/.coverage` is tracked (`git ls-files`); `.gitignore` now lists it but ignoring does not untrack.

### D-18 — Documentation inconsistencies — **Low**
- README "Node.js 20+" vs test tooling needing ≥ 22.22 / 24.15 (D-01). README "98% coverage" is line-only
  (97 % with branches). `requirements.txt` is unpinned (`>=`), so CI resolves new versions each run, and it
  lists `pytest` as a runtime dependency. `Crew.jsx:227` placeholder phone `416-555-0100` is a Toronto
  format in a Nepal-based app. No `engines` field.

### D-19 — Dialogs have no focus trap and do not restore focus — **Low** (code inspection; UNVERIFIED in browser)
- `components/Modal.jsx`: Escape closes and the first control is focused (good), `role="dialog"`,
  `aria-modal`, `aria-labelledby` present, but Tab can leave the dialog and focus is not returned on close.

### D-20 — Live Map poll has no in-flight guard — **Low** (code inspection)
- `LiveMap.jsx:296 setInterval(poll, 1000)`: if the server answers slower than 1 s (see D-02) requests
  pile up. Ticks are safe to run concurrently (C3), so this is load, not corruption.

### D-21 — The safety subsystem has no requirements/analysis traceability — **Medium for the coursework report**
- Grep of `requirements.md`, `use-cases.md`, `dfd.md`, `class-diagram.md`, `erd.md`, `decision-table.md`:
  **0 mentions** of safety/emergency/SOS. Only the README, `api-spec.md`, `DEMO.md` describe it. For a
  *Systems Analysis & Design* submission that is "analysis first", the largest module has no FR/NFR, use
  case or role matrix. This is the real reason the Dispatcher question in §3 cannot be settled from
  requirements.

### D-22 — Cosmetic: 5000-digit path id gives 405 on `PATCH /api/jobs/…` (404 elsewhere) — **Info**
### D-23 — `Server: Werkzeug/3.1.9 Python/3.13.9` header on the dev server — **Info** (use a production WSGI server)

---

## 3. Safety role authorization — the Dispatcher question

**Implementation (verified):** `routes/safety.py:25 SAFETY_CONTROL_ROLES = ("Supervisor", "Admin")`
guards `accident`, `sos`, `respond`, `break`, `resolve`, `return-to-duty`. `tick` and all reads are open to
every staff role. Matrix (B1/B3):

| role | accident | sos | respond | break | resolve | return-to-duty | tick | GET config/audit/live |
|------|---|---|---|---|---|---|---|---|
| none | 401 | 401 | 401 | 401 | 401 | 401 | 401 | 401 |
| Worker (server-forged token) | 403 | 403 | 403 | 403 | 403 | 403 | 403 | 403 |
| Dispatcher | 403 | 403 | 403 | 403 | 403 | 403 | **200** | 200 |
| Supervisor / Admin | 201 | 201 | 200 | 200 | 200* | 200* | 200 | 200 |

\*when the state-machine precondition holds (resolve needs an EMERGENCY, return-to-duty needs POST_INCIDENT; otherwise 409).

Order check: authorisation precedes validation (a Dispatcher gets 403, not 400, for a bad body). No
alternate route mutates safety state (B4 lists every route; GETs proven read-only in G).

**What the documents say:** README: an EMERGENCY "only a supervisor can close"; DEMO: "Dispatchers can
watch but not act" (written in the previous session). Requirements/analysis documents: nothing (D-21).
`api-spec.md` before the previous session said "Role: Staff" for every safety route.

**Assessment:** the restriction on *resolve / return-to-duty* is supported by the README. The restriction on
*accident / sos / respond / break* is the previous session's own decision. Those four are **demo/simulation
controls** (they stand in for a worker's phone), so which staff role may press them has no operational
meaning outside the demo; the safety-relevant decision is who may **close** an emergency, and that is
consistent with the README. Operational implication: if no Supervisor/Admin is signed in, nobody can resolve
an emergency or mark a break; a Dispatcher sees the alert and must escalate by other means. **Verdict:**
not a defect, not a documented requirement — a design decision that needs to be written into the
requirements (D-21). The frontend matches the backend (static + unit tests; browser check pending, see
the manual plan SAF-06/RBAC-05).

---

## 4. Security review summary

| Area | Result |
|------|--------|
| Authentication | Bcrypt; wrong/unknown user identical text (timing differs, D-08); inactive/worker handled; tokens: expired, malformed, tampered, `alg=none`, wrong-key, Basic scheme, query-string token all rejected (D5) |
| Authorization | DB-authoritative role per request; every one of 35 method/route pairs returns 401 without a token (G) |
| Rate limiting | Works as specified; caveats D-13, process-local |
| Secrets/config | Production enforcement verified (D7). Dev default key exists only outside production |
| Headers/CORS | Verified on all response types; CORS reflects only configured origin (E3). No SPA CSP |
| Injection | SQL-style strings stored as data; all queries via SQLAlchemy; no injection found in 2,991 fuzz requests |
| Information leakage | Generic 500 body, no traces; `Overlaps entry #N for <worker>` names workers to staff only (acceptable) |
| Availability | D-02, D-05, D-06, D-07, D-09 |
| Integrity | D-03, D-04 |
| Logging | Throttle log lines contain client address only, no email/password (D3 + unit test) |

## 5. Regression assessment

No regression attributable to the fixes was found. Differential testing against the pre-session commit
(`evidence/differential_old_vs_new.txt`): 125 identical requests (valid and invalid, multi-error bodies
for `update_user`, whole dashboard payload, report endpoints) produced identical status codes and bodies
(the only 2 differing lines are `assigned_at` timestamps); 200 simulated routes hashed identically.
Intended behavioural changes (not regressions): role read from DB; `?route=abc` now 400 instead of ignored;
ids ≤ 0 now 400 instead of silently ignored filters; `parse_date` stricter; overlong passwords 400/401
instead of 500. One harness trap worth knowing: a script that demotes the user whose token it keeps using
will see 403 afterwards — that is the stale-role fix working.

## 6. Production-architecture limitations (not bugs)

SQLite + single process: safety state (`SafetyService`) and the login limiter are in memory (lost on restart,
split across workers); no migrations; Flask dev server; no PostgreSQL driver; map tiles need a Stadia key
off-localhost; no background scheduler (D-12); `create_all()` on every start.


---

## 7. Remediation record (second session, 2026-10-11)

Sections 1-6 above are the original audit and are unchanged. This section records, per finding, what was done and what
was actually verified. Line numbers refer to the working tree after the changes (uncommitted, branch `prithugammer`).
"Before" numbers are from the first audit's evidence files; "after" numbers from `evidence/*AFTER*`, `*FINAL*`, `J_`, `K_`.

### D-02 — Unbounded road search froze the Live Map and the safety controls → **FIXED, VERIFIED**
- **Root cause:** `roads.nearest_node` looped `while True`, widening the search ring until it found any road point (46 M
  iterations for Pokhara; effectively unbounded for (0, 0)). Safety actions call the same simulation.
- **Files:** `backend/roads.py` — `MAX_SNAP_M` (l. 23), `RouteUnavailable` (l. 29), `_coverage` (l. 69), `nearest_node` (l. 82),
  `is_routable` (l. 118); `backend/simulation.py` — `_road_route` (l. 71), `build_route` (l. 78), `UNROUTABLE_STATUS` (l. 39),
  `routable` (l. 419); `frontend/src/pages/LiveMap.jsx` — view bounds, `unroutableSites` alert (l. 335).
- **Reproduction (before):** `PATCH /api/sites/{id}` to (28.2096, 83.9856) then `GET /api/map/live` → 13.5 s; (0, 0) > 60 s.
  Re-created in `tests/test_map_robustness.py` (the lookup for Pokhara returned a node 140 km away after 2.9 s).
- **Fix:** an O(1) bounding-box rejection (the network's box + 5 km), at most ~12 rings, and `None` when nothing is within 5 km;
  non-finite / out-of-range input returns `None`. `road_path`/`snap` raise `RouteUnavailable`; `build_route` returns `None`
  (cached); `get_live_map_state` marks the site `routable: false` and its workers `"Route unavailable"` with no position;
  the page shows a warning and ignores such sites when choosing the opening view. **Supported area** = within 5 km of a road
  point of `data/kathmandu_roads.json` — an engineering bound documented in `docs/live-map-design.md`, not a requirement.
- **Regression tests:** `tests/test_map_robustness.py` (39): normal / 7 unsupported points / 10 invalid coordinates, hard time limits
  via daemon threads, API with far site, safety endpoints responsive, missing/non-numeric/out-of-range coordinates → 400, and
  **golden fingerprints of 6 routes produced by the original code** (supported routes are byte-identical). Frontend: unsupported
  site warning, only-unsupported sites, no marker for unrouted workers.
- **Result (after):** Pokhara first request **20 ms**, (0,0) **6 ms**, (-90,180) 8 ms; 101 requests each, all 200
  (`K_AFTER_stress_suite.txt`). With 6 threads hammering the map: 556 map requests served while 60 unrelated API calls
  (median 28.6 ms, max 133 ms) and 20 safety tick/SOS calls (max 51 ms) all answered. Real browser: warning visible in 1.55 s.
- **Remaining limitation:** a site 3-5 km from the roads is still routed (long walk from the nearest road); sites beyond
  are simply not simulated. `nearest_node` is now complexity grade C (15).

### D-12 — Safety escalation depended on a polling browser → **FIXED, VERIFIED** (restart limitation remains)
- **Root cause:** the state machine only advanced inside `SafetyService.process()`, which was called from dashboard HTTP
  requests; after a gap > `max_poll_gap_seconds` the service deliberately restarted every timer (`_check_poll_gap`,
  `safety/service.py` l. 109), so an unattended incident never escalated.
- **Trace (answers to the brief):** *stationary worker* → `observe()` starts an idle anchor; *check-in expiry* → only when
  `process()` is called, using due-times; *tab closes / connectivity lost* → no calls, so nothing advanced (before);
  *backend running with no clients* → nothing advanced (before); *concurrent clients* → serialised by `RLock`, transitions
  stamped with their due time so a repeat is a no-op; *restart* → all state is in memory and is lost.
- **Files:** `backend/safety/ticker.py` — `SafetyTicker` (l. 35), `tick_once` (l. 51), `start_background_services` (l. 90);
  `backend/app.py` — start in `__main__` (l. 205; debug-reloader parent skipped), `backend/wsgi.py` (new);
  `backend/safety/service.py` — `view()` (l. 97) read-only, `monitoring` block (l. 212); `backend/routes/map.py` adds
  `background`; `backend/config.py` — `SAFETY_TICKER_ENABLED` (l. 108), `SAFETY_TICK_INTERVAL_SECONDS`;
  `frontend/src/pages/LiveMap.jsx` — polls `GET /map/live` (l. 249), warnings for off/stale monitoring (l. 339).
- **Fix:** a heartbeat thread owned by the server process calls `process()` once a second; `create_app()` itself never
  starts it (tests, the seed script and tools stay thread-free). The page no longer drives anything.
- **Documented threshold** (not invented): the existing configuration — first check-in at `idle_threshold_seconds`, each
  window `checkin_response_window_seconds`, emergency after `num_checkins` windows (real mode 600 + 3×120 = 960 s; demo 15 + 3×5 = 30 s).
- **Regression tests:** `tests/test_safety_ticker.py` (16): escalation with no HTTP request at all; closing every tab; the gap
  behaviour without a heartbeat; "I'm OK" still works; background thread reaches EMERGENCY alone (500× clock); start/stop/restart
  idempotence; failing ticks are counted and the thread survives; heartbeat + 8 clients per second ≡ sequential run, one
  EMERGENCY per worker; restart forgets state and re-detects from scratch; wiring (testing mode / off switch / single thread);
  monitoring freshness field; role checks unchanged.
- **Result (after):** real `python app.py` process with only `/api/health` ever requested: IDLE_DETECTED at +15 s, three
  CHECKIN_SENT, **EMERGENCY at +30 s** (`J_AFTER_escalation_with_no_browser.txt`, reproduced inside `stress_suite.py`);
  480 requests from 8 simultaneous clients + the heartbeat gave an identical audit trail and zero duplicates.
- **Remaining limitations:** (1) state is in memory — an open emergency is lost on restart (tested + documented; persistence
  was not added because there is no requirement or table for it); (2) one process only; (3) if the process is *suspended*
  (laptop sleep) for > 10 s the timers restart, by design; (4) browser background-tab throttling no longer matters.

### D-01 — CI frontend job could not run → **FIXED locally, remote UNVERIFIED**
- **Root cause:** `jsdom 30.1.2` requires Node `^22.22.2 || ^24.15.0 || >=26` (and `undici 8` ≥ 22.19); the workflow used Node 20 and
  triggered only on `main` and pull requests, so it never executed.
- **Files:** `.github/workflows/ci.yml` (matrix Node 22, 24 at l. 50; `push: branches ["**"]`; `pip check`; `compileall`),
  `frontend/package.json` `engines` (l. 6), `README.md` requirements line.
- **Result:** `npm ci --dry-run` accepts the lockfile (unchanged); Prettier, **70/70 Vitest tests**, production build pass on
  Node **22.22.2** and **24.17.0** (`evidence/frontend_ci_equivalent_AFTER_node22_node24.txt`); YAML parses. Dependencies unchanged.
- **Remaining:** Python 3.10-3.12, Linux and the actual GitHub run are unverified; `gh run list` is empty because nothing is pushed.

### D-03 / D-04 — Races in clock-ins and crew capacity → **FIXED, VERIFIED**
- **Root cause:** `_check_overlap` (`routes/time_entries.py`) and `job.is_full()` (`routes/assignments.py`) read, then wrote, in
  separate steps; concurrent requests all passed the check.
- **Fix:** `backend/concurrency.py::begin_write()` (l. 45) takes SQLite's write lock (`BEGIN IMMEDIATE`) before the reads —
  in `create_time_entry` (l. 129), `clock_out` (l. 197), `approve` (l. 223) and `create_assignment` (l. 58). A lock held by
  another *process* works too. Backstop: partial unique index `uq_time_entries_one_open_per_worker` (`models.py` l. 23/239),
  created on existing databases by `ensure_schema_guards` (`app.py` l. 114; a warning, not a crash, if data already breaks it).
  Lock timeout `SQLITE_BUSY_TIMEOUT_SECONDS` (10 s) → HTTP **503 + `Retry-After: 1`** with nothing changed (`app.py` l. 159).
  Other databases would need row locks: `begin_write()` is a deliberate no-op there.
- **Regression tests:** `tests/test_concurrency.py` (21) on a real threaded server + file DB: 12 identical clock-ins, 8 different
  start times, 6 overlapping closed windows (pairwise non-overlap checked in the DB), simultaneous clock-outs and decisions,
  capacity boundaries (1/6, 3/8, 5/5, 4/10), 15 repeated last-place trials, double-booking, DB-level rejection of a second open
  entry, index creation/idempotence/dirty data, busy-database 503 and retry, rollback leaves the lock free. **Before the fix 10 of
  these failed** (capacity 3 took 7 of 8, capacity 4 took all 10).
- **Result (after):** 12 identical clock-ins → `{201: 1, 409: 11}`, 1 row (was `{201: 5, 409: 7}`, 5 rows); last-place race
  **0/25 overfilled** (was 24/25); 20 more trials + capacities 3/8 and 4/10 in the stress suite; `PRAGMA integrity_check` ok.
- **Remaining:** SQLite only; a request can wait up to the busy timeout (median 128-145 ms for 12 simultaneous identical
  clock-ins — they queue by design).

### D-05 / D-06 / D-07 / D-09 — Input-related HTTP 500s and missing size limit → **FIXED, VERIFIED**
- **Root causes:** `request.get_json(silent=True)` does not catch `RecursionError`; lone surrogates are valid JSON but cannot be
  encoded when SQLite binds them; `day_bounds` added one day to `date.max` (and the default 7-day report window subtracted past
  year 1); `MAX_CONTENT_LENGTH` was unset.
- **Files:** `validation.py` — `get_json` (l. 40; `RecursionError` l. 49), `require_str` (`UnicodeEncodeError` l. 70),
  `day_bounds` (l. 242); `routes/reports.py` `_date_range` (l. 29); `app.py` — `reject_oversized_bodies` (l. 82) and the 413 message;
  `config.py` `MAX_REQUEST_BYTES` → `MAX_CONTENT_LENGTH` (l. 113, default 1 MiB).
- **Reproduction (before):** 3,000 `[` → 500; `"\ud800"` in a title / login email → 500; `?date=9999-12-31` and `?to=9999-12-31` → 500;
  a 5 MB field was parsed in full. 74 of the new tests failed on the old code.
- **Fix:** nesting → `400 "Request body is nested too deeply."`; text that cannot be UTF-8 encoded → 400 on that field;
  overflow-safe windows (`datetime.max`, `date.min`); bodies over the limit → `413` from the `Content-Length` header before any
  route reads them. Real unexpected exceptions still return a generic 500 and are logged (tested).
- **Regression tests:** `tests/test_input_hardening.py` (108): 4 nesting shapes × 13 body endpoints, 13 oversize cases, 5 surrogate
  forms × 10 text fields, query/path garbage, valid Unicode (Nepali, accents, CJK, emoji) still accepted, 14 extreme-date URLs,
  last day (`9999-12-31`) and first day (`0001-01-01`) end to end, impossible dates still 400, configurable limit, a genuine bug
  still 500 + logged + no leak, security headers on the new 413/503.
- **Result (after):** audit fuzz (3,069 requests incl. all 17 endpoints × every field × 38 hostile values, 1,980 query-string cases):
  **0** responses ≥ 500 (was 20); integrity checks ok; 35/35 routes still 401 without a token; GETs still read-only.
- **Remaining:** none known for these classes; years 0001 / 9999 are still accepted as dates (no business range invented).

### D-08 — Login timing revealed account existence → **MITIGATED, measured**
- **Root cause:** `auth.py` short-circuited `user is None or not user.check_password(...)`, so unknown emails skipped bcrypt.
- **Fix:** `User.burn_password_check` (`models.py` l. 87) verifies against a cached dummy hash of the **same cost** for unknown emails,
  accounts without a password (Worker records) and anything else with nothing to compare; `auth.py` l. 81 uses it; the dummy hash is
  built at start-up. Over-long (> 72 byte) passwords skip bcrypt for known and unknown emails alike. Throttling, `Retry-After`
  and the generic message are untouched; throttled requests still cost no bcrypt.
- **Tests:** `tests/test_login_timing.py` (9): exactly one bcrypt verification per failure type, none when throttled, identical responses,
  dummy-hash caching and cost, a loose timing ratio (old gap was ~250×), no secrets logged, throttling unchanged.
- **Measured (bcrypt cost 12, n = 30, `F_AFTER_login_timing_cost12.txt`):** known email 206.1 ms median (p95 211), unknown 201.9 (p95 204), Worker
  record 204.1, inactive 202.6 — ratio **0.98**; before: 201.0 vs 0.6 ms (ratio 0.00).
- **Limitations (honest):** the two distributions overlap but are not identical (≈ 2 % median difference); an attacker with very many
  low-noise samples might still detect a few-ms bias, and network jitter normally hides it. Perfect equivalence is **not** claimed.
  The 429 throttle also bounds sampling (5 per account, 20 per client per window).

### D-19 — Dialog focus → **FIXED, VERIFIED (real browser)**
`components/Modal.jsx` (`FOCUSABLE`, l. 3): Tab / Shift+Tab cycle inside the dialog; Escape or Cancel returns focus to the opener.
Tests: `modal.test.jsx` (6) and the Playwright check "Tab never moves focus out of the dialog" (failed before, passes after).

### New findings from the real-browser run
| ID | Finding | Evidence (first run → final) | Fix / status |
|----|---------|------------------------------|--------------|
| N-01 | Page wider than the screen on phones: scrollWidth 422 / 603 / 412 / 500 / 488 px on a 390 px screen (Dashboard, Live Map, Crew, Time Entries, Reports); tablet Live Map 920 px on 820 | `browser_results_FIRST_RUN…json` | `.topbar` → `min-height` + `flex-wrap`, `.topbar__user` wraps, `.card__header` wraps, clock group wraps (`global.css`, `live-map.css`). **Fixed — 0 overflow at 1366 / 820 / 390 px, 7 pages** |
| N-02 | Scrollable tables unreachable by keyboard (axe `scrollable-region-focusable`, 5 scans / 7 nodes) | `browser_results_second_run…json` | `DataTable.jsx` (l. 37): `tabIndex=0`, `role="region"`, `aria-label`. **Fixed** (+3 tests) |
| N-03 | Contrast: muted text #6b7280 on #f4f5f7 = 4.43:1 (44 nodes); sidebar text 4.31:1 / 4.43:1 (42); white on green Approve button 3.47:1 (20) — axe `color-contrast`, 178 nodes in 19 of 21 scans | `contrast.mjs` output | `--color-muted` #636b79 (4.9:1), sidebar text alpha .45 → .58, `--color-green-600` #16803c for `.btn--success` (5.0:1). **Fixed** |
| N-04 | White on the brand orange `#ff7a00` primary button = **2.61:1** (14 px text) — 9 nodes, 9 scans | axe, after fixes | **OPEN — decision needed.** Options: navy `#14213d` text on the orange (6.1:1); or darken to `#b45309` / `#c2410c` (white text 5.0 / 5.2:1). Not changed because it alters the brand look |
| N-05 | Interactive targets < 24×24 px: Dashboard 5, Live Map 18 (map markers/controls) | `layout.small` in the JSON | **OPEN — Low.** WCAG 2.2 AA 2.5.8; outside the 2.1 AA scope axe was asked to check |

Final axe result (WCAG 2.0/2.1 A + AA, 21 page × viewport × theme scans): **12 scans with zero violations**; the other 9 contain only N-04.
Browser checks: **72 / 72 pass** (first run 61 pass, 10 fail — 8 of those were real defects: 6 horizontal-overflow cases = N-01 and 2 dialog-focus cases = D-19; 2 were
mistakes in the audit script that were corrected: a stray earlier emergency, and an init script that re-set the token).

### Status of findings not worked on this session
| ID | Sev | Status | Note |
|----|-----|--------|------|
| D-10 | Low/Med | OPEN | seed CLI creates the app (and tables) before the non-SQLite guard; unreachable DB gives a traceback |
| D-11 | Low/Med | OPEN | datetime offsets (`Z`, `+05:45`) still silently discarded; no business range on dates |
| D-13 | Low/Med | OPEN, by design | per-account throttle lets a third party lock a victim out for ≤ 300 s |
| D-14 | Low/Med | OPEN | an admin password reset does not end existing sessions (no token revocation) |
| D-15 | Info | OPEN | passwords are trimmed and not Unicode-normalised |
| D-16 | Low | OPEN | 35 `ResourceWarning`s (unclosed in-memory SQLite connections in tests) |
| D-17 | Low | OPEN | `backend/.coverage` is tracked in git |
| D-18 | Low | PARTIAL | Node range, test counts, env vars, deployment notes fixed; `requirements*.txt` still unpinned; Toronto phone placeholder |
| D-20 | Low | OPEN | Live Map poll has no in-flight guard (now pointless to worry: the server answers in ms, but unchanged) |
| D-21 | Med (report) | OPEN | no requirement / use case / role matrix for the safety subsystem |
| D-22, D-23 | Info | OPEN | 405 for a 5,000-digit path; `Server:` header on the dev server |

---

## 8. SESSION 3 record (2026-10-11, later) — findings D-10, D-11, D-13 … D-17, safety persistence, contrast

§7 above is the state after session 2 and is historical. Line numbers refer to the working tree now (uncommitted).

### D-12 (remaining part) — safety state lost on restart → **FIXED, VERIFIED**
- **Was:** all safety state in memory; a restart dropped an open emergency, the audit log and the messages.
- **Now:** `safety/store.py` — tables `safety_worker_state`, `safety_audit`, `safety_notification`, `safety_lease`; `safety/service.py` — `attach_store` / `reload`
  (l. ~95), `_persist` (one transaction), `_durable` (undo + 503 on failure), `_try_persist` (heartbeat retry), `monitoring.persistence`;
  `safety/machine.py` `to_state/from_state`; `safety/ticker.py` `_lead` (lease, takeover reload); `app.py` attaches the store after `create_all()` (start-up fails if unreadable).
- **Root-cause analysis:** the state machine, flags (`_frozen`, `_incapacitated`, `_on_break`), audit deque and notifier deque were plain attributes of `SafetyService`.
- **Not saved on purpose:** workers that are simply normal (no row), accumulated idle time before check-in 1, reply plans (re-derived from the seed), `_seen`
  (re-filled by the next tick; a restored worker is accepted by the API before that).
- **Regression tests:** `tests/test_safety_persistence.py` (22): emergency saved and restored (status, creation time, history); restart mid-escalation continues on schedule
  with no `CHECKIN_CLEARED`; 4 restarts → one emergency, one mock call; ids continue; "I'm OK" saved; false alarm / real incident / return-to-duty saved and restored;
  accident/break/incapacity saved; normal workers have no rows; **failed save → 503, emergency stays open, RESOLVED entry undone, database still says open**; every action undone on failure;
  heartbeat save failure → emergency still escalates in memory, warning, retried, saved once; unreadable database stops start-up; one bad row skipped; persistence can be off;
  6 threads × 40 ticks → 1 emergency; two processes → one leader; leader stops → takeover continues; expired lease taken; HTTP roles after restart; tables added to an old database without touching data.
  Verified to fail without the feature: `test_persistence_can_be_switched_off` shows the old behaviour (empty after restart).
- **Real-process proof:** `probes/restart_e2e.py` 14/14 (hard kill twice).
- **Remaining limitations / accepted risks:** SQLite only; one process; up to ~3 s extra delay when a crashed leader's lease must expire; during a *database outage plus restart*
  unsaved events are lost; nothing escalates while the server is down; audit retention undecided (no deletion, so the table grows); `_persist` complexity 16.

### N-04 — contrast of the primary button → **FIXED, MEASURED**
- **Cause:** `--color-white` text on `--color-orange` (#ff7a00) = 2.61:1. **Fix:** `--color-on-orange: #14213d` (brand navy) used by `.btn--primary` (`tokens.css`, `global.css`).
- **Measured in Chromium, Firefox, WebKit (computed styles):** rest 6.11:1, hover (#e56d00) 4.96:1, focus 6.11:1; the focus ring (a 35 % orange box-shadow) is a non-text indicator outside the button.
  Disabled state exempt (WCAG 1.4.3). White-on-orange *icons* none; the logo mark (white on orange) is exempt as a logo; orange text on navy is 6.11:1.
- **Regression:** `contrast.test.js` reads the real tokens and fails if any pair drops below 4.5:1; browser audit checks the three states.
- **Result:** axe (WCAG 2.0/2.1 A + AA), 21 scans per engine, light and dark, desktop / phone: **0 violations in all three engines**.

### D-10 — seed CLI acted on the database before the guard → **FIXED**
`seed.py::main` checks `check_reset_allowed` from `Config` *before* `create_app()`; any other failure prints one line (`Could not open or write the database (<ErrorType>)`) without the URL.
Tests: 7 subprocess tests (`test_audit_followups.py`). Severity before: Low/Medium (no data loss, but a foreign database could receive FieldTrack tables).

### D-11 — time zones silently dropped → **FIXED** (behaviour change)
`validation.parse_datetime` now returns 400 `must not include a time zone` for `Z` / offsets (normalising `Z` first so Python 3.10 gives the same message). The browser never sends a zone.
Dates years 0001-9999 remain accepted (no business range was invented; **accepted**).

### D-13 — lock-out by a stranger → **MITIGATED**
`security.LoginRateLimiter`: counters per (email, address) = 5, per email overall = 25 (`LOGIN_MAX_FAILURES_PER_ACCOUNT_TOTAL`), per address = 20. Tests: owner at another address still signs in
after 7 attacker failures; rotating 28 addresses hits the ceiling at 25. **Remaining:** an attacker using ≥ 25 addresses can still block the account for ≤ 300 s; memory per process; no CAPTCHA.

### D-14 — sessions survive a password reset → **FIXED**
`User.session_stamp()` (SHA-256 of the hash, 16 hex chars) is put in the token as `pwv`; `role_required` rejects a mismatch with 401 *Your session has ended*. Tests: reset ends only that user's sessions;
profile edits and an empty password field do not; resetting to the same password still ends them (new salt); tokens without the claim are refused (one-time re-login after upgrade).
**Remaining:** no logout-all / revocation list for other causes (role change and deactivation were already immediate).

### D-15 — passwords trimmed, no Unicode normalisation → **ACCEPTED RISK (Info)**
Consistent on set and login. Changing it would make existing users whose password has leading/trailing spaces or a different Unicode form unable to sign in. Revisit together with a forced reset.

### D-16 — test warnings → **FIXED**: 35 `ResourceWarning`s → 0 (`tests/conftest.py` closes the SQLite connections each test opened).

### D-17 — `backend/.coverage` tracked → **OPEN, owner action**: run `git rm --cached backend/.coverage` (it is already in `.gitignore`). Not done here because it edits the git index.

### D-18 / D-20 / D-21 / D-22 / D-23
D-18: Toronto phone placeholder replaced; **requirements still unpinned** (open). D-20: **fixed** (one poll at a time; test fails without the guard, passes with it).
D-21: safety requirements, roles, failure states, use case written (requirements §7, UC14) — **awaiting owner approval; DECISION NEEDED markers kept**. D-22 / D-23: **accepted**, cosmetic.

### Cross-platform findings (new)
| ID | Finding | Status |
|----|---------|--------|
| X-01 | Route golden test compared exact float hashes → failed on Linux and other Python versions | **FIXED** (structural summary, taken from the original code) |
| X-02 | Python 3.10 rejects `…Z` / one-digit fractions in `fromisoformat` → inconsistent 400 text | **FIXED** (`Z` normalised); fractions remain a 400 on 3.10 (format is `HH:MM[:SS]`) |
| X-03 | 'Nested too deeply' message depends on the Python version | **FIXED** in the test (both messages accepted; always a clean 400) |
| X-04 | CI only covered one Python version | **FIXED** (matrix 3.10 / 3.12 / 3.13) — not yet observed on GitHub |

### Unverified observations / not covered
PostgreSQL (unsupported); macOS; Safari proper (Playwright WebKit on Windows only); real touch devices; screen readers; high-contrast mode; multi-process serving; sustained load; power-loss durability of SQLite (default journal mode, no `PRAGMA synchronous` change).
