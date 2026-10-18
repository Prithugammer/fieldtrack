# FieldTrack — Current Codebase Status

> ## SESSION 3 STATUS (latest, 2026-10-11) — blocks below it are historical
> **Branch `prithugammer`, HEAD `1fd784e`; all work uncommitted; no commit/push/merge/branch change.** Run `git status` for the exact list.
>
> **Verdict: PARTIALLY COMPLETE — all in-scope code defects fixed and locally verified; remote CI, PostgreSQL, real users and a few findings remain.**
>
> | Area | Status | Evidence |
> |------|--------|----------|
> | Active emergency survives a restart (D-12 limitation) | **FIXED — VERIFIED** (SQLite) | 22 tests + real-process kill -9 test 14/14 |
> | No duplicate incident from repeated ticks / concurrent threads / restarts / two processes | **VERIFIED** | 6-thread × 40-tick test, 4 restarts, lease tests, real process |
> | A save failure never marks an emergency resolved / loses it | **VERIFIED** (tests; not by pulling a real disk) | operator actions → 503 + undo; heartbeat retries; Live Map warning |
> | Primary-button contrast (N-04) | **FIXED — MEASURED** | 6.11 / 4.96 / 6.11 : 1; axe 21/21 clean in 3 engines |
> | D-10, D-11, D-14, D-16, D-20 | **FIXED — VERIFIED** | see DEEP_AUDIT_FINDINGS §8 |
> | D-13 | **MITIGATED** (design change) | owner no longer locked out by a stranger; temporary lock-out by many addresses remains possible |
> | D-15 passwords trimmed / not normalised | **ACCEPTED RISK** | changing it would lock out users whose password has edge spaces |
> | D-17 tracked `backend/.coverage` | **OPEN — owner action** | `git rm --cached backend/.coverage` (I did not touch the git index) |
> | D-18 | **PARTIAL** | placeholder fixed; `requirements*.txt` still unpinned |
> | D-21 safety module absent from analysis docs | **DOCUMENTED, NOT APPROVED** | requirements §7, UC14, data dictionary — decisions D-21 / NFR-11 still need an owner |
> | N-05 touch targets < 24 px | **OPEN — Low** | unchanged |
> | Backend tests | **676 passed** on Windows 3.13 and Linux 3.10 / 3.12 / 3.13 | line coverage 97.49 % (CI cmd, Linux) · 96.68 % line+branch (Windows) |
> | Frontend | **78 tests passed** on Node 22 and 24, Windows and Linux; build + Prettier pass | |
> | Stress suite / browser audit | **34/34**; **76/76 in Chromium, Firefox, WebKit** | |
> | Remote GitHub Actions | **NOT OBSERVED** (nothing pushed) | the workflow now covers Python 3.10/3.12/3.13 and Node 22/24 |
> | Manual (human) testing | **NOT DONE** — see `MANUAL_TEST_PLAN.md` §24 | automation covered several REM cases; their result columns stay blank |
> | PostgreSQL / macOS / real phone / Safari / screen reader / real users | **NOT TESTED** | not supported or not available |
>
> **Biggest remaining risks:** (1) single-process only — a second process serves stale alerts and has its own login limiter; (2) nothing escalates while the
> server is down (no external watchdog), and a crash costs up to ~3 s of lease handover; (3) idle time accumulated before check-in 1 is not saved;
> (4) audit retention policy undecided and the table grows without limit; (5) all worker input is simulated and all notifications are mocks —
> **this is not a real man-down system**; (6) GitHub Actions not yet seen passing.

---


> ## UPDATE 2 — after the remediation session (2026-10-11)
> Everything under **"Original audit status"** further down is the first audit, preserved unchanged. This
> block records what was changed afterwards and what was actually verified. Evidence: `evidence/` (files marked
> `AFTER`/`FINAL`/`J_`/`K_`), `browser/`, `probes/`, and `REMEDIATION_SUMMARY.md`.

### Repository state
- **Branch:** `prithugammer` — the branch that holds the earlier fixes (commit `1fd784e` "new fixes", already on
  `origin/prithugammer`). `main` and `backup/original-main` still hold older code and were **not** touched or merged.
