# Swell forecast: design (2026-10-15)

What is coming at the coast: NOAA's offshore wave model for the whole window seven days out, NOAA's nearshore wave
model (NWPS) for the beaches, a "Swell forecast" map layer with a time slider, the forecast drawn into every buoy's
popup beside its observed trace, and a "Surf beaches" layer that shows beach by beach what the swell does when it
refracts in. Chris asked for 1 and 2 of the three options and for beach-by-beach refraction (2026-10-15 17:39).
Same pipeline as the currents layer (`docs/superpowers/specs/2026-10-13-currents-flow-layer-design.md`).

## Sources (spiked 2026-10-15, all public domain)
- **GFS-Wave, west-coast 0.16° grid** on AWS `noaa-gfs-bdp-pds`: `gfs.<yyyymmdd>/<HH>/wave/gridded/gfswave.t<HH>z.wcoast.0p16.f<NNN>.grib2`
  with `.idx`; runs 00/06/12/18Z (f072 of the 18Z run was posted by 00:40Z); steps f000..f120 hourly, then 3-hourly to f384
  (the listing showed f000-f036 hourly; the job must read the listing). 272 KB per step; by byte range per field 9-22 KB:
  `HTSGW`, `PERPW`, `DIRPW` (combined), `WVHGT/WVPER/WVDIR` (wind sea), `SWELL`, `SWPER`, `SWDIR` for partitions 1-3
  (level "1 in sequence" ... "3 in sequence"), `WIND`, `WDIR`. Grid 25-50 N, 210-250 E (lon 0-360).
- **NWPS** (Nearshore Wave Prediction System, per forecast office) on NOMADS `pub/data/nccf/com/nwps/prod/wr.<yyyymmdd>/<wfo>/<HH>/CG<n>/`:
  one GRIB2 per run and grid holding all hours (145 steps, hourly to 144 h). `wfo` in `sew`, `pqr`, `mfr`; runs on demand (sew and
  mfr 00/12, pqr up to six a day). **CG1 is the coarse outer grid** (sew: 99 x 93 at 0.052° x 0.036°, about 4 km); the nests
  **CG2..CG5** are the nearshore grids (sew has CG2; pqr and mfr have CG2-CG5); sew CG1 is 15 MB, CG2 9.8 MB whole. The
  filter CGI `filter_wrnwps.pl` (vars `HTSGW PERPW DIRPW SWELL SWPER SWDIR WVHGT? WIND WDIR RIPCOP DSLM DIRC SPC`, `lev_surface`)
  returned a 5 MB subset for CG1 in under a second with `swh, shts (total swell height), dirpw, perpw`; the partitioned
  swell needs the sequence levels or the whole file (the implementer checks what the nest files hold). Also per-buoy
  2-D spectra text files (`spc2d_<id>_CG1`) for 46041, 46087, 46088, 46206.
- **Observed**: the site's `buoys.js` (NDBC, CDIP, ECCC, Backyard Buoys): Hs, period, direction, swell split, 24 h trace.

## 1. Scope
1. **Swell forecast layer** (`lySwell`, Coastal group): a canvas raster of primary-swell height (GFS-Wave everywhere,
   NWPS nests drawn on top where they exist and the run covers the hour), direction glyphs on a fixed screen spacing
   with length by period, a 3-hourly slider from now to +168 h with Play and opacity, legend in feet, a note with the
   run times and credit "NOAA GFS-Wave and NWPS (Seattle, Portland, Medford offices)". Click-anywhere: the three GFS-Wave
   partitions at that point and hour ("primary 8.2 ft at 15 s from WNW; secondary 2.6 ft at 9 s from SW; wind sea 1.3 ft")
   and the NWPS primary where the point is in a nest ("at the beach: 6.1 ft at 15 s from W").
2. **Buoy popups**: a 7-day chart (height, with period as a second trace) of the GFS-Wave point forecast at the buoy,
   drawn with the rivers chart idiom after the observed trace, so observed and forecast line up at "now".
