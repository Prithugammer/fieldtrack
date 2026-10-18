# FieldTrack — ISO/IEC 9126 Quality Assessment (second, evidence-based evaluation)

**Subject:** FieldTrack @ commit `1fd784e` · **Date:** 2026-10-11 · **Assessor:** independent audit (no code changes made)

This is an *evaluation against the six ISO/IEC 9126-1 quality characteristics*, not a claim of compliance with
the standard. A completed checklist does not make a product "ISO 9126 compliant"; the ratings below describe how
much evidence supports each characteristic and what that evidence shows.

## 0. Method, evidence types and rubric

**Evidence types** (always stated per finding): **M** measured (a number from a tool or probe run in this
audit) · **A** automated test result · **I** code/document inspection · **U** manual UI testing (*none performed
— see MANUAL_TEST_PLAN.md*) · **X** assumption (stated, not verified).

**Rating rubric (applied per characteristic):**

| Rating | Meaning |
|--------|---------|
| **A** | Demonstrated by measurement **and** manual/user-level testing; no open High/Critical defect affecting it |
| **B** | Demonstrated mainly by automated tests, measurement or inspection; open defects are at most Medium; no key sub-characteristic undemonstrated |
| **C** | At least one open **High** defect, or a key sub-characteristic is only weakly demonstrated |
| **D** | Failing, or core behaviour not working |
| **NR** | Not rated — evidence insufficient to rate responsibly |

**Confidence:** *High* = reproduced by me, several independent signals; *Medium* = automated/inspection only or one signal;
*Low* = largely assumed.

Where the previous session reported a result, it is treated as a claim; only independently reproduced numbers are used.

## 1. Summary

| Characteristic | Rating | Confidence | One-line reason |
|----------------|:-----:|:----------:|-----------------|
| Functionality | **B** | Medium | FR-01…FR-13 each have passing automated tests and API probes; no UI execution; two High-ish edge failures (far-away site, concurrency) and the safety module has no requirements |
| Reliability | **C** | High | Reproduced: live-map hang for far sites (High), duplicate/overfilled records under concurrency, 500s on nesting/surrogates/extreme dates, safety monitoring dies without a polling client |
| Usability | **NR** | — | No browser/accessibility/user testing was possible; static inspection only |
| Efficiency | **B** | Medium | NFR-03 met with a ~30× margin on demo data (measured); not load-tested; D-02 is a pathological outlier |
| Maintainability | **B** | Medium-High | 444 tests, avg complexity A (3.2), black-clean, CI file present; 1 function CC 18, tests unpinned, CI not running |
| Portability | **C** | Medium | Verified only on Windows/Python 3.13/Node 24; CI config fails on Node 20; docs inconsistent |

---

## 2. Functionality

*(suitability, accuracy, interoperability, security, compliance)*

| Sub-characteristic | Evidence | Type |
|---|---|---|
| Suitability — FR-01…FR-13 | Each FR is exercised end-to-end through the API: sign-in (D1), roles (B1/RBAC), user/site/job/assignment CRUD (differential 125-request run, 444 tests), double-booking (`UNIQUE` + 409), time-entry rules and approvals, geofence flag at 199/201 m (tests), reports/CSV, dashboard, live map. 17 GET routes verified read-only | M, A |
| Accuracy | Geofence haversine boundaries and overnight hours (8.5 h) covered by tests; differential test shows the refactors changed no output; 200 simulated routes identical to baseline | M, A |
| Interoperability | JSON API with a uniform `{"error","field"}` error shape (verified on 400/401/403/404/405/429); CSV export. No third-party integration exists | M, I |
| Security | Strong: bcrypt, DB-authoritative roles, token attacks rejected, throttling, secret enforcement, headers, CORS (see Findings §4). Weak: login timing enumeration (D-08), temporary lock-out abuse (D-13), no session revocation on password reset (D-14) | M |
| Compliance | Standards/regulatory compliance not assessed. Internal compliance with the project's own documents: safety subsystem has **no** requirement, use case, DFD, ERD or class-diagram entry (D-21) | I |

**Known defects affecting Functionality:** D-02 (FR-13 fails for sites outside the Valley), D-03/D-04 (FR-06/FR-08 rules not atomic), D-11 (timezone semantics), D-21 (no requirement for safety).
**Unverified:** every browser-level behaviour (forms, banners, button visibility, map rendering).
**Measurement/test needed:** MANUAL_TEST_PLAN §5–§14, §17; fix D-02/03/04 and add regression tests.
**Rating B** because core rules hold under automated and probe testing, but the unmeasured UI layer and the open races keep it from A. Confidence **Medium**.

## 3. Reliability

*(maturity, fault tolerance, recoverability, compliance)*

