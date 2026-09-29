# radar/: Blackwater Radar (radar.blackwaterlabs.org)

Read `HANDOFF.md` here first if it exists. History is in `git log` (own repo, pushed to
github.com/SelkerMetricsCG/blackwater-radar); `README.txt` is partly stale (it still describes one
Northwest window, R2 paths without a region prefix, and drag-and-drop deploys). Trust this file over it.

## What lives here
- **The public weather map**: one Leaflet page, `map.html`, for five regions (`pnw` default, `sierra`,
  `utco`, `imw`, `ne`; defined in `region.py`). `ne` (New England & NY, added 2026-09-26) differs:
  GOES-East satellite (`"goes": "East"`), CONUS NDFD grid, no SNOTEL (so no SNOTEL layer).
  Each region's frame names and labels use the time zone most of its land is in, set per region in both
  workflows (Chris, 2026-09-27): `pnw`, `sierra` Pacific; `utco`, `imw` Mountain (`America/Denver`); `ne` Eastern.
  Radar and satellite loops, rain/snow totals, weather stations, webcams, NOAA (NDFD) forecast, NWAC,
  freezing level, SNODAS, SNOTEL (stations, basins or both, like NRCS iMap), rivers, USBR snow-to-flow, air quality (AirNow monitors, AirFire temporary smoke monitors, AirNow's
  interpolated AQI), fires (WFIGS, CWFIF and BC Wildfire Service incidents and perimeters) and
  satellite hotspots (NASA FIRMS, NOAA NGFS), the HRRR smoke forecast loop, NWS alerts, click-anywhere point values.
- **One passenger that uses the same Actions and R2 setup:**
  - `rivers/`: daily analysis behind rivers.blackwaterlabs.org (site itself is `BlackwaterLabs/rivers`).
    `rivers/wenatchee/` is a copy; develop in `BlackwaterLabs/Wenatchee_River_Analysis` and mirror with
    `rivers/sync_analysis.bat`.
- The Roaring Creek SolSat telemetry pull (`solsat.py`) moved to the roaring repo (private
  `SelkerMetricsCG/roaring`) on 2026-09-27; nothing here feeds `roaring-data` any more.
- **Snow-conditions tracker (started 2026-09-28, in progress)**: a snow-surface model for skiing, to be its own site
  (snow.blackwaterlabs.org) on this repo's Actions and R2. Spec `docs/superpowers/specs/2026-09-28-snow-conditions-model-design.md`,
  status and next steps in `HANDOFF.md`. Built so far: the season archive (`snow/archive.py`, run last in the hourly job for
  regions with `"snow": True` in `region.py`, `pnw` only), full avalanche.org products (`snow/avyproducts.py`), NAC
  observations gated on `NAC_OBS_ORIGIN` (`snow/observations.py`; never send an origin we were not given). Archive layout:
  `<region>/snow/archive/<local date>/HH.json.gz` (stations, HRRR freezing level f0, MRMS 1 h, zone danger), `daily.json.gz`
  (74 h SNOTEL series, NDFD grids, freezing f0..f18, MRMS 24 h, SNODAS, full station records), `products/`, `obs/`; every
  file is written once and never rewritten (`r2sync` uploads it immutable). Grids are the click-anywhere grids
  (`values.read_grid`) at 64 px (smooth fields) or 256 px (precipitation), nodata -1. Static: the 100 m terrain lattice
  (`snow/lattice.py`, built by the `snow static` workflow into `<region>/snow/static/`), the solar term (`snow/solar.py`),
  the surface-state model (`snow/state.py`, `snow.yml` step 1 daily at 09:20 UTC, writes `<region>/snow/state/`; forcing from
  the archive in `snow/forcing.py`, R2 access in `snow/store.py`), the ledger and LLM passes (`snow/daily.py`, step 2: `ledger.py`,
  `llm.py` through the Claude API with the Actions secret `BW_SNOW_MODEL` (the key, expires 2027-07-31; model from the
  repository variable of the same name), `score.py`, `assimilate.py`; writes `<region>/snow/ledger/` and `brief/`),
  parameters in `snow/snow_config.yaml` (same protocol as `snotel_config.yaml`; nothing approved yet). The site: `snow.html`,
  `python build_snow.py` -> `web_snow/` (gitignored), `npx wrangler deploy --config wrangler_snow.toml` (Worker `snow`).
  Trip log: `snow/trips.json`. Offline: `snow/replay.py` (re-run a date range on a subset of cells), `snow/fit.py`
  (bounded parameter fit on the ledger's residuals; `snow_fit.yml` by hand proposes, `--apply` from a session changes
  `snow_config.yaml` and writes `param` ledger records).
