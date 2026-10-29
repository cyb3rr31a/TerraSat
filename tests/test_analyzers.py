from shapely.geometry import LineString, Point, mapping

from backend.app.profiles.loader import list_profiles, load_profile
from backend.app.services import geo
from backend.app.services.analyzers import ANALYZERS, AnalysisContext, compute_exposure, run_analyzer
from backend.app.services.audit import run_audit
from backend.app.services.layers import LAYER_FILES
from backend.app.services.sam_service import Detection, MockBackend
from backend.app.services.tiles import TileCache
from tests.test_tiles import fake_fetcher

LON, LAT = 36.8580, -1.2615
M = 1 / 111_320


def det(cls, dx, dy, size=8, prompt="x"):
    g = geo.buffer_m(Point(LON + dx * M, LAT + dy * M), size / 2).envelope
    return Detection(cls, prompt, 0.9, g, geo.area_m2(g))


BOUNDS = (LON - 1100 * M, LAT - 1100 * M, LON + 1100 * M, LAT + 1100 * M)


def test_every_profile_is_wired():
    profiles = list_profiles()
    assert {"flood", "solar_minigrid"} <= {p.id for p in profiles}
    assert sum(p.status == "case_study" for p in profiles) == 1  # one flagship demo
    for p in profiles:
        assert p.analyzer in ANALYZERS
        assert all(layer in LAYER_FILES for layer in p.layers)
        assert "building" in p.classes
        for spec in p.classes.values():
            # SAM 3.1 takes one short noun phrase per request - no lists
            assert all("," not in pr and ";" not in pr for pr in spec.prompts)


def test_flood_profile_params_flow_through():
    river = {"type": "Feature", "properties": {"waterway": "river"},
             "geometry": mapping(LineString([(LON - 900 * M, LAT), (LON + 900 * M, LAT)]))}
    dets = [det("building", 0, 20), det("garbage", 10, 5, 6)]
    prof = load_profile("flood")
    r30 = run_analyzer(prof, AnalysisContext(dets, {"osm_waterways": [river]}, BOUNDS, (LON, LAT), {}))
    assert r30.summary["buildings_in_riparian_zone"] == 1
    assert r30.summary["garbage_piles_detected"] == 1
    r6 = run_analyzer(prof, AnalysisContext([det("building", 0, 20)], {"osm_waterways": [river]}, BOUNDS,
                                            (LON, LAT), {"riparian_buffer_m": 6}))
    assert r6.summary["buildings_in_riparian_zone"] == 0


def test_solar_minigrid_rings_economics_verdict():
    dets = [det("building", 100 + i * 15, 0) for i in range(10)]      # 100-235 m from pin
    dets += [det("building", 800, i * 15) for i in range(5)]          # ~800 m: outer ring only
    dets.append(det("solar_panel", 100, 0, 3))                        # on the first roof
    line = {"type": "Feature", "properties": {"power": "minor_line"},
            "geometry": mapping(LineString([(LON + 300 * M, LAT - 900 * M), (LON + 300 * M, LAT + 900 * M)]))}
    prof = load_profile("solar_minigrid")
    ctx = AnalysisContext(dets, {"osm_power_lines": [line]}, BOUNDS, (LON, LAT), {"dense_min_buildings": 5})
    s = run_analyzer(prof, ctx).summary
    inner, outer = s["rings"]["transformer_zone"], s["rings"]["wisp_sector"]
    assert inner["buildings"] == 10 and inner["buildings_with_solar"] == 1
    assert outer["buildings"] == 15 and inner["unserved_households_est"] == 9
    assert inner["capex_per_unserved_household_usd"]["wisp_mast"] == round(3500 / 9, 2)
    assert abs(s["distance_center_to_power_line_m"] - 300) < 5
    assert s["verdict"] == "GRID_EXTENSION_CANDIDATE"
    far = AnalysisContext(dets, {"osm_power_lines": []}, BOUNDS, (LON, LAT), {"dense_min_buildings": 5})
    assert run_analyzer(prof, far).summary["verdict"].startswith("UNKNOWN_GRID")


def test_same_engine_runs_both_profiles(tmp_path):
    cache = TileCache(root=tmp_path / "tiles", fetcher=fake_fetcher([]), provider="mapbox")
    for pid in ("flood", "solar_minigrid"):
        prof = load_profile(pid)
        roof = prof.classes["building"].prompts[0]
        factory = lambda m: MockBackend({roof: [det("building", 0, 30).geometry]}, m)
        out = run_audit(pid, LON, LAT, backend_factory=factory, layers={}, side_m=600,
                        tile_cache=cache, sam_cache_dir=tmp_path / "sam")
        assert out.result.profile_id == pid
        assert out.result.summary["detections_by_class"] == {"building": 1}


