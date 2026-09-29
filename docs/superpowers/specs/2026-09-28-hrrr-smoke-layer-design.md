# Smoke forecast layer (HRRR near-surface smoke): design (2026-09-28)

Phase 3 of "Smoke & fires". Phase 1 (Air quality) and phase 2 (Fires) went live 2026-09-28. Chris asked for this phase as
one continuous build-and-release session with **no review stops** (`smoke_research/NEXT_SESSION_hrrr_smoke.md`): every
decision below that is not marked "Chris" was taken by Claude on his behalf and is recorded with its alternatives and
what it costs if wrong, for him to review afterwards. Endpoints were re-checked 2026-09-29 01:58–02:10 UTC (evening of
2026-09-28 Pacific); the numbers here are from that check.

## Goal
Answer "will there be smoke where I'm going, and when?" with NOAA's HRRR near-surface smoke forecast, hour by hour for
the next two days, as a loop in the **Smoke & fires** section, with the value and a 48-hour curve at any clicked point.

## Decisions
| # | Decision | By | Alternatives | Cost if wrong |
|---|---|---|---|---|
| 1 | Third layer in **Smoke & fires**, after Fires and Satellite hotspots. | Chris | | |
| 2 | HRRR `MASSDEN` at 8 m above ground, 48 h forecasts of the 00/06/12/18Z runs, as a loop. | Chris | | |
| 3 | NWS smoke advisories are not repeated (Hazards already shows them). HRRR-fused AQI surface is a later phase. | Chris | | |
| 4 | **Colours: the PM2.5 AQI category colours on µg/m³** (EPA 2024 breakpoints: Moderate from 9.1, USG 35.5, Unhealthy 55.5, Very unhealthy 125.5, Hazardous 225.5), stepped, plus a **light-smoke band 2–9 µg/m³ in translucent warm grey**; **transparent below 2 µg/m³**. | Claude | (a) a continuous µg/m³ ramp like NOAA GSL's HRRR-Smoke plots (1, 2, 4 … 200); (b) AQI colours with green for Good; (c) floor at 1, 5 or 9 µg/m³. | The colours say "AQI category", but HRRR is smoke only (no background PM2.5) and an hourly instant, while the AQI is a NowCast / 24 h measure: a reader can over-read a yellow patch as "the AQI will be Moderate". The legend and tip say so. (a) would avoid that but adds a second colour language beside the AQI stations and AirNow grid, and the reader's question is "unhealthy or not". A floor at 2 hides faint model haze (on 2026-09-28 18Z f01, 0.1 % of the PNW window and 5 % of Sierra were ≥ 2; ≥ 1 was 4–9 %); in a smoky August the grey band may cover much of the West, which is true but busy (opacity slider). |
| 5 | **Column smoke (HMS "smoke aloft" polygons): later**, not in this release. | Claude | Add HMS now as a fourth layer (ArcGIS GeoJSON, ~2 issues a day). | HMS shows observed smoke that may be aloft; beside a near-surface forecast in the same first release it invites reading it as ground smoke and needs its own legend and wording. Cost: readers lack an observed-smoke check until then (the AQI stations and satellite loop partly fill it). Design sketch kept below. |
| 6 | **RRFS: stay on HRRR**; revisit after RRFS is operational and on AWS. | Claude | Switch at RRFS go-live (2026-10-14). | See "RRFS: when and how to switch". HRRR is not being retired (SCN 26-48). Cost of waiting: BC stays masked in PNW and the loop stays 48 h (RRFS: 84 h, 13 km North America grid covers BC). |
| 7 | **PNW north of HRRR's edge: masked**, with the model edge drawn as a dashed line ("no smoke forecast north of here"). | Claude | Fill BC from ECCC RAQDPS (10 km, 00/12Z, 72 h). | 18 % of the PNW window (southern BC) shows no smoke forecast. A RAQDPS fill would put a seam between two models with different physics, grids, run times and emissions on the map, and needs a second pipeline (GeoMet WMS images carry no values; values need the MSC Datamart GRIB). |
| 8 | **Runs in the hourly job** (`hourly.yml`, after freezing level); **builds only when a newer complete 48 h run is posted**, otherwise does nothing (one small `.idx` request). | Claude | (a) the 15-minute radar job; (b) rebuild every hour. | (a) would shave ≤ 15 min of latency but lengthen the 6–9 min radar job (it must finish in 15) four times a day. Cost of the choice: a run is on the map ~2 h 5 min to ~2 h 25 min after its start time (f48 is posted ~1 h 49 min after the run; the hourly job starts at :04); if f48 is late past :04 the run waits another hour. (b) would re-upload identical frames (MD5 skip saves the PUTs but not the work). |
| 9 | **48 frames (f01–f48), one per hour**, lossless WebP at 640 × 640 px (0–3 KB each), in **two alternating slots** (`a01…a48`, `b01…b48`): a new run is written to the slot the page is not using, then `smoke.js` switches. | Claude | One set of names overwritten in place; names by valid time with deletions; 3-hourly frames after 24 h. | Fixed names in one set would show, for the seconds of an upload, a new run's image under the old run's time label (6 h off). Two slots cost nothing extra in writes; R2 keeps 96 small frames per region. |
| 10 | **Click anywhere (while the layer is on): the value at the shown hour and a 48 h curve at that point**, from one value file per run: 128 × 128 cells × 48 hours, integer µg/m³ (brotli-compressed by R2 on the way out). | Claude | One 256 × 256 grid per hour (the freezing-level pattern: 48 files per run, finer cells) plus a peak grid. | Cells are ~9–12 km (a block mean of the model's 3 km cells), so next to a fire the clicked value is lower than the peak pixel in the frame; the popup says "about" and "10 km average". Saves 47 R2 writes per run per region and gives the curve. |
| 11 | The page shows hours from the one nearest now onward (valid time > now − 30 min); past hours of the run are hidden. The loop plays from that hour to +48 h of the run and restarts. | Claude | Show the whole run, past hours greyed. | Past hours of a forecast are not what the reader asks; hiding them makes the run's age matter only as a shorter loop (38–46 h ahead usually). |
| 12 | **Player inside the layer's panel** (Play/Pause, step, slider, time label) and a small **time badge on the map** while the layer is on; not the radar bar. | Claude | Drive it from the radar bar; hour chips like freezing level. | The radar bar is a past timeline shared by radar and satellite; mixing a +48 h forecast into it would confuse both. 48 chips do not fit a 300 px panel. On a phone the panel is a bottom sheet, so the badge keeps the hour visible while the loop plays with the panel closed. |

## What the reader sees
```
Smoke & fires
  ☐ Fires (?)
  ☐ Satellite hotspots (?)
  ☐ Smoke forecast (HRRR) (?)
      [Play] [<] [>] ─────────o──────────
      Tue 3 PM · in 14 h
      opacity ──────o──
      [ light | Moderate | USG | Unhealthy | V. unhealthy | Hazardous ]  2  9  35  55  125  225 µg/m³
      HRRR run Mon 11 AM (18Z) · 46 h ahead · updated 1:12 PM
      Smoke only, near the ground (8 m), hourly. Colours are the PM2.5 AQI category for that concentration; grey is
      light smoke (still Good). A model: plumes from new fires can be misplaced.   [PNW: dashed line = edge of the model;
      no smoke forecast north of it.]
```
- Off by default. The switch and the opacity slider join `DEF_CHECKS` / `DEF_RANGES`, so "Make current map & settings
  my default" keeps them; the switch defaults off, so old saved defaults need no `migrateDefault` entry.
- Loads only when switched on (`smoke.js`, then the frames of the shown hours); reloads `smoke.js` every 30 min while
  on, keeping the shown valid time when the new run has it.
- Overlay `zIndex` 386 (between freezing-level bands 385 and the AirNow grid 387), default opacity 0.65.
- Map badge (Leaflet control, bottom left): "Smoke forecast · Tue 3 PM".
- (?) tip: what HRRR is, smoke only (a monitor in clean air reads a few µg/m³ higher), the colours, that it is a model
  (plumes from new fires can be misplaced; check AQI stations for measured air), runs every 6 h, ~2 h to arrive.
- **Click anywhere** with the layer on: "Smoke forecast (HRRR)" block: "about 14 µg/m³ at Tue 3 PM (Moderate)", the
  highest value ahead and when, and an SVG curve of the next hours with the category colours (the AQI card's chart
  style), "10 km average; smoke only". Outside the model: "no smoke forecast here (outside the HRRR model)".
- `terms.html`: "Smoke forecasts are NOAA's High-Resolution Rapid Refresh model (HRRR-Smoke, NCEP), from NOAA's open
  data on AWS; a model forecast, not a measurement."

## What runs behind it
New module `smoke.py`, `build(log)`, called in `capture.py`'s hourly block after `freezing`. Requests use the plain
Chrome User-Agent, 30 s timeouts, the runner cache and the hung-host rule (`airquality.fetch`, `_open`, `CACHE_DIR`).

1. **Newest complete run.** Candidates: the 00/06/12/18Z runs of the last 30 h, newest first, only those at least
   1 h 40 min old. A run is complete when its f48 index exists:
   `https://noaa-hrrr-bdp-pds.s3.amazonaws.com/hrrr.YYYYMMDD/conus/hrrr.tHHz.wrfsfcf48.grib2.idx` (S3 answers 403/404 =
   not posted). Checked 2026-09-29: 18Z f01 index posted 18:54:09, f48 19:49:03 UTC.
2. **Nothing new → nothing written.** The private state `data/smoke_cache.json` (`cloud.py STATE_FILES`) holds the run
   on the map, its slot and when it was built. If the newest complete run is that run, the job logs so and writes
   nothing, unless R2's `data/smoke.js` is missing or older than the recorded build (a failed upload): then it rebuilds.
3. **Fetch.** For f01…f48: the `.idx`, the `:MASSDEN:8 m above ground:` record's byte range (record 76 at f01 and f48;
   found by text, never by number), one HTTP Range request (206; 0.6–1.1 MB; must start with `GRIB`).
