# Interpolation and assimilation of station data and point observations in complex terrain

Literature review for the snow-conditions tracker, 2026-09-30. Scope: how to turn ~1,400 hourly stations and a
handful of field reports into fields on 100 m cells over the Washington Cascades. Our current method is in
`snow/tfield.py` (per-zone lapse regression plus inverse-distance-squared residuals to 40 km) and
`snow/assimilate.py` (a report nudges cells with aspect within 45 deg, elevation within 150 m, canopy within
0.3, same side of the crest, weighted by distance). Full texts could not be fetched from any publisher host in
this session (see the last section); every number below comes from a paper's abstract or a citing paper's
summary, and is marked (abstract) or (secondary) where that matters.

## Sources

| Title | Authors, year | Venue / URL | What it is |
|---|---|---|---|
| Physiographically sensitive mapping of climatological temperature and precipitation across the conterminous United States | Daly et al., 2008 | Int. J. Climatol. 28:2031-2064, doi:10.1002/joc.1688 | PRISM: local climate-elevation regression with distance, facet, coastal and inversion-layer weights |
| A meteorological distribution system for high-resolution terrestrial modeling (MicroMet) | Liston and Elder, 2006 | J. Hydrometeorol. 7:217-234 | Barnes interpolation plus lapse rates, dewpoint lapse, terrain wind weighting |
| Spatial interpolation of climatic normals: test of a new method in the Canadian boreal forest | Nalder and Wein, 1998 | Agric. For. Meteorol. 92:211-225 | GIDS: regression on x, y, elevation plus inverse distance squared |
| Comparison of approaches for spatial interpolation of daily air temperature in a large region with complex topography and highly variable station density | Stahl et al., 2006 | Agric. For. Meteorol. 139:224-236 | 12 methods for daily Tmax/Tmin over British Columbia |
| Surface temperature lapse rates over complex terrain: lessons from the Cascade Mountains | Minder, Mote and Lundquist, 2010 | J. Geophys. Res. 115, doi:10.1029/2009JD013493 | Cascade lapse rates from COOP, soundings, a dense sensor network, MM5, PRISM |
| Altitudinal temperature lapse rates in an Alpine valley: trends and the influence of season and weather patterns | Kirchner et al., 2013 | Int. J. Climatol. 33:539-555 | Bavarian Alps lapse rates by season, weather type and slope |
| Automated algorithm for mapping regions of cold-air pooling in complex terrain | Lundquist, Pepin and Rochford, 2008 | J. Geophys. Res. 113, D22107 | DEM-based cold-pool map validated at Loch Vale, Pyrenees, Yosemite |
| Surface temperature patterns in complex terrain: daily variations and long-term change in the central Sierra Nevada | Lundquist and Cayan, 2007 | J. Geophys. Res. 112, D11124 | 37-sensor Yosemite network; when a lapse rate fails |
| Local atmospheric decoupling in complex topography alters climate change impacts | Daly, Conklin and Unsworth, 2010 | Int. J. Climatol. 30:1857-1864 | Cold pools decouple from the free atmosphere |
| Determining temperature lapse rates over mountain slopes using vertically weighted regression | Pages and Miro, 2010 | Meteorol. Appl. 17:53-63 | Lapse rates weighted by elevation band, Pyrenees inversions |
| Interpolation of temperature in a mountainous region using non-linear profiles and non-Euclidean distances | Frei, 2014 | Int. J. Climatol. 34:1585-1605 | Profile with inversion layer, anomalies weighted by elevation-aware distance |
| Daily temperature grids for Austria since 1961 | Hiebl and Frei, 2016 | Theor. Appl. Climatol. doi:10.1007/s00704-015-1411-4 | Frei method operationally, leave-one-out errors |
| Creating a topoclimatic daily air temperature dataset for the conterminous United States (TopoWx) | Oyler et al., 2015 | Int. J. Climatol. doi:10.1002/joc.4127 | Moving-window regression kriging with MODIS LST |
| Empirical downscaling of daily minimum air temperature at very fine resolutions in complex terrain | Holden et al., 2011 | Agric. For. Meteorol. 151:1066-1073 | 140 sensors, Bitterroot; Tmin from cold-air-drainage terrain indices |
| Simulating wind fields and snow redistribution using terrain-based parameters | Winstral and Marks, 2002 | Hydrol. Process. 16:3585-3603 | The Sx upwind shelter parameter |
| Downscaling surface wind predictions from NWP models in complex terrain with WindNinja | Wagenbrenner et al., 2016 | Atmos. Chem. Phys. 16:5229-5241 | WindNinja on WRF, NAM, HRRR vs 53 anemometers |
| Representing atmospheric moisture content along mountain slopes | Feld, Cristea and Lundquist, 2013 | Water Resour. Res. 49:4424-4441 | Dewpoint along Sierra slopes vs empirical, PRISM, WRF |
| An assessment of differences in gridded precipitation datasets in complex terrain | Henn et al., 2018 | J. Hydrol. 556:1205-1219 | Six gridded products over the western US |
| Our skill in modeling mountain rain and snow is bypassing the skill of our observational networks | Lundquist et al., 2019 | Bull. Amer. Meteor. Soc. 100:2473-2490 | Models vs gauges, radar and satellite in mountains |
| Evaluation of MRMS snowfall products over the western United States | Wen et al., 2017 | J. Hydrometeorol. 18:1707-1713 | MRMS vs SNOTEL SWE |
| Assimilation of point SWE data into a distributed snow cover model comparing two contrasting methods | Magnusson et al., 2014 | Water Resour. Res. 50:7816-7835 | EnKF vs statistical interpolation with 3D localisation, Switzerland |
| Improving physically based snow simulations by assimilating snow depths using the particle filter | Magnusson et al., 2017 | Water Resour. Res. 53:1125-1143 | Particle filter at Col de Porte |
| Assessing the benefit of snow data assimilation for runoff modeling in Alpine catchments | Griessinger et al., 2016 | Hydrol. Earth Syst. Sci. 20:3895-3905 | Assimilated snow model vs runoff |
| The bias-detecting ensemble | Winstral, Magnusson, Schirmer and Jonas, 2019 | Water Resour. Res. 55:613-631 | Cheap ensemble that finds forcing bias from ~300 Swiss depth sites |
| Toward snow cover estimation in mountainous areas using modern data assimilation methods: a review | Largeron et al., 2020 | Front. Earth Sci. 8:325 | Review of DA methods for snow |
| CrocO v1.0 / Propagating information from snow observations with CrocO | Cluzet et al., 2021 (GMD 14:1595) and 2022 (TC 16:1281) | Copernicus | Particle filter with spatial localisation, 10-year leave-one-out |
| The Multiple Snow Data Assimilation System (MuSA v1.0) | Alonso-Gonzalez et al., 2022 | Geosci. Model Dev. 15:9127 | Open framework: PBS, ES, PF around FSM2 |
| TopoSUB: a tool for efficient large area numerical modelling in complex topography at sub-grid scales | Fiddes and Gruber, 2012 | Geosci. Model Dev. 5:1245-1257 | k-means terrain clusters as modelling units |
| Statistical modelling of the snow depth distribution in open alpine terrain | Gruenewald et al., 2013 | Hydrol. Earth Syst. Sci. 17:3005 | How much of snow depth terrain explains, by scale |
| Converting snow depth to snow water equivalent using climatological variables | Hill et al., 2019 | The Cryosphere 13:1767 | CSO's depth-to-SWE regression |
| Assimilation of citizen science data in snowpack modeling using a new snow data set: Community Snow Observations | Crumley et al., 2021 | Hydrol. Earth Syst. Sci. 25:4651 | CSO depths into SnowModel, Thompson Pass AK |
| Assimilation of community science data to improve mountain snow distribution estimates | Aragon et al., 2025 | Water Resour. Res. 61, e2025WR040019 | CSO plus SNOTEL, Utah, three winters |

