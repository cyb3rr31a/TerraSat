"""The planning assistant: ask anything about a place and get the matching analysis.

ask(...)               Muse Spark reads the question and picks the use case (flood, solar,
                       densification, business site...) and the place; TerraSat runs that
                       profile's audit on a small square there (satellite picture + SAM + rules),
                       adds what people report, and Muse Spark answers with a verdict and sources.
check_place(lon, lat)  flood facts for one spot (risk class, riparian reserve, 2024 flood,
                       past floods) plus ground truth (reports and neighbours' answers).
"""
from __future__ import annotations

import json
import math
import re
import time
from functools import lru_cache
from typing import Optional

import httpx
from shapely.geometry import Point, shape

from backend.app.core.config import settings
from backend.app.profiles.loader import list_profiles, load_profile
from backend.app.services import geo, meta, reports
from backend.app.services.audit import cached_audit
from backend.app.services.analyzers import (add_terrain, business_verdict, compute_exposure, flood_2024_checker,
                                            flow_grids, score_risk)
from backend.app.services.layers import load_dem, load_layer
from backend.app.services.sam_service import Detection

NAIROBI = (36.65, -1.45, 37.10, -1.15)  # west, south, east, north: where TerraSat has map data today
RIPARIAN_NOTE = ("Riparian reserve: 6-30 m from the highest water mark under the EMCA (Water Quality) "
                 "Regulations 2006; the government enforces 30 m along the Nairobi Rivers (Interior Ministry, May 2024).")
LANGUAGES = {"en": "English", "sw": "Kiswahili"}


# ------------------------------------------------------------------ geocoding
# Short names news uses that match a different place first on the map
ALIASES = {"kwa njenga": "Mukuru Kwa Njenga", "kwa reuben": "Mukuru Kwa Reuben", "kwa rueben": "Mukuru Kwa Reuben"}


def name_variants(place: str) -> list[str]:
    """Search terms for a place as people write it, most specific first:
    "Mombasa Road at Cabanas" -> itself, "Cabanas", "Mombasa Road"; "Jomo Kenyatta ... (JKIA)" -> also "JKIA"."""
    place = ALIASES.get(place.strip().lower(), place)
    inner = re.findall(r"\(([^)]+)\)", place)
    base = re.sub(r"\([^)]*\)", "", place)
    parts = re.split(r",| in | at | along | near | and |/", base)
    clean = lambda t: re.sub(r"\b(informal settlement|slum|ward|junction)\b", "", t, flags=re.I).strip(" -")
    is_road = lambda t: bool(re.search(r"\b(road|highway|superhighway|avenue|bypass|street|way)\b", t, re.I))
    out: list[str] = []
    for t in [place, base, *sorted(parts, key=is_road), *inner]:  # a landmark beats a long road
        t = clean(t)
        if len(t) > 2 and t.lower() not in (o.lower() for o in out):
            out.append(t)
    return out[:5]


def geocode(place: str, client: Optional[httpx.Client] = None) -> Optional[tuple[float, float, str]]:
    """(lon, lat, matched name) via Nominatim, limited to Nairobi (usage policy: 1 request a
    second, identify the app). Prefers named places (suburbs, estates) over roads or shops."""
    own = client is None
    client = client or httpx.Client(timeout=20, headers={"User-Agent": "TerraSat/0.3 (hackathon)"})
    w, s, e, n = NAIROBI
    try:
        for name in name_variants(place):
            time.sleep(1.1)
            r = client.get("https://nominatim.openstreetmap.org/search",
                           params={"q": f"{name}, Nairobi, Kenya", "format": "jsonv2", "limit": 5,
                                   "viewbox": f"{w},{n},{e},{s}", "bounded": 1})
            r.raise_for_status()
            hits = r.json()
            if hits:
                best = next((h for h in hits if h.get("category") == "place"), hits[0])
                return float(best["lon"]), float(best["lat"]), best["display_name"]
    finally:
        if own:
            client.close()
    return None


@lru_cache(maxsize=256)
def _geocode_cached(place: str):
    return geocode(place)


