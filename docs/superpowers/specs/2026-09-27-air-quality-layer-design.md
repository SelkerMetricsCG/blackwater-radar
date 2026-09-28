# Air quality layer: design (2026-09-27)

Agreed with Chris in chat, 2026-09-27 18:38–19:17. Phase 1 of "Smoke & fires"; phases 2 (fires) and 3 (HRRR smoke
forecast loop) get their own specs. Source research, endpoints and terms: `smoke_research/sources_notes.md`.

## Goal
Answer "how smoky is the air where I'm going, right now, and is it getting better or worse?" with regulatory and
temporary smoke monitors, plus AirNow's own interpolated AQI map, in a new **Air quality** section of the panel.

## Decisions (Chris, 2026-09-27)
| # | Decision |
|---|---|
| 1 | Air quality gets **its own panel section**, separate from the later "Smoke & fires" section. |
| 2 | Order of work: Air quality first, then fires, then the smoke forecast loop. |
| 3 | Stations come from **AirNow's public hourly files** (keyless), plus AirNow's temporary smoke monitor file. |
| 4 | Interpolated map: **AirNow's gridded AQI** (`current_pm25.grib2`) now, labelled "monitors only"; an HRRR-fused surface later, after the smoke forecast exists. |
| 5 | **Official AQI colours** (AirNow guideline), not muted versions. |
| 6 | **PurpleAir left out** (paid API; terms limit use to "internal, non-commercial, non-public"). |
| 7 | Show AirNow's own NowCast AQI unchanged; nothing is recomputed. |
| 8 | Ozone left out of phase 1 (same file; easy to add later). |

## What the reader sees
```
Now & forecast
Snow
Water
Air quality                      (new; "Smoke & fires" will follow it in phase 2)
  ☐ AQI stations (?)
      [Good | Moderate | USG | Unhealthy | Very unhealthy | Hazardous]   0 51 101 151 201 301
      NowCast AQI for PM2.5 (smoke and fine particles), hourly; preliminary data from AirNow and reporting agencies.
  ☐ Interpolated AQI (monitors only)
      Interpolated by AirNow from monitors only; it ignores terrain, so a valley and the ridge above it can differ
      from what's shown. Blank where no monitor is near.
Hazards
```
- Both switches are off by default and join `DEF_CHECKS`, so "Make current map & settings my default" keeps them.
- (?) tip: NowCast weights the latest hours so it responds within a few hours when smoke arrives (the official AQI is a
  24 h average); squares are temporary monitors deployed near fires.
- **Markers:** permanent monitors are circles filled with the category colour, thin dark outline (yellow must read on
  light basemaps); temporary smoke monitors are squares in the same colours; no report for more than 3 h = hollow grey.
  From zoom 9 each marker shows its AQI number (the in-view-only divIcon labels from the station-label lag fix).
- **Station card** (click or hover, like weather stations): name, agency (`DataSource`), elevation where known, "temporary smoke
  monitor" tag where it applies; large AQI number with category chip; "PM2.5 12.3 µg/m³ last hour · as of 6 PM (40 min
  ago)"; trend word (rising / falling / steady) from the raw hourly values; a 72 h chart of hourly AQI bars coloured by
  category with day ticks and a hover readout (the rivers chart's tracker); footer "Preliminary data, not verified.
  Source: AirNow (U.S. EPA), <agency>." No airnow.gov link while its DNS fails (see notes).
- **Click anywhere:** the point panel gains an air-quality line: nearest station's AQI and distance; with the grid on,
  also "interpolated AQI 87, Moderate".
- **Grid overlay:** one image per region, category colours, AirNow's blanked cells transparent.
- `terms.html`: AirNow credit and the "preliminary" wording.

## What runs behind it
New module `airquality.py`, `build(log)`, called in `capture.py`'s 15-minute block (`if not HOURLY_ONLY`, next to
alerts): AirNow posts each hour ~:23 after it ends and revises it ~:45, so the hourly job (:04) would always be an hour late.

1. **Stations.** Fetch the two newest `https://files.airnowtech.org/airnow/YYYY/YYYYMMDD/HourlyAQObs_YYYYMMDDHH.dat`
   (the newer one plus the one AirNow revises) and `https://files.airnowtech.org/airnow/today/AirNowWildfire.csv`.
   Skip all work when neither has changed since the last run (Last-Modified kept in state).
   - `HourlyAQObs` columns used: `AQSID` (id), `SiteName`, `Latitude`, `Longitude`, `Elevation`, `DataSource` (agency),
     `ValidDate` + `ValidTime` (UTC, hour-begin), `PM25_AQI` (NowCast AQI), `PM25` (raw hourly µg/m³). Rows without
     `PM25_AQI` are not PM2.5 sites for that hour and are skipped.
   - `AirNowWildfire.csv`: `Latitude, Longitude, SiteName, Time, NowCast Concentration, NowCast AQI`; id = `SiteName`;
     `Time` is local with a zone abbreviation ("Sun 09/27/2026 09:00 PM EDT") and is converted to UTC. Latest hour only.
2. **Rolling store.** `aq_cache.json` in `cloud.py STATE_FILES` (private; the `_cache.json` name keeps r2sync from
   publishing it): per station, 72 hourly slots of NowCast AQI and raw µg/m³. A revised hour overwrites the older value.
   First run (store empty) fills it from the 72 hourly files AirNow keeps. Temporary monitors' history builds up from launch.
   The five regions run in one Actions job, so downloads are cached on the runner and fetched once, not five times.
