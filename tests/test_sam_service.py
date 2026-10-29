import json

import numpy as np
from PIL import Image
from shapely.geometry import box

from backend.app.services import geo
from backend.app.services.sam_service import (
    MetaSAMBackend, MockBackend, collect_output_text, mask_to_polygons, parse_sam_output,
    render_overlay, rle_decode, segment_mosaic, segment_mosaic_cached)
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


# --- parsing real SAM 3.1 wire output (sample from the meta-sam-parser README)
SAMPLE = (
    "<0f>0<|box;x1=211;y1=228;x2=270;y2=254;w=320;h=334;c=0.91|>"
    "<|mask;x=0;y=0;c=0.91;data=27,60,~!!!!M!0c[0o91w?q1!pIH4pPRVp2B3'7`e.ioeAf6-k/#Xd8%dX9x(|>"
    ",1<|box;x1=155;y1=228;x2=202;y2=254;w=320;h=334;c=0.42|>"
    "<|mask;x=0;y=0;c=0.42;data=27,48,~!!!!J!0c[q=Pj_zs=*4C4(/./x#:/`S_GnD`=o3?X{emCgO$y@|>\n"
)


def sse(chunks, final=None):
    lines = [f"data: {json.dumps({'type': 'response.output_text.delta', 'delta': c})}" for c in chunks]
    if final is not None:
        lines.append("data: " + json.dumps({"type": "response.content_part.done",
                                            "part": {"type": "output_text", "text": final}}))
    lines.append("data: " + json.dumps({"type": "response.completed"}))
    return lines


def test_collect_output_text_from_deltas_split_mid_mask():
    cut = SAMPLE.index("Pj_z")  # split inside a mask payload
    assert collect_output_text(sse([SAMPLE[:cut], SAMPLE[cut:]])) == SAMPLE


def test_collect_output_text_prefers_final_part():
    assert collect_output_text(sse(["garbled"], final=SAMPLE)) == SAMPLE


def test_parse_sam_output_polygons_in_source_pixels():
    masks = parse_sam_output(SAMPLE, "rooftop")
    assert len(masks) == 2
    m0 = masks[0]
    xs = [p[0] for p in m0.polygon]
    ys = [p[1] for p in m0.polygon]
    assert 211 <= min(xs) and max(xs) <= 271 and 228 <= min(ys) and max(ys) <= 255
    assert abs(m0.score - 0.91) < 1e-6


def test_confidence_filter_and_empty_output():
    assert len(parse_sam_output(SAMPLE, "rooftop", min_confidence=0.5)) == 1
    assert parse_sam_output("", "rooftop") == []


def test_backend_payload_and_segment(monkeypatch):
    be = MetaSAMBackend(api_key="test")
    img = Image.new("RGB", (320, 334))
    body = be.payload(img, "rooftop")
    content = body["input"][0]["content"]
    assert body["model"] == "sam-3.1"
    assert content[0] == {"type": "input_text", "text": "rooftop"}
    assert content[1]["image_url"].startswith("data:image/jpeg;base64,")
    calls = []
    monkeypatch.setattr(be, "call", lambda image, prompt: calls.append(prompt) or SAMPLE)
    out = be.segment(img, ["rooftop", "garbage pile"])
    assert calls == ["rooftop", "garbage pile"]  # one request per concept
    assert len(out) == 4 and {m.prompt for m in out} == {"rooftop", "garbage pile"}
