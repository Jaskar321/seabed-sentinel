"""
Seabed Sentinel - interactive app (historic + live modes, click-to-enrich).

    pip install flask pandas numpy paho-mqtt websocket-client requests
    python app.py
    # open http://127.0.0.1:5000

Pick the corridor from the dropdown in the UI (no env var needed):
  great_belt  - Danish waters, matches DMA day-files
  estlink2    - Gulf of Finland, matches the free Digitraffic live feed (real incident area)
"""
import os, threading, datetime
from collections import defaultdict, deque
import pandas as pd
from flask import Flask, jsonify, request, render_template

import seabed
from enrich import enrich
from spots import SPOTS as PRESETS
import geo_layers
import live_sources

def _apply_spot(name):
    """Configure detector for a spot: real cable route (if imported), route model, bathymetry."""
    cfg = PRESETS[name]
    cable = geo_layers.load_saved_cable(name) or cfg["cable"]
    seabed.configure(cable, cfg["buffer"])
    seabed.load_route(name)
    seabed.configure_bathymetry(f"bathy_{name}.tif")
    return cfg

ACTIVE = os.environ.get("CORRIDOR", "great_belt")
if ACTIVE not in PRESETS:
    ACTIVE = "great_belt"
CFG = _apply_spot(ACTIVE)

WINDOW_MIN, PRUNE_MIN = 90, 45
app = Flask(__name__)

LOCK = threading.Lock()
LIVE = dict(feed=None, source=None)
APP = dict(in_bbox=0)
VES = defaultdict(lambda: dict(pts=deque(maxlen=400), static={}))
HIST = dict(rows=[], static={})

def _now():
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)

def rows_to_geojson(rows):
    return dict(type="FeatureCollection", features=[dict(type="Feature",
        geometry=dict(type="LineString", coordinates=[[c[1], c[0]] for c in r["coords"]]),
        properties=dict(mmsi=r["mmsi"], name=r["name"] or f"MMSI {r['mmsi']}",
                        ship_type=r["ship_type"], label=r["label"], score=r["score"],
                        alert=r["alert"], watch=bool(r.get("watch")),
                        ml_anomaly=r.get("ml_anomaly"), route_anomaly=r.get("route_anomaly"),
                        behavior_anomaly=r.get("behavior_anomaly"),
                        factors=r["factors"])) for r in rows])

# ---------------- live feed handling ----------------
def on_msg(msg):
    mmsi = msg.get("mmsi")
    lat, lon = msg.get("lat"), msg.get("lon")
    la0, la1, lo0, lo1 = CFG["bbox"]
    with LOCK:
        v = VES[mmsi]
        for k in ("name", "imo", "callsign", "ship_type", "destination",
                  "length", "width", "draught", "nav_status"):
            if msg.get(k) not in (None, ""):
                v["static"][k] = msg[k]
        v["static"]["mmsi"] = mmsi
        if lat is not None and lon is not None and la0 <= lat <= la1 and lo0 <= lon <= lo1:
            v["pts"].append((msg.get("ts") or _now(), lat, lon,
                             msg.get("sog"), msg.get("cog"), msg.get("heading")))
            APP["in_bbox"] += 1

def _live_dataframe():
    cutoff = _now() - datetime.timedelta(minutes=WINDOW_MIN)
    recs = []
    with LOCK:
        for mmsi, v in list(VES.items()):
            pts = [p for p in v["pts"] if p[0] >= cutoff]
            if len(pts) < 5:
                continue
            st = v["static"]
            for (ts, lat, lon, sog, cog, hdg) in pts:
                recs.append(dict(Timestamp=ts, MMSI=mmsi, Latitude=lat, Longitude=lon,
                                 SOG=sog, COG=cog, Heading=hdg,
                                 **{"Ship type": st.get("ship_type", ""), "Name": st.get("name", "")}))
    if not recs:
        return pd.DataFrame()
    df = pd.DataFrame(recs)
    df["Timestamp"] = pd.to_datetime(df["Timestamp"])
    return df

def _prune():
    cutoff = _now() - datetime.timedelta(minutes=PRUNE_MIN)
    with LOCK:
        for mmsi in [m for m, v in VES.items() if not v["pts"] or v["pts"][-1][0] < cutoff]:
            del VES[mmsi]

# ---------------- routes ----------------
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/config")
def api_config():
    cable = seabed.CABLE
    clat = sum(p[0] for p in cable) / len(cable)
    clon = sum(p[1] for p in cable) / len(cable)
    return jsonify(corridor=ACTIVE, presets=list(PRESETS.keys()), cable=cable,
                   bbox=CFG["bbox"], center=[clat, clon],
                   live=bool(LIVE["feed"]), source=LIVE["source"])

