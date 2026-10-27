from shapely.geometry import LineString, Point, mapping

from backend.app.services import geo
from backend.app.services.exposure import compute_exposure
from backend.app.services.sam_service import Detection

LON, LAT = 36.8580, -1.2615
M = 1 / 111_320  # ~degrees per metre near the equator


def house(dx_m, dy_m, size_m=8):
    p = Point(LON + dx_m * M, LAT + dy_m * M)
    g = geo.buffer_m(p, size_m / 2).envelope
    return Detection("building", "rooftop", 0.9, g, geo.area_m2(g))


def river_feature(**props):
    line = LineString([(LON - 600 * M, LAT), (LON + 600 * M, LAT)])  # east-west river
    return {"type": "Feature", "geometry": mapping(line),
            "properties": {"waterway": "river", "name": "Test River", **props}}


BOUNDS = (LON - 500 * M, LAT - 500 * M, LON + 500 * M, LAT + 500 * M)


def test_riparian_classification_and_distance():
    near = house(0, 15)     # 15 m from river centreline -> inside 30 m zone
    edge = house(100, -40)  # 40 m -> outside
    far = house(-200, 200)
    r = compute_exposure([near, edge, far], [river_feature()], BOUNDS, buffer_m=30)
    assert near.props["in_riparian_zone"] is True
    assert edge.props["in_riparian_zone"] is False
    assert far.props["in_riparian_zone"] is False
    assert abs(near.props["distance_to_river_m"] - 11) < 1.5   # 15 m minus half the 8 m house
    assert r.summary["buildings_in_riparian_zone"] == 1
    assert abs(r.summary["river_length_in_area_m"] - 1000) < 15


def test_buffer_width_is_configurable():
    h = house(0, 20)
    assert compute_exposure([h], [river_feature()], BOUNDS, buffer_m=30).summary[
        "buildings_in_riparian_zone"] == 1
    h2 = house(0, 20)
    assert compute_exposure([h2], [river_feature()], BOUNDS, buffer_m=6).summary[
        "buildings_in_riparian_zone"] == 0


def test_culverted_sections_ignored():
    h = house(0, 10)
    r = compute_exposure([h], [river_feature(tunnel="culvert")], BOUNDS, buffer_m=30)
    assert r.summary["buildings_in_riparian_zone"] == 0


def test_new_since_baseline():
    old = house(0, 10)
    new = house(50, 10)
    baseline = [house(0, 10).geometry]  # only the first existed in 2023
    r = compute_exposure([old, new], [river_feature()], BOUNDS, buffer_m=30, baseline=baseline,
                         persons_per_structure=3)
    assert old.props["new_since_baseline"] is False
    assert new.props["new_since_baseline"] is True
    assert r.summary["new_buildings_in_riparian_zone"] == 1
    assert r.summary["est_people_exposed"] == 6
    gj = r.to_geojson()
    classes = {f["properties"]["class"] for f in gj["features"]}
    assert {"building", "riparian_zone", "waterway"} <= classes