- **This session's work is uncommitted:** 23 tracked files modified, 13 new source/test files, plus this audit folder.
  No commit, no push, no branch switch, no history rewrite. `git status` shows no generated files, databases or secrets;
  `package-lock.json` is unchanged.

### Overall verdict — **PARTIALLY FIXED** (all targeted code defects fixed and locally verified; some items remain)
Fixed and verified here: the Live Map hang, browser-dependent safety escalation, the CI Node mismatch (locally), the
clock-in and crew-capacity races, the input-related HTTP 500s, the login-timing leak, the dialog focus trap, and the
responsive / keyboard / contrast problems found by the first real-browser run. **Not** done or not provable: remote
GitHub Actions (nothing pushed, 0 runs), persistence of safety state across a restart, the brand-orange button contrast
(needs your design decision), and the Low/Medium items listed below.

### Defects from the first audit — current status
| ID | Defect | Status now | Evidence |
|----|--------|-----------|----------|
| D-02 | Far-away site froze Live Map + safety controls | **FIXED — VERIFIED** | Pokhara first request 20 ms (was 13.5 s), (0,0) 6 ms (was > 60 s); 556 map requests served while unrelated + safety endpoints answered ≤ 133 ms (`K_AFTER_stress_suite.txt`); real browser: warning shown in 1.5 s |
| D-12 | Safety escalation needed a polling browser | **FIXED — VERIFIED** (restart limitation remains) | Real server, no client: EMERGENCY at +30 s (`J_AFTER_escalation_with_no_browser.txt`); 480 concurrent ticks ≡ sequential |
| D-01 | CI frontend job failed on Node 20 | **FIXED locally — remote UNVERIFIED** | 70/70 tests, format, build pass on Node 22.22.2 **and** 24.17; GitHub run not observed |
| D-03 | Duplicate clock-ins under concurrency | **FIXED — VERIFIED** | 12 simultaneous: 5 stored → **1**; 20 more trials in the stress suite |
| D-04 | Crew over capacity under concurrency | **FIXED — VERIFIED** | 24/25 overfilled → **0/25**; capacity 3/8 → 3 stored, 4/10 → 4 stored |
| D-05 | Deeply nested JSON → 500 | **FIXED — VERIFIED** | 3,000 and 60,000 deep → 400 on all 13 body endpoints; 25× against the live server |
| D-06 | Lone surrogates → 500 | **FIXED — VERIFIED** | 400 on every text field incl. unauthenticated login |
| D-07 | `date=9999-12-31` → 500 | **FIXED — VERIFIED** | 14 extreme-date URLs → 200; first/last calendar day work end to end |
| D-08 | Login timing revealed account existence | **MITIGATED — measured** | cost 12: unknown/known median ratio 0.00 → **0.98** (202 ms vs 206 ms); not perfectly equal |
| D-09 | No request-size limit | **FIXED — VERIFIED** | > 1 MiB → 413 before parsing; same limit recommended at the reverse proxy |
| D-19 | Dialog had no focus trap | **FIXED — VERIFIED (real browser)** | Tab cycles inside; Escape restores focus to the opener |
| D-10, D-11, D-13, D-14, D-15, D-16, D-17, D-20, D-21, D-22, D-23 | see `DEEP_AUDIT_FINDINGS.md` §7 | **OPEN / unchanged** | not in scope of this session |
| D-18 | Documentation inconsistencies | **PARTIALLY FIXED** | Node range, test counts, new env vars, deployment notes corrected; unpinned requirements and Toronto phone placeholder remain |

### New findings from the real-browser run (first run: 61 passed / 10 failed)
| ID | Finding | Status |
|----|---------|--------|
| N-01 | Horizontal page scroll on phone width on Dashboard, Live Map, Crew, Time Entries, Reports (and tablet Live Map): the top bar never wrapped | **FIXED — VERIFIED** (0 overflow at 1366/820/390 px) |
| N-02 | Scrollable tables were not reachable by keyboard (axe `scrollable-region-focusable`, 5 scans) | **FIXED — VERIFIED** |
| N-03 | Colour contrast: muted text 4.43:1, sidebar text 4.31:1, Approve/Success button 3.47:1 (axe: 178 elements) | **FIXED — VERIFIED** (axe violations 19 scans → 9) |
| N-04 | **White text on the brand-orange primary button is 2.61:1** (needs 4.5:1) | **OPEN — design decision**: options in `DEEP_AUDIT_FINDINGS.md` §7 |
| N-05 | 5 (dashboard) and 18 (Live Map) interactive targets are smaller than 24×24 px (WCAG 2.2 AA 2.5.8; not part of 2.1 AA) | **OPEN — Low**, not changed |

