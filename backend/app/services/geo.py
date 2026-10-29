"""Geospatial core: Web Mercator tile math, pixel <-> GPS conversion,
duplicate merging across overlapping windows, and metric buffers.

Conventions
-----------
- "Global pixel" = pixel coordinate in the Web Mercator world image at a given
  zoom, using 256 px XYZ tiles (the scheme Mapbox/OSM raster tiles use).
- Geographic coordinates are (lon, lat) in EPSG:4326, matching GeoJSON order.
- All distances/areas are computed in UTM 37S (EPSG:32737), metric for Nairobi.
"""
from __future__ import annotations

import heapq
import math
from dataclasses import dataclass
from functools import lru_cache
from typing import Iterable, Sequence

import numpy as np
from pyproj import Transformer
from shapely.geometry import Polygon, box
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform
from shapely.strtree import STRtree

TILE_SIZE = 256
EARTH_CIRCUMFERENCE_M = 40_075_016.686
MAX_LAT = 85.05112878


# ---------------------------------------------------------------- tile math
def lonlat_to_global_px(lon: float, lat: float, zoom: int) -> tuple[float, float]:
    lat = max(min(lat, MAX_LAT), -MAX_LAT)
    world = TILE_SIZE * (2 ** zoom)
    x = (lon + 180.0) / 360.0 * world
    s = math.sin(math.radians(lat))
    y = (0.5 - math.log((1 + s) / (1 - s)) / (4 * math.pi)) * world
    return x, y


def global_px_to_lonlat(x: float, y: float, zoom: int) -> tuple[float, float]:
    world = TILE_SIZE * (2 ** zoom)
    lon = x / world * 360.0 - 180.0
    n = math.pi - 2 * math.pi * y / world
    lat = math.degrees(math.atan(math.sinh(n)))
    return lon, lat


def meters_per_pixel(lat: float, zoom: int) -> float:
    return EARTH_CIRCUMFERENCE_M * math.cos(math.radians(lat)) / (TILE_SIZE * 2 ** zoom)


@dataclass(frozen=True)
class PixelBox:
    """Axis-aligned box in global pixel space at `zoom`."""
    x0: float
    y0: float
    x1: float
    y1: float
    zoom: int

    @property
    def width(self) -> int:
        return int(round(self.x1 - self.x0))

    @property
    def height(self) -> int:
        return int(round(self.y1 - self.y0))


def square_around(lon: float, lat: float, side_m: float, zoom: int) -> PixelBox:
    """Pixel box of a square of `side_m` metres centred on (lon, lat)."""
    cx, cy = lonlat_to_global_px(lon, lat, zoom)
    half = side_m / meters_per_pixel(lat, zoom) / 2
    return PixelBox(math.floor(cx - half), math.floor(cy - half),
                    math.ceil(cx + half), math.ceil(cy + half), zoom)