4. **Decode** with ecCodes from memory: Lambert conformal, 1799 × 1059, 3 km, tangent at 38.5°N, LoV 262.5°, first
   point 21.138123°N 237.280472°E, sphere R = 6,371,229 m (all read from the message, checked, not assumed);
   kg/m³ × 10⁹ = µg/m³.
5. **Resample** to the region window (5 × 5 zoom-7 Web Mercator tiles, computed at 640 × 640 px): each pixel's
   latitude/longitude → the model's fractional (i, j) with the Lambert formula (matches ecCodes' own coordinates to
   0.0000 cells on a 1,300-point sample, 2026-09-29), bilinear interpolation, NaN outside the grid.
6. **Frame** per hour: category image (decision 4) as lossless WebP, `frames/smoke/<slot><hh>.webp`.
7. **Values**: the 640 px field → 128 × 128 block means per hour (NaN block → -1), integers, hour-major, one file
   `data/values/smoke_<slot>.js`: `window.VALUES["smoke_a"] = {w:128, h:128, n:48, t0, dt:3600, scale:1, unit, nodata:-1, data}`.
8. **`data/smoke.js`**, global `SMOKE`: `{run_utc, run_t, updated, updated_t, slot, floor, coverage, hours:[{h, t, file,
   max}], series:"smoke_a", edge:[[[lat, lon], …], …]}` (`max` = window maximum µg/m³ that hour; `edge` = the model's
   boundary inside the window, empty where the window is fully covered; `coverage` = share of window pixels inside
   the model).
