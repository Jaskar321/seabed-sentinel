"""
Seabed Sentinel - Phase 1 pipeline
Ingest AIS -> build tracks -> movement features -> classify -> anchor-drag anomaly score.

Reads the Danish Maritime Authority (DMA) AIS CSV schema. Works on the small
self-test sample (load_ais) and on real multi-GB DMA day-files via a chunked,
bounding-box filtered loader (load_ais_bbox). Call configure() to point the
detector at a real cable corridor.

Tuned on real Danish AIS (2026-06-26, Great Belt):
  - anchor-drag requires a cable-capable vessel (not leisure/sail; size >= 40 m
    when known) that is genuinely slow (median <= 4.5 kn) -> rejects sailboats
  - dark/AIS-gap requires the vessel to be underway (real transit), not moored
  - heading/course statistics are computed only over moving segments, so a
    stationary vessel's GPS jitter no longer fakes "crabbing / erratic course"
"""
import math
import numpy as np
import pandas as pd

# ---- Corridor / projection state (defaults = Gulf of Finland self-test) ----
REF_LAT, REF_LON = 59.8, 25.9
CABLE = [(60.20, 25.40), (59.47, 26.42)]     # cable route waypoints (lat, lon)
BUFFER_M = 2000.0                            # protection corridor half-width (m)

_MPD_LAT = 111320.0
_MPD_LON = 111320.0 * math.cos(math.radians(REF_LAT))
_CABLE_XY = None

# vessel types that physically cannot drag an anchor through a subsea cable
LEISURE = {"sailing", "pleasure", "pleasure craft", "port tender", "diving", "sar",
           "wing in grnd", "fishing", "other", "medical", "law enforcement",
           "pilot", "spare", "wig"}

DRAGGABLE_MAX_DEPTH = 100.0   # m; deeper than this an anchor can't realistically reach the seabed
_BATHY = None

def configure_bathymetry(path):
    """Load an EMODnet DTM GeoTIFF for the depth-gate (None disables it)."""
    global _BATHY
    try:
        import os
        from geo_layers import Bathymetry
        _BATHY = Bathymetry(path) if path and os.path.exists(path) else None
    except Exception:
        _BATHY = None
    return _BATHY

def configure(cable, buffer_m=2000.0):
    """Point the detector at a real corridor; recentres the local projection."""
    global CABLE, BUFFER_M, REF_LAT, REF_LON, _MPD_LAT, _MPD_LON, _CABLE_XY
    CABLE = list(cable)
    BUFFER_M = float(buffer_m)
    REF_LAT = sum(p[0] for p in cable) / len(cable)
    REF_LON = sum(p[1] for p in cable) / len(cable)
    _MPD_LAT = 111320.0
    _MPD_LON = 111320.0 * math.cos(math.radians(REF_LAT))
    _CABLE_XY = [to_xy(*p) for p in CABLE]

# ---------- geometry helpers (local equirectangular projection, meters) ----------
def to_xy(lat, lon):
    return (lon - REF_LON) * _MPD_LON, (lat - REF_LAT) * _MPD_LAT

def _circ_diff(a, b):
    return abs((a - b + 180.0) % 360.0 - 180.0)

def _circ_std(deg):
    deg = np.asarray(deg, float)
    deg = deg[np.isfinite(deg)]
    if len(deg) == 0:
        return 0.0
    r = math.radians(1.0)
    c = np.cos(deg * r).mean(); s = np.sin(deg * r).mean()
    R = math.hypot(c, s)
    return 0.0 if R >= 1.0 else math.degrees(math.sqrt(-2.0 * math.log(max(R, 1e-9))))

def _seg_point_dist(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    if L2 == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))

def _segments_cross(p1, p2, p3, p4):
    def ccw(a, b, c):
        return (c[1] - a[1]) * (b[0] - a[0]) - (b[1] - a[1]) * (c[0] - a[0])
    d1 = ccw(p3, p4, p1); d2 = ccw(p3, p4, p2)
    d3 = ccw(p1, p2, p3); d4 = ccw(p1, p2, p4)
    return ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0))

def _cable_xy():
    global _CABLE_XY
    if _CABLE_XY is None:
        _CABLE_XY = [to_xy(*p) for p in CABLE]
    return _CABLE_XY

def dist_to_cable_m(lat, lon):
    px, py = to_xy(lat, lon)
    cxy = _cable_xy()
    return min(_seg_point_dist(px, py, *cxy[i], *cxy[i + 1]) for i in range(len(cxy) - 1))