- `tests/`: pytest, network blocked in `conftest.py`; webcams, SNOTEL, stations, air quality, the snow archive.

## How it runs (GitHub Actions, all free tier)
| Workflow | When | Does |
|---|---|---|
| `capture.yml` | every 15 min, started by Worker `radar-cron` | `REGION=<r> python cloud.py radar` for each region: radar/satellite frames, accumulation overlays, alerts, air quality (`airquality.py`), fires (`fires.py`), `<r>/frames.js` |
| `hourly.yml` | minute 4 each hour, started by `radar-cron`; one job per region | `python cloud.py hourly`: snotel, stations, rivers, forecast, MRMS, freezing level, smoke forecast (`smoke.py`, only when a new HRRR run is posted), SNODAS, webcams, avalanche, basins |
| `rivers.yml` | 15:30 UTC daily | `python rivers/run_rivers.py` → `rivers/<key>/`, `rivers/index.js` |
| `tests.yml` | every push/PR | `python -m pytest tests/ -v` |
| `snow.yml` | 09:20 UTC daily | `python -m snow.state` then `python -m snow.daily`: the surface-state model for the previous local day, then extraction, scoring and the brief through the Claude API; `<r>/snow/state/`, `ledger/`, `brief/` |
| `snow_fit.yml` | by hand | `python -m snow.fit`: replays the model around every scored report, proposes bounded parameter moves to `<r>/snow/fit/` |
| `snow_static.yml` | by hand | `python -m snow.lattice --upload`: the snow model's terrain lattice (20 USGS DEM tiles) to `<r>/snow/static/` |

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
Every PUT and LIST is an R2 Class A operation (free: 1 million a month, whole account). So `r2sync` skips a rewritten file
whose MD5 equals the ETag `cloud.py` listed; a state cache goes back only if the run changed it; and an hourly run exits if
the region's `stations.js` went up this UTC hour under 30 min ago (hourly.yml's `force` input overrides). List narrow
prefixes (`<region>/frames`, `<region>/data/`), never `<region>/`: pnw holds 109k slope tiles. Measured 2026-09-29:
~20k Class A a day before the smoke and snow jobs. Recheck with the bucket's Metrics tab or a read-only snapshot of
LastModified/ETag.

## Publishing the map page (no workflow does this)
```
python build_web.py      # bakes the R2 URL and region table into web/index.html
npx wrangler deploy      # Worker "radar", assets-only from ./web; Node must be on PATH
```
- Ask Chris before deploying; he does `wrangler` and `gh` logins himself.
- Chris runs `git push` and the deploy himself from Run-button blocks (format in `../CLAUDE.md`). Run
  `build_web.py` yourself first, then hand him `npx --yes wrangler deploy` from `C:/Users/16035/Desktop/BlackwaterLabs/radar`.
  Afterwards, curl https://radar.blackwaterlabs.org/ (not `/index.html`, which answers empty) and diff it against `web/index.html`.
- `web/` is gitignored but holds the **only copies** of the icons, `manifest.webmanifest` and
  `vendor/leaflet*`. Never delete or regenerate it wholesale.
- The custom domain is attached in the Cloudflare dashboard, not in `wrangler.toml`.
- Local check: run `build_web.py`, serve `web/` with `python -m http.server <port> --bind 127.0.0.1`
  in the background, open it in the in-app browser. Data loads from live R2, so it shows real layers.

