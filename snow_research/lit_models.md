# Physically based snow-surface models and ski-condition products: a review against our design

Written 2026-09-30 for the snow-conditions tracker (spec `docs/superpowers/specs/2026-09-28-snow-conditions-model-design.md`,
rules in `snow/state.py`, parameters in `snow/snow_config.yaml`). Method: web search, plus the primary page where the sandbox
allowed it. The proxy blocked nearly every journal and product site (AMS, Copernicus, Wiley, ScienceDirect, SLF, NVE, OpenSnow,
CAIC, Avalanche Canada), so unless a row says "read", the numbers below come from search excerpts of abstracts or of papers
that cite the source. Section (d) lists what could not be checked at all.

## (a) Sources

| Source | What it is |
|---|---|
| Lehning, Bartelt, Brown, Fierz 2002, SNOWPACK Part III, Cold Reg. Sci. Technol. 35 | Forcing, new-snow density regression (air T, surface T, RH, wind), thin-layer (surface hoar) formation |
| Lehning et al. 1999, CRST 30 | Station-network operational SNOWPACK at SLF |
| Lehning et al. 2006, Alpine3D, Hydrol. Process. 20 | Distributed SNOWPACK: terrain radiation, drifting snow |
| Vionnet et al. 2012, Crocus in SURFEX v7.2, Geosci. Model Dev. 5 | Metamorphism laws, 3-band albedo, wind-drift compaction, surface hoar as added mass |
| Vernay et al. 2022, S2M reanalysis, ESSD 14 | Operational Crocus geometry: massif x 300 m bands x aspects x slopes 0/20/40 deg |
| Guyomarc'h and Merindol 1998, Ann. Glaciol. 26 | Driftability index; thresholds 4 m/s (fresh) to 12-15 m/s (wet, refrozen) |
| Liston and Elder 2006, SnowModel, J. Hydrometeorol. 7; Sproles et al. 2013, HESS 17 | MicroMet/EnBal/SnowPack/SnowTran-3D, 1 m to 1 km; run over the Oregon Cascades |
| Marks et al. 1999 (iSnobal); Hedrick et al. 2018, WRR; Meyer et al. 2023, GMD 16 | Two-layer energy balance; ASO Sierra at 50 m; HRRR-iSnobal ~100 m |
| Tarboton and Luce 1996, UEB; Jordan 1991, SNTHERM.89, CRREL SR 91-16 | One-layer with snow-age albedo (BATS form); CRREL multilayer research model |
| Essery 2015, FSM 1.0, GMD 8; FSM README on GitHub (read); Mott et al. 2023, Front. Earth Sci. 11 | Switchable process options; albedo constants; FSM2oshd operational at 250 m over Switzerland |
| Noah-MP options table; NWM description; SNODAS/NOHRSC model (Carroll et al. 2001) | BATS/CLASS albedo; 1 km Noah-MP in the National Water Model; 1 km three-layer model behind SNODAS |
| Morin et al. 2020, CRST 170 | Status review of Crocus, SNOWPACK, SNOWGRID, seNorge in operations; forecaster overlays incl. modelled surface hoar |
| Horton, Nowak, Haegeli 2020, NHESS 20; Herla et al. 2024, NHESS 24; snowpack.avalanche.ca | SNOWPACK on the 2.5 km HRDPS grid, flat plus 38 deg N/E/S/W; public dashboard |
| CAIC, AMS 2014 abstract; CAIC experimental Snowpack Dashboard | In-house WRF (4 km, 2 km nests) driving SNOWPACK in Colorado |
| Saloranta 2012, seNorge, The Cryosphere 6; NVE snow-maps note | 1 km daily single-layer model; "skiing conditions" map from precip, temperature, snow state, depth |
| OpenSnow support pages (Powder Quality, PowderFinder) | Per-location score from totals, timing, SLR, wind, temperature, recent snow |
| Minder, Durran, Roe 2011, J. Atmos. Sci. 68 | Cascades snow line hundreds of m below free air; mean drop 170 m over three years of storms |
| Minder and Kingsmill 2013, JAS 70 | Same in the Sierra; blocking, melting-induced cooling, melting-layer depth |
| Lundquist et al. 2008, J. Hydrometeorol. 9; Jennings et al. 2018, Nat. Commun.; NOAA HMT / Johnston et al. 2017, JTECH 34 | 50 % rain at 1.5 C; maritime threshold <= 1.0 C, humidity controls; bright band 100-300 m below 0 C |
| Roebber et al. 2003, WAF 18; Baxter et al. 2005, WAF 20; Alcott and Steenburgh 2010, WAF 25 | SLR classes <9, 9-15, >15; US mean ~13; Alta mean 14.4, SLR vs crest temperature and wind |
| USACE 1956, Snow Hydrology; VIC CalibrateSnow docs | Albedo decay alpha_fresh * A^(t^B); A,B = 0.94, 0.58 accumulating, 0.82, 0.46 melting |
| Ozeki and Akitaya 1998, Ann. Glaciol. 26, 35-38 | Sun crust: surface cooling -50 to -100 W/m2 while >200 W/m2 shortwave is absorbed below |
| Mitterer and Schweizer 2013, The Cryosphere 7 | Wet instability when isothermal and net input >200 kJ/m2/day or >1.2 MJ/m2 over 3 days |
| Fierz et al. 2009, International Classification for Seasonal Snow | Standard codes: sun crust, melt-freeze crust, rain crust, wind-packed, surface hoar |
| Li and Pomeroy 1997, J. Appl. Meteorol. 36 | 10 m thresholds: fresh dry 7.5, aged dry 8.0, wet 9.9 m/s; dry threshold quadratic in T, ~7 near -25 C, 9.4 near 0 C |
| Link and Marks 1999, JGR 104; Ellis et al. 2010, HESS 14; Hardy et al. 2004; Pomeroy et al. 2009, Hydrol. Process. 23 | Beer's-law canopy transmittance (k ~0.5 conifers); canopy longwave enhancement tied to shortwave extinction |
| Storck, Lettenmaier, Bolton 2002, WRR 38 | Oregon Cascades interception up to ~60 % of snowfall; maritime unloading |
| Dozier and Frew 1990, IEEE TGRS 28 | Horizon angles and sky-view factor from a DEM |
| Lundquist, Pepin, Rochford 2008, JGR 113; Daly, Conklin, Unsworth 2010, Int. J. Climatol. 30 | DEM cold-air-pool mask; valley decoupling |
| Minder, Mote, Lundquist 2010, JGR 115 | Windward Cascades annual mean lapse 3.9-5.2 C/km |
| Winstral, Elder, Davis 2002, J. Hydrometeorol. 3 | Sx maximum upwind slope |
| Stossel et al. 2010, WRR; Horton, Bellaire, Jamieson 2014, CRST 97 | Surface hoar: clear humid nights, cold surface, wind 1-2 m/s; size from latent heat flux |
| Helfricht et al. 2018, HESS 22; Wayand et al. 2015, WRR | Settling front-loaded in the first hours, hourly new-snow density medians 54-83 kg/m3; Snoqualmie Pass reference dataset |