# ---------- IO ----------
DMA_COLS = ["Timestamp", "MMSI", "Latitude", "Longitude", "Navigational status",
            "SOG", "COG", "Heading", "Ship type", "Name", "Length", "Width"]

def _clean_cols(df):
    df.columns = [c.strip().lstrip("#").strip() for c in df.columns]
    return df

def _parse_time(s):
    return pd.to_datetime(s, format="mixed", dayfirst=True, errors="coerce")

def load_ais(path):
    """Load a small DMA-schema AIS CSV (self-test sample or an already-trimmed file)."""
    df = _clean_cols(pd.read_csv(path))
    keep = [c for c in DMA_COLS if c in df.columns]
    df = df[keep].copy()
    df["Timestamp"] = _parse_time(df["Timestamp"])
    for c in ["Latitude", "Longitude", "SOG", "COG", "Heading", "Length", "Width"]:
        if c in df:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["Timestamp", "MMSI", "Latitude", "Longitude"])
    df = df[df.Latitude.between(-90, 90) & df.Longitude.between(-180, 180)]
    return df.sort_values(["MMSI", "Timestamp"]).reset_index(drop=True)

def load_ais_bbox(path, bbox, chunksize=1_000_000, verbose=True):
    """Stream a real multi-GB DMA day-file, keeping only rows inside bbox.
    bbox = (lat_min, lat_max, lon_min, lon_max). Returns a clean DataFrame."""
    lat0, lat1, lon0, lon1 = bbox
    want = set(DMA_COLS) | {"Type of mobile"}
    parts, total, kept = [], 0, 0
    reader = pd.read_csv(path, chunksize=chunksize, low_memory=False,
                         encoding="latin-1", on_bad_lines="skip")
    for i, chunk in enumerate(reader):
        chunk = _clean_cols(chunk)
        total += len(chunk)
        if "Type of mobile" in chunk:
            chunk = chunk[chunk["Type of mobile"].astype(str).str.contains("Class", na=False)]
        for c in ["Latitude", "Longitude", "SOG", "COG", "Heading", "Length", "Width"]:
            if c in chunk:
                chunk[c] = pd.to_numeric(chunk[c], errors="coerce")
        chunk = chunk.dropna(subset=["Latitude", "Longitude", "MMSI"])
        chunk = chunk[chunk.Latitude.between(lat0, lat1) & chunk.Longitude.between(lon0, lon1)]
        if len(chunk):
            parts.append(chunk[[c for c in want if c in chunk.columns]])
            kept += len(chunk)
        if verbose and i % 5 == 0:
            print(f"  chunk {i}: scanned {total:,} rows, kept {kept:,} in bbox", flush=True)
    if not parts:
        raise SystemExit("No rows inside the bounding box - check BBOX vs the file's area.")
    df = pd.concat(parts, ignore_index=True)
    df["Timestamp"] = _parse_time(df["Timestamp"])
    df = df.dropna(subset=["Timestamp"])
    if verbose:
        print(f"  done: {kept:,} rows / {df.MMSI.nunique()} vessels in bbox")
    return df.sort_values(["MMSI", "Timestamp"]).reset_index(drop=True)

