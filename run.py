"""
Seabed Sentinel - Phase 1 runner.
Point it at ANY AIS CSV in the DMA schema (real or the self-test sample).

    python run.py <ais_csv>            # e.g. real:  python run.py aisdk-2024-12-25.csv
    python run.py                      # defaults to the self-test sample

Outputs:  demo_map.html   (interactive map)   +   alerts.csv   (flagged vessels)
"""
import sys, csv
from seabed import run_detection
from build_map import build_map

def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "data/sample_ais.csv"
    rows = run_detection(path)
    alerts = [r for r in rows if r["alert"]]

    with open("alerts.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["mmsi", "name", "ship_type", "label", "score",
                    "min_cable_km", "slow_moving_km", "hdg_cog_mismatch",
                    "max_gap_min", "factors"])
        for r in rows:
            if r["alert"]:
                w.writerow([r["mmsi"], r["name"], r["ship_type"], r["label"],
                            r["score"], r["min_cable_km"], r["slow_moving_km"],
                            r["hdg_cog_mismatch"], r["max_gap_min"],
                            " | ".join(r["factors"])])

    out = build_map(rows)
    print(f"vessels analysed : {len(rows)}")
    print(f"alerts           : {len(alerts)}")
    for r in alerts:
        print(f"  [{r['label']}] {r['name']} ({r['ship_type']})  score={r['score']}")
    print(f"map              : {out}")
    print(f"alerts table     : alerts.csv")

if __name__ == "__main__":
    main()
