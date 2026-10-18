# FieldTrack — Automated Test Results (independently reproduced)

Run on 2026-10-11 against branch `prithugammer`, commit `1fd784e`, clean working tree. Nothing here is
copied from the previous session's report; every number below was produced during this audit.
Raw logs: [`evidence/`](evidence/).

## 1. Environment

| Item | Value |
|------|-------|
| OS | Windows 11 Home 10.0.26200 (12 logical CPUs) |
| Python | 3.13.9 (project venv `backend/.venv`); CI would use 3.12 (not run locally) |
| Node / npm | v24.17.0 / 11.13.0; also **v20.19.5** (borrowed through `npx node@20.19.5`, repo untouched) |
| Key packages | Flask 3.1.3, Flask-SQLAlchemy 3.1.1, SQLAlchemy 2.1.3, Flask-JWT-Extended 4.7.4, bcrypt 5.0.0, Werkzeug 3.1.9, pytest 9.1.1, pytest-cov 7.1.0, black 26.5.1 |
| Measurement tools | `radon 6.0.1` was installed into `backend/.venv` for complexity numbers; it is **not** in `requirements*.txt` |
| Shell state | A stray `DATABASE_URL` (PostgreSQL, another project) exists in the user's shell; it was cleared **per process** for every run (`[Environment]::SetEnvironmentVariable('DATABASE_URL',$null,'Process')`). Without that the app does not start (`ModuleNotFoundError: psycopg`) |
| Isolation | Tests use `sqlite:///:memory:`; probes used scratch files outside the repo. The developer database `backend/instance/fieldtrack.db` was not touched (mtime predates the audit) |

## 2. Backend

| Command (from `backend/`) | Result |
|---------------------------|--------|
| `pytest --collect-only -q` | **444 tests** collected |
| `pytest -p no:cacheprovider --cov --cov-branch -rs` | **444 passed, 0 failed, 0 skipped, 0 errors**, 22 warnings (all `ResourceWarning: unclosed database`), 59 s |
| `pytest --cov --cov-report=term:skip-covered --cov-fail-under=85` (the exact CI command) | 444 passed; **98.24 % line coverage** (2,162 statements, 38 missed); gate 85 % met |
| Same with `--cov-branch` | **97 %** combined (556 branches, 33 partial) |
| `black --check .` | clean — 43 files unchanged |
| `pip check` | no broken requirements |
| `radon cc -a` (application code) | 238 blocks, **average A (3.21)** |
| `radon cc -n C` (grade C or worse) | `parse_int` 14, `_best_departures` 13, `SafetyMachine.observe` **18**, `SafetyService._alerts` 12, `_nearest_coworker` 12 |
| `radon mi -n B` | only `tests/test_safety.py` (B, 18.75) |
| Linter / type checker | **None configured** in the repo (`ruff` cache directory exists but ruff is not installed). Not run |

Per-file test counts: `test_validation` 166 · `test_assignments_entries_api` 44 · `test_jobs_api` 36 ·
`test_auth_hardening` 34 · `test_users_api` 34 · `test_safety` 32 · `test_security` 27 · `test_safety_authz` 25 ·
`test_rules` 19 · `test_seed` 16 · `test_map` 11 (= 444).

**Coverage configuration (`backend/pyproject.toml`):** `source = ["."]`, `omit = [".venv/*", "tests/*", "tools/*", "instance/*"]`.
Unmeasured application-adjacent code: `tools/build_road_network.py` (111 lines, a one-off script). Lowest
measured modules: `app.py` 86 % (error-handler tails and the `__main__` block), `routes/reports.py` 94 %, `routes/dashboard.py` 95 %,
`safety/service.py` 95 %. Line coverage proves execution, not assertion quality; the fuzz and race probes
(below) found defects that 97–98 % coverage did not (see "Limits of the suite").

**Warnings:** 22 `ResourceWarning`s for unclosed in-memory SQLite connections — test hygiene (D-16).

## 3. Frontend

