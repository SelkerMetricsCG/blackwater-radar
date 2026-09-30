# Snow-conditions model: literature comparison and gap analysis (2026-09-30)

Three research notes in this folder were written by separate agents from web searches on 2026-09-30, each against
the model as built (`snow/state.py`, `snow/tfield.py`, `snow/solar.py`, `snow/assimilate.py`, `snow/score.py`,
`snow/llm.py`):

| File | Covers |
|---|---|
| `lit_models.md` | Snowpack models with a surface state (SNOWPACK, Crocus, Alpine3D, SnowModel, iSnobal, FSM, SNODAS); ski products; process papers (snow line, albedo, wind transport, SLR, crusts, surface hoar, canopy) |
| `lit_interpolation.md` | Station temperature, wind, humidity and precipitation interpolation in terrain (PRISM, GIDS, MicroMet, TopoWx, kriging); cold pools; localised assimilation of point snow observations |
| `lit_products_obs.md` | Products that map ski conditions (OpenSnow, Snow Signals, seNorge, Avalanche Canada); observation schemas (regobs, MIN, UAC, NAC); observer and forecaster bias; weak-layer databases; LLM extraction |

Caveat that applies to all three: the session's egress proxy blocked nearly every journal and product site, so the
numbers come from abstracts and citing papers, and each note lists what it could not verify. Treat a figure as a
pointer to the paper, not as read from its tables.

This file is the synthesis: what exists, where the model matches practice, the ranked list of changes, and my own gap
analysis (Part A, written before the notes were read, kept as a check on them).

## Bottom line

Nothing public does what this model does. Every consumer product found (OpenSnow's Powder Quality, Snow-Forecast,
Windy, WePowder, Powderchasers) rates snowfall amount per resort or point, with no aspect, band or crust state. The
one comparable product, Snow Signals "Alpine Intelligence", is closed, single-region (Tahoe) and its validation could
not be read. The operational physical models (SNOWPACK at SLF and Avalanche Canada, Crocus at Météo-France, SNODAS
and the National Water Model here) stop at grain type and SWE and leave "is it still soft" to the forecaster; none
runs publicly for the Cascades below 1 km. No published work scores human observations against a surface model or
extracts observations from avalanche-center prose with a language model. The observation-to-model loop is ours to
validate.

The model's structure is standard: zone × band × aspect is Crocus's operational geometry; per-zone lapse fit plus
interpolated residuals is GIDS (Nalder and Wein 1998), the method Stahl et al. (2006) chose for British Columbia and
the structure of MicroMet (Liston and Elder 2006); 16-direction horizons, Winstral Sx and a sky-view factor are the
textbook terrain terms; Kasten-Czeplak cloud scaling, a snow-line offset below the freezing level and a
temperature-gated canopy load are all forms in use.

What the review changes is mostly parameter shapes and a few missing processes, listed below in order of value over
effort. The first eight are each an afternoon; none needs new data.

## Ranked adoptions

