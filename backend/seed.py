"""Reset the database and load realistic demo data.

    python seed.py

Dates are relative to TODAY so the demo always works: jobs run yesterday, today and
tomorrow. Everything is recreated from scratch each time this script runs.

Summary of what is created:
  * 1 admin, 2 dispatchers, 1 supervisor (can log in) and 8 workers with trades
  * 6 job sites at real Kathmandu Valley locations (4 with jobs, 2 new with none yet)
  * 8 jobs across 3 days, with assignments
  * 20 time entries: 3 flagged, 4 approved, 1 night shift that crosses midnight,
    and 6 workers currently clocked in today
"""
import math
import random
from datetime import date, datetime, time, timedelta

from app import create_app
from extensions import db
from kathmandu_geo import LANDMARKS, random_point_near
from models import Assignment, Job, JobSite, LocationPing, TimeEntry, User

METRES_PER_DEGREE_LAT = 111_195  # ~ Earth's circumference / 360


def offset(site, north_m=0.0, east_m=0.0):
    """Return (lat, lng) that is north_m metres north and east_m metres east of a site.

    Used to place demo GPS readings a known distance from the site centre.
    """
    lat = site.latitude + north_m / METRES_PER_DEGREE_LAT
    lng = site.longitude + east_m / (METRES_PER_DEGREE_LAT * math.cos(math.radians(site.latitude)))
    return round(lat, 6), round(lng, 6)


def at(day, hh, mm=0):
    return datetime.combine(day, time(hh, mm))


