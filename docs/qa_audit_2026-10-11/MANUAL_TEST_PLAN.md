# FieldTrack — Manual Test Plan

**Applies to:** branch `prithugammer`, commit `1fd784e` · **Prepared:** 2026-10-11 · **Tester:** __________ · **Date run:** __________

Everything below is derived from the repository (routes in `backend/routes/`, screens in `frontend/src/pages/`,
seed data in `backend/seed.py`, wording copied from the source and from `DEMO.md`). The two blank columns
**Actual** and **P/F/B** (Pass / Fail / Blocked) are for you. Where the *Expected* result is "current
behaviour of a known defect", the defect id (D-nn) refers to `DEEP_AUDIT_FINDINGS.md`; record what you really
see — a "Pass" there means *the defect reproduces as described*, and you should note it as such.

> **Automation status of this plan:** none of these UI steps could be executed by the auditor (the browser
> extension was not connected). Everything marked *API* was executed by script in the audit and its result is
> cited in `evidence/`; re-running it by hand is still worthwhile for your own evidence.

> **Updated after the remediation session (2026-10-11).** All original test cases are kept. Cases whose expected result changed carry an
> **After remediation:** note in their *Expected* column, and §23 adds new cases (REM-01 …) for every fixed or newly found issue.
> *Actual* and *P/F/B* columns are still blank for you to fill in. Cases marked **(safety-critical)** concern worker-safety behaviour.

## 0. Rules for safe testing

1. **Use a disposable database for everything in this plan.** Your real development database is
   `backend/instance/fieldtrack.db`; never point destructive tests at it. Section 1 starts a second backend on
   port **5055** with a scratch SQLite file and a second frontend on **5174**; your normal 5000/5173 stack can
   keep running.
2. Your PowerShell may contain a stale `DATABASE_URL` (a PostgreSQL URL from another project). **Set
   `DATABASE_URL` explicitly in each terminal below** or clear it (`Remove-Item Env:DATABASE_URL`); otherwise the
   backend will not start.
3. Do not enter real personal data. Use only the seeded demo accounts and invented values. Never paste your
   real `SECRET_KEY`; where a production-style key is needed, generate a throw-away one.
4. Clean up at the end (§21).

### Seeded demo accounts (from `README.md` / `DEMO.md` / `seed.py`)

| Role | Email | Password |
|------|-------|----------|
| Admin (Sunita Sharma) | `admin@fieldtrack.com` | `Admin123!` |
| Dispatcher (Rajesh Shrestha) | `dispatch@fieldtrack.com` | `Dispatch123!` |
| Dispatcher (Anita Gurung) | `dispatch2@fieldtrack.com` | `Dispatch123!` |
| Supervisor (Bikash Thapa) | `supervisor@fieldtrack.com` | `Super123!` |

Workers (Ramesh Karki, Sita Rai, Dipak Tamang, Suresh Magar, Pooja Basnet, Santosh Khadka, Kamala Poudel,
Bishal Neupane) are records only and cannot sign in. Ids on a fresh seed: Admin 1, Dispatchers 2–3, Supervisor 4,
Workers 5–12 in the order listed (confirm with `GET /api/users`). Sites 1–6: Kirtipur (200 m), Koteshwor (300 m),
Boudha (150 m), Gongabu (250 m), Bhaktapur (200 m), Patan (200 m). **Today's jobs:** *Level 4 framing*
(Kirtipur, 2/3 crew: Ramesh, Pooja), *Deck pour - Span 2* (Gongabu, 2/3: Dipak, Santosh), *Level 3 rough-in*
(Boudha, 2/2: Sita, Kamala). Bishal and Suresh are unassigned today. Seeded entries: 6 workers clocked in today,
3 flagged pending entries, 4 approved entries, Suresh's overnight shift 8.50 h.

## 1. Start the disposable test environment

```powershell
# ---- Terminal 1: disposable backend on :5055 (safety demo timings: idle 15 s, three 5 s check-in windows)
cd "<repo>\backend"
.venv\Scripts\Activate.ps1
mkdir C:\temp -ErrorAction SilentlyContinue | Out-Null
$env:DATABASE_URL = "sqlite:///C:/temp/fieldtrack_qa.db"
$env:CORS_ORIGINS = "http://localhost:5174"
$env:PORT         = "5055"
$env:SAFETY_MODE  = "demo"; $env:SAFETY_SEED = "3"
python seed.py --reset --yes     # expect: Seeded: 12 users, 6 sites, 8 jobs, 17 assignments, 20 time entries (3 flagged, 4 approved), 34 location pings.
python app.py

# ---- Terminal 2: disposable frontend on :5174
cd "<repo>\frontend"
$env:VITE_API_URL = "http://127.0.0.1:5055"
npx vite --port 5174 --strictPort      # open http://localhost:5174
```

Your **normal** stack (for the record) is: Terminal 1 `cd backend; Remove-Item Env:DATABASE_URL; .venv\Scripts\Activate.ps1; python seed.py; python app.py`;
Terminal 2 `cd frontend; npm run dev` → http://localhost:5173.

### API helper (paste once into any PowerShell window used for API tests)

```powershell
$B = "http://127.0.0.1:5055/api"
function Tok($e,$p){ (Invoke-RestMethod "$B/auth/login" -Method Post -ContentType application/json -Body (@{email=$e;password=$p}|ConvertTo-Json)).token }
function Api($m,$path,$tok=$null,$body=$null){
  $h=@{}; if($tok){$h.Authorization="Bearer $tok"}
  try { $r=Invoke-WebRequest "$B$path" -Method $m -Headers $h -ContentType application/json -Body $body -UseBasicParsing
        "{0} {1} -> {2}  {3}" -f $m,$path,$r.StatusCode,$r.Content.Substring(0,[Math]::Min(160,$r.Content.Length)) }
  catch { $e=$_.Exception.Response; $t=(New-Object IO.StreamReader($e.GetResponseStream())).ReadToEnd()
          "{0} {1} -> {2}  {3}" -f $m,$path,[int]$e.StatusCode,$t.Substring(0,[Math]::Min(160,$t.Length)) } }
$adm=Tok "admin@fieldtrack.com" "Admin123!"; $dis=Tok "dispatch@fieldtrack.com" "Dispatch123!"; $sup=Tok "supervisor@fieldtrack.com" "Super123!"
```
(If you trigger the login throttle during §4, restart the backend or wait 5 minutes before re-pasting.)

**Evidence to capture for every test:** a screenshot with the browser URL bar visible, and for API steps the
terminal line. Name files `<TestID>.png` / `<TestID>.txt`. For UI failures also save DevTools → Network
(HAR) and Console.

## 2. Minimum critical regression suite (run these first — marked ★)

`ENV-01 · AUTH-01 · AUTH-03 · AUTH-05 · RBAC-02 · RBAC-07 · DASH-01 · USR-01 · JOB-01 · JOB-02 · TE-01 · TE-02 · TE-03 · GEO-01 · MAP-01 · SAF-01 · SAF-02 · SAF-04 · VAL-01 · SEED-01 · SEED-02 · SEC-01 · REC-01` (23 tests, ≈ 2 hours).

**Suggested order of the first ten:** ENV-01 → AUTH-01 → AUTH-03 → RBAC-02 → JOB-02 → TE-02 → TE-03 → MAP-01 → SAF-01 → SAF-04.

Columns: **ID** · **Pri**(ority) · **Objective / preconditions / data** · **Steps** · **Expected** · **Evidence** · **Actual** · **P/F/B**

## 3. ENV — environment and startup

| ID | Pri | Objective / preconditions / data | Steps | Expected | Evidence | Actual | P/F/B |
|----|-----|----------------------------------|-------|----------|----------|--------|-------|
| ENV-01 ★ | Critical | Clean start of backend. §1 done. | 1) Run Terminal-1 commands. 2) Browse `http://127.0.0.1:5055/api/health`. | Seed line shows 12 users, 6 sites, 8 jobs, 17 assignments, 20 entries (3 flagged, 4 approved), 34 pings. Health → `{"status":"ok"}`. No traceback. | Terminal screenshot + browser | | |
| ENV-02 | High | Frontend start. | Run Terminal-2; open `http://localhost:5174`. | Sign-in page with brand panel, form, 4 demo-account buttons. No console errors. | Screenshot, Console | | |
| ENV-03 | Medium | Reproduce the stale-`DATABASE_URL` failure (docs claim a clear message). | New terminal: `$env:DATABASE_URL="postgresql://u:p@127.0.0.1:5432/x"; cd backend; python app.py`. Then clear it and start again. | First start fails with `ModuleNotFoundError: No module named 'psycopg'` (there is no friendly message — see D-10). After clearing it starts. | Terminal | | |
| ENV-04 | High | Production secret enforcement (NFR-07). | In a new terminal (`DATABASE_URL` = scratch file): a) `$env:APP_ENV="production"; python app.py`. b) add `$env:SECRET_KEY="change-me"`. c) a 31-char key. d) a random 40-char key (`python -c "import secrets;print(secrets.token_hex(20))"`). e) with d) add `$env:FLASK_DEBUG="1"`. f) `$env:APP_ENV="prod"`. | a) `ConfigError: SECRET_KEY must be set in production…` b) placeholder error c) "at least 32 characters" d) starts e) `ConfigError: FLASK_DEBUG must not be enabled when APP_ENV=production` f) `APP_ENV must be one of…`. The key is never printed. | Terminal for each | | |
| ENV-05 | Medium | Debug mode is off by default (NFR-07). | Visit `http://127.0.0.1:5055/console` and `/api/nope`. | JSON `{"error":"That resource was not found.","field":null}` — no Werkzeug debugger page. | Screenshot | | |
| ENV-06 | Medium | CI Node mismatch (D-01). Optional. | Using Node 20 (`nvm`/`fnm`/`npx -y node@20.19.5 node_modules\vitest\vitest.mjs run` from `frontend/`). | Currently all 3 test files fail to load (`markAsUncloneable`). Passing means the defect is fixed.<br>**After remediation:** CI now uses Node 22 and 24 and `package.json` declares `engines`. On Node 20 the tests still cannot load (unchanged, by dependency); passing there would mean jsdom was downgraded. | Terminal | | |
| ENV-07 | Low | Documented dev start (README). | In your normal stack: `python seed.py` on an already-seeded DB. | "The database already contains data, so nothing was changed. …" exit 0. | Terminal | | |

