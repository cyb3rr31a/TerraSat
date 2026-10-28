"""Run a TerraSat audit for one location with any profile.

    python scripts/run_audit.py --profile flood --preset mathare
    python scripts/run_audit.py --profile solar_minigrid --lon 36.98 --lat -1.42
    python scripts/run_audit.py --profile flood --preset mathare --offline   # no network

Outputs: data/outputs/<profile>_<place>/ mosaic.jpg, overlay.png, audit.geojson, summary.json
"""
import argparse
import io
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402
from shapely.geometry import LineString, box, mapping  # noqa: E402

from backend.app.profiles.loader import list_profile_ids, load_profile  # noqa: E402
from backend.app.services import geo  # noqa: E402
from backend.app.services.audit import PRESETS, run_audit  # noqa: E402
from backend.app.services.sam_service import MockBackend, render_overlay  # noqa: E402
from backend.app.services.tiles import TileCache  # noqa: E402



def offline_tiles(z, x, y):
    img = Image.new("RGB", (256, 256), (70 + (x * 7) % 30, 80 + (y * 11) % 30, 60))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def synthetic(profile, lon, lat, seed=7):
    """Fake detections + layers so the whole pipeline runs without network."""
    rnd = random.Random(seed)

    def factory(m):
        def sq(gx, gy, s):
            a = geo.global_px_to_lonlat(gx, gy, m.zoom)
            b = geo.global_px_to_lonlat(gx + s, gy + s, m.zoom)
            return box(a[0], b[1], b[0], a[1])
        truth = {}
        houses = [(rnd.uniform(m.box.x0 + 20, m.box.x1 - 40), rnd.uniform(m.box.y0 + 20, m.box.y1 - 40),
                   rnd.uniform(10, 25)) for _ in range(600)]
        first = {c: s.prompts[0] for c, s in profile.classes.items()}
        truth[first["building"]] = [sq(*h) for h in houses]
        if "solar_panel" in first:   # panels on ~6% of roofs
            truth[first["solar_panel"]] = [sq(x + 2, y + 2, 4) for x, y, s in houses if rnd.random() < 0.06]
        if "garbage" in first:
            truth[first["garbage"]] = [sq(*h[:2], 12) for h in rnd.sample(houses, 15)]
        return MockBackend(truth, m)

    w, s, e, n = lon - 0.01, lat - 0.01, lon + 0.01, lat + 0.01
    layers = {
        "osm_waterways": [{"type": "Feature", "properties": {"waterway": "river", "name": "Synthetic River"},
                           "geometry": mapping(LineString([(w, lat), (lon, lat + 0.0008), (e, lat)]))}],
        "osm_power_lines": [{"type": "Feature", "properties": {"power": "minor_line"},
                             "geometry": mapping(LineString([(lon + 0.003, s), (lon + 0.003, n)]))}],
    }
    return factory, {k: v for k, v in layers.items() if k in profile.layers}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", choices=list_profile_ids(), default="flood")
    ap.add_argument("--preset", choices=PRESETS, default="mathare")
    ap.add_argument("--lon", type=float)
    ap.add_argument("--lat", type=float)
    ap.add_argument("--side", type=float)
    ap.add_argument("--zoom", type=int)
    ap.add_argument("--offline", action="store_true")
    a = ap.parse_args()

    profile = load_profile(a.profile)
    lon, lat = (a.lon, a.lat) if a.lon is not None else PRESETS[a.preset]
    place = a.preset if a.lon is None else f"{lat:.4f}_{lon:.4f}"
    tag = "_offline" if a.offline else ""
    out = ROOT / "data" / "outputs" / f"{profile.id}_{place}{tag}"
    out.mkdir(parents=True, exist_ok=True)

    kw = {}
    if a.offline:
        kw["backend_factory"], kw["layers"] = synthetic(profile, lon, lat)
        kw["tile_cache"] = TileCache(root=ROOT / "data" / "cache" / "tiles_offline", fetcher=offline_tiles, provider="mapbox")
        kw["sam_cache_dir"] = ROOT / "data" / "cache" / "sam_offline"

    print(f"TerraSat audit | profile: {profile.name} | place: {place}")
    res = run_audit(profile.id, lon, lat, side_m=a.side, zoom=a.zoom, **kw)
    m = res.mosaic
    print(f"  mosaic {m.image.width}x{m.image.height} px at {geo.meters_per_pixel(lat, m.zoom):.2f} m/px, "
          f"{len(list(m.windows()))} windows, {len(res.detections)} detections")
    m.save(out / "mosaic")
    render_overlay(m, res.detections, profile.sam_classes()).save(out / "overlay.png")
    (out / "audit.geojson").write_text(json.dumps(res.result.geojson))
    (out / "summary.json").write_text(json.dumps(res.result.summary, indent=2))
    print(json.dumps(res.result.summary, indent=2))
    print(f"Saved to {out}")


if __name__ == "__main__":
    main()
