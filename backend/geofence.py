"""Geofence rules for FieldTrack.

These are *pure functions*: they take numbers and return numbers/booleans, with no database
access, so they are easy to test and easy to explain.

THE GEOFENCE RULE
-----------------
Every job site has a centre point (latitude, longitude) and a radius in metres (default 200).
Picture a circle drawn on the map around the site. When a time entry is recorded we take the
GPS coordinates the worker's phone reported and measure the straight-line distance from the
site centre:

    * distance <= radius  -> the worker was on site, entry is saved normally
    * distance >  radius  -> the entry is STILL SAVED, but it is flagged for a supervisor
                             to review, with a reason like "Clock-in 512 m from site (limit 200 m)"

We never throw an entry away for being outside the circle: GPS drifts, people clock in from
the site trailer, and the company must pay for time actually worked. A human decides.
"""

import math

# Mean radius of the Earth in metres (the value used by most GPS/haversine calculators).
EARTH_RADIUS_M = 6_371_000


def haversine(lat1, lng1, lat2, lng2):
    """Return the great-circle distance in metres between two latitude/longitude points.

    The Earth is round, so we can't use Pythagoras on raw degrees (a degree of longitude
    shrinks as you move away from the equator). The haversine formula measures the distance
    along the surface of a sphere:

        a = sin²(Δφ/2) + cos φ1 · cos φ2 · sin²(Δλ/2)
        d = 2R · asin(√a)

    where φ is latitude and λ is longitude, both in radians, and R is the Earth's radius.
    """
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lng2 - lng1)

    a = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    )
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def should_flag(distance_m, radius_m):
    """Return True when a location is OUTSIDE the geofence and must be flagged.

    The boundary counts as inside: exactly 200 m from a site with a 200 m radius is fine,
    199 m is fine, 201 m is flagged.
    """
    return distance_m > radius_m