# --------------------------------------------------------------- ground truth
def ground_truth(db, lon: float, lat: float, profile: Optional[str] = None) -> dict:
    """What people report (within 300 m) and answer (within 150 m) here, for one use case or all."""
    types = reports.report_types()
    keep_type = lambda t: profile is None or types.get(t, {}).get("profile") in (profile, None)
    here, d = geo.to_utm(Point(lon, lat)), 300 / 111_000
    rows = db.execute("SELECT issue_type, place, created_at, status, lon, lat FROM reports WHERE status != 'dismissed'"
                      " AND lat BETWEEN ? AND ? AND lon BETWEEN ? AND ? ORDER BY id DESC LIMIT 50",
                      (lat - d, lat + d, lon - d, lon + d)).fetchall()
    near = [{k: r[k] for k in ("issue_type", "place", "created_at", "status")} for r in rows
            if keep_type(r["issue_type"]) and geo.to_utm(Point(r["lon"], r["lat"])).distance(here) <= 300][:10]
    qs = reports.questions()
    said: dict = {}
    for o in reports.observations_near(db, lon, lat):
        q = qs.get(o["question_id"])
        if q and (profile is None or q["profile"] == profile):
            entry = said.setdefault(o["question_id"], {"question": q["en"], "answers": {}})
            label = q["options"][o["answer"]][0]
            entry["answers"][label] = entry["answers"].get(label, 0) + 1
    return {"reports_nearby": near, "neighbours_say": said}


# ---------------------------------------------------------------- place check
def check_place(db, lon: float, lat: float) -> dict:
    """Everything TerraSat knows about one spot, for a buyer, planner or resident."""
    if not (reports.KENYA[1] <= lat <= reports.KENYA[3] and reports.KENYA[0] <= lon <= reports.KENYA[2]):
        raise ValueError("lat/lon is outside Kenya")
    p = load_profile("flood").params
    pad = 0.006
    bounds = (lon - pad, lat - pad, lon + pad, lat + pad)
    covered = NAIROBI[0] <= lon <= NAIROBI[2] and NAIROBI[1] <= lat <= NAIROBI[3]
    out: dict = {"lat": lat, "lon": lon, "covered": covered, "flood_risk": None, "surface_water_risk": None,
                 "distance_to_watercourse_m": None, "height_above_watercourse_m": None, "watercourse_source": None,
                 "in_riparian_reserve": None, "riparian_reserve_m": p["riparian_buffer_m"]}
    pt = Point(lon, lat)
    if covered:
        # score the spot exactly like a building in an audit
        spot = Detection("building", "place", 1.0, geo.buffer_m(pt, 3), 0.0, {})
        waterways = load_layer("osm_waterways", bounds)
        compute_exposure([spot], waterways, bounds, buffer_m=p["riparian_buffer_m"])
        dem = load_dem(bounds)
        if dem is not None:
            add_terrain([spot], waterways, dem, p, flow_grids(dem))
        score_risk([spot], p)
        pr = spot.props
        out.update(flood_risk=pr["risk"], surface_water_risk=pr["surface_water_risk"] if dem is not None else None,
                   distance_to_watercourse_m=pr.get("distance_to_river_m"),
                   height_above_watercourse_m=pr.get("height_above_stream_m"),
                   watercourse_source=pr.get("watercourse") or ("osm" if pr.get("distance_to_river_m") is not None else None),
                   in_riparian_reserve=pr.get("in_riparian_zone"))
    out["in_2024_flood"] = flood_2024_checker(load_layer("unosat_2024", bounds), near_m=30)(pt)
    here = geo.to_utm(pt)
    out["past_floods_nearby"] = [{k: f["properties"].get(k) for k in ("place", "date", "what_happened", "source_url")}
                                 for f in load_layer("flood_history", bounds, pad_deg=0.01)  # placed at neighbourhood
                                 if geo.to_utm(shape(f["geometry"])).distance(here) <= 1500][:5]  # centres, so 1.5 km
    out.update(ground_truth(db, lon, lat))
    out["notes"] = ([] if covered else ["TerraSat has no flood map data here yet (Nairobi only)."]) + [
        "Flood risk class: distance to and height above the nearest watercourse, rules checked against "
        "UNOSAT's record of 2024 flood damage. Elevation is a 30 m surface model, so heights are approximate.",
        RIPARIAN_NOTE]
    return out


