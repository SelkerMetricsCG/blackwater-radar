# What already exists: spatial ski-conditions products, observation extraction and quality, weak-layer tracking

Review for the snow-conditions tracker (`snow/`), 2026-09-30. Scope: products that map or forecast ski snow
conditions (not avalanche danger), structured extraction from forecasts and observations, the quality of human
observations, and how centers track persistent weak layers as data. Method: web search plus page fetches. Many hosts
(nwac.us, avalanche.ca, nve.no, slf.ch, opensnow.com, the CalTopo blog, Copernicus journals, the ISSW archive,
snowsignals.com) were blocked by this session's proxy, so those are described from search snippets and listed in (d).
Nothing here is invented; unconfirmed details say so.

## (a) Sources and products

| Name | Who | URL | What it is |
|---|---|---|---|
| OpenSnow Powder Quality, PowderFinder | OpenSnow | support.opensnow.com/feature-guides/powder-quality | Per-resort, three-period daily rating from forecast totals, SLR, wind, temperature; PowderFinder searches forecast totals on a map |
| Snow Signals Alpine Intelligence | Snow Signals | snowsignals.com/alpine-intelligence | Terrain-aware physical snow-surface model, sub-10 m grid, 15 min step, 7 day forecast, Lake Tahoe at launch |
| Snow-Forecast.com | Snow-Forecast | snow-forecast.com/pages/faq | Resort forecasts; 1 km DEM with lapse rates; freezing-level graphs |
| Windy new snow and snow depth | Windy | windy.com | Raw model accumulation (12 h to 10 d) and snow depth with density |
| WePowder; Powderchasers | private | wepowder.com; powderchasers.com | Human-written powder forecasts (Alps; North America) |
| seNorge / Xgeo skiing-conditions map | NVE, MET Norway | senorge.no | 1 km daily HBV-based snow model since 2004; a surface map for ski waxing; 9 day outlook |
| SLF snow maps, White Risk | WSL/SLF | slf.ch, whiterisk.ch | New snow, snow depth, comparative depth, snow-profile maps |
| CalTopo Sun Exposure, terrain shading, Avy Observations | CalTopo | caltopo.com | Sun by date and time from the DEM; shading by slope, aspect, canopy; hourly overlay of avalanche occurrences from NAC's platform |
| ShadeMap | ShadeMap | shademap.app | Ray-traced terrain, tree and building shadow for any time |
| FATMAP | Strava | powder.com coverage | Shut 2024-10-01; Strava keeps heatmaps, not conditions |
| avalanche.org API and observation platform | NAC (USFS) | github.com/NationalAvalancheCenter/Avalanche.org-Public-API-Docs | Documented map layer only; product and obs endpoints are the centers' own, obs needs an allow-listed Origin |
| NWAC observations and layer pages | NWAC | nwac.us/observations, nwac.us/layers | Public and pro observations; per-layer pages keyed by burial date and grain |
| UAC observations | Utah Avalanche Center | utahavalanchecenter.org/observation | Structured Snow Characteristics: Snow Surface Conditions, New Snow Density |
| Mountain Information Network | Avalanche Canada | avalanche.ca/mountain-information-network | Unmoderated public quick, avalanche, snowpack, weather reports |
| Varsom Regobs | NVE | regobs.no, api.nve.no/doc/regobs | Open observation database and API v5, observer competence stars, spatial precision |
| InfoEx | Canadian Avalanche Association | infoexhelp.avalancheassociation.ca | Professional exchange; weak layers labelled by burial date |
| SnowPilot, CAAML | open source; IACS | snowpilot.org, caaml.org | Snow-pit database and profile schema |
| Community Snow Observations | CSO (NASA) | communitysnowobs.org | Citizen depth probes assimilated into a 25 to 100 m daily model |
| Techel and Schweizer 2017 | SLF | Cold Regions Sci. Tech. | Local nowcast vs regional forecast agreement, observer bias |
| Techel et al. 2018 | SLF and partners | NHESS 18, 2697 | Bias between neighbouring warning services |
| ISSW 2024 P1.16 | NVE and coauthors | arc.lib.montana.edu | 26,021 Regobs instability reports by observer competence |
| Herla et al. 2024 | SFU ARP | NHESS 24, 2727 | Simulated profiles validated against forecasters' critical layers |
| Winkler and Techel 2015 | SLF | Lang. Resources and Evaluation | Swiss bulletin composed from a catalogue of phrases |

## (b) Findings