| Command (from `frontend/`) | Result |
|----------------------------|--------|
| `npm run format:check` | clean (Node 24 and Node 20) |
| `npm test` (`vitest run`) on **Node 24.17** | **17 passed** in 3 files (`api.test.js` 5, `safetyPanel.test.jsx` 3, `app.test.jsx` 9) |
| `vitest run` on **Node 20.19.5** | **FAIL — 3 of 3 files error at load**, 0 tests run: `TypeError: webidl.util.markAsUncloneable is not a function` (`jsdom 30.1.2` → `undici`) |
| `npm run build` (Node 24 and Node 20) | succeeds; no warnings; 114 modules |
| `npm ci --dry-run` | lockfile in sync with `package.json` |
| Lint / type-check | none configured |

**Bundle sizes (Vite, 1 kB = 1000 B; raw / gzip):**

| Chunk | Before (single chunk) | After |
|-------|-----------------------|-------|
| Initial JS (`index-*.js`) | 493.48 kB / 149.86 kB | **321.64 kB / 98.63 kB** (−34.8 % raw, −34.2 % gzip) |
| `LiveMap-*.js` (loaded only on `/live-map`) | — | 172.19 kB / 50.78 kB |
| Total JS | 493.48 kB | 493.83 kB (unchanged; split, not reduced) |
| CSS | 41.14 kB / 11.63 kB | 18.62 kB / 4.06 kB initial + 22.53 kB / 8.03 kB lazy |

The like-for-like comparison is raw-to-raw and gzip-to-gzip (the "493 → 322 kB" figures are both raw).
`LiveMap` is genuinely lazy (`App.jsx` `lazy(() => import('./pages/LiveMap'))` + `Suspense`; separate chunk in the build).
Cost: the first visit to the Live Map pays an extra request; the loading fallback is "Loading the map…".

## 4. Continuous integration

| Check | Result |
|-------|--------|
| `.github/workflows/ci.yml` parses as YAML | yes — jobs `backend`, `frontend`; triggers `push: main`, `pull_request` |
| Backend job commands match the repo (`requirements-dev.txt`, `black --check .`, `pytest --cov … --cov-fail-under=85`) | yes (the same commands pass locally on Python 3.13) |
| Frontend job on its configured Node (20) | **would fail at `npm test`** (§3). `npm ci`, format and build would pass |
| Lockfile contains Linux optional binaries (`@rollup/rollup-linux-x64-gnu`, `@esbuild/linux-x64`) | yes |
| Secrets/environment required | none |
| Dependency pinning | `requirements*.txt` use `>=` ranges → CI result may drift over time |
| **Has it ever run on GitHub?** | **No.** `gh run list` → `[]`; `gh workflow list` → empty; `gh pr list` → empty. The workflow exists only on `prithugammer` and triggers only on pushes to `main` / pull requests |
| Status | **Locally inspected, not remotely verified. Not observed passing.** |

## 5. Independent behavioural probes (this audit)

Each probe is a script in `probes/` with its captured output in `evidence/`.

| Probe | What it did | Headline result |
|-------|-------------|-----------------|
| A — validation | 24 numeric forms × 2 ids, 8 path forms × 8 endpoints, 16 query filters, 5 FK bodies, dates, datetimes | 0 × HTTP 500; DB fingerprint unchanged by rejected requests |
| B — safety authz | roles none / forged Worker / Dispatcher / Supervisor / Admin × 6 controls + tick + 5 reads | exactly the intended matrix; state byte-identical after 18 denied attempts |
| C — live map / tick | 50 GET polls; accident-roll isolation; 8 simultaneous clients × 60 s (480 requests) vs sequential; 47 s polling gap | GET is read-only; concurrent ticks ≡ sequential (33 identical events, 0 duplicates); **gap clears the check-in** (D-12) |
| D — auth | login matrix, 11 password encodings, throttle (fake clock), timing, 10 token attacks, role/status changes, 9 production-secret scenarios | all pass; D-08 (timing), D-13, D-14 observed |
| E — headers | real dev server: 10 response types, 429, CORS preflight ×3, HSTS ×3 | headers on every response; CORS correct; HSTS only when enabled + HTTPS |
| F — seed CLI | 13 scenarios incl. production, non-SQLite, missing directory | guard works for SQLite/production/confirmation; D-10 for non-SQLite |
| G — fuzz | **2,991 requests**: 17 endpoints × every field × 38 hostile values + 14 hostile bodies each + path ids; 1,980 query-string cases; integrity checks | 20 × 500 (D-05, D-06); FK check + `integrity_check` = ok; all GET routes read-only; 35/35 route-method pairs 401 without token |
| H — performance & races | latency (n = 100 / 60) in-memory and file-backed HTTP; 8-way tick load; 4 race scenarios | NFR-03 met; **D-03, D-04 reproduced**; UNIQUE-constraint and single-decision races safe |
| I — edge cases | extreme dates, surrogates, nesting depth | D-05, D-06, D-07 |
| Differential | identical 125 requests + 200 route hashes on `67d9214` vs `1fd784e` | identical (except two timestamps) |
| Far-site | move a site to Pokhara / (0,0) | **D-02**: 13.5 s / > 60 s (13.6 s on the old code too) |

