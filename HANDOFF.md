# Handoff: radar map work (2026-09-28 19:40)

Read `CLAUDE.md` in this folder for how the site works. Two pieces of work are open (2 and 3).
Pushes and deploys: Chris runs them from Run-button blocks (format in `../CLAUDE.md`); read his Terminal panel afterwards.

## 11. Hillshade basemap chip: LIVE 2026-09-28 19:36 (`2c854e1`, deploy d34e91d3); merged with origin/main 19:44, push is a fast-forward
- Fifth chip in the Basemap row (`map.html`): Esri `Elevation/World_Hillshade` (native to z16, upsampled to 17) under the
  same Esri boundaries/places and transportation reference tiles Satellite uses. Saved defaults pick it up (`bases[d.base]`).
- Checked locally 19:40 (`build_web.py`, served `web/`): chip switches, 18 hillshade + 36 reference tiles load, no console
  errors, relief crisp at Leavenworth z11. Chris chose this ("option 4") over a real 3D engine; the 3D options he was
  offered, in order: MapLibre terrain port of the whole page, a "3D view" MapLibre panel beside Leaflet, CesiumJS.
- Deployed 19:36 with ski (`f95e5e8`): live page byte-identical to the local build. Chris's push was rejected
  (origin/main had the snow-tracker PR merges, `d526b24` and below). The HRRR smoke session said it is merging
  origin/main plus these two commits in its worktree and will fast-forward radar/main, then hand Chris one push;
  so no local merge here. If that never lands: `git merge origin/main` on main is conflict-free (merge-tree checked).

## 10. Ski reports layer: LIVE with data 2026-09-29 14:20 (page since 09-28 19:36 via deploy d34e91d3; code pushed 09-29 13:57 as `783e047`)
- First hourly run with `ski.py` (14:04 PDT) wrote `pnw/data/ski.js`: 94 areas, 14 on the feed, 2 with a report (off season), 55 report
  links; Stevens opens its snow-and-weather-report page. `tests` green on `main` at `5bf3640` (tests.yml now installs scipy and
  pillow for the smoke tests; the red runs after that are the cloud snow-tracker branch, not main).
