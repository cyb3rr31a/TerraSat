"""Analyzers turn detections + context layers into profile-specific metrics.

Every profile names one analyzer. All analyzers share one signature and return
an AnalysisResult, so the API, UI, memo writer and exports never need to know
which use case they are serving.
"""
from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field
from typing import Callable, Optional, Sequence

import numpy as np
import shapely
from shapely.geometry import Point, box, mapping, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import linemerge, unary_union
from shapely.strtree import STRtree

from backend.app.core.config import settings
from backend.app.services import geo
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
# Watercourses the riparian rule applies to. Drains and ditches are kept for
# the choke-point analysis but don't get a riparian reserve.
RIPARIAN_TYPES = {"river", "stream", "canal"}


@dataclass
class ExposureResult:
    summary: dict
    buildings: list[Detection]
    riparian_zone: Optional[BaseGeometry]          # lon/lat, for the map
    waterways: list[dict] = field(default_factory=list)

    def to_geojson(self) -> dict:
        feats = [b.to_feature() for b in self.buildings]
        if self.riparian_zone is not None and not self.riparian_zone.is_empty:
            feats.append({"type": "Feature", "geometry": mapping(self.riparian_zone),
                          "properties": {"class": "riparian_zone",
                                         "buffer_m": self.summary["buffer_m"]}})
        feats.extend(self.waterways)
        return {"type": "FeatureCollection", "features": feats}


def _is_riparian(f: dict) -> bool:
    p = f.get("properties", {})
    if p.get("tunnel") in ("culvert", "yes"):
        return False  # underground sections have no open bank
    return p.get("waterway") in RIPARIAN_TYPES or p.get("natural") == "water"


def compute_exposure(buildings: Sequence[Detection], waterways: Sequence[dict],
                     bounds: tuple[float, float, float, float],
                     buffer_m: Optional[float] = None,
                     baseline: Optional[Sequence[BaseGeometry]] = None,
                     baseline_overlap: float = 0.2,
                     persons_per_structure: Optional[float] = None,
                     epsg: Optional[int] = None) -> ExposureResult:
    """Annotate buildings and summarise exposure inside the audit `bounds`."""
    buffer_m = settings.riparian_buffer_m if buffer_m is None else buffer_m
    epsg = epsg or settings.utm_epsg
    audit_utm = geo.to_utm(box(*bounds), epsg)

    river_feats = [f for f in waterways if _is_riparian(f)]
    river_utm = [geo.to_utm(shape(f["geometry"]), epsg) for f in river_feats]
    river_union = unary_union(river_utm) if river_utm else None
    zone_utm = river_union.buffer(buffer_m).intersection(audit_utm) if river_union else None

    base_utm = [geo.to_utm(g, epsg) for g in (baseline or [])]
    base_tree = STRtree(base_utm) if base_utm else None

    exposed, exposed_new, new_total = 0, 0, 0
    exposed_area = 0.0
    for b in buildings:
        g = geo.to_utm(b.geometry, epsg)
        dist = g.distance(river_union) if river_union is not None else None
        inside = bool(zone_utm is not None and g.intersects(zone_utm))
        is_new = None
        if base_tree is not None:
            is_new = True
            for j in base_tree.query(g):
                if g.intersection(base_utm[int(j)]).area >= baseline_overlap * g.area:
                    is_new = False
                    break
            new_total += int(is_new)
        b.props.update({
            "in_riparian_zone": inside,
            "distance_to_river_m": None if dist is None else round(dist, 1),
            "new_since_baseline": is_new,
            "height_above_stream_m": None,
        })
        if inside:
            exposed += 1
            exposed_area += b.area_m2
            exposed_new += int(bool(is_new))

    river_len_m = river_union.intersection(audit_utm).length if river_union is not None else 0.0
    summary = {
        "buffer_m": buffer_m,
        "buildings_total": len(buildings),
        "buildings_in_riparian_zone": exposed,
        "pct_in_riparian_zone": round(100 * exposed / len(buildings), 1) if buildings else 0.0,
        "new_buildings_total": new_total if base_tree is not None else None,
        "new_buildings_in_riparian_zone": exposed_new if base_tree is not None else None,
        "exposed_footprint_m2": round(exposed_area, 1),
        "river_length_in_area_m": round(river_len_m, 1),
        "exposed_per_100m_riverbank": round(exposed / (river_len_m / 100), 2) if river_len_m else None,
        "est_people_exposed": round(exposed * persons_per_structure) if persons_per_structure else None,
    }
    zone_ll = geo.to_wgs84(zone_utm, epsg) if zone_utm is not None else None
    river_out = [{"type": "Feature", "geometry": f["geometry"],
                  "properties": {"class": "waterway", **f.get("properties", {})}}
                 for f in waterways]
    return ExposureResult(summary, list(buildings), zone_ll, river_out)