## 6. Performance (measured; baseline only)

Measured on the audit machine (12 logical CPUs, Windows 11, Python 3.13), seeded demo data, 10 discarded warm-ups.
Medians / p95 in ms.

| Endpoint | Test client, in-memory DB (n = 100) | Real HTTP, file SQLite, threaded server (n = 60) |
|----------|-------------------------------------|---------------------------------------------------|
| `/api/dashboard` | 7.0 / 8.1 | 13.4 / 16.2 |
| `/api/jobs` | 6.7 / 7.5 | 13.2 / 14.8 |
| `/api/time-entries` | 6.4 / 7.8 | 12.8 / 16.0 |
| `/api/map/live` | 3.5 / 4.7 | 7.6 / 10.5 |
| `/api/sites` | 2.9 / 3.9 | 7.0 / 17.8 |
| `/api/users` | 1.4 / 2.0 | 4.5 / 5.3 |
| `/api/reports/hours-by-worker` | 4.6 / 5.8 | 7.7 / 9.3 |
| `/api/reports/hours.csv` | 7.2 / 8.5 | 12.0 / 14.7 |
| `POST /api/safety/tick`, 8 simultaneous clients | — | 45.2 / 56.9 (0 errors, 240 requests) |

NFR-03 ("< 500 ms on the demo dataset") is met with a wide margin. Limits: tiny dataset, one machine, no
network latency, dev server, no sustained load; **a job site outside the Valley (D-02) turns the same call
into 13 s – unbounded.** These numbers are not production guarantees.

## 7. Limits of this suite and of this audit

- Line coverage ≠ requirement coverage: the 444 tests did not include nesting, surrogates, date extremes,
  concurrency, far-away sites or CI-matrix (Node 20) execution — all of which produced defects here.
- No browser, mobile or accessibility execution was possible: the Claude-in-Chrome extension reported
  "not connected" in the previous session and again when retried during this audit. The UI was inspected
  statically only; the manual test plan covers it.
- GitHub Actions: not observed.
- Python 3.12, Linux and macOS: not executed.

---

# Update — results after the remediation session (2026-10-11)

Sections above are the first audit's results (unchanged). Everything below was run after the fixes, on the same machine
(Windows 11, 12 logical CPUs, Python 3.13.9, bcrypt 5.0.0, SQLAlchemy 2.1.3) with `DATABASE_URL` cleared per process.
All databases used by tests, probes and the stress suite were temporary files or `:memory:`; the developer database was not opened.

