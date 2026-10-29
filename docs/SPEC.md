# TerraSat: Geospatial Auditing Engine for Kenyan Planning

*Spec v3 (Oct 27, 2026). TerraSat is a general-purpose engine. Urban flood exposure is the case study we demo.*

- **Hackathon:** Meta Global AI Developer Hackathon, Indie Developer Track, "Build for Your World"
- **Deadline:** Nov 4, 11:59 PM PT = **Thu Nov 5, 10:59 AM Nairobi time** (US clocks move to PST on Nov 1)
- **Tagline:** *TerraSat: ask planning questions of satellite imagery. Case study: Nairobi flood exposure before El Niño.*

---

## 1. What TerraSat is

TerraSat lets planners ask a question about a place and get an answer from current satellite imagery, in seconds rather than weeks of field audits.

```
pin or voice command
  → satellite imagery (Mapbox, ~0.6 m/px)
  → SAM 3.1 finds what the question needs (roofs, panels, garbage, water…)
  → map layers + spatial rules (buffers, rings, distances)
  → metrics and a verdict
  → Muse Spark memo grounded in live web search
  → GeoJSON / CSV exports
```

**The engine is not tied to one use case.** What changes between use cases is configuration: what to look for, which map layers to load, which spatial rules apply, and what the memo should say. In TerraSat that configuration is an **audit profile**. Flood exposure, solar and mini-grid siting, heat-island mapping and property-rates gaps all run on the same pipeline with different profiles.

**For the hackathon we go deep on one case study**, urban flood exposure and drainage in Nairobi, because it is urgent this season and makes a clear demo. We also show a second profile (solar and mini-grid planning) briefly, to prove the engine generalises.

## 2. Audit profiles

A profile is one YAML file in `backend/app/profiles/`. Adding a use case means adding a profile (plus an analyzer, if the metrics are new), with no changes to the pipeline.

| Field | Meaning | Flood example | Solar example |
|---|---|---|---|
| `classes` | What SAM looks for. One short noun phrase per prompt. | rooftop, garbage pile, drainage ditch, river | rooftop, solar panel, water tank |
| `layers` | Map layers to load (OSM extracts) | `osm_waterways` | `osm_power_lines` |
| `analyzer` | Which metrics function runs | `flood_exposure` | `solar_minigrid` |
| `params` | Rule settings | 30 m riparian buffer | 600 m / 1 km rings, CapEx, grid distance |
| `memo` | Audience, framing, sections, languages | Protection framing, EN + SW | Unit economics, EN |
| `audit` | Area and zoom | 2.1 km, z18 | 2.1 km, z18 |

## 2a. What TerraSat can do

The core toolchain is voice commands, SAM 3.1 segmentation on Mapbox imagery, spatial rules, and a Muse Spark memo grounded in web search. **Every idea below reuses the same pipeline: drop a pin, segment, apply a spatial rule, write a grounded memo, export.** Only the prompts and the rule change, and each idea becomes one audit profile.

**Status key:** 🟢 demo case study (built in depth) · 🟡 built as a profile, shown briefly · ⚪ roadmap (same engine, profile to write)

### Climate and disaster

| Idea | What SAM finds | What the analysis adds | Who uses it | Status |
|---|---|---|---|---|
| **Flood exposure** | Buildings near rivers | Structures inside riparian buffers, new since 2023 | Counties, Red Cross | 🟢 |
| **Drainage choke points** | Garbage piles, blocked channels near river crossings | Ranks drains to clear before the El Niño peak | Nairobi County, resident associations | 🟢 |
| Urban heat islands | Tree canopy, dark metal roofs, bare ground | A heat-risk score per block, plus the best tree-planting spots (ties into the national tree-planting campaign) | County environment departments, schools | ⚪ |
| Landslide-prone settlements | Buildings | Combined with free elevation data (SRTM / Copernicus) to flag homes on steep slopes, such as Mai Mahiu and Murang'a | National disaster agencies | ⚪ |
| Rainwater harvesting potential | Roof area per building | Roof area × rainfall gives litres per building per season, which helps during water rationing | Water utilities, NGOs | ⚪ |

### Energy and connectivity

