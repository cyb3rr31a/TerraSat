"""F1 - Flood exposure audit.

Given segmented buildings and OSM waterways, work out which structures sit
inside the riparian buffer, how far each one is from the river, and which are
new compared with the 2023 Google Open Buildings baseline.

Low-lying ground (DEM / height above drainage) is added in a later step and
will populate the `height_above_stream_m` property.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional, Sequence

from shapely.geometry import Polygon, box, mapping, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union
from shapely.strtree import STRtree

from backend.app.core.config import settings
from backend.app.services import geo
from backend.app.services.sam_service import Detection

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


def load_waterways(path: Path, bounds: tuple[float, float, float, float],
                   pad_deg: float = 0.002) -> list[dict]:
    """Kept for backwards compatibility; prefer layers.load_layer('osm_waterways', ...)."""
    from backend.app.services.layers import load_layer
    return load_layer("osm_waterways", bounds, pad_deg, path=path)


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
