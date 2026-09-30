# Sun & shade layer: design (2026-09-30)

Chris approved every section in chat on 2026-09-29/30 and asked for the build to run straight through to deploy
("fast track it and no more stops"). Method card: `terrain/METHOD.md`. Parameters: `terrain/terrain_config.yaml`.

## What it is for
Planning a ski day or trip: which slopes are in direct sun or shade at a chosen minute of any date, and for one
spot, the windows of direct sun that day. Clear-sky geometry only.

## What the viewer sees (map.html, pnw window only)
- Terrain group, below Slope angle: checkbox **Sun & shade** with a (?) tip. Same box as the slope layer
  (WA Cascades, 46.0-49.0 N, 122.2-120.0 W); drawn from zoom 10.
- Controls (smoke-player style): date box (today by default, any date), time slider 05:00-22:00 Pacific in
  10-minute steps starting at the current time, Play and < > (10 min), opacity. Label:
  "Tue 30 Sep, 09:40 PDT · sun 23° up, from the SE (128°)".
- Terrain in shadow (cast by terrain, or facing away from the sun) is darkened with a translucent muted blue-grey;
  sunlit terrain is left clear. Sun below the horizon: everything shaded, with a note.
- Clicking a spot while the layer is on adds a line to the existing point popup:
  "Direct sun here on 12 Jan: 9:40-11:20, 12:05-15:30 (5.2 h) · flat horizon 7:52-16:38".
- Help tip: clear-sky geometry (no cloud); bare-earth model (no tree shade); built from USGS lidar; shows where
  the sun reaches, not avalanche conditions (check NWAC).

## Approach (B, chosen over precomputed horizons)
Elevation tiles on R2; the page traces shadows on the GPU (WebGL2) for the exact sun position.

### Elevation tiles (`terrain/`, PC build with QGIS Python, staged like `slope/`)
- Source: the slope build's 3 m DEMs (`slope/work/dem3`: USGS 1 m lidar averaged to 3 m, the 10 m model where no
  lidar). A 30 km ring around the box from USGS 1 arc-second (about 30 m) for distant peaks, plus the 10 m tiles
  the slope build already holds.
- The USGS 1 arc-second border tiles carry BC terrain, so the ring covers north of 49 N too (the limit feared in the
  design discussion does not exist; checked in the second build's figure, 2026-09-30).
- Tiles: web-mercator XYZ PNG, Terrarium encoding (AWS terrain tiles' format: elevation = R*256 + G + B/256 - 32768),
  zoom 11-14 over the box (zoom 14 about 6.5 m on the ground) and zoom 10 (about 100 m) over the box plus the ring.
  R2 prefix `pnw/dem/v1/`, immutable (a rebuild goes to `v2`).
- Stages: `selftest margin mosaic tiles check`; each writes an accounting line and a figure in `terrain/work/diag/`.

### Serving
The bucket has no CORS header, and WebGL must read pixel values, so the site Worker gains a small script
(`site_worker.js`) with an R2 binding that serves `/<region>/dem/v<n>/<z>/<x>/<y>.png` from the bucket on the
site's own origin (edge-cached, immutable); every other path is the static assets, as now. Same pattern as roaring.

### Shadows in the page
- One WebGL2 canvas in its own pane (above tiles, below markers), redrawn on pan/zoom end and every slider step.
- Loads elevation at the view's zoom (capped at 14) over the view plus a 2 km apron, and zoom 10 over the view plus
  25 km.
- Per screen pixel: walk toward the sun, fine steps over the near data to 2 km, growing steps over the coarse data
  to 25 km; shaded if terrain rises above the line to the sun (Earth curvature with terrestrial refraction), or if
  the ground faces away from the sun. Sun position: NOAA's algorithm (ported from `snow/solar.py`) per pixel, plus
  NOAA's atmospheric refraction.
- The click readout runs the same walk in JavaScript every 2 minutes of the day.
- Times are Pacific whatever the device's zone. No WebGL2: a note instead of shadows.

## Checks (verification protocol)
1. Sun position: JS vs `snow/solar.py` and vs astropy (independent ephemeris), several places and dates, 0.1°.
2. Known answer: synthetic wall and cone; shadow length = height / tan(elevation) (+ curvature), in the JS walk,
   the GLSL shader and the Python reference.
3. Blind re-implementation: a fresh agent writes a Python shadow trace from `terrain/METHOD.md` alone, runs it on
   the same tiles at six places x three dates x several times; agreement reported with disagreement figures.
4. Against the snow model's horizons (`snow.sunhours`, 100 m, 16 directions) at about ten points.
5. Chris: ShadeMap and a timestamped photo of a shadow line.
Anything well off goes in `terrain/ANOMALY_LOG.md` with rival explanations before any change.

## Order
Spec -> pipeline + selftest -> mosaic/tiles (background) -> page + worker -> node/pytest tests -> local browser
check with local tiles -> checks 1-4 -> upload tiles -> Chris: push, deploy, check 5.
