"""
Registry of critical waterway spots to monitor.
Each spot = a cable/pipeline route + a protection corridor + a bounding box.
Add spots here; each gets its own self-calibrating route model (route_<name>.joblib),
while the behaviour model and the rules are shared across all spots.

Cable coordinates are APPROXIMATE placeholders - replace with exact routes from
EMODnet Human Activities (submarine cables / pipelines layer).
"""
SPOTS = {
    # Danish waters - matches DMA day-files. Great Belt chokepoint (real HVDC link).
    "great_belt": dict(cable=[(55.33, 10.93), (55.35, 11.12)], buffer=2500.0,
                       bbox=(55.15, 55.55, 10.75, 11.30)),
    # Gulf of Finland - matches the free Digitraffic live feed. Estlink 2 (real incident).
    "estlink2":   dict(cable=[(60.28, 25.60), (59.42, 26.98)], buffer=2500.0,
                       bbox=(59.30, 60.30, 24.80, 26.80)),
    # Add more: Fehmarn Belt (Kontek), Oresund, Bornholm (Nord Stream / BCS), etc.
    # "kontek": dict(cable=[(...),(...)], buffer=2500.0, bbox=(...)),
}
