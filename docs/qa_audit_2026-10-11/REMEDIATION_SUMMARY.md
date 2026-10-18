# FieldTrack — Remediation Summary (second session, 2026-10-11)

Short, factual record of what was changed after the independent audit. Details and evidence are in the other
reports in this folder; every number here comes from a command that was run in this session.

**Branch:** `prithugammer` (holds the earlier fixes; `main` untouched) · **Base commit:** `1fd784e` ·
**State:** all changes uncommitted · **No commit, push or branch switch was performed.**

## What was fixed

| Priority | Defect | Root cause | Fix | Verified by |
|----------|--------|-----------|-----|-------------|
| 1 | Live Map froze for a site outside the Valley (13.5 s → never) and took the safety controls with it | `roads.nearest_node` searched outward with no limit | Bounded, deterministic search: O(1) bounding-box rejection (+5 km), at most ~12 rings, `None` instead of a route; sites get `routable`, their workers "Route unavailable"; UI warning | 39 new map tests incl. golden-route fingerprints from the original code; stress suite (556 map requests under load, other endpoints ≤ 133 ms); real browser (warning in 1.5 s) |
| 2 | Safety escalation only advanced while a browser polled; a 47 s gap cleared a check-in and no emergency was raised | Escalation was driven by the dashboard's HTTP requests | Backend heartbeat thread (`safety/ticker.py`, started by `python app.py` / `wsgi.py`); Live Map now only reads; UI warns if monitoring is off/stale; all transitions idempotent under one lock | 16 deterministic ticker tests; 480 concurrent ticks ≡ sequential; **real process with zero clients raised an EMERGENCY at +30 s** |
| 3 | CI frontend job could not load its tests (Node 20 vs jsdom 30) and never ran | `jsdom 30` needs Node ≥ 22.22 / 24.15; workflow triggered only on `main` + PRs | CI matrix Node 22 + 24, push on all branches, `engines` field, README corrected | 70 frontend tests + format + build executed on Node 22.22.2 and 24.17 (**remote run not observed**) |
| 4 | 5 duplicate clock-ins out of 12 simultaneous; crews overfilled in 24 of 25 races | Check-then-insert with no atomicity | SQLite write lock (`BEGIN IMMEDIATE`) around the check-and-write sections (`concurrency.py`), partial unique index for one open entry per worker, 503 + `Retry-After` when the DB is busy | 21 concurrency tests on a real threaded server + file DB; stress suite; audit harness re-run: **1 stored, 0/25 overfilled** |
| 5 | HTTP 500 on deep JSON, lone surrogates, `date=9999-12-31` (and no body-size limit) | `RecursionError` / `UnicodeEncodeError` / `OverflowError` not handled | `get_json` catches recursion (400); `require_str` rejects non-UTF-8-encodable text (400); overflow-safe date windows; 1 MiB body limit checked up front (413) | 108 tests; 3,069-request fuzz → **0** server errors (was 20) |
| 6 | Login time revealed which emails exist (213 ms vs 0.9 ms) | bcrypt skipped for unknown users | One bcrypt verification for every failed check, against a cached dummy hash of the same cost | 9 tests; measured at cost 12: ratio 0.00 → **0.98** |
| — | Dialog focus escaped; focus not restored (found in the real browser) | no focus management | Focus trap + return of focus | 6 component tests; browser check |
| — | Horizontal page scroll on phones; tables unreachable by keyboard; low text contrast (found in the real browser) | top bar never wrapped; scroll area not focusable; three colour pairs below 4.5:1 | CSS wrap rules; focusable named table regions; three imperceptible colour adjustments | browser audit 72/72; axe violations 19 scans → 9 (only the orange button remains) |

## What was not done (and why)
- **No commit / push** (not authorised) — so GitHub Actions has never run on these changes.
- **Safety state is still lost on a restart.** Persisting it needs new tables and a restore path; there is no requirement
  or data-model support for it and the subsystem is a simulation. Restart behaviour is tested and documented instead.
- **White-on-orange primary button (2.61:1)** is the brand colour; changing it is a design decision. Options: navy text
  on the orange (6.1:1), or a darker orange such as `#b45309` (white text 5.0:1).
- Low/Medium items D-10, D-11, D-13, D-14, D-15, D-16, D-17, D-20, D-21, D-22, D-23 (see `DEEP_AUDIT_FINDINGS.md` §7).

## New or changed files
Backend: `roads.py`, `simulation.py`, `safety/ticker.py` (new), `safety/service.py`, `safety/__init__.py`, `concurrency.py` (new),
`models.py`, `app.py`, `auth.py`, `config.py`, `validation.py`, `routes/{assignments,map,reports,time_entries}.py`, `wsgi.py` (new).
Tests (new): `test_map_robustness.py`, `test_safety_ticker.py`, `test_concurrency.py`, `test_input_hardening.py`, `test_login_timing.py`;
`test_auth_hardening.py` made order-independent. Frontend: `LiveMap.jsx`, `Modal.jsx`, `DataTable.jsx`, `global.css`, `live-map.css`,
`tokens.css`, `package.json` (`engines`); tests (new): `liveMap`, `pages`, `modal`, `dataTable`. CI: `.github/workflows/ci.yml`.
Docs: `README.md`, `DEMO.md`, `docs/api-spec.md`, `docs/data-dictionary.md`, `docs/live-map-design.md`, `backend/.env.example`, this folder.