| # | Change | Now | From | Effort |
|---|---|---|---|---|
| 1 | Wind transport threshold by surface: ~18 mph fresh and settled, ~22 mph wet, none on crust classes | one `wind_mph` = 25 for everything, above every published threshold | Li and Pomeroy 1997 (7.5-8 m/s dry, 9.9 wet), Guyomarc'h 1998 (4 m/s very fresh) | low |
| 2 | Elevation-aware distance in the residual interpolation, `d² = dh² + (k·dz)²`, k 10-20 | horizontal inverse distance to 40 km, so a valley cold-pool residual reaches the ridges | Frei 2014, Magnusson et al. 2014 (3-D localisation) | low, one line in `tfield._idw` |
| 3 | On inverted nights fit the lapse on stations above the inversion top; let the valley residuals carry the pool | one linear fit per zone, flattened by the valley stations | Pages and Miro 2010, Frei 2014 | low |
| 4 | Albedo `α = 0.85·A^(t^B)`, A,B = 0.94, 0.58 cold and 0.82, 0.46 melting | linear 0.03/day, temperature-blind (8 days: 0.61 either way; the form gives 0.69 cold, 0.51 melting) | USACE 1956 as used in VIC and FSM | low |
| 5 | Lapse fallback 4.5 °C/km, bounds [3, 7] | 6.5, used when the station fit fails, which is on storm days | Minder, Mote and Lundquist 2010 (3.9-5.2 windward Cascades; Tmax 6.1, Tmin 4.2) | trivial |
| 6 | Diffuse term scaled by the sky-view factor, plus a terrain-reflected term `(1−V)·α·global` | `diffuse_fraction` 0.10 isotropic and unshaded; `svf` on the lattice unused | Dozier and Frew 1990 | low |
| 7 | Log leave-one-out MAE for Tmax and Tmin daily | no error record | Stahl 2006, Frei 2014 (good methods: 1.0-1.5 °C in winter mountains; fixed lapse 1.5-2) | low |
| 8 | Obs record fields: `moisture` (dry/moist/wet), `wind_effect`, `spatial_precision_m`, `source_tier`; layer records keyed by `buried` date + CAAML `grain` | one 15-class `surface` enum; precision chosen inside `score.py`; layers keyed by free text | regobs, UAC Snow Characteristics, NWAC layer pages (`20220130_fcsf`) | low, schema only |
| 9 | Snow level from rate, wet-bulb and cold pool, per hour; `upside_down` storm flag | one fixed margin below the daily mean 0 °C height | Minder, Durran and Roe 2011 (170 m mesoscale lowering, more in heavy precipitation); Lundquist 2008; Jennings 2018 (rain above ~1.0-1.5 °C) | medium |
| 10 | Sun crust from absorbed energy `(1−α)·incident`, split from melt-freeze by night sky | incident MJ with a warmth gate; `crust_tfull_c` = 0 blurs the two | Ozeki and Akitaya 1998; Mitterer and Schweizer 2013 (200 kJ/m²/day net input for the isothermal rule) | medium |
| 11 | Surface hoar and near-surface facet accumulators, a `recrystallised` class, auto-raised `layer` record when buried | absent | Stössel 2010 (clear, 1-2 m/s, humid, cold), Horton 2014 | low-medium |
| 12 | Precipitation: NDFD/HRRR QPF as the drift, per-zone daily SNOTEL-to-drift ratio, MRMS kept for timing and the rain line | MRMS QPE alone; `snotel_hn24_in` computed and unused | Wen 2017 (MRMS −77 % vs SNOTEL in snow), Henn 2018, Lundquist 2019 | medium |
| 13 | Gaussian similarity kernel for assimilation and a per-cell confidence field | hard box (12 km, 150 m, 45°, 0.3 canopy) | Magnusson 2014, Cluzet 2022, Gruenewald 2013 | low |
| 14 | Cold-air-pool mask on the lattice (flat, concave, low percentile elevation), applied on inverted nights | residual reaches every cell in range | Lundquist 2008 | medium |
| 15 | SLR: wind reduction at high crest wind; density bins <9, 9-15, >15 for the ledger | linear in daily mean temperature | Alcott and Steenburgh 2010, Roebber 2003 | low |
| 16 | Canopy interception on `hn24` under trees | full `hn24` everywhere | Storck, Lettenmaier and Bolton 2002 (60 % of snowfall intercepted, maritime Douglas-fir) | low |
| 17 | Corn clock: softening hour per aspect from hourly absorbed irradiance against the overnight deficit | daily class only | own derivation; OpenSnow's three-period day for the brief's wording | medium |
| 18 | Own per-cell SWE mass balance anchored to SNOTEL; VIIRS or Sentinel-2 snow cover for the spring snow line | SNODAS depth at 1 km | spec's spring items | high |
| 19 | Kriging of residuals with a seasonal variogram, for the error map | IDW | Stahl 2006 (accuracy gain over GIDS small; the variance map is the reason) | medium, season two |

Not changed on the review's evidence: `settle_days` = 2 (Helfricht 2018: settling is front-loaded);
`canopy_solar_tau` as a fraction (Beer's law needs LAI, which WorldCover is not); `slr_at_0c` = 8 (the warm maritime
end, plausible near 0 °C); `rain_line_margin_ft` = 1000 (keep, raise the upper bound to ~1600 ft and add the
station-temperature gate of item 9).

## What the observation literature says about scoring

Expert local nowcasts agree with the regional forecast only 76 % of the time (71 % after observer bias; Techel and
Schweizer 2017), observers carry persistent high or low bias, and competence changes what gets reported as well as
how accurately (ISSW 2024, 26,021 regobs reports). Neighbouring centers describe the same snow in different house
styles (Techel et al. 2018). Consequences for `score.py`, `assimilate.py` and `fit.py`, all cheap: one report never
moves a cell group far (the 1.5× set-minimum nudge is right in kind; weight it by tier); absence of a report is no
evidence; the fit needs several concordant residuals per parameter (`MIN_RESIDUALS` 30 is fine, add a concordance
test); `confidence` drops on hedged phrases and the brief quotes rather than paraphrases. Citizen depth probes did
improve a distributed model in 62-78 % of ensemble runs (Community Snow Observations; Aragon 2025 cut SWE RMSE up to
23 %), which is the justification for assimilating trip reports at all.

