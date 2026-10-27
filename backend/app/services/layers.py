"""Context map layers (OpenStreetMap extracts etc.) that profiles can request.

Each layer is a GeoJSON file in data/raw, produced by scripts/fetch_osm_layers.py.
To add a layer: add an Overpass query in that script and an entry here.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Iterable

from shapely.geometry import box, shape

from backend.app.core.config import settings

LAYER_FILES: dict[str, str] = {
    "osm_waterways": "nairobi_waterways.geojson",
    "osm_power_lines": "nairobi_power_lines.geojson",
    "osm_roads": "nairobi_roads.geojson",
}


def layer_path(name: str) -> Path:
    if name not in LAYER_FILES:
        raise KeyError(f"Unknown layer {name!r}. Known: {sorted(LAYER_FILES)}")
    return Path(settings.data_dir) / "raw" / LAYER_FILES[name]


@lru_cache(maxsize=8)
def _read(path: str) -> list[dict]:
    return json.loads(Path(path).read_text())["features"]


def load_layer(name: str, bounds: tuple[float, float, float, float],
               pad_deg: float = 0.002, path: Path | None = None) -> list[dict]:
    """Features of a layer intersecting (west, south, east, north). Missing
    files return an empty list (the analyzer reports the gap)."""
    p = Path(path) if path else layer_path(name)
    if not p.exists():
        return []
    w, s, e, n = bounds
    area = box(w - pad_deg, s - pad_deg, e + pad_deg, n + pad_deg)
    return [f for f in _read(str(p)) if shape(f["geometry"]).intersects(area)]


def load_layers(names: Iterable[str], bounds) -> dict[str, list[dict]]:
    return {n: load_layer(n, bounds) for n in names}
