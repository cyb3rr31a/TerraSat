# TerraSat

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
3. If a new map layer is needed, add it to `scripts/fetch_osm_layers.py` and `backend/app/services/layers.py`.

## Setup (Windows, Anaconda Prompt)

```bat
cd C:\hackathons\terrasat
conda create -n terrasat python=3.11 -y
conda activate terrasat
pip install -r requirements.txt
copy .env.example .env    &REM then add META_API_KEY and MAPBOX_TOKEN
```

- **Meta key:** [dev.meta.ai](https://dev.meta.ai/) → API keys.
- **Mapbox token:** [account.mapbox.com/access-tokens](https://account.mapbox.com/access-tokens/).
- If pip has trouble with geopandas on Windows, run `conda install -c conda-forge geopandas` first.

## Run

```bat
python scripts\smoke_test_meta.py sam                        &REM 1 SAM call (~$0.0025) -> data\outputs\smoke\
python scripts\smoke_test_meta.py spark                      &REM 1 Muse Spark + web search call
python scripts\fetch_osm_layers.py                           &REM waterways, power lines, roads -> data\raw\
python scripts\run_audit.py --profile flood --preset mathare  &REM flood case study (~64 SAM calls, cached)
python scripts\run_audit.py --profile solar_minigrid --preset syokimau
python scripts\run_audit.py --profile flood --offline         &REM no network: fake tiles + mock SAM
uvicorn backend.app.main:app --reload                        &REM API docs at http://127.0.0.1:8000/docs
python -m pytest -q                                          &REM tests
```

Each audit writes `mosaic.jpg`, `overlay.png`, `audit.geojson` and `summary.json` to `data\outputs\<profile>_<place>\`.

## Project layout

```
backend/app/
  main.py                 FastAPI (GET /profiles; POST /audit next)
  profiles/*.yaml         audit profiles: one file per use case
  profiles/loader.py      profile schema + validation
  services/audit.py       run_audit(profile, lon, lat): the whole pipeline
  services/tiles.py       Mapbox tile grid, stitching, cache
  services/sam_service.py SAM 3.1 backend, mask parsing, window dedup, overlays
  services/geo.py         tile math, pixel↔GPS, UTM, buffers, polygon NMS
  services/layers.py      OSM context layers
  services/analyzers.py   metrics per profile (flood_exposure, solar_minigrid)
  services/exposure.py    riparian exposure helpers
scripts/                  fetch_osm_layers, run_audit, smoke_test_meta
tests/                    pytest suite
docs/SPEC.md              full specification and roadmap
```

## Status

- **Working:**
  - imagery pipeline;
  - SAM 3.1 integration (official `meta-sam-parser`);
  - dedup across windows;
  - flood exposure and solar/mini-grid analyzers;
  - profile system;
  - tests.
- **Next:**
  - first live runs;
  - elevation (low-lying ground) layer;
  - `/audit` endpoint;
  - drainage choke points;
  - Muse Spark memo;
  - in-app voice reports;
  - React dashboard.

## Data and attribution

- **Imagery:** © Mapbox, © Maxar and other providers.
- **Map data:** © OpenStreetMap contributors (ODbL).
- **Building baseline:** Google Open Buildings (CC BY 4.0).
- **Elevation:** Copernicus GLO-30.
- **Segmentation:** SAM 3.1 by Meta, used under the SAM License. Mask parsing uses `meta-sam-parser`.

## Responsible use

TerraSat's flood outputs are for **protection**: early warning, evacuation priority, drains to clear and relief staging. They are not meant for identifying homes to demolish. Detection counts are estimates from imagery and should be checked in the field before decisions that affect people.
