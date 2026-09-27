# radar/: Blackwater Radar (radar.blackwaterlabs.org)

Read `HANDOFF.md` here first if it exists. History is in `git log` (own repo, pushed to
github.com/SelkerMetricsCG/blackwater-radar); `README.txt` is partly stale (it still describes one
Northwest window, R2 paths without a region prefix, and drag-and-drop deploys). Trust this file over it.

## What lives here
- **The public weather map**: one Leaflet page, `map.html`, for five regions (`pnw` default, `sierra`,
  `utco`, `imw`, `ne`; defined in `region.py`). `ne` (New England & NY, added 2026-09-26) differs:
  GOES-East satellite (`"goes": "East"`), CONUS NDFD grid, no SNOTEL (so no basin snowpack).
  Each region's frame names and labels use the time zone most of its land is in, set per region in both
  workflows (Chris, 2026-09-27): `pnw`, `sierra` Pacific; `utco`, `imw` Mountain (`America/Denver`); `ne` Eastern.
  Radar and satellite loops, rain/snow totals, weather stations, webcams, NOAA (NDFD) forecast, NWAC,
  freezing level, SNODAS, basin snowpack, rivers, USBR snow-to-flow, NWS alerts, click-anywhere point values.
- **One passenger that uses the same Actions and R2 setup:**
  - `rivers/`: daily analysis behind rivers.blackwaterlabs.org (site itself is `BlackwaterLabs/rivers`).
    `rivers/wenatchee/` is a copy; develop in `BlackwaterLabs/Wenatchee_River_Analysis` and mirror with
    `rivers/sync_analysis.bat`.
- The Roaring Creek SolSat telemetry pull (`solsat.py`) moved to the roaring repo (private
  `SelkerMetricsCG/roaring`) on 2026-09-27; nothing here feeds `roaring-data` any more.
- `tests/`: pytest, network blocked in `conftest.py`; currently the webcam tests.

## How it runs (GitHub Actions, all free tier)
| Workflow | When | Does |
|---|---|---|
| `capture.yml` | every 15 min, started by Worker `radar-cron` | `REGION=<r> python cloud.py radar` for each region: radar/satellite frames, accumulation overlays, `<r>/frames.js` |
| `hourly.yml` | minute 4 each hour, started by `radar-cron`; one job per region | `python cloud.py hourly`: stations, rivers, forecast, MRMS, freezing level, SNODAS, webcams, avalanche, basins |
| `rivers.yml` | 15:30 UTC daily | `python rivers/run_rivers.py` → `rivers/<key>/`, `rivers/index.js` |
| `tests.yml` | every push/PR | `python -m pytest tests/ -v` |

