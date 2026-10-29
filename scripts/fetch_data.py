"""Download the map data TerraSat needs into data/raw/. Already-downloaded
layers are skipped (use --force to refresh).

    python scripts/fetch_data.py                  # everything
    python scripts/fetch_data.py roads buildings  # some layers

Layers:
  waterways, roads, power_lines  OpenStreetMap via the Overpass API
  buildings                      Overture Maps footprints around each demo site
  terrain                        Copernicus GLO-30 elevation tile(s) covering the demo sites
  flood_2024                     UNOSAT 2024 flood mapping, cut to each demo site. Download
                                 FL20240426KEN_SHP.zip from HDX by hand and extract it into
                                 data/raw/flood_2024/ first (the licence asks us to credit UNOSAT).
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.services.audit import PRESETS  # noqa: E402
from backend.app.services.layers import layer_path  # noqa: E402

OVERPASS_URLS = ["https://overpass-api.de/api/interpreter",          # main server
                 "https://overpass.kumi.systems/api/interpreter"]  # mirror if the main one is busy
NAIROBI_BBOX = (-1.45, 36.65, -1.15, 37.10)  # south, west, north, east
DEMO_BBOX = (-1.39, 36.77, -1.24, 36.95)     # demo sites only: lighter queries

# layer -> (TerraSat layer name, area, Overpass selectors, tags to keep)
OSM_LAYERS = {
    "waterways": ("osm_waterways", NAIROBI_BBOX,
                  ['way["waterway"~"^(river|stream|canal|drain|ditch)$"]', 'way["natural"="water"]'],
                  ["waterway", "natural", "name", "tunnel"]),
    "roads": ("osm_roads", DEMO_BBOX,
              ['way["highway"~"^(motorway|trunk|primary|secondary|tertiary|residential|unclassified|service|track)$"]'],
              ["highway", "surface", "name", "bridge"]),
    "power_lines": ("osm_power_lines", DEMO_BBOX,
                    ['way["power"~"^(line|minor_line|cable)$"]'],
                    ["power", "voltage", "name", "operator"]),
}
ALL = [*OSM_LAYERS, "buildings", "terrain", "flood_2024"]
FLOOD_SITES = ("mathare", "mukuru", "kibera")
SITE_HALF_DEG = 0.0105  # ~1.2 km each way: covers the 2.1 km audit square


def overpass_query(selectors, bbox):
    s, w, n, e = bbox
    body = "\n".join(f"  {sel}({s},{w},{n},{e});" for sel in selectors)
    return f"[out:json][timeout:180];\n(\n{body}\n);\nout tags geom;"


def to_geojson(osm, keep):
    feats = []
    for el in osm.get("elements", []):
        if not el.get("geometry"):
            continue
        coords = [[p["lon"], p["lat"]] for p in el["geometry"]]
        tags = el.get("tags", {})
        is_area = coords[0] == coords[-1] and len(coords) > 3 and tags.get("natural") == "water"
        feats.append({
            "type": "Feature", "id": f"way/{el['id']}",
            "geometry": {"type": "Polygon", "coordinates": [coords]} if is_area
            else {"type": "LineString", "coordinates": coords},
            "properties": {"osm_id": el["id"], **{k: tags.get(k) for k in keep}},
        })
    return {"type": "FeatureCollection", "features": feats}


def fetch_osm(name, force=False):
    layer, bbox, selectors, keep = OSM_LAYERS[name]
    dst = layer_path(layer)
    if dst.exists() and not force:
        return print(f"{name}: already downloaded")
    with httpx.Client(timeout=240, headers={"User-Agent": "TerraSat/0.1 (hackathon)"}) as c:
        for url in OVERPASS_URLS:
            try:
                r = c.post(url, data={"data": overpass_query(selectors, bbox)})
                r.raise_for_status()
                gj = to_geojson(r.json(), keep)
                break
            except (httpx.HTTPError, ValueError) as e:  # busy server or bad JSON
                print(f"  {url} failed ({e.__class__.__name__}), trying the next server...")
        else:
            raise RuntimeError(f"{name}: all Overpass servers are busy - try again later")
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(gj))
    print(f"{name}: {len(gj['features'])} features")


def site_bbox(site):
    lon, lat = PRESETS[site]
    return lon - SITE_HALF_DEG, lat - SITE_HALF_DEG, lon + SITE_HALF_DEG, lat + SITE_HALF_DEG


def fetch_buildings(force=False):
    """Overture footprints (includes Google Open Buildings) around each flood site."""
    folder = layer_path("buildings_baseline")
    folder.mkdir(parents=True, exist_ok=True)
    for site in FLOOD_SITES:
        dst = folder / f"{site}.geojson"
        if dst.exists() and not force:
            print(f"buildings/{site}: already downloaded")
            continue
        r = subprocess.run([sys.executable, "-m", "overturemaps", "download",
                            "--bbox=" + ",".join(f"{v:.5f}" for v in site_bbox(site)),
                            "-f", "geojson", "--type=building", "-o", str(dst)],
                           capture_output=True, text=True)
        if r.returncode != 0:
            dst.unlink(missing_ok=True)
            raise RuntimeError(f"buildings/{site}: {r.stderr.strip()[-400:]}")
        print(f"buildings/{site}: {len(json.loads(dst.read_text(encoding='utf-8'))['features'])} footprints")


def fetch_terrain(force=False):
    """Copernicus GLO-30 elevation (free, AWS Open Data): one 1x1 degree tile per demo area."""
    import math
    folder = layer_path("copernicus_dem")
    folder.mkdir(parents=True, exist_ok=True)
    tiles = {(math.floor(lat), math.floor(lon)) for lon, lat in PRESETS.values()}
    for lat, lon in sorted(tiles):
        name = (f"Copernicus_DSM_COG_10_{'N' if lat >= 0 else 'S'}{abs(lat):02d}_00_"
                f"{'E' if lon >= 0 else 'W'}{abs(lon):03d}_00_DEM")
        dst = folder / f"{name}.tif"
        if dst.exists() and not force:
            print(f"terrain/{name}: already downloaded")
            continue
        url = f"https://copernicus-dem-30m.s3.amazonaws.com/{name}/{name}.tif"
        with httpx.stream("GET", url, timeout=300, follow_redirects=True) as r:
            r.raise_for_status()
            with open(dst, "wb") as f:
                for chunk in r.iter_bytes():
                    f.write(chunk)
        print(f"terrain/{name}: {dst.stat().st_size / 1e6:.0f} MB")


def cut_flood_2024(force=False):
    """Cut the UNOSAT 1 May 2024 Nairobi mapping (Pleiades imagery) to each demo site.

    Keeps what was mapped (analysis extent), what clouds hid (so nobody reads
    "no damage" where the satellite simply couldn't see), the flood extent and
    the affected structures / bridges.
    """
    import geopandas as gpd
    import pandas as pd
    src = layer_path("unosat_2024").parent
    shp = {k: next(src.rglob(f"PL_20240501_{k}*Kiambu.shp"), None)
           for k in ("AnalysisExtent_Nairobi", "CloudObstruction", "FloodExtent", "AffectedStructure", "Affectedbridge")}
    if shp["FloodExtent"] is None:
        raise RuntimeError("flood_2024: extract FL20240426KEN_SHP.zip into data/raw/flood_2024/ first")
    kinds = {"AnalysisExtent_Nairobi": "analysis_extent", "CloudObstruction": "cloud",
             "FloodExtent": "flood_extent", "AffectedStructure": "affected_structure", "Affectedbridge": "affected_bridge"}
    layers = {kinds[k]: gpd.read_file(p, columns=[]).to_crs(4326) for k, p in shp.items() if p}
    folder = layer_path("unosat_2024")
    folder.mkdir(parents=True, exist_ok=True)
    for site in FLOOD_SITES:
        dst = folder / f"{site}.geojson"
        if dst.exists() and not force:
            print(f"flood_2024/{site}: already done")
            continue
        parts = [gdf.clip(site_bbox(site))[["geometry"]].assign(kind=kind) for kind, gdf in layers.items()]
        out = gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), crs=4326)
        out = out[~out.geometry.is_empty]
        dst.write_text(out.to_json(), encoding="utf-8")
        counts = ", ".join(f"{k} {n}" for k, n in out["kind"].value_counts().items())
        print(f"flood_2024/{site}: {counts or 'not covered by the UNOSAT mapping'}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("layers", nargs="*", help=f"any of {ALL} (default: all)")
    ap.add_argument("--force", action="store_true", help="download again even if present")
    a = ap.parse_args()
    for name in a.layers or ALL:
        if name not in ALL:
            sys.exit(f"Unknown layer {name!r}; choose from {ALL}")
        try:  # one busy server shouldn't stop the other layers
            if name == "buildings":
                fetch_buildings(a.force)
            elif name == "terrain":
                fetch_terrain(a.force)
            elif name == "flood_2024":
                cut_flood_2024(a.force)
            else:
                fetch_osm(name, a.force)
        except (RuntimeError, httpx.HTTPError) as e:
            print(f"FAILED: {e}")


if __name__ == "__main__":
    main()