def combine_with_baseline(sam_buildings: list[Detection], baseline: list[dict]) -> list[Detection]:
    """SAM detections plus every baseline footprint SAM did not find.

    SAM 3.1 finds formal buildings well but misses most roofs in dense informal
    settlements (live test, Mathare, Oct 28), so footprints from the baseline
    fill those gaps. Each building keeps a `source` so the UI can show which is which.
    """
    for d in sam_buildings:
        d.props["source"] = "sam"
    if not baseline:
        return list(sam_buildings)
    tree = STRtree([d.geometry for d in sam_buildings]) if sam_buildings else None
    out = list(sam_buildings)
    for f in baseline:
        g = shape(f["geometry"])
        if g.geom_type != "Polygon":
            continue
        if tree is not None and any(g.intersects(sam_buildings[int(j)].geometry) for j in tree.query(g)):
            continue
        out.append(Detection("building", "baseline", 1.0, g, geo.area_m2(g), {"source": "baseline"}))
    return out


def flow_grids(dem) -> tuple[np.ndarray, np.ndarray]:
    """How deep water would pond in each cell, and how many hectares drain through it."""
    filled = geo.fill_depressions(dem.z)
    return filled - dem.z, geo.flow_accumulation(filled) * dem.cell_area_m2 / 1e4


def add_terrain(buildings: list[Detection], waterways: list[dict], dem, p: dict, grids) -> dict:
    """Height above the nearest river, ponding dips and overland flow paths,
    sampled at each building's centre from the elevation grid."""
    depth, upstream_ha = grids
    pts = shapely.points([b.geometry.centroid.coords[0] for b in buildings])
    r, c = dem.cells(shapely.get_x(pts), shapely.get_y(pts))
    rivers = unary_union([shape(f["geometry"]) for f in waterways if _is_riparian(f)])
    hand = None
    if not rivers.is_empty:
        ends = shapely.get_point(shapely.shortest_line(pts, rivers), 1)  # nearest point on a river
        rr, rc = dem.cells(shapely.get_x(ends), shapely.get_y(ends))
        hand = dem.z[r, c] - dem.z[rr, rc]
    # Where OpenStreetMap maps no river nearby, measure to drainage lines derived
    # from the DEM instead (2024 test: east Nairobi had 824 damaged structures
    # and no mapped river; drainage lines caught ~60% of them as high/medium).
    channel = upstream_ha >= p.get("channel_min_ha", 200)
    if channel.any():
        cr, cc = np.nonzero(channel)
        clon, clat = dem.west + (cc + 0.5) * dem.dx, dem.north - (cr + 0.5) * dem.dy
        near = STRtree(shapely.points(clon, clat)).nearest(pts)
        kx = 111_320 * math.cos(math.radians(float(np.mean(clat))))
        d_ch = np.hypot((shapely.get_x(pts) - clon[near]) * kx, (shapely.get_y(pts) - clat[near]) * 110_574)
        h_ch = dem.z[r, c] - dem.z[cr[near], cc[near]]
    for i, b in enumerate(buildings):
        pr = b.props
        pr["height_above_stream_m"] = None if hand is None else round(float(hand[i]), 1)
        pr["watercourse"] = "osm" if pr.get("distance_to_river_m") is not None else None
        osm_d = pr.get("distance_to_river_m")
        if channel.any() and (osm_d is None or osm_d > p.get("channel_fallback_m", 500)):
            pr.update(distance_to_river_m=round(float(d_ch[i]), 1),
                      height_above_stream_m=round(float(h_ch[i]), 1), watercourse="dem_channel")
        pr["in_dip"] = bool(depth[r[i], c[i]] >= p.get("dip_depth_m", 0.5))
        pr["on_flow_path"] = bool(upstream_ha[r[i], c[i]] >= p.get("flow_path_min_ha", 5))
    low = p.get("low_lying_m", 3)
    return {
        "buildings_measured_to_dem_channels": sum(b.props["watercourse"] == "dem_channel" for b in buildings),
        "dem": "Copernicus GLO-30, ~30 m (a surface model: includes roofs and trees, so approximate in dense areas)",
        "buildings_low_lying": sum(1 for b in buildings if (b.props["height_above_stream_m"] or 1e9) <= low),
        "buildings_in_dips": sum(b.props["in_dip"] for b in buildings),
        "buildings_on_flow_paths": sum(b.props["on_flow_path"] for b in buildings),
    }