| Sub-characteristic | Evidence | Type |
|---|---|---|
| Maturity | 444/444 tests pass; 2,991-request fuzz found **20 server errors** in two root causes (nesting D-05, surrogates D-06) plus date overflow (D-07); DB `integrity_check` and `foreign_key_check` clean after fuzz | M |
| Fault tolerance | Unhandled-exception handler returns a generic body and rolls back (verified, no leaks). But: a far-away site makes a request run for 13 s – unbounded (D-02, also disables safety controls); race conditions store 5/12 duplicate entries (D-03) and overfill crews in 24/25 trials (D-04); `UNIQUE` double-booking and single-decision races are safe | M |
| Recoverability | Dev signing key makes tokens survive restarts; DB persists (SQLite). Safety state, audit log and throttle counters are in memory and are lost on restart (README states this). Missing/unreachable DB → raw traceback (D-10) | M, I |
| Availability of the safety function | Escalation advances only while a client polls; after a 47 s gap a stationary worker's check-in was cleared and no emergency raised (D-12) | M |
| Compliance | n/a | — |

**Known defects:** D-02 (High), D-03, D-04 (Medium), D-05/06/07, D-10, D-12 (High for a real deployment, Info for the simulated scope).
**Unverified:** behaviour under sustained load; browser back-pressure (D-20); long-run memory.
**Tests/measurements:** fix D-02/D-03/D-04 and add concurrency + far-site regression tests; MANUAL_TEST_PLAN §14 (SAF-10/11/13), §20 (REC-*); soak test.
**Rating C** (open High defect on availability plus reproduced data-integrity races). Confidence **High** — each defect was reproduced, several on the pre-session code too (so this is not a regression).

## 4. Usability

*(understandability, learnability, operability, attractiveness)*

| Sub-characteristic | Evidence | Type |
|---|---|---|
| Understandability / learnability | `DEMO.md` provides a 9-step script and click-to-fill demo accounts; inline field errors by design (`FormField` `role="alert"`); loading/empty/error components exist and are unit-tested for dashboard/sign-in | I, A |
| Operability | Static findings only: dialogs close on Escape and focus the first control, but no focus trap or focus return (D-19); labels are bound with `htmlFor`; map markers get `aria-label`s; the Live Map shows "Lost connection … retrying" on failure | I |
| Attractiveness / responsive layout | README says the sidebar collapses below 800 px and light/dark themes exist — **not observed** | X |
| Accessibility | Not tested (no axe/Lighthouse/screen-reader run) | — |

**Verified:** only that the relevant code paths exist and 17 unit tests pass.
**Unverified:** everything a user sees — layout, mobile, keyboard flow, contrast, readability, task times.
**Tests needed:** MANUAL_TEST_PLAN §18 (UX-01…10) with axe/Lighthouse reports, plus 3–5 task-based sessions with real users (e.g. "assign Bishal and flag a 500 m clock-in") recording success rate and time.
**Rating NR** — assigning even a "B" from code reading would overstate the evidence. Confidence: n/a.

## 5. Efficiency

*(time behaviour, resource utilisation)*

| Sub-characteristic | Evidence | Type |
|---|---|---|
| Time behaviour | See table. NFR-03 (< 500 ms) met by a wide margin on the 12-user / 8-job demo data | M |
| Resource utilisation | Initial JS 321.64 kB raw / 98.63 kB gzip (was 493.48 / 149.86); Live Map chunk 172 kB loaded on demand. 1 Hz polling = 1 POST + 1 GET per open map; tick with 8 simultaneous clients: median 45 ms, 0 errors. **Server memory/CPU not measured** | M |
| Algorithmic risk | Route search `nearest_node` is unbounded (D-02); several list endpoints load related rows one by one (code inspection: `Job.to_dict` crew, `dashboard` `e.worker`) | I, M |

Measurements (median / p95, ms; 12-CPU Windows 11 laptop, Python 3.13, seeded demo data, 10 warm-ups discarded):

| Endpoint | in-memory DB, test client, n = 100 | real HTTP, file SQLite, n = 60 |
|---|---|---|
| dashboard | 7.0 / 8.1 | 13.4 / 16.2 |
| jobs | 6.7 / 7.5 | 13.2 / 14.8 |
| time-entries | 6.4 / 7.8 | 12.8 / 16.0 |
| map/live | 3.5 / 4.7 | 7.6 / 10.5 |
| sites | 2.9 / 3.9 | 7.0 / 17.8 |
| users | 1.4 / 2.0 | 4.5 / 5.3 |

**Limits:** ≈ 100 rows total; single machine; no network latency; Flask dev server; no sustained or concurrent-user load test; in-memory SQLite is not a production figure. **Needed:** load test (e.g. 50 users, 10 000 time entries), memory profile, Lighthouse performance run on the built SPA.
**Rating B** (met the stated requirement with margin, nothing contradicts it except the D-02 outlier). Confidence **Medium**.

