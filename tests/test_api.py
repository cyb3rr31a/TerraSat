import pytest
from fastapi.testclient import TestClient
from shapely.geometry import LineString, mapping

from backend.app import main
from backend.app.core.config import settings
from backend.app.services import reports


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(main, "_db", reports.connect(tmp_path / "test.db"))
    monkeypatch.setattr(reports.audio, "to_wav", lambda data, suffix: b"wav")
    monkeypatch.setattr(reports.meta, "transcribe", lambda wav: "Maze, mtaro imeblock karibu na bridge Mathaari")
    monkeypatch.setattr(reports.meta, "spark_json", lambda prompt, **kw: {
        "issue_type": "blocked_drain", "place": "Mathare, near the bridge", "urgency": "high",
        "summary_en": "Drain blocked near the bridge.", "summary_sw": "Mtaro umeziba karibu na daraja."})
    monkeypatch.setattr(reports, "corroborate", lambda lon, lat: {"distance_to_watercourse_m": 12.0, "corroborated": True})
    return TestClient(main.app)


def post_report(client, client_id="abc-1"):
    return client.post("/reports", data={"lat": "-1.2625", "lon": "36.8594", "device_id": "phone-1",
                                         "client_id": client_id},
                       files={"audio": ("note.m4a", b"fake audio", "audio/mp4")})


def test_report_flow(client):
    r = post_report(client).json()
    assert r["issue_type"] == "blocked_drain" and r["status"] == "corroborated" and r["profile"] == "flood"
    assert r["summary_sw"] and r["context"]["corroborated"] is True
    assert post_report(client).json()["id"] == r["id"]           # offline-queue retry: no duplicate
    assert len(client.get("/reports", params={"device_id": "phone-1"}).json()) == 1
    assert client.patch(f"/reports/{r['id']}", json={"status": "resolved"}).json()["status"] == "resolved"
    assert client.get("/reports", params={"device_id": "phone-1"}).json()[0]["status"] == "resolved"


def test_bad_inputs(client):
    assert client.patch("/reports/999", json={"status": "resolved"}).status_code == 404
    rid = post_report(client).json()["id"]
    assert client.patch(f"/reports/{rid}", json={"status": "flying"}).status_code == 400
    assert client.post("/audit", json={"profile": "flood"}).status_code == 400
    assert client.post("/audit", json={"profile": "nope", "preset": "mathare"}).status_code == 400


def test_audit_is_cached(client, monkeypatch):
    calls = []

    def fake_save(out, folder):
        folder.mkdir(parents=True, exist_ok=True)
        info = {"profile": "flood", "bounds": {}, "summary": {"buildings_total": 1}}
        (folder / "summary.json").write_text(__import__("json").dumps(info))
        return info
    from backend.app.services import audit
    monkeypatch.setattr(audit, "run_audit", lambda *a, **k: calls.append(a) or object())
    monkeypatch.setattr(audit, "save_audit", fake_save)
    a = client.post("/audit", json={"preset": "mukuru"}).json()
    b = client.post("/audit", json={"preset": "mukuru"}).json()
    assert a["audit_id"] == b["audit_id"] and len(calls) == 1
    assert a["files"]["geojson"].endswith("audit.geojson") and a["summary"]["buildings_total"] == 1


def test_corroborate_near_river(monkeypatch):
    river = {"type": "Feature", "properties": {"waterway": "river"},
             "geometry": mapping(LineString([(36.85, -1.2625), (36.87, -1.2625)]))}
    monkeypatch.setattr(reports, "load_layer", lambda name, bounds: [river] if name == "osm_waterways" else [])
    monkeypatch.setattr(reports, "load_dem", lambda bounds, pad_deg: None)
    near = reports.corroborate(36.8594, -1.2626)
    far = reports.corroborate(36.8594, -1.2700)
    assert near["corroborated"] and near["distance_to_watercourse_m"] < 20
    assert not far["corroborated"]


def test_location_checks(client):
    bad = client.post("/reports", data={"lat": "0", "lon": "0"}, files={"audio": ("n.m4a", b"x", "audio/mp4")})
    assert bad.status_code == 400 and "outside Kenya" in bad.json()["detail"]
    r = client.post("/reports", data={"client_id": "no-gps"}, files={"audio": ("n.m4a", b"x", "audio/mp4")}).json()
    assert r["location_source"] == "place_name" and abs(r["lat"] + 1.2625) < 1e-6   # "Mathare, near the bridge"


