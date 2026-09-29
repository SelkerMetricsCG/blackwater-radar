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

## Waiting on Chris
- Email to forecasters@nwac.us (draft given in chat 2026-09-28): telemetry API access, observation feed access.
- Merge `claude/fervent-maxwell-q8kphc` so the hourly job on main keeps the archive going (a run was dispatched from
  the branch on 2026-09-29 to start it: check `pnw/snow/archive/<date>/` on R2 and the `products/*.json` shape).
- The `snow static` workflow was dispatched from the branch on 2026-09-29; confirm `pnw/snow/static/lattice.json` on R2
  lists `zones`.

## Next, in order
1. Canopy fraction on the lattice (NLCD Tree Canopy Cover; mrlc.gov is blocked from the cloud session, try the
   MRLC geoserver WCS with a bbox from Actions or a PC) and per-zone elevation bands (NWAC's forecast pages).
2. Surface-state model (`snow/state.py`, parameters in `snow/snow_config.yaml`): winter powder aging first.
3. Ledger and the two LLM passes (`snow/ledger.py`, `snow/brief.py`): extraction with structured output, layer tracking,
   the brief from the ledger. `ANTHROPIC_API_KEY` as an Actions secret; `snow.yml` daily workflow.
4. `snow.html` and its Worker; then a `SNOW` global and layer group in `map.html`.

## Gotchas
- The cloud session's network policy blocks api.avalanche.org and nwac.us; add them to the environment's allowed
  domains (or run those checks from a PC).
- The archive keys a day by the region's local date (TZ from `hourly.yml`); the daily file is written by the first
  run of the day that finds none in R2, so its 74 h SNOTEL series covers the previous three days.
