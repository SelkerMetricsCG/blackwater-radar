# Surface currents flow layer: design (2026-10-13)

An animated particle-flow layer ("Windy-style") of modelled surface currents in the Coastal group, from NOAA's own
operational ocean models: **SSCOFS** (Salish Sea and Columbia River, FVCOM, 4 cycles a day at 03/09/15/21Z, 72 h) on its
regular 0.005° product, and **WCOFS** (West Coast shelf, ROMS, 1 cycle a day at 03Z, 72 h) on its regular 0.04° product,
read as surface slices over the CO-OPS OPeNDAP server so nothing larger than a few MB is ever downloaded. Chris chose
this (2026-10-13) over a home-built tide model as the first step; a home-built model would drop into the same renderer
and be scored against the 53 current-prediction stations already on the site.

Spike results (2026-10-13, `opendap.co-ops.nos.noaa.gov/thredds/dodsC/NOAA/SSCOFS/MODELS/<yyyy>/<mm>/<dd>/
sscofs.tHHz.<yyyymmdd>.regulargrid.fNNN.nc`, same pattern under `WCOFS`): variables `Latitude[ny][nx]`,
`Longitude[ny][nx]` (2-D but rectilinear), `Depth` (0, 1, 2, 4 m ...; index 0 is the surface), `u_eastward[time][Depth][ny][nx]`,
`v_northward` in m/s, `mask`, `Times` (ISO string), `time` (s since 2018-01-01 for SSCOFS, 2016-01-01 for WCOFS).
SSCOFS grid 1553 x 1519 over 44.37-52.13 N, -129.53 to -121.94 E; WCOFS 935 x 833 over 18.4-55.8 N, -145.4 to -112.1 E.
A surface slice of the Puget Sound sub-box at stride 2 (1 km) takes about 8 s plus 8 s of metadata per file; the
whole WCOFS window at stride 1 about 6 s. Sample values at 03Z on 10/14: Admiralty Inlet 1.3 m/s, Columbia bar 1.5 m/s
ebb, max 2.96 m/s in the sub-box. The DAP server returns an occasional "DAP server error"; retries are needed.
The AWS copies (`noaa-nos-ofs-pds`) are 1.7 GB (SSCOFS) and 580 MB (WCOFS) per hour: not used.

## 1. Scope
- One new layer in the Coastal group: **Surface currents (model)** with a time slider over the newest cycle's hours
  (0 to 24 h ahead, hourly), Play, and an opacity slider (Sun & shade idiom). Particles move with the current and
  are coloured by speed; a legend in knots. Click-anywhere adds "surface current now: 1.2 kt toward NW (NOAA SSCOFS
  model, Tue 4 PM)". Nothing else changes.
- Out of scope: 3-D or deeper layers, the home-built model, the 72 h horizon (24 h keeps a cycle fetch under 10 min).

## 2. Data module `currents.py` (hourly slot, after `sst`; `region.cfg().get("coastal")` only)
- Finds the newest SSCOFS cycle whose `regulargrid.f024.nc` is listed in the day's THREDDS catalog
  (`.../catalog/NOAA/SSCOFS/MODELS/<yyyy>/<mm>/<dd>/catalog.xml`, today then yesterday) and the newest WCOFS cycle
  likewise; skips when both match `currents_cache.json` (state file). A new cycle fetches f001..f024 for SSCOFS and
  f001..f024 for WCOFS (3 worker threads each, 20 s connect timeout, 2 tries per file; a cycle with any missing hour
  is abandoned and the previous one kept, like `smoke.py`).
- Each hour is composited onto one regular output grid: the region window at **0.01°** (pnw: 43.07-52.48 N,
  -126.56 to -112.5 E, 941 x 1406 cells; land and nodata outside both models). SSCOFS (stride 2 of its 0.005° grid,
  sub-box 46.0-50.2 N, -125.3 to -121.9 E) wins where it has a value; WCOFS (nearest cell of its 0.04° grid) elsewhere.
  Cells with no model value are nodata.
- Output per hour: `frames/currents/<cycle>/h<NN>.png` (RGB, no alpha, so canvas reads are exact): R = u, G = v as
  `round(cm/s / 2) + 128` clipped to 1..255 (so ±2.54 m/s; the Narrows and Deception Pass saturate at the peak, said in
  the note), B = 255 for a valid cell, 0 for nodata. About 100-200 KB each. Plus `data/currents.js` ->
  `window.CURRENTS = {cycle: "sscofs t15z 2026-10-13 + wcofs t03z", updated, updated_t, bbox: [lat0, lat1, lon0, lon1],
  nx, ny, step: 0.01, scale_cms: 2, hours: [{t: epoch s, file: "frames/currents/<cycle>/h01.png"}, ...], credit}`.
  Files are named by cycle so they never change (r2sync uploads frames immutable); old cycles are pruned from the
  local layout only (R2 keeps them for 30 h like scans, via the same prune rule on `frames/currents/`).
- `requirements.txt` gains `netCDF4`.

