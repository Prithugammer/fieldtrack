"""Creates fieldtrack.db from schema.sql and fills it with demo data.
Run: python seed.py      (standard library only, no installs)
Demo login for every user: password = FieldTrack123!
"""
import sqlite3, hashlib, os, math
from datetime import datetime, timedelta, date

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "fieldtrack.db")

def hash_pw(pw: str) -> str:
    salt = os.urandom(8).hex()
    h = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 100_000).hex()
    return f"pbkdf2${salt}${h}"

def haversine_m(lat1, lng1, lat2, lng2):
    R = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return round(2 * R * math.asin(math.sqrt(a)))

def offset(lat, lng, north_m, east_m):
    return (lat + north_m / 111_320,
            lng + east_m / (111_320 * math.cos(math.radians(lat))))

if os.path.exists(DB):
    os.remove(DB)
con = sqlite3.connect(DB)
con.execute("PRAGMA foreign_keys = ON")
con.executescript(open(os.path.join(HERE, "schema.sql")).read())
cur = con.cursor()

now = datetime.now().replace(microsecond=0)
today = date.today()
yesterday = today - timedelta(days=1)
iso = lambda d: d.isoformat(sep=" ")
pw = hash_pw("FieldTrack123!")

# ---- users ----
staff = [("Alex Morgan","Admin"), ("Sarah Chen","Dispatcher"),
         ("Tom Reyes","Supervisor"), ("Linda Park","Supervisor")]
workers = [("Miguel Santos","Carpenter"), ("Dave Whitaker","Operator"),
           ("Priya Nair","Laborer"), ("Carlos Mendez","Carpenter"),
           ("Jamal Brooks","Operator"), ("Emily Torres","Laborer"),
           ("Ryan O'Neil","Carpenter"), ("Aisha Khan","Laborer"),
           ("Ben Carter","Operator"), ("Hannah Lee","Carpenter"),
           ("Omar Haddad","Laborer"), ("Kevin Brown","Laborer")]
uid = {}
def add_user(name, role, trade=None):
    email = name.lower().replace("'", "").replace(" ", ".") + "@fieldtrack.test"
    cur.execute("INSERT INTO users(full_name,email,password_hash,phone,role,trade) VALUES (?,?,?,?,?,?)",
                (name, email, pw, f"555-01{len(uid):02d}", role, trade))
    uid[name] = cur.lastrowid
for n, r in staff:   add_user(n, r)
for n, t in workers: add_user(n, "Worker", t)

# ---- sites ----
sites = [("Riverside Apartments - Phase 2", "1200 River Rd, Riverside", 44.9778, -93.2650, 200),
         ("Hwy 41 Culvert Repair", "Hwy 41 at Mile 12, Eastfield", 44.9537, -93.0900, 250),
         ("Maple Street Warehouse Retrofit", "88 Maple St, Westgate", 44.9210, -93.3000, 200)]
sid, coords, radius = {}, {}, {}
for name, addr, lat, lng, r in sites:
    cur.execute("INSERT INTO job_sites(site_name,address,latitude,longitude,geofence_radius_m) VALUES (?,?,?,?,?)",
                (name, addr, lat, lng, r))
    sid[name] = cur.lastrowid; coords[name] = (lat, lng); radius[name] = r
RIV, HWY, MAP = [s[0] for s in sites]

# ---- jobs: (code, site, supervisor, title, date, start, end, crew, status) ----
jobs = [("JOB-1041", RIV, "Tom Reyes",  "Framing level 2",        yesterday, "07:00","15:30",2,"Completed"),
        ("JOB-1042", RIV, "Tom Reyes",  "Framing level 3",        today,     "07:00","15:30",3,"In Progress"),
        ("JOB-1043", HWY, "Linda Park", "Culvert excavation",     today,     "06:30","15:00",2,"In Progress"),
        ("JOB-1044", MAP, "Linda Park", "Demolition prep",        today,     "09:00","17:00",2,"Scheduled"),
        ("JOB-1045", RIV, "Tom Reyes",  "Site cleanup",           today,     "05:00","13:00",1,"Completed"),
        ("JOB-1046", HWY, "Linda Park", "Guardrail install",      today,     "10:00","18:00",3,"Scheduled"),
        ("JOB-1047", MAP, "Linda Park", "Roof inspection",        today,     "07:30","16:00",1,"In Progress")]