## Part 1: temperature

**The methods.** PRISM (Daly et al. 2008) fits, at every grid cell, a local regression of the climate element on
elevation using nearby stations, each weighted by distance, elevation difference, topographic facet, coastal
proximity and a two-layer "vertical layer" weight that lets valley stations under an inversion belong to a
different regression than the slopes above them. Cross-validation MAEs for the West are about 0.7 C for Tmax and
commonly above 1 C for Tmin; precipitation MAE is about 10 percent, highest in winter (secondary summaries).
Daly, Conklin and Unsworth (2010) is the argument for treating Tmin this way: cold pools are decoupled from the
free atmosphere. PRISM's errors are for monthly normals and for daily grids built as anomalies on them; a
day-by-day fit like ours is a noisier problem.

GIDS (Nalder and Wein 1998) is our method with one change: a multiple regression on x, y and elevation, then
inverse-distance-squared residuals. It beat four kriging variants on a 32-station network. Stahl et al. (2006)
tested 12 methods on daily Tmax and Tmin over British Columbia: cross-validation MAE 1.22 to 1.99 C across
methods, GIDS-type local regression best where stations were dense, with occasional large outliers at high
elevation where the local lapse rate was poorly constrained, the failure our per-zone pooling rule guards
against. MicroMet (Liston and Elder 2006) brings station temperatures to sea level with a fixed monthly lapse
rate, spreads them with a Barnes (Gaussian) filter and puts them back on the DEM; it is built for sparse
networks and never learns the day's lapse rate. ANUSPLIN fits a thin plate spline in x, y, z with smoothing set by
generalised cross-validation; it is stable in sparse high terrain but does not capture inversions (secondary).

