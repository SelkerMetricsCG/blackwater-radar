# Snow conditions model: design (2026-09-28)

Agreed with Chris in chat, 2026-09-28. The project behind snow.blackwaterlabs.org: a model of ski-snow surface
condition that runs every day from weather and terrain, scores itself against what people report, and tunes its
parameters on a slower clock. Everything below is the starting design; the parameter values are placeholders until
the first season's archive exists, and every one of them goes through the same verification protocol as
`snotel_config.yaml` (source category, derivation, alternative not chosen, approval date).

## Goal
Answer, for any point in the PNW window at any elevation and aspect: what is the snow surface like today, where is
the powder still good after a storm, where will corn be good and when, and where does the snow start for a spring
approach. Four modes, one model: the modes are views of the same per-cell state.

| Mode | Question | What decides it |
|---|---|---|
| Storm powder | where did the storm land, how dense, was it rained on | new snow, density, rain line, wind during the storm |
| Aging powder | where is it still soft N days later | days since snowfall, solar load by aspect, air temperature by band, wind after the storm |
| Spring pockets | which north-facing pockets are still dry | cumulative solar since last snow, refreeze history, no rain |
| Corn | when and where melt-freeze snow is good | overnight refreeze quality, morning solar by aspect, clouds, wind |
| Approach | where the snow starts, what the pack is doing | snow line (SNODAS, SNOTEL melt-out, VIIRS), isothermal pack, melt rate |

## Decisions (Chris, 2026-09-28)
| # | Decision |
|---|---|
| 1 | A model, not a conditions report: it runs from weather and terrain whether or not anyone observed anything. Observations are the residuals. |
| 2 | Recursive on two clocks: every day the run scores yesterday's prediction against yesterday's observations; parameters move only when enough residuals have accumulated, with a cap per step, and every change is logged with the residuals that drove it. |
| 3 | The LLM (Claude Opus 5 or Fable 5.1 through the API, from Actions with `ANTHROPIC_API_KEY`) interprets text and writes the brief. It never fits numbers. Its jobs: extract observations into structured records, track persistent weak layers across days, write model notes, write the daily brief from the ledger. |
| 4 | Memory is a dated ledger of structured facts with sources, never a brief that feeds the next brief. |
| 5 | Persistent weak layers are ledger records with lifetimes (a season if need be), never deleted mid-season. |
| 6 | Separate site (snow.blackwaterlabs.org), same repo and plumbing: the hourly job already fetches every input. No second pipeline. |
| 7 | PNW first (NWAC zones). Other regions follow by setting `"snow": True` in `region.py`. |
| 8 | Ask NWAC (forecasters@nwac.us) for telemetry API access and for the observation feed; never send an Origin header we were not given. |
| 9 | Free tier for everything but the API calls (well under $100 a season at one call per region per day). |