def test_2024_flag_is_unknown_under_cloud(monkeypatch):
    sq = lambda d: mapping(LineString([(36.86 - d, -1.26 - d), (36.86 + d, -1.26 - d), (36.86 + d, -1.26 + d),
                                       (36.86 - d, -1.26 + d)]).convex_hull)
    unosat = [{"type": "Feature", "properties": {"kind": "analysis_extent"}, "geometry": sq(0.05)},
              {"type": "Feature", "properties": {"kind": "cloud"}, "geometry": sq(0.01)},
              {"type": "Feature", "properties": {"kind": "flood_extent"}, "geometry": sq(0.02)}]
    monkeypatch.setattr(reports, "load_layer", lambda name, bounds: unosat if name == "unosat_2024" else [])
    assert reports.corroborate(36.86, -1.26)["in_2024_flood"] is None       # hidden by cloud
    assert reports.corroborate(36.875, -1.26)["in_2024_flood"] is True      # seen, inside the flood


def fake_audit(monkeypatch, tmp_path, audit_id="0123456789ab"):
    """A saved audit with two choke points: a big river crossing and a small drain next to Mathare."""
    import json
    folder = tmp_path / "outputs" / "api" / audit_id
    folder.mkdir(parents=True)
    pt = lambda lon, lat, up, b: {"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]},
                                  "properties": {"class": "choke_point", "kind": "mapped", "upstream_ha": up,
                                                 "buildings_at_risk_nearby": b, "road": "residential",
                                                 "watercourse": "drain", "in_2024_flood": None}}
    (folder / "audit.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": [
        pt(36.8700, -1.2700, 500, 10), pt(36.8594, -1.2626, 30, 10)]}))
    (folder / "summary.json").write_text(json.dumps({"profile": "flood", "bounds": {"west": 36.85, "south": -1.28, "east": 36.88, "north": -1.25},
                                                     "summary": {"risk": {"high": 5}}}))
    monkeypatch.setattr(main, "DATA", tmp_path)
    return audit_id


def test_choke_points_rerank_with_reports_and_export(client, monkeypatch, tmp_path):
    aid = fake_audit(monkeypatch, tmp_path)
    before = client.get(f"/audit/{aid}/choke-points").json()
    assert before[0]["upstream_ha"] == 500 and before[1]["reports_nearby"] == 0
    for i in range(3):                     # residents report the blocked drain at Mathare
        post_report(client, client_id=f"r{i}")
    after = client.get(f"/audit/{aid}/choke-points").json()
    drain = next(r for r in after if r["upstream_ha"] == 30)
    assert drain["reports_nearby"] == 3 and drain["rank"] == 1
    csv_text = client.get(f"/audit/{aid}/choke-points", params={"format": "csv"}).text
    assert csv_text.startswith("rank,score,kind") and len(csv_text.strip().splitlines()) == 3
    assert client.get("/reports", params={"format": "csv"}).text.count("blocked_drain") == 3
    assert client.get("/audit/../../etc/choke-points").status_code == 404
    assert client.get("/audit/ffffffffffff/choke-points").status_code == 404


def test_memo_is_sourced_and_cached(client, monkeypatch, tmp_path):
    from backend.app.services import audit
    aid = fake_audit(monkeypatch, tmp_path)
    post_report(client)
    prompts = []
    monkeypatch.setattr(audit.meta, "spark", lambda prompt, **kw: prompts.append((prompt, kw)) or {
        "text": "## Risk summary\nClear the drain at rank 1 first (resident reports).",
        "citations": [{"url": "https://meteo.go.ke/forecast", "title": "KMD 7-day forecast"}], "web_searches": 1})
    m = client.post(f"/audit/{aid}/memo", params={"lang": "sw"}).json()
    assert m["lang"] == "sw" and m["sources"][0]["url"] == "https://meteo.go.ke/forecast"
    prompt, kw = prompts[0]
    assert kw["web_search"] and "Kiswahili" in prompt and "blocked_drain" in prompt   # the report is in the data
    assert "## Sources" in (tmp_path / "outputs" / "api" / aid / "memo_sw.md").read_text(encoding="utf-8")
    client.post(f"/audit/{aid}/memo", params={"lang": "sw"})
    assert len(prompts) == 1                                   # cached
    assert client.post(f"/audit/{aid}/memo", params={"lang": "fr"}).status_code == 422


