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

## Waiting on Chris
- Email to forecasters@nwac.us (draft given in chat 2026-09-28): telemetry API access, observation feed access.
- The hourly job must run once from main (or this branch) to confirm the archive lands in R2:
  `https://radar-files.blackwaterlabs.org/pnw/snow/archive/<date>/daily.json.gz`.

## Next, in order
1. NDFD sky cover, dewpoint and wind speed into `forecast.py` for the archive only (no map layer): `ds.sky.bin`,
   `ds.td.bin`, `ds.wspd.bin`, next 48 h at 3 h steps, 64 px grids in `daily.json.gz`.
2. Terrain lattice (`snow/lattice.py`): ~100 m cells from the 1/3 arc-second NED in UTM 10N/11N, per cell elevation,
   slope, aspect octant, NLCD canopy fraction, NWAC zone (from the map-layer polygons), elevation band. Built once
   on a PC (downloads are big), stored in R2 under `pnw/snow/static/`.
3. Solar term (`snow/solar.py`): clear-sky irradiance on the inclined cell by day and hour, times NDFD cloud fraction;
   overnight refreeze index from cloud, dewpoint, wind, band minimum temperature.
4. Surface-state model (`snow/state.py`, parameters in `snow/snow_config.yaml`): winter powder aging first.
5. Ledger and the two LLM passes (`snow/ledger.py`, `snow/brief.py`): extraction with structured output, layer tracking,
   the brief from the ledger. `ANTHROPIC_API_KEY` as an Actions secret; `snow.yml` daily workflow.
6. `snow.html` and its Worker; then a `SNOW` global and layer group in `map.html`.

## Gotchas
- The cloud session's network policy blocks api.avalanche.org and nwac.us; add them to the environment's allowed
  domains (or run those checks from a PC).
- The archive keys a day by the region's local date (TZ from `hourly.yml`); the daily file is written by the first
  run of the day that finds none in R2, so its 74 h SNOTEL series covers the previous three days.
