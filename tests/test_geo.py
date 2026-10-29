import math

from shapely.geometry import Point, box

from backend.app.services import geo

MATHARE = (36.8580, -1.2615)  # lon, lat


def test_px_roundtrip():
    for z in (16, 18, 19):
        x, y = geo.lonlat_to_global_px(*MATHARE, z)
        lon, lat = geo.global_px_to_lonlat(x, y, z)
        assert math.isclose(lon, MATHARE[0], abs_tol=1e-9)
        assert math.isclose(lat, MATHARE[1], abs_tol=1e-9)


def test_resolution_near_equator():
    assert math.isclose(geo.meters_per_pixel(0, 18), 0.597, abs_tol=0.001)


def test_square_around_size():
    pb = geo.square_around(*MATHARE, side_m=2100, zoom=18)
    mpp = geo.meters_per_pixel(MATHARE[1], 18)
    assert abs(pb.width * mpp - 2100) < 2 * mpp
    w, s, e, n = geo.pixelbox_to_lonlat_bounds(pb)
    assert w < MATHARE[0] < e and s < MATHARE[1] < n


def test_tiles_cover_box():
    pb = geo.square_around(*MATHARE, side_m=2100, zoom=18)
    tiles = geo.tiles_covering(pb)
    xs = {t[1] for t in tiles}
    ys = {t[2] for t in tiles}
    assert min(xs) * 256 <= pb.x0 and (max(xs) + 1) * 256 >= pb.x1
    assert min(ys) * 256 <= pb.y0 and (max(ys) + 1) * 256 >= pb.y1


def test_window_offsets_cover_image():
    offs = geo.window_offsets(3520, 3520, win=1024, overlap=0.1)
    assert offs[0] == (0, 0)
    assert max(o[0] for o in offs) + 1024 == 3520
    assert len(offs) == 16  # 4 x 4 grid
    assert geo.window_offsets(800, 600) == [(0, 0)]


def test_pixel_polygon_to_lonlat_and_back():
    z = 18
    ox, oy = geo.lonlat_to_global_px(*MATHARE, z)
    poly = geo.pixel_polygon_to_lonlat([(0, 0), (20, 0), (20, 20), (0, 20)], ox, oy, z)
    assert math.isclose(poly.exterior.coords[0][0], MATHARE[0], abs_tol=1e-9)
    side = math.sqrt(geo.area_m2(poly))
    assert abs(side - 20 * geo.meters_per_pixel(MATHARE[1], z)) < 0.1
    back = geo.lonlat_polygon_to_pixel(poly, ox, oy, z)
    assert abs(back.bounds[2] - 20) < 1e-6


def test_buffer_m_is_metric():
    pt = Point(*MATHARE)
    buf = geo.buffer_m(pt, 30)
    assert abs(geo.area_m2(buf) - math.pi * 30 ** 2) / (math.pi * 30 ** 2) < 0.01


def test_merge_duplicates():
    a = box(0, 0, 10, 10)
    a_shift = box(1, 0, 11, 10)        # IoU ~0.82 with a -> duplicate
    a_frag = box(0, 0, 4, 10)          # fragment inside a -> replaced by a
    b = box(20, 20, 30, 30)            # separate building
    keep = geo.merge_duplicates([a, a_shift, a_frag, b], [0.9, 0.8, 0.95, 0.7])
    assert keep == [0, 3]


def test_block_mask_does_not_swallow_buildings():
    block = box(0, 0, 100, 100)        # oversized mask, low score
    houses = [box(10, 10, 20, 20), box(50, 50, 60, 60)]
    keep = geo.merge_duplicates(houses + [block], [0.9, 0.9, 0.5])
    assert 0 in keep and 1 in keep


def test_fill_depressions_and_flow():
    import numpy as np
    z = np.add.outer(np.arange(20.0), np.zeros(20))   # slope: rows get higher going south
    z[10, 10] -= 3                                     # a 3 m pit; it spills over its 9 m neighbour
    filled = geo.fill_depressions(z)
    depth = filled - z
    assert 1.9 < depth[10, 10] < 2.1 and depth[2, 2] < 0.01  # ponds 2 m deep; the slope doesn't pond
    acc = geo.flow_accumulation(filled)
    assert acc[0].sum() == z.size                      # everything drains to the low (north) edge
    assert acc[19].max() == 1                          # top row receives nothing
