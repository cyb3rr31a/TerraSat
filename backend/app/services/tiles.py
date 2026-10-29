"""Fetch satellite tiles, cache them on disk and stitch them into a
georeferenced mosaic covering the audit area.

The default source is the Mapbox Raster Tiles API (mapbox.satellite, 256 px
tiles). Any XYZ source works by changing `url_template`. The UI must show the
Mapbox / imagery attribution wherever these images are displayed.
"""
from __future__ import annotations

import io
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import httpx
from PIL import Image

from backend.app.core.config import settings
from backend.app.services import geo

MAPBOX_URL = "https://api.mapbox.com/v4/mapbox.satellite/{z}/{x}/{y}.jpg90?access_token={token}"
# Fallback while a Mapbox account issue is sorted out. Esri World Imagery needs no
# key for development; check Esri's terms of use and show "Source: Esri, Maxar,
# Earthstar Geographics" attribution if used in the demo.
ESRI_URL = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
# Mapbox Static Images API: one request returns a whole 1280 px block (the API maximum). Static
# zoom is 512-px-tile based, so static zoom z-1 == our (256-px) zoom z, i.e. a
# 1024 px image at static zoom 17 covers exactly a 1024 px block at our z18.
MAPBOX_STATIC_URL = ("https://api.mapbox.com/styles/v1/mapbox/satellite-v9/static/"
                     "{lon:.8f},{lat:.8f},{szoom},0/{size}x{size}"
                     "?access_token={token}&logo=false&attribution=false")
PROVIDERS = {"mapbox_static": MAPBOX_STATIC_URL, "mapbox": MAPBOX_URL, "esri": ESRI_URL}
TILE_PX = {"mapbox_static": 1280, "mapbox": 256, "esri": 256}

Fetcher = Callable[[int, int, int], bytes]


def redact(url: str) -> str:
    """Hide access tokens in URLs before they reach logs or error messages."""
    return re.sub(r"(access_token=)[^&]+", r"\1***", url)


class TileCache:
    def __init__(self, root: Optional[Path] = None, fetcher: Optional[Fetcher] = None,
                 url_template: Optional[str] = None, token: Optional[str] = None,
                 provider: Optional[str] = None, retries: int = 5):
        provider = provider or settings.tile_provider
        if provider not in PROVIDERS:
            raise ValueError(f"Unknown tile provider {provider!r}; choose from {list(PROVIDERS)}")
        self.provider = provider
        # each provider gets its own cache folder so imagery never mixes
        self.root = Path(root or settings.cache_dir / f"tiles_{provider}")
        self.url_template = url_template or PROVIDERS[provider]
        self.tile_px = TILE_PX[provider]
        self.retries = retries
        self.token = token if token is not None else settings.mapbox_token
        self._fetcher = fetcher or self._http_fetch
        self._client: Optional[httpx.Client] = None

    def _http_fetch(self, z: int, x: int, y: int) -> bytes:
        if not self.token and "{token}" in self.url_template:
            raise RuntimeError("MAPBOX_TOKEN is not set (see .env.example)")
        if self._client is None:
            self._client = httpx.Client(timeout=30, headers={"User-Agent": "TerraSat/0.1"})
        url = self.tile_url(z, x, y)
        for attempt in range(self.retries + 1):
            r = self._client.get(url)
            if r.status_code == 200:
                return r.content
            if r.status_code in (429, 500, 502, 503, 504) and attempt < self.retries:
                wait = r.headers.get("retry-after")
                time.sleep(float(wait) if wait and wait.replace(".", "").isdigit() else min(2 ** attempt, 30))
                continue
            limits = {k: v for k, v in r.headers.items() if "rate-limit" in k.lower()}
            raise RuntimeError(
                f"Tile request failed: HTTP {r.status_code} from {self.provider} for "
                f"{redact(url)}\n  body: {r.text[:300]!r}\n  rate-limit headers: {limits}")
        raise RuntimeError("unreachable")

    def tile_url(self, z: int, x: int, y: int) -> str:
        if self.provider == "mapbox_static":
            # centre of the virtual tile -> lon/lat; static zoom is one lower
            cx, cy = (x + 0.5) * self.tile_px, (y + 0.5) * self.tile_px
            lon, lat = geo.global_px_to_lonlat(cx, cy, z)
            return self.url_template.format(lon=lon, lat=lat, szoom=z - 1, size=self.tile_px,
                                            token=self.token)
        return self.url_template.format(z=z, x=x, y=y, token=self.token)

    def path(self, z: int, x: int, y: int) -> Path:
        return self.root / str(z) / str(x) / f"{y}.img"  # jpg or png; PIL detects

    def get(self, z: int, x: int, y: int) -> Image.Image:
        p = self.path(z, x, y)
        if not p.exists():
            data = self._fetcher(z, x, y)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
        img = Image.open(p).convert("RGB")
        if img.size != (self.tile_px, self.tile_px):
            img = img.resize((self.tile_px, self.tile_px))
        return img


@dataclass
class Mosaic:
    """A stitched image whose top-left pixel sits at global pixel
    (box.x0, box.y0) at zoom box.zoom."""
    image: Image.Image
    box: geo.PixelBox

    @property
    def zoom(self) -> int:
        return self.box.zoom

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        """(west, south, east, north) - what Leaflet's ImageOverlay needs."""
        return geo.pixelbox_to_lonlat_bounds(self.box)

    def windows(self, win: int = 1024, overlap: float = 0.10):
        """Yield (offset_x, offset_y, crop) analysis windows."""
        w, h = self.image.size
        for ox, oy in geo.window_offsets(w, h, win, overlap):
            yield ox, oy, self.image.crop((ox, oy, min(ox + win, w), min(oy + win, h)))

    def save(self, stem: Path) -> dict:
        stem.parent.mkdir(parents=True, exist_ok=True)
        img_path = stem.with_suffix(".jpg")
        self.image.save(img_path, quality=90)
        w, s, e, n = self.bounds
        meta = {"image": img_path.name, "zoom": self.zoom,
                "pixel_box": [self.box.x0, self.box.y0, self.box.x1, self.box.y1],
                "bounds": {"west": w, "south": s, "east": e, "north": n}}
        stem.with_suffix(".json").write_text(json.dumps(meta, indent=2))
        return meta


def build_mosaic(lon: float, lat: float, side_m: Optional[float] = None,
                 zoom: Optional[int] = None, cache: Optional[TileCache] = None,
                 workers: int = 4) -> Mosaic:
    side_m = side_m or settings.audit_box_m
    zoom = zoom or settings.tile_zoom
    cache = cache or TileCache()
    pb = geo.square_around(lon, lat, side_m, zoom)
    tiles = geo.tiles_covering(pb, cache.tile_px)
    canvas = Image.new("RGB", (pb.width, pb.height))

    def load(t):
        return t, cache.get(*t)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        for (z, tx, ty), img in ex.map(load, tiles):
            px = int(tx * cache.tile_px - pb.x0)
            py = int(ty * cache.tile_px - pb.y0)
            canvas.paste(img, (px, py))
    return Mosaic(canvas, pb)
