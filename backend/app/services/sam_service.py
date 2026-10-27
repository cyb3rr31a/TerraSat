"""Run text-prompted segmentation (SAM 3.1) over a mosaic and return
de-duplicated detections as GPS polygons.

The model call sits behind a small `SegmentationBackend` interface so we can
swap between the Meta Model API, a Baseten-hosted fallback, and a mock used in
tests - without touching the geometry pipeline.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional, Protocol, Sequence

import cv2
import numpy as np
from PIL import Image, ImageDraw
from shapely.geometry import Polygon, mapping, shape

from backend.app.core.config import settings
from backend.app.services import geo
from backend.app.services.tiles import Mosaic

# ------------------------------------------------------------- class config
# Each class groups several prompts; results from all prompts in a class are
# merged together. Colours are used for overlays and in the UI legend.
# SAM 3.1 accepts ONE short noun phrase per request (lists like "a, b" return
# nothing), so every prompt costs one call per window: $2.50 / 1,000 images.
# 16 windows x 4 prompts = 64 calls = ~$0.16 per audit, then cached.
CLASSES: dict[str, dict] = {
    "building": {"prompts": ["rooftop"], "color": "#00E5FF",
                 "min_area_m2": 6, "max_area_m2": 5000},
    "garbage": {"prompts": ["garbage pile"], "color": "#FF3D00",
                "min_area_m2": 4, "max_area_m2": 20000},
    "drainage": {"prompts": ["drainage ditch"], "color": "#FFC400",
                 "min_area_m2": 4, "max_area_m2": 50000},
    "water": {"prompts": ["river"], "color": "#2979FF",
              "min_area_m2": 10, "max_area_m2": 500000},
}


# ------------------------------------------------------------ data classes
@dataclass
class RawMask:
    """One instance returned by a backend, in window pixel coordinates.
    Exactly one of `polygon`, `mask` should be set."""
    prompt: str
    score: float
    polygon: Optional[list[tuple[float, float]]] = None
    mask: Optional[np.ndarray] = None  # bool array, window-sized


@dataclass
class Detection:
    cls: str
    prompt: str
    score: float
    geometry: Polygon            # lon/lat
    area_m2: float = 0.0
    props: dict = field(default_factory=dict)

    def to_feature(self) -> dict:
        return {"type": "Feature", "geometry": mapping(self.geometry),
                "properties": {"class": self.cls, "prompt": self.prompt,
                               "score": round(self.score, 4),
                               "area_m2": round(self.area_m2, 1), **self.props}}

    @classmethod
    def from_feature(cls, f: dict) -> "Detection":
        p = dict(f["properties"])
        return cls(p.pop("class"), p.pop("prompt"), p.pop("score"), shape(f["geometry"]),
                   p.pop("area_m2", 0.0), p)


class SegmentationBackend(Protocol):
    name: str

    def segment(self, image: Image.Image, prompts: Sequence[str],
                origin: tuple[int, int] = (0, 0)) -> list[RawMask]:
        ...


# -------------------------------------------------------------- mask utils
def mask_to_polygons(mask: np.ndarray, min_area_px: float = 20,
                     simplify_px: float = 1.0) -> list[list[tuple[float, float]]]:
    m = (mask > 0).astype(np.uint8)
    contours, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    out = []
    for c in contours:
        if cv2.contourArea(c) < min_area_px:
            continue
        c = cv2.approxPolyDP(c, simplify_px, True)
        if len(c) >= 3:
            out.append([(float(p[0][0]), float(p[0][1])) for p in c])
    return out


def rle_decode(rle: dict) -> np.ndarray:
    """Decode COCO-style RLE ({'size': [h, w], 'counts': [...] or str}).
    Uncompressed counts are handled natively; compressed strings need
    pycocotools."""
    h, w = rle["size"]
    counts = rle["counts"]
    if isinstance(counts, (str, bytes)):
        from pycocotools import mask as mask_utils  # optional dependency
        return mask_utils.decode(rle).astype(bool)
    flat = np.zeros(h * w, dtype=bool)
    pos, val = 0, False
    for c in counts:
        flat[pos:pos + c] = val
        pos += c
        val = not val
    return flat.reshape((w, h)).T  # COCO RLE is column-major


def png_b64_to_mask(data: str) -> np.ndarray:
    img = Image.open(io.BytesIO(base64.b64decode(data))).convert("L")
    return np.array(img) > 127


def image_to_b64(image: Image.Image, fmt: str = "PNG") -> str:
    buf = io.BytesIO()
    image.save(buf, format=fmt)
    return base64.b64encode(buf.getvalue()).decode()


# ---------------------------------------------------------------- backends
class MetaSAMBackend:
    """SAM 3.1 via the Meta Model API (POST /v1/responses, streamed).

    Wire format (dev.meta.ai/docs/sam/reading-segmentation): the output text is
    one line per frame, ``<0f>`` then records ``id<|box;...|><|mask;...|>``.
    Masks are *box-local* rasters; meta-sam-parser gives us their half-open
    source-pixel bounds and decodes the base85 payload.
    """
    name = "meta-sam-3.1"
    max_workers = 8  # windows processed in parallel (team limit is 3,000 RPM)

    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None,
                 model: str = "sam-3.1", timeout: float = 120, retries: int = 3,
                 min_confidence: float = 0.0):
        self.api_key = api_key or settings.meta_api_key
        self.base_url = (base_url or settings.meta_api_base_url or "https://api.meta.ai/v1").rstrip("/")
        self.model = model
        self.timeout = timeout
        self.retries = retries
        self.min_confidence = min_confidence

    # -- request -----------------------------------------------------------
    def payload(self, image: Image.Image, prompt: str) -> dict:
        data_url = "data:image/jpeg;base64," + image_to_b64(image.convert("RGB"), "JPEG")
        return {
            "model": self.model,
            "input": [{"type": "message", "role": "user", "content": [
                {"type": "input_text", "text": prompt},
                {"type": "input_image", "image_url": data_url},
            ]}],
            "metadata": {"include_confidence": "true", "mask_encoding": "one_bit"},
            "stream": True,
        }

    def call(self, image: Image.Image, prompt: str) -> str:
        """Return the raw SAM output text for one image + one prompt."""
        if not self.api_key:
            raise RuntimeError("META_API_KEY is not set (see .env.example)")
        import httpx
        headers = {"Authorization": f"Bearer {self.api_key}", "Accept": "text/event-stream",
                   "Content-Type": "application/json"}
        body = self.payload(image, prompt)
        last_err: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                with httpx.stream("POST", f"{self.base_url}/responses", json=body,
                                  headers=headers, timeout=self.timeout) as r:
                    if r.status_code in (429, 500, 502, 503, 504):
                        raise httpx.HTTPStatusError(f"{r.status_code}", request=r.request, response=r)
                    if r.status_code >= 400:
                        r.read()
                        raise RuntimeError(f"SAM request failed {r.status_code}: {r.text[:500]}")
                    return collect_output_text(r.iter_lines())
            except (httpx.HTTPStatusError, httpx.TransportError) as e:
                last_err = e
                time.sleep(min(2 ** attempt, 20))
        raise RuntimeError(f"SAM request failed after retries: {last_err}")

    # -- response ----------------------------------------------------------
    def segment(self, image: Image.Image, prompts: Sequence[str],
                origin: tuple[int, int] = (0, 0)) -> list[RawMask]:
        out: list[RawMask] = []
        for prompt in prompts:
            out.extend(parse_sam_output(self.call(image, prompt), prompt, self.min_confidence))
        return out


def collect_output_text(lines: Iterable[str]) -> str:
    """Accumulate SSE ``response.output_text.delta`` events into one string.
    If the stream also sends the finished text (content_part.done /
    output_text.done), that complete copy wins."""
    deltas: list[str] = []
    final: Optional[str] = None
    for raw in lines:
        if not raw or not raw.startswith("data:"):
            continue
        data = raw[5:].strip()
        if data == "[DONE]":
            break
        ev = json.loads(data)
        t = ev.get("type")
        if t == "response.output_text.delta":
            deltas.append(ev.get("delta", ""))
        elif t == "response.output_text.done" and ev.get("text") is not None:
            final = ev["text"]
        elif t == "response.content_part.done" and (ev.get("part") or {}).get("type") == "output_text":
            final = ev["part"].get("text", final)
        elif t in ("response.failed", "error"):
            raise RuntimeError(f"SAM stream error: {json.dumps(ev)[:500]}")
        elif t == "response.completed":
            break
    return final if final is not None else "".join(deltas)


def parse_sam_output(text: str, prompt: str, min_confidence: float = 0.0) -> list[RawMask]:
    """Turn SAM 3.1 output text into RawMasks (one polygon per object, in
    source-image pixels)."""
    from meta_sam_parser import CompletedOutcome, decode_mask_to_raster, image_segmentation_format

    if not text.strip():
        return []  # zero matches is a valid, empty result
    parser = image_segmentation_format().create_parser()
    parser.push(text if text.endswith("\n") else text + "\n")
    result = parser.finish(CompletedOutcome()).result
    out: list[RawMask] = []
    for rec in result.records:
        if rec.kind != "mask":
            continue
        conf = rec.confidence if rec.confidence is not None else 1.0
        if conf < min_confidence:
            continue
        m = rec.mask
        raster = np.frombuffer(bytes(decode_mask_to_raster(m)), dtype=np.uint8).reshape(m.height, m.width)
        polys = mask_to_polygons(raster, min_area_px=4)
        if not polys:
            continue
        # keep the largest connected part; small specks are mask noise
        pts = max(polys, key=lambda p: Polygon(p).area if len(p) >= 3 else 0)
        b = rec.bounds
        sx = (b.right - b.left) / m.width
        sy = (b.bottom - b.top) / m.height
        out.append(RawMask(prompt, float(conf),
                           polygon=[(b.left + x * sx, b.top + y * sy) for x, y in pts]))
    return out


class MockBackend:
    """Pretends to be SAM: given ground-truth lon/lat polygons per prompt, it
    returns the parts visible in each window (clipped at window edges, exactly
    like a real model would see them). Used for tests and offline UI work."""
    name = "mock"
    max_workers = 4

    def __init__(self, truth: dict[str, list[Polygon]], mosaic: Mosaic, score: float = 0.9):
        self.truth = truth
        self.mosaic = mosaic
        self.score = score

    def segment(self, image: Image.Image, prompts: Sequence[str],
                origin: tuple[int, int] = (0, 0)) -> list[RawMask]:
        w, h = image.size
        ox = self.mosaic.box.x0 + origin[0]
        oy = self.mosaic.box.y0 + origin[1]
        frame = Polygon([(0, 0), (w, 0), (w, h), (0, h)])
        out = []
        for prompt in prompts:
            for poly in self.truth.get(prompt, []):
                px = geo.lonlat_polygon_to_pixel(poly, ox, oy, self.mosaic.zoom)
                clipped = px.intersection(frame)
                if clipped.is_empty or clipped.area < 1:
                    continue
                for part in getattr(clipped, "geoms", [clipped]):
                    if part.geom_type == "Polygon":
                        out.append(RawMask(prompt, self.score, polygon=list(part.exterior.coords)))
        return out


# ---------------------------------------------------------------- pipeline
def _touches_inner_edge(bounds, ox, oy, w, h, mos_w, mos_h, margin=2.0) -> bool:
    """True if a polygon touches a window edge that is NOT also the mosaic edge.
    Such polygons are cut-off fragments; thanks to the window overlap the same
    object appears whole in a neighbouring window, so we drop the fragment."""
    x0, y0, x1, y1 = bounds
    if x0 <= margin and ox > 0:
        return True
    if y0 <= margin and oy > 0:
        return True
    if x1 >= w - margin and ox + w < mos_w:
        return True
    if y1 >= h - margin and oy + h < mos_h:
        return True
    return False


def segment_mosaic(mosaic: Mosaic, backend: SegmentationBackend,
                   classes: Optional[dict[str, dict]] = None, win: int = 1024,
                   overlap: float = 0.10, iou_thresh: float = 0.5) -> list[Detection]:
    classes = classes or CLASSES
    prompt_to_cls = {p: c for c, cfg in classes.items() for p in cfg["prompts"]}
    prompts = list(prompt_to_cls)
    mos_w, mos_h = mosaic.image.size
    by_cls: dict[str, list[Detection]] = {c: [] for c in classes}

    windows = list(mosaic.windows(win, overlap))

    def run(item):
        ox, oy, crop = item
        return ox, oy, crop.size, backend.segment(crop, prompts, origin=(ox, oy))

    with ThreadPoolExecutor(max_workers=getattr(backend, "max_workers", 1)) as ex:
        results = list(ex.map(run, windows))

    for ox, oy, (w, h), raw_masks in results:
        for rm in raw_masks:
            polys = [rm.polygon] if rm.polygon is not None else mask_to_polygons(rm.mask)
            for pts in polys:
                if len(pts) < 3:
                    continue
                px_poly = Polygon(pts)
                if _touches_inner_edge(px_poly.bounds, ox, oy, w, h, mos_w, mos_h):
                    continue
                ll = geo.pixel_polygon_to_lonlat(pts, mosaic.box.x0 + ox, mosaic.box.y0 + oy,
                                                 mosaic.zoom)
                if not ll.is_valid:
                    ll = ll.buffer(0)
                if ll.is_empty:
                    continue
                cls = prompt_to_cls[rm.prompt]
                a = geo.area_m2(ll)
                cfg = classes[cls]
                if not (cfg.get("min_area_m2", 0) <= a <= cfg.get("max_area_m2", float("inf"))):
                    continue
                by_cls[cls].append(Detection(cls, rm.prompt, rm.score, ll, a))

    out: list[Detection] = []
    for cls, dets in by_cls.items():
        if not dets:
            continue
        keep = geo.merge_duplicates([d.geometry for d in dets], [d.score for d in dets], iou_thresh)
        out.extend(dets[i] for i in keep)
    for i, d in enumerate(out):
        d.props["id"] = f"{d.cls}-{i:05d}"
    return out


# ------------------------------------------------------- caching & output
def cache_key(mosaic: Mosaic, backend: SegmentationBackend, classes: dict) -> str:
    raw = json.dumps({"box": [mosaic.box.x0, mosaic.box.y0, mosaic.box.x1, mosaic.box.y1,
                              mosaic.zoom], "backend": backend.name,
                      "classes": {c: v["prompts"] for c, v in classes.items()}}, sort_keys=True)
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


def segment_mosaic_cached(mosaic: Mosaic, backend: SegmentationBackend,
                          classes: Optional[dict] = None, cache_dir: Optional[Path] = None,
                          **kw) -> list[Detection]:
    classes = classes or CLASSES
    cache_dir = Path(cache_dir or settings.cache_dir / "sam")
    path = cache_dir / f"{cache_key(mosaic, backend, classes)}.geojson"
    if path.exists():
        return [Detection.from_feature(f) for f in json.loads(path.read_text())["features"]]
    dets = segment_mosaic(mosaic, backend, classes, **kw)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(to_feature_collection(dets)))
    return dets


def to_feature_collection(dets: Sequence[Detection]) -> dict:
    return {"type": "FeatureCollection", "features": [d.to_feature() for d in dets]}


def render_overlay(mosaic: Mosaic, dets: Sequence[Detection],
                   classes: Optional[dict] = None, alpha: int = 110) -> Image.Image:
    """Satellite mosaic with semi-transparent coloured masks painted on top."""
    classes = classes or CLASSES
    base = mosaic.image.convert("RGBA")
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    for d in dets:
        hexc = classes.get(d.cls, {}).get("color", "#FFFFFF").lstrip("#")
        rgb = tuple(int(hexc[i:i + 2], 16) for i in (0, 2, 4))
        px = geo.lonlat_polygon_to_pixel(d.geometry, mosaic.box.x0, mosaic.box.y0, mosaic.zoom)
        for part in getattr(px, "geoms", [px]):
            pts = list(part.exterior.coords)
            draw.polygon(pts, fill=rgb + (alpha,), outline=rgb + (255,))
    return Image.alpha_composite(base, layer)