The best-documented modern approach is Frei (2014), operational for Switzerland and Austria: a non-linear
vertical profile (a lapse rate plus an inversion layer of fitted depth and strength) per day, then station
anomalies interpolated with a non-Euclidean distance that grows with elevation difference and with crossing the
inversion top. With about 100 Swiss stations, leave-one-out MAE ran from 0.5 C in summer lowlands to 1.5 C in the
Alps in winter; for Austria, Hiebl and Frei (2016) report 1.1 C for Tmin and 1.0 C for Tmax with near-zero bias.
TopoWx (Oyler et al. 2015) uses moving-window regression kriging with elevation and MODIS surface temperature and
reports MAE of about 1.0 to 1.1 C for both extremes over CONUS. Holden et al. (2011) predicted nightly Tmin at 30 m
from 140 cheap Bitterroot sensors with cold-air-drainage terrain indices and synoptic predictors; the related
250 m Holden et al. (2015) product reports MAE under 1.4 C (secondary).

**Lapse rates and cold pools.** Minder, Mote and Lundquist (2010) is the Cascade reference: annual mean windward
lapse rates of 3.9 to 5.2 C/km, well below 6.5; COOP climatology gives 6.1 C/km for Tmax and 4.2 for Tmin; rates
vary strongly by season, by day and between slopes of the same mountain, and 6.5 versus 4 C/km moves modelled
melt timing by a month. Kirchner et al. (2013) found a mean of 5.5 C/km in the Bavarian Alps, steeper in summer,
flatter with frequent inversions in winter, different on north and south slopes. Pages and Miro (2010) fit the
lapse rate by elevation band with vertical weights so a valley inversion does not corrupt the slope rate.
Lundquist and Cayan (2007) found from 37 Yosemite sensors that a single lapse rate is often a poor description
and that the departures are predictable from reanalysis wind and pressure. Lundquist, Pepin and Rochford (2008)
classify DEM cells as cold-pool-prone from slope, curvature and percentile elevation; splitting the
interpolation by class cut RMSE by up to 3 C at single sites and about 1 C averaged over three test areas
(abstract). Whiteman et al. (2001, Wea. Forecasting 16:432) document the Columbia Basin cold pool as a multi-day
winter feature, which matters for our east-side zones.

