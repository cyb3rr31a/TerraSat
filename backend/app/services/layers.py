"""Context map layers (OpenStreetMap extracts etc.) that profiles can request.

Each layer is a GeoJSON file in data/raw, produced by scripts/fetch_data.py.
To add a layer: add it to that script and an entry here.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterable

import numpy as np
from shapely.geometry import box, shape

from backend.app.core.config import settings

LAYER_FILES: dict[str, str] = {
    "osm_waterways": "nairobi_waterways.geojson",
    "osm_power_lines": "nairobi_power_lines.geojson",
    "osm_roads": "nairobi_roads.geojson",
    # Overture Maps building footprints (includes Google Open Buildings), one file
    # per site in data/raw/buildings/ - downloaded by scripts/fetch_data.py
    "buildings_baseline": "buildings",
    # UNOSAT flood mapping of 1 May 2024, cut per site (analysis extent, cloud,
    # flood extent, affected structures and bridges) - see scripts/fetch_data.py
    "unosat_2024": "flood_2024/sites",
    # Copernicus GLO-30 elevation tiles (GeoTIFF), downloaded by scripts/fetch_data.py
    "copernicus_dem": "terrain",
    # Past flood incidents from news and official statements (Muse Spark web search),
    # placed at neighbourhood level - evidence for memos and reports, not a score input
    "flood_history": "nairobi_flood_history.geojson",
    # shops, services, schools, clinics, markets, bus stops (OpenStreetMap points)
    "osm_pois": "nairobi_pois.geojson",
}
# Layers fetched for the exact spot when an audit needs them (cached in data/cache):
#   nasa_power - long-term solar radiation (NASA POWER climatology, kWh/m2/day)
LIVE_LAYERS = {"nasa_power"}


def solar_radiation(lon: float, lat: float) -> dict | None:
    """Long-term average sunshine at a spot from NASA POWER (free, no key), cached per ~10 km cell.
    Returns {"annual_kwh_m2_day", "monthly_kwh_m2_day"} or None when offline."""
    import httpx
    cache = Path(settings.cache_dir) / "nasa_power" / f"{lat:.1f}_{lon:.1f}.json"
    if not cache.exists():
        try:
            r = httpx.get("https://power.larc.nasa.gov/api/temporal/climatology/point", timeout=30,
                          params={"parameters": "ALLSKY_SFC_SW_DWN", "community": "RE", "format": "JSON",
                                  "longitude": round(lon, 1), "latitude": round(lat, 1)})
            r.raise_for_status()
        except httpx.HTTPError:
            return None
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(r.text)
    values = json.loads(cache.read_text())["properties"]["parameter"]["ALLSKY_SFC_SW_DWN"]
    months = {k: v for k, v in values.items() if k != "ANN"}
    annual = values.get("ANN", sum(months.values()) / max(len(months), 1))
    return {"annual_kwh_m2_day": round(annual, 2), "monthly_kwh_m2_day": months,
            "source": "NASA POWER climatology (all-sky surface shortwave radiation)"}


def overture_buildings(bounds: tuple[float, float, float, float]) -> list[dict]:
    """Footprints for any area: the downloaded site files, or a one-off Overture download for
    this area (needs the `overturemaps` package and internet), cached in data/raw/buildings/."""
    have = load_layer("buildings_baseline", bounds)
    if have:
        return have
    import hashlib
    import subprocess
    import sys
    w, s, e, n = bounds
    folder = layer_path("buildings_baseline")
    folder.mkdir(parents=True, exist_ok=True)
    dst = folder / f"area_{hashlib.sha1(f'{w:.4f},{s:.4f}'.encode()).hexdigest()[:10]}.geojson"
    try:
        subprocess.run([sys.executable, "-m", "overturemaps", "download", f"--bbox={w:.5f},{s:.5f},{e:.5f},{n:.5f}",
                        "-f", "geojson", "--type=building", "-o", str(dst)], check=True, capture_output=True, timeout=150)
    except (subprocess.SubprocessError, OSError):
        dst.unlink(missing_ok=True)
        return []
    return load_layer("buildings_baseline", bounds)


def layer_path(name: str) -> Path:
    if name not in LAYER_FILES:
        raise KeyError(f"Unknown layer {name!r}. Known: {sorted(LAYER_FILES)}")
    return Path(settings.data_dir) / "raw" / LAYER_FILES[name]


@lru_cache(maxsize=8)
def _read(path: str) -> list[dict]:
    return json.loads(Path(path).read_text(encoding="utf-8"))["features"]


def load_layer(name: str, bounds: tuple[float, float, float, float],
               pad_deg: float = 0.002, path: Path | None = None) -> list[dict]:
    """Features of a layer intersecting (west, south, east, north). Missing
    files return an empty list (the analyzer reports the gap)."""
    p = Path(path) if path else layer_path(name)
    if not p.exists():
        return []
    files = sorted(p.glob("*.geojson")) if p.is_dir() else [p]
    w, s, e, n = bounds
    area = box(w - pad_deg, s - pad_deg, e + pad_deg, n + pad_deg)
    return [f for fp in files for f in _read(str(fp)) if shape(f["geometry"]).intersects(area)]


@dataclass
class Dem:
    """An elevation grid in lon/lat. GLO-30 is a surface model, so in dense
    areas it includes roof and tree heights - treat values as approximate."""
    z: np.ndarray
    west: float
    north: float
    dx: float  # degrees per column
    dy: float  # degrees per row (positive, rows go south)

    @property
    def cell_area_m2(self) -> float:
        lat = self.north - self.dy * self.z.shape[0] / 2
        return (self.dx * 111_320 * math.cos(math.radians(lat))) * (self.dy * 110_574)

    def cells(self, lon, lat) -> tuple[np.ndarray, np.ndarray]:
        r = np.clip(((self.north - np.asarray(lat)) / self.dy).astype(int), 0, self.z.shape[0] - 1)
        c = np.clip(((np.asarray(lon) - self.west) / self.dx).astype(int), 0, self.z.shape[1] - 1)
        return r, c


def load_dem(bounds: tuple[float, float, float, float], pad_deg: float = 0.02) -> Dem | None:
    """Elevation around (west, south, east, north), padded so upstream areas
    count when working out where water flows."""
    import rasterio
    from rasterio.windows import from_bounds
    w, s, e, n = bounds[0] - pad_deg, bounds[1] - pad_deg, bounds[2] + pad_deg, bounds[3] + pad_deg
    for tif in sorted(layer_path("copernicus_dem").glob("*.tif")):
        with rasterio.open(tif) as src:
            b = src.bounds
            if not (b.left <= w and b.right >= e and b.bottom <= s and b.top >= n):
                continue
            win = from_bounds(w, s, e, n, src.transform).round_offsets().round_lengths()
            z = src.read(1, window=win).astype(float)
            t = src.window_transform(win)
            return Dem(z, t.c, t.f, t.a, -t.e)
    return None


def load_layers(names: Iterable[str], bounds) -> dict:
    """Vector layers come back as lists of GeoJSON features; the DEM as a Dem; sunshine as a dict."""
    cx, cy = (bounds[0] + bounds[2]) / 2, (bounds[1] + bounds[3]) / 2

    def one(n):
        if n == "copernicus_dem":
            return load_dem(bounds)
        if n == "nasa_power":
            return solar_radiation(cx, cy)
        if n == "buildings_baseline":
            return overture_buildings(bounds)
        return load_layer(n, bounds)
    return {n: one(n) for n in names}