@app.route("/api/corridor", methods=["POST"])
def api_corridor():
    global ACTIVE, CFG
    name = (request.get_json(silent=True) or {}).get("name")
    if name not in PRESETS:
        return jsonify(ok=False, error="unknown corridor"), 400
    with LOCK:
        if LIVE["feed"]:
            LIVE["feed"].stop(); LIVE.update(feed=None, source=None)
        VES.clear(); APP["in_bbox"] = 0
        ACTIVE = name
        CFG = _apply_spot(name)
    return jsonify(ok=True, corridor=name)

@app.route("/api/historic")
def api_historic():
    path = request.args.get("file", "").strip()
    with LOCK:
        if path and os.path.exists(path):
            df = seabed.load_ais_bbox(path, CFG["bbox"])
            df["_b"] = df.Timestamp.dt.floor("30s")
            df = df.drop_duplicates(["MMSI", "_b"]).drop(columns="_b")
        elif os.path.exists("data/real_bbox.csv"):
            df = seabed.load_ais("data/real_bbox.csv")
        else:
            df = seabed.load_ais("data/sample_ais.csv")
        rows = seabed.run_detection(df)
        HIST["rows"] = rows
    return jsonify(mode="historic", geojson=rows_to_geojson(rows),
                   alerts=sum(r["alert"] for r in rows), vessels=len(rows))

@app.route("/api/live/start", methods=["POST"])
def api_live_start():
    body = request.get_json(silent=True) or {}
    source = body.get("source", "digitraffic")
    with LOCK:
        if LIVE["feed"]:
            return jsonify(ok=True, already=True, source=LIVE["source"])
        VES.clear(); APP["in_bbox"] = 0
    try:
        if source == "digitraffic":
            feed = live_sources.DigitrafficFeed(on_msg).start()
        elif source == "aisstream":
            key = body.get("key") or os.environ.get("AISSTREAM_KEY")
            if not key:
                return jsonify(ok=False, error="aisstream needs an API key"), 400
            feed = live_sources.AisstreamFeed(on_msg, key, CFG["bbox"]).start()
        else:
            return jsonify(ok=False, error=f"unknown source {source}"), 400
    except SystemExit as e:
        return jsonify(ok=False, error=str(e)), 500
    with LOCK:
        LIVE.update(feed=feed, source=source)
    return jsonify(ok=True, source=source)

@app.route("/api/live/stop", methods=["POST"])
def api_live_stop():
    with LOCK:
        if LIVE["feed"]:
            LIVE["feed"].stop()
        LIVE.update(feed=None, source=None)
    return jsonify(ok=True)

@app.route("/api/live")
def api_live():
    _prune()
    df = _live_dataframe()
    rows = seabed.run_detection(df) if len(df) else []
    scored = {r["mmsi"]: r for r in rows}
    with LOCK:
        stats = dict(LIVE["feed"].stats) if LIVE["feed"] else {}
        HIST["static"].update({m: v["static"] for m, v in VES.items()})
        tracked, inbox = len(VES), APP["in_bbox"]
        pfeats = []
        for mmsi, v in VES.items():
            if not v["pts"]:
                continue
            _, lat, lon, sog, cog, hdg = v["pts"][-1]
            r = scored.get(mmsi)
            pfeats.append(dict(type="Feature",
                geometry=dict(type="Point", coordinates=[lon, lat]),
                properties=dict(mmsi=mmsi, name=(v["static"].get("name") or f"MMSI {mmsi}"),
                                label=(r["label"] if r else "live"),
                                score=(r["score"] if r else 0),
                                alert=bool(r and r["alert"]),
                                watch=bool(r and r.get("watch")),
                                ml_anomaly=(r.get("ml_anomaly") if r else None))))
    return jsonify(mode="live", source=LIVE["source"], geojson=rows_to_geojson(rows),
                   points=dict(type="FeatureCollection", features=pfeats),
                   alerts=sum(r["alert"] for r in rows), vessels=len(rows),
                   tracked=tracked, in_bbox=inbox,
                   rx=stats.get("rx", 0), parsed=stats.get("parsed", 0),
                   meta=stats.get("meta", 0),
                   connected=stats.get("connected", False), last_error=stats.get("last_error"))

@app.route("/api/vessel/<int:mmsi>")
def api_vessel(mmsi):
    with LOCK:
        st = dict(VES[mmsi]["static"]) if mmsi in VES else {}
        if not st:
            st = HIST["static"].get(mmsi, {"mmsi": mmsi})
    return jsonify(enrich(st))

if __name__ == "__main__":
    print(f"corridor: {ACTIVE}  cable={CFG['cable']}  bbox={CFG['bbox']}")
    print("open http://127.0.0.1:5000   (switch corridor from the dropdown in the UI)")
    app.run(host="127.0.0.1", port=5000, threaded=True, debug=False)