# ---------- feature extraction per vessel track ----------
def track_features(g):
    g = g.sort_values("Timestamp")
    lat = g.Latitude.to_numpy(); lon = g.Longitude.to_numpy()
    t = g.Timestamp.to_numpy()
    hdg = g.Heading.to_numpy() if "Heading" in g else np.full(len(g), np.nan)
    sog = g.SOG.to_numpy() if "SOG" in g else np.full(len(g), np.nan)
    length = None
    if "Length" in g and pd.notna(g.Length.iloc[0]):
        try: length = float(g.Length.iloc[0])
        except Exception: length = None
    xy = [to_xy(a, b) for a, b in zip(lat, lon)]
    cxy = _cable_xy()
    n = len(g)

    m = max(n - 1, 0)
    seg_d = np.zeros(m); seg_dt = np.zeros(m)
    seg_cog = np.full(m, np.nan); seg_mis = np.full(m, np.nan)
    gap_near, max_gap_min = False, 0.0
    for i in range(1, n):
        x0, y0 = xy[i - 1]; x1, y1 = xy[i]
        seg_d[i - 1] = math.hypot(x1 - x0, y1 - y0)
        dt = (t[i] - t[i - 1]) / np.timedelta64(1, "s")
        seg_dt[i - 1] = float(dt) if dt == dt else 0.0
        cog = math.degrees(math.atan2(x1 - x0, y1 - y0)) % 360.0
        seg_cog[i - 1] = cog
        if hdg[i] == hdg[i]:
            seg_mis[i - 1] = _circ_diff(hdg[i], cog)
        gap_min = seg_dt[i - 1] / 60.0
        max_gap_min = max(max_gap_min, gap_min)
        if gap_min > 20.0:
            mx, my = (x0 + x1) / 2, (y0 + y1) / 2
            dd = min(_seg_point_dist(mx, my, *cxy[k], *cxy[k + 1]) for k in range(len(cxy) - 1))
            if dd < BUFFER_M or any(_segments_cross((x0, y0), (x1, y1), cxy[k], cxy[k + 1])
                                    for k in range(len(cxy) - 1)):
                gap_near = True

    path_m = seg_d.sum()
    net_m = math.hypot(*(np.subtract(xy[-1], xy[0]))) if n > 1 else 0.0
    straightness = net_m / path_m if path_m > 0 else 0.0
    with np.errstate(divide="ignore", invalid="ignore"):
        seg_kn = np.where(seg_dt > 0, seg_d / seg_dt / 0.514444, 0.0)
    moving = seg_kn > 1.0
    slow_moving_km = seg_d[(seg_kn >= 0.5) & (seg_kn <= 4.0)].sum() / 1000.0
    sog_median = float(np.nanmedian(sog)) if np.isfinite(sog).any() else float(np.nanmedian(seg_kn))
    moving_speed_med = float(np.median(seg_kn[moving])) if moving.any() else 0.0
    # heading/course stats ONLY over moving segments -> no jitter from moored boats
    cog_std = _circ_std(seg_cog[moving]) if moving.any() else 0.0
    mis_moving = seg_mis[moving]
    hdg_cog_mismatch = float(np.nanmedian(mis_moving)) if np.isfinite(mis_moving).any() else 0.0

    near_lat, near_lon, near_m = lat[0], lon[0], math.inf
    for a, b in zip(lat, lon):
        dm = dist_to_cable_m(a, b)
        if dm < near_m:
            near_m, near_lat, near_lon = dm, a, b
    min_cable_km = near_m / 1000.0
    crosses = any(_segments_cross(xy[i - 1], xy[i], cxy[k], cxy[k + 1])
                  for i in range(1, n) for k in range(len(cxy) - 1))

    return dict(
        mmsi=int(g.MMSI.iloc[0]),
        name=str(g.Name.iloc[0]) if "Name" in g and pd.notna(g.Name.iloc[0]) else "",
        ship_type=str(g["Ship type"].iloc[0]) if "Ship type" in g and pd.notna(g["Ship type"].iloc[0]) else "",
        length=length, n=len(g), sog_median=round(sog_median, 2),
        moving_speed_med=round(moving_speed_med, 2),
        path_km=round(path_m / 1000, 2), straightness=round(straightness, 3),
        slow_moving_km=round(slow_moving_km, 2), cog_std=round(cog_std, 1),
        hdg_cog_mismatch=round(hdg_cog_mismatch, 1),
        min_cable_km=round(min_cable_km, 2), enters_buffer=bool(min_cable_km * 1000.0 < BUFFER_M),
        near=[float(near_lat), float(near_lon)],
        crosses_cable=bool(crosses), max_gap_min=round(max_gap_min, 1),
        gap_near_cable=bool(gap_near),
        coords=[[float(a), float(b)] for a, b in zip(lat, lon)],
    )

