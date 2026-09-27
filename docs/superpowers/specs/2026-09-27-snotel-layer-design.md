# SNOTEL layer: design (2026-09-27)

Agreed with Chris in chat, 2026-09-27 08:07–09:29. Replaces the "SNOTEL as its own panel group" notes in `HANDOFF.md` item 3.

## Goal
One map layer that reads like NRCS iMap's Station/Basin Conditions view: SNOTEL stations, HUC6 basins, or both, for
snow water, snow depth, new snow over the last 12–72 h, water-year precipitation, soil moisture and soil temperature.
The new-snow number is what a skier means by "we got 14 inches last night".

## Decisions (Chris, 2026-09-27)
| # | Decision |
|---|---|
| 1 | Now & forecast order: Radar loop, **Weather stations**, Rain / snow totals, **SNOTEL**, Webcams, then the rest unchanged. |
| 2 | "Snowpack by basin" is renamed **SNOTEL** and leaves the Snow group; Snow keeps only SNODAS. |
| 3 | Modes: Stations / Basins / Stations & basins. |
| 4 | Basins only where NRCS defines a basin index (SWE and water-year precip, % of median). For other elements the basin outlines are **removed**, not greyed. |
| 5 | Snow depth, new snow, soil moisture and soil temperature are raw values (in, in, % water by volume, °F). NRCS publishes no medians for them (checked against the AWDB API 2026-09-27: only WTEQ and PREC return `median`). |
| 6 | Water-year precipitation stays as an element. |
| 7 | New snow = **storm total** (option B): the largest rise from a low point to a later high point inside the window, above a noise floor. Never negative. |
| 8 | SNOTEL markers come out of Weather stations entirely. |
| 9 | Weather stations keeps "New snow" from CoCoRaHS and HADS (134 sites in the live PNW file at 08:09); "New snow water" and the two SNOTEL % of median modes are removed. |
| 10 | Test sites for the new-snow check: Stevens Pass 791:WA:SNTL, Paradise 679:WA:SNTL, Alpine Meadows 908:WA:SNTL, Blewett Pass 352:WA:SNTL, Mt Hood Test Site 651:OR:SNTL. |

## What the reader sees
```
Now & forecast
  ☐ Radar loop
  ☐ Weather stations     Precipitation · New snow · Temperature · Wind
  ☐ Rain / snow totals
  ☐ SNOTEL (?)
      [ Stations ] [ Basins ] [ Stations & basins ]
      ○ Snow water equivalent        % of median
      ○ Snow depth                   inches
      ○ New snow                     inches   [12][24][36][48][60][72] h
      ○ Precipitation (water year)   % of median
      ○ Soil moisture                % water  [2][8][20] in
      ○ Soil temperature             °F       [2][8][20] in
      legend · "NRCS, as of <time>" · link to iMap
  ☐ Webcams
  …
Snow
  ☐ Modeled snow (SNODAS)
```
- Basins: HUC6 fill in the existing iMap bins (`BASIN_BINS` in `map.html`: ≥150, 130, 110, 90, 70, 50, <50 %) with a
  "112%" label on each basin.
- Stations: dots in the same colours as the basin fill for % of median elements, so a station that disagrees with its
  basin stands out. Raw-value elements use existing scales where one exists: snow depth reuses the SNODAS depth legend,
  new snow the current new-snow scale, soil temperature the Weather stations temperature scale. Soil moisture gets a new
  scale (judgment call, shown to Chris before release).
- In Basins-only mode the four stations-only elements are greyed with a "stations only" note, so the map is never blank.
- Missing data uses iMap's symbols: ⊖ observation missing, ⊗ median missing.
- Station popup: name, elevation, NRCS site link; SWE in inches and % of median; depth; new snow for all six windows;
  water-year precip and % of median, precip last 24 h; temperature now, high, low and sparkline; soil moisture and
  temperature at every depth the site has (including 4 and 40 in where present).
- Soil views include NRCS SCAN sites (about 12 in WA/OR/ID/MT). SCAN sites never appear in snow or basin views.
- BC pillows report daily, so they show at 24, 48 and 72 h and are absent at 12, 36 and 60 h.
- Hidden on the `ne` region (no SNOTEL). Sierra, Utah/Colorado and Inland Northwest get it (they have SNOTEL and basins).
- Saved defaults (`localStorage['radar.default']`) keep restoring: `lyBasins` on → SNOTEL on, Basins mode, element from
  the old `basinSel` (`swe` → SWE, `prec` → precip); Weather stations `stMode` `swe_pct` → SNOTEL on, Stations, SWE;
  `wy_pct` → SNOTEL on, Stations, precip; `swe` → Weather stations "New snow". New controls go into `DEF_CHECKS` /
  `DEF_SELECTS` or are saved explicitly.
- Help tips on Radar loop and Rain / snow totals that say "check SNOTEL under Weather stations" are rewritten.