def test_flood_baseline_fills_roofs_sam_missed():
    river = {"type": "Feature", "properties": {"waterway": "river"},
             "geometry": mapping(LineString([(LON - 900 * M, LAT), (LON + 900 * M, LAT)]))}
    sam_house = det("building", 200, 10)                      # SAM found this one (new since baseline)
    old_house = det("building", 0, 10)                        # SAM missed it; baseline has it
    baseline = [{"type": "Feature", "properties": {}, "geometry": mapping(old_house.geometry)},
                {"type": "Feature", "properties": {}, "geometry": mapping(det("building", 0, 400).geometry)}]
    prof = load_profile("flood")
    s = run_analyzer(prof, AnalysisContext([sam_house], {"osm_waterways": [river], "buildings_baseline": baseline},
                                           BOUNDS, (LON, LAT), {})).summary
    assert s["buildings_total"] == 3
    assert s["buildings_by_source"] == {"sam": 1, "baseline": 2}
    assert s["buildings_in_riparian_zone"] == 2
    assert s["buildings_in_riparian_zone_by_source"] == {"sam": 1, "baseline": 1}
    assert s["new_buildings_in_riparian_zone"] == 1  # the SAM house isn't in the baseline


# --- riparian exposure helpers
def house(dx_m, dy_m, size_m=8):
    p = Point(LON + dx_m * M, LAT + dy_m * M)
    g = geo.buffer_m(p, size_m / 2).envelope
    return Detection("building", "rooftop", 0.9, g, geo.area_m2(g))


def river_feature(**props):
    line = LineString([(LON - 600 * M, LAT), (LON + 600 * M, LAT)])  # east-west river
    return {"type": "Feature", "geometry": mapping(line),
            "properties": {"waterway": "river", "name": "Test River", **props}}


EXPOSURE_BOUNDS = (LON - 500 * M, LAT - 500 * M, LON + 500 * M, LAT + 500 * M)


def test_riparian_classification_and_distance():
    near = house(0, 15)     # 15 m from river centreline -> inside 30 m zone
    edge = house(100, -40)  # 40 m -> outside
    far = house(-200, 200)
    r = compute_exposure([near, edge, far], [river_feature()], EXPOSURE_BOUNDS, buffer_m=30)
    assert near.props["in_riparian_zone"] is True
    assert edge.props["in_riparian_zone"] is False
    assert far.props["in_riparian_zone"] is False
    assert abs(near.props["distance_to_river_m"] - 11) < 1.5   # 15 m minus half the 8 m house
    assert r.summary["buildings_in_riparian_zone"] == 1
    assert abs(r.summary["river_length_in_area_m"] - 1000) < 15


def test_buffer_width_is_configurable():
    h = house(0, 20)
    assert compute_exposure([h], [river_feature()], EXPOSURE_BOUNDS, buffer_m=30).summary[
        "buildings_in_riparian_zone"] == 1
    h2 = house(0, 20)
    assert compute_exposure([h2], [river_feature()], EXPOSURE_BOUNDS, buffer_m=6).summary[
        "buildings_in_riparian_zone"] == 0


def test_culverted_sections_ignored():
    h = house(0, 10)
    r = compute_exposure([h], [river_feature(tunnel="culvert")], EXPOSURE_BOUNDS, buffer_m=30)
    assert r.summary["buildings_in_riparian_zone"] == 0


def test_new_since_baseline():
    old = house(0, 10)
    new = house(50, 10)
    baseline = [house(0, 10).geometry]  # only the first existed in 2023
    r = compute_exposure([old, new], [river_feature()], EXPOSURE_BOUNDS, buffer_m=30, baseline=baseline,
                         persons_per_structure=3)
    assert old.props["new_since_baseline"] is False
    assert new.props["new_since_baseline"] is True
    assert r.summary["new_buildings_in_riparian_zone"] == 1
    assert r.summary["est_people_exposed"] == 6
    gj = r.to_geojson()
    classes = {f["properties"]["class"] for f in gj["features"]}
    assert {"building", "riparian_zone", "waterway"} <= classes