9. **Failure**: any hour that fails to fetch or decode aborts the build (the page keeps the previous run; the state is
   not advanced, so the next hourly run tries again); what was written into the unused slot is harmless. A hung host
   stops the step at once (`HostDown`). Budget: 240 s per region step.
10. **Log line**: `smoke: HRRR 18Z Sep 28 -> slot b, 48 h, peak 142 ug/m3 (f01), 82% of window in the model, 38.4 MB, 21 s`
    or `smoke: HRRR 18Z Sep 28 already on the map; next run 00Z`.

`r2sync.py` treats `frames/smoke/` like the other overwritten maps (uploaded when the bytes change, `max-age=60`; the page
adds `?v=<run_t>`), `data/values/*.js` and `data/smoke.js` as now.

### R2 writes (Class A)
Per new run per region: 48 frames + 1 value file + `smoke.js` + `smoke_cache.json` = **51 PUTs** at most (all-clear
hours whose bytes equal the slot's previous run are skipped by the MD5 check). 4 runs × 5 regions = 20 builds a day →
**≤ 1,020 PUTs a day, ≤ 32k in a 31-day month**. Hours with no new run write nothing. Budget after HANDOFF item 9:
~610k of the free 1 million → ≤ ~642k.

## Data check (run by Claude before any page code; no stop)
`python smoke_research/smoke_check.py <region>` runs `smoke.build()` locally without uploading (it never calls
`r2sync`) and prints:
1. **Accounting line**: run, hours fetched / failed, MB, decode grid, window coverage, share of pixels ≥ 2 and ≥ 9.1,
   peak µg/m³ with hour and place, PUTs if published.
2. **Independent check A (geometry)**: for 2,000 random window pixels, the value the pipeline drew against the value
   at the nearest model grid point found with ecCodes' own latitude/longitude arrays and a k-d tree (no shared code
   with the Lambert formula); median and 95th-percentile difference.