- What: Snow > "Ski reports". 520 operating lift-served downhill areas in the five windows (`ski_areas.json`, built by
  `ski_research/build_ski_areas.py` from OpenSkiMap's `ski_areas.geojson`, ODbL, credited in the layer note). The 52 on
  the Ikon/Alterra resort feed (`ski.py`, `mtnpowder.com/feed?resortId=N`, the undocumented JSON the resort sites load;
  Chris accepted using it 2026-09-28) show the resort's own numbers: 24/48/72 h, 7 d at base/mid/summit, base depth,
  storm and season totals, report time; chips switch the label (mid-mountain leads, then summit, then base). Others are
  hollow dots linking to the resort page (Chris: link out for Epic and independents; no scraping, no bot evasion).
  Hourly job: `capture.py` calls `ski.build` after basins; output `<region>/data/ski.js`. Tests `tests/test_ski.py`,
  `tests/test_map_ski.py` (230 pass). Preview: `python ski.py; python ski_research/ski_serve.py` (port 8798, launch entry
  `ski-preview`), checked in the in-app browser: 94 PNW markers, season labels, cards for a feed area and a link-out area.
- **After the push:** the first hourly run (minute 4) writes `ski.js`; until then the layer says "ski data not available yet".
  Check a run's log for `ski: N areas, F on the resort feed, R with a report, X failed`. Off season nearly every report
  is months old (drawn faded, "not updated lately"); the real test is opening day (mid-Nov): labels, stale rule (36 h),
  whether resorts fill base/mid/summit as expected (Schweitzer's points were all `--` in May).
- **Report links (`8a57b95`, 19:45, data only, no redeploy):** Chris: Stevens must open its snow report, not the home page.
  `ski_research/find_reports.py` reads each link-out resort's home page once and keeps the link that says snow report /
  conditions / mountain report (checked to answer) into `ski_research/reports.json` (258); Vail sites get the fixed
  `/the-mountain/mountain-conditions/snow-and-weather-report.aspx`; 11 hand-set in `overrides.json` (Hood Meadows,
  Timberline, Heavenly, Brian Head, ...). 269 of 468 link-outs now carry `report`; the other 199 fall back to the
  website (`ski_research/work/reports_missing.txt` after a run; fix by hand in `overrides.json` `report`). Full suite 291.
- **CLAUDE.md lines still to add** (its working copy is dirty from another session, so left alone): hourly table row
  "ski (resort reports)"; a Rules bullet: ski areas from OpenSkiMap via `ski_research/build_ski_areas.py` (rebuild
  from a PC; `ski_research/work/review.txt` lists areas OpenSkiMap has no lifts for; hand fixes in
  `ski_research/overrides.json`, keyed by the 12-char area id: `mp`, `report`, `name`, `drop`, `keep`, `add`); Ikon feed
  once per resort per hourly run, plain UA, 20 s timeout; Timeline 2026-09-28.
- Open for Chris (none blocking): (1) Stevens Pass numbers: the research agent found WSDOT's daily pass snowfall JSON
  (`wsdot.com/Travel/Real-time/Service/api/MountainPass/SnowFallData?MountainPassId=10&Year=2025`, undocumented; WSDOT's
  summit measurement, not the resort's; 305 in vs the resort's 342 in 2025-26) and suggests emailing WSDOT before using
  it; NOHRSC's public-domain snowfall grids as a cross-check; SnoCountry (paid key) covers Vail resorts. (2) The 199
  link-outs without a `report` page (mostly small eastern hills; the biggest: Waterville Valley, Bretton Woods, Boreal,
  Sunrise Park AZ) and a spot check of the 258 found automatically.
  (3) `review.txt` has 86 lines, mostly nordic or tiny hills; Cochran's VT is a real T-bar hill OpenSkiMap has no lifts
  for (`keep`). (4) Bear Mountain CA (feed 57) and Snowshoe WV (feed 2) were not matched; Boyne (MI) and Alyeska are
  outside the windows.

**SolSat moved out (2026-09-27, another session):** the daily pull runs from the private repo `SelkerMetricsCG/roaring`;
its files, workflow and the solsat part of `tests/conftest.py` are gone from radar. Nothing to do here.

## 1. Layer-panel changes: live, nothing open
- Commit `67543af` (pushed to GitHub), deployed 2026-09-26 16:18; live page matches the local build.
- `517d708` (pushed, deployed 16:33): (?) help tips on Radar loop and Rain / snow totals (`.help` button +
  `.helptip` span inside the `.opt` label), Satellite loop last. Radar keeps 30 h of scans (`cloud.py RETAIN_H`),
  so the tip offers 3–24 h.

## 2. Slope-angle layer: LIVE 2026-09-28 (`6c6fa71`, deployed with `afc3e8f`; tiles on R2 `pnw/slope/v1`, 109,109)
- Checked live 17:30: page = local build, 40/40 sampled R2 tiles identical, 16 tiles load at Colchuck z15, no console errors.
- How to rebuild or extend: `slope/README.md`. README commit is local (Chris pushes).
- 17:37 Chris approved every judgment call (recorded in `slope_config.yaml` `approved:`) and the ~1 m offset; local tiles
  deleted (`slope/work/` now 17 GB). Open, optional: Rainier lidar via the WA DNR portal. Commits to push: README + approvals.

## 3. SNOTEL layer: live 2026-09-27 16:30 (`8367e53`..`8951b56`; spec and plan in `docs/superpowers/`)
- Open for Chris, none blocking: soil-moisture colours (`SMS_BINS`, judgment call); 26 soil sensors at exactly 0.0 %
  (`ANOMALY_LOG.md`); one 2.5 in floor zeroes most 2 in rises in 1-6 h windows (per-window floor?); deferred review minors
  (latest reading unsmoothed, possible false 3 in at North Fork OR / Brundage Reservoir ID, arrow keys reach greyed radios,
  new-snow label decimals, SNOTEL depth freshness in stations.js); caching daily medians would save ~2 min per run.
- Watch 1 Oct: the water-year reset of PREC may zero SNOTEL 24 h precipitation for a day.

## 4. More webcams: YouTube-live cams deployed and pushed 2026-09-27 18:28 (`d959fb3`, docs `78c8a98`); first hourly run on it is 19:04
- `youtube.py` + `webcams_youtube.json` (163 cams, 19 `off` with reasons) through the YouTube Data API only; how it works,
  quota budget and terms: `CLAUDE.md` "Webcams". Chris set the Actions secret `YT_API_KEY` 2026-09-27; `youtube.env` is the
  local copy. Mission Ridge moved from `webcams_extra.json` into the new list in `d959fb3`.
- Released 18:28: page deployed first (live page == `web/index.html`; `/terms.html` 307 -> `/terms` 200), then pushed
  (tests passed on `78c8a98`). Runs up to 18:04 used `97ab270`, so R2 `webcams.js` has no `yt` yet and Mission Ridge still
  shows the old hotlinked way until the 19:04 run moves it into `yt`.
- **Next check (not done yet):** after the 19:04 run, R2 `<region>/data/webcams.js` should carry a `yt` list (pnw about 62
  cams live of 72; sierra, utco, imw too; ne none) and each region's log a `youtube:` line (units, searches, left out);
  first runs may each spend their 10 searches (~1,000 units), fine within 10,000/day.
- Local check 18:00 (pnw, `webcams.build(check=False)`, no upload): without key 940 markers + 0 YouTube; with key 72 cams,
  62 live -> 31 markers; 10 searches (the cap) found 11 cams again (La Grande downtown, Nanaimo, Tamarack snow stake,
  Mt Spokane Chair 4 had restarted with new ids; Snoqualmie/Alpental/Cypress found by title); 1,003 units. Popup checked
  in the in-app browser (icon, credit links, view switching, no console errors). Local state: `regions/pnw/data/youtube_cache.json`.
- Enrichment (`cams_research/youtube_enrich.py`, 18:00, 1,212 units incl. 12 searches): of 144 cams on, 104 live on their
  research id, 20 ended, 1 missing, 19 had no id. Labels fixed from API titles (Snow King's were shuffled, Willamette's
  swapped, Brundage/Kelly Canyon/Schweitzer/Snow Summit/Snow Valley renamed). Session total ~2,220 units today.
- Open for Chris: (1) Snow King is See Jackson Hole's channel, so it is `off` like SeeJH; say if the API route makes SeeJH
  OK. (2) `terms.html` wording (it says using the map means agreeing to YouTube's Terms; the policy wants users to agree
  to a privacy policy before use, done here as a notice, not a click-through). (3) API key restriction: done at creation
  (YouTube Data API v3 only). (4) Compare the drawn YouTube icon with the official file from brand.youtube. (5) Dodge Ridge
  (3) and Dillon are `off`: ids gone and no channel id; add a channel id from the owner's embed to bring them back.
- Optional ideas: ask City of Stevenson to allow its 3 ipcamlive Gorge cams; more Stevens Pass cams; Skaping resolver.

## 5. New England region, avalanche titles, radar-cron, time zones: done 2026-09-27 (`17bc3b7`..`b2838e4`)
- Only check left: if `git log origin/main` lacks `b2838e4`, ask Chris to push it (no redeploy needed).
  Token renewal due 2027-09-27; Chris has a calendar reminder for 2027-09-20.

## 7. Smoke, fires and air quality: Air quality LIVE 2026-09-28 05:37 (`2b4b204`); fires LIVE 2026-09-28 (`afc3e8f`, deploy fec14efe)
- **State:** pushed and deployed; live page == `web/index.html` (and terms). First job run 12:30Z on `a3735af`: pnw 251
  stations (4 temporary), sierra 194 (31), utco 116 (6), imw 110 (7), ne 251 (0); each "24 backfilled", grid new; the
  72 h history is full after 3 runs (~13:00Z). Live check in the in-app browser (sierra): Yosemite temporary monitors
  in a Moderate patch. Observation: at page open the radar loop preloads 144 frames (~20 s here), and any data file
  asked for meanwhile (AQ included) waits behind it; pre-existing, not changed.
- **Where things are:** spec (decisions, parameter ledger) `docs/superpowers/specs/2026-09-27-air-quality-layer-design.md`;
  plan `docs/superpowers/plans/2026-09-27-air-quality-layer.md`; data check `python smoke_research/aq_check.py <region>`;
  local preview `smoke_research/aq_serve.py` (BlackwaterLabs `.claude/launch.json` "aq-preview", port 8795).
- **Open for Chris (none blocking):** the spec's judgment calls (grey after 3 h; trend 5 µg/m³ and 20 %; click radius
  100 km; overlay opacity .55); AirFire's one-hour NowCast lag on temporary monitors (`ANOMALY_LOG.md`); the AirNow
  data-exchange form (he sends it if he wants); Missoula's AQI-50 episode ~2026-09-25 not cross-checked.
- **Deferred minors (final review):** a region's grid can lag an hour (store `lm2 or lm` in `build_grid`); a store with
  `v: 1` but the wrong shape crashes every run (only after an unbumped schema change); the trend can describe an older
  hour than the card's AQI and still shows on stale stations.
- **Phase 2 fires: LIVE 2026-09-28** (`afc3e8f`, merged fast-forward into `main` 15:38; on GitHub under `a545b31`;
  deploy version fec14efe, which also shipped the slope layer). Live page == `web/index.html` (curl + diff, 18:30).
  First capture runs (00:15Z on `afc3e8f`, then every 15 min, no failures): pnw ~185 fires / 125 perimeters, sierra ~90 / 13,
  utco ~74 / 17, imw ~72 / 39, ne 8 / 3; FIRMS 170–600 and NGFS 3–50 hotspots per region.
  Spec `docs/superpowers/specs/2026-09-28-fires-layer-design.md` (decisions 1–9, ledger, "Activity rule: alternatives");
  plan `docs/superpowers/plans/2026-09-28-fires-layer.md`; check `python smoke_research/fires_check.py <region>`; preview
  `smoke_research/fires_serve.py` (port 8796; restart after `build_web.py`). The worktree, branch and preview entry are removed.
  Observed after release: both perimeter layers are edited more often than every 15 min (01:17 and 01:26 UTC at a 01:30
  check), so every run re-downloads perimeters; the stamp rule rarely saves a fetch.
  **Deferred for Chris (before next fire season, none blocking):** incremental NGFS window merged per feature;
  `link_hotspots` spatial prefilter and a hotspot cap; keep the last good incident list per source 1 h when WFIGS/CWFIF
  fail; write `perimeters.js` only when polygons change; hotspot canvas sits under perimeter fills (hotspot tooltip
  unreachable inside a perimeter; fix: own pane); a fire under 0.5 acre shows "0 acres"; two NGFS paging cases log nothing.
  **Phase 3 smoke forecast: LIVE 2026-09-29 14:17 (`f9f3ad3`, on GitHub since 13:54 via the ski session's push; deploy
  version 733253b1; live page == `web/index.html`, checked by curl + diff and in the in-app browser with real R2 data).**
  Built and released in one session without review stops (Chris's brief, `smoke_research/NEXT_SESSION_hrrr_smoke.md`);
  the session report lists every decision taken on his behalf with what it costs if wrong.
  - What: `smoke.py` (hourly job, after freezing level) turns HRRR `MASSDEN` 8 m for f01-f48 of the newest complete
    00/06/12/18Z run into 48 lossless WebP frames in alternating slots `a`/`b`, one value series (128 x 128 x 48, tenths of
    ug/m3) and `data/smoke.js`; builds only when a new run's f48 index exists (51 R2 writes per run per region, <= 32k a
    month). Page: third layer in Smoke & fires, own player, badge bottom-right, AQI-category colours with a light-smoke
    band (2-9 ug/m3), PNW masked north of the model's edge (18 % of the window, dashed line), click-anywhere value and
    48 h curve. Spec (decisions 1-12 with alternatives and cost if wrong, ledger, data-check results, RRFS switch plan):
    `docs/superpowers/specs/2026-09-28-hrrr-smoke-layer-design.md`; plan `docs/superpowers/plans/2026-09-28-hrrr-smoke-layer.md`.
  - Data check (run 2026-09-29 00Z): geometry 100 % (drawn values within their 4 nearest model points, ecCodes' own
    coordinates), frame colours 100 % of pixels; monitors check was a clean evening (Sierra 179 sites, PNW 244, none
    >= 35.5 ug/m3): Spearman 0.13 / -0.30 overall, +0.36 at the 5 smoke-affected PNW sites, no shift wins; logged in
    `ANOMALY_LOG.md`. Figures: `smoke_research/checks/smoke_check_sierra.png`, `smoke_check_pnw.png` (gitignored).
  - Two reviews (fresh subagents) found: integer cells vs frame categories (fixed: tenths, EPA truncation); a
    never-uploaded build followed by a newer run could write into the live slot (fixed); run-out branch left the last
    frame up (fixed). Preload of 48 frames at once hit ERR_NO_BUFFER_SPACE beside the radar loop (fixed: chained).
  - **Open for Chris (none blocking):** the judgment calls in the spec ledger (floor 2, light band, opacity .65, hours
    shown from now - 30 min, 10 km cells); HMS column smoke later (decision 5); RRFS switch plan (decision 6); re-run
    `python smoke_research/smoke_check.py pnw` on a smoky day for a real skill number.
  - **First hourly run on the new code (2026-09-29 21:04 UTC, run 36630757627), all five regions built HRRR 18Z into
    slot `a`, 39.2 MB each:** pnw peak 933 ug/m3 (f07), 82 % of the window in the model, 8 s (runner cache warm);
    sierra 966 (f31), 47 s; utco 47 (f05), 38 s; imw 296 (f31), 48 s; ne 12 (f42), 20 s. R2 lines: 102-116 files
    updated per region (the 48 frames + values + smoke.js among them; the hourly job's usual files are the rest), 11-17
    unchanged. Expected from here: `already on the map` each hour until a run's f48 is posted (~1 h 50 min after 00/06/12/18Z),
    then one build per run into the other slot.

## 8. Point-panel sunrise/sunset 12 h swap: fixed 2026-09-28 (`4a4fdcb`, pushed; live since the air-quality deploy)
- Nothing open. `tests/test_map_suntimes.py` runs the `// BEGIN sunTimes` block under node against NOAA's calculator.
- Open for Chris (optional): (1) push race: his 05:20 push of `main` also carried the air-quality merge made 3 min after
  the sunrise build; proposed rule, not yet in `CLAUDE.md`: sessions hand over `git push origin <sha>:main` for the commit
  they tested. (2) capture #180 (2026-09-28 10:30 UTC) failed once on pypi.org read timeouts in `pip install` (next run
  fine); optional hardening: `--retries 10 --timeout 60` on the pip step, pinned versions.

## 6. Station-label lag fix: live (`9ffc919` pushed; deployed 2026-09-27 09:50, version 620d4f28)
- Zoom 9+ froze 1.4-4 s per zoom (1,047 permanent tooltips in PNW precip). Now divIcon labels for stations in view only.
- After the deploy the live page matched the local build exactly (checked with curl + diff). Only open item: Chris tries a scroll-wheel zoom.
- Not watched: animated (scroll-wheel) zoom, because the in-app browser pane was hidden (timings used `animate: false`).

## 9. R2 Class A budget: done 2026-09-29 (`a545b31`, live since 2026-09-28 18:26); one reading left for Chris
- How it works now: `CLAUDE.md`, "How it runs". Before/after: ~775k Class A per 31-day month, now ~630k incl. fires
  (capture ~115 PUTs/run, hourly ~300; GitHub-schedule duplicate hourly runs exit, seen 3 times 2026-09-29).
- Open: Chris reads the radar bucket's 24 h Class A in the dashboard after 2026-09-29 23:00 UTC (clean of the slope
  upload): ~20k expected from the measured pipeline plus whatever `smoke.py` and the snow model add (not measured).
  Far above ~25k would mean something is uncounted; the free 1 million/month is per account.