def seed():
    """Drop every table, recreate them, and load the demo dataset described above."""
    today = date.today()
    yesterday = today - timedelta(days=1)
    tomorrow = today + timedelta(days=1)

    db.drop_all()
    db.create_all()

    # ---- Users --------------------------------------------------------------------------
    def staff(name, email, role, password, phone):
        u = User(full_name=name, email=email, role=role, phone=phone, is_active=True)
        u.set_password(password)
        return u

    admin = staff("Sarah Mitchell", "admin@fieldtrack.com", "Admin", "Admin123!", "416-555-0100")
    disp1 = staff("Kevin Lam", "dispatch@fieldtrack.com", "Dispatcher", "Dispatch123!", "416-555-0110")
    disp2 = staff("Rosa Delgado", "dispatch2@fieldtrack.com", "Dispatcher", "Dispatch123!", "416-555-0111")
    sup = staff("Greg Hanson", "supervisor@fieldtrack.com", "Supervisor", "Super123!", "416-555-0120")

    def worker(name, email, trade, phone):
        return User(full_name=name, email=email, role="Worker", trade=trade, phone=phone, is_active=True)

    marcus = worker("Marcus Reyes", "marcus.reyes@fieldtrack.com", "Carpenter", "647-555-0131")
    dana = worker("Dana Whitfield", "dana.whitfield@fieldtrack.com", "Electrician", "647-555-0132")
    luis = worker("Luis Ortega", "luis.ortega@fieldtrack.com", "Concrete Finisher", "647-555-0133")
    jamal = worker("Jamal Carter", "jamal.carter@fieldtrack.com", "Equipment Operator", "647-555-0134")
    priya = worker("Priya Nair", "priya.nair@fieldtrack.com", "Laborer", "647-555-0135")
    tom = worker("Tom Kowalski", "tom.kowalski@fieldtrack.com", "Ironworker", "647-555-0136")
    ashley = worker("Ashley Brooks", "ashley.brooks@fieldtrack.com", "Plumber", "647-555-0137")
    ben = worker("Ben Okafor", "ben.okafor@fieldtrack.com", "Laborer", "647-555-0138")

    db.session.add_all([admin, disp1, disp2, sup, marcus, dana, luis, jamal, priya, tom, ashley, ben])

    # ---- Job sites ----------------------------------------------------------------------
    # Each site sits a few hundred metres from a real landmark. The fixed seed keeps the
    # coordinates identical on every run, so the demo script can quote them.
    site_rng = random.Random("fieldtrack-sites")

    def site(name, address, landmark, radius):
        lat, lng = random_point_near(*LANDMARKS[landmark], 0.35, site_rng)
        return JobSite(site_name=name, address=address, latitude=lat, longitude=lng, geofence_radius_m=radius)

    kirtipur = site("Kirtipur Campus Expansion", "Kirtipur Municipality-3, Kathmandu 44618", "Kirtipur", 200)
    koteshwor = site("Koteshwor Flyover Underpass Repair", "Koteshwor Chowk, Kathmandu 44600", "Koteshwor", 300)
    boudha = site("Boudha Stupa Plaza Retrofit", "Boudha-6, Kathmandu 44600", "Boudhanath", 150)
    gongabu = site("Gongabu Bus Park Resurfacing", "New Bus Park, Gongabu, Kathmandu 44600", "Gongabu", 250)
    bhaktapur = site("Bhaktapur Heritage Walk Repaving", "Durbar Square, Bhaktapur 44800", "Bhaktapur Durbar Square", 200)
    patan = site("Patan Durbar Drainage Upgrade", "Mangal Bazar, Lalitpur 44700", "Patan Durbar Square", 200)
    db.session.add_all([kirtipur, koteshwor, boudha, gongabu, bhaktapur, patan])
    db.session.flush()

    # ---- Jobs (8 across yesterday / today / tomorrow) -----------------------------------
    def job(site, title, desc, day, crew, status, creator):
        return Job(site=site, title=title, description=desc, scheduled_date=day,
                   crew_size=crew, status=status, creator=creator)

    j1 = job(kirtipur, "Level 3 framing & sheathing", "Frame and sheath north and east walls, install steel lintels.", yesterday, 3, "Completed", disp1)
    j2 = job(koteshwor, "Culvert excavation & shoring (night)", "Night closure: excavate failed culvert and install trench shoring.", yesterday, 2, "Completed", disp2)
    j3 = job(boudha, "Level 2 rough-in (electrical & plumbing)", "East wing rough-in; core and patch slab penetrations.", yesterday, 3, "Completed", disp1)
    j4 = job(kirtipur, "Level 4 framing", "Frame Level 4 corridor and unit demising walls.", today, 3, "In progress", disp1)
    j5 = job(gongabu, "Deck pour - Span 2", "Place and finish 85 m³ deck concrete on span 2.", today, 3, "In progress", disp2)
    j6 = job(boudha, "Level 3 rough-in (electrical & plumbing)", "West wing rough-in ahead of inspection.", today, 2, "In progress", disp1)
    j7 = job(koteshwor, "Culvert backfill & compaction", "Backfill in 300 mm lifts, compaction testing.", tomorrow, 3, "Scheduled", disp2)
    j8 = job(gongabu, "Deck curing & finishing", "Apply curing compound, saw-cut joints.", tomorrow, 2, "Scheduled", disp2)
    db.session.add_all([j1, j2, j3, j4, j5, j6, j7, j8])
    db.session.flush()

    # ---- Assignments ----------------------------------------------------------------------
    # Yesterday: all 8 workers.  Today: 6 workers (Jamal and Ben worked the night shift,
    # so they are the "unassigned workers" on the dashboard).  Tomorrow: 3 so far.
    crew_plan = [
        (j1, [marcus, priya, tom]),
        (j2, [jamal, ben]),
        (j3, [dana, ashley, luis]),
        (j4, [marcus, priya]),          # 2 of 3 -> shows as understaffed
        (j5, [luis, tom]),              # 2 of 3 -> shows as understaffed
        (j6, [dana, ashley]),
        (j7, [jamal, ben]),
        (j8, [luis]),
    ]
    for j, crew in crew_plan:
        for w in crew:
            db.session.add(Assignment(
                job=j, worker=w, work_date=j.scheduled_date,
                assigned_at=at(j.scheduled_date - timedelta(days=2), 15, 30),
            ))
    db.session.flush()

    # ---- Time entries ---------------------------------------------------------------------
    def entry(w, j, cin, cout, in_offset, out_offset=None, status="Pending", reason=None):
        """Create an entry the same way the API does, including the geofence check."""
        in_lat, in_lng = offset(j.site, *in_offset)
        e = TimeEntry(worker=w, job=j, clock_in=cin, in_lat=in_lat, in_lng=in_lng, status="Pending")
        db.session.add(e)
        e.apply_geofence(in_lat, in_lng, "Clock-in")
        db.session.add(LocationPing(user=w, latitude=in_lat, longitude=in_lng, recorded_at=cin))
        if cout is not None:
            out_lat, out_lng = offset(j.site, *out_offset)
            e.clock_out, e.out_lat, e.out_lng = cout, out_lat, out_lng
            e.apply_geofence(out_lat, out_lng, "Clock-out")
            db.session.add(LocationPing(user=w, latitude=out_lat, longitude=out_lng, recorded_at=cout))
        if status != "Pending":
            e.status, e.approver, e.edit_reason = status, sup, reason
        return e

    ok = "Verified against foreman's daily log"
    y = yesterday
    # Yesterday — Kirtipur (split shifts around lunch)
    entry(marcus, j1, at(y, 7), at(y, 11, 30), (25, -10), (30, 5), "Approved", ok)
    entry(marcus, j1, at(y, 12), at(y, 15, 30), (20, 0), (35, 15), "Approved", ok)
    entry(priya, j1, at(y, 7, 5), at(y, 11, 30), (-40, 20), (-35, 10))
    entry(priya, j1, at(y, 12), at(y, 15, 35), (-30, 15), (-45, 0))
    entry(tom, j1, at(y, 6, 55), at(y, 11, 30), (60, 40), (55, 30))
    entry(tom, j1, at(y, 12, 5), at(y, 15, 40), (50, 35), (350, 0))        # FLAGGED clock-out 350 m
    # Yesterday — Boudha
    entry(dana, j3, at(y, 6, 30), at(y, 11), (10, 10), (15, -5), "Approved", ok)
    entry(dana, j3, at(y, 11, 30), at(y, 15), (5, 20), (10, 0), "Approved", ok)
    entry(ashley, j3, at(y, 6, 30), at(y, 11), (-20, 30), (-25, 20))
    entry(ashley, j3, at(y, 11, 30), at(y, 15, 5), (-15, 25), (-20, 10))
    entry(luis, j3, at(y, 7), at(y, 11, 30), (40, -40), (35, -30))
    entry(luis, j3, at(y, 12), at(y, 15, 30), (30, -35), (45, -25))
    # Yesterday night — Koteshwor culvert: 19:00 -> 03:30 today (crosses midnight = 8.5 h)
    entry(jamal, j2, at(y, 19), at(today, 3, 30), (80, 120), (60, 100))
    entry(ben, j2, at(y, 19, 10), at(today, 3, 30), (610, 0), (90, 110))  # FLAGGED clock-in 610 m

    # Today — currently clocked in (no clock-out yet)
    t = today
    entry(marcus, j4, at(t, 7), None, (25, 5))
    entry(priya, j4, at(t, 7, 2), None, (-30, 10))
    entry(luis, j5, at(t, 6, 45), None, (40, 60))
    entry(tom, j5, at(t, 6, 50), None, (0, 420))                         # FLAGGED clock-in 420 m
    entry(dana, j6, at(t, 7), None, (10, 5))
    entry(ashley, j6, at(t, 7, 5), None, (-15, 20))

    db.session.commit()

    flagged = TimeEntry.query.filter_by(is_flagged=True).count()
    approved = TimeEntry.query.filter_by(status="Approved").count()
    print(
        f"Seeded: {User.query.count()} users, {JobSite.query.count()} sites, {Job.query.count()} jobs, "
        f"{Assignment.query.count()} assignments, {TimeEntry.query.count()} time entries "
        f"({flagged} flagged, {approved} approved), {LocationPing.query.count()} location pings."
    )


if __name__ == "__main__":
    app = create_app()
    with app.app_context():
        seed()
