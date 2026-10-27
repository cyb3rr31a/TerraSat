"""Fetch satellite tiles, cache them on disk and stitch them into a
georeferenced mosaic covering the audit area.

The default source is the Mapbox Raster Tiles API (mapbox.satellite, 256 px
tiles). Any XYZ source works by changing `url_template`. The UI must show the
Mapbox / imagery attribution wherever these images are displayed.
"""
from __future__ import annotations

import io
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import httpx
from PIL import Image

from backend.app.core.config import settings
from backend.app.services import geo

MAPBOX_URL = "https://api.mapbox.com/v4/mapbox.satellite/{z}/{x}/{y}.jpg90?access_token={token}"

Fetcher = Callable[[int, int, int], bytes]


class TileCache:
    def __init__(self, root: Optional[Path] = None, fetcher: Optional[Fetcher] = None,
                 url_template: str = MAPBOX_URL, token: Optional[str] = None):
        self.root = Path(root or settings.cache_dir / "tiles")
        self.url_template = url_template
        self.token = token if token is not None else settings.mapbox_token
        self._fetcher = fetcher or self._http_fetch
        self._client: Optional[httpx.Client] = None

    def _http_fetch(self, z: int, x: int, y: int) -> bytes:
        if not self.token and "{token}" in self.url_template:
            raise RuntimeError("MAPBOX_TOKEN is not set (see .env.example)")
        if self._client is None:
            self._client = httpx.Client(timeout=30, headers={"User-Agent": "TerraSat/0.1"})
        r = self._client.get(self.url_template.format(z=z, x=x, y=y, token=self.token))
        r.raise_for_status()
        return r.content

    def path(self, z: int, x: int, y: int) -> Path:
        return self.root / str(z) / str(x) / f"{y}.jpg"

    def get(self, z: int, x: int, y: int) -> Image.Image:
        p = self.path(z, x, y)
        if not p.exists():
            data = self._fetcher(z, x, y)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
        return Image.open(p).convert("RGB")


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
                 workers: int = 8) -> Mosaic:
    side_m = side_m or settings.audit_box_m
    zoom = zoom or settings.tile_zoom
    cache = cache or TileCache()
    pb = geo.square_around(lon, lat, side_m, zoom)
    tiles = geo.tiles_covering(pb)
    canvas = Image.new("RGB", (pb.width, pb.height))

    def load(t):
        return t, cache.get(*t)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        for (z, tx, ty), img in ex.map(load, tiles):
            px = int(tx * geo.TILE_SIZE - pb.x0)
            py = int(ty * geo.TILE_SIZE - pb.y0)
            canvas.paste(img, (px, py))
    return Mosaic(canvas, pb)