## 6. Maintainability

*(analysability, changeability, stability, testability)*

| Sub-characteristic | Evidence | Type |
|---|---|---|
| Analysability | Backend split into blueprints with docstrings on routes (NFR-05); radon: 238 blocks, **average complexity A (3.21)**; maintainability index A for all application files. Grade-C functions: `SafetyMachine.observe` **18**, `parse_int` 14, `_best_departures` 13, `_alerts` 12, `_nearest_coworker` 12 | M |
| Changeability | Fixes landed as small, local changes; the three refactored functions (`_build_route`, `update_user`, `dashboard`) now sit below grade C and a **125-request / 200-route differential run against the pre-session commit showed identical behaviour** | M |
| Stability (risk of change) | Heavy test net: 444 tests, 98.24 % line / 97 % line+branch coverage; but the net missed 6 defect classes found here (nesting, surrogates, date overflow, races, far site, Node 20 CI) — coverage measures execution, not assertions or inputs | M |
| Testability | Time and randomness are injectable (`clock`, seed); state machine is I/O-free; test DB is in-memory and isolated; limiter clock injectable | I, A |
| Process | CI file exists and parses, but has **never run** and its frontend job fails on its own Node version (D-01); `requirements*.txt` unpinned; a generated `.coverage` file is tracked; 22 `ResourceWarning`s | M |

**Cyclomatic-complexity caveat:** CC counts decision paths in one function. It ignores coupling, naming, documentation and
test quality; a low average can hide a hard-to-follow module and a "C" can be a readable transition table (`observe` is
exactly that). Use it as a screening tool next to coverage and review, not as a score.
**Coverage caveat:** line coverage (98 %) is higher than branch coverage (97 %) and neither measures assertion strength.
**Rating B** — Confidence **Medium-High**.

## 7. Portability

*(adaptability, installability, co-existence, replaceability)*

| Sub-characteristic | Evidence | Type |
|---|---|---|
| Adaptability / environment | Configuration by environment variables (NFR-07) works (verified: `APP_ENV`, secrets, DB URL, CORS, limits). A stray `DATABASE_URL` from another project breaks start-up with an unfriendly error | M |
| Installability | Documented two-terminal setup reproduced on Windows 11 / Python 3.13 / Node 24. **Not run** on Linux, macOS, Python 3.10–3.12. README claims Node 20+, but the test tooling needs ≥ 22.22 or ≥ 24.15 (D-01, D-18); no `engines` field | M, I |
| Co-existence | Second instance on other ports worked alongside the user's own stack | M |
| Replaceability | SQLite only (no Postgres driver, no migrations); SQL via SQLAlchemy keeps a future move feasible but untested | I |

**Tests needed:** run the backend suite on Python 3.10/3.12 and Linux (a CI matrix would do this once D-01 is fixed), fresh-clone install on a second machine, Node 20/22/24 matrix.
**Rating C** — portability is documented but only one platform was demonstrated and the CI/doc claims contradict measured behaviour. Confidence **Medium**.

---

## 8. What this assessment does *not* establish

- Nothing was verified through a browser, on a phone, with assistive technology, or by real users.
- GitHub Actions has not been observed running.
- Production performance, security under a determined attacker, multi-process behaviour and long-term data
  growth were not tested.
- A "B" here means *adequately evidenced for a coursework system on its stated scope*; it does not certify
  suitability for a real construction company's safety-critical use (see D-12).

## 9. Suggested minimum actions to raise the ratings

1. Reliability C → B: fix D-02, D-03, D-04; add regression tests for nesting, surrogates, date extremes (D-05/06/07).
2. Portability C → B: fix D-01 (Node ≥ 22 or `jsdom@26`), add `engines`, watch one green CI run on all matrix cells, correct the README.
3. Usability NR → B/A: execute MANUAL_TEST_PLAN §18 and a small task-based user test; attach the axe/Lighthouse reports.
4. Functionality B → A: add the safety subsystem to the analysis documents (requirements, use cases, role matrix) and execute the full manual plan.

---

## 10. Reassessment after remediation (2026-10-11)

Sections 0-9 above are the first assessment, unchanged. This section re-rates each characteristic using evidence gathered after the
fixes. Evidence types as in §0 (**M** measured, **A** automated test, **I** inspection, **U** manual UI testing). New: **B** =
automated real-browser run (Chromium via Playwright, headless; not a human tester). This is an evaluation, **not** a claim of
ISO/IEC 9126 compliance or certification.