**Reading for our density.** With 1,400 stations a per-zone daily lapse rate is well constrained and the residual
field is dense enough to cross-validate every day. The good daily methods report 1.0 to 1.5 C in winter mountains;
fixed-lapse or plain IDW report 1.5 to 2 C (Stahl). What the better methods add is an inversion-aware vertical
profile and a distance that does not let a valley-floor residual leak up a slope.

## Part 2: wind, humidity, precipitation

**Wind.** MicroMet spreads station speeds by Barnes filter then multiplies by W = 1 + gamma_s Omega_s + gamma_c
Omega_c, with slope-in-the-wind Omega_s and curvature Omega_c each scaled to -0.5..0.5 and weights of 0.5, so W
stays within 0.5 to 1.5; curvature uses a length scale of about half the ridge-to-valley wavelength, and direction
is turned by a slope-aspect term. Winstral and Marks (2002) define Sx as the maximum upward angle to terrain along
an upwind search line; it predicted snow depth variance better than elevation, slope or radiation, and later work
(Winstral et al. 2013; Marsh et al. 2021, TC 15:743) uses a 300 m search on a 10 to 30 m DEM. Wagenbrenner et al.
(2016) ran WindNinja on WRF, NAM and HRRR against 53 anemometers on an isolated butte: downscaling improved speed
when observed speeds exceeded about 5 m/s, most above 10 m/s, and improved direction in downslope flow, but was
mixed during thermally driven periods. Neither is a substitute for a fitted station field on strong-wind days;
both are ways to shape a coarse field with terrain.

**Humidity.** MicroMet and Feld et al. (2013) work in dewpoint, not RH, because dewpoint is close to linear in
elevation; MicroMet uses a monthly dewpoint lapse rate. Feld et al. found dewpoint-from-temperature rules had
biases differing by 0.6 to 8.2 C between summer and winter, that PRISM and WRF did better, and that higher stations
are drier in specific humidity. Textbook dewpoint lapse rates are about 1.6 to 2 C/km.

**Precipitation.** Henn et al. (2018) found the six main gridded products differ by 5 to 60 percent (200 mm/yr or
more) in western complex terrain, with errors of 50 to 100 percent of the annual total where PRISM lacked a gauge;
Lundquist et al. (2019) argue that a well-configured high-resolution atmospheric model now beats gauge
interpolation, and beats radar and satellite by a wide margin, in mountains. Wen et al. (2017) found MRMS
snowfall biased -77 percent against SNOTEL SWE, worst between -10 and 0 C, with poor detection below 5 mm/day and
acceptable detection above 10 mm/day; MRMS in the West suffers beam blockage and high minimum beam heights.
Radar-gauge merging by kriging with external drift (radar as the drift) is the standard fix and helps most where
the radar composite is poor, but the Cascade radar gaps mean the drift itself is missing over much of our lattice.
SNOTEL gauges undercatch snow by an amount that grows with wind above about 2 m/s (Fassnacht 2004, secondary), so
orographic ratios from SNOTEL alone run low on exposed sites.

## Part 3: assimilating sparse point snow observations

Largeron et al. (2020) order the methods: direct insertion and nudging (no uncertainty, no propagation), optimal
interpolation (a fixed error covariance decides how far and to which terrain an increment spreads), EnKF
(Gaussian, needs an ensemble) and particle filters (non-Gaussian, good for classes, prone to degeneracy). Their
theme for mountains is that the covariance, not the update rule, decides whether a point observation helps at
unobserved sites.