| Idea | What SAM finds | What the analysis adds | Who uses it | Status |
|---|---|---|---|---|
| **Solar & mini-grid planning** | Rooftops, solar panels, water tanks | Homes inside the 600 m transformer ring and 1 km WISP ring, solar penetration, distance to the grid, cost per unserved household, and a grid / mini-grid / standalone-solar verdict | Utility planners, mini-grid developers, WISPs, county energy offices | 🟡 |
| Rural infrastructure deserts | Roofs, solar, tanks, unpaved roads | The same solar profile applied to off-grid rural clusters (for example Turkana) | REREC, KOSAP, NGOs | ⚪ |

### Housing, land and revenue

| Idea | What SAM finds | What the analysis adds | Who uses it | Status |
|---|---|---|---|---|
| Property-rates gap | Every building | Buildings missing from the county rates register mean revenue the county isn't collecting | County treasuries (a strong pitch to governments) | ⚪ |
| Fire access in informal settlements | Dense metal-roof clusters, path widths | Finds clusters a fire truck can't reach, relevant after the Gikomba and Kibera fires | Fire services, settlement upgrading programmes | ⚪ |
| Affordable housing site finder | Vacant or bare land near paved roads | Ranks underused plots by access to roads and services | Affordable Housing Programme, developers | ⚪ |
| Densification | Building footprints, tall blocks | How much of each block is built over, measured against zoning limits | Planners in Kilimani and Kileleshwa | ⚪ |

### Mobility and public space

| Idea | What SAM finds | What the analysis adds | Who uses it | Status |
|---|---|---|---|---|
| Desire-line walkways | Dirt footpaths worn into grass and verges | Shows where people walk with no sidewalk, so you know where to build one | Urban roads agencies, walkability advocates | ⚪ |
| Green-space equity | Parks, open fields, trees | Green space per resident, by ward | Planners, journalists | ⚪ |
| Quarry and wetland loss | Quarry scars, wetland vegetation | Flags illegal quarrying in Kajiado and Machakos and wetland infill in Nairobi | NEMA (the national environment regulator) | ⚪ |

### Cross-cutting features (work with every profile)

- **Citizen voice reports:** a resident records a report in the app, for example "the drain near Kangemi market is blocked". TerraSat geolocates it, SAM checks the imagery, and the report joins the map. For flood that means blocked drains; for solar it could mean outage reports.
- **Agentic auditing (stretch):** Muse Spark turns a plain-language question into a chain of prompts and rules, for example "Which schools within 200 m of a river have no tree cover?"
- **Bilingual memos:** reports in English and Swahili for ward-level meetings.

**The demo case study combines three of these:** flood exposure, drainage choke points and citizen voice reports. It is timely with this year's El Niño, very visual on video, and uses all three Meta models in a natural way.

## 3. Demo case study: Urban Flood Exposure & Drainage Watch

### Why now

Kenya Met puts an 81% chance on this year's El Niño being *very strong*, with above-normal short rains from October possibly lasting into February 2027. In the 2024 long rains, Nairobi was the worst-hit county: about 294 people died nationally and informal settlements along the rivers (Mathare, Kibera, Mukuru) took the most damage.

### Questions it answers (before the peak rains)

1. **Who is exposed?** Which buildings, new ones included, sit inside river buffers and on low-lying ground.
2. **Where will water back up?** Which culverts, drains and river crossings are likely choke points.
3. **What are residents seeing right now?** In-app voice reports of blocked drains and rising water, checked against satellite imagery.

**Framing:** the tool is for protection, not enforcement. Its outputs are evacuation priority, drains to clear and where to stage relief, never a list of homes to demolish.

### F1: Flood exposure audit

- **Input:** a pin, a ward name, or a voice command.
- **Imagery:** a 2.1 km square around the pin at zoom 18 (~0.6 m/px), stitched from 9–16 Mapbox Static Images API requests (1280 px each) and cut into 16 overlapping 1024 px windows (10% overlap).
  - The Raster Tiles API returned 429 with a limit of -1 on Rebecca's account (disabled), while Static Images works.
  - Esri World Imagery is a no-key fallback for development (`TILE_PROVIDER=esri`).
