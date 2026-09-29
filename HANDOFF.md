# HANDOFF: snow-conditions tracker (started 2026-09-28)

Spec: `docs/superpowers/specs/2026-09-28-snow-conditions-model-design.md` (read it first). The project is a
snow-surface model for skiing that will be its own site (snow.blackwaterlabs.org) on the same repo, Actions and R2.

## Done (2026-09-28, cloud session)
- `snow/archive.py`: the season archive, run last in the hourly job for regions with `"snow": True` (`pnw` only).
  Hourly `HH.json.gz` and one `daily.json.gz` per day under `regions/pnw/snow/archive/<date>/`, uploaded by `r2sync`
  (immutable). `values.read_grid` reads the click-anywhere grids back.
- `snow/avyproducts.py`: full avalanche.org forecast products per zone, saved per version per day. The product endpoint's
  shape is unverified from the cloud session (api.avalanche.org is blocked by the session's egress policy): the files
  are stored raw, so check the first day's `products/*.json` on R2 after the hourly job runs and note the real keys here.
- `snow/observations.py`: NAC observation API, runs only with `NAC_OBS_ORIGIN` set (an origin NWAC/NAC gives us). Paths
  and parameters unverified; test with `NAC_OBS_ORIGIN=... python -m snow.observations` once granted.
- Tests: `tests/test_snow_archive.py` (10). `tests.yml` now installs numpy.

## Done (2026-09-29, cloud session)
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
  temperature), solar since fresh (cloud from NDFD sky), wind hours above `wind_mph` (NDFD 10 m), rain flag,
  melt days, refreeze index, SNODAS depth. Classes and priority in the module docstring; parameters and their
  bounds in `snow_config.yaml` `state` (all judgment-call placeholders). Writes `<r>/snow/state/latest.npz`
  (carried forward), `<date>_cls.npz`, `<date>.json` and `latest.json` (class fractions by zone x band x aspect octant).
  Tests `test_snow_state.py` (4): storm -> sun crust south / powder north -> wind -> dust on crust -> no snow; spring
  corn -> isothermal; forcing from a fake archive day. 163 tests.

## Waiting on Chris
- Email to forecasters@nwac.us (draft given in chat 2026-09-28): telemetry API access, observation feed access.
- Merge `claude/fervent-maxwell-q8kphc` so the hourly job on main keeps the archive going (a run was dispatched from
  the branch on 2026-09-29 to start it: check `pnw/snow/archive/<date>/` on R2 and the `products/*.json` shape).
- After the merge: run the `snow static` workflow once (GitHub refuses to dispatch a workflow that has never been on
  main), confirm `pnw/snow/static/lattice.json` on R2 lists `zones`, then dispatch `snow` for a date with a complete
  archive day and read its log (class distribution, forcing line). Off season it should say mostly `no_snow`.
- Enable R2 billing (Chris, 2026-09-29: "let's just pay for it"); the archive is ~1.5 MB/day, the lattice 40 MB.

## Next, in order
0. Look at the first real `state` runs (Nov): does `hn24_cm` agree with `snotel_hn24_in` by band (the forcing carries
   both); does the freezing-level phase split put rain where SNOTEL depth fell. Wind direction (`ds.wdir.bin`) into
   the archive so wind can be scoured vs loaded by aspect.
1. Canopy fraction on the lattice (NLCD Tree Canopy Cover; mrlc.gov is blocked from the cloud session, try the
   MRLC geoserver WCS with a bbox from Actions or a PC) and per-zone elevation bands (NWAC's forecast pages).
2. Surface-state model: refinement after the first storms (the v1 is in `snow/state.py`) (`snow/state.py`, parameters in `snow/snow_config.yaml`): winter powder aging first.
3. Ledger and the two LLM passes (`snow/ledger.py`, `snow/brief.py`): extraction with structured output, layer tracking,
   the brief from the ledger. `ANTHROPIC_API_KEY` as an Actions secret; `snow.yml` daily workflow.
4. `snow.html` and its Worker; then a `SNOW` global and layer group in `map.html`.

## Gotchas
- The cloud session's network policy blocks api.avalanche.org and nwac.us; add them to the environment's allowed
  domains (or run those checks from a PC).
- The archive keys a day by the region's local date (TZ from `hourly.yml`); the daily file is written by the first
  run of the day that finds none in R2, so its 74 h SNOTEL series covers the previous three days.