## map.html conventions
- Data comes in by `<script>` tags with a `?t=` cache-buster (the bucket has no CORS header). Globals:
  `RADAR_DATA`, `STATIONS`, `SNOTEL`, `BASINS`, `RIVERS`, `MRMS`, `SNODAS`, `FORECAST`, `FREEZING`, `ALERTS`,
  `AVALANCHE`, `WEBCAMS`, `AIRQ`, `FIRES`, `PERIMS`, `SMOKE`, `VALUES`.
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
  purpose: ipcamlive/webcam.io cams (owner consent needed), SeeJH (Snow King's streams are SeeJH's too), Ambient Weather.
- YouTube-live cams (2026-09-27): `webcams_youtube.json` (163 cams, 19 marked `off` with the reason; kept by hand,
  `make_extra.py` never touches it) goes through `youtube.py` each hourly run, via the YouTube Data API only. Key:
  `YT_API_KEY` (Actions secret of that name; locally `youtube.env`, gitignored); no key = no YouTube cams, nothing fetched.
  `videos.list` says which ids are live and gives the thumbnail URL; a gone or ended stream triggers `search.list` on
  its channel, matched by the cam's `match` word (else its last title, else the channel's only stream); the new id is
  kept in `<region>/data/youtube_cache.json` (in `cloud.py STATE_FILES`; the `_cache.json` name keeps r2sync from
  publishing it). Quota: free 10,000 units/day per key; worst case ~5,200/day (`SEARCH_CAP` 10 searches per region
  per 24 h at 100 units, `videos.list` ~220/day); each run logs its units. They go to `WEBCAMS.yt`, not `cams`, so a
  page without the YouTube credit never shows them. Check the list against the API from a PC:
  `python cams_research/youtube_enrich.py` (4 units; `--search N` costs 100 each).
- YouTube terms (Developer Policies, read 2026-09-27) and how they are met: the job calls only
  `www.googleapis.com/youtube/v3` (never i.ytimg.com or youtube.com; the key rides in a header); API data is refreshed
  hourly, state unconfirmed for 30 days is dropped, and API-learnt channel ids and titles stay in the state file, not
  the list; the popup shows the YouTube icon and name linked to the video, says what is not from YouTube, and links
  YouTube's Terms and Google's Privacy Policy; `terms.html` (copied into `web/` by `build_web.py`, linked at the foot
  of the panel) is the site's terms and privacy notice.
- NPS cams: `python cams_research/refresh_nps.py` refreshes them with Chris's key from `nps.env` (gitignored).

## Rules
- Free tier only: GitHub Actions, R2, Workers. Do not scrape NWAC (its API is for approved researchers);
  Synoptic is paid; never reuse tokens found in web pages.
- `r2.env`, `nps.env` and `youtube.env` are private and gitignored: never print or commit them, and leave `*.env`
  out of any grep whose output is shown.
- Station windows (`stations.py WINDOWS = [1, 3, 6, 12, 24]`) are shared by every station source, the
  interpolation (`interp.py`) and the map's window chips.
- SNOTEL is pulled once per hourly run by `snotel.py` (74 h hourly incl. soil sensors, SCAN soil sites, BC automated
  pillows daily); `stations.py` takes its records from there. New snow from any depth sensor is `newsnow.py`'s storm
  total; its parameters are in `snotel_config.yaml`, the method check in `snotel_check/` (method card `METHOD.md`),
  anomalies in `ANOMALY_LOG.md`.