- **Segmentation:** SAM runs on each window, once per prompt.
- **To map coordinates:** masks become latitude/longitude polygons, then UTM 37S (EPSG:32737) for distances and areas.
- **De-duplication:**
  - Fragments cut off at an inner window edge are dropped, because the overlap means the whole object appears in a neighbouring window.
  - Remaining duplicates are merged with polygon NMS: IoU above 0.5, or a polygon mostly contained in another.
- **Exposure rules:**
  - Inside the **riparian buffer** around OSM rivers, streams and canals. Culverted sections are excluded. The width is configurable (default 30 m; reported legal range 6–30 m; cite the source in the write-up).
  - **Terrain** from the Copernicus GLO-30 elevation model (`fetch_data.py terrain`):
    - **height above the nearest river** at each building;
    - **dips**, where water would pond (depression filling);
    - **overland flow paths** (D8 flow accumulation).

    GLO-30 is a surface model, so values are approximate in dense areas.
- **Flood risk class per building** (rules in `flood.yaml`; the 2024 flood extent is not an input):
  - **High:** within 30 m of a river, or within 60 m and less than 1 m above it.
  - **Medium:** within 60 m, or within 100 m and less than 3 m above it.
  - **Low:** everything else.
  - **Surface-water flag** (separate from the class): the building sits in a dip or on a flow path, where rain ponds away from rivers.
  - **Why these rules:**
    - At Mukuru, distance to the river was the strongest predictor of 2024 damage. Damage rates were 35% within 15 m, 22% at 15–30 m, 9% at 30–60 m, 2% at 60–100 m, and 0% beyond 100 m.
    - Height above the river added to it near the river.
    - Treating dips and flow paths as risk points diluted the river signal, so they became a separate flag.
  - **Unmapped watercourses:** where OSM maps no river within 500 m, distance and height are measured to **drainage lines derived from the DEM** (≥ 200 ha draining through). Each building records `watercourse: osm | dem_channel`.
  - **Results against UNOSAT's 2024 damage** (share of all damaged structures; final rules, Oct 29):

    | Site | Role | High: buildings → damage | High + medium | Low |
    |---|---|---|---|---|
    | Mukuru | calibration | **9% → 79%** | 19% → 96% | 81% → 3.5% |
    | Korogocho | holdout | **6% → 65%** | 18% → 69% | 82% → 0% |
    | East Nairobi | holdout, no mapped river | **6% → 26%** | 14% → 57% | 86% → 38% |

  - **Notes on the results:**
    - **Korogocho:** 105 of the 341 damaged structures have no building in today's footprint map, which is consistent with homes demolished along the river after the floods. Of those still on the map, 93% are rated high and none low.
    - **East Nairobi:** without DEM drainage lines, every building there was rated low, so the river rules catch nothing at all there.
    - **What this means:** the river rules work well near mapped rivers. Away from them, the DEM fallback helps but surface-water flooding remains the weak spot (30 m elevation that includes roofs).
- **Building inventory = SAM + baseline** (decided after the live tests on Oct 28):
  - SAM 3.1 (prompt `building`) finds formal buildings well, but misses most roofs in dense informal settlements, even at zoom 19.
  - Building footprints from **Overture Maps** (which include Google Open Buildings) fill those gaps.
  - Every building carries `source: sam | baseline`.
  - A SAM building with no matching footprint is flagged **new since the baseline**.
- **Metrics:** exposed structures, new exposed structures, exposed footprint, exposure per 100 m of riverbank, and an optional estimate of people exposed.
- **Checked against the 2024 floods** (UNOSAT FL20240426KEN, Pléiades image of 1 May 2024, not field validated; `unosat_2024` layer):
  - Each building is flagged `in_2024_flood`.
  - The summary reports how much of the area UNOSAT could see (clouds), the flooded hectares, and how many of UNOSAT's affected structures fall in TerraSat's exposure zone.
  - **Mukuru (Ngong River), first result, Oct 28:**
    - UNOSAT recorded 568 affected structures in the audit square; 66% of the square was visible through cloud.
    - The **30 m riparian zone flags 4.4% of buildings (1,101 of 24,870) yet contains 72% of the affected structures.**
    - At 60 m it contains 94% of them; at 100 m, 99.8%.
  - **Mathare:** 68% of the square was under cloud, so it can't be validated.
  - **Kibera:** outside UNOSAT's analysis area.

