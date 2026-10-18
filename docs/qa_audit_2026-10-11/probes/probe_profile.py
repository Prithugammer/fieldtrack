import cProfile
import io
import logging
import pstats
import sys
from datetime import date

sys.path.insert(0, ".")
logging.disable(logging.CRITICAL)
import simulation  # noqa: E402

# a ~140 km commute: start near the Valley, finish in Pokhara
start_lat, start_lng = 27.7172, 85.3240
end = (28.2096, 83.9856)
pr = cProfile.Profile()
pr.enable()
route = simulation._build_route(8, date.today(), *end)
pr.disable()
s = io.StringIO()
pstats.Stats(pr, stream=s).sort_stats("cumulative").print_stats(8)
print("\n".join(l for l in s.getvalue().splitlines() if l.strip())[:1800])
print("pieces:", len(route["pieces"]), "| route length km:", round(route["length_m"] / 1000, 1), "| base_minutes:", route["base_minutes"], "| PIECE_M:", simulation.PIECE_M)
