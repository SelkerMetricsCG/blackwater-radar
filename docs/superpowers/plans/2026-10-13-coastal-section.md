# Coastal Section Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A "Coastal" group in the radar map (pnw) with buoys and shore stations, tides and tidal currents, NWS marine and surf-zone forecasts, and a satellite sea-surface-temperature overlay, fed by free public sources on the existing Actions and R2 pipeline.

**Architecture:** Four new Python modules (`buoys.py`, `tides.py`, `marine.py`, `sst.py`) follow the shape of `rivers.py` / `airquality.py` / `snodas.py`: `build(log)` fetches, parses, writes `data/<name>.js` (`window.<NAME> = {...}`), returns a count; `capture.py` calls them in the half-hour and hourly slots when the region has `coastal`. `map.html` gets one new panel group with four layers, a `// BEGIN coastalHelpers` block of pure functions, and click-anywhere rows. `alerts.py` adds marine (`PZ`) zones clipped to the window.

**Tech Stack:** Python 3.12 (urllib, json, csv, xml.etree, numpy, Pillow; nothing new in `requirements.txt`), Leaflet page, pytest with the network blocked (`tests/conftest.py`), node for the page helper tests.

**Spec:** `docs/superpowers/specs/2026-10-13-coastal-section-design.md` (read it first; sources and endpoints are in `coastal_research/CATALOG.md` and the per-topic files there).

## Global Constraints

- Free tier only; no key-gated or paid source; no scraping where terms forbid it (spec §5 lists the endpoints).
- Every fetch: `User-Agent: RadarTracker/1.0 (personal weather map)` (api.weather.gov calls use the existing `alerts.UA`), timeout 20 s, 2 tries, skip a host for the rest of the run after a timeout (`airquality.HostDown` pattern). **No name or email in any header, URL or payload.**
- Units in the output files: feet, mph, °F, mb, knots for currents; epoch seconds for times; `updated` string as `dt.datetime.now().strftime("%a %b %d %I:%M %p")` and `updated_t = int(time.time())` like `alerts.py`.
- Output written atomically (`.tmp` then `os.replace`), compact JSON (`separators=(",", ":")`).
- A module runs only when `region.cfg().get("coastal")`; otherwise `build()` returns 0 without fetching.
- Tests never touch the network: fixtures are short real excerpts saved under `tests/fixtures/coastal/`.
- Work in the worktree branch `coastal`; do not commit (the session lead commits after each task). Do not modify files outside the task's list.

## Review Focus

1. NDBC `latest_obs.txt` rows with `MM` in every wave column for the 3 m buoys: the station must still appear with wind and water temperature, and waves must come from `realtime2/<id>.txt` (Task 2 test `test_latest_obs_mm_waves_filled_from_history`).
2. A CO-OPS subordinate tide station answers `interval=hilo` only; a 6-minute request errors. The page must still draw a curve (Task 3 `test_hilo_only_station_has_no_obs`, Task 6 node test of `tideAt`).
3. Highs and lows that straddle midnight UTC or a DST change: `hilo` times are requested in `time_zone=gmt`, converted once to epoch seconds, never re-parsed as local (Task 3 `test_hilo_times_are_utc_epoch`).
4. A marine zone whose first period has no parseable wind ("Variable winds less than 10 kt" or "Light winds"): `wind_kt_max` null, grey polygon, no exception (Task 4 `test_period_parse_variants`).
5. SST CSV with the grid's latitude running north-to-south or south-to-north: the raster must come out north-up either way (Task 5 `test_grid_orientation`).

---

### Task 1: Plumbing: region flag, job slots, state file, page flag, marine alerts

**Files:**
- Modify: `region.py` (pnw: add `"coastal": True, "marine_cwa": ["SEW", "PQR", "MFR", "EKA"]`)
- Modify: `build_web.py` (regions[key]["coastal"] = bool(c.get("coastal")))
- Modify: `capture.py` (half-hour slot after `rivers`: `buoys`, `tides`; hourly slot after `forecast`: `marine`; after `snodas`: `sst`; each in its own try/except like the others, logging `<name> FAILED`)
- Modify: `cloud.py` (`STATE_FILES` += `"tides_cache.json"`; docstring line listing the new hourly/half-hour outputs)
- Modify: `alerts.py` (URL area adds `,PZ` when `region.cfg().get("coastal")`; drop a feature whose every geometry bbox lies outside `region.bbox()`)
- Create: `tests/test_alerts.py`

