"""
Train the GLOBAL behaviour model (portable across all spots).

    python train_behavior.py data/real_bbox.csv [more day-files / spot slices ...]

Pass as many normal days AND as many different waterways as you can - diversity
is what makes the behaviour model transfer to new spots. Writes behavior_model.joblib.
"""
import sys, os
import seabed
from model import BehaviorModel

def load_any(path):
    if os.path.getsize(path) > 200_000_000:               # raw DMA day-file
        df = seabed.load_ais_bbox(path, (53.0, 66.0, 9.0, 30.0))   # whole Baltic-ish
        df["_b"] = df.Timestamp.dt.floor("30s")
        return df.drop_duplicates(["MMSI", "_b"]).drop(columns="_b")
    return seabed.load_ais(path)

def main():
    files = sys.argv[1:] or ["data/real_bbox.csv"]
    feats = []
    for p in files:
        if not os.path.exists(p):
            print("skip (missing):", p); continue
        rows = seabed.run_detection(load_any(p))
        print(f"{p}: {len(rows)} tracks")
        feats.extend(rows)
    if not feats:
        print("no data"); return
    BehaviorModel().fit(feats).save()
    print(f"behavior_model.joblib saved  ({len(feats)} tracks pooled from {len(files)} file(s))")

if __name__ == "__main__":
    main()
