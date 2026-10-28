import numpy as np
from shapely.geometry import box

from backend.app.services import geo
from backend.app.services.sam_service import (
    MockBackend, mask_to_polygons, render_overlay, rle_decode, segment_mosaic,
    segment_mosaic_cached)
from backend.app.services.tiles import TileCache, build_mosaic
from tests.test_tiles import fake_fetcher

MATHARE = (36.8580, -1.2615)


def lonlat_square(gx, gy, size_px, zoom):
    a = geo.global_px_to_lonlat(gx, gy, zoom)
    b = geo.global_px_to_lonlat(gx + size_px, gy + size_px, zoom)
    return box(a[0], b[1], b[0], a[1])


def make_scene(tmp_path):
    cache = TileCache(root=tmp_path / "tiles", fetcher=fake_fetcher([]), provider="mapbox")
    m = build_mosaic(*MATHARE, side_m=2100, zoom=18, cache=cache)
    houses = []
    # a regular grid of 15 px (~9 m) houses every 97 px across the whole mosaic,
    # so many fall inside window overlaps and some straddle window edges
    for gy in range(int(m.box.y0) + 30, int(m.box.y1) - 30, 97):
        for gx in range(int(m.box.x0) + 30, int(m.box.x1) - 30, 97):
            houses.append(lonlat_square(gx, gy, 15, 18))
    return m, houses


def test_each_house_detected_exactly_once(tmp_path):
    m, houses = make_scene(tmp_path)
    backend = MockBackend({"rooftop": houses}, m)
    dets = segment_mosaic(m, backend)
    buildings = [d for d in dets if d.cls == "building"]
    assert len(buildings) == len(houses)
    # every detection is a whole house (not a fragment)
    expected_area = geo.area_m2(houses[0])
    assert all(abs(d.area_m2 - expected_area) / expected_area < 0.05 for d in buildings)


def test_cache_roundtrip(tmp_path):
    m, houses = make_scene(tmp_path)
    backend = MockBackend({"rooftop": houses[:50]}, m)
    a = segment_mosaic_cached(m, backend, cache_dir=tmp_path / "sam")
    backend.truth = {}  # if the cache works, the backend is never called again
    b = segment_mosaic_cached(m, backend, cache_dir=tmp_path / "sam")
    assert len(a) == len(b) == 50


def test_mask_to_polygons_and_rle():
    mask = np.zeros((50, 60), dtype=bool)
    mask[10:20, 5:25] = True
    polys = mask_to_polygons(mask)
    assert len(polys) == 1
    xs = [p[0] for p in polys[0]]
    assert min(xs) == 5 and max(xs) == 24
    # COCO RLE round trip (column-major)
    flat = mask.T.flatten()
    counts, cur, run = [], False, 0
    for v in flat:
        if v == cur:
            run += 1
        else:
            counts.append(run); cur = v; run = 1
    counts.append(run)
    assert (rle_decode({"size": [50, 60], "counts": counts}) == mask).all()


def test_overlay_renders(tmp_path):
    m, houses = make_scene(tmp_path)
    dets = segment_mosaic(m, MockBackend({"rooftop": houses[:20]}, m))
    img = render_overlay(m, dets)
    assert img.size == m.image.size