3. **Independent check B (against measurements)**: HRRR at AirNow permanent monitors and AirFire temporary monitors vs
   their measured PM2.5 for the run's analysis hour (hour starting at the run time; model = mean of f00 and f01 at the
   site, from the series cell the page would read and from the nearest grid point). Reported: n, Spearman rank
   correlation, median measured − model (background PM2.5 the model does not carry), sites measured ≥ 35.5 with the
   model's value, sites modelled ≥ 35.5 with the measured value, and a georeferencing test: the rank correlation with
   the model field shifted 25 and 50 km in eight directions must not beat the unshifted one by a clear margin.
4. **MATLAB-style figure** (`plt.style.use('matlab')`): the window at the analysis hour with monitors coloured by
   measured PM2.5 category over the smoke field; measured vs modelled scatter (log axes); window peak and area ≥ 9.1
   by forecast hour. Saved to `smoke_research/checks/smoke_check_<region>.png` (gitignored).
The layer ships only if A agrees to within interpolation error and B shows no sign of a unit, place or time error
(HRRR smoke's known skill is modest; low correlation alone is not a defect, a shifted or scaled pattern is).

### Data check results (run 2026-09-29 00Z, checked 19:16–19:20 PDT 2026-09-28, before the page was written)
| | Sierra | PNW |
|---|---|---|
| Hours built / bytes | 48/48, 45.5 MB, 24 s (6 s from the runner cache) | 48/48 |
| Window in the model | 100 % | 81.9 % (edge ~50–52°N, drawn dashed) |
| Pixels ≥ 2 / ≥ 9.1 / ≥ 35.5 µg/m³ (all 48 h) | 3.21 % / 0.05 % / 0.010 % | 1.09 % / 0.17 % / 0.020 % |
| Peak | 1,046 µg/m³ f25 at 37.64°N 119.59°W (Yosemite) | 661 µg/m³ f25 at 44.65°N 118.58°W (E Oregon) |
| A: drawn value within its 4 nearest model points (ecCodes lat/lon + k-d tree, 2,000 px) | 100.0 %; median diff 0.01, p95 0.34 | 100.0 %; median 0.02, p95 4.78 |
| A: saved frame colours = field categories | 100.000 % of 409,600 px | 100.000 % |
| B: monitors (permanent + temporary) | 179 (158 + 21) | 244 (241 + 3) |
| B: Spearman, all sites / smoke-affected sites | 0.13 / n = 4 (too few) | −0.30 / +0.36 (n = 5) |
| B: median measured − model | 4.3 µg/m³ (background the model lacks) | 2.8 µg/m³ |
| B: sites ≥ 35.5 either way | none | none |
| B: shift test (unshifted / best shifted / shifted median) | 0.13 / 0.19 / 0.11 | −0.30 / −0.19 / −0.31 |
| Figure | `smoke_research/checks/smoke_check_sierra.png` | `smoke_research/checks/smoke_check_pnw.png` |

Reading: geometry and colours are right (A); the monitors check on this clean evening cannot measure skill (almost no
site had smoke) but shows no place, time or unit error (no shift wins, the smoky sites rank the right way, values at
the plume monitor are the same order as measured: 35 measured / 17 modelled). The PNW −0.30 is logged in
`ANOMALY_LOG.md` (2026-09-28, smoke check B) with the rival explanations; re-run on a smoky day.

## RRFS: when and how to switch (decision 6)
- Status (SCN 26-48, update "aad"): RRFS v1 goes operational **2026-10-14 at 12Z** (or the next weekday that is not a
  critical weather day); NOMADS paths move from `rrfs/para/` to `rrfs/prod/` (a `rrfs/v1.0/` tree is already served).
  HRRR and RAP are **not retired**. RRFS runs 84 h at 00/06/12/18Z, 18 h otherwise; 3 km CONUS and 13 km North America
  output (`rrfs.tCCz.2dfld.{3km.fFFF.conus|13km.fFFF.na}.grib2` + `.idx`). The AWS prototype bucket
  (`noaa-rrfs-pds`, `rrfs_a/`) stopped updating 2026-08-12; no AWS real-time feed of the operational RRFS is announced.
- Switch when (all three): RRFS operational for ≥ 4 weeks without a rollback; a real-time copy on AWS NODD (NOMADS is
  one rate-limited host, and a hung host costs the job); a side-by-side of `smoke_check.py` (check B) shows RRFS at least
  as good as HRRR at the monitors.
- How: in `smoke.py` change `SRC` to the RRFS path, `RECORD` to the MASSDEN 8 m record chosen by its aerosol text
  (the 2dfld index labels several MASSDEN records), `HOURS` to 1…84 (or keep 48), and read the grid from the message
  (the Lambert code already takes every parameter from it; the 13 km North America grid is rotated lat-lon in some
  products: check `gridType` and add that projection if so). The 13 km grid would remove the PNW mask (decision 7).

## Column smoke (HMS) later: sketch (decision 5)
`https://services2.arcgis.com/C8EMgrsFcRFL6LrL/arcgis/rest/services/NOAA_Satellite_Smoke_Detection_(v1)/FeatureServer/0/query`
(`Satellite, Start, End_, Density`), polygons clipped to the window in the 15-minute job, written only when changed;
a "Smoke seen from satellites (may be aloft)" layer with hatched light/medium/heavy fills.

## Testing
- pytest (network blocked), `tests/test_smoke.py`: index parsing (middle and last record, missing record); the Lambert
  forward and inverse against the corner coordinates from the real message; window coordinates; bilinear resample of
  a linear test field (exact) and NaN outside; category image at every edge (1.99/2.0, 9.0/9.1, 35.4/35.5, 55.4/55.5,
  125.4/125.5, 225.4/225.5, NaN); series encoding (block means, -1 for NaN blocks, hour-major order); model edge
  inside the PNW window and none in Sierra; newest-complete-run selection (too young, not posted, fallback); slot
  alternation; build writes frames, series, `smoke.js` and state; unchanged run writes nothing; a failed hour aborts
  without touching `smoke.js` or the state; missing or stale remote `smoke.js` triggers a rebuild; decode of a small
  Lambert GRIB2 message made with ecCodes (skipped if ecCodes is missing).
- node, `tests/test_map_smoke.py` on a `// BEGIN smokeHelpers` block: category of a µg/m³ value at each edge; hours
  shown from now; start index keeping a valid time; labels; series sampling (cell index, nodata, outside the window);
  reload after 30 min.
- Local build in the in-app browser against live R2 plus this PC's `smoke.js` and frames (`smoke_research/smoke_serve.py`):
  layer, player, badge, legend, click value and curve, PNW edge line, phone width, no console errors;
  `node --check` on the page script.

## Parameter ledger
| Parameter | Value | Source | Where |
|---|---|---|---|
| Field | `MASSDEN` 8 m above ground (cat 20, par 0), kg/m³ × 1e9 → µg/m³ | HRRR wrfsfc index; ecCodes decode 2026-09-29 | smoke.py |
| Runs used | 00/06/12/18Z, f01–f48 | Chris (decision 2); f00 left out: always ≥ 2 h past when posted (**judgment call**) | smoke.py |
| Run is complete | its f48 index exists | **judgment call** | smoke.py |
| Earliest check | run + 1 h 40 min | f48 posted 1 h 49 min after the 18Z run, 2026-09-29 | smoke.py |
| Floor | < 2 µg/m³ transparent | **judgment call** (decision 4) | smoke.py, map.html |
| Light-smoke band | 2 – 9.0 µg/m³, rgb(150,140,128), alpha 110/255 | **judgment call** | smoke.py, map.html |
| Category edges | 9.1, 35.5, 55.5, 125.5, 225.5 µg/m³ | EPA PM2.5 AQI breakpoints, May 2024 (`airquality.PM25_BP`) | smoke.py, map.html |
| Category colours | AirNow's (`airquality.AQ_COLORS`), alpha 255 | AirNow guideline (phase 1) | smoke.py, map.html |
| Overlay opacity | 0.65 default, slider 0.2–1 | **judgment call** | map.html |
| Interpolation | bilinear on the model grid, NaN outside | **judgment call** (nearest shows 3 km blocks) | smoke.py |
| Frame size | 640 × 640 px, lossless WebP | measured: 0–3 KB, smaller than lossy q80 | smoke.py |
| Value cells | 128 × 128 block means (~9–12 km), integer µg/m³ | **judgment call** (decision 10) | smoke.py, map.html |
| Hours shown | valid time > now − 30 min | **judgment call** (decision 11) | map.html |
| Reload | `smoke.js` every 30 min while on | freezing-level pattern | map.html |
| Loop speed | 400 ms a frame, 1.6 s pause on the last | **judgment call** (radar bar default 500 ms) | map.html |
| Fetch budget | 240 s per region step | **judgment call** (hourly job: 45 min timeout, runs 13–25 min) | smoke.py |

## Out of scope
HMS column smoke (sketch above), ECCC RAQDPS for BC, RRFS, the HRRR-fused AQI surface, smoke outlooks and blog
feeds, vertically integrated smoke (`COLMD`), visibility.