### 1. Products that map or forecast ski conditions

Nearly everything here forecasts snowfall amount, not surface state. OpenSnow's Powder Quality is the most developed
amount-plus-quality product: three bars a day per resort (first chair to morning, midday, afternoon) rated Excellent,
Good or Okay from forecast totals, overnight versus daytime split, snow-to-liquid ratio, wind, temperature and recent
snowfall; the support page says the rating is not exact "because everyone has a different definition of their perfect
day." It is a point product with no aspect, band, crust or melt-freeze state. Snow-Forecast.com downscales model
temperature to a 1 km DEM; Windy shows raw model fields; WePowder and Powderchasers are people writing about storms.

The one product that does what our model does is Snow Signals' Alpine Intelligence: a "terrain-aware, physics-driven
snow conditions model" on a sub-10 m grid with a 15 minute timestep and 7 day forecasts, states "from packed powder to
chalky snow to icy crust to corn," with DEM slope, aspect, canopy, a 3D wind field and micro-scale precipitation
interpolation; Lake Tahoe only at launch. Its pages were blocked, so validation, price and whether it ingests field
observations are unknown. Norway's seNorge skiing-conditions map is the only public-agency surface product found: a
1 km HBV-derived model characterizing the surface for cross-country waxing, not per-aspect backcountry state. SLF's
public maps are new snow, depth, comparative depth and profiles; no public SLF surface or wet-snow map was confirmed.
CalTopo's Sun Exposure and ShadeMap compute the same terrain shading as our solar term but show it as a planning layer.
FATMAP is gone; Strava heatmaps are traffic. No academic ski-ability or corn-timing model turned up; the ski-climate
literature uses resort indices (the 100 day rule, 30 cm depth, the Ski Climate Index with sunshine, wind and thermal
comfort facets, "optimal ski day" thresholds such as minus 5 to 5 C and 5 h of sun). Corn timing appears only as
practitioner guidance (overnight freeze of 5 to 6 h, south aspects first).

### 2. Structured extraction and observation quality

No published work applies LLMs or NLP to extracting fields from avalanche bulletins or observations. The nearest is the
reverse direction: the Swiss bulletin's danger text is composed from a controlled catalogue of phrases (Winkler and
Techel), which makes it machine translatable and in principle parsable; readers told catalogue from hand-written text
only 55 percent of the time. SLF's operational AI is numerical (danger-level and instability models from SNOWPACK),
not text. AvaFrame is an Austrian avalanche-dynamics simulator, not NLP. The avalanche.org product already carries
`bottom_line`, `hazard_discussion`, `danger` and `forecast_avalanche_problems` with aspect and elevation roses, so our
extraction works mainly on discussion prose and observation text.

Observation platforms carry structured surface fields, and these are the vocabulary to align with. UAC's form has a
Snow Characteristics block with `New Snow Density` (Low, Medium, High) and `Snow Surface Conditions` with values
including Powder, Dense Loose and Wind Crust. Regobs' `SnowSurfaceObservation` (from NVE's regobslib) has `drift`,
`surface`, `moisture`, `hn24_cm`, `new_snow_line`, `hs_cm`, `snow_line`, `layered_snow_line`, a registration-level
`spatial_precision` in metres and an observer `Competence` level; the public scale runs from no rating to five stars,
tied to NVE course levels 4A (basic, trained), 4B (advanced) and 4C (warning service). MIN quick reports use a pick list
plus comments, are unmoderated, and forecasters review every post to learn which users are reliable. The NAC obs API
(`/obs/v1/public/observation/list/`, `avalanche_observation`, `combined_zones`, tiles) returns `zone_id`,
`location_point` (lat and lng may be null), `advanced_fields`, an `instability` JSON block and nested avalanches, and
answers a bare 401 without an allow-listed Origin (NWACus/web issues 1218, 1337), matching `snow/observations.py`.

On quality: Techel and Schweizer (2017) found 76 percent agreement between experts' local danger nowcasts and the
regional forecast, 71 percent after correcting for local uncertainty and reporting bias, with some observers
consistently high or low; a 2020 estimate puts the reliability of paired local estimates near 0.9. The ISSW 2024
Regobs study (26,021 sign-of-instability reports, five seasons) found significant differences in reporting frequency
between competence groups. Techel et al. (2018) showed systematic bias between neighbouring forecast centers, so the
products we extract from have a house style. Community Snow Observations found a handful of citizen depth probes
improved a distributed model in 62 to 78 percent of ensemble runs, the best evidence that sparse recreational reports
are worth assimilating.