## (b1) Snowpack models that produce a surface state

SNOWPACK (SLF) is a 1-D finite-element model with explicit microstructure: grain size, dendricity, sphericity and bonds evolve
by empirical laws, so it grows surface hoar as a new layer when the latent-heat flux deposits enough mass, forms melt-freeze
crusts when liquid water refreezes, and reports grain type per layer. New-snow density is a regression on air temperature,
surface temperature, humidity and wind, not a temperature-only SLR. Alpine3D runs it per DEM cell (100 m research runs are
common) with terrain shading, reflected shortwave and a saltation-suspension drift module. SLF's station system runs hourly
at about 100 stations and forecasters get map overlays, including modelled surface hoar (Morin 2020). Crocus (Meteo-France)
is similar but its operational geometry is deliberately coarse: massifs, 300 m bands, aspects, slopes 0, 20, 40 deg. Its
albedo is three spectral bands from grain size and impurities in the top 3 cm; wind drift rounds and compacts the top layers
through the Guyomarc'h-Merindol driftability index; surface hoar is mass added to the top layer. SnowModel (Liston) is the
usual choice for distributed hydrology in the Cascades: MicroMet interpolates stations with lapse rates and terrain wind
corrections, EnBal does the energy balance, SnowTran-3D moves snow; no grain type. iSnobal is a two-layer energy-balance
model, the engine behind ASO's Sierra SWE maps at 50 m and the HRRR-iSnobal chain; it gives surface temperature, melt and
liquid water, not stratigraphy. UEB is one layer plus a snow-age state for albedo (BATS form). SNTHERM is CRREL's multilayer
research model with radiation penetration and grain growth. Noah-MP (National Water Model, 1 km CONUS) and JULES are
land-surface schemes with BATS or CLASS albedo aging and no surface class. SNODAS's model is three layers at 1 km and we
already ingest it. FSM (Essery) is the compact middle, five switchable options, and FSM2oshd is Switzerland's operational model
at 250 m.

