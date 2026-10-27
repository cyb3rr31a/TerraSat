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

### Current profiles

| Profile | Status | Question it answers | Users |
|---|---|---|---|
| **Urban Flood Exposure & Drainage Watch** (`flood`) | **Demo case study**, built in depth | Who is exposed, where will water back up, what are residents seeing? | Ward disaster officers, Nairobi County, Kenya Red Cross |
| **Solar & Mini-grid Planning** (`solar_minigrid`) | Beta, shown briefly in the video | How many homes are unserved, how close is the grid, what does it cost per household? | Utility planners, mini-grid developers, WISPs, county energy offices |

### Profiles on the roadmap (same engine)

| Profile | What SAM finds | Rule / metric |
|---|---|---|
| Urban heat islands | Tree canopy, dark metal roofs, bare ground | Heat-risk score per block, tree-planting sites |
| Property-rates gap | Every building | Buildings missing from the county rates register (uncollected revenue) |
| Fire access in informal settlements | Dense roof clusters, path widths | Clusters a fire engine can't reach |
| Affordable housing site finder | Vacant or bare land | Plots ranked by access to roads and services |
| Densification and zoning | Footprints, tall blocks | Plot coverage compared with zoning limits |
| Green-space equity | Parks, fields, trees | Green space per resident by ward |
| Desire-line walkways | Dirt footpaths | Where sidewalks are missing |
| Quarry and wetland loss | Quarry scars, wetland vegetation | Encroachment alerts for NEMA |
| Rural flood plains | Buildings, water | The flood profile applied to Tana River, Garissa and Mandera (worst hit in 2023) |
| Rural infrastructure deserts | Roofs, solar, tanks, unpaved roads | The original mini-grid / WISP feasibility idea |

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
- **Imagery:** a 2.1 km square around the pin at zoom 18 (~0.6 m/px), stitched from Mapbox tiles and cut into 16 overlapping 1024 px windows (10% overlap).
- **Segmentation:** SAM runs on each window, once per prompt.
- **To map coordinates:** masks become latitude/longitude polygons, then UTM 37S (EPSG:32737) for distances and areas.
- **De-duplication:**
  - Fragments cut off at an inner window edge are dropped, because the overlap means the whole object appears in a neighbouring window.
  - Remaining duplicates are merged with polygon NMS: IoU above 0.5, or a polygon mostly contained in another.
- **Exposure rules:**
  - Inside the **riparian buffer** around OSM rivers, streams and canals. Culverted sections are excluded. The width is configurable (default 30 m; reported legal range 6–30 m; cite the source in the write-up).
  - On **low-lying ground**: height above the nearest stream from the Copernicus 30 m DEM below a threshold. *(To do.)*
- **New since 2023:** a SAM building with no overlapping footprint in Google Open Buildings (2023, CC BY 4.0) is flagged as new.
- **Metrics:** exposed structures, new exposed structures, exposed footprint, exposure per 100 m of riverbank, and an optional estimate of people exposed.

### F2: Drainage choke points *(to do)*

- **Candidates:** road–waterway crossings, culverted sections, and SAM garbage or ditch detections near waterways.
- **Ranking inputs:** built-up area upstream, garbage within 50 m, and citizen reports within 100 m.
- **Output:** a ranked list of drains and culverts to clear.

### F3: Citizen reports (in-app voice) *(to do)*

- **The app:** a phone-sized web page with one record button, browser GPS (or a typed landmark) and an optional photo. It records **WAV**, the only format the transcription API accepts.
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

## 6. Architecture

```
React dashboard / Streamlit debug ─┐
In-app voice report page ──────────┼─► FastAPI (backend/app/main.py)
                                   │      GET /profiles   POST /audit (next)
                                   ▼
                    services/audit.py  run_audit(profile, lon, lat)
                       │
   ┌───────────────────┼─────────────────────┬──────────────────────┐
   ▼                   ▼                     ▼                      ▼
tiles.py           sam_service.py        layers.py             analyzers.py
Mapbox grid,       SAM 3.1 per window,   OSM context layers    registry: flood_exposure,
stitch, cache      parse, dedup, cache   (waterways, power,    solar_minigrid, … 
                                         roads)                (exposure.py helpers)
   └──────────── geo.py: tile math, pixel↔GPS, UTM, buffers, NMS ─────────┘

profiles/*.yaml   ← one file per use case (what to find, layers, rules, memo)
next: reasoning.py (Muse Spark memo) · reports.py (voice) · chokepoints.py · export.py
```

**Rules**

- All logic lives in the services, and use cases live in profiles.
- Streamlit is a debug console; the React app (Vite + react-leaflet) is the demo UI.
- React go/no-go on Nov 1.

## 7. Data sources

| Layer | Source | Licence |
|---|---|---|
| Satellite tiles | Mapbox Satellite raster tiles | Mapbox ToS; show attribution |
| Waterways, power lines, roads | OpenStreetMap via Overpass (`scripts/fetch_osm_layers.py`) | ODbL |
| 2023 building baseline | Google Open Buildings v3 | CC BY 4.0 |
| Elevation | Copernicus GLO-30 DEM | Free, attribution |
| Ward boundaries | IEBC / HDX | Check |
| Grounding | KMD, Nairobi County, news via Muse Spark web search, plus a local cache for the live demo | n/a |

## 8. Demo plan (2-minute video)

| Time | Scene |
|---|---|
| 0:00–0:15 | Hook: the El Niño warning, the 2024 Nairobi floods. "TerraSat asks planning questions of satellite imagery." |
| 0:15–1:40 | **Flood case study in Mathare:** a voice command, SAM masks lighting up, the riparian buffer, new structures flagged, a citizen voice report verified by imagery, choke points ranked, the bilingual memo with citations, GeoJSON export. |
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
| Wed Oct 28 | Smoke tests with real keys. First live Mathare run. Tune prompts on real imagery. Open Buildings baseline. |
| Thu Oct 29 | DEM low-lying layer. `POST /audit` endpoint. Streamlit debug UI with a profile picker. |
| Fri Oct 30 | `chokepoints.py`. Start `reasoning.py` (memo template driven by the profile). |
| Sat Oct 31 | Finish the memo (EN/SW, citations). Exports (CSV, memo). |
| Sun Nov 1 | `reports.py` and the in-app voice page (WAV). **React go/no-go.** |
| Mon Nov 2 | React dashboard with a profile switcher. Polish the solar profile on Syokimau (live run, prompt tuning). |
| Tue Nov 3 | Cache all demo presets, polish, rehearse. |
| Wed Nov 4 | Record the video, final README, submit (Thu 10:59 AM Nairobi time). |

## 10. Open questions

- Swahili/Sheng support in `muse-voice-transcribe-1.0`, and whether web search works with image input. Test with `scripts/smoke_test_meta.py`.
- Hackathon rules: video length, public repo or live URL, licence, whether non-Meta inference is allowed.
- The legal riparian buffer width and its citation.
- Network: the Claude sandbox can't reach Mapbox, Overpass or the Meta API. Run scripts locally, or allow those domains in Claude settings under Capabilities.