# ---------- classify + score ----------
def classify_and_score(f):
    st = str(f["ship_type"] or "").strip().lower()
    # LEISURE by name, or by AIS numeric type code (30 fishing, 36 sailing, 37 pleasure)
    small = st in LEISURE or st in {"30", "36", "37"}
    length = f.get("length")
    big_enough = (length is None) or (length >= 40.0)
    cable_capable = (not small) and big_enough
    underway = f["moving_speed_med"] >= 3.0 and f["path_km"] >= 5.0

    factors, score = [], 0.0
    slow_directional = (f["slow_moving_km"] >= 8.0 and f["straightness"] >= 0.30
                        and f["sog_median"] <= 4.5)
    if slow_directional:
        score += 0.30; factors.append(f"sustained slow travel {f['slow_moving_km']} km in drag-speed band (1-4 kn)")
    if f["enters_buffer"]:
        score += 0.20; factors.append(f"enters {int(BUFFER_M)} m cable corridor (min {f['min_cable_km']} km)")
    if f["crosses_cable"]:
        score += 0.15; factors.append("track crosses the cable route")
    if f["hdg_cog_mismatch"] >= 25.0:
        score += 0.20; factors.append(f"heading vs course mismatch {f['hdg_cog_mismatch']} deg while moving (crabbing / dragged)")
    if 15.0 <= f["cog_std"] <= 120.0 and f["moving_speed_med"] < 6:
        score += 0.15; factors.append(f"erratic course (cog std {f['cog_std']} deg) at low speed")
    if f["gap_near_cable"] and underway:
        score += 0.45; factors.append(f"AIS gap {f['max_gap_min']} min over the corridor while underway (went dark)")
    score = min(score, 1.0)

    if f["gap_near_cable"] and f["max_gap_min"] > 20 and underway and cable_capable:
        label = "DARK / AIS GAP"
    elif slow_directional and score >= 0.6 and cable_capable:
        label = "ANCHOR-DRAG SUSPECT"
    elif small or f["ship_type"].lower().startswith("fish") or (f["sog_median"] < 5 and f["straightness"] < 0.3):
        label = "leisure/fishing"
    elif f["sog_median"] >= 8:
        label = "transit"
    elif f["sog_median"] < 0.3:
        label = "stopped"
    else:
        label = "other"

    return dict(label=label, score=round(score, 2), factors=factors,
                alert=label in ("ANCHOR-DRAG SUSPECT", "DARK / AIS GAP"))

_BEHAVIOR = "unset"      # global, portable behaviour model
_ROUTE = None            # per-spot route model for the active corridor

def _behavior():
    global _BEHAVIOR
    if _BEHAVIOR == "unset":
        try:
            import os
            from model import BehaviorModel
            _BEHAVIOR = BehaviorModel.load() if os.path.exists("behavior_model.joblib") else None
        except Exception:
            _BEHAVIOR = None
    return _BEHAVIOR

def load_route(spot_name):
    """Load the per-spot route model route_<spot>.joblib (None if not built yet)."""
    global _ROUTE
    try:
        import os
        from model import RouteModel
        p = f"route_{spot_name}.joblib"
        _ROUTE = RouteModel.load(p) if os.path.exists(p) else None
    except Exception:
        _ROUTE = None
    return _ROUTE

def run_detection(source, min_points=5):
    """source: a CSV path (small file) or an already-loaded DataFrame."""
    df = source if isinstance(source, pd.DataFrame) else load_ais(source)
    rows = []
    for _, g in df.groupby("MMSI"):
        if len(g) < min_points:
            continue
        f = track_features(g)
        f.update(classify_and_score(f))
        if _BATHY is not None:                     # bathymetry depth-gate
            try:
                d = _BATHY.depth_at(*f["near"])
            except Exception:
                d = None
            f["depth_m"] = round(d, 1) if d is not None else None
            if d is not None and d > DRAGGABLE_MAX_DEPTH and f["label"] == "ANCHOR-DRAG SUSPECT":
                f["label"] = "other"; f["alert"] = False
                f["factors"].append(f"water {d:.0f} m deep at closest approach — too deep to drag an anchor")
        rows.append(f)

    B, R = _behavior(), _ROUTE
    for r in rows:
        if B is not None:
            try: r["behavior_anomaly"] = round(B.anomaly(r), 3)
            except Exception: pass
        if R is not None:
            try: r["route_anomaly"] = round(R.anomaly(r["coords"]), 3)
            except Exception: pass
        r["ml_anomaly"] = round(max(r.get("route_anomaly", 0.0) or 0.0,
                                    r.get("behavior_anomaly", 0.0) or 0.0), 3)
        st = str(r.get("ship_type") or "").strip().lower()
        small = st in LEISURE or st in {"30", "36", "37"}
        # ML watchlist: route deviation near the cable, on a vessel the rules did
        # NOT alert and that isn't obvious leisure. Advisory ranking, not an alert.
        r["watch"] = bool((not r["alert"]) and (r.get("route_anomaly", 0.0) or 0.0) >= 0.5
                          and r["min_cable_km"] <= 5.0 and not small)
    rows.sort(key=lambda r: (-r["alert"], -(r.get("watch") or False), -r["score"]))
    return rows

if __name__ == "__main__":
    import sys
    for r in run_detection(sys.argv[1] if len(sys.argv) > 1 else "data/sample_ais.csv"):
        tag = "  <== ALERT" if r["alert"] else ""
        print(f'{r["name"]:<16} {r["ship_type"]:<12} {r["label"]:<20} score={r["score"]}{tag}')