def tiles_covering(pb: PixelBox, tile_size: int = TILE_SIZE) -> list[tuple[int, int, int]]:
    """Tiles (z, x, y) of `tile_size` px needed to cover a pixel box. With the
    default 256 these are standard XYZ tiles; larger sizes are "virtual" tiles
    fetched as single static images."""
    tx0, ty0 = int(pb.x0 // tile_size), int(pb.y0 // tile_size)
    tx1, ty1 = int((pb.x1 - 1) // tile_size), int((pb.y1 - 1) // tile_size)
    return [(pb.zoom, x, y) for y in range(ty0, ty1 + 1) for x in range(tx0, tx1 + 1)]


def window_offsets(width: int, height: int, win: int = 1024, overlap: float = 0.10) -> list[tuple[int, int]]:
    """Top-left offsets of `win`x`win` windows covering a width x height image
    with fractional `overlap`. The last row/column is snapped to the edge so the
    whole image is covered without padding."""
    def axis(length: int) -> list[int]:
        if length <= win:
            return [0]
        step = max(1, int(win * (1 - overlap)))
        offs = list(range(0, length - win, step))
        offs.append(length - win)
        return sorted(set(offs))
    return [(x, y) for y in axis(height) for x in axis(width)]


# ------------------------------------------------------ pixel <-> geographic
def pixel_polygon_to_lonlat(poly_px: Sequence[tuple[float, float]], origin_x: float,
                            origin_y: float, zoom: int) -> Polygon:
    """Convert a polygon given in *local* pixel coords (relative to a mosaic or
    window whose top-left is at global pixel (origin_x, origin_y))."""
    pts = [global_px_to_lonlat(origin_x + x, origin_y + y, zoom) for x, y in poly_px]
    return Polygon(pts)


def lonlat_polygon_to_pixel(poly: BaseGeometry, origin_x: float, origin_y: float,
                            zoom: int) -> BaseGeometry:
    def f(xs, ys, zs=None):
        out = [lonlat_to_global_px(x, y, zoom) for x, y in zip(xs, ys)]
        return [p[0] - origin_x for p in out], [p[1] - origin_y for p in out]
    return transform(f, poly)


# ------------------------------------------------------------ projections
@lru_cache(maxsize=8)
def _transformer(src: int, dst: int) -> Transformer:
    return Transformer.from_crs(src, dst, always_xy=True)


def to_utm(geom: BaseGeometry, epsg: int = 32737) -> BaseGeometry:
    return transform(_transformer(4326, epsg).transform, geom)


def to_wgs84(geom: BaseGeometry, epsg: int = 32737) -> BaseGeometry:
    return transform(_transformer(epsg, 4326).transform, geom)


def buffer_m(geom: BaseGeometry, metres: float, epsg: int = 32737) -> BaseGeometry:
    """Buffer a WGS84 geometry by metres (computed in UTM), returned in WGS84."""
    return to_wgs84(to_utm(geom, epsg).buffer(metres), epsg)


def area_m2(geom: BaseGeometry, epsg: int = 32737) -> float:
    return to_utm(geom, epsg).area


# --------------------------------------------------------- duplicate merging
def iou(a: BaseGeometry, b: BaseGeometry) -> float:
    if not a.intersects(b):
        return 0.0
    inter = a.intersection(b).area
    union = a.union(b).area
    return inter / union if union else 0.0


def merge_duplicates(polys: Sequence[BaseGeometry], scores: Sequence[float],
                     iou_thresh: float = 0.5, contain_thresh: float = 0.8,
                     max_grow: float = 4.0) -> list[int]:
    """Greedy non-maximum suppression on polygons. Returns indices to keep.

    Polygons are visited from highest to lowest score. A candidate is dropped if
    its IoU with a kept polygon exceeds `iou_thresh`, or if it lies mostly
    (`contain_thresh`) inside a kept polygon. If instead a kept polygon lies
    mostly inside the candidate (a fragment of the same object), the more
    complete candidate replaces it - unless the candidate is more than
    `max_grow` times larger, which guards against one oversized mask (a whole
    block) swallowing the individual buildings inside it.
    """
    order = sorted(range(len(polys)), key=lambda i: scores[i], reverse=True)
    valid = [p if p.is_valid else p.buffer(0) for p in polys]
    tree = STRtree(valid)
    keep: set[int] = set()
    for i in order:
        a = valid[i]
        drop = False
        replace: list[int] = []
        for j in tree.query(a):
            j = int(j)
            if j == i or j not in keep:
                continue
            b = valid[j]
            if not a.intersects(b):
                continue
            inter = a.intersection(b).area
            if iou(a, b) > iou_thresh or inter / (a.area or 1e-12) > contain_thresh:
                drop = True
                break
            if inter / (b.area or 1e-12) > contain_thresh and a.area <= max_grow * b.area:
                replace.append(j)
        if drop:
            continue
        keep.difference_update(replace)
        keep.add(i)
    return sorted(keep)


def bbox_polygon(lon0: float, lat0: float, lon1: float, lat1: float) -> Polygon:
    return box(min(lon0, lon1), min(lat0, lat1), max(lon0, lon1), max(lat0, lat1))


def pixelbox_to_lonlat_bounds(pb: PixelBox) -> tuple[float, float, float, float]:
    """(west, south, east, north) of a pixel box."""
    w, n = global_px_to_lonlat(pb.x0, pb.y0, pb.zoom)
    e, s = global_px_to_lonlat(pb.x1, pb.y1, pb.zoom)
    return w, s, e, n


# ------------------------------------------------------------ terrain grids
_D8 = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]


def fill_depressions(z: np.ndarray, eps: float = 1e-3) -> np.ndarray:
    """Priority-flood (Barnes et al. 2014): raise every pit to the level at
    which water would spill out, plus a tiny slope (eps per cell) so flats
    still drain. `filled - z` is how deep water would pond."""
    h, w = z.shape
    filled = z.astype(float).copy()
    seen = np.zeros(z.shape, bool)
    heap = []
    for r in range(h):
        for c in range(w):
            if r in (0, h - 1) or c in (0, w - 1):
                heap.append((filled[r, c], r, c))
                seen[r, c] = True
    heapq.heapify(heap)
    while heap:
        e, r, c = heapq.heappop(heap)
        for dr, dc in _D8:
            rr, cc = r + dr, c + dc
            if 0 <= rr < h and 0 <= cc < w and not seen[rr, cc]:
                seen[rr, cc] = True
                filled[rr, cc] = max(filled[rr, cc], e + eps)
                heapq.heappush(heap, (filled[rr, cc], rr, cc))
    return filled


def flow_accumulation(filled: np.ndarray) -> np.ndarray:
    """D8 flow accumulation: how many cells drain through each cell
    (including itself). Expects a depression-filled grid."""
    h, w = filled.shape
    padded = np.pad(filled, 1, constant_values=np.inf)
    best = np.zeros((h, w))
    receiver = np.full((h, w), -1)
    idx = np.arange(h * w).reshape(h, w)
    pidx = np.pad(idx, 1, constant_values=-1)
    for dr, dc in _D8:
        nb = padded[1 + dr:1 + dr + h, 1 + dc:1 + dc + w]
        drop = (filled - nb) / math.hypot(dr, dc)
        better = drop > best
        best[better] = drop[better]
        receiver[better] = pidx[1 + dr:1 + dr + h, 1 + dc:1 + dc + w][better]
    acc = np.ones(h * w)
    rec = receiver.ravel()
    for i in np.argsort(-filled.ravel(), kind="stable"):
        if rec[i] >= 0:
            acc[rec[i]] += acc[i]
    return acc.reshape(h, w)
