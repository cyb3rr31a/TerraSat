"""Citizen reports and crew tasks, stored in SQLite.

A resident's voice note becomes a report:
    any audio -> WAV -> transcript (Muse Voice) -> issue/place/urgency (Muse Spark)
    -> corroborated against TerraSat's layers (river distance, height, 2024 floods).
Officers assign reports to crews as tasks; crews mark them cleared.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from shapely.geometry import Point, shape
from shapely.ops import nearest_points, unary_union

from backend.app.core.config import settings
from backend.app.services import audio, geo, meta
from backend.app.services.analyzers import flood_2024_checker
from backend.app.services.layers import load_dem, load_layer

ISSUE_TYPES = ["blocked_drain", "flooding", "river_overflow", "garbage", "collapsed_bridge", "other"]
REPORT_STATUSES = ["received", "corroborated", "unconfirmed", "assigned", "cleared", "dismissed"]
TASK_STATUSES = ["assigned", "en_route", "cleared"]
# Names transcription often garbles (e.g. "Athare", "madharek" for Mathare) - Muse Spark maps them back.
NAIROBI_PLACES = ["Mathare", "Mukuru Kwa Reuben", "Mukuru Kwa Njenga", "Kibera", "Korogocho", "Lucky Summer",
                  "Kariobangi", "Dandora", "Kayole", "Komarock", "Njiru", "Ruai", "Mwiki", "Kiambiu", "Donholm",
                  "Eastleigh", "Gikomba", "Globe", "CBD", "Industrial Area", "South B", "South C", "Kawangware",
                  "Kangemi", "Westlands", "Parklands", "Kilimani", "Kileleshwa", "Lang'ata", "Madaraka"]

# Rough centres used when a report has no GPS fix but names a known place.
PLACE_CENTRES = {"mathare": (36.8594, -1.2625), "mukuru": (36.8789, -1.3102), "kibera": (36.7887, -1.3146),
                 "korogocho": (36.8855, -1.2455)}
KENYA = (33.9, -4.8, 41.9, 5.1)  # west, south, east, north

SCHEMA = """
CREATE TABLE IF NOT EXISTS reports (
  id INTEGER PRIMARY KEY, client_id TEXT UNIQUE, device_id TEXT, created_at TEXT,
  lat REAL, lon REAL, accuracy_m REAL, audio_path TEXT, photo_path TEXT,
  transcript TEXT, issue_type TEXT, place TEXT, urgency TEXT, summary_en TEXT, summary_sw TEXT,
  context TEXT, status TEXT, notes TEXT, location_source TEXT);
CREATE TABLE IF NOT EXISTS crews (id INTEGER PRIMARY KEY, name TEXT, phone TEXT);
CREATE TABLE IF NOT EXISTS tasks (
  id INTEGER PRIMARY KEY, report_id INTEGER REFERENCES reports(id), crew_id INTEGER REFERENCES crews(id),
  status TEXT, notes TEXT, after_photo_path TEXT, created_at TEXT, updated_at TEXT);