### Previously "fixed" items re-verified (the brief's list)
| Item | Status | How |
|------|--------|-----|
| Integer overflow / numeric ids (`1e999`, oversized ids) | **VERIFIED** | 166 + parametrised tests; audit probe A; 3,069-request fuzz → 0 server errors |
| Server-side safety role authorization | **VERIFIED** | 25 authz tests; **real browser**: Supervisor sees Trigger accident/SOS/break, Dispatcher sees none; API 403 |
| `GET /api/map/live` read-only | **VERIFIED** | 50 polls change nothing; accident roll only on tick/heartbeat; browser Network log shows only GET |
| Safety tick and escalation transitions | **VERIFIED** | deterministic clock tests (thresholds derived from config: `idle + checkins × window`); real process |
| Passwords > 72 bytes | **VERIFIED** (automated) | no change to behaviour; boundary tests incl. multi-byte; not exercised through the UI by a human |
| Token behaviour after demotion | **VERIFIED** (automated) | demotion/deactivation/promotion tests |
| Strict date parsing (`20261001`) | **VERIFIED** | tests + probe |
| Production `SECRET_KEY` requirements | **VERIFIED** | tests + subprocess start-up matrix in the stress suite |
| Login throttling, security headers | **VERIFIED** | tests; headers also on the new 413 / 503 responses |
| Safe seed / reset | **VERIFIED** (unchanged code) | 16 tests + CLI probe from the first audit; CLI ordering gap D-10 remains |
| Frontend lazy loading, role-dependent controls | **VERIFIED in a real browser** (Chromium) | chunk requested only on navigation; role UI checks on Jobs / Time Entries / Live Map popups |
| Refactored `_build_route`, `update_user`, dashboard | **VERIFIED** | differential run vs baseline; golden route fingerprints now committed as tests |
| API error status codes + frontend handling | **VERIFIED** | 70 frontend tests + browser error-state checks (network abort, 500) |

### Browser and accessibility — what was and was not tested
**Tested (Chromium via Playwright, headless, against a disposable stack):** 7 pages × 3 viewports (1366×768, 820×1180,
390×844) for horizontal overflow and console errors; axe-core WCAG 2.0/2.1 A + AA on 21 page/viewport/theme combinations
(light and dark); keyboard order and focus indicator on sign-in; dialog focus trap and focus return; Live Map network
behaviour; role-dependent controls in worker popups; SOS → alert → resolve end to end; far-away-site scenario; error and
recovery states; invalid-token redirect. **72/72 checks pass** after the fixes (first run: 61/71).
**Not tested:** Firefox, Safari, a real phone (viewport emulation only), a screen reader, high-contrast mode, zoom 200 %
by eye, real users. Automated axe finds only a fraction of accessibility problems; this is **not** a compliance claim.

### Automated results (final, this session)
Backend `pytest` **637 passed** · line coverage **97.83 %** (CI command) · `black` clean · average complexity A (3.25).
Frontend **70 tests passed** on Node 22.22.2 and 24.17 · Prettier clean · build OK. Stress suite **34/34**.
Remote GitHub Actions: **not observed** (nothing pushed; `gh run list` is empty). Details: `AUTOMATED_TEST_RESULTS.md`.

---

## Original audit status — before remediation (preserved)


**Date:** 2026-10-11 · **Audited:** branch `prithugammer` @ `1fd784e` ("new fixes"), pushed to `origin/prithugammer`,
working tree clean · **Baseline for comparison:** `67d9214` · **Application source modified by the audit:** none.

> **Premise check.** The brief assumed branch `main` with ~30 modified, uncommitted files. In reality the
> previous session's work is **already committed (one commit, 44 files, +4,780/−282) and pushed** to the branch
> `prithugammer`; `main` and `backup/original-main` still hold the old code. Nothing is staged or untracked.

## Verdict