- Air quality (`airquality.py`, 15-minute job): permanent monitors show AirNow's `PM25_AQI` unchanged (AirNow
  guidelines); only temporary monitors (USFS AirFire export) get AQI from `aqi_from_pm25` (EPA 2024 breakpoints).
  Never take times from `AirNowWildfire.csv` (its rows carry the file's hour; values are 1-3 h older). State:
  `aq_cache.json`. Check a region with `python smoke_research/aq_check.py <region>` (no upload); preview the page with
  `smoke_research/aq_serve.py`. Spec and parameter ledger: `docs/superpowers/specs/2026-09-27-air-quality-layer-design.md`;
  sources and endpoints: `smoke_research/sources_notes.md`.
- Fires (`fires.py`, 15-minute job, after air quality): every fire the agencies list as
  current (WFIGS for the US, CWFIF joined with BC Wildfire Service by fire number for
  Canada), styled by activity: active = edited within 72 h, or a hotspot linked in the last
  24 h, or Canada out of control / being held; 100 % contained is quiet unless it has hotspots
  (Chris kept this rule 2026-09-28; measured alternatives are in the spec, "Activity rule:
  alternatives"). Complex children are not incidents, but their perimeters and GOES links are
  relabelled to the parent through WFIGS `CpxID`. Perimeters are refetched only when a layer's
  edit stamp changes; hotspots come from FIRMS 48 h + NGFS 24 h (newest detection per tracked
  feature; unconfirmed shown hollow); the page ages hotspots by the time since `FIRES.updated_t`.
  State `fires_cache.json` (keeps raw ids). Check a region with `python
  smoke_research/fires_check.py <region>` (no upload); preview with `smoke_research/fires_serve.py`
  (port 8796; it reads `web/index.html` once at start, so restart it after `build_web.py`). Spec
  and ledger: `docs/superpowers/specs/2026-09-28-fires-layer-design.md`; anomalies in
  `ANOMALY_LOG.md`.
- Smoke forecast (`smoke.py`, hourly job, after freezing level): HRRR near-surface smoke (`MASSDEN` 8 m) for f01-f48 of
  the newest complete 00/06/12/18Z run, one byte-range request per hour from AWS `noaa-hrrr-bdp-pds` (the record is
  found by its `.idx` text). It builds only when a newer run's f48 index exists (a run reaches the map ~2 h 05-25 min
  after its start), into the frame slot (`a`/`b`) the live `smoke.js` is not using, so an upload never pairs one run's
  image with another's time; a failed hour aborts and keeps the previous run. Colours: transparent < 2 ug/m3, light
  smoke 2-9.0 grey, then the PM2.5 AQI categories (9.1, 35.5, 55.5, 125.5, 225.5; judgment calls in the spec ledger).
  PNW north of the model's edge (~50-52 N, 18 % of the window) is masked and the edge drawn dashed. Click-anywhere reads
  `data/values/smoke_<slot>.js` (128 x 128 cells x 48 h, tenths of ug/m3). State `smoke_cache.json`. About 51 R2
  writes per new run per region (<= 32k a month). Check a region with `python smoke_research/smoke_check.py <region>`
  (no upload; geometry check against ecCodes' own coordinates, monitors check with a shift test, figure); preview with
  `smoke_research/smoke_serve.py` (port 8797; restart after `build_web.py`). RRFS (operational 2026-10-14) stays off
  until it is on AWS and checked side by side (spec, "RRFS: when and how to switch"). Spec and ledger:
  `docs/superpowers/specs/2026-09-28-hrrr-smoke-layer-design.md`; anomalies in `ANOMALY_LOG.md`.
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
- 2026-09-27: SNOTEL layer (spec `docs/superpowers/specs/2026-09-27-snotel-layer-design.md`); new snow as a storm total.
- 2026-09-27: YouTube-live webcams through the YouTube Data API (`youtube.py`, `webcams_youtube.json`, `terms.html`).
- 2026-09-28: Air quality section (AQI stations, AirNow interpolated AQI); spec
  `docs/superpowers/specs/2026-09-27-air-quality-layer-design.md`.
- 2026-09-28: Smoke & fires section, phase 2 (fires, perimeters, satellite hotspots); spec
  `docs/superpowers/specs/2026-09-28-fires-layer-design.md`.
- 2026-09-28: snow-conditions tracker started: design spec, season archive (`snow/`), NWAC access request drafted.
- 2026-09-29: snow tracker: terrain lattice (USGS DEM, ESA WorldCover canopy), solar term, surface-state model, ledger and
  LLM passes, `snow.html`; workflows `snow.yml`, `snow_static.yml`.
- 2026-09-28/29: Smoke & fires section, phase 3 (HRRR near-surface smoke loop, `smoke.py`); spec
  `docs/superpowers/specs/2026-09-28-hrrr-smoke-layer-design.md`. Built and released in one session without review stops.
