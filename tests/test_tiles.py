import io

from PIL import Image

from backend.app.services import geo
from backend.app.services.tiles import TileCache, build_mosaic

MATHARE = (36.8580, -1.2615)


def fake_fetcher(calls):
    def f(z, x, y):
        calls.append((z, x, y))
        img = Image.new("RGB", (256, 256), ((x * 37) % 256, (y * 53) % 256, 120))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=95)
        return buf.getvalue()
    return f


def test_mosaic_size_and_cache(tmp_path):
    calls = []
    cache = TileCache(root=tmp_path, fetcher=fake_fetcher(calls), provider="mapbox")
    m = build_mosaic(*MATHARE, side_m=600, zoom=18, cache=cache)
    mpp = geo.meters_per_pixel(MATHARE[1], 18)
    assert abs(m.image.width * mpp - 600) < 2 * mpp
    n_first = len(calls)
    assert n_first == len(geo.tiles_covering(m.box))
    build_mosaic(*MATHARE, side_m=600, zoom=18, cache=cache)
    assert len(calls) == n_first  # second run served from disk cache


def test_mosaic_pixels_line_up_with_tiles(tmp_path):
    cache = TileCache(root=tmp_path, fetcher=fake_fetcher([]), provider="mapbox")
    m = build_mosaic(*MATHARE, side_m=600, zoom=18, cache=cache)
    # pick the pixel at the pin and check it came from the right tile
    gx, gy = geo.lonlat_to_global_px(*MATHARE, 18)
    tx = int(gx // 256)
    r, g, b = m.image.getpixel((int(gx - m.box.x0), int(gy - m.box.y0)))
    assert abs(r - (tx * 37) % 256) <= 3  # JPEG tolerance


def test_bounds_contain_pin_and_save(tmp_path):
    cache = TileCache(root=tmp_path / "tiles", fetcher=fake_fetcher([]), provider="mapbox")
    m = build_mosaic(*MATHARE, side_m=2100, zoom=18, cache=cache)
    w, s, e, n = m.bounds
    assert w < MATHARE[0] < e and s < MATHARE[1] < n
    meta = m.save(tmp_path / "out" / "mathare")
    assert (tmp_path / "out" / "mathare.jpg").exists()
    assert meta["bounds"]["north"] == n
    assert len(list(m.windows())) == 16


def fake_static_fetcher(calls, size=1280):
    def f(z, x, y):
        calls.append((z, x, y))
        img = Image.new("RGB", (size, size), ((x * 37) % 256, (y * 53) % 256, 200))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    return f


def test_static_provider_url_and_alignment(tmp_path):
    from urllib.parse import urlparse
    calls = []
    cache = TileCache(root=tmp_path, fetcher=fake_static_fetcher(calls), provider="mapbox_static",
                      token="pk.test")
    m = build_mosaic(*MATHARE, side_m=2100, zoom=18, cache=cache)
    assert len(calls) <= 16  # 9-16 static images instead of ~196 raster tiles
    gx, gy = geo.lonlat_to_global_px(*MATHARE, 18)
    tx = int(gx // 1280)
    r, g, b = m.image.getpixel((int(gx - m.box.x0), int(gy - m.box.y0)))
    assert r == (tx * 37) % 256 and b == 200
    # URL: static zoom is one lower and centred on the virtual tile
    z, x, y = calls[0]
    url = cache.tile_url(z, x, y)
    assert "/static/" in url and ",17,0/1280x1280" in url and "logo=false" in url
    lon, lat = map(float, urlparse(url).path.split("/static/")[1].split(",")[:2])
    cx, cy = geo.lonlat_to_global_px(lon, lat, 18)
    assert abs(cx - (x + 0.5) * 1280) < 0.01 and abs(cy - (y + 0.5) * 1280) < 0.01