### F2: Drainage choke points *(to do)*

- **Candidates:** road–waterway crossings, culverted sections, and SAM garbage or ditch detections near waterways.
- **Ranking inputs:** built-up area upstream, garbage within 50 m, and citizen reports within 100 m.
- **Output:** a ranked list of drains and culverts to clear.

### F3: Citizen reports and crew tasks (mobile app) *(to do)*

- **The app:** the **TerraSat mobile app** (Expo / React Native, Android first), which has two modes (details in §6a).
- **Residents:** one record button; GPS and an optional photo attach automatically. Reports are **queued offline** and sent when the connection returns.
- **Field crews:** see drains assigned to them, navigate there, and mark them cleared with an after photo.
- **Audio:** the phone records in its native format (AAC/M4A on Android). The backend converts it to **WAV**, the only format the transcription API accepts, with ffmpeg via `imageio-ffmpeg`.
- **Pipeline:**
  1. `muse-voice-transcribe-1.0` transcribes the recording.
  2. Muse Spark extracts the issue type, landmark and urgency.
  3. The landmark is geocoded.
  4. SAM checks the imagery at that spot.
  5. The report appears on the map with a "verified by imagery" badge and feeds into the F2 ranking.
- **Roadmap:** SMS, USSD and phone-call reporting, which work without mobile data.
- **Other profiles:** the reporting flow is generic. In the solar profile the same flow would take outage reports.

### F4: Grounded memo *(to do)*

Muse Spark receives the analyzer summary, recent reports, and web results (KMD forecasts, county notices, news). It writes the sections listed in the profile's `memo`. For flood that means a risk summary, top drains to clear, evacuation priority zones and relief staging points, in English and Swahili.

### F5: Exports

- **GeoJSON** of all layers, for QGIS. Already produced by `run_audit.py`.
- **CSV** priority list.
- **Memo** as Markdown or PDF.

## 4. Second profile: Solar & Mini-grid Planning (beta)

- **SAM classes:** rooftop, solar panel, water tank.
- **Layer:** OSM power lines.
- **Rings:** 600 m (KPLC/REREC transformer and mini-grid zone) and 1 km (WISP / community Wi-Fi sector).
- **Metrics per ring:**
  - buildings;
  - buildings with solar (a panel overlapping the roof);
  - solar penetration;
  - estimated unserved households;
  - CapEx per unserved household (defaults: $25,000 for a 15 kW mini-grid, $3,500 for a WISP mast).
- **Grid proximity:** distance from the pin to the nearest power line.
- **Verdict:**
  - dense and near the grid → grid extension candidate;
  - dense and far from the grid → mini-grid candidate;
  - sparse → standalone solar.

This fixes the original spec's flaw that "no solar panel" doesn't mean "unserved".

## 5. Meta models (shared by every profile)

| Model | Role |
|---|---|
| `sam-3.1` | Finds whatever the profile asks for in the imagery. Also checks the imagery at citizen reports. |
| `muse-spark-1.3` | Parses reports, ranks priorities, and writes the profile's memo grounded in live web search. |
| `muse-voice-transcribe-1.0` | In-app voice reports, and voice commands such as "audit this area for flood exposure" or "now check it for solar". |

**API facts (dev.meta.ai docs, checked Oct 27)**

- **Base URL and auth:** `https://api.meta.ai/v1`, Bearer key, OpenAI-SDK compatible.
- **SAM 3.1** (`POST /v1/responses`, streamed):
  - **One short noun phrase per request.**
  - **Image:** passed as a URL or base64 data URL.
  - **Output:** special-token text with box-local masks, parsed with the official `meta-sam-parser`.
  - **Price:** **$2.50 per 1,000 images**. An audit is 16 windows × 3–4 prompts = 48–64 calls ≈ $0.12–0.16, then cached.
- **Muse Spark 1.3:**
  - Search grounding through the Responses API, `tools=[{"type":"web_search"}]`, which returns `url_citation` annotations.
  - Prices: $1.25 per 1M input tokens, $4.25 per 1M output tokens, plus $2.50 per 1,000 searches.
  - Contributor mode is ~10× cheaper but lets Meta train on your data. Use it for development only, never for citizen reports.