## 4. AUTH — authentication and sessions

| ID | Pri | Objective / preconditions / data | Steps | Expected | Evidence | Actual | P/F/B |
|----|-----|----------------------------------|-------|----------|----------|--------|-------|
| AUTH-01 ★ | Critical | FR-01 each role signs in. | For each of the 4 demo accounts: click its demo button → **Sign in**. Sign out between. | Lands on Dashboard; top bar shows the user's name and role; no console errors. | 4 screenshots | | |
| AUTH-02 | High | Wrong password. | Admin email + `wrong-password` → **Sign in**. | Inline error under Password: "Invalid email or password."; stay on page; `localStorage.fieldtrack_token` absent (DevTools → Application). | Screenshot + Application tab | | |
| AUTH-03 ★ | High | Client validation (NFR-02). | Click **Sign in** with both fields empty (DevTools → Network open). | "Email is required." and "Password is required." appear; **no** request to `/auth/login`. | Screenshot + Network | | |
| AUTH-04 | High | No account enumeration (text). | Try `ghost@fieldtrack.com` / `x`, and Admin / wrong. | Identical message "Invalid email or password." (timing differs — see SEC-04). | 2 screenshots | | |
| AUTH-05 ★ | High | Rate limiting (D3). Disposable backend. | Admin email + wrong password **6 times**, then the correct password once. | Attempts 1-5: "Invalid email or password."; attempt 6: "Too many failed sign-in attempts. Try again in 300 seconds." (API: HTTP 429, `Retry-After: 300`); the correct password is also refused until the window passes (or you restart the backend). | Screenshots; `Api POST /auth/login` line | | |
| AUTH-06 | Medium | Per-client cap. | API: loop 25 different unknown emails: `1..25 \| % { Api POST /auth/login $null ('{"email":"u'+$_+'@x.com","password":"x"}') }` | First 20 → 401, then 429. | Terminal | | |
| AUTH-07 | Medium | After the window the user can log in. | After AUTH-05 wait 300 s (or restart backend) and sign in correctly. | Success; afterwards 5 fresh wrong attempts are allowed. | Screenshot | | |
| AUTH-08 | High | Session persistence. | Sign in; press F5 on Dashboard, Jobs, Time Entries. Then **Sign out**; press browser Back. | F5 keeps you signed in ("Restoring your session…" briefly). After sign-out you are at /login and Back does not show data without a session. | Screenshots | | |
| AUTH-09 | High | Tampered / invalid token. | Signed in: DevTools → Application → Local Storage → change `fieldtrack_token` to `abc`; reload. | Redirected to Sign in; token removed. | Screenshot | | |
| AUTH-10 | High | Deactivated account mid-session. | Browser A: Admin. Browser B (private window): Dispatcher 2 signed in. A: **Crew → Edit** Anita Gurung → deactivate. B: click any nav item/Refresh. Then B tries to sign in again. | B's request is refused (403 "Your account is no longer active.") and the UI shows an error/sign-out; sign-in → "This account has been deactivated. Contact an administrator." | Screenshots of both | | |
| AUTH-11 | High | Demotion applies immediately (D6). | A: Admin changes Bikash Thapa's role to Dispatcher. B (Bikash, still signed in as Supervisor): open Time Entries → try **Record time entry** → Save. Restore role afterwards. | Save is refused with 403 "Your role (Dispatcher) cannot do this…". | Screenshot | | |
| AUTH-12 | Medium | Passwords > 72 bytes (D2). | Admin → **Crew → Add person** (Dispatcher) with password = 73 × `a`. Then 72 × `a`. | 73: error under Password "Password must be at most 72 bytes long." (no crash). 72: created and can sign in. | Screenshots | | |
| AUTH-13 | Medium | Worker cannot sign in. | Sign in as `ramesh.karki@fieldtrack.com` with any password. | "Invalid email or password." (workers have no password). | Screenshot | | |
| AUTH-14 | Medium | D-14: admin password reset does not end existing sessions (documented defect). | B signed in as Dispatcher. A: Admin sets a new password for that Dispatcher. B: keep using the app. | **Current behaviour:** B keeps working until the 8 h token expires. Record.<br>**After session 3:** the old token must now be REFUSED with 401 'Your session has ended' (D-14 fixed). 'Still works' = failure. | Screenshot | | |
| AUTH-15 | Low | Theme toggle. | Click the sun/moon on the sign-in page and in the app; reload. | Choice persists; sign-in page and app both follow it. | 2 screenshots | | |
| AUTH-16 | Medium | Unreachable backend at login. | Stop the backend; try to sign in. | "Cannot reach the FieldTrack server. Make sure the backend is running on port 5000." (the text says 5000 even if you use 5055 — cosmetic). | Screenshot | | |

## 5. RBAC — role-based authorization

