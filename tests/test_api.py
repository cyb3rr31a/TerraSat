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


def test_report_to_cleared_task_loop(client):
    r = post_report(client).json()
    assert r["issue_type"] == "blocked_drain" and r["status"] == "corroborated"
    assert r["summary_sw"] and r["context"]["corroborated"] is True
    assert post_report(client).json()["id"] == r["id"]           # offline-queue retry: no duplicate
    assert len(client.get("/reports", params={"device_id": "phone-1"}).json()) == 1

    crew = client.get("/crews").json()[0]
    task = client.post("/tasks", json={"report_id": r["id"], "crew_id": crew["id"]}).json()
    assert task["status"] == "assigned" and task["place"].startswith("Mathare")
    assert client.get(f"/reports").json()[0]["status"] == "assigned"

    done = client.patch(f"/tasks/{task['id']}", data={"status": "cleared"},
                        files={"photo": ("after.jpg", b"jpeg", "image/jpeg")}).json()
    assert done["status"] == "cleared" and done["after_photo_path"]
    assert client.get("/reports").json()[0]["status"] == "cleared"   # the resident sees it cleared
    assert len(client.get("/tasks", params={"crew_id": crew["id"]}).json()) == 1


def test_bad_inputs(client):
    assert client.patch("/tasks/999", data={"status": "cleared"}).status_code == 404
    assert client.post("/tasks", json={"report_id": 999, "crew_id": 1}).status_code == 404
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
    monkeypatch.setattr(main, "run_audit", lambda *a, **k: calls.append(a) or object())
    monkeypatch.setattr(main, "save_audit", fake_save)
    monkeypatch.setattr(main, "DATA", settings.data_dir)
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