3. **Output `<region>/data/airquality.js`**, global `AIRQ`:
   `{updated, updated_t, hours:[72 UTC hour stamps], grid:{t, file} | null,
     stations:[{id, name, agency, lat, lon, elev, temp:bool, aqi:[72], pm:[72]}]}`
   (`null` for missing hours; for temporary monitors, which AirNow publishes without raw hourly values, `pm` holds the
   NowCast concentration and the card says "NowCast PM2.5"). Only stations inside the region window
   (`region.bbox()`). Expected ~150 KB for PNW, less elsewhere.
4. **Grid.** Fetch `https://files.airnowtech.org/airnow/today/current_pm25.grib2` only when its Last-Modified changed;
   decode with cfgrib; cut to the region window and resample to Web Mercator the way the existing overlays do (cKDTree
   nearest neighbour); colour by AQI category, 9999 cells transparent; write one WebP in a new `aq/` folder (added to the
   image-folder list in `r2sync.py`) and a click-anywhere grid with `values.write_grid("aqi", ...)`.
5. **Failure.** Any failed fetch keeps the last good `airquality.js`, image and store; the page greys stations whose
   newest report is more than 3 h old. Log line per run: `airquality: 242 stations (12 temporary), newest 00Z, grid 01:44Z`.

Page: `AIRQ` joins the script-tag globals; the overlay and markers refresh through `applyData` like the other layers.

## Data check (gate before any map code)
Run `airquality.build()` locally for `pnw` with no upload (`r2.env` absent, or call `build()` directly). Show Chris:
1. The accounting line: rows read, PM2.5 sites, inside the window, temporary monitors, rows skipped and why.
2. A MATLAB-style figure: the grid overlay with the stations on top, coloured by category, for one hour.
3. **Independent check:** our AQI for every station in the newest hour against USFS AirFire's NowCast export for the
   same hour (`monitoring/v2/latest/geojson/mv4_airnow_PM2.5_latest.geojson`; a different pipeline from the same
   monitors), converted to AQI with the 2024 breakpoints. Expect exact agreement at ~93% of stations and within 2
   points at ~97% (the research agent's figures); list the outliers. Also the grid value at each station against its
   station AQI (research: mean difference 1.0).
4. Three stations' 72 h series (one urban, one mountain valley, one temporary monitor) as a plot, raw beside AQI.
Chris looks at these before the map work starts.

## Testing and release
- pytest (network blocked by `conftest.py`), with small fixture files: parse both AirNow files, including the local-time
  stamps across EDT/CDT/MDT/PDT and a missing `PM25_AQI`; rolling merge (revised hour overwrites; slots age out after
  72 h; first-run fill); window clipping; unchanged Last-Modified skips work; failed fetch keeps the last good file.
  cfgrib/numpy imported inside functions, not at module level (CI installs only pytest and pyyaml).
- node tests on `// BEGIN…END` blocks in `map.html` (the `test_map_*.py` pattern): AQI category and colour for the
  edges 0, 50, 51, 100, 101, 150, 151, 200, 201, 300, 301, 500; trend rule; saving and restoring the two switches.
- Local build (`build_web.py`, `web/` served on 127.0.0.1) checked in the in-app browser against live data: markers,
  labels at zoom 9, card and chart, grid, click-anywhere, legend, no console errors; phone width.
- Release as before: Chris runs the push and deploy from Run-button blocks; then curl the live page and diff it
  against `web/index.html`, and check the first Actions runs' `airquality:` log lines for all five regions.

## Parameter ledger (judgment calls and sources; Chris to confirm when shown)
| Parameter | Value | Source | Where |
|---|---|---|---|
| AQI category edges | 0 / 51 / 101 / 151 / 201 / 301 | EPA AQI Technical Assistance Document (May 2024) | map.html, airquality.py |
| Category colours | 00E400, FFFF00, FF7E00, FF0000, 8F3F97, 7E0023 | EPA AQI TAD official RGB (AirNow guideline) | map.html, airquality.py |
| History length | 72 h | judgment call (matches AirNow's 72 h of files) | airquality.py |
| Stale after | 3 h without a report | **judgment call** | map.html |
| Trend rule | latest raw hour vs 3 h earlier: rising if up ≥ 5 µg/m³ and ≥ 20 %, falling if down by the same, else steady; temporary monitors use NowCast concentration | **judgment call** | map.html |
| Station set | inside `region.bbox()` | judgment call (same window as every other layer) | airquality.py |
| Grid resampling | nearest neighbour (cKDTree), same output size as the freezing-level overlay | existing pattern; the grid is ~2.5 km, finer than one output pixel at the window scale | airquality.py |
| Grid nodata | 9999 → transparent | AirNow file | airquality.py |
| Label zoom | 9+ | existing station labels | map.html |

## Open items found while designing
- airnow.gov (www, fire., document.) fails to resolve through 1.1.1.1 and 8.8.8.8 (checked 2026-09-28 02:00 UTC);
  files.airnowtech.org is fine. Recheck before adding any airnow.gov link.
- AirNow's data-exchange guidelines include a form "to return" to AirNow's data management centre: Chris's call
  whether to send it (he sends it himself).

## Out of scope
Ozone and PM10; PurpleAir and other low-cost sensors; the HRRR-fused AQI surface; AirFire temporary-monitor history
backfill; fires; smoke forecast; smoke outlooks and blog feeds (phases 2 and 3).