### 3. Persistent weak layers as data

Naming by burial date is an industry convention: InfoEx labels a layer by grain and date ("SH 17 January") and has a
persistent weak layer overview and hazard assessment module. NWAC publishes per-layer pages at
`nwac.us/layers/<yyyymmdd>_<grain>/` (example `20220130_fcsf`: buried 2022-01-30, primary grain FCsf, zones STV, EN,
EC, SNQ, WS, dated forecaster comments), and its products say "the January 30 facets" or "the 1/20 MFcr". CAIC and UAC
track layers all season in prose. Herla et al. (2024) validated ten seasons of simulated profiles in three Canadian
regions against the critical layers forecasters recorded, and the SARP tools (profile alignment, averaging, clustering
into forecast regions) treat layers as objects with burial dates. SnowPilot and CAAML are the structured pit schemas.
No public cross-center database of named layers with status over time was found; NWAC's layer pages are the nearest.

## (c) Comparison to our approach

Novel in ours: a per-aspect, per-band surface-state field for backcountry terrain at 100 m from public data on free
tiers; an LLM pass that turns center prose and public observations into dated, quoted records; scoring those records
against the model and nudging it; and a layer table keyed by the forecasters' own names. Only Alpine Intelligence is
comparable in output, and it is closed and single-region; nothing found closes the loop from human observations back
to a surface model.

What others do better and we should copy. First, controlled vocabularies: UAC and regobs keep surface, moisture and
wind as three small enums, whereas our `surface` folds them into fifteen classes. Optional `moisture` (dry, moist,
wet) and `wind_effect` (none, light, heavy) on the obs record would let "wind-affected but still soft" keep both facts.
Second, a `spatial_precision` in metres per record, as regobs has; the scorer already picks 300 m, 1.5 km or zone, so
store that choice instead of inferring it later. Third, an observer tier: a `source_tier` of `center_product`,
`pro_obs`, `public_obs`, `trip` costs nothing now, whatever the NAC payload turns out to carry. Fourth, NWAC's layer id
(`20220130_fcsf`) is a better key than free text: keep `name` for the brief, add `buried` as an ISO date and `grain` as
the CAAML code so "Jan 30 facets" and "late January facet-crust sandwich" resolve to one layer. Fifth, OpenSnow's
three-part day is a good frame for the brief's melt-freeze and corn language.

What the observation literature implies for scoring weights. Experts disagree with the regional product about a
quarter of the time and individual observers carry persistent bias, so one report should never move a cell group far:
weight by tier (center product and pro obs above public obs, trips between), keep the 21 day dormancy, and fit
parameters only to several concordant residuals. Competence changes what people report as well as how accurately, so
absence of a report is no evidence. For a surface model, location precision matters more than observer type: a
report with coordinates but no aspect should score only the band, and one with a place name only should carry its
1.5 km radius into the residual weight. Center prose has a house style, so `confidence` should drop for hedged phrases
and the brief should quote rather than paraphrase.

Schemas to align with: CAAML grain codes for `grain`; regobs `SnowSurfaceObservation` and UAC's Snow Characteristics
for surface, moisture and wind; the product's aspect and elevation rose for `aspects` and `band`; NWAC's layer id form.

## (d) Could not verify

- OpenSnow's exact Powder Quality formula (pages blocked; from search snippets).
- Alpine Intelligence validation, pricing, use of observations, regions beyond Tahoe (site blocked).
- Any SLF public snow-surface or wet-snow map for skiers; only new snow, depth, comparative depth and profiles confirmed.
- Member lists of regobs enums `SnowCover.Surface`, `Moisture`, `Drift`, `SpatialPrecision`, `Observer.Competence` (raw file unreachable; names from a partial GitHub view).
- MIN quick-report pick-list values, and any peer-reviewed study of MIN report quality (none found).
- The NAC observation record's full field list and whether it carries an observer type (only the fields named in NWACus/web issues 1218 and 1337).
- NWAC layer page labels beyond burial date, grain and zones (page blocked; from a snippet).
- Full text and numbers of ISSW 2024 P1.16 and Herla et al. 2024 (hosts blocked; abstracts from snippets).
- Any published LLM or NLP extraction from avalanche bulletins or observations (searched; none found).
- Any peer-reviewed powder-day or corn-timing climatology for skiing (searched; only resort climate indices and practitioner guidance).