| Check (exact command, from the stated directory) | Result |
|---|---|
| `backend$ pytest --collect-only -q` | **637 tests** (was 444) |
| `backend$ pytest --cov --cov-report=term-missing:skip-covered --cov-fail-under=85` (the CI command) | **637 passed, 0 failed**, 35 `ResourceWarning`s; **97.83 %** line coverage (2,394 stmts, 52 missed). With `--cov-branch`: 96.88 % (614 branches, 34 partial) |
| `backend$ black --check .` | clean, 51 files |
| `backend$ pip check` / `python -m compileall -q .` | no broken requirements / exit 0 |
| `backend$ radon cc -n C` | grade C: `parse_int` 14, `_best_departures` 13, `nearest_node` 15, `SafetyMachine.observe` 18, `_alerts` 12, `_nearest_coworker` 12; average **A (3.25)** |
| `frontend$ npm ci --dry-run` | lockfile accepted (unchanged) |
| Node **22.22.2** and **24.17.0**: `prettier --check .`, `vitest run`, `vite build` | all pass; **70 tests** in 7 files (api 5, app 9, dataTable 3, liveMap 17, modal 6, pages 27, safetyPanel 3) |
| `vitest` on Node 20 | still cannot load (documented; not a CI target any more) |
| Build sizes (raw / gzip) | initial JS 322.34 kB / 98.87 kB; LiveMap chunk 173.07 kB / 51.15 kB |
| Browser audit (`probes/browser/audit_browser.mjs`, Chromium headless, disposable stack) | **72 / 72 checks**; first run 61 passed / 10 failed (see `browser/`); axe-core WCAG 2.1 A+AA: 21 scans, 12 with no violations, 9 only the orange button (2.61:1) |
| Stress suite (`probes/stress_suite.py`) | **34 / 34**: map under load, races, 480 concurrent ticks, hostile bodies, throttling, start-up matrix, real process with no client |
| Differential check of the earlier refactors | unchanged (first audit); golden route fingerprints now in the test suite |
| Remote GitHub Actions | **not observed**: nothing pushed, `gh run list` empty |

**Before → after, same harness:** 12 simultaneous identical clock-ins stored 5 → **1**; last-place crew race overfilled 24/25 → **0/25**;
far-site first map request 13.5 s → **20 ms** ((0,0): > 60 s → 6 ms); fuzz server errors 20 → **0**; login known/unknown time ratio 0.00 → **0.98**;
real server with no client: no escalation → **EMERGENCY at +30 s**.

**Latency (real HTTP, threaded dev server, file SQLite, n = 60, median / p95 ms; two quiet-machine runs, before vs after code):**
dashboard 15.3 / 32.2 → 13.2 / 32.0; jobs 15.2 / 20.2 → 11.3 / 31.8; time-entries 16.6 / 31.4 → 11.5 / 31.7; map/live 8.3 / 13.7 → 9.1 / 30.1;
sites 6.8 / 8.9 → 5.8 / 8.4; users 4.5 / 6.5 → 4.1 / 20.5. No regression beyond run-to-run noise (p95 is noisy at n = 60). NFR-03 (< 500 ms) met.

**Known limitations of this evidence:** warnings are unclosed in-memory connections in tests (not triaged); the browser run is automated Chromium
only (no Firefox/Safari, no real device, no screen reader); concurrency was proven on SQLite with the Werkzeug threaded server only;
timing equivalence of logins is statistical, not exact; remote CI unobserved.

---

# SESSION 3 results (2026-10-11, after the persistence / contrast / findings work)

All earlier sections are historical. Environment: Windows 11 (12 logical CPUs) Python 3.13.9, Node 22.22.2 and 24.17.0; **plus Linux containers
(Docker Desktop, WSL2 kernel 6.18)**: `python:3.10-slim` (3.10.22), `python:3.12-slim` (3.12.15), `python:3.13-slim` (3.13.16), `node:22-slim` (22.23.3), `node:24-slim` (24.21.0).
`DATABASE_URL` cleared per process; every database used was a temporary file or `:memory:`.