**Ready for manual QA** — with two caveats you should know before you start:
1. The UI has still **never been executed in a browser by anyone but you** (the extension was unavailable
   again), so every UI claim below is "by code + unit test" only.
2. **CI has never run**, and as configured its frontend job **would fail** (Node 20 vs `jsdom 30`).

The previous session's headline fixes are real. This audit found **no regression** caused by them and
**no claimed fix that is absent**. It did find **one High defect that predates and was never reported** (a job site
outside the Kathmandu Valley freezes the Live Map and the safety controls) and several Medium issues
(concurrency races, login-timing enumeration, unhandled-input 500s).

## 1. Previously reported fixes — verified status

| Area | Status |
|------|--------|
| Integer overflow: `1e999`, huge path ids, NaN/±inf, 64-bit limits, zero/negative ids, path/query/body consistency | **VERIFIED FIXED** |
| `parse_date` strictness (`20261001` rejected, `YYYY-MM-DD` accepted) | **VERIFIED FIXED** |
| Safety controls restricted to Supervisor/Admin (backend; 401/403, no state change) | **VERIFIED FIXED** |
| Safety controls hidden in the UI for other roles | **UNVERIFIED** (code + 3 unit tests; no browser) |
| `GET /api/map/live` read-only | **VERIFIED FIXED** |
| `POST /api/safety/tick` | **PARTIALLY FIXED** — correct, authenticated, concurrency-safe; but escalation only runs while a client polls (D-12) |
| Login throttling, 429 + `Retry-After` | **VERIFIED FIXED** (caveats: temporary victim lock-out D-13; per-process memory) |
| Production `SECRET_KEY` enforcement; debug refused in production | **VERIFIED FIXED** |
| Security headers; HSTS only on HTTPS when enabled | **VERIFIED FIXED** (API only; no SPA CSP) |
| Password > 72 bytes: no 500, no silent truncation | **VERIFIED FIXED** |
| Role from DB, not token (demotion/deactivation immediate) | **VERIFIED FIXED** (password reset does not end sessions — D-14) |
| Seeding: ordinary seed non-destructive; reset needs `--reset --yes`; refused in production | **VERIFIED FIXED** |
| Seeding: refused for non-SQLite URLs | **PARTIALLY FIXED** — unit-tested, but the CLI crashes with `ModuleNotFoundError` before reaching the guard (D-10) |
| Complexity: `_build_route`, `update_user`, `dashboard` refactored; behaviour preserved | **VERIFIED FIXED** (125 identical requests, 200 identical routes vs baseline) |
| `machine.observe` still CC 18 | **CONFIRMED** as stated |
| 444 backend tests, 98 % coverage | **VERIFIED** (98.24 % line; 97 % with branches; excludes `tests/`, `tools/`) |
| 17 frontend tests | **VERIFIED on Node 24; FAIL on Node 20** (D-01) |
| GitHub Actions workflow | **PARTIALLY FIXED / not observed** — 0 runs ever; frontend job fails as configured |
| Bundle 493 → 322 kB | **VERIFIED** (raw vs raw; gzip 149.86 → 98.63 kB; total JS unchanged, Live Map is a 172 kB lazy chunk) |
| Documentation updated | **PARTIALLY FIXED** (inconsistencies D-18) |
| Worker self clock-in | **NOT APPLICABLE** — requirements deliberately exclude worker login |

Counts: **20 verified · 5 partially fixed / mixed · 1 unverified · 0 not fixed · 0 regressions.**

## 2. Open defects by priority (full register in `DEEP_AUDIT_FINDINGS.md`)

| ID | Sev | Title | Pre-existing? |
|----|-----|-------|---------------|
| D-01 | **High** | CI frontend job fails on Node 20 (jsdom 30); workflow never executed | introduced by the session's CI/test setup |
| D-02 | **High** | Job site outside the Valley (e.g. Pokhara: 13.5 s; (0,0): > 60 s) freezes Live Map **and** safety controls — `roads.nearest_node` unbounded | yes (same 13.6 s on `67d9214`) |
| D-12 | High (real deployment) | Safety escalation needs a polling client; a 47 s gap cleared a check-in, no emergency raised | yes (documented limitation) |
| D-03 | Medium | 12 concurrent identical clock-ins stored 5 duplicates | yes |
| D-04 | Medium | Crew overfilled in 24/25 racing trials | yes |
| D-08 | Medium | Login timing reveals which emails exist (213 ms vs 0.9 ms) | yes |
| D-21 | Medium (for the report) | Safety subsystem has no requirement/use case/DFD/ERD/role matrix | n/a |
| D-05/06/07/09 | Low–Med | 500 on 3,000-deep JSON, lone surrogates, `date=9999-12-31`; no body-size limit | yes |
| D-10/11/13/14/15–20, 22, 23 | Low–Info | see register | mostly yes |