Magnusson et al. (2014) assimilated Swiss point SWE with EnKF and optimal interpolation using 3D localisation in
horizontal distance and elevation, and found that assimilating fluxes (snowfall and melt inferred from SWE) beat
inserting SWE itself; information transferred usefully to unobserved cells. Magnusson et al. (2017) showed a
particle filter on snow depth cutting SWE, runoff and soil temperature errors at Col de Porte. Griessinger et al.
(2016) found the assimilated snow model improved runoff only at high elevation. Winstral et al. (2019) proposed
the bias-detecting ensemble: a small ensemble of forcing perturbations, about 300 depth sites picking the member
that removes the bias, checked at 38 held-out sites; RMSE fell by up to 40 percent for depth and 37 percent for
SWE, NSE 0.98 against 0.81. Cluzet et al. (2022) ran a 10-year leave-one-out over the French Alps and Pyrenees
with a localised particle filter: a radius of 35 to 50 km (of 17 to 300 tested) gave the lowest RMSE and best
spread-skill, and CRPS improved about 13 percent where open-loop errors were largest. CrocO's units are massif x
elevation band x aspect x slope, so "similar terrain" is built into the state and localisation is only in
distance. MuSA (2022) packages the same tools around FSM2 and is the easiest code to borrow.

Terrain-similarity transfer has its own literature. TopoSUB (Fiddes and Gruber 2012) clusters cells by k-means on
elevation, slope, aspect and sky view and models each cluster once, a formal version of our similarity mask.
Gruenewald et al. (2013) is the caution: a global regression of snow depth on elevation, slope, northing and wind
shelter explained 23 percent of variance, while locally fitted models aggregated to 400 m units explained 30 to
91 percent; terrain predicts snow far better within a small region than across regions, which argues for a
distance limit on any transfer.

Citizen science: Hill et al. (2019) give the CSO depth-to-SWE regression. Crumley et al. (2021) found that a
relatively small number of CSO depths, assimilated in SnowModel with SNOTEL, improved the modelled distribution
around Thompson Pass; Aragon et al. (2025) found that adding CSO to SNOTEL cut SWE RMSE by up to 23 percent against
the open loop over three Utah winters, the gain coming from observations where the fixed network has none. The
project's own summaries say the value is that skiers sample high, far from roads and across aspects. No quantified
observer bias (probe error, sampling near tracks) was found in the abstracts read.

## Comparison to our approach

**Is regression plus inverse distance defensible for a first season?** Yes. It is GIDS, the method Stahl et al.
chose for BC, and at our density daily errors should sit near the 1.0 to 1.5 C the operational products report
rather than the 2 C of a fixed lapse rate. Two things the literature says matter for Tmin are missing. First, an
inversion-aware profile: on a cold-pool night our per-zone linear fit returns a flattened or inverted slope for
the whole zone, which warms every ridge in it. Frei's fix is a profile with a separate valley layer; Pages and
Miro's cheaper fix is to fit the lapse rate on stations above the inversion top (or with weights that fall off
below it) and let the valley residuals carry the pool. Second, a distance that respects elevation: horizontal IDW
lets a valley-floor residual of -6 C reach a ridge 3 km away. A vertical term in the distance,
d_eff^2 = d_h^2 + (k dz)^2 with k of order 10 to 20 (what Magnusson's 3D localisation and Frei's non-Euclidean
distance amount to), is a one-line change in `_idw` and the highest-value edit. A cold-pool mask from Lundquist
et al. (2008) terrain indices (flat, concave, low percentile elevation in a 1 to 5 km window), applied only on
nights with negative valley residuals, is the next step and needs only the lattice we have.

**What regression kriging or MicroMet would add, and at what cost.** Regression kriging replaces IDW weights with
weights from a fitted residual variogram, which gives an error map and stops over-weighting station clusters (our
HADS and ASOS sites clump in valleys). The cost is a daily variogram fit, or a seasonal one reused daily, plus a
dense solve; with 1,400 stations and a 1 km coarse grid that is minutes of numpy, and `scikit-gstat` or `pykrige`
do the fitting. Cross-validation must be leave-one-out per day, which needs no new data. The MAE gain over GIDS in
dense networks is small in the comparisons read (Stahl; Nalder and Wein found the IDW-based method better than
kriging), so it is a second-season upgrade justified by the error map, not by accuracy. MicroMet adds nothing for
temperature but its terrain wind weighting and dewpoint handling are the right zero-cost models for wind and
humidity.

