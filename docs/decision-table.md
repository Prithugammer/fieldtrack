# FieldTrack — Clock-in Decision Table

Implemented in `backend/routes/time_entries.py` (`create_time_entry`) using
`backend/geofence.py`.

## 1. Core decision table (as specified)

Conditions are evaluated **in order** — the assignment check happens first, so if the
worker is not assigned the geofence is never checked.

| | Rule 1 | Rule 2 | Rule 3 | Rule 4 |
|---|:---:|:---:|:---:|:---:|
| **C1** Worker is assigned to this job on the clock-in date? | Y | Y | N | N |
| **C2** Clock-in location is within the site's geofence? | Y | N | Y | N |
| **A1** Save the time entry (status = Pending) | ✔ | ✔ | | |
| **A2** Set `is_flagged = true` and write `flag_reason` | | ✔ | | |
| **A3** Reject with HTTP 409 "not assigned" (nothing saved) | | | ✔ | ✔ |

Rules 3 and 4 have the same action, so C2 is a *don't-care* when C1 = N. The reduced table
therefore has three rules:

| | R1 | R2 | R3 |
|---|:---:|:---:|:---:|
| C1 Assigned? | Y | Y | N |
| C2 Within geofence? | Y | N | – |
| Action | Save, not flagged | **Save and flag** | Reject 409 |

**Why flagged entries are still saved:** GPS can be inaccurate, workers sometimes clock in
from the site trailer or parking lot, and the company must pay for time actually worked.
The system therefore never throws away a location-suspicious entry — it flags it and a
supervisor makes the final decision (approve or reject with a reason).

## 2. What "within the geofence" means

```
distance_m = haversine(clock_in_lat, clock_in_lng, site.latitude, site.longitude)
flag       = distance_m > site.geofence_radius_m          (should_flag)
```

- The boundary itself counts as inside: at exactly 200 m with a 200 m radius the entry is **not** flagged.
- 199 m → not flagged; 201 m → flagged.
- Every site has a radius (the column is NOT NULL). A site created without one gets the default
  `GEOFENCE_RADIUS_M = 200`; radii outside 25–5000 m are rejected with HTTP 400.

## 3. Full decision table (all checks performed by the endpoint)

| | R1 | R2 | R3 | R4 | R5 | R6 |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| C1 Required fields present & valid? | N | Y | Y | Y | Y | Y |
| C2 Worker active and role = Worker? | – | N | Y | Y | Y | Y |
| C3 Assigned to job on clock-in date? | – | – | N | Y | Y | Y |
| C4 Overlaps an existing entry for the worker? | – | – | – | Y | N | N |
| C5 Within geofence? | – | – | – | – | Y | N |
| **Action** | 400 + field | 400 `user_id` | 409 not assigned | 409 overlap | **Save** | **Save + flag** |

The same geofence rule (C5) is applied again at clock-out, using the clock-out coordinates;
a clock-out outside the geofence also flags the entry and appends its own reason.