## 3. Automated results (reproduced)

| Check | Result |
|-------|--------|
| `pytest` (backend) | **444 passed**, 0 failed/skipped, 22 `ResourceWarning`s |
| Coverage (CI command) | **98.24 %** line · **97 %** line+branch · gate 85 % met |
| `black --check .` | clean |
| `vitest run` Node 24 / Node 20 | **17 passed** / **0 run, 3 files error** |
| `prettier --check`, `vite build` | clean (Node 24 and 20) |
| 2,991-request fuzz | 20 × HTTP 500 (2 root causes); DB integrity OK |
| 480-request concurrent tick test | identical to sequential run, 0 duplicates |
| GitHub Actions | **not observed** (0 runs) |
| Linter / type-checker | none configured |

Details: `AUTOMATED_TEST_RESULTS.md`; raw logs: `evidence/`.

## 4. Was the frontend verified?

**No.** Static inspection (role gating matches the backend, error/loading states exist, lazy loading is real in
the build output) and 17 unit tests only. No rendering, mobile, keyboard or accessibility execution. Use
`MANUAL_TEST_PLAN.md` §13, §14, §18 first.

## 5. The first ten manual tests to run

1. **ENV-01** start the disposable backend and seed.
2. **AUTH-01** sign in with all four demo accounts.
3. **AUTH-03** empty sign-in form makes no network call.
4. **RBAC-02** Dispatcher has no record/approve controls (and API 403).
5. **JOB-02** assignment + double-booking 409.
6. **TE-02** 500 m clock-in is flagged but saved.
7. **TE-03** approve needs a reason; cannot be decided twice.
8. **MAP-01** Live Map polls `POST /api/safety/tick`, not `GET /api/map/live`.
9. **SAF-01 / SAF-02** SOS → EMERGENCY → resolve (Supervisor).
10. **SAF-04** Dispatcher sees the alert but has no controls (and API 403).

## 6. Exact commands

Backend (your normal stack, from the repo root — note the `DATABASE_URL` line):
```powershell
cd backend
Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue   # your shell holds a PostgreSQL URL from another project
.venv\Scripts\Activate.ps1
python seed.py          # fills an EMPTY database only; use "python seed.py --reset --yes" to reload demo data
python app.py           # http://127.0.0.1:5000
```
Frontend:
```powershell
cd frontend
npm run dev             # http://localhost:5173
```
For the manual plan use the **disposable** variant in `MANUAL_TEST_PLAN.md` §1 (ports 5055/5174, scratch DB).
**Restart any backend that was started before commit `1fd784e`** — the Live Map now calls `POST /api/safety/tick`.

## 7. Limits of this audit

- No browser/mobile/accessibility execution; GitHub Actions not observed; Python 3.12, Linux, macOS not run.
- Performance was measured on ~100 rows on one laptop (dev server): a baseline, not a guarantee.
- Race conditions were reproduced on SQLite with the threaded dev server; behaviour on another server/DB may differ.
- Browser timer throttling for hidden tabs (relevant to D-12) was **not** measured.
- I installed `radon` (measurement only) into `backend/.venv`; it is not in the requirements files.

## 8. Where everything is

`docs/qa_audit_2026-10-11/` — `CURRENT_CODEBASE_STATUS.md` (this file) · `DEEP_AUDIT_FINDINGS.md` ·
`MANUAL_TEST_PLAN.md` (168 cases in 18 modules, 23 starred) · `ISO_IEC_9126_ASSESSMENT.md` · `AUTOMATED_TEST_RESULTS.md` ·
`evidence/` (15 raw outputs) · `probes/` (scripts to reproduce them; replace `<SCRATCH_DIR>` first).
