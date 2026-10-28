from shapely.geometry import LineString, Point, mapping

from backend.app.profiles.loader import list_profiles, load_profile
from backend.app.services import geo
from backend.app.services.analyzers import ANALYZERS, AnalysisContext, run_analyzer
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
