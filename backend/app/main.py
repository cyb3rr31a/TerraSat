"""
TerraSat API. Business logic lives in app/services and use cases in
app/profiles; the mobile app and the dashboard both call these endpoints.
Interactive docs: http://127.0.0.1:8000/docs (click "Authorize" to enter the API key)

Access: every endpoint except /health needs the X-API-Key header once API_KEY is set in .env;
staff-only endpoints also need X-Staff-Key. Limits and keys live in core/security.py.
"""
import csv
import io
import json
import re
from pathlib import Path
from typing import Literal, Optional

import httpx
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from backend.app.core.config import settings
from backend.app.core.security import (ASK_LIMIT, LIGHT_LIMIT, REPORT_LIMIT, is_staff, limited, require_api_key,
                                       require_staff)
from backend.app.profiles.loader import list_profiles, load_profile
from backend.app.services import assistant, reports
from backend.app.services.audit import PRESETS, cached_audit, ranked_choke_points, write_memo

app = FastAPI(title="TerraSat", version="0.5.0", dependencies=[Depends(require_api_key)],
              description="Urban planning assistant on a geospatial auditing engine: satellite imagery + SAM 3.1 + "
                          "spatial rules + Muse Spark, configured by audit profiles, plus ground truth from people "
                          "(reports, quick questions, chat). Case study: Nairobi flood risk.")
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


def read_upload(f: UploadFile, max_mb: float, what: str) -> bytes:
    """The upload's bytes, refusing anything over max_mb before reading it all into memory."""
    limit = int(max_mb * 1024 * 1024)
    data = f.file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(413, f"{what} is too large (max {max_mb:g} MB)")
    return data


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


@app.post("/audit", dependencies=[Depends(limited(ASK_LIMIT))])
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
        return cached_audit(req.profile, lon, lat, req.params, refresh=req.refresh)
    except KeyError as e:
        raise HTTPException(400, str(e))
    except Exception as e:  # noqa: BLE001
        fail(e)


@app.get("/audit/{audit_id}/choke-points")
def choke_points(audit_id: str, format: Literal["json", "csv"] = "json"):
    """Drainage choke points (culverts and bridges), ranked with the latest residents' reports."""
    rows = [{**{k: f["properties"].get(k) for k in ("rank", "score", "kind", "road", "watercourse", "upstream_ha",
                                                    "buildings_at_risk_nearby", "reports_nearby", "in_2024_flood")},
             "lat": round(f["geometry"]["coordinates"][1], 6), "lon": round(f["geometry"]["coordinates"][0], 6)}
            for f in ranked_choke_points(audit_folder(audit_id), reports.list_reports(db()))]
    return csv_response(rows, f"choke_points_{audit_id}.csv") if format == "csv" else rows


@app.post("/audit/{audit_id}/memo", dependencies=[Depends(limited(ASK_LIMIT))])
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
@app.post("/reports", dependencies=[Depends(limited(REPORT_LIMIT))])
def create_report(audio: UploadFile = File(...), lat: Optional[float] = Form(None), lon: Optional[float] = Form(None),
                  accuracy_m: Optional[float] = Form(None), device_id: str = Form(""),
                  client_id: Optional[str] = Form(None), photo: Optional[UploadFile] = File(None)) -> dict:
    """A resident's voice note (any audio format) with GPS and an optional photo."""
    audio_bytes = read_upload(audio, settings.max_audio_mb, "The voice note")
    photo_bytes = read_upload(photo, settings.max_photo_mb, "The photo") if photo else None
    try:
        return reports.create_report(
            db(), audio_bytes, Path(audio.filename or "").suffix.lower() or ".m4a", lat, lon, accuracy_m,
            photo_bytes, Path(photo.filename or "").suffix.lower() if photo else ".jpg", device_id, client_id)
    except Exception as e:  # noqa: BLE001
        fail(e)


@app.get("/reports")
def get_reports(status: Optional[str] = None, device_id: Optional[str] = None, since: Optional[str] = None,
                format: Literal["json", "csv"] = "json", x_staff_key: Optional[str] = Header(None)):
    """One person's reports (device_id), or, for staff, everyone's (filter by status / since; format=csv)."""
    if not device_id and not is_staff(x_staff_key):
        raise HTTPException(403, "Give your device_id, or send the X-Staff-Key header to see everyone's reports")
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


@app.patch("/reports/{report_id}", dependencies=[Depends(require_staff)])
def patch_report(report_id: int, body: ReportUpdate) -> dict:
    try:
        out = reports.update_report(db(), report_id, body.status, body.notes)
    except ValueError as e:
        fail(e)
    if not out:
        raise HTTPException(404, "report not found")
    return out


@app.get("/places", dependencies=[Depends(limited(LIGHT_LIMIT))])
def places(q: str) -> list[dict]:
    """Place suggestions while typing (suburbs and landmarks in Nairobi)."""
    return assistant.search_places(q)


@app.get("/report-types")
def report_types() -> dict:
    """What people can report: {type: {en, sw, profile}}. Comes from the audit profiles."""
    return reports.report_types()


# ------------------------------------------------- place check, chat, questions
class Spot(BaseModel):
    lat: float
    lon: float


@app.post("/check", dependencies=[Depends(limited(LIGHT_LIMIT))])
def check(body: Spot) -> dict:
    """What TerraSat knows about one spot: flood risk class, riparian reserve, 2024 flood,
    past floods, reports and neighbours' answers nearby."""
    try:
        return assistant.check_place(db(), body.lon, body.lat)
    except ValueError as e:
        fail(e)


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    text: str = Field(max_length=4000)


class AskRequest(BaseModel):
    message: str = Field(min_length=1, max_length=1000)
    lang: Literal["en", "sw"] = "en"
    lat: Optional[float] = None      # the map pin, or the phone's location
    lon: Optional[float] = None
    on_site: bool = False            # true when lat/lon is the phone's own GPS (then quick questions are asked)
    device_id: str = ""
    history: list[ChatTurn] = Field(default=[], max_length=12)


@app.post("/ask", dependencies=[Depends(limited(ASK_LIMIT))])
def ask(body: AskRequest) -> dict:
    """Ask anything about a place: Muse Spark picks the analysis (flood, solar, densification,
    business site...) and the place, TerraSat runs it there (satellite picture + rules + ground truth),
    and Muse Spark answers with a verdict. Returns the reply, highlights, the audit (picture, GeoJSON)
    and, for people on site, a quick question."""
    try:
        return assistant.ask(db(), body.message, body.lang, body.lat, body.lon, body.device_id,
                             [t.model_dump() for t in body.history], body.on_site)
    except Exception as e:  # noqa: BLE001
        fail(e)


class Observation(BaseModel):
    question_id: str
    answer: str
    lat: float
    lon: float
    device_id: str = ""
    lang: Literal["en", "sw"] = "en"


@app.post("/observations", dependencies=[Depends(limited(LIGHT_LIMIT))])
def observe(body: Observation) -> dict:
    """Save a tap-to-answer reply and return the next question for this spot (or null)."""
    try:
        saved = reports.save_observation(db(), body.device_id, body.lat, body.lon, body.question_id, body.answer)
    except ValueError as e:
        fail(e)
    profile = reports.questions()[body.question_id]["profile"]
    return {"saved": saved, "next": assistant.next_question(db(), body.device_id, body.lon, body.lat, body.lang, profile)}
