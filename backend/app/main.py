"""
TerraSat API. Business logic lives in app/services and use cases in
app/profiles; the mobile app and the dashboard both call these endpoints.
Interactive docs: http://127.0.0.1:8000/docs
"""
import csv
import hashlib
import io
import json
import re
from pathlib import Path
from typing import Literal, Optional

import httpx
from fastapi import FastAPI, File, Form, HTTPException, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend.app.core.config import settings
from backend.app.profiles.loader import list_profiles, load_profile
from backend.app.services import reports
from backend.app.services.audit import PRESETS, ranked_choke_points, run_audit, save_audit, write_memo

app = FastAPI(title="TerraSat", version="0.3.0",
              description="Geospatial auditing engine: satellite imagery + SAM 3.1 + spatial rules + "
                          "Muse Spark, configured by audit profiles. Case study: Nairobi flood exposure.")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

DATA = Path(settings.data_dir)
for sub in ("outputs/api", "media"):
    (DATA / sub).mkdir(parents=True, exist_ok=True)
app.mount("/outputs", StaticFiles(directory=DATA / "outputs"), name="outputs")
app.mount("/media", StaticFiles(directory=DATA / "media"), name="media")

_db = None


def db():
    global _db
    if _db is None:
        _db = reports.connect()
    return _db


def fail(e: Exception):
    """Map service errors to HTTP status codes."""
    if isinstance(e, LookupError):
        raise HTTPException(404, str(e))
    if isinstance(e, ValueError):
        raise HTTPException(400, str(e))
    if isinstance(e, (httpx.HTTPError, RuntimeError)):  # Meta / Mapbox down, or a key missing
        raise HTTPException(502, f"Upstream service failed: {e}")
    raise e  # a bug: 500, with the full traceback in the server log


