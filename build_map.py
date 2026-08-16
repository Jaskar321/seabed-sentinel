"""Render detection results to a self-contained interactive Leaflet map."""
import json
import seabed

STYLE = {
    "ANCHOR-DRAG SUSPECT": ("#d1495b", 5, None),
    "DARK / AIS GAP":      ("#e8833a", 5, "8 6"),
    "fishing-like":        ("#3b82c4", 3, None),
    "transit":             ("#9aa5b1", 2, None),
    "stopped":             ("#b0b7c0", 3, None),
    "other":               ("#8a94a3", 2, None),
}

def build_map(rows, out="demo_map.html", title="Seabed Sentinel — AIS behaviour"):
    feats = []
    for r in rows:
        col, w, dash = STYLE.get(r["label"], STYLE["other"])
        if r.get("watch") and not r["alert"]:
            col, w, dash = "#eab308", 4, None
        feats.append({
            "type": "Feature",
            "geometry": {"type": "LineString",
                         "coordinates": [[c[1], c[0]] for c in r["coords"]]},
            "properties": {"name": r["name"] or f"MMSI {r['mmsi']}", "ship_type": r["ship_type"],
                           "label": r["label"], "score": r["score"], "alert": r["alert"],
                           "watch": bool(r.get("watch")), "ml_anomaly": r.get("ml_anomaly"),
                           "factors": r["factors"], "color": col, "weight": w, "dash": dash or ""},
        })
    cable = {"type": "Feature",
             "geometry": {"type": "LineString",
                          "coordinates": [[p[1], p[0]] for p in seabed.CABLE]},
             "properties": {}}
    clat = sum(p[0] for p in seabed.CABLE) / len(seabed.CABLE)
    clon = sum(p[1] for p in seabed.CABLE) / len(seabed.CABLE)
    alerts = [r for r in rows if r["alert"]]
    alist = "".join(
        f'<div class="al" onclick="focusV({json.dumps(r["name"] or ("MMSI "+str(r["mmsi"])))})">'
        f'<b style="color:{STYLE.get(r["label"],STYLE["other"])[0]}">{r["label"]}</b> '
        f'&middot; {r["name"] or ("MMSI "+str(r["mmsi"]))} <span class="sc">score {r["score"]}</span><br>'
        f'<small>{r["ship_type"]}</small></div>' for r in alerts) or '<div class="al">no alerts — corridor clear</div>'

    html = f"""<!doctype html><html><head><meta charset="utf-8">
<title>{title}</title>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.css"/>
<script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.js"></script>
<style>
 html,body{{margin:0;height:100%;font-family:system-ui,Segoe UI,Roboto,sans-serif}}
 #map{{position:absolute;inset:0}}
 #panel{{position:absolute;top:12px;right:12px;z-index:1000;width:290px;max-height:92%;
   overflow:auto;background:#0f172a;color:#e2e8f0;border-radius:10px;padding:14px 16px;
   box-shadow:0 6px 24px rgba(0,0,0,.35);font-size:13px}}
 #panel h2{{margin:0 0 2px;font-size:15px}} #panel .sub{{color:#94a3b8;font-size:11px;margin-bottom:10px}}
 .al{{background:#1e293b;border-radius:7px;padding:8px 10px;margin:6px 0;cursor:pointer;line-height:1.35}}
 .al:hover{{background:#334155}} .sc{{float:right;color:#94a3b8;font-size:11px}}
 .lg{{margin-top:12px;border-top:1px solid #334155;padding-top:10px}}
 .lg div{{margin:4px 0}} .sw{{display:inline-block;width:22px;height:3px;vertical-align:middle;margin-right:8px}}
 .pop b{{font-size:13px}} .pop ul{{margin:6px 0 0;padding-left:16px}} .pop li{{margin:2px 0}}
</style></head><body>
<div id="map"></div>
<div id="panel">
 <h2>Seabed Sentinel</h2><div class="sub">{title}</div>
 <b>{len(alerts)} alert(s)</b> of {len(rows)} vessels
 {alist}
 <div class="lg">
  <div><span class="sw" style="background:#d1495b"></span>anchor-drag suspect</div>
  <div><span class="sw" style="background:#e8833a"></span>dark / AIS gap</div>
  <div><span class="sw" style="background:#3b82c4"></span>fishing-like</div>
  <div><span class="sw" style="background:#9aa5b1"></span>transit (normal)</div>
  <div><span class="sw" style="background:#2a9d8f"></span>protected cable</div>
 </div>
</div>
<script>
 var map=L.map('map',{{zoomControl:true}}).setView([{clat},{clon}],10);
 L.tileLayer('https://{{s}}.basemaps.cartocdn.com/light_all/{{z}}/{{x}}/{{y}}{{r}}.png',
   {{attribution:'&copy; OpenStreetMap &copy; CARTO',subdomains:'abcd',maxZoom:19}}).addTo(map);
 L.geoJSON({json.dumps(cable)},{{style:{{color:'#2a9d8f',weight:3,dashArray:'6 5'}}}}).addTo(map);
 var data={json.dumps({"type":"FeatureCollection","features":feats})};
 var byName={{}};
 L.geoJSON(data,{{
   style:function(f){{return {{color:f.properties.color,weight:f.properties.weight,
     opacity:f.properties.alert?0.95:0.55,dashArray:f.properties.dash||null}};}},
   onEachFeature:function(f,l){{
     byName[f.properties.name]=l;
     var p=f.properties, fx=p.factors.map(function(x){{return '<li>'+x+'</li>';}}).join('');
     l.bindPopup('<div class="pop"><b>'+p.name+'</b> ('+p.ship_type+')<br>'+
       p.label+' &middot; score '+p.score+(fx?'<ul>'+fx+'</ul>':'')+'</div>');
     if(p.alert) l.setStyle({{weight:6}});
   }}}}).addTo(map);
 function focusV(n){{var l=byName[n]; if(l){{map.fitBounds(l.getBounds().pad(1.2)); l.openPopup();}}}}
</script></body></html>"""
    with open(out, "w") as f:
        f.write(html)
    return out
