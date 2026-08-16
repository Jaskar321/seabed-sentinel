"""
Build a PER-SPOT route (lane) model from that spot's own AIS history.
Self-calibrating: it just learns where traffic normally goes at that spot.

    python build_route.py great_belt data/real_bbox.csv [more days ...]
    python build_route.py estlink2  <gulf_of_finland_ais.csv> ...

Writes route_<spot>.joblib. More days = cleaner lanes. Spots live in spots.py.
"""
import sys, os
import seabed
from spots import SPOTS
from model import RouteModel

def main():
    if len(sys.argv) < 2 or sys.argv[1] not in SPOTS:
        print("usage: python build_route.py <spot> <file...>   spots:", ", ".join(SPOTS)); return
    spot = sys.argv[1]
    files = sys.argv[2:] or ["data/real_bbox.csv"]
    bbox = SPOTS[spot]["bbox"]
    rm = RouteModel(bbox)
    total = 0
    for p in files:
        if not os.path.exists(p):
            print("skip (missing):", p); continue
        df = seabed.load_ais_bbox(p, bbox) if os.path.getsize(p) > 200_000_000 else seabed.load_ais(p)
        for _, g in df.groupby("MMSI"):
            rm.update([[float(a), float(b)] for a, b in zip(g.Latitude, g.Longitude)])
            total += 1
    rm.finalize()
    rm.save(f"route_{spot}.joblib")
    print(f"route_{spot}.joblib saved  ({total} tracks over bbox {bbox})")

if __name__ == "__main__":
    main()
