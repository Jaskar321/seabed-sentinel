"""
Vessel enrichment for a clicked data point.
Pulls "more public data" on a ship identifier:
  1. AIS static fields already in the stream/file (name, IMO, type, dims, dest)
  2. Flag state derived OFFLINE from the MMSI MID (first 3 digits) - no API,
     and the interesting signal for shadow-fleet / flag-of-convenience vessels
  3. Optional online lookups (Global Fishing Watch) if GFW_TOKEN is set
  4. Click-through links to public vessel pages (no fetching required)
"""
import os

# MMSI Maritime Identification Digits (MID) -> flag state. Focused table:
# Baltic + Europe + common flags of convenience / shadow-fleet flags.
MID = {
    "201": "Albania", "205": "Belgium", "209": "Cyprus", "210": "Cyprus",
    "211": "Germany", "212": "Cyprus", "218": "Germany", "219": "Denmark",
    "220": "Denmark", "224": "Spain", "225": "Spain", "226": "France",
    "227": "France", "228": "France", "230": "Finland", "231": "Faroe Is",
    "232": "United Kingdom", "233": "United Kingdom", "234": "United Kingdom",
    "235": "United Kingdom", "236": "Gibraltar", "237": "Greece", "238": "Croatia",
    "239": "Greece", "240": "Greece", "241": "Greece", "244": "Netherlands",
    "245": "Netherlands", "246": "Netherlands", "247": "Italy", "248": "Malta",
    "249": "Malta", "250": "Ireland", "253": "Luxembourg", "256": "Malta",
    "257": "Norway", "258": "Norway", "259": "Norway", "261": "Poland",
    "265": "Sweden", "266": "Sweden", "267": "Slovakia", "269": "Switzerland",
    "271": "Turkey", "272": "Ukraine", "273": "Russia", "275": "Latvia",
    "276": "Estonia", "277": "Lithuania", "278": "Slovenia", "279": "Serbia",
    "303": "USA (Alaska)", "338": "USA", "366": "USA", "367": "USA", "368": "USA",
    "351": "Panama", "352": "Panama", "353": "Panama", "354": "Panama",
    "355": "Panama", "356": "Panama", "357": "Panama", "370": "Panama",
    "371": "Panama", "372": "Panama", "373": "Panama", "374": "Panama",
    "412": "China", "413": "China", "414": "China", "416": "Taiwan",
    "422": "Iran", "431": "Japan", "432": "Japan", "440": "South Korea",
    "441": "South Korea", "477": "Hong Kong", "525": "Indonesia",
    "518": "Cook Islands", "548": "Philippines", "563": "Singapore",
    "564": "Singapore", "565": "Singapore", "566": "Singapore",
    "538": "Marshall Islands", "636": "Liberia", "637": "Liberia",
    "620": "Comoros", "667": "Sierra Leone", "671": "Togo", "677": "Tanzania",
    "375": "St Vincent & Gren.", "376": "St Vincent & Gren.", "377": "St Vincent & Gren.",
    "341": "St Kitts & Nevis", "306": "Curacao/Neth.", "312": "Belize",
}

# Flags frequently associated with sanctioned / "shadow fleet" tankers - a hint, not a verdict.
SHADOW_HINT = {"Panama", "Liberia", "Marshall Islands", "Cook Islands", "Comoros",
               "Gabon", "Palau", "Cameroon", "Barbados", "St Kitts & Nevis",
               "St Vincent & Gren.", "Togo", "Sierra Leone", "Tanzania"}

def mmsi_flag(mmsi):
    s = str(int(mmsi)) if mmsi else ""
    country = MID.get(s[:3], "unknown")
    return country, (country in SHADOW_HINT)

def external_links(mmsi, imo=None):
    links = {}
    if mmsi:
        links["MarineTraffic"] = f"https://www.marinetraffic.com/en/ais/details/ships/mmsi:{int(mmsi)}"
        links["VesselFinder"] = f"https://www.vesselfinder.com/vessels?name={int(mmsi)}"
    if imo:
        links["Equasis (IMO)"] = f"https://www.equasis.org/  (search IMO {imo})"
    return links

def gfw_lookup(mmsi):
    """Optional online identity/registry lookup via Global Fishing Watch.
    Enabled only if GFW_TOKEN is set. Returns {} on any failure."""
    token = os.environ.get("GFW_TOKEN")
    if not token or not mmsi:
        return {}
    try:
        import requests
        r = requests.get(
            "https://gateway.api.globalfishingwatch.org/v3/vessels/search",
            params={"query": str(int(mmsi)), "datasets[0]": "public-global-vessel-identity:latest"},
            headers={"Authorization": f"Bearer {token}"}, timeout=8)
        if r.ok:
            items = (r.json() or {}).get("entries", [])
            if items:
                v = items[0].get("selfReportedInfo", [{}])[0] if items[0].get("selfReportedInfo") else items[0]
                return {"gfw_shipname": v.get("shipname"), "gfw_flag": v.get("flag"),
                        "gfw_callsign": v.get("callsign"), "gfw_imo": v.get("imo")}
    except Exception as e:
        return {"gfw_error": str(e)}
    return {}

def enrich(vessel):
    """vessel: dict of AIS fields we already hold (mmsi, name, imo, ship_type, ...)."""
    mmsi = vessel.get("mmsi")
    imo = vessel.get("imo")
    country, shadow = mmsi_flag(mmsi)
    out = {
        "mmsi": mmsi,
        "name": vessel.get("name") or "",
        "imo": imo or "",
        "callsign": vessel.get("callsign") or "",
        "ship_type": vessel.get("ship_type") or "",
        "flag_state": country,
        "flag_of_convenience_hint": shadow,
        "length_m": vessel.get("length"),
        "width_m": vessel.get("width"),
        "draught_m": vessel.get("draught"),
        "destination": vessel.get("destination") or "",
        "nav_status": vessel.get("nav_status") or "",
        "links": external_links(mmsi, imo),
    }
    out.update(gfw_lookup(mmsi))   # no-op unless GFW_TOKEN is set
    return out

if __name__ == "__main__":
    # quick offline check
    for m in [273123456, 636111222, 230999888, 111000111]:
        c, s = mmsi_flag(m)
        print(m, "->", c, "(shadow hint)" if s else "")
