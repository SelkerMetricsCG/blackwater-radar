# Smoke forecast layer (HRRR) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A 48-hour HRRR near-surface smoke loop in the map's Smoke & fires section, with click-anywhere values and a curve.

**Architecture:** New job module `smoke.py` in the hourly job builds frames and one value file per new HRRR run into
alternating slots; `map.html` gets a layer with its own player. Same patterns as `freezing.py` (window grid, value
grids) and `fires.py` (shared request helpers, state file, check and serve scripts).

**Tech Stack:** Python 3.12 (numpy, scipy `map_coordinates`, Pillow WebP, ecCodes), Leaflet page, pytest, node.

**Spec:** `docs/superpowers/specs/2026-09-28-hrrr-smoke-layer-design.md` (decisions 1–12, ledger).

**Execution (Chris's brief, 2026-09-28):** no review stops. Native execution by Claude in worktree
`C:\Users\16035\Desktop\BlackwaterLabs\radar-smoke` (branch `smoke` from `a545b31`); a fresh reviewer subagent checks
each task's diff before the next starts (per-task review stays on). Tests: `C:\Users\16035\anaconda3\python.exe -m pytest tests/ -q`
with `PYTHONIOENCODING=utf-8`. Stage only named files, never `git add -A`.

## Global Constraints
- Requests: plain Chrome User-Agent (`airquality.UA`), never Chris's name or email; 30 s timeouts; `airquality._open` hung-host rule.
- No `capture_all()` or `cloud.py` runs locally (they upload to the live bucket).
- `values`-style outputs must cover the full window (5 × 5 tiles); the smoke series is its own format (128 × 128 × 48).
- New page layers load only when switched on; the radar preload at open must not wait on them.
- `DEF_CHECKS` / `DEF_RANGES` get the new controls; defaults off (no `migrateDefault` entry needed).
- Ages and "hours ahead" on the page are computed from valid times and the viewer's clock, never baked in by the job.
- R2 writes: ≤ 51 per new run per region (spec, "R2 writes").

## Review Focus
1. A run whose f48 index exists but one middle hour is missing or truncated (not `GRIB`, short body): the build must abort and leave the map on the previous run — test `test_build_failed_hour_keeps_previous`.
2. Two slots: after a skipped run (06Z shown, 12Z never built, 18Z arrives) the new run must still go to the slot not in use — test `test_slot_is_the_one_not_in_use`.
3. The page open for hours: the run gets old while the tab is open; hours already past must drop out of the player on reload and the badge must never show a past hour as "now" — node test `smokeHours` with `now` past several hours.
4. PNW clicks north of the model edge: the popup must say "outside the HRRR model", not "0 µg/m³" — node test on `smokeAt` nodata, and the series encoder's -1 for NaN blocks.
5. The upload failed after a build (state says built, R2 lacks the new `smoke.js`): the next hour must rebuild — test `test_build_rebuilds_when_remote_is_stale`.

---

### Task 1: `smoke.py` pure helpers (grid, resample, images, series, edge)

**Files:**
- Create: `smoke.py`
- Test: `tests/test_smoke.py`

**Interfaces (produced):**
- `idx_range(idx_text: str, record: str) -> tuple[int, int|None] | None` — byte range of the first line containing `record`; end is the next record's start − 1, `None` for the last record.
- `Grid` = dict with `ni, nj, lat1, lon1, lov, latin, dx, radius` (floats/ints).
- `lcc_ij(grid, lat, lon) -> (fi, fj)` numpy arrays; `lcc_latlon(grid, fi, fj) -> (lat, lon)` (lon in −180..180).
- `window_latlon(size=640) -> (lat[size], lon[size])` pixel-centre coordinates of the region window.
- `resample(field[nj, ni], grid, size=640) -> float32[size, size]` bilinear, NaN outside.
- `category(ug) -> int array` −1 transparent, 0 light, 1..5 Moderate..Hazardous; `frame_rgba(ug) -> uint8[size, size, 4]`.
- `series_blocks(ug640, n=128) -> int array[n, n]` block means rounded to int, −1 where the block is all NaN.
- `edge_segments(grid) -> list[list[[lat, lon]]]` model boundary inside `region.bbox()`.

- [ ] Step 1: failing tests — `idx_range` (record 2 of 3 → `(100, 199)`; last → `(200, None)`; missing → `None`); `lcc_ij` at the message's corners (`(21.138123, 237.280472)` → (0, 0); `(47.839, -134.095)` → (0, 1058) within 0.05; `(47.842, -60.917)` → (1798, 1058)); `lcc_latlon(lcc_ij(x)) == x` to 1e-6°; `window_latlon` first/last centres inside `region.bbox()` and monotone; resample of `field = i + 1000 j` equals `fi + 1000 fj` at interior pixels (1e-3) and NaN for a pixel outside; `category` at 1.99, 2.0, 9.0, 9.09, 9.1, 35.4, 35.5, 55.4, 55.5, 125.4, 125.5, 225.4, 225.5, NaN → `[-1, 0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, -1]`; `frame_rgba` alpha 0 below the floor, 110 in the light band, 255 above; `series_blocks` of a 640 array with one NaN block and a known block mean; `edge_segments` non-empty with all points north of 49°N for pnw, empty for sierra (monkeypatch `region.KEY`).
- [ ] Step 2: run, expect import failure.
- [ ] Step 3: implement (Lambert: tangent cone, `n = sin(latin)`, `F = cos(latin) tan^n(π/4 + latin/2) / n`, `rho = R F / tan^n(π/4 + φ/2)`, `x = rho sin(n Δλ)`, `y = −rho cos(n Δλ)`, offsets from the first point, `/ dx`; inverse by `rho = sign(n) sqrt(x² + y²)`, `φ = 2 atan((R F / rho)^(1/n)) − π/2`, `λ = lov + atan2(x, −y) / n`).
- [ ] Step 4: tests pass.
- [ ] Step 5: commit `smoke.py: grid, resample, frames, series and model edge helpers`.

### Task 2: `smoke.py` fetch, decode, run choice, build; job wiring

**Files:**
- Modify: `smoke.py`, `capture.py` (hourly block after freezing), `cloud.py` (`STATE_FILES` += `smoke_cache.json`, docstring), `r2sync.py` (`"smoke"` in the overwritten-map folders, docstring)
- Test: `tests/test_smoke.py`

**Interfaces (produced):**
- `fetch_range(url, start, end) -> bytes` (Range request via `airquality._open`; 206 or 200; body must start with `b"GRIB"`, else `RuntimeError`; runner cache keyed by url+range).
- `decode(msg: bytes) -> (ug[nj, ni] float32, grid)`; raises unless `gridType == "lambert"` and `Latin1 == Latin2`.
- `latest_run(now: datetime) -> datetime | None` (UTC, synoptic, ≥ 1 h 40 min old, f48 idx exists, ≤ 30 h back).
- `load_store() / save_store(s)`; state keys `v, run, slot, built_t`.
- `build(log=print, now=None) -> str` (short status for `capture.py`'s cycle line).
- Outputs: `frames/smoke/<slot><hh>.webp`, `data/values/smoke_<slot>.js`, `data/smoke.js` (`window.SMOKE`), `data/smoke_cache.json`.

- [ ] Step 1: failing tests with `fetch`/`fetch_range`/`decode` monkeypatched: `test_latest_run_skips_young_and_unposted`; `test_slot_is_the_one_not_in_use`; `test_build_writes_frames_series_js_and_state` (48 frames, series header and length 48·128·128, `SMOKE.hours[0].t == run + 3600`, `file` has `?v=`, state advanced); `test_build_same_run_writes_nothing`; `test_build_failed_hour_keeps_previous`; `test_build_rebuilds_when_remote_is_stale` (`r2sync.REMOTE` with an old `smoke.js` time); `test_fetch_range_rejects_non_grib`; `test_decode_lambert_message` (ecCodes: `GRIB2` sample set to template 3.30 with a 4 × 3 grid; `importorskip`).
- [ ] Step 2: run, expect failures.
- [ ] Step 3: implement; wire `capture.py` (`ok.append("smoke %s" % smoke.build(log))` in a try/except like its neighbours), `cloud.py`, `r2sync.py`.
- [ ] Step 4: full suite passes.
- [ ] Step 5: commit `smoke.py: HRRR MASSDEN fetch and build into alternating slots; hourly job, state file, r2 folder`.

### Task 3: data check and preview server (no stop)

**Files:**
- Create: `smoke_research/smoke_check.py`, `smoke_research/smoke_serve.py`

- [ ] Step 1: `smoke_check.py <region>`: runs `smoke.build()` (no r2sync), prints the accounting line, check A (2,000 random pixels vs ecCodes lat/lon + `cKDTree` nearest point), check B (AirNow HourlyAQObs + AirFire latest for the analysis hour; f00 fetched here only; Spearman, median residual, ≥ 35.5 lists, shifted-field test), and saves the three-panel figure with `plt.style.use('matlab')`.
- [ ] Step 2: run for sierra and pnw (and ne as the clean case); record numbers; anything physically odd → `ANOMALY_LOG.md` with rival explanations. If the check shows a unit, place or time error, fix Task 1/2 first.
- [ ] Step 3: `smoke_serve.py` (fires_serve pattern, port 8797): serves `web/index.html` and local `smoke.js`, `frames/smoke/*`, `data/values/smoke_*.js` for the region, everything else proxied from live R2.
- [ ] Step 4: commit `smoke_research: smoke data check and preview server`.

### Task 4: the page

**Files:**
- Modify: `map.html` (panel HTML in Smoke & fires; `// BEGIN smokeHelpers` block; overlay, player, badge, legend, edge line, click block, `applyData` bounds list, `DEF_CHECKS` += `lySmoke`, `DEF_RANGES` += `smokeOpacity`), `terms.html` (credit)
- Test: `tests/test_map_smoke.py`

**Interfaces (page helpers, pure):** `SMOKE_EDGES = [2, 9.1, 35.5, 55.5, 125.5, 225.5]`, `SMOKE_COLS` (6 colours), `SMOKE_NAMES`; `smokeCat(ug) -> -1..5`; `smokeHours(d, nowS) -> hours with t > nowS − 1800`; `smokeIndex(hours, keepT) -> int`; `smokeWhen(t, nowS) -> "in 14 h" | "now"`; `smokeAt(g, lat, lon, bounds) -> number[] | null` (null outside the window; values −1 kept as null entries); `smokeNeedsLoad(d, loadedAt, nowMs)`.

- [ ] Step 1: failing node tests for each helper at its edges (see Review Focus 3 and 4).
- [ ] Step 2: implement the block, then the layer code; `node --check` on the extracted script.
- [ ] Step 3: `terms.html` credit line.
- [ ] Step 4: full suite passes; commit `map.html: smoke forecast layer (player, badge, legend, model edge, click curve); terms credit`.

### Task 5: browser check, docs, release
- [ ] Copy `..\radar\web` into the worktree (gitignored), `python build_web.py`, run `smoke_serve.py`, check in the in-app browser: layer, play/step/slider, badge, legend, click value and curve (inside and north of the PNW edge), phone width, no console errors. Restart the server after every `build_web.py`.
- [ ] Docs: `CLAUDE.md` (smoke rule line, globals `SMOKE`, hourly table row, timeline), spec final numbers.
- [ ] Merge `smoke` into `main` in `../radar` (other sessions' uncommitted edits set aside with a tagged stash and restored), full tests, `build_web.py`; `git fetch`; if `origin/main` moved, merge it and re-test; hand Chris `git push origin <sha>:main` and `npx --yes wrangler deploy`; read his terminal; curl the live page and diff; read the first hourly runs' `smoke:` lines for all five regions; `HANDOFF.md` item 7; remove worktree and branch.