Operational status for our terrain: nothing publishes a physically modelled snow surface for the Cascades. SNODAS and the NWM
run at 1 km but expose mass and depth. Avalanche Canada's SNOWPACK chain on the 2.5 km HRDPS grid is described as covering
"neighbouring U.S. states" (check whether Washington is in the domain). CAIC has driven SNOWPACK with its own WRF in Colorado
since 2013. In the Sierra, ASO/iSnobal is operational for water supply, not surface condition.

What these models represent that ours does not: surface hoar; wet-snow metamorphism and refreezing of liquid water as the
crust process (rather than a rule on band minimum); albedo tied to grain size and temperature rather than days; a transport
threshold that depends on the surface (loose vs crusted); canopy longwave from warm trunks; and radiation as a net budget
(shortwave in, longwave out), which is what decides melt, refreeze and sun crust.

## (b2) Products for skiers and forecasters

OpenSnow's Powder Quality is a per-location score from forecast totals, night vs day timing, SLR, wind, temperature and recent
snowfall, three bars per day; PowderFinder is a map search over forecast and reported totals. It is a forecast heuristic by
resort or saved point, not a terrain-resolved state. seNorge (NVE) publishes a 1 km daily "skiing conditions" map from
precipitation, temperature, its snow-state field and depth; single layer, no aspect. Norway's regobs and Canada's Mountain
Information Network are observation platforms. Canada's model side is the public snowpack.avalanche.ca dashboard: SNOWPACK
profiles per 2.5 km cell for flat and 38 deg N/E/S/W, summarised into new snow, wind slab, persistent layer and wet snow
problems (Herla 2024). CAIC's experimental Snowpack Dashboard is the Colorado equivalent. SLF's public maps are fresh snow and
depth; modelled surface hoar overlays are for forecasters. Windy and snow-forecast.com display NWP snowfall and depth. I found
no product that maps a ski-surface class (powder age, sun crust, corn timing) by aspect at sub-kilometre scale; "corn timing"
exists only as advice (east faces soften around 09:00, then south, then west).

## (b3) Process literature