3. **Surf beaches layer** (`lyBeaches`): markers at curated surf spots, coloured by the NWPS primary swell height at the
   slider's hour (grey when no nest covers the spot), label from zoom 9, popup with the spot's facing, the 72 h NWPS
   height/period/direction chart, the current partition line, and "offshore: <GFS-Wave at the nearest 0.16° cell>".
   The spot list (`surf_spots.json`) is the documented (not lore) subset of `coastal_research/user_needs.md` section 3:
   name, lat, lon, facing (degrees the beach faces), region note; each spot carries a `sample` point: the nearest NWPS
   water cell seaward of the beach (found by the module, cached in the index).
Out of scope now: the swell particle animation, Environment Canada's wave model, the spectral files.

## 2. Data modules
| Module | Slot | Writes |
|---|---|---|
| `swell.py` | hourly, after `currents` | `frames/swell/<cycle>/s<NN>.png` (one per 3-h step, NN = step index 0..56 for f000..f168), `data/swell.js`, `data/swell_points.js`, state `swell_cache.json` |
| `nwps.py` | hourly, after `swell` | `frames/nwps/<cycle>/h<NN>.png` (one per 3-h valid hour, up to 24 = 72 h from the newest run), `data/nwps.js`, `data/beaches.js`, state `nwps_cache.json` |

`swell.py`: newest GFS-Wave cycle whose f168 `.idx` exists; skip if unchanged. For each 3-hourly step: byte-range the 12
fields (3 partitions x height/period/direction, plus HTSGW/PERPW/DIRPW), read with cfgrib or eccodes from the fetched
bytes, bilinear onto a **0.04° window grid** (pnw: 235 x 352), encode one PNG with **three bands stacked vertically**
(partition 1 on top, then 2, then 3), RGB per band: R = height in 0.1 m (cap 25.5), G = period in 0.5 s (cap 63.5 s),
B = direction / 2 (0-179; 255 = nodata or no partition). Point series at every buoy in the region's `buoys.js`
(`data/swell_points.js` -> `{cycle, points: {<buoy id>: {t0, dt: 10800, p1: [[h_ft, per_s, dir], ...], p2, p3, hs: [...]}}}`),
sampled bilinearly. `data/swell.js` -> `window.SWELL = {cycle: "gfswave_t18z_20261015", updated, updated_t, bbox, nx, ny, step,
bands: 3, hours: [{t, file}], credit}`. 57 steps x 12 fields = 684 range requests, about 9 MB; the index must list f168.

`nwps.py`: for each office, the newest run on NOMADS whose nest files exist (`wr.<date>/<wfo>/<HH>/CG<n>/`); skip if all
unchanged. Download each nest GRIB2 whole (or through the filter CGI if it serves the partitions; implementer's call,
say which), read the primary swell (partition 1 if present, else total swell `shts` with `perpw`/`dirpw`) for 3-hourly
steps 0..72, composite nests onto the **0.01° window grid** (finer nest wins; the currents land mask applies), encode
as one band with the same RGB rule, `data/nwps.js` -> `window.NWPS = {runs: {sew: "t12z 2026-10-15", ...}, updated,
updated_t, bbox, nx, ny, step, hours: [{t, file}], credit}`. Beach series: `data/beaches.js` -> `window.BEACHES =
{updated, spots: [{name, lat, lon, facing, sample: [lat, lon], wfo, series: {t0, dt: 10800, p: [[h_ft, per_s, dir], ...]}}]}`
sampled at the spot's `sample` cell (nearest water cell of the finest nest within 3 km seaward along the facing; null
series when no nest covers it). Both modules: 20 s timeout, 2 tries, abandon a run on a missing piece and keep the old.

## 3. Serving and plumbing
`site_worker.js` serves `/<region>/(currents|swell|nwps)/<cycle>/<name>.png` from R2 under `frames/` (generalise the
currents route); `r2sync.py` uploads `frames/swell/` and `frames/nwps/` immutable like `frames/currents/`; `cloud.py`
prunes their cycles by the `tHHz_YYYYMMDD` stamp (cycle names: `gfswave_t18z_20261015`, `nwps_sew_t12z_20261015-pqr_t18z_20261015-mfr_t12z_20261015`).
`requirements.txt` already has cfgrib and eccodes.