def csv_response(rows: list[dict], filename: str) -> Response:
    """Rows as a CSV download (opens in Excel / Google Sheets)."""
    buf = io.StringIO()
    if rows:
        w = csv.DictWriter(buf, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


def audit_folder(audit_id: str) -> Path:
    folder = DATA / "outputs" / "api" / audit_id
    if not re.fullmatch(r"[0-9a-f]{12}", audit_id) or not (folder / "summary.json").exists():
        raise HTTPException(404, "audit not found - run POST /audit first")
    return folder


# ------------------------------------------------------------------ engine
@app.get("/health")
def health() -> dict:
    return {"status": "ok", "meta_key_set": bool(settings.meta_api_key),
            "mapbox_token_set": bool(settings.mapbox_token)}


@app.get("/profiles")
def profiles() -> list[dict]:
    """Available audit profiles (use cases) and what each one looks for."""
    return [{"id": p.id, "name": p.name, "tagline": p.tagline, "status": p.status,
             "audience": p.audience, "classes": {k: v.prompts for k, v in p.classes.items()},
             "layers": p.layers} for p in list_profiles()]


@app.get("/presets")
def presets() -> dict:
    return {name: {"lon": lon, "lat": lat} for name, (lon, lat) in PRESETS.items()}


class AuditRequest(BaseModel):
    profile: str = "flood"
    preset: Optional[str] = None
    lon: Optional[float] = None
    lat: Optional[float] = None
    params: dict = {}
    refresh: bool = False   # re-run even if cached (e.g. after new layers or code)


@app.post("/audit")
def audit(req: AuditRequest) -> dict:
    """Run (or reuse) an audit. Results are cached on disk, so repeats are instant."""
    if req.preset:
        if req.preset not in PRESETS:
            raise HTTPException(400, f"Unknown preset; choose from {list(PRESETS)}")
        lon, lat = PRESETS[req.preset]
    elif req.lon is not None and req.lat is not None:
        lon, lat = req.lon, req.lat
    else:
        raise HTTPException(400, "Give a preset, or lon and lat")
    try:
        load_profile(req.profile)
    except KeyError as e:
        raise HTTPException(400, str(e))
    key = json.dumps([req.profile, round(lon, 5), round(lat, 5), req.params], sort_keys=True)
    audit_id = hashlib.sha1(key.encode()).hexdigest()[:12]
    folder = DATA / "outputs" / "api" / audit_id
    if (folder / "summary.json").exists() and not req.refresh:
        info = json.loads((folder / "summary.json").read_text())
    else:
        try:
            info = save_audit(run_audit(req.profile, lon, lat, params=req.params), folder)
        except Exception as e:  # noqa: BLE001
            fail(e)
    base = f"/outputs/api/{audit_id}"
    return {"audit_id": audit_id, "center": {"lon": lon, "lat": lat}, **info,
            "files": {"geojson": f"{base}/audit.geojson", "overlay": f"{base}/overlay.png",
                      "mosaic": f"{base}/mosaic.jpg"}}


@app.get("/audit/{audit_id}/choke-points")
def choke_points(audit_id: str, format: Literal["json", "csv"] = "json"):
    """Drainage choke points (culverts and bridges), ranked with the latest residents' reports."""
    rows = [{**{k: f["properties"].get(k) for k in ("rank", "score", "kind", "road", "watercourse", "upstream_ha",
                                                    "buildings_at_risk_nearby", "reports_nearby", "in_2024_flood")},
             "lat": round(f["geometry"]["coordinates"][1], 6), "lon": round(f["geometry"]["coordinates"][0], 6)}
            for f in ranked_choke_points(audit_folder(audit_id), reports.list_reports(db()))]
    return csv_response(rows, f"choke_points_{audit_id}.csv") if format == "csv" else rows


@app.post("/audit/{audit_id}/memo")
def memo(audit_id: str, lang: Literal["en", "sw"] = "en", refresh: bool = False) -> dict:
    """Briefing memo by Muse Spark, with sources. Cached; refresh=true writes a new one
    (e.g. after new reports or a new forecast). Download: /outputs/api/<audit_id>/memo_<lang>.md"""
    folder = audit_folder(audit_id)
    cached = folder / f"memo_{lang}.json"
    if cached.exists() and not refresh:
        return json.loads(cached.read_text(encoding="utf-8"))
    try:
        return write_memo(folder, reports.list_reports(db()), lang)
    except Exception as e:  # noqa: BLE001
        fail(e)


# ------------------------------------------------------- citizen reports
@app.post("/reports")
def create_report(audio: UploadFile = File(...), lat: Optional[float] = Form(None), lon: Optional[float] = Form(None),
                  accuracy_m: Optional[float] = Form(None), device_id: str = Form(""),
                  client_id: Optional[str] = Form(None), photo: Optional[UploadFile] = File(None)) -> dict:
    """A resident's voice note (any audio format) with GPS and an optional photo."""
    try:
        return reports.create_report(
            db(), audio.file.read(), Path(audio.filename or "").suffix.lower() or ".m4a", lat, lon, accuracy_m,
            photo.file.read() if photo else None, Path(photo.filename or "").suffix.lower() if photo else ".jpg",
            device_id, client_id)
    except Exception as e:  # noqa: BLE001
        fail(e)


@app.get("/reports")
def get_reports(status: Optional[str] = None, device_id: Optional[str] = None, since: Optional[str] = None,
                format: Literal["json", "csv"] = "json"):
    """Dashboard feed (filter by status / since) or one resident's reports (device_id). format=csv to export."""
    rows = reports.list_reports(db(), status, device_id, since)
    if format == "csv":
        keep = ("id", "created_at", "status", "issue_type", "urgency", "place", "lat", "lon", "location_source",
                "summary_en", "summary_sw", "transcript")
        return csv_response([{**{k: r.get(k) for k in keep}, "corroborated": r["context"].get("corroborated"),
                              "distance_to_watercourse_m": r["context"].get("distance_to_watercourse_m")}
                             for r in rows], "reports.csv")
    return rows


class ReportUpdate(BaseModel):
    status: Optional[str] = None
    notes: Optional[str] = None


@app.patch("/reports/{report_id}")
def patch_report(report_id: int, body: ReportUpdate) -> dict:
    try:
        out = reports.update_report(db(), report_id, body.status, body.notes)
    except ValueError as e:
        fail(e)
    if not out:
        raise HTTPException(404, "report not found")
    return out


# ------------------------------------------------------------ crew tasks
@app.get("/crews")
def crews() -> list[dict]:
    return reports.list_crews(db())


class TaskCreate(BaseModel):
    report_id: int
    crew_id: int
    notes: str = ""


@app.post("/tasks")
def create_task(body: TaskCreate) -> dict:
    try:
        return reports.create_task(db(), body.report_id, body.crew_id, body.notes)
    except Exception as e:  # noqa: BLE001
        fail(e)


@app.get("/tasks")
def get_tasks(crew_id: Optional[int] = None) -> list[dict]:
    return reports.list_tasks(db(), crew_id)


@app.patch("/tasks/{task_id}")
def patch_task(task_id: int, status: str = Form(...), notes: Optional[str] = Form(None),
               photo: Optional[UploadFile] = File(None)) -> dict:
    """Crew updates: en_route / cleared, optionally with an after photo."""
    try:
        out = reports.update_task(db(), task_id, status, notes, photo.file.read() if photo else None,
                                  Path(photo.filename or "").suffix.lower() if photo else ".jpg")
    except ValueError as e:
        fail(e)
    if not out:
        raise HTTPException(404, "task not found")
    return out
