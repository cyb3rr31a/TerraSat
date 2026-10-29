"""One entry point for every audit, whatever the profile:

    pin -> mosaic -> SAM (profile prompts) -> context layers -> analyzer -> result

Used by scripts/run_audit.py now and the FastAPI endpoint next.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from backend.app.profiles.loader import Profile, load_profile
from backend.app.services.analyzers import AnalysisContext, AnalysisResult, run_analyzer
from backend.app.services.layers import load_layers
from backend.app.services.sam_service import (Detection, MetaSAMBackend, SegmentationBackend,
                                              render_overlay, segment_mosaic_cached)
from backend.app.services.tiles import Mosaic, TileCache, build_mosaic

BackendFactory = Callable[[Mosaic], SegmentationBackend]

# Demo sites (lon, lat). Flood sites sit on the river (checked against OSM, Oct 28).
PRESETS = {
    "mathare": (36.8594, -1.2625),   # Mathare River
    "mukuru": (36.8789, -1.3102),    # Ngong River
    "kibera": (36.7887, -1.3146),    # Motoine River
    # holdout sites to test the flood risk rules (densest 2024 damage clusters in UNOSAT's data)
    "korogocho": (36.8855, -1.2455),
    "east_cluster": (37.0375, -1.2835),  # eastern Nairobi, far from mapped rivers: surface-water test
    "syokimau": (36.9300, -1.3700),  # solar & mini-grid profile
}


@dataclass
class AuditOutput:
    profile: Profile
    mosaic: Mosaic
    detections: list[Detection]
    result: AnalysisResult


def run_audit(profile_id: str, lon: float, lat: float, *,
              backend_factory: Optional[BackendFactory] = None,
              layers: Optional[dict[str, list[dict]]] = None,
              side_m: Optional[float] = None, zoom: Optional[int] = None,
              params: Optional[dict] = None, tile_cache: Optional[TileCache] = None,
              sam_cache_dir: Optional[Path] = None) -> AuditOutput:
    profile = load_profile(profile_id)
    mosaic = build_mosaic(lon, lat, side_m or profile.audit.side_m, zoom or profile.audit.zoom,
                          tile_cache)
    backend = backend_factory(mosaic) if backend_factory else MetaSAMBackend()
    dets = segment_mosaic_cached(mosaic, backend, profile.sam_classes(), cache_dir=sam_cache_dir)
    if layers is None:
        layers = load_layers(profile.layers, mosaic.bounds)
    ctx = AnalysisContext(dets, layers, mosaic.bounds, (lon, lat), params or {})
    return AuditOutput(profile, mosaic, dets, run_analyzer(profile, ctx))


def save_audit(out: AuditOutput, folder: Path) -> dict:
    """Write mosaic.jpg, overlay.png, audit.geojson and summary.json; return what a UI needs."""
    folder.mkdir(parents=True, exist_ok=True)
    meta = out.mosaic.save(folder / "mosaic")
    render_overlay(out.mosaic, out.detections, out.profile.sam_classes()).save(folder / "overlay.png")
    (folder / "audit.geojson").write_text(json.dumps(out.result.geojson))
    info = {"profile": out.profile.id, "bounds": meta["bounds"], "summary": out.result.summary}
    (folder / "summary.json").write_text(json.dumps(info, indent=2))
    return info
