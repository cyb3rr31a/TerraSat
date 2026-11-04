# TerraSat

[![tests](https://github.com/cyb3rr31a/TerraSat/actions/workflows/tests.yml/badge.svg)](https://github.com/cyb3rr31a/TerraSat/actions/workflows/tests.yml)

**An urban planning assistant: know a place before you buy, build, rent or plan.**

TerraSat helps **home buyers, developers, agents, lenders, county planners and residents** answer "what is this place really like?" Ask in the app ("Is Kileleshwa prone to flooding?" or "check where I am") and TerraSat answers from satellite imagery, map layers and what people on the ground report, in English or Swahili. Emergencies are one use; everyday decisions about land are the bigger one.

**Ask anything about a place and get the analysis that fits the question:**

| Ask… | TerraSat looks at | You get |
|---|---|---|
| "Is this a good spot for a pharmacy?" | Competitors from **Google Maps** (names, ratings, reviews; optional key) and OpenStreetMap, anchors (schools, clinics, markets, bus stops), homes within walking distance from rooftops, road access | A verdict (strong / moderate / crowded), people per competitor, the map |
| "Can I put solar on this roof?" | The roof under the pin (SAM), NASA POWER sunshine, panels already on neighbours' roofs, distance to the grid | kWp, kWh per year, payback (with assumptions marked) |
| "How built-up is Kilimani? Room to build?" | Every roof (SAM + Overture footprints), what is new since the footprint data, floors where known, roads | Ground coverage, buildings per hectare, new construction, verdict |
| "Does South C flood?" | River distance and height, the 2024 flood, news of past floods, the riparian reserve, what neighbours say | Risk class, flood history, legal reserve |

Each answer comes with the **satellite picture of the area with the findings drawn on it**.

<img width="960" height="450" alt="Screenshot 2026-11-03 095508" src="https://github.com/user-attachments/assets/c332ae81-9800-42dc-99d2-6eeaf6b59458" />

Under the hood TerraSat is a geospatial auditing engine. Drop a pin or say what you need. TerraSat pulls current satellite imagery, uses **SAM 3.1** to find what the question requires (roofs, solar panels, garbage piles, water…), applies spatial rules (buffers, rings, distances) against map layers, and returns metrics, a verdict and a **Muse Spark** memo grounded in live web search, plus GeoJSON and CSV exports for QGIS.

> **One engine, many use cases.** Flood exposure, solar and mini-grid siting, heat islands, property-rates gaps and more all run on the same pipeline. Each use case is an **audit profile**, a short YAML file that says what to look for, which layers to load, which rules apply and what the memo should cover.
>
> **Ground truth from people closes the gap.** Satellites and maps miss what happens on the street. Residents send voice reports (flooding, blocked drains, water that stays for days, power cuts, broken roads…) and answer quick tap-to-answer questions in the chat ("Did this street flood last season? Ankle, knee, waist?"). Each profile decides what can be reported and asked.
>
> **Hackathon case study: flood risk in Nairobi.** After the 2024 floods and the riparian demolitions that followed, knowing whether a plot floods or sits inside a river reserve matters to every buyer and planner, and Kenya Met gives an 81% chance that this season's El Niño will be very strong. A second profile, **Solar & Mini-grid Planning**, shows the same engine answering a completely different question.

Built for the Meta Global AI Developer Hackathon 2026 (Indie Developer Track, *Build for Your World*).

## How it works

```
pin / voice ─► satellite mosaic ─► SAM 3.1 (profile prompts) ─► map layers + spatial rules
            ─► metrics + verdict ─► Muse Spark memo (web-grounded) ─► GeoJSON / CSV
```

| Meta model | Role in TerraSat |
|---|---|
| `sam-3.1` | Finds whatever the active profile asks for in the imagery, and checks the imagery at citizen reports |
| `muse-spark-1.3` | Answers place questions in the chat, parses reports, and writes the profile's memo with live web-search citations |
| `muse-voice-transcribe-1.0` | In-app voice reports and voice commands |

## Apps

| App | For | What it does |
|---|---|---|
| **TerraSat mobile** (Expo / React Native, `mobile/`) | **People on the ground** | **Ask** about where you stand (same engine, with the picture), answer quick questions on the spot; **Report** by voice with GPS and photo, works offline |
| **TerraSat web** (React + Leaflet, `web/`) | **Developers, businesses, real-estate firms, planners** (the main app) | Ask about any place: chat, map and satellite picture side by side, highlights, memo and exports |

Both apps use the same FastAPI backend.

## What TerraSat can do

The core toolchain is voice commands, SAM 3.1 segmentation on Mapbox imagery, spatial rules, and a Muse Spark memo grounded in web search. **Every idea below reuses the same pipeline: drop a pin, segment, apply a spatial rule, write a grounded memo, export.** Only the prompts and the rule change.

🟢 demo case study · 🟡 built, shown briefly · ⚪ roadmap (same engine, new profile)

### Climate and disaster

| Idea | What SAM finds | What the analysis adds | Who uses it | |
|---|---|---|---|---|
| **Flood exposure** | Buildings near rivers | Structures inside riparian buffers, new since 2023 | Counties, Red Cross | 🟢 |
| **Drainage choke points** | Garbage piles, blocked channels near river crossings | Ranks drains to clear before the El Niño peak | Nairobi County, resident associations | 🟢 |
| Urban heat islands | Tree canopy, dark metal roofs, bare ground | A heat-risk score per block, plus the best tree-planting spots (ties into the national tree-planting campaign) | County environment departments, schools | ⚪ |
| Landslide-prone settlements | Buildings | Combined with free elevation data to flag homes on steep slopes, such as Mai Mahiu and Murang'a | National disaster agencies | ⚪ |
| Rainwater harvesting potential | Roof area per building | Roof area × rainfall gives litres per building per season, which helps during water rationing | Water utilities, NGOs | ⚪ |

### Energy and connectivity

| Idea | What SAM finds | What the analysis adds | Who uses it | |
|---|---|---|---|---|
| **Solar & mini-grid planning** | Rooftops, solar panels, water tanks | Homes inside the 600 m transformer ring and 1 km WISP ring, solar penetration, distance to the grid, cost per unserved household, and a recommendation | Utility planners, mini-grid developers, WISPs | 🟡 |
| Rural infrastructure deserts | Roofs, solar, tanks, unpaved roads | The solar profile applied to off-grid rural clusters | REREC, KOSAP, NGOs | ⚪ |

### Housing, land and revenue

| Idea | What SAM finds | What the analysis adds | Who uses it | |
|---|---|---|---|---|
| Property-rates gap | Every building | Buildings missing from the county rates register mean revenue the county isn't collecting | County treasuries | ⚪ |
| Fire access in informal settlements | Dense metal-roof clusters, path widths | Finds clusters a fire truck can't reach, relevant after the Gikomba and Kibera fires | Fire services, settlement upgrading programmes | ⚪ |
| Affordable housing site finder | Vacant or bare land near paved roads | Ranks underused plots by access to roads and services | Affordable Housing Programme, developers | ⚪ |
| Densification | Building footprints, tall blocks | How much of each block is built over, measured against zoning limits | Planners in Kilimani and Kileleshwa | ⚪ |

### Mobility and public space

| Idea | What SAM finds | What the analysis adds | Who uses it | |
|---|---|---|---|---|
| Desire-line walkways | Dirt footpaths worn into grass and verges | Shows where people walk with no sidewalk, so you know where to build one | Urban roads agencies, walkability advocates | ⚪ |
| Green-space equity | Parks, open fields, trees | Green space per resident, by ward | Planners, journalists | ⚪ |
| Quarry and wetland loss | Quarry scars, wetland vegetation | Flags illegal quarrying in Kajiado and Machakos and wetland infill in Nairobi | NEMA (national environment regulator) | ⚪ |

### Works with every idea

- **Citizen voice reports:** a resident records "the drain near Kangemi market is blocked". TerraSat geolocates it, SAM checks the imagery, and the report joins the map.
- **Bilingual memos:** English and Swahili for ward-level meetings.
- **Agentic auditing (stretch):** plain-language questions such as "Which schools within 200 m of a river have no tree cover?" become a chain of prompts and rules.

**Hackathon demo:** flood exposure, drainage choke points and citizen voice reports, combined into one case study in Nairobi.

## Audit profiles: how one engine covers all of this

Each idea above becomes an **audit profile**, a YAML file in `backend/app/profiles/`. Two exist today: `flood` (the demo case study) and `solar_minigrid`.

A profile looks like this (`backend/app/profiles/solar_minigrid.yaml`, shortened):

```yaml
id: solar_minigrid
classes:                      # what SAM looks for (one short phrase per prompt)
  building:    {prompts: [rooftop]}
  solar_panel: {prompts: [solar panel]}
layers: [osm_power_lines]     # map layers to load
analyzer: solar_minigrid      # metrics function
params:
  rings_m: {transformer_zone: 600, wisp_sector: 1000}
  capex_usd: {minigrid_15kw: 25000, wisp_mast: 3500}
```

**Adding a use case:**

1. Copy a profile YAML and change it.
2. If the metrics are new, register an analyzer in `backend/app/services/analyzers.py`.
3. If a new map layer is needed, add it to `scripts/fetch_data.py` and `backend/app/services/layers.py`.

## Setup (Windows, Anaconda Prompt)

```bat
cd C:\hackathons\terrasat
conda create -n terrasat python=3.11 -y
conda activate terrasat
pip install -r requirements.txt
copy .env.example .env
```

- **Meta key:** [dev.meta.ai](https://dev.meta.ai/) → API keys.
- **Mapbox token:** [account.mapbox.com/access-tokens](https://account.mapbox.com/access-tokens/).
- If pip has trouble with geopandas on Windows, run `conda install -c conda-forge geopandas` first.

## Run

Run these from the project folder (`C:\hackathons\terrasat`):

| Command | What it does |
|---|---|
| `python scripts/fetch_data.py` | Downloads rivers, roads, power lines (OpenStreetMap), building footprints (Overture Maps) and elevation (Copernicus GLO-30) to `data/raw/`, and cuts the UNOSAT 2024 flood mapping to each site (download `FL20240426KEN_SHP.zip` from HDX into `data/raw/flood_2024/` first); skips what you already have |
| `python scripts/fetch_data.py pois` | Shops, services, schools, clinics, markets and bus stops in Nairobi (OpenStreetMap), for the business-site analysis |
| `python scripts/fetch_data.py places` | Suburb and neighbourhood names, for place search in the web app |
| `python scripts/fetch_data.py flood_history` | Past Nairobi floods (2024, March 2026, Interior Ministry at-risk list) found by Muse Spark web search and mapped with Nominatim |
| `python scripts/run_audit.py --profile flood --preset mathare` | Runs a full audit; results in `data/outputs/<profile>_<place>/` |
| `python scripts/run_audit.py --profile solar_minigrid --preset syokimau` | Same engine, solar & mini-grid profile |
| `python scripts/run_audit.py --profile flood --offline` | Runs without internet (fake imagery + mock SAM) |
| `python scripts/check.py mapbox` | Checks the Mapbox token |
| `python scripts/check.py sam` / `spark` | One live call to SAM 3.1 / Muse Spark with web search |
| `python scripts/check.py voice --audio data/voice/english.m4a` | Transcribes a voice note (any format) |
| `python scripts/check.py prompts --classes building,garbage --zoom 19` | Compares SAM prompt wordings on real imagery |
| `uvicorn backend.app.main:app --reload` | Starts the API; docs at http://127.0.0.1:8000/docs |
| `python -m pytest -q` | Runs the tests |
| `cd web` then `npm install` and `npm run dev` | Starts the web app at http://localhost:5173 (the API must be running; set `VITE_API_URL` in `web/.env` if it isn't on 127.0.0.1:8000) |
| `cd mobile` then `npm install` and `npx expo start` | Starts the mobile app; scan the QR code with Expo Go (Android). In the app, open ⚙ and enter the API address, e.g. `http://192.168.1.20:8000` (run uvicorn with `--host 0.0.0.0`) |

**Public demo:** the API runs on [Modal](https://modal.com) (`modal_app.py`) and the web app on Vercel.
- Once: `pip install modal`, `modal setup`, `modal secret create terrasat --from-dotenv .env`, `modal volume create terrasat-data`, then upload the map data: `modal volume put terrasat-data data/raw raw`, `modal volume put terrasat-data data/cache cache`, `modal volume put terrasat-data data/outputs outputs`.
- Deploy (and after every backend change): `modal deploy modal_app.py`. It prints the API address (`https://<workspace>--terrasat-api.modal.run`).
- Vercel: Root Directory `web`; set `VITE_API_URL` to that address (no trailing slash) and `VITE_API_KEY` to the `API_KEY` in `.env`; redeploy after changing them.
- One container stays on (`min_containers=1`) so answers have no cold start; set it to 0 after judging to stop using credits.

SAM calls are cached, so repeating a run costs nothing. Imagery comes from the Mapbox Static Images API (`TILE_PROVIDER=mapbox_static`); `esri` is a no-key fallback for development.

## API

Start it with `uvicorn backend.app.main:app --reload`; interactive docs at http://127.0.0.1:8000/docs.

| Endpoint | What it does |
|---|---|
| `GET /profiles`, `GET /presets` | Use cases and demo sites |
| `POST /audit` | Run an audit for a profile at a preset or lon/lat; cached, returns summary + GeoJSON / overlay URLs |
| `POST /reports` | A resident's voice note (any audio format) + GPS + optional photo -> transcript, issue type, place, urgency, EN/SW summary, corroboration against river distance, height and 2024 floods |
| `GET /reports`, `PATCH /reports/{id}` | Report feed (filter by status, device or time) and status updates |
| `GET /audit/{id}/choke-points` | Culverts and bridges to clear, ranked by land draining through, at-risk buildings and residents' reports (re-ranked live); `format=csv` to export |
| `POST /audit/{id}/memo?lang=en` | Muse Spark briefing memo (English or Swahili) with sources and this week's KMD rain outlook; saved as `memo_<lang>.md` |
| `GET /reports?format=csv` | Reports as CSV |
| `POST /check` | Everything TerraSat knows about one spot: flood risk class, riparian reserve, 2024 flood, past floods, reports and neighbours' answers nearby |
| `POST /ask` | Ask anything about a place: Muse Spark picks the analysis (business site, solar, densification, flood) and the place, TerraSat runs it there and answers with a verdict, highlights and the picture; people on site get a quick question |
| `POST /observations` | Save a tap-to-answer reply; returns the next question |
| `GET /places?q=` | Place suggestions while typing (suburbs and landmarks, from local OpenStreetMap data) |
| `GET /report-types` | What people can report (from the audit profiles) |

Report statuses: `corroborated` / `unconfirmed` -> `assigned` -> `cleared` (or `dismissed`). Data is stored in `data/terrasat.db` (SQLite) and `data/media/`.

## Access and limits

Before the API gets a public address, set two keys in `.env` (make each with
`python -c "import secrets; print(secrets.token_urlsafe(24))"`):

| Setting | What it does |
|---|---|
| `API_KEY` | Every endpoint except `/health` needs the `X-API-Key` header. The apps send it: web via `VITE_API_KEY` in `web/.env`, phone via Settings → Advanced → Access key. It keeps strangers out, but it ships inside the apps, so it isn't a password. Empty = checks off (local development). |
| `STAFF_KEY` | Needed (header `X-Staff-Key`) to list everyone's reports, export them as CSV, or change a report's status. Never put it in the apps. People see only their own reports (by their phone's device id). |
| Rate limits | Per IP address and per phone (`X-Device-Id`): questions and memos 10/min and 100/day (`ASK_PER_MINUTE`, `ASK_PER_DAY`), voice reports 5/min and 50/day; place search and quick answers 120/min. Over the limit: HTTP 429 with `Retry-After`. Behind the Cloudflare tunnel the visitor's IP comes from `CF-Connecting-IP`. |
| `GOOGLE_CALLS_PER_DAY` | Cap on Google Places calls for the whole server (default 300). When it's used up, business answers use OpenStreetMap competitors and say so. |
| Upload limits | Voice notes up to 10 MB (`MAX_AUDIO_MB`) and photos up to 5 MB (`MAX_PHOTO_MB`), refused with HTTP 413 before they're read into memory; audio longer than 2 minutes is cut before transcription. Question text is capped at 1,000 characters. |

Limits are kept in memory and reset when the server restarts; a production setup would keep them in Redis.

## Project layout

```
backend/app/
  main.py                 FastAPI endpoints (ask, audits, reports, place check)
  core/config.py          settings from .env
  core/security.py        API key, staff key, rate limits, Google daily cap
  profiles/*.yaml         audit profiles: one file per use case
  profiles/loader.py      profile schema + validation
  services/audit.py       run_audit(profile, lon, lat): the whole pipeline + demo sites
  services/tiles.py       satellite imagery: fetch, stitch, cache
  services/sam_service.py SAM 3.1 calls, mask parsing, window dedup, overlays
  services/geo.py         tile maths, pixel to GPS, UTM, buffers
  services/layers.py      map layers (OSM, building footprints)
  services/analyzers.py   metrics per profile (flood exposure, solar & mini-grid)
  services/audio.py       converts voice notes to WAV for transcription
  services/meta.py        Muse Voice transcription and Muse Spark calls
  services/reports.py     reports and quick-question answers (SQLite)
  services/assistant.py   the Ask engine: routing, quick audits, place check, answers
web/                      React + Leaflet web app: src/App.tsx (map, panel, place search, ask), src/Report.tsx
                          (site report card, before/after slider, progress, memo), src/api.ts
mobile/                   Expo app: App.tsx (role picker, settings), src/Resident.tsx (voice reports,
                          offline queue, my reports, status timeline), src/Chat.tsx (Ask with report cards),
                          src/api.ts (API client + queue), src/ui.tsx (components, EN/SW text)
scripts/                  fetch_data.py, run_audit.py, check.py
tests/                    pytest suite
docs/SPEC.md              full specification and roadmap
```

## Status

- **Working:**
  - imagery pipeline (Mapbox Static Images API) and SAM 3.1 with Overture footprints;
  - flood risk rules (river distance + height, surface-water flag), checked against UNOSAT's 2024 damage;
  - drainage choke points, re-ranked live with residents' reports;
  - flood history layer (news and official records, evidence only);
  - the Ask engine across four analyses: business site, solar viability, densification, flood;
  - web app: chat beside a map, the analysis picture on the map, highlight cards, Google Maps competitor list, memo;
  - voice reports (Muse Voice + Muse Spark), corroboration, quick questions;
  - Muse Spark memo in English and Swahili with sources;
  - CSV / GeoJSON / Markdown exports;
  - solar/mini-grid profile;
  - tests (47).
  - mobile app (Expo, Android): Ask and voice reports with offline queue;
- **Next:**
  - polish and live runs of the four questions on demo places.

## Working with issues

Planned work is tracked as GitHub issues, grouped into milestones **M1 Live pipeline → M2 Backend API → M3 Mobile app → M4 Dashboard → M5 Demo & submission**.

- Mention the issue number in commit messages, e.g. `feat(reports): voice report pipeline (#5)`.
- Put `Closes #5` in the commit message (or pull request) when the work is done; GitHub closes the issue when it reaches `main`.
- New ideas or bugs: use the **Feature** or **Bug** template on GitHub's "New issue" page.

## Data and attribution

- **Imagery:** © Mapbox, © Maxar and other providers.
- **Map data:** © OpenStreetMap contributors (ODbL).
- **Business competitors:** Google Maps (Places API (New)), fetched live per question and never stored except place IDs; shown as a credited list, not drawn on non-Google maps, as Google's terms require.
- **Riparian reserve:** 6–30 m from the highest water mark under the EMCA (Water Quality) Regulations 2006; the government enforces 30 m along the Nairobi Rivers (Interior Ministry, May 2024). TerraSat uses 30 m.
- **Building footprints:** Overture Maps Foundation (includes Google Open Buildings, Microsoft and OpenStreetMap data; ODbL / CDLA).
- **Elevation:** Copernicus GLO-30.
- **2024 flood mapping:** UNITAR-UNOSAT, FL20240426KEN (CC BY-SA), via the Humanitarian Data Exchange.
- **Flood history:** news and government sources found by Muse Spark (each item keeps its URL); places geocoded with Nominatim (© OpenStreetMap contributors).
- **Segmentation:** SAM 3.1 by Meta, used under the SAM License. Mask parsing uses `meta-sam-parser`.

## Responsible use

TerraSat's flood outputs are **information to help people decide and protect themselves**: where to buy or build, early warning, drains to clear. Risk describes a place, never the people who live there, and the outputs are not meant for identifying homes to demolish. The chat never calls a place "safe" and tells buyers to confirm the title and riparian boundary with the authorities and to visit after heavy rain. Reports about crime or safety are deliberately not collected, because they stigmatise neighbourhoods. Detection counts are estimates from imagery and should be checked in the field before decisions that affect people.