- **Voice** (`POST /v1/asr/transcribe`):
  - Multipart request, **WAV only**, up to 10 min / 32 MB.
  - $0.18 per hour of audio.
  - Swahili support isn't documented, so we test it.
- **Rate limits:** SAM and Spark 3,000 RPM each.

**Credits**

- **Meta ($150):** everything core.
- **Baseten ($100):** fallback only (SAM weights or Whisper).
- **Modal:** optional pre-computing.

## 6a. Apps (decided Oct 27)

| App | Tech | Users | What it does |
|---|---|---|---|
| **TerraSat mobile** (`mobile/`) | Expo / React Native, Android first, demoed with Expo Go | **Residents** | Record a voice report (GPS + optional photo attached), offline queue, track status (received → verified by imagery → crew assigned → cleared), see nearby risk |
| | | **Field crews** | List of assigned drains / choke points, map and navigation, mark cleared with an after photo |
| **TerraSat dashboard** (`dashboard/`) | React (Vite) + react-leaflet, web | County / Red Cross monitoring and logistics teams | Audit map and layers, use-case switcher, live report feed, choke-point ranking, **assign crews and track tasks**, grounded memo, exports |

- **Both apps call the same FastAPI backend.**
- **Streamlit is dropped to save time.** The API's built-in `/docs` page covers backend testing.
- **The phone must reach the backend.** On the same Wi-Fi, use the laptop's LAN IP. For the demo, use a public URL: a tunnel (cloudflared / ngrok) or deploy the API (e.g. Modal, Render).

**Backend additions for the apps**

| Endpoint | Purpose |
|---|---|
| `POST /audit` | Run an audit (profile, lon, lat) and return the summary + GeoJSON |
| `POST /reports` | Multipart upload: audio, lat/lon, optional photo, device id. The pipeline runs: convert to WAV → transcribe → Muse Spark parses → geocode → SAM checks the imagery |
| `GET /reports` | Report feed for the dashboard (filter by status or area); a reporter's own reports for the mobile app |
| `POST /tasks`, `PATCH /tasks/{id}` | Assign a choke point or report to a crew; status updates and after photos from the crew app |
| `GET /tasks?crew=` | A crew's assigned tasks for the mobile app |

**Storage:** SQLite for reports and tasks, and the filesystem for audio and photos.

## 6. Architecture

```
TerraSat mobile (Expo) ──┐  residents: voice reports · crews: tasks
TerraSat dashboard (web) ┼─► FastAPI (backend/app/main.py)
                         │      /profiles  /audit  /reports  /tasks
                         ▼
                    services/audit.py  run_audit(profile, lon, lat)
                       │
   ┌───────────────────┼─────────────────────┬──────────────────────┐
   ▼                   ▼                     ▼                      ▼
tiles.py           sam_service.py        layers.py             analyzers.py
Mapbox grid,       SAM 3.1 per window,   OSM context layers    registry: flood_exposure,
stitch, cache      parse, dedup, cache   (waterways, power,    solar_minigrid, … 
                                         roads, footprints)     (flood exposure helpers)
   └──────────── geo.py: tile math, pixel↔GPS, UTM, buffers, NMS ─────────┘

profiles/*.yaml   ← one file per use case (what to find, layers, rules, memo)
next: reasoning.py (Muse Spark memo) · reports.py (voice pipeline) · tasks.py (crew logistics) · chokepoints.py · export.py · db.py (SQLite)
```

**Rules**

- All logic lives in the services, and use cases live in profiles.
- The mobile app and dashboard are thin clients of the API.

## 7. Data sources

| Layer | Source | Licence |
|---|---|---|
| Satellite imagery | Mapbox Satellite via the Static Images API (`satellite-v9`) | Mapbox ToS; show © Mapbox © Maxar attribution in the UI (the logo is turned off in the images) |
| Waterways, power lines, roads | OpenStreetMap via Overpass (`scripts/fetch_data.py`) | ODbL |
| Building footprint baseline | Overture Maps buildings (includes Google Open Buildings, Microsoft, OSM), downloaded per site with the `overturemaps` CLI | ODbL / CDLA (per source); attribute in the README |
| Elevation | Copernicus GLO-30 DEM | Free, attribution |
| 2024 flood extent + affected structures | UNOSAT FL20240426KEN via HDX (downloaded by hand into `data/raw/flood_2024/`, cut per site by `fetch_data.py flood_2024`). The download also has Mai Mahiu landslide and Garissa / Tana River layers for later profiles | CC BY-SA; credit UNOSAT |
| Ward boundaries | IEBC / HDX | Check |
| Grounding | KMD, Nairobi County, news via Muse Spark web search, plus a local cache for the live demo | n/a |