| Characteristic | Before | Now | Confidence | What changed / why not higher |
|---|:-:|:-:|:-:|---|
| Functionality | B | **B** | Medium | Safety escalation now works without a client (M: real process, EMERGENCY at +30 s; A: 16 tests); unsupported sites degrade gracefully (M, A, B). Not A: no human UI testing; safety subsystem still has no requirement/use case (D-21); state lost on restart |
| Reliability | C | **B-** (B with the caveats) | Medium-High | Open High defects D-02, D-12 fixed; races D-03/D-04 fixed (M: 1 stored, 0/25 overfilled); 0 server errors in a 3,069-request fuzz (was 20). Not higher: single process only; in-memory safety state; only SQLite locking verified; no soak test; no long-run memory data |
| Usability | NR | **C (provisional)** | Low-Medium | First real evidence (B): no overflow at 3 viewports, focus trap, keyboard sign-in, 72/72 checks, axe 12/21 scans clean. Open: white-on-orange 2.61:1 (N-04), small targets (N-05), no screen-reader, Firefox/Safari, real-device or user testing. Rating is provisional until a human runs MANUAL_TEST_PLAN §18/§23 |
| Efficiency | B | **B** | Medium | Unchanged: medians 1-14 ms (test client) / 4-14 ms (real HTTP) on ~100 rows; the 13 s outlier is gone (20 ms). Concurrent writers now queue on the SQLite write lock (12 identical clock-ins: median ≈130-145 ms). Heartbeat cost not separately measured; no load or soak test |
| Maintainability | B | **B** | Medium-High | 637 backend + 70 frontend tests, avg complexity A (3.25), black/prettier clean; new modules small and documented. Grade-C functions now 6 (adds `roads.nearest_node` 15). CI configured but never observed running; requirements unpinned |
| Portability | C | **C+ / B-** | Medium | CI matrix Node 22/24, `engines`, README corrected; verified locally on Windows with Node 22.22.2 and 24.17, Python 3.13. Not verified: Linux, macOS, Python 3.10-3.12, remote CI, any non-SQLite DB (not supported) |

Measured versus inferred: every number in the tables above is from `AUTOMATED_TEST_RESULTS.md` or the files in `evidence/` and `browser/`.
Judgements (ratings, "provisional") are inspection-based and depend on the rubric in §0. Missing evidence: human usability testing,
screen-reader testing, multi-browser, remote CI, load/soak, restart persistence of safety state.

---

## 11. SESSION 3 reassessment (2026-10-11, later)

Sections 0-10 are historical. This is an evidence-based evaluation, **not** a statement of ISO/IEC 9126 compliance or certification. Evidence tags as in §0
(**M** measured, **A** automated test, **B** automated real-browser run, **I** inspection, **U** human testing — none).

| Characteristic | Session 2 | Now | Confidence | Basis |
|---|:-:|:-:|:-:|---|
| Functionality | B | **B** | Medium | Safety function now covers the whole lifecycle incl. restart (A: 22 tests; M: kill -9 run). Safety requirements finally written down (I) but **not approved**; all worker behaviour simulated, notifications mocked. No human UI testing. |
| Reliability | B- | **B** | Medium | Emergency durability proven on SQLite (M); no duplicate incidents under threads / restarts / two processes (A, M); failed saves never mark an emergency resolved (A). Gaps: single process only; no external watchdog while the server is down; crash → ≤ 3 s lease handover; no soak / power-loss test; PostgreSQL untested; audit growth unbounded. |
| Usability | C (prov.) | **C+ / B- (provisional)** | Low-Medium | Automated axe WCAG 2.1 AA: 0 violations / 21 scans in 3 engines (B); measured button contrast 6.11 / 4.96 : 1 (M); focus trap, keyboard sign-in, no phone overflow (B). Still no screen reader, real device, Safari, touch-target (N-05) fix or user task testing — automated tools find only part of accessibility problems. |
| Efficiency | B | **B** | Medium | No regression seen (stress suite 34/34; heartbeat saves only changed rows, ≈ one small write per state change). Not load-tested; small dataset; one laptop. |
| Maintainability | B | **B** | Medium | 676 + 78 tests, 0 test warnings, avg complexity A (3.34); new grade-C functions: `_persist` 16, `SafetyStore.save` 11. CI file now has Python 3.10/3.12/3.13 × Node 22/24 but is **unobserved**. Requirements unpinned. |
| Portability | C | **B-** | Medium | Backend suite passes on Linux with Python 3.10, 3.12, 3.13 and on Windows 3.13; frontend on Windows + Linux with Node 22 and 24; browser audit in Chromium, Firefox, WebKit (Windows builds). Not tested: macOS, Windows + Python 3.10/3.12, PostgreSQL (unsupported), real Safari. Cross-platform runs *found and fixed* three test-portability defects (X-01…X-03). |

Missing evidence (affects confidence): human usability and accessibility testing; remote CI; multi-process behaviour; production database; long-run durability; retention policy decision.