## Behaviour changes a user can notice
- Live Map polls `GET /api/map/live` (not `POST /api/safety/tick`); extra fields: `job_sites[].routable`, `safety.monitoring`,
  worker status `"Route unavailable"`.
- New responses: **413** (body too large), **503** + `Retry-After: 1` (database busy).
- `?route=` and other malformed inputs that used to 500 now return 400; extreme dates are valid.
- Starting the backend with `python app.py` also starts the safety heartbeat (`SAFETY_TICKER_ENABLED`, default on).
- Existing databases get the one-open-entry index on the next start (idempotent; a warning is logged if the data already
  violates the rule).
- Node 22.22.2+ / 24.15+ is now required for the frontend tests (README, `engines`).

---

# SESSION 3 — safety persistence, contrast, remaining findings, cross-platform (2026-10-11, later)

Earlier sections of this file describe the *second* session and are historical. Everything below was done and run afterwards.
**Branch:** `prithugammer` · **HEAD still `1fd784e`** · all work uncommitted · no commit, push, merge or branch switch.

## What was already done before this session
Live Map hang (D-02), browser-independent escalation (D-12), CI Node mismatch (D-01, local), clock-in / crew races (D-03/D-04),
input 500s (D-05/06/07/09), login timing (D-08), dialog focus (D-19), phone overflow / keyboard tables / most contrast (N-01…N-03).

## What changed in this session
| Item | Change | Files | Verified by |
|------|--------|-------|-------------|
| **Safety persistence (highest priority)** | Open check-ins, EMERGENCY, post-incident holds, stopped/break flags, the audit log and message feed are saved to four new tables after every change and restored at start-up. Operator actions are all-or-nothing (a failed save is undone and answered with 503); heartbeat save failures are retried every second and shown on the Live Map; start-up refuses an unreadable database; a database lease lets only one process run the heartbeat and lets another take over (it reloads the saved state). | `backend/safety/store.py` (new), `safety/service.py`, `safety/machine.py`, `safety/audit.py`, `safety/notifier.py`, `safety/ticker.py`, `app.py`, `config.py`, `routes/map.py`; `frontend/src/pages/LiveMap.jsx` | 22 new tests; **real-process kill -9 test, 14/14** (`probes/restart_e2e.py`, `evidence/L_…`) |
| Primary-button contrast (N-04) | Label colour on the orange changed from white (2.61:1) to the brand navy: **6.11:1 rest, 4.96:1 hover, 6.11:1 focus** (measured in a browser, 3 engines). New token `--color-on-orange`. | `frontend/src/styles/tokens.css`, `global.css` | `contrast.test.js` (5), browser audit, axe: 21/21 scans clean in 3 engines |
| D-14 sessions after a password reset | Tokens carry a fingerprint of the password hash (`pwv`); a changed password ends old sessions at once (401). No schema change. | `models.py`, `auth.py` | 6 tests |
| D-13 lock-out of the real owner | Failures are counted per (account, address); the account-wide ceiling is separate and higher (25). A stranger's guesses block only their own address. | `security.py`, `config.py`, `app.py` | 2 tests updated/added; stress suite |
| D-11 time zones | `Z` / `+05:45` in a clock time is now a **400** (it was silently dropped); documented format unchanged. | `validation.py` | tests |
| D-10 seed CLI | A reset against a foreign / production database is refused **before** any connection; unreachable DB gives one clean line without the URL. | `seed.py` | 7 subprocess tests |
| D-16 test warnings | Test harness closes its SQLite connections; **0 warnings** (was 35). | `tests/conftest.py` | full run |
| D-20 / D-18 (part) | Live Map polls one request at a time; phone placeholder is no longer a Toronto number. | `LiveMap.jsx`, `Crew.jsx` | test fails without the guard, passes with it |
| Cross-platform findings | Route "golden" test used exact float hashes that differ between OS / Python versions → now a stable structural summary; Python 3.10 cannot parse a trailing `Z`; the nesting message differs on Python 3.12+. All made version-independent. CI now runs Python 3.10 / 3.12 / 3.13. | `tests/`, `validation.py`, `.github/workflows/ci.yml` | Linux containers |
| Documentation | Safety module added to requirements (FR-14…24, NFR-08…11, roles, failure states), use case UC14, data dictionary, API spec, README, DEMO, `.env.example`. | `docs/*`, `README.md`, `DEMO.md` | – |

## Behaviour changes a user can notice
- An open emergency is **still shown after a restart**; no second alert or call is made.
- Operator action while the database is down: **503, nothing changed** (previously there was nothing to fail).
- Resetting a user's password signs that user out everywhere (they must log in again).
- A clock time with a zone (`Z`, `+05:45`) is refused with a clear message.
- Login: five wrong passwords from one address block that address for that account; another address is not blocked until 25 failures.
- Primary buttons have dark text on the orange.
- New env vars: `SAFETY_PERSISTENCE`, `LOGIN_MAX_FAILURES_PER_ACCOUNT_TOTAL`.

## Not done / still open
See `CURRENT_CODEBASE_STATUS.md` (Session 3 block). Main items: remote CI unobserved; PostgreSQL unsupported and untested; no real-user,
screen-reader, real-phone or Safari testing; D-15 accepted; D-17 needs one git command from you; audit-retention policy undecided.