## Corrections to the spec

- The snow-line paper is Minder, Durran and Roe 2011, JAS, "Mesoscale controls on the mountainside snow line". The
  2008 QJRMS paper cited in chat is a different one (small-scale orographic precipitation climatology).
- "AvyFx" does not exist; NWAC's app is "Avy", display only.
- The MRMS figure in `lit_interpolation.md` refers to about 1,400 stations; the archive holds fewer with 12+ hourly
  readings (the `tfield:` log line prints the count each day). The recommendation does not depend on the number.

## Part A. Gap analysis of the model as built (2026-09-30)

Written from the code in `snow/state.py`, `snow/tfield.py`, `snow/solar.py` and `snow/assimilate.py`, before the
literature reports below were read. Each item says what the model does now, what is missing, and what the fix would
use, so it can be checked against the literature comparison in Part C.

### A1. Physical processes

**Snow level from the freezing level (biggest single gap).** `step` uses `snow_level = fzl - rain_line_margin_ft`
with one fixed margin, and a fixed mixing band `rain_mix_ft`. The real snow level sits 200 to 500 m below the 0 °C
height and moves with three things the archive already holds: precipitation rate (heavy precipitation drags the snow
level down by melting-cooling the column; the hourly `mrms1` grids give the rate), the wet-bulb depression (dry air
lowers it by evaporative cooling; NDFD dewpoint is archived), and cold pools (easterly flow through the Cascade gaps and
valley inversions hold the Leavenworth and Methow valleys well below the free-air snow level; `tfield` already
computes `tmin_resid_c` and logs the inversion but `step` never reads it). Fix: hourly snow level = HRRR wet-bulb
0 °C height when available (HRRR carries it as a separate field; the freezing-level job reads only the 0 °C isotherm),
minus a rate term, minus a cold-pool term from `tmin_resid_c`; then phase per hour, not per day. The
freezing-level job (`freezing.py`) reads only `HGT` at the `0C isotherm`; a wet-bulb 0 °C height can be computed from
the HRRR pressure-level temperature and humidity in the same byte-range style `smoke.py` uses, and the National
Blend of Models publishes a snow-level element directly.

**Storm timing within the day.** The state advances once per day, so a storm that starts as rain and turns to snow
(right-side-up, the good case) is indistinguishable from one that starts cold and warms (upside-down, rain on new
snow). The archive has hourly `fz0` and `mrms1`, so the sequence is available. Fix: a `storm_trend` field (freezing
level change during hours with precipitation) and an `upside_down` class or flag when the snow level rose more than
a threshold while snow was falling; `hn24` should then split into snow that fell before and after the rise.

**Precipitation under-catch in the mountains.** MRMS QPE behind the radar horizon (east slopes of the Cascades, the
Pasayten, everything the Langley Hill and Camano beams overshoot) under-reads by a factor that varies with
elevation and storm direction. `day_forcing` computes `snotel_hn24_in` per zone × band and `step` ignores it. Fix:
per zone × band ratio of SNOTEL precipitation increment (or SNOTEL HN24 / modelled HN24) to MRMS at the SNOTEL
pixels, smoothed across zones, applied as a multiplier on `precip_in`; fall back to NDFD QPF where MRMS is zero
and the SNOTEL sites recorded precipitation.