## Inputs and where they come from
| Input | Source | Already pulled by | Archive |
|---|---|---|---|
| New snow, SWE, depth, precip, air temp, soil (hourly, 74 h) | NRCS AWDB (`snotel.py`) | hourly | daily, full series |
| Station temp, wind, RH, precip, depth (HADS, NWS, CoCoRaHS) | `stations.py` | hourly | hourly compact + daily full |
| Freezing level, analysis and f3..f18 | HRRR via NOMADS (`freezing.py`) | hourly | hourly f0, daily all |
| MRMS QPE 1 h and 24 h | `mrms.py` | hourly | hourly 1 h, daily 24 h |
| NDFD snow, rain, gust, high, low | `forecast.py` | hourly | daily |
| SNODAS depth and SWE | `snodas.py` | hourly (daily product) | daily |
| Zone danger by day | avalanche.org map layer (`avalanche.py`) | hourly | hourly |
| Full forecast product: danger by elevation, problems with aspect/elevation rose, bottom line, discussion | avalanche.org product endpoint (`snow/avyproducts.py`) | new | per version per day |
| Observations (citizen and pro) | NAC observation API (`snow/observations.py`), gated on an allow-listed origin | new, blocked until granted | daily, last 3 days |
| Ridgetop wind | NWAC telemetry API (researcher access) | not yet | to add once granted; HRRR 10 m wind is the fallback and under-reads ridges |
| Sky cover, dewpoint, wind (overnight refreeze) | NDFD `ds.sky.bin`, `ds.td.bin`, `ds.wspd.bin` | not yet | to add to `forecast.py`, archive only (no map layer) |
| Snow cover (snow line) | VIIRS VNP10A1F daily 375 m (Earthdata token) | not yet | spring |
| Canopy fraction | NLCD tree canopy cover, static 30 m | not yet | lattice attribute |
| Elevation, slope, aspect | USGS 1/3 arc-second NED (the slope build's fallback dataset) | not yet | lattice |

## The terrain lattice
About 100 m cells over the PNW window from the 1/3 arc-second NED, in UTM so slope is in true ground metres
(`slope/slope_config.yaml` has the reasons). Per cell, static: elevation, slope, aspect octant, canopy fraction,
NWAC zone, elevation band (below treeline / near / above, by NWAC's zone definitions where published, else fixed
bands), sky-view or horizon angles later. Cells are grouped for scoring and display into zone × band × aspect
octant, which is the resolution the observations can support.

Clear-sky irradiance on the inclined cell (solar position, cosine of incidence, a simple atmospheric transmittance)
times the day's cloud fraction gives the solar term. Overnight net longwave loss is approximated from cloud
fraction, dewpoint and wind: clear, dry, calm nights refreeze the surface at air temperatures above 0 °C.

## Surface state
Per cell, carried forward day to day:
- `class`: fresh, settled powder, wind-affected, sun crust, breakable crust, rain crust, melt-freeze (corn window),
  isothermal, dust-on-crust, no snow
- `hn24`, `hn72` (cm), `density_new` (kg/m³ from SNOTEL SWE/depth increments and temperature during snowfall)
- `days_since_snow`, `days_since_rain`
- `solar_since_snow` (MJ/m²), `wind_since_snow` (hours above the transport threshold, by direction relative to aspect)
- `refreeze_last_night` (none / partial / solid), `melt_hours_today`
- `canopy_load` (snow on trees, from snowfall near 0 °C, released by wind or warming)
- `depth`, `swe`, `melt_rate` (from SNODAS and the nearest SNOTEL by band)

Transitions are rules with named parameters (first list, all placeholders):
`wind_transport_ms`, `settle_rate_per_day`, `solar_crust_mj`, `rain_line_margin_m`, `refreeze_hours`,
`refreeze_tmin_c`, `corn_melt_hours`, `isothermal_swe_loss_mm_day`, `tree_bomb_wind_ms`, `tree_bomb_tmax_c`.
They live in `snow/snow_config.yaml` in the `snotel_config.yaml` format, with bounds and a max step per fit.

## Ledger
`<region>/snow/ledger.json` in R2, append-only records, each with `date`, `kind`, `source`, `zone`, `band`, `aspect`,
and kind-specific fields:
- `obs`: an extracted observation (surface class seen, location, elevation, aspect, confidence, the source text id)
- `residual`: predicted class vs observed class for one obs, and the cell's state that day
- `layer`: a persistent weak layer (name, buried date, zones, bands, first and last mention, status active / dormant /
  healed, the product ids that mention it). Dormant after N days unmentioned; never deleted in season.
- `note`: an LLM model note with the evidence it cites (obs ids, product ids)
- `param`: a parameter change with the residuals that drove it
- `trip`: Chris's own trip record (the same fields as `obs`)

## Daily run (`snow.yml`, once a day after the daily archive exists)
1. Load yesterday's state and the archive for the last day.
2. Advance the state one day per cell.
3. LLM pass 1 (extraction): new products and observations → `obs` and `layer` records. Structured output, one call
   per region, the products and observations as documents.
4. Score: each new `obs` against the predicted class in its cell group → `residual` records.
5. Fit, only when due (N residuals or a week): adjust parameters within bounds and step caps → `param` records.
6. LLM pass 2 (brief): the last 2–3 weeks of the ledger plus today's state summary → the daily brief per zone and
   `note` records. Never yesterday's brief.
7. Write `snow.js` (state summary by zone × band × aspect, pockets, corn timing) and the state grid for the page.

## Site
`snow.html`, its own Worker and assets directory, custom domain snow.blackwaterlabs.org, data from the same R2 bucket
under `<region>/snow/`. Views: a timeline of days, zone cards with the aspect rose per band, the brief, the ledger of
layers, the trip log input. Later, a `SNOW` global and one layer group in `map.html`.

## Not in scope yet
Sun-angle-by-date terrain shading, resort snow reports, avalanche danger itself (NWAC's, shown as they publish it),
anything that scrapes NWAC.

## Verification
- The archive is the record: nothing in it is ever rewritten, and every model input comes from it, so any day can be
  re-run.
- Scoring is coarse on purpose (zone × band × aspect); per-cell output is displayed, band-level skill is what is claimed.
- Every parameter change is a ledger record with its evidence; the changelog is the audit.
- Tests in `tests/test_snow_*.py`, no network.