| Check | Result |
|-------|--------|
| Backend, Windows 3.13: `pytest --cov --cov-branch --cov-fail-under=85` | **676 passed, 0 failed, 0 warnings** (was 637 passed / 35 warnings); line+branch coverage **96.68 %** (2,708 stmts, 68 missed; 694 branches, 35 partial). `evidence/backend_pytest_SESSION3.txt` |
| Backend, Linux, the CI command `pytest --cov --cov-fail-under=85` | Python **3.10 / 3.12 / 3.13: 676 passed each**, line coverage **97.49 %** each; `black --check` clean; `pip check` clean; `compileall` ok. `evidence/M_linux_python*_backend_FINAL.txt` |
| `black --check .` (Windows) / `pip check` | clean (54 files) / no broken requirements |
| radon (grade C or worse) | `parse_int` 14, `_best_departures` 13, `nearest_node` 15, `SafetyMachine.observe` 18, **`SafetyService._persist` 16 (new)**, `_alerts` 12, `_nearest_coworker` 12, `SafetyStore.save` 11 (new); average **A (3.34)** |
| Frontend, Windows Node **22.22.2** and **24.17.0**: `prettier --check`, `vitest run`, `vite build` | all pass; **78 tests in 8 files** (was 70 / 7); `evidence/frontend_ci_equivalent_SESSION3_…` |
| Frontend, Linux Node **22.23.3** and **24.21.0**: `npm ci`, prettier, `npm test`, `npm run build` | all pass, **78 tests**; `evidence/M_linux_node22_frontend.txt`, `…node24…` (run before the final edits, none of which touched `frontend/`) |
| Build sizes (raw / gzip) | initial JS 322.34 kB / 98.87 kB, LiveMap chunk 173.42 kB / 51.28 kB (Linux) — unchanged |
| Stress suite `probes/stress_suite.py` | **34 / 34** (re-run after all changes; `evidence/K_SESSION3_stress_suite.txt`) |
| Real-process restart test `probes/restart_e2e.py` (new) | **14 / 14**: emergency saved by the heartbeat with no client, still in the file after a hard kill, shown again after restart, no duplicate event, Dispatcher 403 / no token 401, Supervisor resolves, resolution saved, second kill+restart keeps it, no re-escalation, return-to-duty removes the row. `evidence/L_restart_persistence_real_process.txt` |
| Browser audit `probes/browser/audit_browser.mjs` | **76 / 76 in each of Chromium 156, Firefox 157, WebKit 27.2** (Playwright builds on Windows; WebKit is *not* Safari). axe-core WCAG 2.1 A + AA: **21 / 21 scans clean in all three** (was 12/21 clean, only the orange button left). `browser/*_SESSION3.json` |
| Measured primary-button contrast (computed colours in the browser) | rest **6.11:1** (`rgb(20,33,61)` on `rgb(255,122,0)`), hover **4.96:1** (on `rgb(229,109,0)`), keyboard focus **6.11:1**; old white-on-orange: 2.61:1. Disabled buttons are exempt (WCAG 1.4.3) and use 55 % opacity. Dark theme: the orange and the label colour are unchanged, so the same ratios apply (dark-theme axe scans clean) |
| Remote GitHub Actions | **not observed** — nothing pushed; `gh run list` is empty |

## Why the counts changed
Backend +39: `test_safety_persistence.py` 22, `test_audit_followups.py` 16, one limiter test (D-13). Frontend +8: `contrast.test.js` 5, `liveMap.test.jsx` +3
(persistence warning ×2, no stacked polls). Browser +4 checks (3 contrast, 1 table keyboard access). Coverage fell from 97.83 % to 96.68 % (line+branch vs
line-only is not a like-for-like comparison: the CI-command line figure is 97.49 % on Linux) because the new store / lease / failure paths and `wsgi.py` have
some untested lines (`wsgi.py` 0 %; `store.py` 91 %; `seed.py` main-path lines are exercised in subprocesses, which coverage does not see).

## What changed because of cross-platform runs (real findings, now fixed)
1. The "supported routes unchanged" test compared `repr` hashes of floats; they differ in the last bit between Windows and Linux and between Python versions → 4–6 route tests failed on Linux. Now compared as a structural summary taken from the original code.
2. Python 3.10 cannot parse `…Z` or one-digit fractional seconds → a time with `Z` gave a different (generic) 400 message. `Z` is now normalised so every version says "must not include a time zone".
3. The 'nested too deeply' wording is Python-version dependent (3.12+ on Linux parses a 5,000-deep list and rejects it as "not a JSON object"). Same 400 either way; the test accepts both.

## Limits of this evidence
Concurrency and restart tests ran on SQLite with the Werkzeug threaded server only; PostgreSQL is not supported (no driver, `begin_write()` is a deliberate no-op) and
was **not** tested although a `postgres:15` image exists locally. macOS, Windows+Python 3.10/3.12, real phones, Safari, screen readers and real users were not tested.
Performance was not re-measured beyond the stress suite (no regression seen; small data, one laptop). Linux Docker runs share the WSL2 kernel, not a clean cloud runner.