def score_risk(buildings: list[Detection], p: dict) -> dict:
    """River-flood risk class per building, plus a separate surface-water flag.

    Rules (from `risk_rules` in the profile) combine distance to the river with
    height above it, e.g. high = within 30 m, or within 60 m and under 1 m above
    the river. Calibrated on UNOSAT's 2024 damage at Mukuru, where distance was
    the strongest signal and height added to it near the river. The 2024 flood
    extent itself is not an input, so it can still be used as a check.
    Dips and flow paths (rain ponding away from rivers) are a separate flag.
    """
    rules = p.get("risk_rules", {})

    def matches(pr, rule):
        d, h = pr.get("distance_to_river_m"), pr.get("height_above_stream_m")
        if d is None or d > rule["within_m"]:
            return False
        return "below_m" not in rule or (h is not None and h < rule["below_m"])

    for b in buildings:
        pr = b.props
        pr["risk"] = next((level for level in ("high", "medium")
                           if any(matches(pr, r) for r in rules.get(level, []))), "low")
        pr["surface_water_risk"] = bool(pr.get("in_dip") or pr.get("on_flow_path"))
    counts = Counter(b.props["risk"] for b in buildings)
    return {"high": counts["high"], "medium": counts["medium"], "low": counts["low"],
            "surface_water_flagged": sum(b.props["surface_water_risk"] for b in buildings)}


CHOKE_REPORT_TYPES = {"blocked_drain", "flooding", "garbage", "collapsed_bridge"}


def flood_2024_checker(unosat: list[dict], near_m: float = 20) -> Callable[[Point], Optional[bool]]:
    """Returns check(point): inside (or within near_m of) the 2024 flood extent?
    None where the 2024 image was clouded or didn't reach, so nobody reads "no flood" there."""
    by_kind: dict[str, list] = {}
    for f in unosat:
        by_kind.setdefault(f["properties"].get("kind"), []).append(shape(f["geometry"]))
    hit = lambda k, pt, d=0.0: any(g.distance(pt) <= d for g in by_kind.get(k, []))  # distance: buffering 75k-vertex extents runs out of memory

    def check(pt: Point) -> Optional[bool]:
        if not hit("analysis_extent", pt) or hit("cloud", pt):
            return None
        return hit("flood_extent", pt, near_m / 111_320)
    return check


