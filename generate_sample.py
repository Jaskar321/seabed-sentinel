"""
Generate a realistic synthetic Gulf-of-Finland AIS dataset in the DMA schema.
Scenario models the Estlink-2 corridor: normal transit lanes, slow/erratic
fishing vessels (the false-positive stressor), one anchor-drag vessel, and one
vessel that drops AIS over the cable (Phase-2 hook).

Deterministic (fixed seed) so results are reproducible.
"""
import math
import numpy as np
import pandas as pd

rng = np.random.default_rng(42)
REF_LAT = 59.8
MPD_LAT = 111320.0
MPD_LON = 111320.0 * math.cos(math.radians(REF_LAT))
T0 = pd.Timestamp("2024-12-25 00:00:00")
KN = 0.514444  # m/s per knot

rows = []
def emit(ts, mmsi, lat, lon, navstat, sog, cog, hdg, stype, name):
    rows.append(dict(Timestamp=ts.strftime("%d/%m/%Y %H:%M:%S"), MMSI=mmsi,
                     Latitude=round(lat, 6), Longitude=round(lon, 6),
                     **{"Navigational status": navstat}, SOG=round(sog, 1),
                     COG=round(cog % 360, 1), Heading=round(hdg % 360, 1),
                     **{"Ship type": stype}, Name=name))

def step(lat, lon, bearing_deg, dist_m):
    th = math.radians(bearing_deg)
    return lat + dist_m * math.cos(th) / MPD_LAT, lon + dist_m * math.sin(th) / MPD_LON

def vessel(mmsi, name, stype, lat, lon, bearing, sog_kn, navstat, n=240, dt=30,
           bearing_jitter=0.0, hdg_offset=0.0, sog_jitter=0.0, drop=None):
    """Lay down a track. drop=(start_idx,end_idx) omits points (AIS gap)."""
    for i in range(n):
        ts = T0 + pd.Timedelta(seconds=i * dt)
        b = bearing + (rng.normal(0, bearing_jitter) if bearing_jitter else 0.0)
        s = max(0.0, sog_kn + (rng.normal(0, sog_jitter) if sog_jitter else 0.0))
        if not (drop and drop[0] <= i < drop[1]):
            emit(ts, mmsi, lat, lon, navstat, s, b, b + hdg_offset, stype, name)
        lat, lon = step(lat, lon, b, s * KN * dt)
    return lat, lon

# ---- 40 normal transit vessels along the E-W Gulf lane (~14 kn, straight) ----
types = ["Cargo", "Tanker", "Passenger", "Cargo", "Cargo"]
for k in range(40):
    lat0 = 59.88 + rng.normal(0, 0.04)
    if k % 2 == 0:          # eastbound
        lon0, brg = 24.55 + rng.normal(0, 0.05), 95 + rng.normal(0, 4)
    else:                   # westbound
        lon0, brg = 27.05 + rng.normal(0, 0.05), 275 + rng.normal(0, 4)
    vessel(200000000 + k, f"TRANSIT_{k:02d}", types[k % len(types)],
           lat0, lon0, brg, sog_kn=13 + rng.uniform(0, 4), navstat="Under way using engine",
           n=int(rng.integers(180, 240)), bearing_jitter=1.5, sog_jitter=0.4)

# ---- 5 fishing vessels: slow, erratic loops, NOT near the cable ----
for k in range(5):
    lat, lon = 59.66 + rng.normal(0, 0.03), 25.05 + rng.normal(0, 0.05)
    mmsi, name = 230000000 + k, f"FISHER_{k:02d}"
    brg = rng.uniform(0, 360)
    for i in range(220):
        ts = T0 + pd.Timedelta(seconds=i * 30)
        brg += rng.normal(0, 35)                # wander -> loops, low straightness
        s = 2.5 + rng.uniform(-1, 1.5)
        emit(ts, mmsi, lat, lon, "Engaged in fishing", s, brg, brg + rng.normal(0, 10),
             "Fishing", name)
        lat, lon = step(lat, lon, brg, s * KN * 30)

# ---- 1 anchor-drag suspect: slow, crosses cable, hull crabbed off track ----
# starts just E of the cable, drags WSW slowly across it (~1.8 kn) for ~14 km
vessel(111000111, "SHADOW TRADER", "Cargo", 59.97, 25.95, bearing=250,
       sog_kn=1.8, navstat="Under way using engine", n=520, dt=30,
       bearing_jitter=10.0, hdg_offset=35.0, sog_jitter=0.4)

# ---- 1 dark vessel: transits ~12 kn over the cable but drops AIS across it ----
vessel(111000222, "GHOST RUNNER", "Cargo", 60.02, 25.95, bearing=200,
       sog_kn=12.0, navstat="Under way using engine", n=200, dt=30,
       bearing_jitter=1.0, hdg_offset=0.0, sog_jitter=0.3, drop=(70, 150))

df = pd.DataFrame(rows, columns=["Timestamp", "MMSI", "Latitude", "Longitude",
      "Navigational status", "SOG", "COG", "Heading", "Ship type", "Name"])
df.to_csv("data/sample_ais.csv", index=False)
print(f"wrote data/sample_ais.csv  rows={len(df)}  vessels={df.MMSI.nunique()}")