def next_question(db, device_id: str, lon: float, lat: float, lang: str = "en", profile: str = "flood") -> Optional[dict]:
    """The first of the profile's questions this person hasn't answered near here."""
    answered = {o["question_id"] for o in reports.observations_near(db, lon, lat, radius_m=200)
                if o["device_id"] == device_id}
    i = 0 if lang == "en" else 1
    for q in load_profile(profile).questions:
        if q.id not in answered:
            return {"id": q.id, "text": q.en if lang == "en" else q.sw,
                    "options": [{"id": k, "label": v[i]} for k, v in q.options.items()]}
    return None


# ------------------------------------------------------ competitors (Google)
def google_competitors(business: Optional[str], lon: float, lat: float, radius_m: float) -> Optional[dict]:
    """Businesses of this kind within radius_m from Google Maps (Places API (New) Text Search, up to
    60 results). Google lists far more small businesses in Nairobi than OpenStreetMap. Fetched live
    for every question and never cached: Google's terms only allow storing place IDs. Google's terms
    also say Places results shown on a map must be on a Google map, so the UI lists them (with
    "Google Maps" credited) instead of drawing them on our satellite picture."""
    if not settings.google_maps_api_key or not business:
        return None
    dlat, dlon = radius_m / 110_574, radius_m / (111_320 * math.cos(math.radians(lat)))
    body = {"textQuery": business, "pageSize": 20, "locationRestriction": {"rectangle": {
        "low": {"latitude": lat - dlat, "longitude": lon - dlon},
        "high": {"latitude": lat + dlat, "longitude": lon + dlon}}}}
    headers = {"X-Goog-Api-Key": settings.google_maps_api_key,
               "X-Goog-FieldMask": "places.id,places.displayName,places.location,places.rating,"
                                   "places.userRatingCount,places.businessStatus,nextPageToken"}
    found: list[dict] = []
    with httpx.Client(timeout=20) as c:
        for _ in range(3):  # 20 per page, 60 at most
            r = c.post("https://places.googleapis.com/v1/places:searchText", json=body, headers=headers)
            r.raise_for_status()
            page = r.json()
            found += page.get("places", [])
            if not page.get("nextPageToken"):
                break
            body = {**body, "pageToken": page["nextPageToken"]}
    here = geo.to_utm(Point(lon, lat))
    rows = []
    for pl in found:
        loc = pl.get("location") or {}
        if pl.get("businessStatus") == "CLOSED_PERMANENTLY" or "latitude" not in loc:
            continue
        d = geo.to_utm(Point(loc["longitude"], loc["latitude"])).distance(here)
        if d <= radius_m:
            rows.append({"place_id": pl.get("id"), "name": (pl.get("displayName") or {}).get("text"),
                         "distance_m": round(d), "rating": pl.get("rating"), "reviews": pl.get("userRatingCount", 0)})
    rows.sort(key=lambda x: x["distance_m"])
    rated = [x["rating"] for x in rows if x["rating"]]
    return {"source": "Google Maps", "business": business, "radius_m": radius_m, "count": len(rows),
            "may_be_more": len(found) >= 60, "avg_rating": round(sum(rated) / len(rated), 1) if rated else None,
            "total_reviews": sum(x["reviews"] for x in rows), "nearest": rows[:10]}


# ------------------------------------------------------------------------ ask
def _route(message: str, history: list[dict]) -> dict:
    """Muse Spark picks the use case, the place and (for businesses) what counts as a competitor."""
    menu = "\n".join(f"- {p.id}: {p.name}. {p.tagline}" for p in list_profiles())
    convo = "\n".join(f"{m.get('role')}: {m.get('text')}" for m in history[-4:])
    out = meta.spark_json(
        "TerraSat analyses places in Nairobi for people planning to build, buy, rent or open a business. "
        f"Analyses:\n{menu}\n\nRecent conversation:\n{convo or '(none)'}\nNew message: \"{message}\"\n\n"
        'Return JSON: {"use_case": the best analysis id, or "general" if none fits; "place": the place they name '
        '(estate, road, landmark), or null if they name none ("here" is not a name); "business": the kind of business '
        'if any, else null; "competitor_tags": OpenStreetMap tags for that kind of business, e.g. ["amenity=pharmacy"] '
        'or ["shop=hardware", "shop=doityourself"], else []}')
    ids = {p.id for p in list_profiles()}
    return {"use_case": out.get("use_case") if out.get("use_case") in ids else "general",
            "place": out.get("place") or None, "business": out.get("business") or None,
            "competitor_tags": [t for t in out.get("competitor_tags") or [] if isinstance(t, str) and "=" in t]}