## What runs behind it
- **`snotel.py`** (new), run by the hourly job before `stations.py`, one AWDB pull per run:
  - US SNOTEL, hourly, last 74 h: SNWD, WTEQ, PREC, TOBS, SMS and STO at −2, −8, −20 in (plus −4, −40 for popups).
  - SCAN, hourly, same window: SMS, STO (soil views only).
  - BC pillows, daily, last 4 days.
  - Daily WTEQ and PREC medians (`centralTendencyType=MEDIAN`), as `stations.py` does now.
  - Writes `data/snotel.js` → `window.SNOTEL`: `{updated, updated_t, date, windows: [12..72], soil_depths: [2, 8, 20],
    sites: [{id, name, net, lat, lon, elev, swe, swe_med, swe_pct, depth, new: {w: in}, wy, wy_med, wy_pct, p24,
    temp: {now, max, min, spark, t}, soil: {depth: {m, t}}, last}]}`.
  - Logs an accounting line: sites requested, returned, dropped and why.
- **`stations.py`** stops pulling SNOTEL and takes its records from `snotel.py`. SNOTEL stays in `stations.js`, so the
  Rain / snow totals interpolation and the click-anywhere readout keep working; `map.html` filters `src === 'SNOTEL'`
  out of the Weather stations markers. `WINDOWS` stays `[1, 3, 6, 12, 24]`.
- **Storm-total function**: one function, used for SNOTEL 12–72 h in `snotel.js` and for SNOTEL and HADS depth sensors
  at 1–24 h in `stations.js`, so the SNOTEL layer, Weather stations and the "New snow" interpolation agree. Its
  parameters (noise floor, spike filter) are read from `snotel_config.yaml`.
- **`basins.py`** unchanged.
- If `snotel.py` fails, `stations.py` carries on without SNOTEL (as today when `snotel()` fails) and the layer shows
  "SNOTEL data not available".

## New-snow check (gate before any map code)
Follows `~/.claude/verification-protocol.md`; this number is public.
1. Method card `snotel_check/METHOD.md`: what the storm total does, intuition, assumptions, failure modes, parameters,
   and a published reference on ultrasonic snow-depth sensor behaviour (with page), not a paraphrase.
2. Data: hourly SNWD, WTEQ and PREC at the five test sites, 2025-10-01 to 2026-05-31.
3. Noise floor, fitted from data: (a) summer bare-ground scatter; (b) the storm total computed in mid-winter dry spells
   (no WTEQ and no PREC rise). The floor is set from (b); both are reported.
4. Spike check: count one-hour jumps that revert. If they matter, a short rolling median goes in; before/after shown.
5. Independent check per storm, from different sensors: implied new-snow density = WTEQ gain (pillow) ÷ storm total
   (ultrasonic). Expected roughly 5–20 %. Storms far outside go to Chris with rival explanations and are logged in
   `radar/ANOMALY_LOG.md`, never absorbed into a parameter.
6. Figure (MATLAB style, muted colours): each site's winter depth record with about six storms marked; per storm, options
   A (end minus start), B (storm total) and C (now minus window low) side by side, and the implied density.
7. `snotel_config.yaml`: every parameter with value, units, source category, how derived, and an empty `approved:`.
8. Known-answer pytest cases on synthetic traces: clean storm, storm then settling, one-hour spike, noise only, melt.

**Gate:** Chris approves the figure and the config values before the pipeline and panel are built.

## Testing and release
- pytest (network blocked): storm-total known answers; record builder against a saved AWDB response; saved-default
  migration.
- Local run of `snotel.build()` and `stations.build()` directly (never `capture_all()` with `r2.env` present, which
  uploads to the live bucket). Record file size and run time.
- Browser check of every mode, element, window and soil depth on a local build, via a proxy that serves local
  `data/snotel.js` and passes the rest to R2; also `ne` (layer hidden) and one other region.
- Release: Chris pushes; one hourly run publishes `snotel.js` in each region; then Chris runs `build_web.py` and
  `npx wrangler deploy`. Deploying the page first would leave the layer empty for up to an hour.
- Afterwards: update `radar/CLAUDE.md` (globals list, the "SNOTEL hourly data is pulled for the last 26 h" rule) and
  retire `HANDOFF.md` item 3.

## Judgment calls (flagged, Chris to confirm when shown)
- Soil depth buttons 2 / 8 / 20 in only; 4 and 40 in appear in popups only.
- Soil moisture reading exactly 0.0 % (seen at Beaver Pass −2 in on 2026-09-26): dead sensor or dry soil. Shown to Chris
  with the data before any filter.
- Soil moisture colour scale.

## Open items found while designing
- The live PNW `stations.js` (2026-09-27 08:09) has no BC pillows; the 2026-09-13 local copy had 20. Cause not yet
  checked.

## Out of scope
Reservoir and streamflow elements (iMap has them); % of average and period-of-record parameters; SCAN in snow views;
basin values for depth, new snow or soil.