"""
DEMO_CREWS = [("Crew A - Mathare", ""), ("Crew B - Mukuru", ""), ("Crew C - Korogocho", "")]


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path: Optional[Path] = None) -> sqlite3.Connection:
    path = Path(path or settings.db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA)
    if "location_source" not in [r["name"] for r in db.execute("PRAGMA table_info(reports)")]:
        db.execute("ALTER TABLE reports ADD COLUMN location_source TEXT")
    if not db.execute("SELECT 1 FROM crews LIMIT 1").fetchone():
        db.executemany("INSERT INTO crews (name, phone) VALUES (?, ?)", DEMO_CREWS)
    db.commit()
    return db


def save_media(data: bytes, suffix: str) -> str:
    folder = Path(settings.data_dir) / "media"
    folder.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4().hex}{suffix}"
    (folder / name).write_bytes(data)
    return name  # served at /media/<name>


def parse_report(transcript: str) -> dict:
    """Muse Spark turns a free-form EN/SW/Sheng transcript into structured fields."""
    prompt = (
        "A Nairobi resident sent this flood or drainage report as a voice note (English, Swahili or Sheng):\n"
        f'"{transcript}"\n\n'
        f"Return JSON with: issue_type (one of {ISSUE_TYPES}), place (the neighbourhood or landmark; "
        f"transcription often garbles names, so match to one of {NAIROBI_PLACES} when it sounds similar, "
        "plus any landmark such as 'near the bridge'), urgency (low, medium or high), "
        "summary_en (one sentence in English), summary_sw (one sentence in Swahili).")
    out = meta.spark_json(prompt)
    if out.get("issue_type") not in ISSUE_TYPES:
        out["issue_type"] = "other"
    return {k: out.get(k) for k in ("issue_type", "place", "urgency", "summary_en", "summary_sw")}


def corroborate(lon: float, lat: float, near_m: float = 100) -> dict:
    """Does what TerraSat knows about this spot support a flood report?"""
    pad = 0.01
    bounds = (lon - pad, lat - pad, lon + pad, lat + pad)
    p_utm = geo.to_utm(Point(lon, lat))
    ctx = {"distance_to_watercourse_m": None, "height_above_watercourse_m": None, "in_2024_flood": None}
    water = [shape(f["geometry"]) for f in load_layer("osm_waterways", bounds)]
    if water:
        union = unary_union(water)
        ctx["distance_to_watercourse_m"] = round(geo.to_utm(union).distance(p_utm), 1)
        dem = load_dem(bounds, pad_deg=0.002)
        if dem is not None:
            q = nearest_points(union, Point(lon, lat))[0]
            r, c = dem.cells([lon, q.x], [lat, q.y])
            ctx["height_above_watercourse_m"] = round(float(dem.z[r[0], c[0]] - dem.z[r[1], c[1]]), 1)
    # None = the 2024 satellite image couldn't see this spot (cloud, or outside the mapping)
    ctx["in_2024_flood"] = flood_2024_checker(load_layer("unosat_2024", bounds), near_m=30)(Point(lon, lat))
    # past floods named in the news within 1 km: shown to officers, not part of the rule below
    ctx["past_floods_nearby"] = [f"{f['properties']['place']} ({f['properties']['date']})"
                                 for f in load_layer("flood_history", bounds)
                                 if geo.to_utm(shape(f["geometry"])).distance(p_utm) <= 1000][:5]
    d, h = ctx["distance_to_watercourse_m"], ctx["height_above_watercourse_m"]
    ctx["corroborated"] = bool((d is not None and d <= near_m) or ctx["in_2024_flood"]
                               or (h is not None and h < 3 and d is not None and d <= 3 * near_m))
    return ctx


def create_report(db, audio_bytes: bytes, audio_suffix: str, lat: Optional[float], lon: Optional[float],
                  accuracy_m: Optional[float] = None, photo: Optional[bytes] = None, photo_suffix: str = ".jpg",
                  device_id: str = "", client_id: Optional[str] = None) -> dict:
    has_gps = lat is not None and lon is not None
    if has_gps and not (KENYA[1] <= lat <= KENYA[3] and KENYA[0] <= lon <= KENYA[2]):
        raise ValueError(f"lat/lon ({lat}, {lon}) is outside Kenya - send the phone's GPS fix, or leave it out")
    if client_id:  # the phone's offline queue may send the same report twice
        row = db.execute("SELECT id FROM reports WHERE client_id = ?", (client_id,)).fetchone()
        if row:
            return get_report(db, row["id"])
    transcript = meta.transcribe(audio.to_wav(audio_bytes, audio_suffix))
    fields = parse_report(transcript) if transcript else {}
    location_source = "gps" if has_gps else None
    if not has_gps:  # no GPS fix: fall back to a known place named in the report
        place = (fields.get("place") or "").lower()
        match = next((c for name, c in PLACE_CENTRES.items() if name in place), None)
        if match:
            (lon, lat), location_source = match, "place_name"
    ctx = corroborate(lon, lat) if lat is not None and lon is not None else {"corroborated": False}
    cur = db.execute(
        "INSERT INTO reports (client_id, device_id, created_at, lat, lon, accuracy_m, audio_path, photo_path,"
        " transcript, issue_type, place, urgency, summary_en, summary_sw, context, status, location_source)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (client_id or uuid.uuid4().hex, device_id, now(), lat, lon, accuracy_m,
         save_media(audio_bytes, audio_suffix or ".m4a"), save_media(photo, photo_suffix) if photo else None,
         transcript, fields.get("issue_type"), fields.get("place"), fields.get("urgency"),
         fields.get("summary_en"), fields.get("summary_sw"), json.dumps(ctx),
         "corroborated" if ctx.get("corroborated") else "unconfirmed", location_source))
    db.commit()
    return get_report(db, cur.lastrowid)


def _row(row) -> dict:
    d = dict(row)
    if "context" in d:
        d["context"] = json.loads(d["context"] or "{}")
    return d


def get_report(db, report_id: int) -> Optional[dict]:
    row = db.execute("SELECT * FROM reports WHERE id = ?", (report_id,)).fetchone()
    return _row(row) if row else None


def list_reports(db, status: Optional[str] = None, device_id: Optional[str] = None,
                 since: Optional[str] = None) -> list[dict]:
    sql, args = "SELECT * FROM reports WHERE 1=1", []
    for col, val, op in (("status", status, "="), ("device_id", device_id, "="), ("created_at", since, ">")):
        if val:
            sql += f" AND {col} {op} ?"
            args.append(val)
    return [_row(r) for r in db.execute(sql + " ORDER BY id DESC", args)]


def update_report(db, report_id: int, status: Optional[str] = None, notes: Optional[str] = None) -> Optional[dict]:
    if status and status not in REPORT_STATUSES:
        raise ValueError(f"status must be one of {REPORT_STATUSES}")
    db.execute("UPDATE reports SET status = COALESCE(?, status), notes = COALESCE(?, notes) WHERE id = ?",
               (status, notes, report_id))
    db.commit()
    return get_report(db, report_id)


def list_crews(db) -> list[dict]:
    return [dict(r) for r in db.execute("SELECT * FROM crews ORDER BY id")]


def create_task(db, report_id: int, crew_id: int, notes: str = "") -> dict:
    if not get_report(db, report_id):
        raise LookupError(f"report {report_id} not found")
    cur = db.execute("INSERT INTO tasks (report_id, crew_id, status, notes, created_at, updated_at)"
                     " VALUES (?, ?, 'assigned', ?, ?, ?)", (report_id, crew_id, notes, now(), now()))
    db.execute("UPDATE reports SET status = 'assigned' WHERE id = ?", (report_id,))
    db.commit()
    return get_task(db, cur.lastrowid)


def get_task(db, task_id: int) -> Optional[dict]:
    row = db.execute("SELECT t.*, r.lat, r.lon, r.place, r.issue_type, r.summary_en, r.summary_sw, c.name AS crew"
                     " FROM tasks t JOIN reports r ON r.id = t.report_id JOIN crews c ON c.id = t.crew_id"
                     " WHERE t.id = ?", (task_id,)).fetchone()
    return dict(row) if row else None


def list_tasks(db, crew_id: Optional[int] = None) -> list[dict]:
    ids = db.execute("SELECT id FROM tasks" + (" WHERE crew_id = ?" if crew_id else "") + " ORDER BY id DESC",
                     (crew_id,) if crew_id else ()).fetchall()
    return [get_task(db, r["id"]) for r in ids]


def update_task(db, task_id: int, status: str, notes: Optional[str] = None,
                after_photo: Optional[bytes] = None, photo_suffix: str = ".jpg") -> Optional[dict]:
    if status not in TASK_STATUSES:
        raise ValueError(f"status must be one of {TASK_STATUSES}")
    task = get_task(db, task_id)
    if not task:
        return None
    photo = save_media(after_photo, photo_suffix) if after_photo else None
    db.execute("UPDATE tasks SET status = ?, notes = COALESCE(?, notes),"
               " after_photo_path = COALESCE(?, after_photo_path), updated_at = ? WHERE id = ?",
               (status, notes, photo, now(), task_id))
    if status == "cleared":  # closes the loop: the resident sees their report cleared
        db.execute("UPDATE reports SET status = 'cleared' WHERE id = ?", (task["report_id"],))
    db.commit()
    return get_task(db, task_id)