## 4. Page
- `lySwell`: slider/Play/opacity in the Sun & shade idiom, `swellLabel`, `swellInfo`; a canvas raster layer: for the
  slider's valid time draw the GFS-Wave band-1 height as a colour fill (bilinear sampling of the 0.04° PNG; feet bins
  0, 1, 2, 3, 4, 6, 8, 10, 13, 16, 20+ on a muted blue-teal-amber-red ramp), then the NWPS PNG for the same valid time on
  top where valid (its nodata shows the GFS fill), then direction glyphs: an arrow every 28 screen px pointing where the
  swell travels (direction + 180°), length 8-24 px by period (6 s to 20 s). Decode PNGs through the Worker route like
  currents. Hour label: "Sat 7 AM · GFS-Wave 18Z, NWPS Seattle 12Z / Portland 18Z". Paused when off.
- Buoy popup: after the 24 h trace, "7-day swell forecast (GFS-Wave)": height line (feet) with period labels at local
  noon each day, the rivers chart idiom with hover; from `data/swell_points.js` loaded on demand.
- `lyBeaches`: circle markers coloured by NWPS primary height at the slider hour (or hour 0 when the swell layer is
  off), hollow when the spot has no nest; label "6 ft 15 s" from zoom 9; popup: name, facing as compass, "now" line,
  the 72 h chart, and the offshore GFS-Wave line. Legend shares the feet bins. Note: "NWPS runs twice a day (Portland
  more often); heights are open-water significant height, not face height" and the credit.
- Click-anywhere rows per scope §1. Helpers in `// BEGIN swellHelpers`: `decodeBand(px, nx, ny, band, x, y)`,
  `swellBin(ft)`, `arrowLen(per)`, `travelDir(deg)`, `compass` reused, `SWELL_BINS`.
- `lySwell`, `lyBeaches` in `DEF_CHECKS`.

## 5. Judgment calls (ledger)
| # | Decision | Value | Why |
|---|---|---|---|
| 1 | Offshore grid and horizon | 0.04° window grid, 3-hourly to +168 h | GFS-Wave is 0.16°; 4x oversampling keeps the fill smooth; 7 days is what surfers plan with |
| 2 | Nearshore grid and horizon | 0.01° window grid, 3-hourly to +72 h | NWPS nests are 0.5-1.8 km; beyond 72 h NWPS is just GFS-Wave refracted |
| 3 | Encoding | R height 0.1 m, G period 0.5 s, B direction/2, 255 nodata | exact decode without alpha; 25 m / 63 s caps never bind here |
| 4 | Height bins (ft) | 0, 1, 2, 3, 4, 6, 8, 10, 13, 16, 20 | the buoys layer's bins plus 1 and 3 ft for the small end surfers care about |
| 5 | Which swell is drawn | partition 1 (the primary, largest energy) | the number surf reports quote; the others are in click-anywhere and the charts |
| 6 | Beach sample point | nearest nest water cell within 3 km seaward along the facing | NWPS cells at the shoreline are land; the first water cell is the break's forcing |
| 7 | Glyph spacing and length | 28 px; 8-24 px for 6-20 s | readable at the site's zooms without a key |
| 8 | Spot list | documented spots only from `user_needs.md`, lore excluded | publishing lore as fact would mislead |

## 6. Tests and checks
`tests/test_swell.py` (idx parsing and byte ranges, GRIB decode from a fixture message, resampling, stacked encoding
round-trip, unchanged-cycle skip, point sampling), `tests/test_nwps.py` (run listing parse from an HTML fixture, nest
precedence, land mask, beach sample search, series shape), `tests/test_site_worker.py` (new routes), `tests/test_map_swell.py`
(node: decode, bins, arrow length, travel direction), `tests/test_r2_uploads.py` as needed. Checks for `CHECKS.md`: buoy
46041's forecast at hour 0 against its observed Hs/period; NWPS vs GFS-Wave at the same offshore point; a beach series
against the NWPS point output for the nearest buoy spectrum file.