## 3. Serving: `site_worker.js`
The bucket sends no CORS header and the page reads the PNG pixels, so, as for the DEM tiles, the Worker proxies
`/<region>/currents/<cycle>/h<NN>.png` from R2 with `Cache-Control: public, max-age=31536000, immutable`
(a missing file: 404, 5-min cache). `tests/test_site_worker.py` covers the new route.

## 4. Page
- Layer `lyCurrents` in the Coastal group, after SST: slider (`curSlider`, hour index), Play (steps every 0.8 s),
  opacity, `curInfo` with the hour label ("Tue 4 PM, SSCOFS t15z + WCOFS t03z"), the knots legend
  (0, 0.5, 1, 1.5, 2, 3+ kt; muted blue to amber) and the note with credit ("NOAA CO-OPS SSCOFS and WCOFS operational
  forecast models, surface layer; 1 km in the Sound and Columbia, 4 km on the shelf; speeds above 4.9 kt are capped").
- Renderer: a Leaflet canvas layer in the overlay pane (`L.Layer` subclass, one `<canvas>` resized with the map,
  redrawn on `moveend`/`zoomend`). The hour's PNG is decoded once into `Uint8ClampedArray` via an offscreen canvas;
  `sampleUV(lat, lon)` is bilinear between valid cells (nodata cells excluded). Particles: count scales with the
  visible area (2,000 at zoom 7 to 6,000 at zoom 12, capped), positions in lat/lon, advanced each animation frame by
  `(u, v) * dt` with `dt` such that 1 m/s moves about 1.5 px per frame at the current zoom; a particle respawns at a
  random visible water cell after 60-120 frames or when it leaves the water. Trails: the canvas is faded each frame
  (`globalAlpha` 0.92 composite of itself) and new segments drawn on top, line width 1.2 px, colour by speed from the
  legend bins. Paused (no animation loop) while the layer is off or the page is hidden (`visibilitychange`).
- Click-anywhere: a "Surface current" row from `sampleUV` at the slider's hour (or hour 0 when the layer is off but
  data is loaded): speed in knots to one decimal, direction "toward <compass>", the model and valid time.
- Pure helpers in `// BEGIN currentsHelpers`: `decodeUV(r, g, b, scale) -> [u, v] | null`, `bilinearUV(grid, x, y)`,
  `speedBin(kt)`, `CUR_BINS`, `particleCount(zoom)`, `stepPx(zoom, lat)`.
- `lyCurrents` joins `DEF_CHECKS`; the slider position is not saved.

## 5. Judgment calls (ledger, none approved yet)
| # | Decision | Value | Why |
|---|---|---|---|
| 1 | Output grid | 0.01° over the window | SSCOFS at stride 2 is 1 km; finer costs 4x fetch time; 1 km resolves the main channels, not Deception Pass |
| 2 | Hours per cycle | 24 | two tide cycles ahead; 16 s per hour per model over DAP |
| 3 | Encoding | uint8 u, v at 2 cm/s, cap ±2.54 m/s; B channel mask | canvas-exact without alpha; 1 % of cells saturate at peak flood in the Narrows |
| 4 | Model precedence | SSCOFS over WCOFS | the Salish Sea model resolves the inland water; WCOFS has no Sound |
| 5 | Particle look | fade 0.92, 1.2 px, 2-6k particles, 1 m/s = 1.5 px/frame | reads like Windy at the site's zooms; tunable constants |
| 6 | Knots legend | 0, 0.5, 1, 1.5, 2, 3+ kt | small-craft relevance: 1 kt matters to a paddler, 3 kt to a kiter's drift |
| 7 | Cycle selection | newest with f024 listed; both models independent | a half-posted cycle is never shown |
| 8 | Land mask (2026-10-15) | GSHHG full-resolution shoreline rasterised on the 0.01° grid, centre-in-polygon; particles die on a land cell | WCOFS's 4 km cells reached ~2 mi inland (Chris, 2026-10-15); 5.1 % of the live frame's water cells were on land; residual overlap is at most half a cell (~0.35 mi) |

## 6. Tests
- `tests/test_currents.py`: cycle parsing from a catalog XML fixture; compositing with two small synthetic NetCDF files
  written by the test (netCDF4, in `tmp_path`): SSCOFS-wins rule, nodata, encoding round-trip (`decode(encode(u)) == u`
  within 1 cm/s), saturation, output index shape; the "unchanged cycle" early exit (fetch monkeypatched to raise).
- `tests/test_site_worker.py`: the currents route and the 404 path.
- `tests/test_map_currents.py` (node): `decodeUV` at 128/128 -> 0, saturation, nodata; `bilinearUV` on a 2x2 cell;
  `speedBin` edges; `particleCount` bounds.
- Checks (`coastal_research/CHECKS.md`): the module's value at Admiralty Inlet and the Columbia bar against the
  OPeNDAP values above; the particle direction at a passage against the CO-OPS current prediction's flood or ebb
  at that hour (the site's own Tides & currents layer).