**Snow-to-liquid ratio.** Linear in daily mean air temperature, capped. The ratio also falls with wind (riming and
fragmentation) and with in-cloud temperature rather than surface temperature; a daily mean hides a cold-front
passage. Fix: hourly temperature at the cell (lapsed from `tfield`'s hourly stations, or the NDFD `temp` grid) and
an hourly ratio, with a wind reduction above the transport threshold.

**Densification and settlement.** "Fresh", "settled", "settled_late" and "old" are set by days alone. New snow
settles faster when warm and under a load; a 30 cm cold storm skis like powder for a week, a 30 cm warm storm is
settled the next day. Fix: carry new-snow density (from the ratio) and a temperature-dependent settlement rate
(Anderson-type compaction: settlement proportional to load and exp(k·T)); "powder quality" becomes the depth of
snow below a density threshold rather than an age.

**Canopy interception.** Under trees the model reduces sun and refreeze but gives every cell the full `hn24`.
Storck, Lettenmaier and Bolton (2002, WRR, Umpqua NF) measured about 60 % of snowfall intercepted by mature
Douglas-fir canopy in the maritime PNW, most of it melting or dripping later. Fix: `hn24_under = hn24 · (1 − i ·
canopy)` with `i` a fitted parameter near 0.5, and the intercepted water added to `canopy_load` (the tree-debris
logic already exists).

**Surface hoar and near-surface facets.** Not represented at all, and they matter twice: as a ski surface
(recrystallised "loud powder" on shaded aspects after a clear cold week) and as the persistent weak layer once
buried. Both are predictable from the inputs the refreeze index already takes: surface hoar grows on clear, calm
nights when the dewpoint is above the snow-surface temperature (humid air, radiative cooling); near-surface facets
grow when the diurnal surface temperature swing is large (clear nights, sunny days, shallow snow). Fix: two
accumulators, `hoar_nights` and `facet_days`, a `recrystallised` class, and a ledger `layer` record raised
automatically when a hoar surface is buried by a `fresh` day, so the LLM layer tracker starts from a model guess.

**Rime and freezing fog.** Near-crest cells sit in cloud below 0 °C for days at a time in the Cascades and end up
with a rime crust. Detectable from NDFD sky 100 %, dewpoint depression near zero and a temperature below 0 °C at
the cell, with wind. Not modelled; a `rime` accumulator would be cheap.

**Energy balance instead of solar plus a warmth gate.** Crusting uses cumulative absorbed solar times a gate on
`tmax`; melt is `tmax > threshold and solar > 1 MJ`. This misses the warm-wind case (a sub-tropical flow with rain or
just warm humid wind melts more snow by turbulent flux than the sun does, in cloud) and the clear-night case
(strong longwave loss on a north aspect undoes a day of sun, so a north face at 1800 m stays dry while the model
accumulates solar). The lattice has a sky-view factor that nothing uses, so diffuse sky irradiance on cloudy days
and the terrain's longwave contribution are both dropped. Fix, in steps: (1) add the diffuse term with the sky-view
factor (cloudy days deliver 1 to 3 MJ of diffuse sun; today they deliver a fraction of the direct); (2) a daily net
longwave estimate from cloud, dewpoint and air temperature, subtracted from the absorbed solar so `solar_mj` becomes
a net-energy accumulator; (3) a turbulent term proportional to wind × (T − 0) × humidity. A full point energy
balance (SNOWPACK, Crocus, iSnobal) is not needed for a surface-class model, but a daily net-energy accumulator is
one array operation per term.

**Melt-freeze timing by aspect (the corn clock).** The model says "melt_freeze" for the day. Skiers want the hour.
`solar.irradiance` is hourly already; with the refreeze index as an overnight energy deficit and hourly absorbed
irradiance by aspect, the softening hour per cell falls out (east aspects around 09:00, south 11:00, west 14:00 in
March, shifting with cloud). Fix: `corn_hour` field from the first hour at which cumulative absorbed irradiance
exceeds a deficit proportional to the refreeze index; show it on the aspect rose.

**Crust breakability.** A rain crust and a sun crust are one class each. Whether a crust is supportable or
breakable is what decides the ski quality, and it depends on the water input (rain amount, melt amount) and the
depth of the subsequent refreeze (tmin, hours below 0). Fix: `crust_mm` (water that froze) and `crust_solid`
(refreeze index at formation) fields, with a breakable/supportable split at a fitted threshold.

**Wind transport threshold by snow age.** One `wind_mph` threshold for every surface. Fresh cold snow moves at
about 5 m/s, a day-old sintered surface at 8 to 10, a crust not at all. Fix: threshold rising with `days` and
suppressed on crust classes, so a windy day on old snow does not reclassify it to `wind`.

**Wind loading amount, not just hours.** `wind_lee_h` counts hours; the depth of the slab depends on how much
transportable snow was upwind. Fix: an erodible-snow budget on windward cells drained into lee cells along the
wind octant (a one-step Sx-weighted transfer), giving `loaded_cm`.

**Snow depth and the spring snow line.** Depth comes from SNODAS at 1 km, which does not resolve aspect, canopy or
wind redistribution and is known to be poor in the Cascades. The approach question (where does snow start) is the
one mode with no independent observation source in the archive. Fix: (1) our own per-cell mass balance,
`swe_mm` accumulated from `hn24` water and drawn down by the net-energy melt above, anchored to SNOTEL SWE per
zone × band; (2) VIIRS VNP10A1F (375 m, daily, needs an Earthdata token) or Sentinel-2 fractional snow cover on
clear days to correct the snow line, both already listed in the spec as spring work.

**Albedo.** Ages with days only. Rain and melt drop it faster than dry aging, and a dust event or forest-fire ash
drops it at once. Fix: reset the aging clock faster on `rain_wet` and `melt_freeze` days; MODIS/VIIRS albedo is
available but is a season-two item.

**Lapse rate.** `tfield` fits a lapse per zone from the stations, which is right. `step` still applies a fixed
`lapse_c_per_km` wherever the field is missing; the seasonal cycle of the lapse rate (steeper in spring, near-zero
or inverted in December) is in the archive to fit by month.

### A2. Modelling approach

**Interpolation.** `tfield` is elevation regression per zone plus inverse-distance-weighted residuals on a coarse
grid. This is the structure of MicroMet (Liston and Elder 2006), which is the standard forcing generator for
distributed snow models, and of GIDS (Nalder and Wein 1998). Kriging of the residuals would add two things: a
fitted range from the station variogram instead of the fixed `tfield_idw_km`, and a variance map that says where
the field is guesswork. With 60 to 150 stations, ordinary kriging of the residuals costs one small linear solve per
day. Regression kriging with more covariates (Sx, canopy, distance to crest, valley-bottom flag from the lattice)
is the next step and is what PRISM does with facets. Recommendation: keep the regression, replace `_idw` with
ordinary kriging of residuals (variogram fitted daily, exponential model), and carry the kriging variance into the
state as a confidence field.

**Wind.** NDFD 10 m wind scaled by Sx is a rough copy of the MicroMet wind model (which also curves the wind by
slope and curvature). Ridge winds under-read; the NWAC telemetry request is the fix, and until then the HRRR
80 m or 925 hPa wind would be a better ridge proxy than the NDFD 10 m grid.

**Assimilation.** `assimilate.nudge` moves the state of similar cells toward an observed class. The literature
does this with ensemble or particle filters over SWE, which does not transfer to a categorical surface state with
a handful of observations. What does transfer: a per-cell confidence (kriging variance plus days since an
observation within the similarity kernel) so the page can show where the model is unverified.

**Parameter fitting.** Coordinate descent on a categorical loss with bounds and step caps. Fine for a handful of
thresholds. Two additions: report the confusion matrix by class alongside the loss (which transitions are wrong,
not just how many), and hold out by place so a fit is not scored on the observations that drove it.

**Validation baselines.** No baseline yet. Persistence (yesterday's class) and a climatology (class by day-of-year
× aspect × band from the first season) are the two the model has to beat before the fit means anything.

### A3. Observation side

**Observation sources beyond NAC.** The NAC feed is blocked until the origin is granted. Other structured text the
LLM pass could read now: NWAC's public forecasts (already archived through avalanche.org), USFS Wenatchee and
Okanogan-Wenatchee trail and road reports, Stevens Pass and Mission Ridge snow reports (resort HN24 and base are
observations at a known point), WSDOT pass reports, and Chris's trip log. Each is a `source` field in the `obs`
record already.

**Snow-surface cameras.** The webcam list has ski-area and pass cameras. Frame-differencing or an LLM vision pass
on a daily frame gives snow-on-ground yes/no at a known point, which is exactly the spring snow-line observation
the model lacks. Free at the API's image rates for a few dozen cameras a day.

## Part B. How the notes and Part A line up

Part A and the three notes were written independently and agree on the large items: the snow level (A1 first item;
`lit_models` item 1), the wind threshold, the albedo form, surface hoar, the diffuse and sky-view term, canopy
interception, MRMS in snow, the elevation-aware residual distance and the kernel for assimilation. The notes add what
Part A lacked: the published threshold values and the papers to cite in `snow_config.yaml`'s parameter notes, the
observation-schema fields, and the finding that the loop itself is unpublished. Part A adds what the notes did not
raise: storm timing within the day (`upside_down`), crust breakability as a field, wind loading as an amount, the
corn clock, rime, resort and DOT reports as observation sources, and camera frames as a snow-line observation.

Where they disagree: `lit_models` says settlement needs no change (days as the class boundary); Part A wants a
density carried per cell. Both can hold: keep the day classes for the page, add density as a field once the ratio
and albedo forms are in, and let the residuals decide whether the class boundary should move to density.