def test_non_flood_report_is_received_not_corroborated(client, monkeypatch):
    monkeypatch.setattr(reports.meta, "spark_json", lambda prompt, **kw: {
        "issue_type": "power_outage", "place": "Mathare", "urgency": "medium",
        "summary_en": "Power has been off since morning.", "summary_sw": "Umeme umekatika tangu asubuhi."})
    monkeypatch.setattr(reports, "corroborate", lambda lon, lat: pytest.fail("power reports have no flood check"))
    r = post_report(client, client_id="power-1").json()
    assert r["issue_type"] == "power_outage" and r["profile"] == "solar_minigrid" and r["status"] == "received"
    types = client.get("/report-types").json()
    assert types["standing_water"]["profile"] == "flood" and types["water_supply"]["profile"] is None


def river_layers(monkeypatch):
    """A river along LAT (the valley floor of the synthetic DEM) for the place check."""
    from backend.app.services import assistant
    from tests.test_analyzers import LAT, LON, valley_dem
    river = {"type": "Feature", "properties": {"waterway": "river", "name": "Test River"},
             "geometry": mapping(LineString([(LON - 0.01, LAT), (LON + 0.01, LAT)]))}
    monkeypatch.setattr(assistant, "load_layer", lambda name, bounds, **kw: [river] if name == "osm_waterways" else [])
    monkeypatch.setattr(assistant, "load_dem", lambda bounds: valley_dem())
    return LON, LAT


def test_place_check_and_quick_questions(client, monkeypatch):
    lon, lat = river_layers(monkeypatch)
    by_river = client.post("/check", json={"lat": lat + 15 / 111_320, "lon": lon}).json()
    assert by_river["flood_risk"] == "high" and by_river["in_riparian_reserve"] is True
    assert by_river["in_2024_flood"] is None and any("Riparian" in n for n in by_river["notes"])
    uphill = client.post("/check", json={"lat": lat + 600 / 111_320, "lon": lon}).json()
    assert uphill["flood_risk"] == "low" and uphill["in_riparian_reserve"] is False

    first = {"lat": lat, "lon": lon, "device_id": "phone-9"}
    r = client.post("/observations", json={**first, "question_id": "flooded_last_season", "answer": "knee"}).json()
    assert r["next"]["id"] == "water_stays"                       # asks the next unanswered question
    assert client.post("/observations", json={**first, "question_id": "flooded_last_season",
                                              "answer": "swimming"}).status_code == 400
    said = client.post("/check", json={"lat": lat, "lon": lon}).json()["neighbours_say"]
    assert said["flooded_last_season"]["answers"] == {"Knee deep": 1}


def test_ask_routes_to_the_right_analysis(client, monkeypatch):
    from backend.app.services import assistant
    lon, lat = river_layers(monkeypatch)
    routes = iter([{"use_case": "business_site", "place": None, "business": "pharmacy",
                    "competitor_tags": ["amenity=pharmacy", "nonsense"]},
                   {"use_case": "flood", "place": None},
                   {"use_case": "weather", "place": None}])
    monkeypatch.setattr(assistant.meta, "spark_json", lambda prompt, **kw: next(routes))
    prompts, audits = [], []
    monkeypatch.setattr(assistant.meta, "spark", lambda prompt, **kw: prompts.append(prompt) or {
        "text": "Verdict: ...", "citations": [{"url": "https://example.org", "title": "x"}], "web_searches": 1})
    fake = {"business_site": {"verdict": "STRONG_OPPORTUNITY", "competitors": 0, "people_in_catchment_est": 4000,
                              "people_per_competitor_est": 4000, "anchors": {"schools": 2}},
            "flood": {"risk": {"high": 1}}}
    monkeypatch.setattr(assistant, "cached_audit", lambda pid, lon, lat, params, side_m: audits.append((pid, params, side_m))
                        or {"audit_id": "abc", "summary": fake[pid], "files": {"mosaic": "/outputs/api/abc/mosaic.jpg"}})

    biz = client.post("/ask", json={"message": "Is this a good spot for a pharmacy?", "lat": lat, "lon": lon}).json()
    assert biz["use_case"] == "business_site" and biz["audit"]["files"]["mosaic"].endswith("mosaic.jpg")
    assert audits[0] == ("business_site", {"business": "pharmacy", "competitor_tags": ["amenity=pharmacy"]}, 1000)
    assert biz["verdict"] == {"label": "Strong opportunity", "tone": "good"}
    assert {"icon": "competitors", "label": "Competitors within 500 m", "value": 0} in biz["highlights"]
    assert biz["ask"] is None                                  # a map pin, not someone standing there

    flood = client.post("/ask", json={"message": "Does it flood?", "lang": "sw", "lat": lat + 15 / 111_320, "lon": lon,
                                      "on_site": True, "device_id": "p1"}).json()
    assert flood["check"]["flood_risk"] == "high" and flood["ask"]["id"] == "flooded_last_season"
    assert flood["verdict"] == {"label": "High flood risk", "tone": "poor"}
    assert "Kiswahili" in prompts[1]

    other = client.post("/ask", json={"message": "Will it rain tomorrow?"}).json()
    assert other["use_case"] == "general" and other["audit"] is None and "can analyse" in prompts[2]