GitHub's own `schedule:` fired `capture.yml` only every 2–6 h (40 runs 2026-09-20 to 09-26), so the Cloudflare
Worker `radar-cron` (`cron/`: `worker.js`, `wrangler.toml`) sends a `workflow_dispatch` on its cron triggers. Its secret
`GH_TOKEN` is a fine-grained token (this repo only, Actions read/write) that Chris made; when it expires the
dispatches fail (visible in the Worker's logs) and the GitHub schedules, kept on as a backstop, are all that runs.
The token expires 2027-09-27 (renewal steps in `cron/worker.js`). The last step of `capture.yml` is a watchdog: on a
GitHub-scheduled run it fails if the Worker has not started a run for an hour, so GitHub emails Chris. Caveat: GitHub
disables `schedule:` triggers after 60 days without a commit, and then the watchdog stops running too.
Deploy it with `npx wrangler deploy` from `cron/`.

Data goes to the public R2 bucket `radar` (https://radar-files.blackwaterlabs.org) under `<region>/`.
`cloud.py` rebuilds state from R2 each run and prunes scans older than 30 h. `r2sync.py` sets
cache headers per file type (frames immutable, `data/*.js` and `frames.js` no-cache).

## Publishing the map page (no workflow does this)
```
python build_web.py      # bakes the R2 URL and region table into web/index.html
npx wrangler deploy      # Worker "radar", assets-only from ./web; Node must be on PATH
```
- Ask Chris before deploying; he does `wrangler` and `gh` logins himself.
- `web/` is gitignored but holds the **only copies** of the icons, `manifest.webmanifest` and
  `vendor/leaflet*`. Never delete or regenerate it wholesale.
- The custom domain is attached in the Cloudflare dashboard, not in `wrangler.toml`.
- Local check: run `build_web.py`, serve `web/` with `python -m http.server <port> --bind 127.0.0.1`
  in the background, open it in the in-app browser. Data loads from live R2, so it shows real layers.

## map.html conventions
- Data comes in by `<script>` tags with a `?t=` cache-buster (the bucket has no CORS header). Globals:
  `RADAR_DATA`, `STATIONS`, `BASINS`, `RIVERS`, `MRMS`, `SNODAS`, `FORECAST`, `FREEZING`, `ALERTS`,
  `AVALANCHE`, `WEBCAMS`, `VALUES`.
- Panel: groups are `.sec.grp`; a layer is a `label.opt` checkbox followed by a `.subwrap data-for=<id>`
  that opens only while it is on. The group badge counts `.body > .opt > input:checked`, so sub-controls
  must not sit directly in an `.opt` under `.body`.
- "Make current map & settings my default" saves to `localStorage['radar.default']`. A new control must be
  added to `DEF_CHECKS` / `DEF_SELECTS` (or saved explicitly, like `stMode` and `stWin`), and old saved
  keys should keep restoring.

## Webcams (`webcams.py`, rebuilt by the hourly job)
- Sources: AlertWest (fire PTZ cams plus the DOT road, FAA and utility cams it aggregates; road vs fire comes
  from the agency in `src`, see `DOT_SRC`); USGS river (HIVIS), USGS volcano (Ashcam) and NOAA buoy cams pulled
  live each run; `webcams_extra.json`, the curated conditions cams (ski, water, town, park). The hourly job
  fetches each once and logs failures by host but drops only Brownrice offline cards: several hosts refuse or
  404 GitHub's runners while serving browsers (entries marked `robots` are never fetched, only hotlinked).
  Prune dead ones from a PC: `python cams_research/prune_extra.py` (lists), `--apply` (removes).
- Road cams within `SITE_M` (250 m) become one marker with `views`; road sites are thinned to one per
  `RURAL_KM` (3 km), or `URBAN_KM` (10 km) inside the hand-set metro circles in `URBAN`.
- The research behind the curated list (sources, URL patterns, terms, Chris's 2026-09-27 decisions) is in
  `cams_research/` (`sources_notes.md`; `make_extra.py` rebuilds the list from `combined.json`). Left out on
  purpose: YouTube thumbnails, ipcamlive/webcam.io cams (owner consent needed), SeeJH, Ambient Weather.
- NPS cams: `python cams_research/refresh_nps.py` refreshes them with Chris's key from `nps.env` (gitignored).

## Rules
- Free tier only: GitHub Actions, R2, Workers. Do not scrape NWAC (its API is for approved researchers);
  Synoptic is paid; never reuse tokens found in web pages.
- `r2.env` and `nps.env` are private and gitignored: never print or commit them, and leave `*.env` out of
  any grep whose output is shown.
- Station windows (`stations.py WINDOWS = [1, 3, 6, 12, 24]`) are shared by every station source, the
  interpolation (`interp.py`) and the map's window chips. SNOTEL hourly data is pulled for the last 26 h only.
- Ideas Chris has parked for this site: `BlackwaterLabs/NEXT_PROJECTS.md`, "Radar-site ideas parked for later".

## Gotchas
- `core.autocrlf=true`, no `.gitattributes`: files are LF in the index; git's CRLF warnings are harmless.
- `capture.capture_all()` run locally **uploads to the live bucket** whenever `r2.env` exists (`r2sync.sync`
  at the end), with frame names in this PC's Pacific time. To test a region without publishing, call the
  job modules' `build()` directly, or run with `r2.env` renamed.
- `capture.py` run locally stops at 10:00 or when a STOP file appears (`start_capture.cmd` is legacy;
  capture runs on Actions now).
- Slope from a DEM: compute it in true ground metres (UTM). In web-mercator metres it under-reads by
  cos(latitude); at 47°N a 35° slope comes out near 25°.
- Chris's router caches NXDOMAIN for new hostnames; test a new subdomain on his phone or 1.1.1.1.

## Timeline
- 2026-09-13: pipeline, map, Actions, multi-region engine, MRMS reflectivity (RainViewer fallback),
  stations, USBR snow-to-flow, saved defaults.
- 2026-09-14: `solsat.py`; `rivers/` daily analysis (Peshastin default gauge; Plain, Icicle, ENSO added).
- 2026-09-25/26: pytest suite for `solsat.py` (PR #1, the only merge).
- 2026-09-26: layer-panel reorder; slope-angle layer from WA lidar started (see `HANDOFF.md`).
- 2026-09-27: `solsat.py`, its tests and workflow moved to the roaring repo.
