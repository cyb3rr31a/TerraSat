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
  flood_history                  Past flood incidents (2024, March 2026) and the Interior Ministry's
                                 at-risk areas, found by Muse Spark web search and placed with
                                 OpenStreetMap's geocoder (Nominatim). Needs META_API_KEY. ~$0.10.
"""
import argparse
import json
import re
import subprocess
import sys
import time
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
    "roads": ("osm_roads", NAIROBI_BBOX,
              ['way["highway"~"^(motorway|trunk|primary|secondary|tertiary|residential|unclassified|service|track)$"]',
               'way["highway"~"^(footway|path|pedestrian|steps)$"]["bridge"]'],  # footbridges: river crossings in settlements
              ["highway", "surface", "name", "bridge"]),
    "power_lines": ("osm_power_lines", DEMO_BBOX,
                    ['way["power"~"^(line|minor_line|cable)$"]'],
                    ["power", "voltage", "name", "operator"]),
}
ALL = [*OSM_LAYERS, "buildings", "terrain", "flood_2024", "flood_history"]
FLOOD_SITES = ("mathare", "mukuru", "kibera", "korogocho", "east_cluster")
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


HISTORY_EVENTS = {"2024_long_rains": "the April-May 2024 long-rains floods",
                  "2026_march": "the March 2026 flash floods"}


def _incidents_prompt(label):
    return (f"Search news reports and official statements about {label} in Nairobi County, Kenya. "
            "List every distinct place in Nairobi reported flooded (estate, neighbourhood, road or landmark, "
            "named as in the source). For each give: place, date (YYYY-MM-DD, or YYYY-MM if the day is unknown), "
            "what_happened (one short factual sentence, e.g. homes flooded, road impassable, deaths), and "
            "source_url (the page you read it on). Only include places named in a source you opened. "
            'Up to 40 places. JSON shape: {"incidents": [{"place": "", "date": "", "what_happened": "", "source_url": ""}]}')


AT_RISK_PROMPT = ("In March 2026 Kenya's Ministry of Interior published a list of areas in Nairobi at risk of "
                  "flooding (around 15 March 2026). Find that list and return every Nairobi area on it. "
                  'JSON shape: {"date": "YYYY-MM-DD", "source_url": "", "areas": [""]}')


def _same_url(a, b):
    norm = lambda u: (u or "").split("?")[0].split("#")[0].rstrip("/").replace("://www.", "://").lower()
    return norm(a) == norm(b)


# Short names news uses that match a different place first on the map
ALIASES = {"kwa njenga": "Mukuru Kwa Njenga", "kwa reuben": "Mukuru Kwa Reuben", "kwa rueben": "Mukuru Kwa Reuben"}


def name_variants(place):
    """Search terms for a place as news writes it, most specific first:
    "Mombasa Road at Cabanas" -> itself, "Cabanas", "Mombasa Road"; "Jomo Kenyatta ... (JKIA)" -> also "JKIA"."""
    place = ALIASES.get(place.strip().lower(), place)
    inner = re.findall(r"\(([^)]+)\)", place)
    base = re.sub(r"\([^)]*\)", "", place)
    parts = re.split(r",| in | at | along | near | and |/", base)
    clean = lambda t: re.sub(r"\b(informal settlement|slum|ward|junction)\b", "", t, flags=re.I).strip(" -")
    is_road = lambda t: bool(re.search(r"\b(road|highway|superhighway|avenue|bypass|street|way)\b", t, re.I))
    out = []
    for t in [place, base, *sorted(parts, key=is_road), *inner]:  # a landmark beats a long road
        t = clean(t)
        if len(t) > 2 and t.lower() not in (o.lower() for o in out):
            out.append(t)
    return out[:5]


def geocode(client, place):
    """Nominatim, limited to Nairobi (usage policy: 1 request a second, identify the app).
    Prefers named places (suburbs, estates) over roads or shops that share the name."""
    w, s, e, n = NAIROBI_BBOX[1], NAIROBI_BBOX[0], NAIROBI_BBOX[3], NAIROBI_BBOX[2]
    for name in name_variants(place):
        time.sleep(1.1)
        r = client.get("https://nominatim.openstreetmap.org/search",
                       params={"q": f"{name}, Nairobi, Kenya", "format": "jsonv2", "limit": 5,
                               "viewbox": f"{w},{n},{e},{s}", "bounded": 1})
        r.raise_for_status()
        hits = r.json()
        if hits:
            best = next((h for h in hits if h.get("category") == "place"), hits[0])
            return float(best["lon"]), float(best["lat"]), best["display_name"]
    return None


def fetch_flood_history(force=False):
    """News and official records of past floods, as map points. Evidence only (memos, report
    context): coverage favours places reporters reach, so it isn't used in the risk score."""
    from backend.app.services import meta
    dst = layer_path("flood_history")
    if dst.exists() and not force:
        return print("flood_history: already downloaded")
    rows = []
    for event, label in HISTORY_EVENTS.items():
        ans = meta.spark(_incidents_prompt(label) + meta.JSON_ONLY, web_search=True)
        cited = [c["url"] for c in ans["citations"]]
        for it in meta.parse_json(ans["text"]).get("incidents", []):
            rows.append({"kind": "incident", "event": event, **{k: it.get(k) for k in
                         ("place", "date", "what_happened", "source_url")},
                         "source_verified": any(_same_url(it.get("source_url"), u) for u in cited)})
        print(f"flood_history: {event}: {len(rows)} incidents so far, {ans['web_searches']} web searches")
    ans = meta.spark(AT_RISK_PROMPT + meta.JSON_ONLY, web_search=True)
    lst = meta.parse_json(ans["text"])
    verified = any(_same_url(lst.get("source_url"), c["url"]) for c in ans["citations"])
    rows += [{"kind": "at_risk_area", "event": "interior_ministry_2026", "place": a, "date": lst.get("date"),
              "what_happened": "Listed by the Ministry of Interior as at risk of flooding",
              "source_url": lst.get("source_url"), "source_verified": verified} for a in lst.get("areas", [])]
    feats, missed, cache = [], [], {}
    with httpx.Client(timeout=30, headers={"User-Agent": "TerraSat/0.1 (hackathon; flood history)"}) as c:
        for row in rows:
            key = (row["place"] or "").strip().lower()
            if key and key not in cache:
                cache[key] = geocode(c, row["place"])
            hit = cache.get(key)
            if not hit:
                missed.append(row["place"])
                continue
            feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [hit[0], hit[1]]},
                          "properties": {**row, "geocoded_to": hit[2],
                                         "precision": "named place (approximate, often a neighbourhood centre)"}})
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps({"type": "FeatureCollection", "features": feats}), encoding="utf-8")
    print(f"flood_history: {len(feats)} mapped, {sum(f['properties']['source_verified'] for f in feats)} "
          f"with a source Muse Spark opened; not found on the map: {missed or 'none'}")


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
            elif name == "flood_history":
                fetch_flood_history(a.force)
            else:
                fetch_osm(name, a.force)
        except (RuntimeError, ValueError, httpx.HTTPError) as e:
            print(f"FAILED: {e}")


if __name__ == "__main__":
    main()