**Interfaces:**
- Produces: `alerts.in_window(geometry, bbox) -> bool` (bbox = `(lat0, lat1, lon0, lon1)` as `region.bbox()` returns); `alerts.URL` built by `alerts.alert_url(states, coastal) -> str`.

- [ ] **Step 1: Write the failing tests** in `tests/test_alerts.py`:

```python
def test_alert_url_adds_marine_area_for_coastal_regions():
    assert alerts.alert_url(["WA", "OR"], True).split("area=")[1].split("&")[0] == "WA,OR,PZ"
    assert "PZ" not in alerts.alert_url(["UT", "CO"], False)

def test_in_window_drops_a_polygon_wholly_outside():
    bbox = (41.0, 49.7, -126.6, -112.5)
    inside = {"type": "Polygon", "coordinates": [[[-124.5, 46.0], [-124.0, 46.0], [-124.0, 46.5], [-124.5, 46.0]]]}
    outside = {"type": "Polygon", "coordinates": [[[-123.0, 37.0], [-122.5, 37.0], [-122.5, 37.5], [-123.0, 37.0]]]}
    assert alerts.in_window(inside, bbox) and not alerts.in_window(outside, bbox)
```

- [ ] **Step 2: Run** `python -m pytest tests/test_alerts.py -v` — expected: FAIL (no `alert_url`).
- [ ] **Step 3: Implement** `alert_url` and `in_window` (bbox overlap of the geometry's coordinate extent, any depth of nesting), use them in `build()` (filter after zone geometry lookup, so land-zone alerts are unaffected), and make the other edits listed above. In `capture.py` keep the existing style: `import buoys; ok.append("buoys %d" % buoys.build(log))`.
- [ ] **Step 4: Run** `python -m pytest tests/test_alerts.py tests/test_map_defaults.py -v` — expected: PASS.
- [ ] **Step 5:** Tell the lead the task is done (no commit).

### Task 2: `buoys.py`

**Files:**
- Create: `buoys.py`, `tests/test_buoys.py`, `tests/fixtures/coastal/latest_obs_excerpt.txt`, `46041.txt` (last 30 rows), `46041.spec` (last 10 rows), `cdip_wave_agg.csv`, `eccc_4600206.xml`, `nanoos_chaba_met.json`, `nanoos_byb_quileute.json`, `coops_wind_9441102.json`, `coops_wtemp_9441102.json`.
- Read first: spec §3 (`BUOYS` shape), §5, §6 rows 1-3; `coastal_research/waves_buoys.md` §1-3 (station table, endpoints, the `MM` caveat, the ECCC period caveat); `coastal_research/nanoos_ioos.md` §1 (dataset ids and columns); `rivers.py` and `airquality.py` for style.

**Interfaces:**
- Produces: `buoys.build(log=print, now=None) -> int` (stations written); `buoys.parse_latest_obs(text, bbox) -> dict[id, record]`; `buoys.parse_realtime(text) -> list[dict]` (rows newest first, keys `t, hs_ft, dpd_s, apd_s, mwd_deg, wspd_mph, gust_mph, wdir_deg, wtmp_f, atmp_f, pres_mb`); `buoys.parse_spec(text) -> dict` (newest row: `swh_ft, swp_s, swd_deg, wwh_ft, wwp_s, wwd_deg, steep`); `buoys.parse_cdip(csv_text) -> dict[cdip_id, {t, hs_ft, dpd_s, mwd_deg, apd_s}]`; `buoys.parse_swob(xml_text) -> dict`; `buoys.parse_erddap(json_text, mapping) -> dict`; `buoys.merge(...) -> list[station]`; constants `STALE_H = 6`, `DROP_H = 24`, `CDIP_RELAY = {"036": "46211", "162": "46243", "179": "46248", "248": "46267", "270": "46278", "139": "46229"}`, `ECCC_IDS = {"4600206": "46206", "4600146": "46146", "4600304": "46304"}`.

- [ ] **Step 1:** Fetch the fixtures once with curl (they are the only network use in this task; keep them short) and write the failing tests:

```python
def test_latest_obs_window_filter_and_units(): ...        # 46041 inside, a California id outside; m -> ft, m/s -> mph, C -> F
def test_latest_obs_mm_waves_filled_from_history(): ...   # 46041 row has WVHT MM; after merge with parse_realtime(46041.txt) hs_ft is the :50 row's value
def test_realtime_rows_newest_first_and_trace_24h(): ...  # trace has 24 slots, hourly, None where the hour is missing
def test_spec_swell_split(): ...                          # SwH/SwP/SwD/WWH/WWP/WWD/STEEPNESS parsed; MM -> None
def test_cdip_overwrites_relay_direction(): ...           # CDIP Dp replaces the NDBC relay mwd_deg for 46211; credit "Data courtesy of CDIP"
def test_eccc_swob_period_and_direction(): ...            # Tp and peak direction from the XML, not NDBC's; credit line
def test_nanoos_and_byb_records(): ...                    # Cha'ba wind/SST; Quileute Center Hs/Tp/SST; BYB credit text exact
def test_coops_wind_and_wtemp_station(): ...              # src "COOPS", kt -> mph
def test_stale_and_drop(): ...                            # 7 h old -> stale True; 25 h old -> dropped
def test_output_shape(tmp_path, monkeypatch): ...         # build() with fetch monkeypatched to fixtures writes window.BUOYS with updated, updated_t, stations
```

- [ ] **Step 2: Run** `python -m pytest tests/test_buoys.py -v` — expected: FAIL (module missing).
- [ ] **Step 3: Implement `buoys.py`.** Fetch order: station table (names, owners; cached in memory per run), `latest_obs.txt`, then `realtime2/<id>.txt` for every station in the window that reports any wave column or is a CDIP relay (also `.spec`, 404 tolerated), CDIP CSV, the three SWOB-ML latest files (list the day's directory, take the newest file for each id), NANOOS ERDDAP datasets (`chaba_met_all`, `chaba_hydro`, the six `backyardbuoys_*`, ORCA/PISCES/Se'lhaem met datasets named in `nanoos_ioos.md`), CO-OPS `wind` and `water_temperature` `date=latest` for the stations `tides.py` lists as having those sensors (read `tides_cache.json` if present; otherwise the CO-OPS metadata call). Write `data/buoys.js`. Log `buoys: N stations, W with waves, S stale, F failed hosts`.
- [ ] **Step 4: Run** `python -m pytest tests/test_buoys.py -v` — expected: PASS. Then `python buoys.py` once from the worktree (REGION=pnw) and report the log line and three sample stations (46041, 46211, Cha'ba) to the lead.
- [ ] **Step 5:** Done (no commit).

### Task 3: `tides.py`

**Files:**
- Create: `tides.py`, `tests/test_tides.py`, fixtures `coops_stations_waterlevels.json` (3 stations), `coops_stations_tidepredictions.json` (3, one subordinate), `coops_stations_currentpredictions.json` (2), `coops_hilo_9439040.json`, `coops_wl_9447130.json`, `coops_maxslack_PUG1701.json`, `chs_stations.json` (3), `chs_wlp_hilo.json`, `chs_wlo.json`, `chs_wcp1_events.json`.
- Read first: spec §3 (`TIDES` shape), §5, §6 rows 4, 5, 9, 10; `coastal_research/tides_currents_sst.md` §1-2 (endpoints, station tables, the subordinate-station rule, datums, units, throttling note).

**Interfaces:**
- Produces: `tides.build(log=print, now=None) -> int`; `tides.parse_coops_stations(json_text, kind, bbox) -> list[meta]`; `tides.parse_hilo(json_text) -> list[[epoch, ft, "H"|"L"]]`; `tides.parse_wl(json_text) -> list[[epoch, ft]]`; `tides.parse_maxslack(json_text) -> list[[epoch, kind, kt]]`; `tides.parse_chs_*` equivalents (metres -> feet, chart datum kept as `datum: "CD"`); `tides.refresh_plan(cache, now, limit=60) -> list[station ids]`; `tides.load_cache() / save_cache()` on `data/tides_cache.json` with `{"meta": {...fetched: epoch}, "pred": {id: {"day": "YYYY-MM-DD", "hilo": [...]}}, "cur": {...}}`.
- Consumes: nothing from other tasks; `buoys.py` reads this module's cache for CO-OPS sensor lists (meta records carry `sensors: ["wind", "wtemp"]`).

- [ ] **Step 1: Write the failing tests:**

```python
def test_coops_meta_window_and_sensors(): ...
def test_hilo_times_are_utc_epoch(): ...              # "2026-10-13 03:54" in gmt -> 1792000440; a value 2.22 m? no: units=english so ft kept as given
def test_hilo_only_station_has_no_obs(): ...          # subordinate: obs None, hilo present
def test_wl_last_12h_30min(): ...                     # 6-min rows thinned to every 30 min
def test_maxslack_events_kt(): ...                    # cm/s -> kt (x 0.019438), "slack" when Type == "slack"
def test_chs_metres_to_feet_and_datum(): ...
def test_refresh_plan_limits_and_prefers_stale(): ... # 100 stale stations, limit 60 -> 60 oldest first
def test_output_shape(tmp_path, monkeypatch): ...
```

- [ ] **Step 2: Run** `python -m pytest tests/test_tides.py -v` — FAIL.
- [ ] **Step 3: Implement `tides.py`.** Metadata: CO-OPS `stations.json?type=waterlevels&expand=sensors`, `?type=tidepredictions`, `?type=currentpredictions`, CHS `/stations` (filter to the window; a CHS station is kept when it has `wlp` or `wlo` time series; refresh metadata every 7 days). Predictions: `predictions&interval=hilo&units=english&time_zone=gmt&datum=MLLW&begin_date=<yesterday>&range=72` per station; CHS `wlp-hilo` from yesterday 00:00Z for 72 h; currents `currents_predictions&interval=MAX_SLACK&units=english&time_zone=gmt&bin=<first bin listed>` and CHS `wcp1-events`. Observations every run: `water_level&date=latest` plus `water_level&range=12` (thin to 30 min) for live stations; CHS `wlo` last 12 h. Sleep 0.2 s between CO-OPS calls (their page asks for sleeps). Write `data/tides.js`. Log `tides: N stations (L live), C current stations, R predictions refreshed, F failed`.
- [ ] **Step 4: Run** the tests, then `python tides.py` once (REGION=pnw) and report the log line plus Westport's next high and Deception Pass's next slack to the lead.
- [ ] **Step 5:** Done.

### Task 4: `marine.py`

**Files:**
- Create: `marine.py`, `tests/test_marine.py`, fixtures `nws_zones_coastal.json` (4 zones, two cwa), `nws_zone_PZZ150.json` (with geometry), `nws_zone_forecast_PZZ150.json`, `nws_products_srf_PQR.json`, `nws_product_srf.json`.
- Read first: spec §3 (`MARINE` shape), §5, §6 row 6; `coastal_research/waves_buoys.md` §4c (zone ids, SRF offices, the "list zones by id" caveat); `alerts.py` (`fetch`, `UA`, `zone_cache.json` use).

**Interfaces:**
- Produces: `marine.build(log=print) -> int`; `marine.parse_period(text) -> (wind_kt_max | None, seas_ft_max | None)`; `marine.zones_for(cwas, zones_json) -> list[meta]`; `marine.srf_text(product_json) -> (text, issued_epoch)`.

- [ ] **Step 1: Write the failing tests**, including `test_period_parse_variants` over these texts: "W wind 15 to 25 kt. Seas 6 to 8 ft.", "NW wind 10 kt becoming 20 kt in the afternoon. Seas 4 ft.", "Variable winds less than 10 kt.", "Light winds. Seas 2 ft or less.", "S wind 30 to 40 kt with gusts to 50 kt. Seas 12 to 15 ft." (expect 25/8, 20/4, None/None, None/2, 50/15: gusts count), plus `test_zones_filtered_by_cwa`, `test_zone_geometry_cached` (second call makes no fetch), `test_srf_latest_product`, `test_output_shape`.
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement `marine.py`**: `/zones?type=coastal` once per run, filter `cwa` by `region.cfg()["marine_cwa"]`, geometry from `/zones/forecast/<id>` cached in `data/zone_cache.json` under the zone URL (same file and key style as `alerts.py`), forecast from `/zones/forecast/<id>/forecast` (keep up to 6 periods: `name`, `detailedForecast` as `text`), SRF: `/products/types/SRF/locations/<cwa>` -> first `@graph` item -> `/products/<id>` -> `productText` (2,500 chars), for each cwa in the list (404 or empty = none). Coordinates rounded to 4 places (`alerts._round`). Log `marine: N zones, S surf-zone forecasts, F failed`.
- [ ] **Step 4: Run** tests; `python marine.py` once and report the zone count and which offices gave an SRF.
- [ ] **Step 5:** Done.

### Task 5: `sst.py`

**Files:**
- Create: `sst.py`, `tests/test_sst.py`, fixture `sst_excerpt.csv` (a 6x8 subset of the real CSV, with the header lines).
- Read first: spec §3 (`SST` shape), §5, §6 row 8; `coastal_research/tides_currents_sst.md` §3 (dataset ids, the `.das` check, latency); `snodas.py` (raster to webp, legend, `values.write_grid`), `freezing.py` or `airquality.resample` (window pixel space: `region.window()` / the 1280 px window used by `values`).

**Interfaces:**
- Produces: `sst.build(log=print) -> str | None` (the analysis date written, or None when nothing new); `sst.parse_csv(text) -> (lats, lons, grid_c)` with `grid_c` north-up `(nlat, nlon)` float32, NaN for nodata; `sst.to_window(lats, lons, grid_c) -> np.ndarray` in the full window pixel space (nearest neighbour), °F; `sst.colorize(arr_f) -> PIL.Image` (RGBA, transparent nodata); `SST_BINS` (°F, colour) per spec row 8.

- [ ] **Step 1: Write the failing tests:** `test_parse_csv_values_and_nan`, `test_grid_orientation` (feed the same rows in both latitude orders; `to_window` output identical), `test_colorize_nodata_transparent`, `test_legend_bins_match_colors`, `test_skips_when_date_unchanged` (`data/sst.js` already has the date: no fetch; monkeypatch fetch to raise).
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement `sst.py`:** read the dataset's `.das` once to find the time coverage end (or request `[(last)]`), compare with the date in the existing `data/sst.js`, fetch the CSV subset for the window when newer, parse, resample to the window, write `frames/sst/sst.webp` (lossless webp, like snodas), `data/values/sst.js` (`values.write_grid("sst", arr_f, unit="F", scale=0.1)`), `data/sst.js` with `date, file, min_f, max_f, legend`. Log `sst: analysis <date> (<n> cells, <min>-<max> F)` or `sst: unchanged <date>`.
- [ ] **Step 4: Run** tests; `python sst.py` once and report the date and range; compare the value at 46041's position with that buoy's water temperature from Task 2's run (note the difference for `CHECKS.md`).
- [ ] **Step 5:** Done.

### Task 6: `map.html`: the Coastal group, four layers, click-anywhere, defaults

**Files:**
- Modify: `map.html` (panel markup after the Water group; a `// ---------- Coastal ----------` script section after the rivers section; `// BEGIN coastalHelpers ... // END coastalHelpers`; click-anywhere rows after the "Nearest gauge" block; `DEF_CHECKS` and explicit `buoyMode` save/restore next to `stMode`; hide the group when `!REG.coastal`).
- Create: `tests/test_map_coastal.py`; Modify: `tests/test_map_defaults.py` (assert the four ids are in `DEF_CHECKS` by reading the file).
- Read first: spec §4 and §6; the rivers section (chart + tracker, `renderRivers`, `loadRivers`, the 15-min reload), the stations section (modes, `windIcon`, labels from zoom), the SNODAS section (image overlay), `legendHtml`, `esc`, `nearest`, `sample/getGrid`; the sun & shade section for how a layer is hidden per region.

**Interfaces:**
- Consumes: `window.BUOYS`, `window.TIDES`, `window.MARINE`, `window.SST`, `data/values/sst.js` (Tasks 2-5 shapes, spec §3).
- Produces (inside `coastalHelpers`, pure, no DOM): `tideAt(hilo, t) -> ft | null` (cosine between the bracketing extremes; null outside), `tideStage(hilo, t) -> {dir: "rising"|"falling"|"slack", next: [t, ft, "H"|"L"], mins: n}`, `currentAt(events, t) -> {kind, kt}`, `waveBin(ft)`, `tempBin(f)`, `windBinKt(kt)`, `compass(deg) -> "NW"`, `fmtAge(sec)`, `WAVE_BINS`, `TEMP_BINS`, `ZONE_BINS`.

- [ ] **Step 1: Write the failing node tests** in `tests/test_map_coastal.py` (same harness as `test_map_airquality.py`, block name `coastalHelpers`): `tideAt` equals the extremes at their times and the mean at the midpoint; `tideStage` says rising with `mins` to the next high; slack within 20 min; `currentAt` interpolates kt between a slack and a max; bins at every edge; `compass(292.5) == "WNW"`; `fmtAge`.
- [ ] **Step 2: Run** `python -m pytest tests/test_map_coastal.py -v` — FAIL (block missing).
- [ ] **Step 3: Implement** the markup, helpers and the four layers per spec §4 (`lyBuoys` with chips `buoyMode` waves/wind/wtemp; `lyTides`; `lyMarine`; `lySst`), each with `load<Name>()` via `loadScript`, a `render<Name>()`, the `onchange` wiring, a 15-min reload while on, the panel info/legend/note (credits per spec §4), labels from zoom 8 using the station-layer label pattern, popups with the cards described in the spec. Hide the whole group when `!REG.coastal`. Click-anywhere rows per spec §4 (radii 60 and 40 km). Add the ids to `DEF_CHECKS`; save and restore `buoyMode` like `stMode`.
- [ ] **Step 4: Run** `python -m pytest tests/test_map_coastal.py tests/test_map_defaults.py tests/test_map_airquality.py -v` — PASS. Then a local check: build a scratch `index.html` (the lead supplies the script), serve it, open in the in-app browser: four layers draw, popups open, no console errors, phone width. Report what you saw with a screenshot path.
- [ ] **Step 5:** Done.

### Task 7: Webcams

**Files:**
- Modify: `webcams_youtube.json` (add the 18 streams and refresh the 4 ids from `coastal_research/webcams.md` table A: `key`, `name`, `kind: "water"`, `lat`, `lon`, `video`, `channel` when known, `match`, `owner`, `page`), `webcams_extra.json` (Yaquina Bay bar still, Point Roberts marina still; Kalaloch `img` fixed; Cannon Beach CBCC entry removed).
- Test: `python -m pytest tests/test_webcams.py tests/test_youtube.py -v` (existing); `python cams_research/youtube_enrich.py` from the main checkout if `youtube.env` is present (the lead runs it; it needs the key).

- [ ] **Step 1:** Make the JSON edits; keep the file's existing field names and ordering; one entry per camera; `off` entries untouched.
- [ ] **Step 2: Run** the two test files — PASS; `python -c "import json; json.load(open('webcams_youtube.json')); json.load(open('webcams_extra.json'))"`.
- [ ] **Step 3:** Done.

### Task 8: Docs, checks and release

**Files:**
- Modify: `CLAUDE.md` (a "Coastal" paragraph under Rules: modules, cadence, credits and licences, the no-personal-data header rule, where the research lives; two timeline lines), `coastal_research/HANDOFF.md`.
- Create: `coastal_research/CHECKS.md` (the independent checks from spec §7 with the values seen and the source page's values, dated).

- [ ] **Step 1:** Full suite `python -m pytest tests/ -q` green in the worktree.
- [ ] **Step 2:** Lead: ff-merge `coastal` into `main`, `python build_web.py`, local browser check of `web/index.html`, hand Chris the push, wait for the first runs, check R2 for `pnw/data/buoys.js`, `tides.js`, `marine.js`, `sst.js`, then hand Chris the deploy and diff the live page.
- [ ] **Step 3:** Record the checks in `CHECKS.md`; update `HANDOFF.md` to the finishing commit and the open items (deferred list from spec §1, judgment calls awaiting Chris).
