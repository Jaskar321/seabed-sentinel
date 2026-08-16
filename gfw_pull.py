"""
Cross-reference a cable-incident vessel against Global Fishing Watch events.

GFW's free API gives vessel identity + discrete EVENTS (loitering, AIS-gap,
encounters, port visits) - not raw tracks. So this checks whether GFW
independently recorded the culprit loitering / going dark at the incident.

Reads GFW_TOKEN from the environment (never hard-code it):
    PowerShell:  $env:GFW_TOKEN="<your token>"
    then:        python gfw_pull.py "Eagle S" 2024-12-20 2024-12-28
                 python gfw_pull.py "Yi Peng 3" 2024-11-14 2024-11-20
                 python gfw_pull.py "NewNew Polar Bear" 2023-10-05 2023-10-10
    (search by IMO/MMSI also works: python gfw_pull.py 9229655 2024-12-20 2024-12-28)

Writes gfw_events.csv and gfw_events.geojson (points for the map).
"""
import os, sys, json, csv
import requests

BASE = "https://gateway.api.globalfishingwatch.org/v3"
TOKEN = os.environ.get("GFW_TOKEN")
EVENT_DATASETS = {
    "loitering":  "public-global-loitering-events:latest",
    "gap":        "public-global-gaps-events:latest",
    "encounter":  "public-global-encounters-events:latest",
    "port_visit": "public-global-port-visits-events:latest",
}

def H():
    return {"Authorization": f"Bearer {TOKEN}"}

def search_vessel(q):
    r = requests.get(f"{BASE}/vessels/search",
                     params={"query": q, "datasets[0]": "public-global-vessel-identity:latest"},
                     headers=H(), timeout=30)
    if r.status_code != 200:
        print("search failed:", r.status_code, r.text[:200]); return []
    return r.json().get("entries", [])

def vessel_ids(entry):
    ids = []
    for sri in (entry.get("selfReportedInfo") or []):
        if sri.get("id"):
            ids.append(sri["id"])
    if entry.get("id"):
        ids.append(entry["id"])
    return list(dict.fromkeys(ids))

def get_events(vessel_id, dataset, start, end):
    params = {"vessels[0]": vessel_id, "datasets[0]": dataset,
              "start-date": start, "end-date": end, "limit": 100, "offset": 0}
    out = []
    while True:
        r = requests.get(f"{BASE}/events", params=params, headers=H(), timeout=60)
        if r.status_code != 200:
            if params["offset"] == 0:
                print(f"    ({dataset.split(':')[0]}) {r.status_code}: {r.text[:120]}")
            break
        ents = r.json().get("entries", [])
        out.extend(ents)
        if len(ents) < params["limit"]:
            break
        params["offset"] += params["limit"]
    return out

def main():
    if not TOKEN:
        print("set GFW_TOKEN first:  $env:GFW_TOKEN=\"<token>\""); return
    if len(sys.argv) < 4:
        print('usage: python gfw_pull.py "<name or IMO/MMSI>" <start YYYY-MM-DD> <end YYYY-MM-DD>'); return
    q, start, end = sys.argv[1], sys.argv[2], sys.argv[3]

    entries = search_vessel(q)
    if not entries:
        print("no vessel match for", q); return

    print("candidates:")
    for e in entries[:8]:
        s = (e.get("selfReportedInfo") or [{}])[0]
        print(f"   {s.get('shipname'):<20} flag={s.get('flag')}  imo={s.get('imo')}  mmsi={s.get('ssvid')}")

    # prefer an exact (case-insensitive) shipname match over the first fuzzy hit
    ql = q.strip().lower()
    e = next((x for x in entries
              if any((s.get("shipname") or "").strip().lower() == ql
                     for s in (x.get("selfReportedInfo") or []))), entries[0])
    sri = (e.get("selfReportedInfo") or [{}])[0]
    name = sri.get("shipname") or q
    ids = vessel_ids(e)
    print(f"\nusing: {name}  flag={sri.get('flag')}  imo={sri.get('imo')}  ids={ids[:2]}")

    rows = []
    for vid in ids[:2]:
        for kind, ds in EVENT_DATASETS.items():
            evs = get_events(vid, ds, start, end)
            if evs:
                print(f"  {kind}: {len(evs)} event(s)")
            for ev in evs:
                pos = ev.get("position") or {}
                rows.append(dict(kind=kind, start=ev.get("start"), end=ev.get("end"),
                                 lat=pos.get("lat"), lon=pos.get("lon"), vessel=name))
    if not rows:
        print("no events in that window (GFW may not cover this vessel/date)"); return

    with open("gfw_events.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["kind", "start", "end", "lat", "lon", "vessel"])
        w.writeheader(); w.writerows(rows)
    gj = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [r["lon"], r["lat"]]},
         "properties": r} for r in rows if r["lat"] is not None]}
    json.dump(gj, open("gfw_events.geojson", "w"))
    print(f"saved gfw_events.csv / gfw_events.geojson  ({len(rows)} events)")

if __name__ == "__main__":
    main()
