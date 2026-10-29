"""
TerraSat API. Business logic lives in app/services and use cases in
app/profiles; the mobile app and the dashboard both call these endpoints.
Interactive docs: http://127.0.0.1:8000/docs
"""
import hashlib
import json
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend.app.core.config import settings
from backend.app.profiles.loader import list_profiles, load_profile
from backend.app.services import reports
from backend.app.services.audit import PRESETS, run_audit, save_audit

app = FastAPI(title="TerraSat", version="0.2.0",
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
    raise HTTPException(502, f"Upstream service failed: {e}")


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
    if (folder / "summary.json").exists():
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
def get_reports(status: Optional[str] = None, device_id: Optional[str] = None, since: Optional[str] = None):
    """Dashboard feed (filter by status / since) or one resident's reports (device_id)."""
    return reports.list_reports(db(), status, device_id, since)


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