## 8. Demo plan (2-minute video)

| Time | Scene |
|---|---|
| 0:00–0:15 | Hook: the El Niño warning, the 2024 Nairobi floods. "TerraSat asks planning questions of satellite imagery." |
| 0:15–1:40 | **Flood case study in Mathare:** on the **dashboard**, SAM masks light up, the riparian buffer appears, new structures are flagged. On the **phone**, a resident records "the drain by the bridge is blocked"; the report appears on the dashboard, verified by imagery. Choke points are ranked and the officer **assigns a crew**. On the **crew's phone**, they navigate there and mark it cleared with a photo. The bilingual memo with citations, then GeoJSON export. |
| 1:40–1:55 | **Same engine, different question:** switch the profile to Solar & Mini-grid on Syokimau. Rings, solar penetration, grid distance and cost per household appear. No code change. |
| 1:55–2:00 | Roadmap: heat islands, property rates, fire access, rural flood plains… "One engine, any planning question." |

**Presets**

- **Flood:** Mathare (Mathare River), Mukuru (Ngong/Motoine), Kibera (Ngong).
- **Solar:** Syokimau.

Swap any site with poor imagery.

## 9. Roadmap

| Date | Work |
|---|---|
| Tue Oct 27 | ✅ Scaffold. ✅ geo, tiles, SAM 3.1 backend (real API format via `meta-sam-parser`), dedup, flood exposure. ✅ **Audit profiles** (flood + solar_minigrid), layer and analyzer registries, `audit.py`, `/profiles` endpoint, OSM layer fetcher, smoke-test script. 29 tests passing. |
| Tue Oct 27 (later) | ✅ Imagery switched to the Mapbox Static Images API (Raster Tiles is disabled on the account). ✅ Decision: Expo mobile app (residents + crews) plus a web dashboard. |
| Wed Oct 28 | ✅ Milestone 1: live checks, first live Mathare audit, prompt tests (SAM misses informal roofs → Overture footprints fill the gaps; 1,665 structures in the Mathare riparian zone). ✅ Scripts consolidated to `fetch_data.py`, `run_audit.py`, `check.py`. |
| Thu Oct 29 | ✅ Terrain (height above river, dips, flow paths, DEM drainage lines), risk rules validated on 2024 damage at three sites. ✅ **API:** `/audit` (cached), `/reports` (voice → WAV → Muse Voice → Muse Spark parse with Nairobi place names → corroboration against river distance, height and 2024 floods), `/crews`, `/tasks` (the full loop from resident to crew to cleared), SQLite. |
| Fri Oct 30 | Muse Spark memo (EN/SW, citations), flood history layer (news incidents via web search + the Interior Ministry's list of at-risk areas), choke points, exports. |
| Sat Oct 31 | **Mobile app, resident mode:** record, GPS, photo, offline queue, my reports and status. |
| Sun Nov 1 | **Mobile app, crew mode:** assigned tasks, map and navigation, mark cleared with a photo. Nearby-risk view. |
| Mon Nov 2 | **Web dashboard:** map and layers, use-case switcher, report feed, task board, memo panel. |
| Tue Nov 3 | Solar profile live run on Syokimau. Public backend URL (tunnel or deploy). Cache all presets, rehearse. |
| Wed Nov 4 | Record the video, final README, submit (Thu 10:59 AM Nairobi time). |

## 10. Open questions

- Swahili/Sheng support in `muse-voice-transcribe-1.0`, and whether web search works with image input. Test with `python scripts/check.py voice --audio …`.
- Hackathon rules: video length, public repo or live URL, licence, whether non-Meta inference is allowed.
- The legal riparian buffer width and its citation.
- Network: the Claude sandbox can't reach Mapbox, Overpass or the Meta API. Run scripts locally, or allow those domains in Claude settings under Capabilities.