**Recommended methods.** Temperature: keep the per-zone daily lapse fit, but when the pooled fit is inverted
refit on stations above the inversion top (start by excluding cold-pool-prone stations); interpolate residuals
with the elevation-aware distance; keep the 30 to 40 km reach; log leave-one-out MAE for Tmax and Tmin every
day so the season yields the numbers to justify kriging. Wind: interpolate the log of station speed (or its
anomaly) by the same distance rule, multiply by the MicroMet weight from lattice slope and curvature (weights
0.5, curvature scale about 1 km), and use Sx from the day's mean direction (300 m search on the 10 m DEM) as the
loading and scouring index; keep RAWS and SNOTEL anemometers apart, since heights and sheltering differ.
Humidity: interpolate dewpoint with a fitted daily dewpoint lapse rate and the same residual scheme, then derive
RH from the cell temperature. Precipitation: do not interpolate gauges alone and do not trust MRMS in snow; use
NDFD or HRRR QPF as the drift, fit a daily gauge-to-drift ratio per zone (undercatch-corrected SNOTEL and
CoCoRaHS), interpolate the log ratio with the elevation-aware distance, and keep MRMS for the rain-snow line and
timing at low elevation where it detects above 10 mm/day.

**Propagating a point snow-surface observation.** The literature supports our mask in kind: the assimilation
systems that work in mountains localise in horizontal distance and elevation (Magnusson 2014; Cluzet 2022) and
carry aspect and slope in the state units (CrocO; TopoSUB). Two changes are recommended. First, replace the hard
box with a product of Gaussian kernels, which is what a localised covariance is:
w = c * exp(-d_h^2 / 2L^2) * exp(-dz^2 / 2sz^2) * exp(-dtheta^2 / 2sa^2) * exp(-dcanopy^2 / 2sc^2) * [same crest
side], with L about 10 to 20 km for surface class (Cluzet's 35 to 50 km is for depth over a far larger domain and
is an upper bound), sz about 150 m, sa about 30 deg and sc about 0.3, which reproduce our cut-offs near the
1-sigma point while removing edge effects. Second, weight by observation type: a probe or a named-place report
gets full weight, a zone-level report only its zone x band x aspect group, as `score.py` does now. Gruenewald's
scale result is the argument for a small L and for trusting a report more within its own drainage than across
the crest. Once the season has enough scored reports, their residuals binned by (d_h, dz, dtheta, dcanopy) give an
empirical correlogram and the kernel widths can be fitted rather than judged, which is how the operational
systems set their localisation.

## Could not verify

- No full text could be fetched: prism.oregonstate.edu, agupubs and rmets on Wiley, all Copernicus journals,
  fs.usda.gov and research.fs.usda.gov, osti.gov, repository.library.noaa.gov, journals.ametsoc.org,
  ui.adsabs.harvard.edu, semanticscholar.org, core.ac.uk and blogs.ubc.ca were all blocked by the egress proxy.
- PRISM's Tmax 0.7 C and Tmin above 1 C cross-validation figures, and Holden's under 1.4 C MAE, come from
  citing papers' summaries, not from the papers' own tables.
- The Lundquist et al. (2008) "up to 3 C at single sites, about 1 C averaged" figures come from a search
  abstract; the terrain-index window sizes and thresholds were not seen.
- Magnusson et al. (2014) error reductions in numbers were not found; only the qualitative result (fluxes beat
  states, 3D localisation transfers information) is confirmed.
- Crumley et al. (2021) numeric improvements were not found; the 23 percent RMSE reduction belongs to Aragon et
  al. (2025), and some search summaries wrongly attach it to Crumley.
- No paper quantifying CSO observer error or spatial sampling bias was found; the claims about where skiers
  sample come from the project's own descriptions.
- Wagenbrenner et al. (2016) RMSE and bias tables were not seen, only the thresholds (5 and 10 m/s) and the
  qualitative findings.
- Sx search distances (300 m) come from later users of the parameter, not from Winstral and Marks (2002) itself.
- Fassnacht (2004) undercatch figures and Whiteman et al. (2001) cold-pool climatology were read only as
  search snippets.
