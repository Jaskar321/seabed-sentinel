"""
Seabed Sentinel - REAL Danish AIS runner.
Streams a full multi-GB DMA day-file, keeps only vessels near a chosen cable
corridor, thins to ~1 fix / 30 s, runs the detector, and writes the map.

    python run_real.py "C:\\path\\to\\aisdk-2026-06-26.csv"

Outputs:  demo_map_real.html   +   alerts_real.csv   +   data/real_bbox.csv
(the last one is the small bbox-filtered slice - share it back for tuning.)

EDIT the corridor below to your target cable. The default is the Great Belt
(Storebaelt) chokepoint in Danish waters - dense traffic, real HVDC power link.
Replace the waypoints with the exact route (e.g. from EMODnet Human Activities).
"""
import sys, csv, os
import pandas as pd
import seabed
from build_map import build_map

# ---- corridor (EDIT ME) : Great Belt Power Link, Denmark (approx) ----
CABLE    = [(55.33, 10.93), (55.35, 11.12)]        # cable waypoints (lat, lon)
BUFFER_M = 2500.0                                   # corridor half-width (m)
BBOX     = (55.15, 55.55, 10.75, 11.30)             # lat_min, lat_max, lon_min, lon_max

def main():
    if len(sys.argv) < 2:
        print('usage: python run_real.py "path\\to\\aisdk-YYYY-MM-DD.csv"'); return
    path = sys.argv[1]
    if not os.path.exists(path):
        print(f"file not found: {path}"); return

    seabed.configure(CABLE, BUFFER_M)
    os.makedirs("data", exist_ok=True)

    print(f"streaming + bbox-filtering: {path}")
    df = seabed.load_ais_bbox(path, BBOX)

    # thin to ~1 fix / 30 s per vessel (vectorised) - keeps it fast
    before = len(df)
    df["_b"] = df.Timestamp.dt.floor("30s")
    df = df.drop_duplicates(["MMSI", "_b"]).drop(columns="_b")
    print(f"thinned {before:,} -> {len(df):,} fixes")
    df.drop(columns=[c for c in ['_b'] if c in df]).to_csv("data/real_bbox.csv", index=False)

    rows = seabed.run_detection(df)
    alerts = [r for r in rows if r["alert"]]

    with open("alerts_real.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["mmsi", "name", "ship_type", "label", "score", "min_cable_km",
                    "slow_moving_km", "hdg_cog_mismatch", "max_gap_min", "factors"])
        for r in alerts:
            w.writerow([r["mmsi"], r["name"], r["ship_type"], r["label"], r["score"],
                        r["min_cable_km"], r["slow_moving_km"], r["hdg_cog_mismatch"],
                        r["max_gap_min"], " | ".join(r["factors"])])

    build_map(rows, out="demo_map_real.html",
              title=f"Seabed Sentinel — real DMA AIS ({os.path.basename(path)})")

    print(f"\nvessels analysed : {len(rows)}")
    print(f"alerts           : {len(alerts)}")
    for r in alerts[:25]:
        print(f"  [{r['label']}] {r['name'] or r['mmsi']} ({r['ship_type']})  score={r['score']}")
    print("\nmap   : demo_map_real.html")
    print("table : alerts_real.csv")
    print("slice : data/real_bbox.csv  (small - send this back for tuning)")
    print("\nNOTE: on a normal day expect few/zero drag alerts (that's the point -")
    print("low false-positive rate). DARK/AIS-GAP hits often just mean a vessel")
    print("left AIS range or the bbox edge; trust ANCHOR-DRAG first, vet DARK.")

if __name__ == "__main__":
    main()
