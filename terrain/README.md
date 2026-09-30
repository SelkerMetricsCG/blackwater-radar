# Sun & shade layer (WA Cascades)

The map's Terrain → **Sun & shade** layer: for any date and a 05:00-22:00 Pacific slider, the page darkens ground in
terrain shade (cast by terrain out to 25 km, or facing away from the sun), traced on the GPU from elevation tiles;
clicking a spot adds its windows of direct sun to the point popup. Design:
`docs/superpowers/specs/2026-09-30-sun-shade-layer-design.md`. Method card: `METHOD.md`. Parameters (with sources and
approvals): `terrain_config.yaml`. Anomalies: `ANOMALY_LOG.md`.

## Pieces
- `build_terrain.py` (QGIS Python, from this folder): stages `selftest margin mosaic tiles check`. Source is the slope
  build's 3 m DEMs (`../slope/work/dem3`, USGS lidar, 10 m where none) plus USGS 1 arc-second tiles for a 30 km ring
  (`work/margin/`, 20 tiles, 1.1 GB). Output: Terrarium PNG tiles, zoom 11-14 over the box and zoom 10 over the box
  plus the ring, in `work/tiles/` (27,565 tiles, ~1.7 GB). About 12 minutes end to end once the margin is downloaded.
  Each stage appends to `work/accounting.log` and draws in `work/diag/`.
  `"C:\Program Files\QGIS 3.34.13\bin\python-qgis-ltr.bat" build_terrain.py selftest margin mosaic tiles check`
- `upload_tiles.py` (main Python, from `radar/`): `work/tiles` to R2 `pnw/dem/v1/` (resumable, `--dry-run` first).
  Tiles are immutable: a rebuild goes to a new prefix (`v2`) and the page's `DEM` path changes with it.
- `../site_worker.js`: the site Worker serves `/<region>/dem/v<n>/...` from the bucket on the page's own origin (the
  page reads pixel values in WebGL, and the bucket's public domain sends no CORS header). Deployed with the page.
- `../map.html`, section `sun & shade`: the `// BEGIN sunShade` block (sun position, Pacific time, the walk, the
  readout; tested under node by `tests/test_map_sunshade.py`) and the WebGL shader `SUN_FS`, which must stay the same
  walk. `window.sunDebug.compare(n)` checks the shader against the JavaScript walk at n random pixels of the view.

## Checks (verification protocol; results in `work/check/`)
1. Sun position vs astropy and `snow/solar.py`, refraction by hand, Pacific times from any device zone, synthetic
   walls / slopes / plains: `python -m pytest tests/test_map_sunshade.py`.
2. Elevations vs published summits, tiles vs the mosaic, zoom 10 vs zoom 14: the `check` stage.
3. Blind re-implementation from `METHOD.md` alone vs the page's walk: `python terrain/check_js.py`, then compare with
   the independent program's `blind_results.json` (`python terrain/compare_blind.py BLIND.json`).
4. Against the snow model's horizons: `python terrain/check_snow.py lattice.npz lattice.json` (lattice from R2
   `pnw/snow/static/`).
5. Chris: ShadeMap and a timestamped photo of a shadow line.

## Gotchas
- Warp sources keep their own no-data values (the slope DEMs use -9999, USGS tiles -999999); see `ANOMALY_LOG.md`.
- Decode tiles with colour management off (`createImageBitmap(..., {colorSpaceConversion: 'none'})`): a colour-managed
  decode would change the encoded elevations.
- The shader and `sunLit` in the block are two copies of one algorithm; change both, then run `sunDebug.compare`.
- A preview needs the tiles on the page's origin at `/pnw/dem/v1/`: serve a folder with a junction to `work/tiles`.
  Delete such a junction with `cmd /c rmdir`, never `rm -rf` (which follows it into the tiles).
