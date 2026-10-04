"""Kathmandu Valley geography for the Live Map simulation.

Real landmark coordinates are used as road waypoints and job-site anchors so the simulated
worker routes look grounded on the map. Nothing here touches the database.
"""
import math
import random

# Map view for the Live Map page (south, west, north, east).
KATHMANDU_VALLEY_BOUNDS = {"south": 27.60, "west": 85.20, "north": 27.80, "east": 85.45}

# name -> (lat, lng)
LANDMARKS = {
    "Kathmandu Durbar Square": (27.7049, 85.3077),
    "Patan Durbar Square": (27.6730, 85.3246),
    "Bhaktapur Durbar Square": (27.6710, 85.4298),
    "Boudhanath": (27.7215, 85.3620),
    "Kirtipur": (27.6773, 85.2870),
    "Koteshwor": (27.6775, 85.3485),
    "Kalanki": (27.6939, 85.2816),
    "Chabahil": (27.7215, 85.3467),
    "Jawalakhel": (27.6710, 85.3130),
    "Gongabu": (27.7360, 85.3180),
    "Thimi": (27.6805, 85.3920),
    "Sankhu": (27.7460, 85.4480),
}

# Busy junctions. A worker travelling within `radius_m` of one moves at
# `speed_multiplier` x normal speed (0.3 = 30% speed, i.e. the segment takes 3.3x longer).
TRAFFIC_HOTSPOTS = {
    "Koteshwor": {"radius_m": 700, "speed_multiplier": 0.25},
    "Kalanki": {"radius_m": 650, "speed_multiplier": 0.3},
    "Chabahil": {"radius_m": 550, "speed_multiplier": 0.35},
    "Gongabu": {"radius_m": 600, "speed_multiplier": 0.3},
}

METRES_PER_DEGREE_LAT = 111_195


def random_point_near(lat, lng, max_offset_km, rng=None):
    """Return (lat, lng) uniformly inside a circle of max_offset_km around the point.

    Pass a seeded random.Random as `rng` for a repeatable result.
    """
    rng = rng or random
    distance_m = max_offset_km * 1000 * math.sqrt(rng.random())
    bearing = rng.uniform(0, 2 * math.pi)
    d_lat = distance_m * math.cos(bearing) / METRES_PER_DEGREE_LAT
    d_lng = distance_m * math.sin(bearing) / (METRES_PER_DEGREE_LAT * math.cos(math.radians(lat)))
    return round(lat + d_lat, 6), round(lng + d_lng, 6)