def highlights(use_case: str, summary: dict, check: Optional[dict], google: Optional[dict] = None) -> list[dict]:
    """The few numbers worth a card in the UI, per use case."""
    s, out = summary or {}, []
    add = lambda label, value: value is not None and out.append({"label": label, "value": value})
    if use_case == "flood" and check:
        add("Flood risk", (check["flood_risk"] or "no data").title())
        add("Nearest watercourse", f"{check['distance_to_watercourse_m']:.0f} m" if check["distance_to_watercourse_m"] is not None else None)
        add("Height above it", f"{check['height_above_watercourse_m']:.0f} m" if check["height_above_watercourse_m"] is not None else None)
        add("In riparian reserve", {True: "Yes", False: "No"}.get(check["in_riparian_reserve"]))
        add("2024 flood", {True: "Flooded", False: "Not flooded"}.get(check["in_2024_flood"], "Not visible"))
        add("Past floods nearby", len(check["past_floods_nearby"]))
    elif use_case == "solar_minigrid":
        r = s.get("rooftop", {})
        pin = r.get("building_at_pin") or {}
        add("Sunshine", f"{r['sunshine_kwh_m2_day']} kWh/m²/day" if r.get("sunshine_kwh_m2_day") else None)
        add("Roof at pin", f"{pin['roof_m2']} m² → {pin['kwp']} kWp" if pin else None)
        add("Output", f"{pin['kwh_per_year']:,} kWh/yr" if pin.get("kwh_per_year") else None)
        add("Payback", f"{pin['payback_years']} yrs" if pin.get("payback_years") else None)
        add("Neighbours with panels", f"{r.get('area_adoption_pct')}%" if r else None)
        add("Power line", f"{s['distance_center_to_power_line_m']:.0f} m" if s.get("distance_center_to_power_line_m") is not None else None)
    elif use_case == "densification":
        add("Ground coverage", f"{s.get('ground_coverage_pct')}%")
        add("Buildings per ha", s.get("buildings_per_ha"))
        add("New since baseline", s.get("new_since_baseline"))
        add("Floor area ratio (est.)", s.get("floor_area_ratio_est"))
        add("Major road", f"{s['distance_to_major_road_m']} m" if s.get("distance_to_major_road_m") is not None else None)
        add("Verdict", (s.get("verdict") or "").split(" - ")[0].replace("_", " ").title())
    elif use_case == "business_site":
        g = google or {}
        verdict = g.get("verdict") or s.get("verdict") or ""
        add("Verdict", verdict.split(" - ")[0].replace("_", " ").title())
        if google:
            add("Competitors within 500 m (Google Maps)", f"{g['count']}{'+' if g['may_be_more'] else ''}")
            add("Their average rating", f"{g['avg_rating']} ★ ({g['total_reviews']:,} reviews)" if g.get("avg_rating") else None)
        else:
            add("Competitors within 500 m (OpenStreetMap)", s.get("competitors"))
        add("People nearby (est.)", f"{s.get('people_in_catchment_est', 0):,}")
        per = g.get("people_per_competitor_est") or s.get("people_per_competitor_est")
        add("People per competitor", f"{per:,}" if per else None)
        add("Anchors", ", ".join(f"{n} {k}" for k, n in (s.get("anchors") or {}).items() if n) or None)
        add("Major road", f"{s['distance_to_major_road_m']} m" if s.get("distance_to_major_road_m") is not None else None)
    return out


