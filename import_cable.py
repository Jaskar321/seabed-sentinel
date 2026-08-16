"""
Import a REAL cable route into cable_<spot>.geojson. Three ways:

  1) discover EMODnet cable layer names (no download):
       python import_cable.py layers
  2) pull straight from EMODnet WFS (no download):
       python import_cable.py estlink2 wfs:<layerName>
  3) from a local file you downloaded (shapefile / GeoJSON):
       python import_cable.py estlink2 emodnet_cables.shp [name_contains]

Picks the longest route inside the spot's bbox. Once cable_<spot>.geojson exists,
the app/detector use that real multi-vertex route instead of the placeholder.
"""
import sys, os
from spots import SPOTS
import geo_layers

def _len(r):
    return sum(((r[i][0] - r[i-1][0])**2 + (r[i][1] - r[i-1][1])**2) ** 0.5
               for i in range(1, len(r)))

def main():
    args = sys.argv[1:]
    if args and args[0] == "layers":
        try:
            names = geo_layers.list_wfs_layers(filter_kw="cable")
        except Exception as e:
            print("could not reach EMODnet WFS:", e); return
        print("EMODnet WFS layers matching 'cable':")
        for n in names:
            print("  ", n)
        print("\nthen:  python import_cable.py <spot> wfs:<layerName>")
        return

    if len(args) < 2 or args[0] not in SPOTS:
        print(__doc__); print("spots:", ", ".join(SPOTS)); return
    spot, src = args[0], args[1]
    name = args[2] if len(args) > 2 else None

    if src.startswith("wfs:"):
        src = geo_layers.wfs_geojson_url(src[4:], bbox=SPOTS[spot]["bbox"])
    elif not src.startswith("http") and not os.path.exists(src):
        print(f"file not found: {src}")
        here = [f for f in os.listdir(".") if f.lower().endswith((".shp", ".geojson", ".json", ".gpkg"))]
        print("geo files in this folder:", here or "(none — download the EMODnet cables layer first,")
        if not here:
            print("or use:  python import_cable.py layers   to pull it from WFS with no download)")
        return

    try:
        routes = geo_layers.load_cable_routes(src, bbox=SPOTS[spot]["bbox"], name_contains=name, verbose=True)
    except Exception as e:
        print("failed to read routes:", e); return
    if not routes:
        print("no cable routes found in that bbox / name filter"); return
    best = max(routes, key=_len)
    geo_layers.save_cable(spot, best)
    print(f"cable_{spot}.geojson saved: {len(best)} waypoints (from {len(routes)} routes in bbox)")

if __name__ == "__main__":
    main()
