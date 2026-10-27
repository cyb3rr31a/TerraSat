"""Analyzers turn detections + context layers into profile-specific metrics.

Every profile names one analyzer. All analyzers share one signature and return
an AnalysisResult, so the API, UI, memo writer and exports never need to know
which use case they are serving.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Callable, Sequence

from shapely.geometry import Point, mapping, shape
from shapely.ops import unary_union
from shapely.strtree import STRtree

from backend.app.core.config import settings
from backend.app.services import geo
from backend.app.services.exposure import compute_exposure
from backend.app.services.sam_service import Detection


@dataclass
class AnalysisContext:
    detections: Sequence[Detection]
    layers: dict[str, list[dict]]
    bounds: tuple[float, float, float, float]   # west, south, east, north
    center: tuple[float, float]                 # lon, lat
    params: dict


@dataclass
class AnalysisResult:
    profile_id: str
    summary: dict
    geojson: dict


Analyzer = Callable[[AnalysisContext], tuple[dict, list[dict]]]
ANALYZERS: dict[str, Analyzer] = {}


def register(name: str):
    def deco(fn: Analyzer) -> Analyzer:
        ANALYZERS[name] = fn
        return fn
    return deco


def run_analyzer(profile, ctx: AnalysisContext) -> AnalysisResult:
    if profile.analyzer not in ANALYZERS:
        raise KeyError(f"Profile {profile.id!r} uses unknown analyzer {profile.analyzer!r}")
    ctx.params = {**profile.params, **(ctx.params or {})}
    summary, features = ANALYZERS[profile.analyzer](ctx)
    summary = {"profile": profile.id,
               "detections_by_class": dict(Counter(d.cls for d in ctx.detections)),
               **summary}
    return AnalysisResult(profile.id, summary, {"type": "FeatureCollection", "features": features})


def _by_class(dets: Sequence[Detection], cls: str) -> list[Detection]:
    return [d for d in dets if d.cls == cls]


def _layer_features(features: list[dict], cls: str) -> list[dict]:
    return [{"type": "Feature", "geometry": f["geometry"],
             "properties": {"class": cls, **f.get("properties", {})}} for f in features]


# ------------------------------------------------------------------- flood
@register("flood_exposure")
def flood_exposure(ctx: AnalysisContext):
    p = ctx.params
    buildings = _by_class(ctx.detections, "building")
    res = compute_exposure(buildings, ctx.layers.get("osm_waterways", []), ctx.bounds,
                           buffer_m=p.get("riparian_buffer_m"),
                           persons_per_structure=p.get("persons_per_structure"))
    others = [d.to_feature() for d in ctx.detections if d.cls != "building"]
    summary = dict(res.summary)
    summary["garbage_piles_detected"] = len(_by_class(ctx.detections, "garbage"))
    if not ctx.layers.get("osm_waterways"):
        summary["warning"] = "No waterways layer for this area - run scripts/fetch_osm_layers.py"
    return summary, res.to_geojson()["features"] + others


# ------------------------------------------------------- solar & mini-grid
@register("solar_minigrid")
def solar_minigrid(ctx: AnalysisContext):
    p = ctx.params
    epsg = settings.utm_epsg
    center_utm = geo.to_utm(Point(*ctx.center), epsg)
    buildings = _by_class(ctx.detections, "building")
    panels = _by_class(ctx.detections, "solar_panel")
    tanks = _by_class(ctx.detections, "water_tank")

    b_utm = [geo.to_utm(b.geometry, epsg) for b in buildings]
    panel_utm = [geo.to_utm(s.geometry, epsg) for s in panels]
    panel_tree = STRtree(panel_utm) if panel_utm else None

    # a building "has solar" if any detected panel overlaps its roof
    for b, g in zip(buildings, b_utm):
        has = bool(panel_tree is not None and any(
            g.intersects(panel_utm[int(j)]) for j in panel_tree.query(g)))
        b.props["has_solar"] = has
        b.props["distance_to_center_m"] = round(g.centroid.distance(center_utm), 1)

    # grid proximity
    lines = ctx.layers.get("osm_power_lines", [])
    line_union = unary_union([geo.to_utm(shape(f["geometry"]), epsg) for f in lines]) if lines else None
    grid_dist = round(center_utm.distance(line_union), 1) if line_union is not None else None
    for b, g in zip(buildings, b_utm):
        b.props["distance_to_power_line_m"] = (round(g.distance(line_union), 1)
                                               if line_union is not None else None)

    hh = float(p.get("households_per_building", 1.0))
    capex = p.get("capex_usd", {})
    rings = {}
    ring_features = []
    for name, r in p.get("rings_m", {}).items():
        inside = [b for b in buildings if b.props["distance_to_center_m"] <= r]
        with_solar = sum(b.props["has_solar"] for b in inside)
        unserved_hh = (len(inside) - with_solar) * hh
        rings[name] = {
            "radius_m": r,
            "buildings": len(inside),
            "buildings_with_solar": with_solar,
            "solar_penetration_pct": round(100 * with_solar / len(inside), 1) if inside else 0.0,
            "unserved_households_est": round(unserved_hh),
            "capex_per_unserved_household_usd": {
                k: (round(v / unserved_hh, 2) if unserved_hh else None) for k, v in capex.items()},
        }
        ring_geom = geo.to_wgs84(center_utm.buffer(r), epsg)
        ring_features.append({"type": "Feature", "geometry": mapping(ring_geom),
                              "properties": {"class": "ring", "name": name, "radius_m": r}})

    # verdict (spec decision tree)
    inner = min(p.get("rings_m", {"inner": 600}).items(), key=lambda kv: kv[1])[0] if rings else None
    dense = bool(inner and rings[inner]["buildings"] >= p.get("dense_min_buildings", 100))
    near_grid = grid_dist is not None and grid_dist <= p.get("grid_near_m", 600)
    if grid_dist is None:
        verdict = "UNKNOWN_GRID - add power line layer"
    elif dense and near_grid:
        verdict = "GRID_EXTENSION_CANDIDATE"
    elif dense:
        verdict = "MINIGRID_CANDIDATE"
    else:
        verdict = "STANDALONE_SOLAR_RECOMMENDED"

    summary = {
        "rings": rings,
        "distance_center_to_power_line_m": grid_dist,
        "water_tanks_detected": len(tanks),
        "verdict": verdict,
    }
    if not lines:
        summary["warning"] = "No power line layer for this area - run scripts/fetch_osm_layers.py power_lines"
    features = ([b.to_feature() for b in buildings] + [d.to_feature() for d in panels + tanks]
                + ring_features + _layer_features(lines, "power_line"))
    return summary, features
