"""
Real geographic layers for Seabed Sentinel.

  - load_cable_routes()  : read real cable/pipeline routes from an EMODnet
                           shapefile or GeoJSON (needs geopandas)
  - save/load_saved_cable(): persist the chosen route per spot as cable_<spot>.geojson
                           (loading our own GeoJSON needs no geopandas)
  - Bathymetry           : sample seabed depth from an EMODnet DTM GeoTIFF
                           (needs rasterio) for the anchor-drag depth-gate

Data:
  Cables     -> EMODnet Human Activities, "Telecommunication cables (actual routes)"
                https://emodnet.ec.europa.eu/en/human-activities  (download shapefile, or WFS)
  Bathymetry -> EMODnet Bathymetry DTM 2024 GeoTIFF tile for your area
                https://emodnet.ec.europa.eu/en/bathymetry
"""
import os, json


EMODNET_HA_WFS = "https://ows.emodnet-humanactivities.eu/wfs"

def list_wfs_layers(base=EMODNET_HA_WFS, filter_kw="cable"):
    """Query WFS GetCapabilities and return feature-type names (optionally filtered)."""
    import requests, re
    r = requests.get(base, params={"SERVICE": "WFS", "REQUEST": "GetCapabilities",
                                    "VERSION": "2.0.0"}, timeout=60)
    names = re.findall(r"<(?:\w+:)?Name>([^<\s]+)</(?:\w+:)?Name>", r.text)
    names = [n for n in names if any(ch.isalpha() for ch in n)]
    if filter_kw:
        names = [n for n in names if filter_kw.lower() in n.lower()]
    return sorted(set(names))

def wfs_geojson_url(typename, base=EMODNET_HA_WFS, bbox=None):
    """bbox = (lat_min, lat_max, lon_min, lon_max). Uses CRS84 (lon,lat) to avoid axis ambiguity."""
    from urllib.parse import urlencode
    params = {"SERVICE": "WFS", "VERSION": "2.0.0", "REQUEST": "GetFeature",
              "typeNames": typename, "outputFormat": "application/json", "count": "100000"}
    if bbox:
        la0, la1, lo0, lo1 = bbox
        params["BBOX"] = f"{lo0},{la0},{lo1},{la1},urn:ogc:def:crs:OGC:1.3:CRS84"
    return base + "?" + urlencode(params)


def _lines(geom):
    t = getattr(geom, "geom_type", None)
    if t == "LineString":
        return [geom]
    if t == "MultiLineString":
        return list(geom.geoms)
    return []

def load_cable_routes(path, bbox=None, name_contains=None, verbose=False):
    """Return list of routes, each a list of (lat, lon) waypoints, clipped to bbox.
    Reads any format geopandas/fiona supports (.shp, .geojson, .gpkg) or a URL."""
    import geopandas as gpd
    from shapely.geometry import box
    gdf = gpd.read_file(path)
    if verbose:
        print(f"  read {len(gdf)} features (crs={gdf.crs})")
    try:
        if gdf.crs and gdf.crs.to_epsg() != 4326:
            gdf = gdf.to_crs(4326)
    except Exception:
        pass
    if name_contains:
        for col in gdf.columns:
            if gdf[col].dtype == object:
                m = gdf[col].astype(str).str.contains(name_contains, case=False, na=False)
                if m.any():
                    gdf = gdf[m]; break
    if bbox:
        la0, la1, lo0, lo1 = bbox
        gdf = gdf[gdf.intersects(box(lo0, la0, lo1, la1))]
    routes = []
    for geom in gdf.geometry:
        for line in _lines(geom):
            routes.append([(y, x) for x, y in line.coords])
    return routes

def save_cable(spot, route):
    """route = list of (lat, lon). Saves cable_<spot>.geojson (LineString, [lon,lat])."""
    gj = {"type": "Feature", "properties": {"spot": spot},
          "geometry": {"type": "LineString", "coordinates": [[lon, lat] for lat, lon in route]}}
    with open(f"cable_{spot}.geojson", "w") as f:
        json.dump(gj, f)

def _first_line_coords(gj):
    if gj.get("type") == "FeatureCollection":
        for feat in gj["features"]:
            c = _first_line_coords(feat)
            if c: return c
        return None
    geom = gj.get("geometry", gj)
    if geom.get("type") == "LineString":
        return geom["coordinates"]
    if geom.get("type") == "MultiLineString":
        return geom["coordinates"][0]
    return None

def load_saved_cable(spot):
    """Load cable_<spot>.geojson -> [(lat,lon),...] or None. No geopandas needed."""
    p = f"cable_{spot}.geojson"
    if not os.path.exists(p):
        return None
    try:
        coords = _first_line_coords(json.load(open(p)))
        return [(lat, lon) for lon, lat in coords] if coords else None
    except Exception:
        return None


class Bathymetry:
    """Sample seabed depth (metres, positive down) from an EMODnet DTM GeoTIFF."""
    def __init__(self, path):
        import rasterio
        self.ds = rasterio.open(path)
        self._tf = None
        try:
            if self.ds.crs and self.ds.crs.to_epsg() != 4326:
                from pyproj import Transformer
                self._tf = Transformer.from_crs(4326, self.ds.crs, always_xy=True)
        except Exception:
            self._tf = None

    def depth_at(self, lat, lon):
        try:
            x, y = (self._tf.transform(lon, lat) if self._tf else (lon, lat))
            val = next(self.ds.sample([(x, y)]))[0]
        except Exception:
            return None
        if val is None:
            return None
        try:
            v = float(val)
        except Exception:
            return None
        if v != v or abs(v) > 1e6:      # NaN / nodata
            return None
        return -v if v < 0 else 0.0     # EMODnet elevation: negative below sea level
