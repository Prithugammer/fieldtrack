"""usage: probe_farsite.py LAT LNG - move the seeded site that has a job today, then time GET /api/map/live."""
import logging
import sys
import time

sys.path.insert(0, r"<SCRATCH_DIR>")
from probe_common import *  # noqa: E402,F401,F403

from datetime import date  # noqa: E402
from models import Job  # noqa: E402

logging.disable(logging.CRITICAL)
lat, lng = float(sys.argv[1]), float(sys.argv[2])
app, ctx = seeded_app()
c = app.test_client()
H = login_all(c)
job = Job.query.filter(Job.scheduled_date == date.today()).first()
site_id = job.site_id
r = c.patch(f"/api/sites/{site_id}", json={"latitude": lat, "longitude": lng}, headers=H["dispatcher"])
print(f"PATCH site #{site_id} -> ({lat}, {lng}): HTTP {r.status_code} (the API accepts it: valid coordinates)", flush=True)
t0 = time.time()
r = c.get("/api/map/live", headers=H["dispatcher"])
print(f"GET /api/map/live -> {r.status_code} in {time.time() - t0:.1f}s", flush=True)
t0 = time.time()
r = c.get("/api/map/live", headers=H["dispatcher"])
print(f"GET /api/map/live (2nd call, cached) -> {r.status_code} in {time.time() - t0:.1f}s", flush=True)
