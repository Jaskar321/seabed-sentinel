"""
Live AIS feed connectors. Each runs in a background thread and calls
handler(msg) with a NORMALISED dict:
  {mmsi, ts, lat, lon, sog, cog, heading, name, ship_type, imo,
   callsign, destination, nav_status, length, width, draught}

Each feed exposes .stats = {source, rx, parsed, connected, last_error}
so the app/UI can show what's actually happening.

Sources:
  DigitrafficFeed  - free, no API key, MQTT-over-WebSocket, Finnish / Gulf of Finland
  AisstreamFeed    - free API key, global, WebSocket JSON
"""
import json, threading, datetime

def _now():
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)

def _ts_epoch(sec):
    try:
        return datetime.datetime.utcfromtimestamp(float(sec))
    except Exception:
        return _now()


class DigitrafficFeed:
    """Finnish Fintraffic Digitraffic marine AIS. wss://meri.digitraffic.fi:443/mqtt
    Topic vessels-v2/<mmsi>/locations, flat JSON payload {lat,lon,sog,cog,heading,time}."""
    HOST, PORT, PATH = "meri.digitraffic.fi", 443, "/mqtt"

    def __init__(self, handler, topic="vessels-v2/#"):
        self.handler, self.topic = handler, topic
        self._client, self._thread, self.meta = None, None, {}
        self.stats = {"source": "digitraffic", "rx": 0, "parsed": 0, "meta": 0,
                      "connected": False, "last_error": None}

    def start(self):
        try:
            import paho.mqtt.client as mqtt
        except ImportError:
            raise SystemExit("pip install paho-mqtt")
        try:
            c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, transport="websockets")
        except Exception:
            c = mqtt.Client(transport="websockets")
        c.ws_set_options(path=self.PATH)
        c.tls_set()

        def on_connect(cl, u, flags, rc, *a):
            ok = int(getattr(rc, "value", rc)) == 0
            self.stats["connected"] = ok
            if not ok:
                self.stats["last_error"] = f"connect rc={rc}"
            cl.subscribe(self.topic)

        def on_disconnect(cl, u, *a):
            self.stats["connected"] = False

        c.on_connect, c.on_disconnect, c.on_message = on_connect, on_disconnect, self._on_message
        try:
            c.connect(self.HOST, self.PORT, keepalive=60)
        except Exception as e:
            self.stats["last_error"] = f"connect failed: {e}"
            raise SystemExit(f"digitraffic connect failed: {e}")
        self._client = c
        self._thread = threading.Thread(target=c.loop_forever, daemon=True)
        self._thread.start()
        return self

    def _on_message(self, client, userdata, m):
        self.stats["rx"] += 1
        parts = m.topic.split("/")
        if len(parts) < 3 or not parts[1].isdigit():
            return  # skip vessels-v2/status and other non-vessel topics
        try:
            mmsi = int(parts[1]); kind = parts[2]
            p = json.loads(m.payload.decode("utf-8", "ignore"))
        except Exception as e:
            self.stats["last_error"] = f"parse: {e}"
            return
        if kind in ("location", "locations"):
            lat, lon = p.get("lat"), p.get("lon")
            if lat is None or lon is None:
                return
            self.stats["parsed"] += 1
            self.handler(self._merge(mmsi, dict(lat=lat, lon=lon, sog=p.get("sog"),
                cog=p.get("cog"), heading=p.get("heading"),
                nav_status=p.get("navStat"), ts=_ts_epoch(p.get("time")))))
        elif kind == "metadata":
            self.stats["meta"] += 1
            self.meta[mmsi] = dict(
                name=(p.get("name") or "").strip(), imo=p.get("imo"),
                callsign=p.get("callSign"), ship_type=p.get("shipType"),
                destination=(p.get("destination") or "").strip(),
                draught=p.get("draught"))

    def _merge(self, mmsi, d):
        d["mmsi"] = mmsi
        md = self.meta.get(mmsi)
        if md:
            for k, v in md.items():
                if v not in (None, ""):
                    d.setdefault(k, v)
        return d

    def stop(self):
        if self._client:
            try: self._client.disconnect()
            except Exception: pass


class AisstreamFeed:
    """aisstream.io global live AIS. Needs a free API key from aisstream.io."""
    URL = "wss://stream.aisstream.io/v0/stream"

    def __init__(self, handler, api_key, bbox):
        self.handler, self.key, self.bbox = handler, api_key, bbox
        self._thread, self._ws = None, None
        self.stats = {"source": "aisstream", "rx": 0, "parsed": 0,
                      "connected": False, "last_error": None}

    def start(self):
        try:
            import websocket
        except ImportError:
            raise SystemExit("pip install websocket-client")
        la0, la1, lo0, lo1 = self.bbox
        sub = {"APIKey": self.key, "BoundingBoxes": [[[la0, lo0], [la1, lo1]]],
               "FilterMessageTypes": ["PositionReport", "ShipStaticData"]}

        def on_open(ws):
            self.stats["connected"] = True
            ws.send(json.dumps(sub))

        def on_error(ws, err):
            self.stats["last_error"] = str(err)

        def on_close(ws, *a):
            self.stats["connected"] = False

        def on_message(ws, raw):
            self.stats["rx"] += 1
            try:
                msg = json.loads(raw)
            except Exception:
                return
            if "error" in msg:
                self.stats["last_error"] = str(msg.get("error"))
                return
            meta = msg.get("MetaData", {}) or {}
            mmsi = meta.get("MMSI") or meta.get("mmsi")
            t = msg.get("MessageType")
            body = (msg.get("Message") or {}).get(t, {}) if t else {}
            if t == "PositionReport" and mmsi:
                self.stats["parsed"] += 1
                self.handler(dict(mmsi=int(mmsi), ts=_now(),
                    lat=meta.get("latitude"), lon=meta.get("longitude"),
                    sog=body.get("Sog"), cog=body.get("Cog"),
                    heading=body.get("TrueHeading"),
                    nav_status=body.get("NavigationalStatus"),
                    name=(meta.get("ShipName") or "").strip()))
            elif t == "ShipStaticData" and mmsi:
                self.handler(dict(mmsi=int(mmsi), ts=_now(),
                    name=(body.get("Name") or meta.get("ShipName") or "").strip(),
                    imo=body.get("ImoNumber"), callsign=body.get("CallSign"),
                    ship_type=body.get("Type"), destination=body.get("Destination"),
                    length=(body.get("Dimension", {}) or {}).get("A"),
                    draught=body.get("MaximumStaticDraught")))

        import websocket
        self._ws = websocket.WebSocketApp(self.URL, on_open=on_open, on_message=on_message,
                                          on_error=on_error, on_close=on_close)
        self._thread = threading.Thread(target=self._ws.run_forever, daemon=True)
        self._thread.start()
        return self

    def stop(self):
        if self._ws:
            try: self._ws.close()
            except Exception: pass
