"""One entry point for every audit, whatever the profile:

    pin -> mosaic -> SAM (profile prompts) -> context layers -> analyzer -> result -> memo

Used by scripts/run_audit.py and the API.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from backend.app.profiles.loader import Profile, load_profile
from backend.app.services import meta
from backend.app.services.analyzers import (AnalysisContext, AnalysisResult, choke_point_summary,
                                            rank_choke_points, run_analyzer)
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


def ranked_choke_points(folder: Path, reports: list[dict]) -> list[dict]:
    """A saved audit's choke points, re-ranked with the latest residents' reports."""
    info = json.loads((folder / "summary.json").read_text())
    feats = [f for f in json.loads((folder / "audit.geojson").read_text())["features"]
             if f["properties"].get("class") == "choke_point"]
    return rank_choke_points(feats, reports, load_profile(info["profile"]).params)


LANGUAGES = {"en": "English", "sw": "Kiswahili"}


def write_memo(folder: Path, reports: list[dict], lang: str = "en") -> dict:
    """A short, sourced briefing memo by Muse Spark (with web search for the rain forecast),
    from the saved audit, the latest choke-point ranking and residents' reports in the area.
    Saved next to the audit as memo_<lang>.md."""
    info = json.loads((folder / "summary.json").read_text())
    profile = load_profile(info["profile"])
    if lang not in profile.memo.languages:
        raise ValueError(f"lang must be one of {profile.memo.languages}")
    b = info["bounds"]  # saved as {"west", "south", "east", "north"}
    w, s, e, n = b["west"], b["south"], b["east"], b["north"]
    summary = dict(info["summary"])
    chokes = ranked_choke_points(folder, reports)
    if chokes:
        summary["choke_points"] = choke_point_summary(chokes)
    nearby = [{k: r.get(k) for k in ("created_at", "issue_type", "place", "urgency", "status", "summary_en")}
              for r in reports if r.get("lon") is not None and w <= r["lon"] <= e and s <= r["lat"] <= n][:25]
    prompt = (
        f"Write a short briefing memo for {profile.audience}.\n"
        f"Use case: {profile.name}. Area: the audit square around lat {(s + n) / 2:.5f}, lon {(w + e) / 2:.5f} "
        f"(Nairobi, Kenya). Today is {datetime.now(timezone.utc):%d %B %Y}.\n"
        f"Framing: {profile.memo.framing}\n"
        f"Write in {LANGUAGES[lang]}. Use these sections as markdown headings: {', '.join(profile.memo.sections)}.\n"
        "Rules:\n"
        "- Use only facts from DATA below or from web pages you open and cite. If something is unknown, say so.\n"
        "- Search the web for the Kenya Meteorological Department's latest forecast for Nairobi for the next "
        "7 days, summarise it with a citation, and say which places in DATA to warn first if heavy rain is coming.\n"
        "- Name choke points by rank, road and watercourse, with lat, lon to 5 decimals.\n"
        "- Cite where facts come from: (TerraSat audit), (UNOSAT 2024), (resident reports), or the source URL "
        "for past incidents.\n"
        "- Under 450 words. Plain language for officers in the field.\n\n"
        f"DATA:\n{json.dumps({'audit_summary': summary, 'resident_reports': nearby}, default=str)}")
    ans = meta.spark(prompt, web_search=True)
    sources = {c["url"]: c.get("title") for c in ans["citations"] if c.get("url")}
    for item in (summary.get("flood_history") or {}).get("items", []):
        sources.setdefault(item["source_url"], item["place"])
    memo = {"lang": lang, "markdown": ans["text"], "sources": [{"url": u, "title": t} for u, t in sources.items() if u],
            "web_searches": ans["web_searches"], "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    lines = "\n".join(f"- [{x['title'] or x['url']}]({x['url']})" for x in memo["sources"])
    (folder / f"memo_{lang}.md").write_text(f"{memo['markdown']}\n\n## Sources\n{lines}\n", encoding="utf-8")
    (folder / f"memo_{lang}.json").write_text(json.dumps(memo, indent=2), encoding="utf-8")
    return memo
