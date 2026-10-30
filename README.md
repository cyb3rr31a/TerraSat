# TerraSat

[![tests](https://github.com/cyb3rr31a/TerraSat/actions/workflows/tests.yml/badge.svg)](https://github.com/cyb3rr31a/TerraSat/actions/workflows/tests.yml)

**Ask planning questions of satellite imagery.**

TerraSat is a geospatial auditing engine for Kenyan urban and regional planning. Drop a pin or say what you need. TerraSat pulls current satellite imagery, uses **SAM 3.1** to find what the question requires (roofs, solar panels, garbage piles, water…), applies spatial rules (buffers, rings, distances) against map layers, and returns metrics, a verdict and a **Muse Spark** memo grounded in live web search, plus GeoJSON and CSV exports for QGIS.

> **One engine, many use cases.** Flood exposure, solar and mini-grid siting, heat islands, property-rates gaps and more all run on the same pipeline. Each use case is an **audit profile**, a short YAML file that says what to look for, which layers to load, which rules apply and what the memo should cover.
>
> **Hackathon case study: Urban Flood Exposure & Drainage Watch (Nairobi).** Kenya Met gives an 81% chance that this season's El Niño will be very strong. After the 2024 floods hit Nairobi's riverside settlements hardest, we show TerraSat finding exposed structures, drainage choke points and verified citizen reports before the peak rains. A second profile, **Solar & Mini-grid Planning**, shows the same engine answering a completely different question.

Built for the Meta Global AI Developer Hackathon 2026 (Indie Developer Track, *Build for Your World*).

## How it works

```
pin / voice ─► satellite mosaic ─► SAM 3.1 (profile prompts) ─► map layers + spatial rules
            ─► metrics + verdict ─► Muse Spark memo (web-grounded) ─► GeoJSON / CSV
```

| Meta model | Role in TerraSat |
|---|---|
| `sam-3.1` | Finds whatever the active profile asks for in the imagery, and checks the imagery at citizen reports |
| `muse-spark-1.3` | Parses reports, ranks priorities and writes the profile's memo with live web-search citations |
| `muse-voice-transcribe-1.0` | In-app voice reports and voice commands |

## Apps

| App | For | What it does |
|---|---|---|
| **TerraSat mobile** (Expo / React Native, `mobile/`, *in progress*) | **Residents** | Record a voice report (GPS + photo attached), works offline and sends later, track your report from received → verified → crew assigned → cleared |
| | **Field crews** | See assigned drains and choke points, navigate there, mark them cleared with a photo |
| **TerraSat dashboard** (React web app, `dashboard/`, *in progress*) | County / Red Cross monitoring and logistics teams | Audit map and layers, use-case switcher, live report feed, choke-point ranking, assign crews and track tasks, grounded memo, exports |

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

SAM calls are cached, so repeating a run costs nothing. Imagery comes from the Mapbox Static Images API (`TILE_PROVIDER=mapbox_static`); `esri` is a no-key fallback for development.

## API

Start it with `uvicorn backend.app.main:app --reload`; interactive docs at http://127.0.0.1:8000/docs.

| Endpoint | What it does |
|---|---|
| `GET /profiles`, `GET /presets` | Use cases and demo sites |
| `POST /audit` | Run an audit for a profile at a preset or lon/lat; cached, returns summary + GeoJSON / overlay URLs |
| `POST /reports` | A resident's voice note (any audio format) + GPS + optional photo -> transcript, issue type, place, urgency, EN/SW summary, corroboration against river distance, height and 2024 floods |
| `GET /reports`, `PATCH /reports/{id}` | Report feed (filter by status, device or time) and status updates |
| `GET /crews`, `POST /tasks`, `GET /tasks`, `PATCH /tasks/{id}` | Assign reports to crews; crews mark tasks en route / cleared with an after photo |
| `GET /audit/{id}/choke-points` | Culverts and bridges to clear, ranked by land draining through, at-risk buildings and residents' reports (re-ranked live); `format=csv` to export |
| `POST /audit/{id}/memo?lang=en` | Muse Spark briefing memo (English or Swahili) with sources and this week's KMD rain outlook; saved as `memo_<lang>.md` |
| `GET /reports?format=csv` | Reports as CSV |

Report statuses: `corroborated` / `unconfirmed` -> `assigned` -> `cleared` (or `dismissed`). Data is stored in `data/terrasat.db` (SQLite) and `data/media/`.

## Project layout

```
backend/app/
  main.py                 FastAPI endpoints (audits, reports, crews, tasks)
  core/config.py          settings from .env
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
  services/reports.py     citizen reports and crew tasks (SQLite)
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
  - voice reports (Muse Voice + Muse Spark), corroboration, crews and tasks;
  - Muse Spark memo in English and Swahili with sources;
  - CSV / GeoJSON / Markdown exports;
  - solar/mini-grid profile;
  - tests (47).
- **Next:**
  - mobile app (resident and crew modes);
  - web dashboard.

## Working with issues

Planned work is tracked as GitHub issues, grouped into milestones **M1 Live pipeline → M2 Backend API → M3 Mobile app → M4 Dashboard → M5 Demo & submission**.

- Mention the issue number in commit messages, e.g. `feat(reports): voice report pipeline (#5)`.
- Put `Closes #5` in the commit message (or pull request) when the work is done; GitHub closes the issue when it reaches `main`.
- New ideas or bugs: use the **Feature** or **Bug** template on GitHub's "New issue" page.

## Data and attribution

- **Imagery:** © Mapbox, © Maxar and other providers.
- **Map data:** © OpenStreetMap contributors (ODbL).
- **Building footprints:** Overture Maps Foundation (includes Google Open Buildings, Microsoft and OpenStreetMap data; ODbL / CDLA).
- **Elevation:** Copernicus GLO-30.
- **2024 flood mapping:** UNITAR-UNOSAT, FL20240426KEN (CC BY-SA), via the Humanitarian Data Exchange.
- **Flood history:** news and government sources found by Muse Spark (each item keeps its URL); places geocoded with Nominatim (© OpenStreetMap contributors).
- **Segmentation:** SAM 3.1 by Meta, used under the SAM License. Mask parsing uses `meta-sam-parser`.

## Responsible use

TerraSat's flood outputs are for **protection**: early warning, evacuation priority, drains to clear and relief staging. They are not meant for identifying homes to demolish. Detection counts are estimates from imagery and should be checked in the field before decisions that affect people.