def test_flood_2024_comparison():
    river = {"type": "Feature", "properties": {"waterway": "river"},
             "geometry": mapping(LineString([(LON - 900 * M, LAT), (LON + 900 * M, LAT)]))}
    sq = lambda x0, y0, x1, y1: mapping(LineString([(LON + x0 * M, LAT + y0 * M), (LON + x1 * M, LAT + y0 * M),
                                                    (LON + x1 * M, LAT + y1 * M), (LON + x0 * M, LAT + y1 * M),
                                                    (LON + x0 * M, LAT + y0 * M)]).convex_hull)
    pt = lambda dx, dy: mapping(Point(LON + dx * M, LAT + dy * M))
    unosat = [{"type": "Feature", "properties": {"kind": "analysis_extent"}, "geometry": sq(-1100, -1100, 1100, 1100)},
              {"type": "Feature", "properties": {"kind": "cloud"}, "geometry": sq(500, 500, 1100, 1100)},
              {"type": "Feature", "properties": {"kind": "flood_extent"}, "geometry": sq(-100, -40, 100, 40)},
              {"type": "Feature", "properties": {"kind": "affected_structure"}, "geometry": pt(0, 10)},    # in riparian zone
              {"type": "Feature", "properties": {"kind": "affected_structure"}, "geometry": pt(0, 300)}]   # outside it
    dets = [det("building", 0, 10), det("building", 400, 400)]
    s = run_analyzer(load_profile("flood"), AnalysisContext(dets, {"osm_waterways": [river], "unosat_2024": unosat},
                                                            BOUNDS, (LON, LAT), {})).summary["flood_2024"]
    assert s["buildings_in_2024_flood"] == 1
    assert s["unosat_affected_structures"] == 2
    assert s["affected_within_riparian_zone_pct"] == 50.0
    assert 85 < s["observed_pct_of_area"] < 95  # the cloud hides ~7% of the square


def valley_dem():
    """A river valley along LAT: ground rises 1 m per 10 m away from the river, with a dip."""
    import numpy as np
    from backend.app.services.layers import Dem
    dx = 10 * M
    n = 241
    rows = np.abs(np.arange(n) - n // 2)[:, None] * 1.0 + np.zeros((1, n))  # metres above river
    rows[60:63, 150:153] -= 4                                                 # a pond-shaped dip ~600 m north
    return Dem(1600 + rows, LON - n // 2 * dx, LAT + n // 2 * dx + dx / 2, dx, dx)


def test_terrain_and_risk_score():
    river = {"type": "Feature", "properties": {"waterway": "river"},
             "geometry": mapping(LineString([(LON - 1200 * M, LAT), (LON + 1200 * M, LAT)]))}
    riverside, uphill, in_dip = det("building", 0, 15), det("building", 0, 500), det("building", 300, 600)
    s = run_analyzer(load_profile("flood"), AnalysisContext(
        [riverside, uphill, in_dip], {"osm_waterways": [river], "copernicus_dem": valley_dem()},
        BOUNDS, (LON, LAT), {})).summary
    assert riverside.props["height_above_stream_m"] <= 3 and riverside.props["risk"] == "high"
    assert uphill.props["height_above_stream_m"] > 40 and uphill.props["risk"] == "low"
    assert in_dip.props["in_dip"] is True
    assert s["risk"]["high"] == 1 and s["terrain"]["buildings_low_lying"] == 1


def test_2024_damage_by_risk_class():
    river = {"type": "Feature", "properties": {"waterway": "river"},
             "geometry": mapping(LineString([(LON - 1200 * M, LAT), (LON + 1200 * M, LAT)]))}
    dets = [det("building", 0, 15), det("building", 0, 500), det("building", 200, 500)]
    unosat = [{"type": "Feature", "properties": {"kind": "affected_structure"}, "geometry": mapping(Point(LON, LAT + 15 * M))}]
    s = run_analyzer(load_profile("flood"), AnalysisContext(
        dets, {"osm_waterways": [river], "copernicus_dem": valley_dem(), "unosat_2024": unosat},
        BOUNDS, (LON, LAT), {})).summary["flood_2024"]["by_risk_class"]
    assert s["high"] == {"buildings_pct": 33.3, "damaged_pct": 100.0}
    assert s["damaged_not_matched_to_a_building"] == 0


def test_dem_channels_used_where_no_river_is_mapped():
    riverside = det("building", 0, 15)
    s = run_analyzer(load_profile("flood"), AnalysisContext(
        [riverside], {"osm_waterways": [], "copernicus_dem": valley_dem()}, BOUNDS, (LON, LAT),
        {"channel_min_ha": 1})).summary
    assert riverside.props["watercourse"] == "dem_channel"
    assert riverside.props["distance_to_river_m"] <= 30 and riverside.props["risk"] == "high"
    assert s["terrain"]["buildings_measured_to_dem_channels"] == 1