def ask(db, message: str, lang: str = "en", lat: Optional[float] = None, lon: Optional[float] = None,
        device_id: str = "", history: Optional[list[dict]] = None, on_site: bool = False) -> dict:
    """One question about a place. lat/lon is the map pin or the phone's location; a place named in
    the message wins. People on site (phone GPS) also get a quick tap-to-answer question."""
    history = history or []
    route = _route(message, history)
    use_case = route["use_case"]
    where = None
    if route["place"]:
        hit = _geocode_cached(str(route["place"]))
        if hit:
            where = {"name": route["place"], "matched": hit[2], "lon": hit[0], "lat": hit[1], "source": "named"}
    not_found = bool(route["place"]) and where is None
    if where is None and lat is not None and lon is not None:
        where = {"name": "the selected spot" if not on_site else "where the person is standing",
                 "lon": lon, "lat": lat, "source": "gps" if on_site else "pin"}
    audit = check = google = None
    notes: list[str] = []
    if where and use_case != "general":
        profile = load_profile(use_case)
        params = {"business": route["business"], "competitor_tags": route["competitor_tags"]} \
            if use_case == "business_site" else {}
        try:
            audit = cached_audit(use_case, where["lon"], where["lat"], params, side_m=profile.audit.ask_side_m)
        except Exception as e:  # noqa: BLE001 - imagery or SAM down: answer from the map layers alone
            notes.append(f"Satellite analysis unavailable right now ({e.__class__.__name__}).")
        check = check_place(db, where["lon"], where["lat"]) if use_case == "flood" else None
        truth = ground_truth(db, where["lon"], where["lat"], use_case)
        if use_case == "business_site":
            try:
                google = google_competitors(route["business"], where["lon"], where["lat"],
                                            profile.params.get("catchment_m", 500))
            except httpx.HTTPError as e:
                google = None
                notes.append(f"Google Maps competitor search failed ({e.__class__.__name__}); using OpenStreetMap only.")
            if google and audit:
                people = audit["summary"].get("people_in_catchment_est", 0)
                google["people_per_competitor_est"] = round(people / (google["count"] + 1))
                google["verdict"] = business_verdict(google["people_per_competitor_est"], profile.params)
    else:
        truth = None
    data = {"use_case": use_case, "place": where, "analysis": (audit or {}).get("summary"), "flood_check": check,
            "competitors_google_maps": google, "ground_truth": truth, "notes": notes}
    framing = load_profile(use_case).memo.framing if use_case != "general" else ""
    menu = ", ".join(p.name for p in list_profiles())
    convo = "\n".join(f"{m.get('role')}: {m.get('text')}" for m in history[-6:])
    prompt = (
        "You are TerraSat, an urban planning assistant for Nairobi. People ask about places where they want to build, "
        "buy, rent or open a business.\n"
        f"Reply in {LANGUAGES.get(lang, 'English')}, under 150 words: start with a one-line verdict, then the key "
        "numbers, then what to check on the ground.\n"
        f"{framing}\n"
        "Use only facts from DATA, the conversation, or web pages you open and cite (use the web for laws, prices, "
        "tariffs and recent news). Say plainly when something is an estimate or an assumption.\n"
        + ("For competitors, prefer competitors_google_maps (Google lists far more small businesses than "
           "OpenStreetMap) and credit it as Google Maps.\n" if google else "")
        + (f"TerraSat could not find '{route['place']}' on the map: say so and ask for a nearby landmark.\n" if not_found else "")
        + ("If there is no place in DATA, ask them to name one or drop a pin.\n" if not where else "")
        + (f"No analysis fits this question; answer briefly if you can, and say TerraSat can analyse: {menu}.\n"
           if use_case == "general" else "")
        + "Never call a place safe or guarantee an outcome. Describe places, never judge the people who live there.\n\n"
        f"CONVERSATION:\n{convo or '(none)'}\nUSER: {message}\n\nDATA:\n{json.dumps(data, default=str)}")
    ans = meta.spark(prompt, web_search=True)
    ask_next = (next_question(db, device_id, where["lon"], where["lat"], lang, use_case)
                if where and on_site and use_case != "general" else None)
    return {"reply": ans["text"], "use_case": use_case,
            "use_case_name": load_profile(use_case).name if use_case != "general" else None,
            "place": where, "business": route["business"], "audit": audit, "check": check, "ground_truth": truth,
            "highlights": highlights(use_case, (audit or {}).get("summary"), check, google),
            "competitors": google,
            "ask": ask_next, "sources": ans["citations"]}