def test_google_competitors_pages_and_filters(client, monkeypatch):
    from backend.app.services import assistant
    lon, lat = 36.80, -1.29
    place = lambda i, dx, status="OPERATIONAL", rating=4.0: {
        "id": f"p{i}", "displayName": {"text": f"Chemist {i}"}, "businessStatus": status, "rating": rating,
        "userRatingCount": 10, "location": {"latitude": lat, "longitude": lon + dx / 111_320}}
    pages = [{"places": [place(1, 100), place(2, 450), place(3, 300, "CLOSED_PERMANENTLY")], "nextPageToken": "t2"},
             {"places": [place(4, 700), place(5, 50, rating=5.0)]}]          # 700 m: outside the 500 m circle
    sent = []

    class FakeClient:
        def __init__(self, **kw): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def post(self, url, json, headers):
            sent.append(json)
            page = pages[len(sent) - 1]
            return type("R", (), {"raise_for_status": lambda self: None, "json": lambda self: page})()

    monkeypatch.setattr(assistant.httpx, "Client", FakeClient)
    monkeypatch.setattr(assistant.settings, "google_maps_api_key", "test-key")
    g = assistant.google_competitors("pharmacy", lon, lat, 500)
    assert sent[1]["pageToken"] == "t2" and sent[0]["textQuery"] == "pharmacy"
    assert g["count"] == 3 and [x["name"] for x in g["nearest"]] == ["Chemist 5", "Chemist 1", "Chemist 2"]
    assert g["avg_rating"] == 4.3 and g["source"] == "Google Maps"
    monkeypatch.setattr(assistant.settings, "google_maps_api_key", "")
    assert assistant.google_competitors("pharmacy", lon, lat, 500) is None    # no key: OpenStreetMap only


def test_place_suggestions_rank_suburbs_and_prefixes_first(client, monkeypatch):
    from backend.app.services import assistant
    monkeypatch.setattr(assistant, "_gazetteer", lambda: [
        ("west hill school", "West Hill School", "school", 36.78, -1.31),
        ("westlands", "Westlands", "suburb", 36.80, -1.26),
        ("south westlands", "South Westlands", "neighbourhood", 36.80, -1.27),
        ("westlands", "Westlands", "marketplace", 36.80, -1.26)])
    names = [p["name"] for p in client.get("/places", params={"q": "WEST"}).json()]
    assert names == ["Westlands", "West Hill School", "South Westlands"]       # duplicate name dropped
    assert client.get("/places", params={"q": "w"}).json() == []



def test_spark_returns_only_the_final_answer(monkeypatch):
    from backend.app.services import meta
    msg = lambda text, urls=(): {"type": "message", "content": [{"type": "output_text", "text": text, "annotations": [
        {"type": "url_citation", "url": u, "title": "t"} for u in urls]}]}
    out = {"output": [msg("I'll check Nairobi's zoning rules.", ["https://a.org"]), {"type": "web_search_call"},
                      msg("I found the Zone 4D limit; opening it.", ["https://a.org", "https://b.org"]),
                      {"type": "web_search_call"}, msg("Verdict: medium density.", ["https://b.org"])]}
    monkeypatch.setattr(meta.settings, "meta_api_key", "k")
    monkeypatch.setattr(meta.httpx, "post", lambda *a, **k: type("R", (), {
        "raise_for_status": lambda self: None, "json": lambda self: out})())
    ans = meta.spark("q", web_search=True)
    assert ans["text"] == "Verdict: medium density." and ans["web_searches"] == 2
    assert [c["url"] for c in ans["citations"]] == ["https://a.org", "https://b.org"]      # all sources, no repeats