| ID | Pri | Objective / preconditions / data | Steps | Expected | Evidence | Actual | P/F/B |
|----|-----|----------------------------------|-------|----------|----------|--------|-------|
| RBAC-01 | High | All staff reach all pages (App routes). | For each role open Dashboard, Jobs, Live Map, Job Sites, Crew, Time Entries, Reports. | All 7 load for Admin, Dispatcher, Supervisor; none for a signed-out user. | 3 × screenshot | | |
| RBAC-02 ★ | Critical | FR-02: Dispatcher cannot record/approve time. | Sign in as Dispatcher → Time Entries. Then API: `Api POST /time-entries $dis '{"user_id":5,"job_id":4,"clock_in":"2026-10-11T07:00","in_lat":27.7,"in_lng":85.3}'`. | UI: no **Record time entry**, **Approve**, **Reject** or **Clock out** buttons. API: 403 `Your role (Dispatcher) cannot do this. Allowed: Supervisor, Admin.` | Screenshot + terminal | | |
| RBAC-03 | High | Supervisor cannot manage jobs. | Supervisor → Jobs; then `Api POST /jobs $sup '{}'`. | No **New job / Edit / Assign worker**. API 403 `Allowed: Dispatcher, Admin.` | Screenshot + terminal | | |
| RBAC-04 | High | Only Admin edits people. | Supervisor and Dispatcher → Crew. Then `Api POST /users $dis '{}'`. | Text "Only admins can edit people."; no **Add person**/**Edit**. API 403. | Screenshot + terminal | | |
| RBAC-05 | High | Only Dispatcher/Admin edit sites. | Supervisor → Job Sites. | No **New site/Edit**. | Screenshot | | |
| RBAC-06 | High | Admin sees every control. | Admin on each page. | **New job, Assign worker, New site, Add person, Record time entry, Approve/Reject, Clock out** all present. | Screenshots | | |
| RBAC-07 ★ | Critical | Full API role matrix. | Run for each token (`$adm,$dis,$sup`, and none): `Api POST /users $t '{}'`; `Api POST /sites $t '{}'`; `Api POST /jobs $t '{}'`; `Api POST /assignments $t '{}'`; `Api POST /time-entries $t '{}'`; `Api PATCH /time-entries/1/approve $t '{}'`; `Api POST /safety/workers/5/sos $t`. | Users: Admin only. Sites/jobs/assignments: Dispatcher+Admin. Time entries/approve: Supervisor+Admin. Safety controls: Supervisor+Admin. Wrong role → 403; no token → 401 `Please log in to continue.`; allowed roles reach validation or the action (201/400/404/409), never 403. | Terminal log | | |
| RBAC-08 | Medium | Every route needs a token. | Without a token call 6 routes: `/users /jobs /dashboard /map/live /safety/audit /reports/flagged`. | All 401. | Terminal | | |
| RBAC-09 | Medium | Role claim in a stored token is not enough. | Decode your JWT payload (jwt.io, local only), note `role`; use Admin to demote the user; call a role-restricted API with the **old** token. | 403 — the database role wins (audit D6). | Terminal | | |

## 6. DASH — dashboard (FR-12)

| ID | Pri | Objective | Steps | Expected | Evidence | Actual | P/F/B |
|----|-----|-----------|-------|----------|----------|--------|-------|
| DASH-01 ★ | High | KPIs on a fresh seed (any role). | Sign in; read the four cards and lists. | Active jobs **3**; Workers clocked in **6**; Flagged entries **3**; Hours today is a non-negative decimal that grows with time of day. *Jobs today*: 3 rows with crew counts 2/3, 2/3, 2/2. *Needs attention*: 3 flagged entries + "Level 4 framing has 2 of 3" + "Deck pour - Span 2 has 2 of 3". *Unassigned workers*: Suresh Magar, Bishal Neupane. | Screenshot | | |
| DASH-02 | Medium | Loading state. | DevTools → Network → throttle "Slow 3G"; click **Refresh**. | "Loading today's operations…" visible; then data. | Screenshot | | |
| DASH-03 | Medium | Error and retry (NFR-02). | Stop the backend; **Refresh**. Start it; click **Try again**. | "Couldn't load this data" + message + **Try again**; recovers. | 2 screenshots | | |
| DASH-04 | Low | Links. | Click **Review** on a flagged item and **Assign crew** on an understaffed item. | `/time-entries?flagged=true` and `/jobs` open. | Screenshots | | |
| DASH-05 | Medium | Dashboard updates after actions. | Do JOB-02 (assign Bishal), then Refresh. | Unassigned workers shows only Suresh; the understaffed count changes. | Screenshot | | |

## 7. USR — user management (FR-03, Crew page)

| ID | Pri | Objective | Steps | Expected | Evidence | Actual | P/F/B |
|----|-----|-----------|-------|----------|----------|--------|-------|
| USR-01 ★ | High | Create staff. Admin. | **Add person**: name `Maya Lama`, email `maya.lama@example.test`, role Dispatcher, password `Sup3rSecret!` → save. Sign out; sign in as Maya. | Appears in the list; can sign in; email stored lower-case. | Screenshots | | |
| USR-02 | High | Worker needs a trade, no password. | Add person role Worker without trade → save; then with trade `Welder`. | First: inline error on Trade. Second: created; hint "Workers don't log in, so they don't need a password."; cannot sign in. | Screenshots | | |
| USR-03 | Medium | Duplicate email (case-insensitive). | Add another user with `MAYA.LAMA@EXAMPLE.TEST`. | Error on Email: "A user with email maya.lama@example.test already exists." | Screenshot | | |
| USR-04 | Medium | Field validation (boundaries). | Try: name 1 char / 101 chars; email `not-an-email`; phone `abc`; password 7 chars. | Each rejected with an inline message on the right field; nothing created. | 4 screenshots | | |
| USR-05 | High | Edit. | **Edit** a worker: change phone; then try an email already used. | Phone saved. Email clash → error on Email; original email unchanged. | Screenshots | | |
| USR-06 | High | Self-protection. | As Admin, edit yourself: set role Dispatcher; then deactivate yourself. | "You cannot remove your own Admin role." / "You cannot deactivate your own account."; account unchanged. | Screenshots | | |
| USR-07 | Medium | Deactivate/reactivate. | Deactivate Maya; try to sign in as Maya; reactivate; sign in. | While inactive: "This account has been deactivated. Contact an administrator."; after: works. | Screenshots | | |
| USR-08 | Medium | Role change rules. | Change worker Bishal to Dispatcher without a password; then with one. | First: error "Set a password so this staff member can log in." (field Password). Second: OK. | Screenshots | | |
| USR-09 | Low | Odd text is data. | Create a worker named `Robert'); DROP TABLE users;--`. | Saved and displayed literally; app unaffected. | Screenshot | | |
| USR-10 | Low | Phone placeholder (D-18). | Open **Add person**. | Placeholder shows `416-555-0100` (Toronto format). Note as cosmetic. | Screenshot | | |

## 8. JOB — jobs and crews (FR-05, FR-06, FR-07)

| ID | Pri | Objective | Steps | Expected | Evidence | Actual | P/F/B |
|----|-----|-----------|-------|----------|----------|--------|-------|
| JOB-01 ★ | High | Create a job (DEMO step 2). Dispatcher. | **Jobs → New job**: click **Create job** empty first. Then site *Kirtipur Campus Expansion*, title `Level 4 drywall prep`, date **today**, crew size **2** → **Create job**. | Empty: "Job site is required." (and other required messages). Valid: job appears in the list with status Scheduled. | Screenshots | | |
| JOB-02 ★ | Critical | Assign + double-booking 409 (DEMO steps 3–4). | On the new job: **Assign worker** → Bishal Neupane → assign; **Done**. On *Level 4 framing*: assign Bishal. | 1st succeeds (Bishal under *Current crew*). 2nd: under Worker field: "Bishal Neupane is already assigned to 'Level 4 drywall prep' … A worker can only be booked on one job per day." Nothing saved. | Screenshots | | |
| JOB-03 | High | Crew full. | Assign a 3rd worker to `Level 4 drywall prep` (crew 2) after Bishal + one more. | "The crew for 'Level 4 drywall prep' is full (2 of 2)." | Screenshot | | |
| JOB-04 | High | Edit rules. | **Edit** *Level 4 framing*: crew size 1 (2 assigned); then change its date while workers are assigned. | Crew size: error "can't be less than the 2 worker(s) already assigned". Date: 409 "Remove the 2 assigned worker(s) before changing the date." | Screenshots | | |
| JOB-05 | Medium | Filters. | Use Date, Status, **Today**, **Clear filters**. | List filters correctly; empty result shows an empty state, not a blank page. | Screenshots | | |
| JOB-06 | Medium | Remove a worker. | **Remove** Bishal from `Level 4 drywall prep`. Then try to remove Ramesh from *Level 4 framing* after recording time for him (TE-01). | First succeeds. Second refused: "Time has already been recorded for this worker on this job…". | Screenshots | | |
| JOB-07 | Medium | Completed job takes no crew. | Set a job to Completed; try **Assign worker**. | 409 "This job is already completed." | Screenshot | | |
| JOB-08 | Medium | Boundaries. | Title 2 / 3 / 121 chars; crew size 0 / 1 / 50 / 51; description 1001 chars. | 2, 121, 0, 51, 1001 rejected with field messages; 3, 1, 50 accepted. | Screenshots | | |
| JOB-09 | Low | Date extremes (D-11). | API: `Api POST /jobs $dis '{"site_id":1,"title":"Far future","scheduled_date":"9999-12-31","crew_size":2}'`. | **Current behaviour:** 201 (no range check). Record. | Terminal | | |
| JOB-10 | Medium | Created-by is the signed-in user. | Create a job as Dispatcher 2, view it. | "Created by Anita Gurung"; a `created_by` in the request body is ignored (API). | Screenshot | | |

## 9. SITE — job sites (FR-04)

| ID | Pri | Objective | Steps | Expected | Evidence | Actual | P/F/B |
|----|-----|-----------|-------|----------|----------|--------|-------|
| SITE-01 | High | Create/edit. | **New site**: `Test Yard`, `12 Ring Road, Kathmandu`, lat 27.70, lng 85.30, radius blank. Edit radius to 450. | Created with radius 200; edit saved. | Screenshots | | |
| SITE-02 | Medium | Radius boundaries. | Radius 24, 25, 5000, 5001, `abc`, blank-on-edit. | 24, 5001, abc, blank-on-edit rejected on Geofence radius; 25, 5000 accepted. | Screenshots | | |
| SITE-03 | Medium | Coordinate boundaries. | lat 91, -91, 90; lng 181, -181, 180; `abc`. | ±91/±181/abc rejected; 90/180 accepted. | Screenshots | | |
| SITE-04 | **High** | **D-02** far-away site hangs the Live Map. **Disposable DB only.** | 1) Open **Live Map** and confirm it works. 2) As Dispatcher edit site *Kirtipur Campus Expansion* (has a job today): lat `28.2096`, lng `83.9856` (Pokhara). 3) Reload **Live Map**; time how long it takes. 4) Try a safety control (SAF-01). 5) Restore the original latitude/longitude (write them down in step 2 before editing). | **Current behaviour:** the map/Safety panel stalls for ~13 s on first load (longer for much farther points); safety controls hang equally. Passing = the map answers < 1 s. Record seconds.<br>**After remediation (expected now):** the Live Map answers immediately (well under 1 s; a real browser showed the warning in ≈1.5 s including page load), shows 'N job site(s) outside the supported road network', the affected worker is not drawn, and safety controls still respond. A stall of ~13 s is a failure. See REM-05/REM-06. | Screen recording / stopwatch | | |
| SITE-05 | Low | Geofence edit does not rewrite history. | Reduce a site's radius; check an existing entry's flag state. | Existing entries keep their stored flags; only new entries use the new radius. | Screenshot | | |

## 10. ASG — assignments (API-level, FR-06/07)

| ID | Pri | Objective | Steps | Expected | Evidence | Actual | P/F/B |
|----|-----|-----------|-------|----------|----------|--------|-------|
| ASG-01 | High | Double-booking via API. | `Api POST /assignments $dis '{"job_id":6,"user_id":5}'` (Ramesh is on job 4 today). | 409 naming "Level 4 framing". | Terminal | | |
| ASG-02 | High | Invalid ids. | `…'{"job_id":-1,"user_id":5}'`; `'{"job_id":4,"user_id":9223372036854775808}'`; `'{"job_id":99999,"user_id":5}'`; `'{"job_id":4,"user_id":1}'` (an Admin). | 400 (job_id), 400 (user_id), 404 (job_id), 400 "is a Admin, not a Worker". | Terminal | | |
| ASG-03 | Medium | Wrong date. | `'{"job_id":4,"user_id":12,"work_date":"2030-01-01"}'`. | 400 field work_date ("assignments must be for that date"). | Terminal | | |
| ASG-04 | Medium | Filters. | `Api GET "/assignments?job_id=4" $dis`; `?user_id=0`; `?work_date=soon`. | 2 rows; 400; 400. | Terminal | | |
| ASG-05 | Medium | **D-04** crew-size race (optional script). | Use `probes/probe_h5_run.py` / `probe_h_run.py` (Python venv) on a scratch DB, or two browser windows pressing **Assign** for two different workers on a job with one free place at the same instant. | **Current behaviour:** crew can exceed its size (24/25 trials in the audit). Record.<br>**After remediation:** the crew never exceeds its size; the loser gets 409 'The crew for … is full'. See REM-08. | Script output | | |

## 11. TE — time entries (FR-08, FR-10, FR-11)

Use **Supervisor** unless stated. Click-to-fill buttons: **On site (30 m)**, **500 m away**, "Simulate phone GPS".

| ID | Pri | Objective | Steps | Expected | Evidence | Actual | P/F/B |
|----|-----|-----------|-------|----------|----------|--------|-------|
| TE-01 ★ | Critical | Inside geofence (DEMO 5). Needs JOB-02 first. | **Record time entry**: Bishal Neupane, job *Level 4 drywall prep*, clock-in today 07:00 → **On site (30 m)**; clock-out today 11:30 → second **On site (30 m)** → **Save entry**. | Green banner: clock-in ~30 m from site, inside the 200 m geofence. Row not flagged; hours 4.50. | Screenshot | | |
| TE-02 ★ | Critical | 500 m away (DEMO 6). | Same worker/job, clock-in 12:00 → **500 m away**, clock-out 15:30 on site → **Save**. | Amber banner "FLAGGED for review — Clock-in 500 m from site (limit 200 m)"; entry **still saved**; row flagged. | Screenshot | | |
| TE-03 ★ | Critical | Approve with mandatory reason (DEMO 7, FR-11). | **Geofence → Flagged only** (4 amber rows). On Bishal's 12:00 row **Approve**; submit empty; then enter a reason. Try to approve it again. | Empty: "A reason is required for the audit trail." After: *Approved* + "Bikash Thapa: …". Second attempt unavailable/refused: "already approved by Bikash Thapa" (API 409). | Screenshots | | |
| TE-04 | High | Reject. | Reject another pending closed entry with reason `Wrong job`. | Status Rejected; excluded from reports hours. | Screenshot | | |
| TE-05 | High | Not assigned (FR-08). | Record time for **Suresh Magar** on *Level 4 framing* today. | 409 on Worker: "Suresh Magar is not assigned to 'Level 4 framing' on <date>. Assign the worker to this job first." Nothing saved. | Screenshot | | |
| TE-06 | High | Overlap. | Record Ramesh Karki today 07:30–08:30 on *Level 4 framing* (he is already clocked in from 07:00). | 409 "Overlaps entry #N for Ramesh Karki (… – still clocked in)." | Screenshot | | |
| TE-07 | High | Clock out. | On a still-open row (e.g. Sita Rai) click **Clock out**: time before clock-in; then > 24 h later; then valid. | "Clock-out must be after clock-in." / "A shift can't be longer than 24 hours." / success + geofence re-check. A second clock-out → 409 "already been clocked out". | Screenshots | | |
| TE-08 | High | Overnight shift (FR-10). | Record a worker 22:00 today → 06:30 tomorrow (job must be assigned for today). Also view seeded Suresh Magar yesterday 19:00 → today 03:30. | Hours **8.50** for both; entry belongs to the clock-in date. | Screenshot | | |
| TE-09 | Medium | Approve an open entry. | **Approve** on a row with no clock-out (API if no button): `Api PATCH /time-entries/<id>/approve $sup '{"decision":"Approved","edit_reason":"test ok"}'`. | 400 "Clock the worker out before approving or rejecting this entry." | Terminal | | |
| TE-10 | Medium | Filters. | Status, Geofence (Flagged only / Not flagged), Worker, date; **Clear filters**. | Lists match; newest first. | Screenshots | | |
| TE-11 | Medium | GPS bounds. | lat 91; lng 181; text; blank. | Rejected with field messages. | Screenshot | | |
| TE-12 | Medium | **D-03** double-submit. | Fill a valid entry; press **Save entry** as fast as possible several times (or double-click). Check the list. | **Ideal:** one entry. **Known risk:** duplicates/overlap (audit: 5 of 12 concurrent). Record what you see.<br>**After remediation:** exactly one entry is saved; the others are refused with 409 'Overlaps entry #…' (or 'already has an open time entry'). See REM-07. | Screenshot | | |
| TE-13 | Medium | **D-11** timezone suffix. | API: `Api POST /time-entries $sup '{"user_id":12,"job_id":7,"clock_in":"<tomorrow>T07:00:00Z","in_lat":27.7,"in_lng":85.3}'` (tomorrow's job 7 is Bishal's). | **Current behaviour:** accepted; stored as 07:00 local (offset discarded). Record.<br>**After session 3:** HTTP 400 'must not include a time zone' (D-11 fixed), not accepted. | Terminal | | |
| TE-14 | Low | Future clock-in. | Record an entry for tomorrow on tomorrow's assignment. | **Current behaviour:** accepted (no "future" rule). Record. | Screenshot | | |
| TE-15 | Medium | CSV integrity. | **Reports → Download CSV** for today ± 2 days. Compare rows with the Time Entries page. | Same entries, hours, status, approver. | CSV + screenshot | | |

## 12. GEO — geofence rule (FR-09)

| ID | Pri | Objective | Steps | Expected | Evidence | Actual | P/F/B |
|----|-----|-----------|-------|----------|----------|--------|-------|
| GEO-01 ★ | Critical | Boundary around the radius. | Get the Kirtipur site coordinates: `Api GET /sites $sup` (radius 200). Record clock-ins at lat = site lat + **190 m** (190/111195 = 0.001709°) and + **210 m** (0.001889°), same lng. | 190 m: not flagged. 210 m: flagged "Clock-in 210 m from site (limit 200 m)". (Exact 199/201 m boundaries are covered by automated tests.) | Screenshots | | |
| GEO-02 | Medium | Clock-out flag and combined reasons. | Clock-in 500 m away, clock-out 500 m away. | One flagged entry whose reason mentions both clock-in and clock-out. | Screenshot | | |
| GEO-03 | Medium | Different radii. | Same 210 m offset at Boudha (150 m) and Koteshwor (300 m). | Boudha flagged; Koteshwor not. | Screenshots | | |
| GEO-04 | Low | Extreme coordinates. | Clock-in with lat 90, lng 180 on a normal site. | Accepted, flagged (distance huge); no 500. | Screenshot | | |

## 13. MAP — Live Map (FR-13)

| ID | Pri | Objective | Steps | Expected | Evidence | Actual | P/F/B |
|----|-----|-----------|-------|----------|----------|--------|-------|
| MAP-01 ★ | Critical | Loads and polls through the new endpoint. | Sign in (Supervisor); open **Live Map**; DevTools → Network, filter `/api/`. Watch 10 s. | Sites with geofence circles; workers moving; "Simulated time" and "New cycle in m:ss" labels. Network shows **`POST /api/safety/tick` about once per second** and `GET /api/map/sim-clock`; **no** repeated `GET /api/map/live`.<br>**After remediation (replaces the line above):** Network shows **`GET /api/map/live` about once a second and no `POST /api/safety/tick`**; the backend, not this page, advances safety escalation. | Screenshot + Network | | |
| MAP-02 | High | Lazy loading. | Hard-reload on Dashboard (Network cleared), then click **Live Map**. | `LiveMap-*.js` and its CSS are requested only on that click; a "Loading the map…" fallback may flash; no console errors. | Network | | |
| MAP-03 | High | Backend loss and recovery. | With the map open stop the backend for 15 s, then start it. | A warning "Lost connection to the server — retrying." appears; markers stay; after restart the warning disappears **without reload**. | 2 screenshots | | |
| MAP-04 | Medium | Popup / route. | Click a moving worker. | Popup shows job and "km left"; a route line shrinks; "Delayed near <junction>" for slowed workers. Safety buttons only for Supervisor/Admin (see SAF). | Screenshot | | |
| MAP-05 | Medium | Reset view and bounds. | Zoom/drag far away; click **Reset view**. | Returns to the sites' view; panning is bounded. | Screenshot | | |
| MAP-06 | Medium | Cycle restart. | Wait for the countdown to reach 0:00. | Markers fade out/in; no duplicates or JS errors. | Console | | |
| MAP-07 | Medium | Theme/tile switch. | Toggle dark mode on the map. | Light and dark base maps match the theme. (Needs internet for tiles.) | Screenshots | | |
| MAP-08 | Medium | Token expiry mid-map. | Edit `fieldtrack_token` to `abc` while the map polls. | Next poll 401 → redirect to Sign in; polling stops. | Screenshot | | |
| MAP-09 | Medium | **D-12** hidden tab. | Open the map as Supervisor. Switch to another browser tab (or minimise the window) for 3 minutes without closing the map tab. Return. Open **Safety → Audit log**. | Record whether entries such as "monitoring was paused" appear (browsers throttle background timers; the server resets idle timers after a gap > 10 s).<br>**After remediation:** a hidden or closed tab no longer matters — escalation continues on the server. 'monitoring was paused' now appears only if the *server process* was suspended (> 10 s). Re-test with REM-02. | Screenshot | | |
| MAP-10 | Medium | Two viewers. | Open the map in two browsers (Supervisor + Dispatcher); make one worker idle (SAF-05). | Both show the same alerts; the audit log shows each transition **once**. | Screenshots | | |

## 14. SAF — safety and emergency (needs `SAFETY_MODE=demo` as in §1)

Pick a worker whose popup shows **On site** or **In transit** ("on shift"). Times below assume demo mode
(idle 15 s, 3 check-ins × 5 s ⇒ emergency about 30 s after a worker stops).

| ID | Pri | Objective | Steps | Expected | Evidence | Actual | P/F/B |
|----|-----|-----------|-------|----------|----------|--------|-------|
| SAF-01 ★ | Critical | SOS → EMERGENCY. Supervisor. | Click an on-shift worker → **SOS**. Look at the marker, the **Safety** panel (Alerts, Messages, Audit log). | Marker red/pulsing, status EMERGENCY; panel shows a critical alert with location and nearest co-worker; Messages shows a supervisor alert and the **mock** emergency-services call; Audit has SOS, EMERGENCY, SUPERVISOR_ALERT, EMERGENCY_CALL. | Screenshots | | |
| SAF-02 ★ | Critical | Resolve as false alarm. | In the alert type a note, click **Resolved – false alarm**. | Worker returns to normal; Audit shows RESOLVED with note and actor "Bikash Thapa (Supervisor)". | Screenshots | | |
| SAF-03 | High | Real incident → return to duty. | New SOS; **Resolved – real incident**; then **Return to duty**. | Status Post-incident (kept visible, not re-escalated) then normal; audit RESOLVED, RETURN_TO_DUTY. | Screenshots | | |
| SAF-04 ★ | Critical | Dispatcher cannot act (see Findings §3). | Sign in as Dispatcher. Open a worker popup and an active alert (have a Supervisor trigger one in another window). API: `Api POST /safety/workers/<id>/accident $dis`, `…/resolve $dis '{"outcome":"false_alarm"}'`. | Popup shows status only — **no Trigger accident, SOS, Start break, I'm OK**; the alert shows no resolve / return-to-duty buttons; the Messages tab shows no reply button. API: 403 for each, and the emergency stays EMERGENCY. | Screenshots + terminal | | |
| SAF-05 | High | Accident escalation timeline. | Supervisor: **Trigger accident** on an on-shift worker; open Audit log; note timestamps. | Worker stops (status Stopped); IDLE/ACCIDENT, CHECKIN_SENT 1,2,3 and EMERGENCY at roughly +15 s, +20 s, +25 s, +30 s (± 2 s); worker never answers. | Audit export | | |
| SAF-06 | High | Dispatcher cannot press "I'm OK" / break; Admin can. | Dispatcher: look for **Start break** and **I'm OK**; Admin: use them. | Dispatcher: absent; Admin: present and working. | Screenshots | | |
| SAF-07 | High | Break suppresses idle. | **Start break** on a stationary on-site worker; wait 40 s; **End break**. | No check-ins during the break; monitoring resumes after (timers restart). | Audit | | |
| SAF-08 | Medium | "I'm OK". | Let a fine-but-idle worker reach check-in 1; in **Messages** press **Reply "I'm OK" as <name>**. | Check-in cleared (CHECKIN_RESPONSE + CHECKIN_CLEARED); back to normal. | Audit | | |
| SAF-09 | Medium | Audit export. | **Audit log** tab → export CSV and JSON. | Files download; rows match the on-screen log; CSV opens in Excel; actor/time/message columns present. | Files | | |
| SAF-10 | High | **Restart loses safety state** (documented limitation). | Raise an emergency; stop and restart the backend; reload the map. | Emergency and audit log are gone. Record.<br>**SUPERSEDED in session 3:** the emergency and audit log now SURVIVE a restart (see PER-01). The old expectation ('gone') is no longer correct. | Screenshots | | |
| SAF-11 | High | **D-12** polling gap. | Make a worker stationary (e.g. SOS-free idle worker on site) and note the first check-in; close the Live Map tab for 40 s; reopen. | Check-in disappears; audit shows "Check-in n cleared: monitoring was paused (no dashboard was open)"; **no emergency** raised during the gap. Record.<br>**After remediation:** closing the Live Map for 40 s must **not** clear the check-in; on return the audit shows the normal CHECKIN_UNANSWERED / EMERGENCY entries at their due times. See REM-01/REM-02. (Old behaviour = defect D-12.)<br>**After session 3:** unchanged from session 2 (no 'paused' clearing; escalation continues on the server). | Audit | | |
| SAF-12 | Medium | Invalid transitions give clear messages. | SOS the same worker twice; Resolve a worker who is not in an emergency; Return-to-duty on a normal worker. | Red banner with 409 text each time ("already in an emergency", "not in an emergency", "not marked post-incident"); state unchanged. | Screenshots | | |
| SAF-13 | Medium | Two supervisors race. | Two windows (Supervisor, Admin) resolve the same emergency at once. | Exactly one succeeds; the other shows a 409 message; audit has one RESOLVED. | Audit | | |
| SAF-14 | Low | Privacy note. | Read the bottom of the Safety panel. | Text says location is used only to raise safety alerts and every event is audited. | Screenshot | | |
| SAF-15 | Medium | Tick isolation. | API: `Api POST "/safety/tick?now=0" $dis`; `Api GET /safety/tick $sup`. | 200 (parameter ignored; server clock); GET → 405. | Terminal | | |

## 15. VAL — input validation and error handling (API)

| ID | Pri | Objective | Steps | Expected | Evidence | Actual | P/F/B |
|----|-----|-----------|-------|----------|----------|--------|-------|
| VAL-01 ★ | Critical | The two original 500s. | `Api POST /time-entries $sup '{"user_id": 1e999, "job_id": 4, "clock_in": "2026-10-11T07:00", "in_lat": 27.7, "in_lng": 85.3}'`; `Api GET /jobs/99999999999999999999999 $sup`. | 400 `{"error":"Worker must be a whole number.","field":"user_id"}`; 404 `Job #… was not found.` — **never 500**. | Terminal | | |
| VAL-02 | High | 64-bit boundary table. | Repeat the first call with `user_id` = `9223372036854775807`, `9223372036854775808`, `-9223372036854775808`, `-9223372036854775809`, a 30-digit number, `0`, `-1`, `NaN`, `Infinity`, `-Infinity`, `null`, `"abc"`, `"7"`, `7.0`, `7.5`, `true`. | 404, then 400 for out of range / non-finite / zero / negative / null / text / fraction / boolean; `"7"` and `7.0` accepted (reach business rules). | Terminal | | |
| VAL-03 | High | Query filters. | `Api GET "/jobs?site_id=0" $sup`, `?site_id=9223372036854775808`, `?site_id=1e999`, `?site_id=abc`, `?site_id=` (blank), `Api GET "/map/live?route=abc" $sup`. | 400 each (field named), blank → 200 (ignored). | Terminal | | |
| VAL-04 | High | Dates. | `Api GET "/jobs?date=20261001"`, `…2026-W40-4`, `…2026-02-30`, `…2026-10-01`. | 400, 400, 400, 200. | Terminal | | |
| VAL-05 | Medium | Malformed JSON. | `Api POST /jobs $dis ''`, `'[1]'`, `'null'`, `'{'`. | 400 `Request body must be a JSON object.` | Terminal | | |
| VAL-06 | Medium | **D-05** nested JSON. | PowerShell: `Api POST /auth/login $null ('['*3000)`. | **Current behaviour:** 500. After a fix: 400. Record.<br>**After remediation:** HTTP **400** `Request body is nested too deeply.` (was 500, D-05). | Terminal | | |
| VAL-07 | Medium | **D-06** lone surrogate. | `Api POST /auth/login $null '{"email":"\ud800","password":"x"}'` and a job with title `\ud800\ud800\ud800`. | **Current behaviour:** 500. After a fix: 400.<br>**After remediation:** HTTP **400** with `field` set (e.g. email) — `contains characters that are not allowed.` (was 500, D-06). | Terminal | | |
| VAL-08 | Medium | **D-07** extreme date range. | `Api GET "/reports/hours-by-worker?to=9999-12-31" $adm`; `Api GET "/time-entries?date=9999-12-31" $adm`. | **Current behaviour:** 500. After a fix: 200.<br>**After remediation:** HTTP **200** (was 500, D-07). | Terminal | | |
| VAL-09 | Medium | **D-09** oversized body. | Send a 5 MB `email` string to `/auth/login`. | **Current behaviour:** parsed fully, then 400 `Email must be at most 120 characters.` (no size limit).<br>**After remediation:** HTTP **413** `The request body is too large.` (limit 1 MiB, D-09). | Terminal | | |
| VAL-10 | Medium | Error shape. | Provoke 400, 401, 403, 404, 405, 409, 429. | Every body is `{"error": "...", "field": ...}`. | Terminal | | |
| VAL-11 | High | No partial writes. | Before/after a rejected request, compare `GET /jobs`, `/users`, `/time-entries` counts and a sample row. | Identical. | Terminal | | |
| VAL-12 | Medium | Text is data. | Create a job titled `<b>bold</b>` and a site `O'Brien "Yard"`. | Stored and displayed literally everywhere (list, dashboard, map popup); no HTML interpreted. | Screenshots | | |

## 16. SEED — seeding, persistence and recovery of data

| ID | Pri | Objective | Steps | Expected | Evidence | Actual | P/F/B |
|----|-----|-----------|-------|----------|----------|--------|-------|
| SEED-01 ★ | Critical | Ordinary seed is harmless. | In the scratch DB add a user via the UI. Stop the backend; `python seed.py` twice. Restart; list users. | Output "The database already contains data, so nothing was changed…" (exit 0); your added user still exists; counts unchanged. | Terminal + screenshot | | |
| SEED-02 ★ | Critical | Reset needs confirmation. | `cmd /c "python seed.py --reset < NUL"` (stdin is not a terminal) and `python seed.py --yes`. | First: "Refusing to reset without confirmation: add --yes." exit 1, data intact. Second: seed message, data intact. | Terminal | | |
| SEED-03 | High | Authorised reset. | `python seed.py --reset --yes`. | Wipes the scratch DB and reloads (your added user disappears; 12 users). | Terminal | | |
| SEED-04 | High | Interactive reset. | In an interactive terminal: `python seed.py --reset`; answer `no`; repeat and type `RESET`. | `no`/anything else → "Reset cancelled." exit 1; `RESET` → reloads. Ctrl+C at the prompt → cancelled. | Terminal | | |
| SEED-05 | High | Production refusal. | `$env:APP_ENV="production"; $env:SECRET_KEY="<40 random chars>"; python seed.py --reset --yes`. | "Refusing to reset: APP_ENV=production. Production data is never wiped." exit 1. | Terminal | | |
| SEED-06 | Medium | Non-SQLite URL (**D-10**). | `$env:DATABASE_URL="postgresql://u:p@127.0.0.1:5432/x"; python seed.py --reset --yes`. | **Current behaviour:** `ModuleNotFoundError: psycopg` (not the friendly refusal; no data touched). Record.<br>**After session 3:** a clean one-line refusal ('Refusing to reset a postgresql database…') with no traceback and no password in the text (D-10 fixed). | Terminal | | |
| SEED-07 | Medium | Unavailable DB (**D-10**). | `$env:DATABASE_URL="sqlite:///C:/no/such/dir/x.db"; python seed.py`. | **Current behaviour:** raw SQLAlchemy traceback, exit 1. Record.<br>**After session 3:** one line 'Could not open or write the database (…)'; no traceback, no path/URL (D-10 fixed). | Terminal | | |
| SEED-08 | High | Seeded logins & relationships. | After reset sign in with all 4 accounts; open Crew, Jobs. | 4 accounts work; 8 workers; each assignment's date equals its job's date; workers have no password. | Screenshots | | |
| SEED-09 | Medium | Persistence across restart. | Create a job; stop and restart the backend (no seed); reload. | Job persists (SQLite file); safety state does not (SAF-10). | Screenshot | | |
| SEED-10 | Low | Docs match CLI. | Copy-paste every seed command from README.md and DEMO.md. | Each runs as described. | Terminal | | |

## 17. NAV — navigation, integration and reports

| ID | Pri | Objective | Steps | Expected | Evidence | Actual | P/F/B |
|----|-----|-----------|-------|----------|----------|--------|-------|
| NAV-01 | High | Deep link when signed out. | Signed out, open `/time-entries` directly; sign in. | Redirected to /login, then returned to Time Entries. | Screenshot | | |
| NAV-02 | Medium | Unknown URL. | Open `/does-not-exist` signed in. | Redirected to Dashboard. | Screenshot | | |
| NAV-03 | Medium | Back/Forward. | Visit Dashboard → Jobs → Crew; Back ×2, Forward ×1. | Correct pages; no blank screen. | Screenshots | | |
| NAV-04 | Medium | Sign-out across tabs. | Two tabs signed in; sign out in tab 1; use tab 2. | Tab 2 works until its next API call returns 401, then signs out (token held in memory). Record. | Screenshots | | |
| NAV-05 | High | Reports (FR-12). | **Reports** → From = 2 days ago, To = +2 days → **Apply range**. Compare with Time Entries. | *Hours by worker* approved vs pending, *Hours by job*, *Flagged entries* correct; totals add up; rejected entries and open shifts excluded. | Screenshots | | |
| NAV-06 | Medium | Invalid range. | From later than To. | Error message in the UI (API 400). | Screenshot | | |
| NAV-07 | Medium | **D-07** in the UI. | To = `9999-12-31` (type the date). | **Current behaviour:** generic server error state (500). Record. | Screenshot | | |
| NAV-08 | Low | CSV download. | **Download CSV**. | File `*.csv` with header + rows; opens in Excel; commas in names quoted. | File | | |
| NAV-09 | Medium | Hard refresh on every page. | F5 on all 7 pages. | No blank pages; no console errors. | Console | | |

## 18. UX — responsive layout and accessibility

Use Chrome DevTools device toolbar for sizes; screenshot each result. For accessibility use the **axe DevTools**
extension or Lighthouse (Accessibility) and save the report.

| ID | Pri | Objective | Steps | Expected | Evidence | Actual | P/F/B |
|----|-----|-----------|-------|----------|----------|--------|-------|
| UX-01 | High | Desktop 1366×768 and 1920×1080. | Visit all 7 pages. | No horizontal page scroll; tables readable; modals fit. | Screenshots | | |
| UX-02 | High | Phone 390×844 (and 360×640). | Sign-in, Dashboard, Jobs (create modal), Time Entries (record modal), Live Map. | Usable without zoom; sidebar collapses to icons below 800 px; forms scroll inside modals; map fills screen.<br>**After remediation:** no horizontal page scroll on Dashboard, Live Map, Crew, Time Entries, Reports at 390 px (was failing, N-01). | Screenshots | | |
| UX-03 | High | Keyboard only (no mouse). | Tab through sign-in; Enter submits; open a modal with Enter/Space; Esc closes. | Visible focus ring on every control; logical order; Enter submits. | Screen recording | | |
| UX-04 | Medium | **D-19** modal focus. | Open **New job**; press Tab repeatedly past the last button; close with Esc; note where focus lands. | Expected good practice: focus stays inside the dialog and returns to the opening button. **Current (by code):** may leave the dialog / not return. Record.<br>**After remediation:** focus stays inside the dialog (Tab and Shift+Tab wrap) and returns to the opening button on close (verified in Chromium; D-19). | Recording | | |
| UX-05 | Medium | Labels and errors. | Click each form label; submit invalid forms with a screen reader (NVDA) or the accessibility tree. | Label focuses its input; errors (`role="alert"`) are announced; no unlabeled controls. | axe report | | |
| UX-06 | Medium | Colour contrast, light and dark. | axe/Lighthouse on /login, /, /time-entries, /live-map in both themes. | No WCAG AA contrast failures (record any).<br>**After remediation:** automated axe (WCAG 2.1 AA) reports only the white-on-orange primary button (2.61:1, N-04, awaiting a design decision); record anything else you see.<br>**After session 3:** automated axe now reports zero violations in 3 engines; still record what you see. | Reports | | |
| UX-07 | Medium | 200 % zoom and text-only zoom. | Browser zoom 200 %. | No clipped or overlapping content. | Screenshots | | |
| UX-08 | Medium | Map keyboard access. | Tab to map markers; press Enter. | Markers focusable with names (aria-labels); popup opens. | Recording | | |
| UX-09 | Low | Loading/empty states. | Slow 3G on each page; filter to zero results. | "Loading…" then data; empty states with explanatory text; never a blank area. | Screenshots | | |
| UX-10 | Low | Date/time inputs. | Enter times in 12 h/24 h locale. | Values interpreted as local site time (no timezone support — D-11). | Screenshot | | |

## 19. SEC — security checks

| ID | Pri | Objective | Steps | Expected | Evidence | Actual | P/F/B |
|----|-----|-----------|-------|----------|----------|--------|-------|
| SEC-01 ★ | Critical | Forged/edited token. | Copy your JWT; at jwt.io (offline decode only!) edit `role` to `Admin` without re-signing; send it: `Api GET /users "<edited token>"`; also try `…eyJhbGciOiJub25lIn0….` (alg none). | 401 `Your session is invalid. Please log in again.` | Terminal | | |
| SEC-02 | High | Security headers. | DevTools → Network → any API response → Headers. | `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `Content-Security-Policy: default-src 'none'; frame-ancestors 'none'; base-uri 'none'`, `Cache-Control: no-store`; no HSTS on http. | Screenshot | | |
| SEC-03 | High | CORS. | With the disposable backend (allows only :5174), open your **normal** frontend `http://localhost:5173` pointed at it (`VITE_API_URL=http://127.0.0.1:5055`) and sign in. | Browser blocks the request (CORS error in Console); no data. | Console | | |
| SEC-04 | Medium | **D-08** timing enumeration. | PowerShell: `Measure-Command { Api POST /auth/login $null '{"email":"admin@fieldtrack.com","password":"x"}' }` ×10, then with `ghost@fieldtrack.com` ×10 (restart the backend between to avoid 429, or use 4 each). | **Current behaviour:** known email ≈ 0.2 s slower than unknown (bcrypt). Record medians.<br>**After remediation:** known and unknown emails take about the same time (measured median ratio 0.98 at cost 12). A visible gap of ~0.2 s means the fix is missing. | Terminal | | |
| SEC-05 | Medium | **D-13** victim lock-out. | 5 wrong attempts for `supervisor@fieldtrack.com` from your PC; then try the right password from another browser/machine. | 429 for up to 300 s. Record.<br>**After session 3:** the owner at ANOTHER address is NOT blocked by a stranger's five failures (D-13). A block only happens after 25 failures across addresses, or 5 from the owner's own address. | Screenshot | | |
| SEC-06 | Medium | XSS. | Job title `<b>x</b><img src=x onerror=console.log(1)>`; view it in Jobs, Dashboard, Time Entries, Live Map popup. | Shown as literal text; Console never logs `1`. | Screenshot + Console | | |
| SEC-07 | Low | Token storage. | DevTools → Application. | Token is in `localStorage` (XSS-readable by design); note for the report. | Screenshot | | |
| SEC-08 | Low | Server banner. | Inspect `Server` response header. | `Werkzeug/…` on the dev server (use a production server in deployment). | Screenshot | | |
| SEC-09 | Medium | Secrets never logged. | Fail 6 logins; read the backend terminal. | Lines like "Login throttled for client 127.0.0.1 (retry in 300s)" — no email, password, token or hash. | Terminal | | |
| SEC-10 | Medium | SQL injection probes. | Filters/fields with `' OR 1=1 --`, `"; DROP TABLE users;--`. | 400/404 or stored literally; data intact. | Terminal | | |

## 20. REC — recovery and restart behaviour

| ID | Pri | Objective | Steps | Expected | Evidence | Actual | P/F/B |
|----|-----|-----------|-------|----------|----------|--------|-------|
| REC-01 ★ | High | Backend crash/restart. | Signed in on Time Entries; stop the backend; click around; start it. | Friendly "Cannot reach…"/error states while down; after restart pages work again **without** signing in (dev signing key is stable; with a production `SECRET_KEY` from the environment tokens also survive). | Screenshots | | |
| REC-02 | High | What a restart clears. | Raise an emergency, fail 3 logins, restart. | Safety state and login-throttle counters reset; database content persists. | Notes | | |
| REC-03 | Medium | Database file missing/locked. (Scratch DB only.) | While running, rename `C:\temp\fieldtrack_qa.db`; use the app; rename back. | Generic error state (500 body "Something went wrong on the server."), no stack trace in the browser; recovers after rename back. | Screenshot | | |
| REC-04 | Medium | Browser refresh during an action. | Press F5 while a modal save is in flight. | No duplicate/partial record on reload; list consistent. | Screenshot | | |
| REC-05 | Low | Laptop sleep / long idle. | Leave the app signed in 9+ hours (or edit the token expiry: set `JWT_EXPIRES_HOURS=0.01` before starting the backend and wait 40 s). | Next request → "Your session has expired. Please log in again." → Sign in page. | Screenshot | | |
| REC-06 | Medium | CI parity. | Optional: push a branch/PR and watch **Actions**. | Backend job should pass; **frontend job currently fails at `npm test` on Node 20 (D-01)**. Record the run URL.<br>**After remediation:** both the Node 22 and Node 24 frontend jobs and the backend job are expected to pass; this is the only way to observe remote CI. | Screenshot | | |

## 21. Clean-up

```powershell
# stop both terminals (Ctrl+C), then remove only the scratch files you created:
Remove-Item C:\temp\fieldtrack_qa.db -ErrorAction SilentlyContinue
# clear per-terminal variables (they die with the window anyway)
Remove-Item Env:DATABASE_URL, Env:CORS_ORIGINS, Env:PORT, Env:SAFETY_MODE, Env:SAFETY_SEED, Env:VITE_API_URL, Env:APP_ENV, Env:SECRET_KEY -ErrorAction SilentlyContinue
```
Your real `backend\instance\fieldtrack.db` and the 5000/5173 servers are untouched by this plan.

## 22. Traceability (test → requirement)

FR-01 AUTH-01…13 · FR-02 RBAC-* · FR-03 USR-* · FR-04 SITE-* · FR-05 JOB-01/04/05/08 · FR-06 JOB-02/03/06/07, ASG-* ·
FR-07 JOB-02, ASG-01 · FR-08 TE-01/05/06 · FR-09 TE-02, GEO-* · FR-10 TE-07/08 · FR-11 TE-03/04/09 ·
FR-12 DASH-*, NAV-05…08, TE-15 · FR-13 MAP-*, SITE-04 · NFR-01 AUTH-12, SEC-* · NFR-02 AUTH-03, DASH-03, VAL-10 ·
NFR-03 MAP-01 / DASH-* (feel) + `AUTOMATED_TEST_RESULTS.md` §6 · NFR-04 TE-06, JOB-02, ASG-05, TE-12 ·
NFR-06 ENV-*, UX-* · NFR-07 ENV-04/05, SEC-02 · *Safety (no FR/NFR exists — D-21)* SAF-*.

## 23. Tests added after the remediation (REM-xx)

Same columns as above. **Pri** is Critical / High / Medium / Low; **(safety-critical)** marks anything about alerts, check-ins or emergencies.
Use the disposable stack of §1. For REM-01…REM-04 start the backend in **demo** mode (`SAFETY_MODE=demo`, `SAFETY_AUTO_RESPOND_CHANCE=0`,
`SAFETY_ACCIDENT_PROBABILITY=0`) so the thresholds are 15 s idle + 3 × 5 s windows = **30 s**.

| ID | Pri | Objective / preconditions / data | Steps | Expected | Evidence | Actual | P/F/B |
|----|-----|----------------------------------|-------|----------|----------|--------|-------|
| REM-01 ★ | Critical (safety-critical) | **D-12** Escalation advances with no browser open. Fresh backend, seeded, demo mode. | 1) Start only the backend (Terminal 1 of §1); do **not** open any browser and do not call any API except `/api/health`. 2) Wait 40 s. 3) Then sign in via the API helper and `Api GET /safety/audit $sup`. | Audit contains, for at least one stationary on-site worker: `IDLE_DETECTED` (~+15 s), three `CHECKIN_SENT`, `CHECKIN_UNANSWERED` ×3 and `EMERGENCY` (~+30 s), plus `EMERGENCY_CALL` (mock). Backend console shows the `[SAFETY]` lines at those times. | Audit JSON + console | | |
| REM-02 ★ | Critical (safety-critical) | **D-12** Closing the dashboard does not stop an escalation that has started. | 1) Open the Live Map as Supervisor. 2) Wait for a worker to enter check-in 1 (Safety panel). 3) Close the tab / whole browser. 4) Wait 35 s. 5) Reopen the Live Map. | The worker is in EMERGENCY (or later check-in) at the due times; Audit shows no `CHECKIN_CLEARED … monitoring was paused`. | Screenshot + audit | | |
| REM-03 | High (safety-critical) | **Heartbeat-off warning.** | Start the backend with `$env:SAFETY_TICKER_ENABLED="0"`. Open the Live Map. | Yellow banner: 'Safety monitoring is not running on the server, so check-ins and emergencies will not escalate…'. Workers never escalate on their own. | Screenshot | | |
| REM-04 | High (safety-critical) | **Restart behaviour (documented limitation).** | Let a worker reach EMERGENCY; stop and restart the backend; reload the Live Map; watch for 40 s. | The emergency and the Audit log are **gone** after the restart (state is in memory). The same worker is re-detected from zero: IDLE after ~15 s, EMERGENCY ~30 s after the restart. Record this as expected-but-limited.<br>**SUPERSEDED in session 3:** safety state is now saved. Expected now: after the restart the SAME emergency is shown with its original times, no second alert/call, audit history intact (see PER-01). | Screenshots + audit | | |
| REM-05 ★ | Critical | **D-02** Unsupported site, Pokhara. Disposable DB. | As Dispatcher edit the site of a job scheduled today: latitude `28.2096`, longitude `83.9856`. As Supervisor open **Live Map**; time it. Restore the coordinates afterwards. | Map and Safety panel load in about a second; warning 'N job site is outside the supported road network (<name>) … (1 affected)'; that worker is not drawn; other workers keep moving. (Before the fix: 13.5 s stall.) | Screenshot + stopwatch | | |
| REM-06 | High (safety-critical) | **D-02** Safety controls stay usable with an unsupported site. Continue from REM-05. | With the far site still in place, in the Live Map click an on-shift worker → **SOS**, then **Resolved – false alarm**. Also run `Api POST /safety/tick $sup`. | Each action completes in well under a second; the unsupported-site warning stays; no error banner. | Screenshot + terminal | | |
| REM-07 ★ | Critical | **D-03** Simultaneous clock-ins. | Run `python ..\docs\qa_audit_2026-10-11\probes\stress_suite.py --skip-real-process` from `backend/` (it builds its own temp DB), or in the UI have two supervisors press **Save entry** for the same worker/time at the same moment. | '12 simultaneous identical clock-ins … `{201: 1, 409: 11}` … exactly one stored'. In the UI: one entry saved, the other shows 409 'Overlaps entry …'. | Terminal output | | |
| REM-08 | High | **D-04** Crew capacity under concurrency. | Same script; or two dispatchers press **Assign to job** for two different workers on a job with one free place at the same instant. | 'capacity boundary 3/8 stored 3', '4/10 stored 4', 'crew race … overfilled in 0 trial(s)'. In the UI: one succeeds, one gets 'The crew for … is full'. | Terminal output | | |
| REM-09 | Medium | **D-09** Oversized body. | `Api POST /auth/login $null ('{"email":"' + ('a'*2000000) + '"}')` | HTTP **413** `The request body is too large.` immediately; server still healthy (`GET /api/health`). | Terminal | | |
| REM-10 | Medium | **D-05** Nested JSON. | `Api POST /auth/login $null ('['*3000)` and `('['*60000)` | HTTP **400** `Request body is nested too deeply.` both times. | Terminal | | |
| REM-11 | Medium | **D-06** Lone surrogate. | `Api POST /auth/login $null '{"email":"\ud800","password":"x"}'`; create a job with title `"\ud800\ud800\ud800"` as Dispatcher. | HTTP **400**, `field` = email / title, 'contains characters that are not allowed.' Valid Nepali / emoji names are still accepted (create a user named `प्रिथक शाह`). | Terminal | | |
| REM-12 | Medium | **D-07** Extreme dates. | `Api GET "/reports/hours-by-worker?to=9999-12-31" $adm`; `Api GET "/time-entries?date=9999-12-31" $adm`; `Api GET "/reports/hours.csv?from=0001-01-01&to=9999-12-31" $adm`. In the Reports page set To = 9999-12-31 and press **Apply range**. | HTTP 200 each (empty or full data); the Reports page shows a table, not an error. | Terminal + screenshot | | |
| REM-13 | Medium | **D-08** Login timing. | Use the stress-suite style measure: run `Measure-Command` on 15 wrong-password logins for `admin@fieldtrack.com`, then 15 for `ghost@fieldtrack.com` (restart the backend between to avoid the 429, or set `LOGIN_RATE_LIMIT_ENABLED=0`). | Medians within a few percent of each other (measured ratio 0.98). Record both medians and p95; a ~0.2 s gap = fix missing. | Terminal | | |
| REM-14 | Medium | **Busy database → 503.** Disposable DB file path known. | 1) In another terminal: `python -c "import sqlite3,time; c=sqlite3.connect(r'C:/temp/fieldtrack_qa.db',isolation_level=None); c.execute('BEGIN IMMEDIATE'); time.sleep(30)"`. 2) While it sleeps, record a time entry (UI or API) with `SQLITE_BUSY_TIMEOUT_SECONDS=2` set for the backend. 3) After the 30 s, repeat. | Step 2: HTTP **503**, `Retry-After: 1`, message 'The server is busy with another change. Please retry in a moment.', nothing saved. Step 3: succeeds. | Terminal | | |
| REM-15 | High | **D-19** Dialog focus. | Open **New job**; press Tab 15×, then Shift+Tab 5×; press Escape. | Focus never leaves the dialog; after Escape it is back on the **New job** button. | Screen recording | | |
| REM-16 ★ | High | **N-01** Phone layout. Browser DevTools device mode, 390×844 and 360×640. | Visit Dashboard, Live Map, Crew, Time Entries, Reports; try to scroll sideways. | The page itself never scrolls horizontally; the top bar wraps onto two rows; tables scroll inside their own box. | Screenshots | | |
| REM-17 | Medium | **N-02** Keyboard access to wide tables (phone width). | On Time Entries at 390 px press Tab until the table region is focused (outline), then use Left/Right arrows. | The table area receives focus (screen readers announce 'Data table' region) and scrolls with the arrow keys. | Recording | | |
| REM-18 | Medium | **N-03** Contrast after the colour fixes. Install the axe DevTools extension. | Scan Login, Dashboard, Jobs, Time Entries, Reports, Crew, Sites in light and dark themes. | No findings for muted text, sidebar text or the green Approve button. The **only** expected finding is white-on-orange primary buttons (N-04).<br>**After session 3:** expect NO axe findings at all (the orange button was fixed). | axe reports | | |
| REM-19 | Medium | **N-04** Decision record for the orange button (2.61:1). | Look at **Create job** / **Sign in**; decide: navy text on orange (6.1:1) or a darker orange (`#b45309`, 5.0:1) or accept. | A written decision. This test only records it; it is expected to remain 'open' until you choose.<br>**After session 3:** resolved — primary buttons use dark navy text on the orange (6.11:1). Record whether you accept the look. | Screenshot + note | | |
| REM-20 ★ | High | **D-01** Remote CI. | Push the branch (your decision), open **Actions** on GitHub. | Backend job passes; frontend job passes on **Node 22 and Node 24**. Record run URLs. Not verifiable by the auditor. | Screenshot | | |
| REM-21 | Medium | **Role UI in a real browser.** | Supervisor and Dispatcher on Live Map: click a worker. Supervisor on Jobs / Dispatcher on Time Entries. | Supervisor popup: Trigger accident, SOS, Start break. Dispatcher popup: none. Dispatcher has no Record / Approve; Supervisor has no New job. (Automated browser run passed; repeat by hand.) | Screenshots | | |
| REM-22 | Low | **Engine range.** | `npm ci` with Node 20. | npm prints an engine warning for jsdom/undici; `npm test` fails to load. Expected and documented. | Terminal | | |
| REM-23 | Medium | **WSGI entry point (untested by the auditor).** If you deploy with a WSGI server. | Start it (one worker) using `wsgi:app`; read the log. | The line 'Safety monitoring started (every 1.00 s)' appears **once**; REM-01 passes against it. | Console | | |
| REM-24 | Medium | **Index on an existing database.** | Start the backend once against your *copy* of an older database file. | Start-up succeeds; `PRAGMA index_list('time_entries')` lists `uq_time_entries_one_open_per_worker` (or a log warning says which worker has two open entries). | sqlite3 output | | |
| REM-25 | Medium | **Fuzz sweep.** | Run `probes\probe_g_run3.py` style sweep (copy from the audit) or the stress suite sections 1 and 4. | 0 responses with status ≥ 500; integrity check 'ok'. | Terminal | | |

## 24. Session 3 additions (2026-10-11, later)

### 24.1 New cases (PER-xx). Safety-critical ones are marked. *Actual* and *P/F/B* are blank for you.

Use the disposable stack of §1 with `SAFETY_MODE=demo` (emergency 30 s after a worker stops). Persistence is on by default (`SAFETY_PERSISTENCE=1`).

| ID | Pri | Objective / preconditions / data | Steps | Expected | Evidence | Actual | P/F/B |
|----|-----|----------------------------------|-------|----------|----------|--------|-------|
| PER-01 ★ | Critical (safety-critical) | **Restart keeps an open emergency.** Fresh scratch DB, backend + frontend running, signed in as Supervisor on Live Map. | 1) Wait (or press SOS on a worker) until a worker is in EMERGENCY. 2) In the backend terminal press Ctrl+C **or** kill the process (`Stop-Process -Force`). 3) Start the backend again (same `DATABASE_URL`, no `--reset`). 4) Reload the Live Map. 5) Open **Audit log**. | The same worker is still EMERGENCY with the original 'since' time; Alerts list unchanged; Audit shows the earlier events and **no second EMERGENCY / EMERGENCY_CALL**; backend log prints 'Restored safety state for N worker(s)'. | Screenshots + log | | |
| PER-02 ★ | Critical (safety-critical) | **Resolution survives a restart.** Continue from PER-01. | Resolve it as *real incident* with a note; restart the backend again; reload. Then *Return to duty*, restart once more. | After restart #2: worker shows Post-incident with the note; no re-escalation within 40 s. After return-to-duty and restart #3 the worker is normal and has no alert. | Screenshots | | |
| PER-03 ★ | High (safety-critical) | **Restart in the middle of an escalation.** | Make a worker idle; when Safety shows 'Check-in 2 of 3', restart the backend; reload. | Check-in 2 (or later) continues and the EMERGENCY appears at the original due time; no 'Check-in cleared' entry. | Audit export | | |
| PER-04 | High (safety-critical) | **Save failure is visible and safe.** Needs a scratch DB you can make read-only. | While an emergency is open make the DB file read-only (or temporarily rename it), wait 5 s, open Live Map; try **Resolved – false alarm**; restore the file. | Yellow banner 'could not save safety events (N waiting)'; resolve is refused (error shown, 'could not be saved'), emergency stays open; after restoring, the banner clears within seconds and a retry works. | Screenshots | | |
| PER-05 | Medium | **Two server processes.** Scratch DB. | Start the backend twice on different ports with the SAME `DATABASE_URL`; watch both consoles for 20 s. | Exactly one logs 'Safety heartbeat acquired'; the other 'held by another process'. Stop the first with Ctrl+C: within ~3 s the second logs 'Took over the safety heartbeat; reloading saved state'. (Running two processes is still unsupported for serving users.) | Consoles | | |
| PER-06 | Medium | **Existing database upgrade.** A COPY of an older `fieldtrack.db`. | Start the backend on the copy. | Starts normally; the four `safety_*` tables now exist (`sqlite3 … ".tables"`); existing users/jobs unchanged. | sqlite output | | |
| PER-07 | Medium | **Unreadable database at start-up.** | Point `DATABASE_URL` at a file that is not a database (a text file) and start the backend. | The backend refuses to start with an error (it must not start with an empty safety state). | Console | | |
| SEC-11 | High | **D-14** Password reset ends sessions. | Browser A: Dispatcher signed in. Browser B: Admin sets a new password for that Dispatcher (Crew → Edit). In A click any nav item. | A is signed out (401 'Your session has ended'); signing in with the new password works; the old password does not. | Screenshots | | |
| SEC-12 | Medium | **D-13** Owner not locked out by a stranger. | From PC 1 enter 5 wrong passwords for `supervisor@fieldtrack.com`; from PC 2 (or a different network / phone hotspot) sign in correctly. | PC 1 gets 429 after the 5th; PC 2 signs in. (A single PC cannot show this; use `X-Forwarded-For` only if `TRUSTED_PROXY_COUNT` is set.) | Screenshots | | |
| VAL-13 | Medium | **D-11** Time with a zone. | `Api POST /time-entries $sup` with `"clock_in":"<today>T07:00:00Z"` and `"…+05:45"`. | 400, field `clock_in`, 'must not include a time zone'. Without the zone it is accepted/409 as before. | Terminal | | |
| SEED-11 | Low | **D-10** Clean seed errors. | `$env:DATABASE_URL="postgresql://u:secret@127.0.0.1/x"; python seed.py --reset --yes`, then `sqlite:///C:/no/such/dir/x.db`. | One-line messages; no traceback; the word 'secret' never appears. | Terminal | | |
| UX-11 ★ | High | **N-04** Orange button contrast by eye and by tool. | Open Sign in, Jobs (New job), Time Entries, Reports in light and dark; hover and Tab to the primary button; run axe. | Dark navy text on the orange, readable in every state; axe reports no contrast issue. Record the colours the tool shows (expected 6.11:1 rest, 4.96:1 hover). | axe report | | |
| UX-12 | Medium | **Real Safari / iPhone / Android** (not available to the auditor). | Open the app on a real iPhone (Safari) and an Android phone (Chrome); sign in; open Dashboard, Jobs, Live Map, Time Entries. | No sideways page scroll; dialogs usable; tables scroll inside their box; Live Map pans and popups open. | Photos/screenshots | | |
| UX-13 | Medium | **Screen reader** (NVDA/JAWS/VoiceOver). | Sign in; open a dialog; trigger a validation error; read the Safety panel with an active alert. | Fields are announced with labels; errors are announced; the dialog is announced with its title; alerts are reachable. | Notes | | |
| CI-01 ★ | High | **Remote CI** (only you can do this). | Push the branch; open GitHub → Actions. | Backend job passes on Python 3.10, 3.12, 3.13; frontend on Node 22 and 24. Record the run URL. | Screenshot | | |
| PG-01 | Low | **PostgreSQL is unsupported.** | Do not test: there is no driver and the write-lock protection is SQLite-only. | Documented limitation only. If you ever add PostgreSQL, the concurrency and persistence tests must be re-run against it. | – | | |

### 24.2 What the AUDITOR executed by automation (not a substitute for your manual results)

This table records tool runs for cases listed in the plan. It does **not** mark any of the 193 existing cases as passed: the *Actual* and *P/F/B* columns above stay blank until a person runs them.

| Plan case | What was executed by automation | Result | Evidence | Still needs a human? |
|-----------|----------------------------------|--------|----------|----------------------|
| REM-01 | Real `python app.py` process, no client, demo thresholds | EMERGENCY at +30 s with idle/3 check-ins in the audit log | `evidence/J_AFTER_…`, `K_SESSION3_…` §7, `L_…` | Yes — repeat by hand, watch the console |
| REM-02 | Equivalent: unit test "closing every tab" + real process with no client. **The literal 'open the page, then close the browser' step was not performed.** | pass (equivalent) | `test_safety_ticker.py`, `L_…` | Yes |
| REM-04 | Superseded by PER-01: real-process hard kill + restart (twice) | PASS 14/14 | `L_restart_persistence_real_process.txt` | Yes (PER-01…03 in the UI) |
| REM-05, REM-06 | Playwright: site moved to Pokhara, warning shown, safety config answered fast, rest of page works | pass in Chromium, Firefox, WebKit (warning in ≈1.5 s) | `browser/*_SESSION3.json` | Yes |
| REM-07, REM-08 | Stress suite with a threaded server and file DB | pass (12 identical clock-ins → 1 stored; capacities 3/8, 4/10 exact; 0/20 overfilled) | `K_SESSION3_stress_suite.txt` | Yes (two real users) |
| REM-09…REM-14 | Fuzz / stress / unit tests | pass | `G_AFTER…`, `I_AFTER…`, tests | Partly |
| REM-15, REM-16, REM-17, REM-18 | Playwright (focus trap; no horizontal scroll at 390×844 on 7 pages; table keyboard focus; axe) — viewport **emulation**, not a real phone | pass in 3 engines | `browser/…` | Yes (real phone) |
| REM-19, UX-11 | Computed-style contrast measurement | 6.11 / 4.96 / 6.11 : 1 | `browser_results_*_SESSION3.json` (`primaryButtonContrast`) | Yes (by eye) |
| REM-20, CI-01 | **BLOCKED** — nothing is pushed; `gh run list` is empty | not run | – | Yes — only you |
| REM-21 | Playwright role checks in worker popups, Jobs and Time Entries | pass in 3 engines | `browser/…` | Yes |
| REM-22, REM-23, REM-24 | Not executed (Node 20, WSGI server, old-database copy). A test creates the tables on an old schema (REM-24 equivalent). | partial | `test_safety_persistence.py` | Yes |
| REM-25 | Fuzz: 3,069 requests | 0 responses ≥ 500 | `G_AFTER_fuzz.txt` | – |
| AUTH-01…AUTH-16, RBAC-*, DASH-*, USR-*, JOB-*, SITE-*, ASG-*, TE-*, GEO-*, MAP-*, SAF-*, VAL-*, SEED-*, NAV-*, SEC-*, REC-* (original 168) | Covered in part by the 676 backend and 78 frontend tests and by the 76 browser checks, but **not executed as written** | **NOT RUN as manual tests** | – | **Yes — all of them** |

Environment notes: Playwright's WebKit build on Windows is not Safari. Docker (WSL2) provided Linux for the automated suites only; no GUI testing was done on Linux.