## 12. HANDOFF: snow-conditions tracker (started 2026-09-28) (tracked handoff from PR #2-#4, merged here 2026-09-28)
Spec: `docs/superpowers/specs/2026-09-28-snow-conditions-model-design.md` (read it first). The project is a
snow-surface model for skiing that will be its own site (snow.blackwaterlabs.org) on the same repo, Actions and R2.

### Done (2026-09-28, cloud session)
- `snow/archive.py`: the season archive, run last in the hourly job for regions with `"snow": True` (`pnw` only).
  Hourly `HH.json.gz` and one `daily.json.gz` per day under `regions/pnw/snow/archive/<date>/`, uploaded by `r2sync`
  (immutable). `values.read_grid` reads the click-anywhere grids back.
- `snow/avyproducts.py`: full avalanche.org forecast products per zone, saved per version per day. The product endpoint's
  shape is unverified from the cloud session (api.avalanche.org is blocked by the session's egress policy): the files
  are stored raw, so check the first day's `products/*.json` on R2 after the hourly job runs and note the real keys here.
- `snow/observations.py`: NAC observation API, runs only with `NAC_OBS_ORIGIN` set (an origin NWAC/NAC gives us). Paths
  and parameters unverified; test with `NAC_OBS_ORIGIN=... python -m snow.observations` once granted.
- Tests: `tests/test_snow_archive.py` (10). `tests.yml` now installs numpy.

### Done (2026-09-29, cloud session)
- `snow/lattice.py` + `snow_static.yml` (workflow_dispatch): the 100 m UTM 10N terrain lattice over NWAC's area
  (`snow/snow_config.yaml` `lattice`, bbox 124.9-120.0 W, 45.2-49.0 N) from 20 USGS 1 arc-second tiles
  (prd-tnm.s3.amazonaws.com, reachable from the cloud session; 63 s, 4267 x 3850 cells, 39 MB npz). Elevation,
  Horn slope, aspect (-1 flat), band (0/1/2 by 4000/6000 ft, Stevens Pass's bands everywhere for now), avalanche
  zone id (rasterized from the avalanche.org map layer; needs api.avalanche.org, so only the Actions build has it).
  Checked: Leavenworth 356 m, Stevens Pass 1246 m, Rainier cell 4371 m. Output `pnw/snow/static/lattice.npz` + `.json`.
- `snow/solar.py`: NOAA sun position, Meinel-Laue clear-sky direct, cosine of incidence on the cell, Kasten-Czeplak
  cloud factor, `daily_mj` (arrays), a placeholder `refreeze_index`. Parameters in `snow_config.yaml` `solar`.
  Checked: Dec 21 noon at Leavenworth 18.96 deg; Jan 15 30 deg slope N 0.5 / S 14.0 MJ/m2, flat 6.1; Jul 1 flat 32.9.
- `forecast.snow_fields`: NDFD sky cover, dewpoint, wind speed at every step to 48 h into `data/snowvals/`
  (never uploaded), packed into `daily.json.gz` as `ndfd`. Untested against tgftp (blocked here); guarded so the map
  layer cannot be affected. Check the first daily file for an `ndfd` key.
- Tests: `test_snow_solar.py` (8), `test_snow_lattice.py` (3); 155 total.
- First hourly run with the archive (branch dispatch, run 36508840159, pnw 18:38 PDT 2026-09-28): `forecast: snow fields
  sky x16, td x16, wspd x16`; `archive 2026-09-28: 18:44K, daily:537K, obs 0, products +35`; 37 new objects in R2.
  So the product endpoint answers for all 35 zones (about 1.5 MB/day in all). The next run's log prints the product's
  top-level keys (`products: NWAC <zone> keys: ...`): copy them into the spec.
- `snow/forcing.py`: archive window grids -> lattice cells, points -> cells, station records -> zone x band means.
- `snow/store.py`: R2 (or local) access for the daily run: lattice, archive days, state.
- `snow/state.py` + `snow.yml` (09:20 UTC daily, `workflow_dispatch` with a date): the surface-state model. Per cell:
  class, days since fresh snow, hn24 (MRMS liquid x snow fraction from the HRRR freezing level x SLR from band
  temperature), solar since fresh (cloud from NDFD sky), wind hours above the surface's transport threshold (NDFD 10 m), rain flag,
  melt days, refreeze index, SNODAS depth. Classes and priority in the module docstring; parameters and their
  bounds in `snow_config.yaml` `state` (all judgment-call placeholders). Writes `<r>/snow/state/latest.npz`
  (carried forward), `<date>_cls.npz`, `<date>.json` and `latest.json` (class fractions by zone x band x aspect octant).
  Tests `test_snow_state.py` (4): storm -> sun crust south / powder north -> wind -> dust on crust -> no snow; spring
  corn -> isothermal; forcing from a fake archive day. 163 tests.

### Waiting on Chris
- Email to forecasters@nwac.us (draft given in chat 2026-09-28): telemetry API access, observation feed access.
- Merge `claude/fervent-maxwell-q8kphc` so the hourly job on main keeps the archive going (a run was dispatched from
  the branch on 2026-09-29 to start it: check `pnw/snow/archive/<date>/` on R2 and the `products/*.json` shape).
- Nothing: merged (PRs #2, #3, #4, 2026-09-29), R2 Paid is active, the lattice is on R2 (run 36512081004: 20 tiles,
  59 s, zones rasterized), and the model ran for 2026-09-28 (run 36512417396: 1 hourly file, precip max 0.21 in,
  freezing level 8120-13270 ft, `no_snow 100%`, 828 s of which 795 s solar; the binned solar lookup that replaced the
  cell-by-cell integral takes ~15 s for the lattice). `snow.yml` now runs itself at 09:20 UTC; a run whose saved
  state is already at or past the date does nothing (`--force` steps again).

### Done (2026-09-29 afternoon, cloud session: items 1-5 of the build list)
- Wind direction (`ds.wdir.bin`) in the archive; the model keeps lee (loaded) and windward (scoured) hours by aspect
  (`wind_sector_deg` 60) and has classes `wind_loaded`, `wind_scoured` beside `wind`.
- Canopy on the lattice from ESA WorldCover 2021 (10 m class 10 averaged to the cell; four tiles, reachable from the
  cloud session; checked Hoh 100%, Enchantments 0%, Leavenworth 3%, Stevens base 21%). Treeline per zone from the
  canopy (`snow_config.yaml` `lattice.treeline`), near band 600 m below it; fixed 4000/6000 ft where no cut.
  `snow static` rerun 2026-09-29 21:22 UTC (run 36632763515, 88 s): treeline for 8 zones, ids 3020-3022 and 3032 at
  1900 m, 3023 at 2000 m, 3024 and 3030 at 2200 m, 3029 at 2300 m (west side low, east side high; NWAC's "above
  treeline" edge is 6000 ft = 1830 m at Stevens). Zone names for those ids: `pnw/snow/static/zones.json` on R2.
  Zones without a cut use the fixed 4000/6000 ft bands. `static/zones.js` (the page's polygons) is up.
- Ledger (`snow/ledger.py`, `<r>/snow/ledger/ledger.json`), LLM passes (`snow/llm.py`: extraction of observations,
  weak-layer snapshots and notes from the day's products and NAC observations; the brief from the ledger and the
  state summary; Claude API, JSON-schema output, model `SNOW_MODEL` default `claude-opus-5`), scoring
  (`snow/score.py`, residual records), the orchestrator `snow/daily.py` as `snow.yml` step 2. Key: Actions secret
  `BW_SNOW_MODEL` (console key "Blackwater SnowModel", **expires 2027-07-31**: make a new key in the console and update
  the secret); model: repository variable `BW_SNOW_MODEL` = `claude-fable-5-1` (2026-09-29). Without a key the step
  logs "skipped" and still writes ledger and brief files.
- Trip log: `snow/trips.json` in the repo (a list of obs-shaped records; the page's form writes one to paste);
  records for a day become `trip` records and are scored like observations.
- Site outputs: every state and brief file also as `.js` (`window.SNOW_STATE`, `SNOW_CLS`, `SNOW_BRIEF`, `SNOW_INDEX`,
  `SNOW_ZONES`), a Web Mercator class PNG per day (`state/<date>_cls.png`, bounds and palette in `_cls.js`),
  `state/index.js` (dates). The page: `snow.html`, `build_snow.py` (-> `web_snow/`, gitignored), `wrangler_snow.toml`
  (Worker `snow`, deploy `npx wrangler deploy --config wrangler_snow.toml`, whose `routes` attach
  snow.blackwaterlabs.org like taxes/roaring; workers.dev is off). Chris deploys. **LIVE 2026-09-29 16:00** (version
  29cd6c2c, `f23edea`). Until a run writes `state/index.js` the page says "has not published a day yet": the 09-28 run
  predates the `.js` outputs, so the first day it shows should come from the 09-30 09:20 UTC run (for 09-29).

### Done (2026-09-29 evening, cloud session): replay and fit
- `snow/replay.py`: re-runs the model offline over a date range on a subset of the lattice (`Subset`: windows around
  chosen cells, 1-D arrays the model steps directly; `day_forcing` takes a subset and locates SNOTEL sites on the full
  lattice). Forcing cached per (day, subset, wind thresholds) under `snow/work/replay/`. `python -m snow.replay --start
  --end --lat --lon` prints the class at a point and in its window, day by day.
- `snow/fit.py` + `snow_fit.yml` (by hand): coordinate descent over every `state` parameter with bounds and max_step,
  loss = confidence x (1 - share of the residual's neighbourhood cells in the observed class) over every residual that
  names a cell (coordinates or gazetteer place; zone-group residuals do not take part), replayed from SPINUP (10) days
  before the first residual. Needs MIN_RESIDUALS (30). Writes `fit/<date>.json` to R2; `--apply` rewrites the values
  in `snow_config.yaml` (comments and bounds kept) and appends `param` ledger records. Apply from a session, commit,
  and merge; the workflow only proposes. Tests `test_snow_fit.py` (4): a fit recovers a lower sun-crust threshold.

### Done (2026-09-30, cloud session): terrain, wind exposure, station temperature field, albedo, settled split
- Lattice: `horizon` (16 directions, deg, to 10 km; azimuths in `lattice.json` `horizon_azimuths`), `sx` (8 octants,
  Winstral shelter index to 300 m, negative exposed), `svf` (sky view, percent). 19 s on the full lattice. Checked
  against an exact ray-march at six points (within a few degrees; a twisting canyon differed 9 deg at 8 directions,
  hence 16) and by sun hours: Colchuck Lake gets no direct sun on Dec 21 and 7.8 h on Mar 20; Alpental base 2.1 h on
  Dec 21. `python -m snow.sunhours --lat --lon --date` prints sunrise/sunset on terrain for a point, to compare with
  ShadeMap or SunCalc (blocked from the cloud session; Chris to spot-check a few places). **Rerun `snow static`.**
- Solar: the day's direct sun is cut by the share the terrain blocks (`solar.terrain_factor`, a per-latitude table of
  direct energy by sector and sun elevation); diffuse (a tenth) is not.
- Wind: NDFD speed scaled per cell by the shelter index toward the wind's octant (`wind_sx_per_deg`, clamped).
- `snow/tfield.py`: the station network's own daily max/min field (every station with 12+ hourly readings in the
  archive; per-zone linear fit in elevation, pooled where a zone has under 6 stations spanning 500 m; residuals by
  inverse distance squared to 40 km on a 1 km grid). Replaces the band means when 20+ stations reported. The night
  fit's slope is logged per zone (`tfield: ... night lapse (C/km, + = inversion)`), and `tmin_resid_c` rides in the
  forcing as the cold-pool field. Kriging with a fitted variogram is the upgrade once the season shows the
  residuals' structure.
- Model: albedo ages from `albedo_fresh` to `albedo_min` (absorbed energy scaled to `albedo_ref`); under a canopy
  `canopy_lw_fraction` of what the trees absorb reaches the snow as longwave; `settled` is 2-7 days and
  `settled_late` 8-14 (`settled_days`); page classes updated. Tests `test_snow_terrain.py` (5); 329 in all.

### Literature review (2026-09-30, cloud session)
- `snow_research/lit_review.md`: synthesis of three agent-written notes (`lit_models.md`, `lit_interpolation.md`,
  `lit_products_obs.md`) against the model as built, with a 19-row ranked adoption table and a gap analysis of the
  physical processes still missing. Finding: no public product maps a ski-surface class by aspect at sub-km scale, and
  nothing published scores human observations against a surface model or extracts them with an LLM; the loop is ours
  to validate. Most journal sites were blocked from the cloud session, so the figures are from abstracts (each note
  lists what it could not verify).

### Done (2026-09-30, cloud session): lit-review items 1-8
- Wind transport by surface (`wind_mph_dry` 18, `wind_mph_wet` 22; crusts never): `day_forcing` counts hours above
  both thresholds (`wind_h`, `wind_h_wet` and the lee/windward pairs), `step` picks per cell by yesterday's class
  (`WET_SURFACE`, `NO_TRANSPORT`). Replay caches are keyed by both thresholds (old caches are simply rebuilt).
- `tfield`: residuals interpolated in the elevation-aware distance d^2 = dh^2 + (k dz)^2 (`tfield_vertical_k` 15), per
  station over its reach window on the regular lattice (no coarse grid any more); on nights whose fit is flatter than
  `tfield_inversion_lapse` (-2 C/km) the lapse is refitted on the stations above the warmest 200 m bin, or the free-air
  `lapse_c_per_km` is anchored there (`_fit_night`; logged as `tfield: inversions:`); daily leave-one-out MAE for max
  and min logged (`tfield: leave-one-out MAE`) and written into the day's `SNOW_STATE` summary as `tfield`.
  **Watch the first winter runs for this line**: 1.0-1.5 C is the literature's good range; above 2 C means the fit or
  the reach is wrong for that day.
- Albedo: USACE 1956 form (`albedo_cold_a/b`, `albedo_melt_a/b`, melting when the cell's max is at or above 0 C),
  `state.albedo_aged`; `albedo_decay_per_day` removed. `lapse_c_per_km` 6.5 -> 4.5, bounds [3, 7].
- Solar: `solar.daily_components_binned` (direct, diffuse, global on the flat; direct scaled by 1 - cloud, diffuse takes
  the rest of the Kasten-Czeplak total) and `solar.terrain_irradiance` (direct x terrain factor + diffuse x sky-view +
  (1 - svf) x `terrain_albedo` 0.5 x global); `day_forcing` uses them, so a walled-in north cell now gets its diffuse.
- Observation records (`snow/llm.py` schema): `moisture`, `wind_effect`, `spatial_precision_m`, `source_tier`;
  layers keyed by `buried` + CAAML `grain` (`ledger.layer_key`); `score.py` uses the record's precision as the
  neighbourhood radius; `assimilate.py` weights by tier (`TIER_WEIGHT`, to move into `snow_config.yaml` once fitted).

### Next, in order (from `snow_research/lit_review.md`, "Ranked adoptions"; items 1-8 done above)
0. Look at the first real `state` runs (Nov): does `hn24_cm` agree with `snotel_hn24_in` by band (the forcing carries
   both); does the freezing-level phase split put rain where SNOTEL depth fell.
1. Snow level per hour from rate, wet-bulb and cold pool, with the `upside_down` storm flag (9); sun crust as absorbed
   energy split from melt-freeze (10); surface hoar and facet accumulators feeding the layer ledger (11).
2. Precipitation drift from QPF with the SNOTEL ratio (12); Gaussian assimilation kernel and a confidence field (13);
   cold-pool mask (14); SLR wind term (15); canopy interception (16); corn clock (17).
3. Season two: own SWE mass balance and satellite snow line (18); kriging for the error map (19).

### Gotchas
- The cloud session's network policy blocks api.avalanche.org and nwac.us; add them to the environment's allowed
  domains (or run those checks from a PC).
- The archive keys a day by the region's local date (TZ from `hourly.yml`); the daily file is written by the first
  run of the day that finds none in R2, so its 74 h SNOTEL series covers the previous three days.
