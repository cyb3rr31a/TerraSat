"""Download context layers for Nairobi from OpenStreetMap (Overpass API) and
save each as GeoJSON in data/raw. Usage:

    python scripts/fetch_osm_layers.py                       # all layers
    python scripts/fetch_osm_layers.py waterways power_lines # some layers
    python scripts/fetch_osm_layers.py --bbox S W N E roads  # another area
"""
import argparse
import json
from pathlib import Path

import httpx

OVERPASS_URLS = ["https://overpass-api.de/api/interpreter",          # main server
                 "https://overpass.kumi.systems/api/interpreter"]  # mirror, used if the main one fails
NAIROBI_BBOX = (-1.45, 36.65, -1.15, 37.10)  # south, west, north, east
RAW = Path(__file__).resolve().parents[1] / "data" / "raw"

# layer -> (output file, Overpass selectors, tags to keep)
LAYERS = {
    "waterways": ("nairobi_waterways.geojson",
                  ['way["waterway"~"^(river|stream|canal|drain|ditch)$"]', 'way["natural"="water"]'],
                  ["waterway", "natural", "name", "tunnel"]),
    "roads": ("nairobi_roads.geojson",
              ['way["highway"~"^(motorway|trunk|primary|secondary|tertiary|residential|unclassified|service|track)$"]'],
              ["highway", "surface", "name", "bridge"]),
    "power_lines": ("nairobi_power_lines.geojson",
                    ['way["power"~"^(line|minor_line|cable)$"]'],
                    ["power", "voltage", "name", "operator"]),
}


def build_query(selectors, bbox):
    s, w, n, e = bbox
    body = "\n".join(f"  {sel}({s},{w},{n},{e});" for sel in selectors)
    return f"[out:json][timeout:180];\n(\n{body}\n);\nout tags geom;"


def to_geojson(osm, keep):
    feats = []
    for el in osm.get("elements", []):
        geom = el.get("geometry")
        if not geom:
            continue
        coords = [[p["lon"], p["lat"]] for p in geom]
        tags = el.get("tags", {})
        closed = coords[0] == coords[-1] and len(coords) > 3
        is_area = closed and tags.get("natural") == "water"
        feats.append({
            "type": "Feature", "id": f"way/{el['id']}",
            "geometry": {"type": "Polygon", "coordinates": [coords]} if is_area
            else {"type": "LineString", "coordinates": coords},
            "properties": {"osm_id": el["id"], **{k: tags.get(k) for k in keep}},
        })
    return {"type": "FeatureCollection", "features": feats}


def fetch(layer, bbox, client):
    fname, selectors, keep = LAYERS[layer]
    last = None
    for url in OVERPASS_URLS:
        try:
            r = client.post(url, data={"data": build_query(selectors, bbox)})
            r.raise_for_status()
            osm = r.json()
            break
        except (httpx.HTTPError, ValueError) as e:  # busy server or bad JSON: try the mirror
            last = e
            print(f"  {url} failed ({e.__class__.__name__}); trying next server...")
    else:
        raise RuntimeError(f"All Overpass servers failed for {layer}: {last}")
    gj = to_geojson(osm, keep)
    RAW.mkdir(parents=True, exist_ok=True)
    (RAW / fname).write_text(json.dumps(gj))
    print(f"{layer}: {len(gj['features'])} features -> data/raw/{fname}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("layers", nargs="*", help=f"any of {list(LAYERS)} (default: all)")
    ap.add_argument("--bbox", nargs=4, type=float, default=NAIROBI_BBOX)
    a = ap.parse_args()
    with httpx.Client(timeout=240, headers={"User-Agent": "TerraSat/0.1 (hackathon)"}) as c:
        for layer in a.layers or list(LAYERS):
            if layer not in LAYERS:
                raise SystemExit(f"Unknown layer {layer!r}; choose from {list(LAYERS)}")
            try:
                fetch(layer, a.bbox, c)
            except RuntimeError as e:  # a busy server shouldn't block the other layers
                print(f"{layer}: FAILED - {e}. Run again later: python scripts/fetch_osm_layers.py {layer}")


if __name__ == "__main__":
    main()