def find_choke_points(roads: list[dict], waterways: list[dict], dem, upstream_ha, buildings: list[Detection],
                      unosat: list[dict], bounds, p: dict, epsg: int) -> list[dict]:
    """Places where water has to pass under a road (a culvert or bridge) and can back up when it blocks.

    Two kinds:
      mapped     a road crosses a waterway mapped in OpenStreetMap (rivers, streams, drains, ditches)
      flow_path  a road crosses a DEM flow path with no mapped waterway (often an unmapped drain):
                 a peak in upstream area along the road, falling away on both sides
    """
    cfg = p.get("choke_points", {})
    min_ha, merge_m, near_m = cfg.get("min_upstream_ha", 20), cfg.get("merge_m", 60), cfg.get("near_m", 150)
    audit = box(*bounds)
    road_feats = [f for f in roads if f["geometry"]["type"] == "LineString"]
    road_lines = [shape(f["geometry"]) for f in road_feats]
    if not road_lines:
        return []
    road_tree = STRtree(road_lines)
    cands = []  # (lon/lat point, kind)
    for w in waterways:
        g = shape(w["geometry"])
        if g.geom_type != "LineString":
            continue
        for j in road_tree.query(g, predicate="intersects"):
            x = g.intersection(road_lines[j])
            cands += [(pt, "mapped") for pt in getattr(x, "geoms", [x])
                      if pt.geom_type == "Point" and audit.contains(pt)]
    up_at = lambda lon, lat: upstream_ha[dem.cells(lon, lat)] if dem is not None else np.zeros(np.size(lon))
    if dem is not None:
        step = min(10.0, dem.dy * 110_574 / 2)  # metres between samples along a road: under half a DEM cell
        merged = linemerge(unary_union(road_lines))  # whole streets: OSM splits roads at bridges
        for line in getattr(merged, "geoms", [merged]):
            n = int(geo.to_utm(line, epsg).length // step) + 1
            if n < 9:
                continue
            pts = shapely.line_interpolate_point(line, np.linspace(0, 1, n), normalized=True)
            a = up_at(shapely.get_x(pts), shapely.get_y(pts))
            for i in range(4, n - 4):
                if (a[i] >= min_ha and a[i] == a[i - 3:i + 4].max()
                        and max(a[i - 4], a[i + 4]) < 0.5 * a[i] and audit.contains(pts[i])):
                    cands.append((pts[i], "flow_path"))
    if not cands:
        return []
    # the DEM line can sit a cell off the mapped one, so take the best of the 3x3 cells around each point
    pad = np.pad(upstream_ha, 1, mode="edge") if dem is not None else None
    best = (np.max([pad[i:i + upstream_ha.shape[0], j:j + upstream_ha.shape[1]] for i in range(3) for j in range(3)],
                   axis=0) if dem is not None else None)
    lons, lats = np.array([c[0].x for c in cands]), np.array([c[0].y for c in cands])
    ups = best[dem.cells(lons, lats)] if dem is not None else np.zeros(len(cands))
    kept: list[list] = []  # [utm point, lon/lat point, kind, upstream]
    for i in np.argsort(-ups, kind="stable"):
        u = geo.to_utm(cands[i][0], epsg)
        twin = next((k for k in kept if k[0].distance(u) <= merge_m), None)
        if twin is None:
            kept.append([u, cands[i][0], cands[i][1], float(ups[i])])
        elif cands[i][1] == "mapped":
            twin[2] = "mapped"
    b_utm = [geo.to_utm(b.geometry.centroid, epsg) for b in buildings
             if b.props.get("risk") in ("high", "medium")]
    b_tree = STRtree(b_utm) if b_utm else None
    ww_named = [(shape(w["geometry"]), w["properties"]) for w in waterways]
    in_2024 = flood_2024_checker(unosat)
    feats = []
    for u, pt, kind, up in kept:
        road = road_feats[int(road_tree.nearest(pt))]["properties"]
        ww = min(ww_named, key=lambda gp: gp[0].distance(pt), default=None)
        ww = ww[1] if ww and geo.to_utm(ww[0], epsg).distance(u) <= 50 else {}
        feats.append({"type": "Feature", "geometry": mapping(pt), "properties": {
            "class": "choke_point", "kind": kind, "upstream_ha": round(up),
            "road": road.get("name") or road.get("highway"), "road_is_bridge": road.get("bridge") == "yes",
            "watercourse": ww.get("name") or ww.get("waterway") or ww.get("natural"),
            "buildings_at_risk_nearby": len(b_tree.query(u.buffer(near_m), predicate="intersects")) if b_tree else 0,
            "in_2024_flood": in_2024(pt)}})
    return rank_choke_points(feats, [], p)


def rank_choke_points(points: list[dict], reports: list[dict], p: dict, epsg: Optional[int] = None) -> list[dict]:
    """Score 0-1 from upstream area (log scale), at-risk buildings nearby and residents' reports
    nearby (up to 3 count), weighted as the profile says. Re-run whenever new reports come in.
    The 2024 flood is kept out of the score so it can check the ranking."""
    if not points:
        return []
    cfg = p.get("choke_points", {})
    w = {"upstream": 0.4, "buildings": 0.3, "reports": 0.3, **cfg.get("weights", {})}
    near_m, epsg = cfg.get("near_m", 150), epsg or settings.utm_epsg
    rep = [geo.to_utm(Point(r["lon"], r["lat"]), epsg) for r in reports
           if r.get("lon") is not None and r.get("issue_type") in CHOKE_REPORT_TYPES and r.get("status") != "dismissed"]
    max_up = max(math.log1p(f["properties"]["upstream_ha"]) for f in points) or 1
    max_b = max(f["properties"]["buildings_at_risk_nearby"] for f in points) or 1
    for f in points:
        pr = f["properties"]
        u = geo.to_utm(shape(f["geometry"]), epsg)
        pr["reports_nearby"] = sum(r.distance(u) <= near_m for r in rep)
        pr["score"] = round(w["upstream"] * math.log1p(pr["upstream_ha"]) / max_up
                            + w["buildings"] * pr["buildings_at_risk_nearby"] / max_b
                            + w["reports"] * min(pr["reports_nearby"], 3) / 3, 3)
    points.sort(key=lambda f: -f["properties"]["score"])
    for i, f in enumerate(points, 1):
        f["properties"]["rank"] = i
    return points


def choke_point_summary(points: list[dict], top: int = 10) -> dict:
    """Counts, the top few, and a check: are the top-ranked ones where the 2024 flood was?"""
    seen = [f["properties"]["in_2024_flood"] for f in points if f["properties"]["in_2024_flood"] is not None]
    seen_top = [f["properties"]["in_2024_flood"] for f in points[:top] if f["properties"]["in_2024_flood"] is not None]
    pct = lambda xs: round(100 * sum(xs) / len(xs), 1) if xs else None
    keys = ("rank", "kind", "road", "watercourse", "upstream_ha", "buildings_at_risk_nearby", "reports_nearby", "score")
    return {"found": len(points), "by_kind": dict(Counter(f["properties"]["kind"] for f in points)),
            "top": [{**{k: f["properties"][k] for k in keys}, "lon": f["geometry"]["coordinates"][0],
                     "lat": f["geometry"]["coordinates"][1]} for f in points[:5]],
            "check_2024": {"top_in_2024_flood_pct": pct(seen_top), "all_in_2024_flood_pct": pct(seen),
                           "top_n": top, "note": "share of points the 2024 image could see"}}


def compare_with_2024(buildings: list[Detection], unosat: list[dict], riparian_zone,
                      bounds, epsg: int, match_m: float = 10.0) -> Optional[dict]:
    """Flag buildings inside the UNOSAT 1 May 2024 flood extent and check how
    well today's exposure flags would have caught the structures UNOSAT
    recorded as affected. Areas hidden by cloud count as "not observed"."""
    if not unosat:
        return None
    audit = geo.to_utm(box(*bounds), epsg)
    union = lambda kind: unary_union([geo.to_utm(shape(f["geometry"]), epsg) for f in unosat
                                      if f["properties"].get("kind") == kind]).intersection(audit)
    flood, cloud, mapped = union("flood_extent"), union("cloud"), union("analysis_extent")
    observed = mapped.difference(cloud)
    for b in buildings:
        b.props["in_2024_flood"] = bool(geo.to_utm(b.geometry, epsg).intersects(flood))
    affected = [geo.to_utm(shape(f["geometry"]), epsg) for f in unosat
                if f["properties"].get("kind") == "affected_structure"]
    affected = [pt for pt in affected if audit.contains(pt)]
    zone = geo.to_utm(riparian_zone, epsg) if riparian_zone is not None else None
    caught = sum(1 for pt in affected if zone is not None and pt.distance(zone) <= match_m)
    # which risk class did each damaged structure get? (nearest building within match_m)
    by_risk = None
    if affected and buildings and "risk" in buildings[0].props:
        tree = STRtree([b.geometry for b in buildings])
        pts_ll = [geo.to_wgs84(pt, epsg) for pt in affected]
        hit = tree.query_nearest(pts_ll, max_distance=match_m / 111_320, all_matches=False)
        matched = Counter(buildings[int(j)].props["risk"] for j in hit[1])
        total = Counter(b.props["risk"] for b in buildings)
        by_risk = {k: {"buildings_pct": round(100 * total[k] / len(buildings), 1),
                       "damaged_pct": round(100 * matched[k] / len(affected), 1)} for k in ("high", "medium", "low")}
        sw = [buildings[int(j)].props.get("surface_water_risk") for j in hit[1]]
        by_risk["surface_water_flag"] = {
            "buildings_pct": round(100 * sum(b.props.get("surface_water_risk", False) for b in buildings) / len(buildings), 1),
            "damaged_pct": round(100 * sum(sw) / len(affected), 1)}
        by_risk["damaged_not_matched_to_a_building"] = len(affected) - len(hit[1])
    return {
        "source": "UNOSAT FL20240426KEN, Pleiades image of 1 May 2024 (not field validated)",
        "observed_pct_of_area": round(100 * observed.area / audit.area, 1),
        "flooded_area_ha": round(flood.area / 1e4, 1),
        "buildings_in_2024_flood": sum(b.props["in_2024_flood"] for b in buildings),
        "unosat_affected_structures": len(affected),
        "affected_within_riparian_zone_pct": round(100 * caught / len(affected), 1) if affected else None,
        "by_risk_class": by_risk,
    }


def history_summary(history: list[dict], top: int = 12) -> dict:
    """Past floods named in news and official statements near the audit area (evidence only)."""
    keys = ("place", "date", "event", "what_happened", "source_url", "source_verified")
    pr = [f["properties"] for f in history]
    return {"incidents": sum(p["kind"] == "incident" for p in pr),
            "listed_at_risk_2026": sorted({p["place"] for p in pr if p["kind"] == "at_risk_area"}),
            "items": [{k: p.get(k) for k in keys} for p in sorted(pr, key=lambda p: p.get("date") or "", reverse=True)][:top],
            "note": "From news and official statements, placed at neighbourhood level. Not used in the risk score."}


@register("flood_exposure")
def flood_exposure(ctx: AnalysisContext):
    p = ctx.params
    sam_buildings = _by_class(ctx.detections, "building")
    baseline = ctx.layers.get("buildings_baseline", [])
    buildings = combine_with_baseline(sam_buildings, baseline)
    res = compute_exposure(buildings, ctx.layers.get("osm_waterways", []), ctx.bounds,
                           buffer_m=p.get("riparian_buffer_m"),
                           baseline=[shape(f["geometry"]) for f in baseline] or None,
                           persons_per_structure=p.get("persons_per_structure"))
    others = [d.to_feature() for d in ctx.detections if d.cls != "building"]
    summary = dict(res.summary)
    summary["buildings_by_source"] = dict(Counter(b.props["source"] for b in buildings))
    summary["buildings_in_riparian_zone_by_source"] = dict(Counter(
        b.props["source"] for b in buildings if b.props.get("in_riparian_zone")))
    if not baseline:
        summary["note"] = "No building footprint baseline for this area: dense settlements will be undercounted"
    dem = ctx.layers.get("copernicus_dem")
    grids = flow_grids(dem) if dem is not None else None
    summary["terrain"] = add_terrain(buildings, ctx.layers.get("osm_waterways", []), dem, p, grids) if dem is not None and buildings else None
    summary["risk"] = score_risk(buildings, p)
    summary["flood_2024"] = compare_with_2024(buildings, ctx.layers.get("unosat_2024", []), res.riparian_zone,
                                              ctx.bounds, settings.utm_epsg)
    chokes = find_choke_points(ctx.layers.get("osm_roads", []), ctx.layers.get("osm_waterways", []), dem,
                               grids[1] if grids else None, buildings, ctx.layers.get("unosat_2024", []),
                               ctx.bounds, p, settings.utm_epsg)
    summary["choke_points"] = choke_point_summary(chokes) if chokes else None
    history = ctx.layers.get("flood_history", [])
    summary["flood_history"] = history_summary(history) if history else None
    summary["garbage_piles_detected"] = len(_by_class(ctx.detections, "garbage"))
    if not ctx.layers.get("osm_waterways"):
        summary["warning"] = "No waterways layer for this area - run: python scripts/fetch_data.py waterways"
    return summary, res.to_geojson()["features"] + others + chokes + _layer_features(history, "past_flood")


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
        summary["warning"] = "No power line layer for this area - run: python scripts/fetch_data.py power_lines"
    features = ([b.to_feature() for b in buildings] + [d.to_feature() for d in panels + tanks]
                + ring_features + _layer_features(lines, "power_line"))
    return summary, features