Snow level. Minder, Durran and Roe 2011 is the snow-line paper (the 2008 QJRMS "climatology of small-scale orographic
precipitation" by the same group is about precipitation patterns): the mountainside snow line sits hundreds of metres below
the free-air snow line, 170 m on average over three years of Cascades storms, from latent cooling by melting of
terrain-enhanced snowfall, adiabatic cooling of forced ascent and hydrometeor melting distance. Minder and Kingsmill 2013 find
the same in the Sierra and tie the size to blocking and precipitation rate. Separately, the free-air bright-band snow level is
usually 100-300 m below the 0 C level (NOAA HMT). At the surface, Lundquist 2008 gives 50 % rain at 1.5 C and Jennings 2018
puts maritime thresholds at or below 1.0 C, with humidity the main control.

Snow-to-liquid ratio. Roebber 2003: 1650 events, ratios 1.9 to 46.8, classes heavy (<9), average (9-15), light (>15);
predictors are column temperature and humidity plus compaction by surface wind and amount. Baxter 2005: US mean near 13,
lower in warm maritime areas. Alcott and Steenburgh 2010: Alta mean 14.4, with SLR tied to crest-level temperature and wind.

Albedo. USACE 1956 curves, carried into VIC as alpha = alpha_fresh * A^(t^B), A, B = 0.94, 0.58 while accumulating and 0.82,
0.46 while melting (t in days): slow decay for cold snow, fast once melt starts. FSM relaxes albedo from 0.8 toward 0.5 with
e-folding 1000 h cold and 100 h melting, refreshed by 10 kg/m2 of new snow. BATS (UEB, Noah-MP) ages faster near 0 C.

Sun crust and melt-freeze. Ozeki and Akitaya 1998 reproduced sun crust in a wind tunnel: the surface loses 50-100 W/m2 to
the sky while more than 200 W/m2 of shortwave is absorbed just below, and capillary-held meltwater refreezes into a thin ice
layer. Sun crust is therefore a cold, clear, sunny-day product, distinct from a melt-freeze crust, which needs bulk surface
melt then a night freeze. Mitterer and Schweizer 2013 give the wet end a scale: isothermal instability follows net daily
energy input above 200 kJ/m2 or a 3-day sum above 1.2 MJ/m2.

Wind transport. Li and Pomeroy 1997: 10 m thresholds 7.5 m/s (fresh dry), 8.0 (aged dry), 9.9 (wet or icy); the dry
threshold is quadratic in air temperature, lowest near -25 C (~7 m/s), 9.4 m/s near 0 C as grains sinter. Guyomarc'h and
Merindol 1998 span 4 m/s for fresh snow to 12-15 m/s for wet or refrozen surfaces. Winstral 2002's Sx is the standard shelter
term.

Canopy. Beer's law tau = exp(-k LAI), k about 0.5 for conifers (Hardy 2004); Link and Marks 1999 and Ellis 2010 use it in
energy-balance snowmelt under canopy. Pomeroy 2009: sunlit trunks run warmer than air and the longwave enhancement scales
with the canopy's shortwave extinction. Storck 2002, Oregon Cascades: interception up to ~60 % of snowfall, released mostly as
meltwater drip, with mass release on wind and warming.

Terrain and temperature. Dozier and Frew 1990 define horizon angles and the sky-view factor from a DEM and scale the diffuse
and terrain-reflected terms by it. Lundquist 2008 gives a DEM-only cold-air-pool mask (flat slope, local depression,
percentile elevation); Daly 2010 shows those valleys decouple from free-air warming. Minder, Mote and Lundquist 2010:
windward Cascades annual mean lapse 3.9-5.2 C/km, not 6.5, and melt timing moves a month between the two.

## (c) Comparison to our approach

Where we match practice. Scoring at zone x band x aspect is the geometry Crocus runs operationally and Avalanche Canada
displays; a 100 m lattice is finer than any operational avalanche product and equals Alpine3D research runs. Terrain shading
by 16 horizons, canopy transmittance as a fraction, Winstral Sx, a per-day station lapse fit with residual interpolation
(MicroMet does the same with a fixed lapse), a snow-line offset below the freezing level, temperature-gated canopy load and
Kasten-Czeplak cloud scaling are all standard forms. Rain-then-refreeze as a crust and days-since-snow classes are how
forecasters talk, even if no model states them that way, and the operational models stop at grain type and leave "is it
still soft" to people; our observation-driven fit is the right way to get those thresholds.

Simplifications with a known better form, ranked by value over effort:

1. Rain-snow split (value high, effort low). `rain_line_margin_ft` = 1000 ft folds two offsets together: the free-air
   melting layer (0 C to snow level, 100-300 m) and the mesoscale terrain lowering (170 m mean in the Cascades, more in
   heavy precipitation), 300-450 m together, so 1000 ft is the low side. Keep the value, raise the upper bound to ~1600 ft,
   and add a second gate from the station field: cells above ~1.5 C during precipitation get rain regardless (Lundquist
   2008; Jennings 2018 maritime <= 1.0 C). Cite Minder 2011 in the note instead of "literature".
2. Albedo (value high, effort low). Our 0.03/day is temperature-blind. Adopt alpha = 0.85 * A^(t^B), A,B = 0.94, 0.58
   when the band max is below 0 C, 0.82, 0.46 otherwise, t = days since a resetting snowfall (FSM resets at 10 kg/m2,
   about 1 cm SWE). At 8 days this gives 0.69 cold and 0.51 melting where our line gives 0.61 for both; the sun-crust and
   corn rules will feel it. Two parameters replace one.
3. Wind transport (value high, effort low). Make the threshold depend on the surface: 7.5-8 m/s (17-18 mph) for dry loose
   snow, 9.9 m/s (22 mph) for wet or icy snow (Li and Pomeroy), down to 4 m/s for very fresh snow (Guyomarc'h). Our 25 mph
   on the exposure-corrected NDFD wind is above all of them, so we under-count wind on cold dry snow and over-count it on
   crusts, which should not transport at all. Suggest ~18 mph for fresh/settled, ~22 for rain_wet/melt_freeze, no count on
   crust classes; the temperature quadratic can come later.
4. Lapse fallback (value medium, effort trivial). `lapse_c_per_km` 6.5 should be ~4.5 with bounds [3, 7] (Minder 2010). It
   only matters when the station fit fails, which is on the stormy days that matter.
5. Sun crust as an absorbed-energy budget (value high, effort medium). Convert `solar_crust_mj` from incident to
   (1 - alpha) * incident with the albedo of item 2, and split the two crusts by weather: sun crust when absorbed shortwave
   since snowfall passes a threshold and the nights were clear (Ozeki and Akitaya; our `crust_tmin_c` = -8 lower gate fits
   this), melt-freeze when the band max is above `melt_tmax_c` and the refreeze index is high. The current `crust_tfull_c`
   = 0 upper gate blurs the two. Mitterer's 200 kJ/m2 per day net input is the calibration point for the isothermal rule.
6. Surface hoar class (value medium for skiers, high for the layer ledger; effort low-medium). We archive night sky,
   dewpoint and wind already. Flag it on clear nights (sky under ~0.3), wind 1-2 m/s (Stossel 2010), small dewpoint
   depression, cold band min. Skiers notice it (fast cold powder, then a buried weak layer) and the ledger's layer records
   would get a model-side origin. Horton 2014 sizes it from latent heat flux if a flag is not enough.
7. SLR (value medium, effort low). Our 8 at 0 C rising 1 per degree to a cap of 20 is Roebber-shaped. Add wind after
   Alcott and Steenburgh (reduce SLR at high crest wind, bounded), and use Roebber's bins (<9, 9-15, >15) for the ledger's
   density observations. The SNOWPACK regression adds humidity, which NDFD dewpoint could supply.
8. Sky-view factor (value medium, effort low, the horizons exist). `diffuse_fraction` 0.10 is isotropic and unshaded; scale
   it by Dozier and Frew's sky-view factor from the 16 horizons and add a terrain-reflected term (1 - V) * alpha * global,
   which matters in spring bowls.
9. Cold-air-pool mask (value medium, effort medium). Lundquist 2008's DEM classification as a lattice attribute would let
   `tfield` carry a negative tmin residual only into pool-prone cells instead of everything inside the IDW radius.
10. Canopy (value low, effort low). Keep `canopy_solar_tau`; Beer's law needs LAI, which WorldCover fraction is not. Cite
    Storck 2002 for interception magnitude and maritime drip unloading (supports a large `tree_load_decay` in warm spells),
    and Pomeroy 2009 for `canopy_lw_fraction` scaling with shortwave extinction, which the (1 - tau) * canopy factor already
    does.
11. Settlement (no change). Helfricht 2018 confirms settling is front-loaded; `settle_days` = 2 is fine as a class boundary.
    Hourly new-snow density medians of 54-83 kg/m3 are a check on `slr_at_0c` = 8 (125 kg/m3), which is the warm maritime end
    and plausible near 0 C.

## (d) Could not verify

- The VIC equation form alpha = alpha_fresh * A^(t^B) is from memory of the VIC docs; A, B and the USACE origin are from
  excerpts. Check UW-Hydro/VIC `docs/Documentation/CalibrateSnow.md` before use.
- Li and Pomeroy's dry-snow quadratic: only the constant (9.43 m/s) and the endpoints are confirmed; the linear and quadratic
  coefficients are not.
- Minder 2011's 170 m is from an abstract excerpt; I could not confirm the reference height (free-air snow line vs 0 C). The
  "100-300 m below 0 C" bright-band figure is from a NOAA HMT news page.
- Ellis 2010 and Link and Marks 1999 transmittance values: not extracted, so the "0.1-0.4" range in our config note is
  unverified from here.
- Roebber's class boundaries and counts, Baxter's PNW pattern and Alcott and Steenburgh's wind relation are from excerpts.
- Whether Avalanche Canada's domain includes Washington, and whether CAIC's SNOWPACK product is still live: both sites blocked.
- "AvyFx" and "Snowbound" as modelling products: no evidence. "Avy" is NWAC's forecast app (display only); Snowbound is a
  resort-report app. A MeteoSwiss or SLF public "snow quality" map: not found.
- The Dozier and Frew sky-view integral is not reproduced here; take it from the paper before coding.
- Ozeki and Akitaya's flux numbers and Mitterer and Schweizer's energy thresholds are from abstract excerpts.