jid = {}
for code, site, sup, title, d, st, en, crew, status in jobs:
    cur.execute("""INSERT INTO jobs(job_code,site_id,created_by,supervisor_id,title,scheduled_date,
                   start_time,end_time,crew_size,status) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (code, sid[site], uid["Sarah Chen"], uid[sup], title, str(d), st, en, crew, status))
    jid[code] = cur.lastrowid
site_of = {j[0]: j[1] for j in jobs}

# ---- assignments (Hannah, Omar, Kevin, Ben left unassigned on purpose) ----
crew = {"JOB-1041": ["Miguel Santos","Dave Whitaker"], "JOB-1042": ["Miguel Santos","Ryan O'Neil","Priya Nair"],
        "JOB-1043": ["Dave Whitaker","Carlos Mendez"], "JOB-1044": ["Jamal Brooks"],
        "JOB-1045": ["Emily Torres"],                  "JOB-1047": ["Aisha Khan"]}
work_date = {j[0]: str(j[4]) for j in jobs}
for code, names in crew.items():
    for n in names:
        cur.execute("INSERT INTO assignments(job_id,user_id,work_date) VALUES (?,?,?)",
                    (jid[code], uid[n], work_date[code]))

# ---- time entries ----
def entry(name, code, clock_in, clock_out, north, east, status="Pending", approver=None):
    site = site_of[code]; slat, slng = coords[site]
    lat, lng = offset(slat, slng, north, east)
    dist = haversine_m(lat, lng, slat, slng)
    flagged = int(dist > radius[site])
    cur.execute("""INSERT INTO time_entries(user_id,job_id,clock_in,clock_out,in_lat,in_lng,out_lat,out_lng,
                   distance_from_site_m,is_flagged,status,approved_by,approved_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (uid[name], jid[code], iso(clock_in), iso(clock_out) if clock_out else None,
                 lat, lng, lat if clock_out else None, lng if clock_out else None, dist, flagged, status,
                 uid[approver] if approver else None, iso(now) if approver else None))
    return lat, lng

h = timedelta
# yesterday: approved, for the reports screen
y = datetime.combine(yesterday, datetime.min.time())
entry("Miguel Santos",  "JOB-1041", y+h(hours=7),    y+h(hours=15,minutes=30), 30, 10, "Approved", "Tom Reyes")
entry("Dave Whitaker",  "JOB-1041", y+h(hours=7,minutes=5), y+h(hours=15,minutes=20), 20, -15, "Approved", "Tom Reyes")
# today: still clocked in (clock_out NULL)
live = {}
live["Miguel Santos"] = entry("Miguel Santos", "JOB-1042", now-h(hours=3,minutes=14), None, 30, 30)    # ~42 m
live["Ryan O'Neil"]   = entry("Ryan O'Neil",   "JOB-1042", now-h(hours=3,minutes=10), None, 60, 20)
live["Priya Nair"]    = entry("Priya Nair",    "JOB-1042", now-h(hours=3,minutes=5),  None, 480, 0)    # flagged
live["Dave Whitaker"] = entry("Dave Whitaker", "JOB-1043", now-h(hours=2,minutes=14), None, 70, 40)
live["Carlos Mendez"] = entry("Carlos Mendez", "JOB-1043", now-h(hours=2,minutes=10), None, 0, 510)    # flagged
live["Aisha Khan"]    = entry("Aisha Khan",    "JOB-1047", now-h(hours=1,minutes=45), None, -450, 90)  # flagged
# today: completed shift awaiting approval
entry("Emily Torres", "JOB-1045", now-h(hours=9), now-h(hours=1), 25, 5)

# ---- location pings: one every 5 min while clocked in; newest is 3 min old ----
for name, (lat, lng) in live.items():
    for i in range(4):
        la, ln = offset(lat, lng, i * 2, i * -2)
        cur.execute("INSERT INTO location_pings(user_id,latitude,longitude,recorded_at) VALUES (?,?,?,?)",
                    (uid[name], la, ln, iso(now - h(minutes=3 + 5 * (3 - i)))))

con.commit(); con.close()
print("Created", DB)
