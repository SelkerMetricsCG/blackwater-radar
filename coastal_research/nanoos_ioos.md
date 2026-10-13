# NANOOS and IOOS data for the Coastal section

Research note for radar.blackwaterlabs.org, written 2026-10-13 (fetches 19:40-20:10 UTC). Scope: what NANOOS
(www.nanoos.org, the IOOS regional association for WA/OR) and the national IOOS system add on top of NDBC/CDIP
waves, CO-OPS tides and the wind forecasts that other notes cover. Window: 41.0-49.7 N, -126.6 to -112.5.
Every fetch used `User-Agent: coastal-research/0.1`, a 20 s timeout, and at most a handful of requests per host.
Nothing was registered for and no embedded key was reused (two Google Maps keys sit in NVS/HFRNet page source;
they are not recorded here and must not be used).

## Summary

- The practical NANOOS interface for a script is **ERDDAP**, not NVS. `erddap.nanoos.org/erddap` (a front for
  `nwem.apl.washington.edu/erddap`, the UW-APL Northwest Environmental Moorings server) answers JSON/CSV with a
  standard `tabledap` URL; 117 datasets, of which ~25 are live today. What it adds for surfers and kiters that
  nobody else carries: the **Cha'ba/NEMO** wind-and-met buoy off La Push (47.966 N, -124.950), six tribal **Backyard
  Buoys** wave spotters off Quileute and Quinault land (wave height, period, direction, water temperature, inshore
  of any NDBC buoy), the six **ORCA** plus three new **PISCES** met buoys in Puget Sound and Hood Canal (wind,
  pressure, air temperature), **Se'lhaem** in Bellingham Bay, and OSU's **CB-06** off Coos Bay.
- **HF radar surface currents** are the one genuinely new map layer. The national HFRNet totals are on NDBC's
  THREDDS (`dods.ndbc.noaa.gov/thredds`, public domain) with a NetCDF Subset Service that returns a bounding-box
  NetCDF for one hour in one request. Today the 6 km west-coast grid had valid vectors from 41.3 to 45.9 N only;
  the three Washington radars (LOO1, WSP1, KAL1) were sending radials but produced no total vectors north of
  45.9 N at 17:00 Z. Expect Oregon coverage most hours, Washington coverage intermittent. Latency 2-3 h.
- **OOI Endurance** surface moorings (Oregon and Washington shelf, 44.64 N and 46.99 N) are on OOI's own ERDDAP
  with met and wave spectra, but the telemetered feed is ~1 day behind; their hourly values reach NDBC as
  stations 46097-46100 (the NDBC note's territory), which is the better live path.
- **NVS** (nvs.nanoos.org) is a PHP/JS app whose data calls (`/ssa/get_platform_data.php`, etc.) are POST-driven and
  undocumented; the one GET that works is the **asset list CSV** (`/services/download_asset_list.php`, 266 assets
  with lat/lon and provider), which is a good seed catalogue. The old GeoServer and SOS endpoints are gone (404).
- Not usable live: CMOP/SATURN (Columbia estuary) is effectively retired (its ERDDAP returned 503; mirrored data
  ends Nov 2025); the OOI "gold copy" ERDDAP returned 502; IOOS's `erddap.sensors.ioos.us` carries no NANOOS
  moorings at all (only federal stations plus gliders), though it does send CORS headers.
- Products that are PDF or page-only: PNW HAB Bulletin (latest 2026-10-04), Beach View (WA/OR closures), IPACOA
  (ocean acidification). Link out; nothing to poll.

Licence picture: HFRNet and OOI are public-domain / free with credit; the APL datasets carry ERDDAP's standard
"may be used and redistributed for free" line; the IOOS glider line is CC BY 4.0; the **Backyard Buoys datasets are
CC BY-NC 4.0** (fine for a free public site, but it must stay non-commercial and credit the Quileute Tribe and
Quinault Indian Nation).

---

## 1. NANOOS ERDDAP (erddap.nanoos.org = nwem.apl.washington.edu)

**Endpoint pattern.** `https://erddap.nanoos.org/erddap/tabledap/<datasetID>.<json|csv|nc>?<vars>&time>=now-3hours&orderByMax("time")`.
Dataset list: `.../tabledap/allDatasets.csv?datasetID,title,minLongitude,minLatitude,maxLongitude,maxLatitude,maxTime`.
Metadata (variables, licence): `.../info/<datasetID>/index.csv`. `data.nanoos.org/erddap/...` 301-redirects here.
Gotcha found today: some requests on `erddap.nanoos.org` get a **302 to `http://nwem.apl.washington.edu/erddap/...`**
(plain http, alias dataset ids such as `nemo-chaba_winds`, `orca1_met`), and the redirected URL answered 400 when
the query was carried over. Requests written as `?&time>=...` answered 200 directly. Safer: call
`https://nwem.apl.washington.edu/erddap/` itself, which has the same datasets plus a few more (PISCES, `npby1_surfctd`).
**CORS: none** on either host (no `Access-Control-Allow-Origin`), so the Actions job must fetch and republish.
**Licence** (dataset `license` attribute, read on `chaba_met_all` and `orca_met_hansville`, 2026-10-13): "The data may
be used and redistributed for free but is not intended for legal use, since it may contain inaccuracies..." (the
ERDDAP default). Server legal page (`erddap.nanoos.org/erddap/legal.html`): "The data from some datasets may be
subject to usage limitations or restrictions. See the dataset's license metadata". NVS Disclaimer page
(`nvs.nanoos.org/Disclaimer`): "Experimental Data and Products - NOT for Navigational or Operational Purposes" and
"many of the data streams are presented in near real-time and have not been quality controlled". Every row carries
QARTOD `_qc_agg` flags (1 pass, 2 not evaluated, 3 suspect, 4 fail); show only flag 1-2.
Fetched today: `allDatasets` 200 (117 rows); four dataset pulls 200; samples below.

| Dataset id (erddap.nanoos.org) | Asset, lat/lon | Variables (CF names) | Last data at fetch (19:47 Z) | Notes |
|---|---|---|---|---|
| `chaba_met_all` (= `chaba_met`, `nemo-chaba_met`) | **NEMO Cha'ba** buoy off La Push, 47.966 N -124.950 E | `wind_speed`, `wind_speed_of_gust`, `wind_from_direction`, `air_pressure_at_mean_sea_level`, `air_temperature`, `relative_humidity`, `dew_point_temperature`, `rainfall_amount`, shortwave | 17:50 Z (≈2 h behind); sample `{wind_speed 8.12 m/s, gust 9.70, dir 287, p 1021.5, Ta 11.8}` | 10-min rows. UW-APL Northwest Environmental Moorings (Travis/Mickett). The only met buoy on the WA outer coast north of 46041 besides OOI. |
| `chaba_wind` (`nemo-chaba_winds`) | same | Vaisala WMT700 wind only | same | alias; request redirected (see gotcha). |
| `chaba_hydro` (`chaba_ctd_nrt`) | same, surface CTD | `sea_water_temperature`, salinity, oxygen, chlorophyll, turbidity, `sea_water_ph_reported_on_total_scale` | 17:40 Z | "near-realtime (incomplete data)" in its own title; SST and pH at the surf-zone-adjacent buoy. |
| `backyardbuoys_quileute_center` | Sofar Spotter, 47.841 N -124.689 E (drifts within a 1-2 km box) | `sea_surface_wave_significant_height`, `_mean_period`, `_from_direction`, `_directional_spread`, peak period/direction, `sea_water_temperature` | 18:30 Z (≈1.3 h); sample `{Hs 1.19 m, Tm 8.5 s, dir 274, Tp 14.6 s, SST 10.6}` | 30-min rows. **Licence CC BY-NC 4.0**, institution Quileute Tribe, "Backyard Buoys, NSF". |
| `backyardbuoys_quileute_north` | 47.94 N -124.76 E | same | 2026-09-23 (stale) | seasonal gaps; check `maxTime` each run and hide when > 6 h old. |
| `backyardbuoys_quileute_south` | 47.76-47.85 N -124.58..-124.71 E | same | 2026-03-08 (stale) | |
| `backyardbuoys_quinault_north` | 47.454 N -124.436 E | same | 2026-09-28 (stale) | institution Quinault Indian Nation. |
| `backyardbuoys_quinault_mid` / `_south` | 47.34 / 47.28 N, -124.37 / -124.33 E | same | 2026-01-30 (stale) | |
| `orca_met_twanoh` (`orca1_met`) | ORCA1 Twanoh, Hood Canal 47.375 N -123.008 E | `wind_speed`, `wind_from_direction`, pressure, air T, RH, dew point, PAR, shortwave | 19:24 Z (20 min) | 10-min rows. |
| `orca_met_hoodsport` (`orca2_met`) | Hoodsport 47.422 N -123.113 E | same | 2026-09-09 (down) | |
| `orca_met_hansville` (`orca3_met`) | Hansville 47.907 N -122.627 E | same | 18:50 Z (≈1 h); sample `{wind 2.36 m/s dir 128, p 1022.4, Ta 12.5}` | at the mouth of Hood Canal / Admiralty Inlet, useful for kiters at Point No Point. |
| `orca_met_dabobbay` (`orca4_met`) | Dabob Bay 47.803 N -122.803 E | same | 2025-09-30 (down) | |
| `orca_met_pointwells` (`npby1_met`) | NPBY1 Point Wells 47.761 N -122.397 E | same | 18:50 Z | central Puget Sound; also `npby1_surfctd` (surface T/S) 18:49 Z. |
| `orca_met_carrinlet` (`npby2_met`) | NPBY2 Carr Inlet 47.28 N -122.73 E | same | 19:29 Z | south Sound. |
| `pisces1/2/3_met` (nwem only) | PISCES-South/North/East, Hood Canal 47.665-47.692 N, -122.81..-122.87 E | met as ORCA | pisces2, pisces3 18:50 Z; pisces1 2026-08-24 | new 2026; same APL group; `pisces2_adcp` currents too. |
| `bellinghambay_met` | Se'lhaem, Bellingham Bay 48.724 N -122.577 E | met | 18:00 Z | plus `_surfhydro` (surface T/S) and `_deephydro` 18:50 Z. |
| `OSU_CB06` | OSU CB-06 off Coos Bay 43.292 N -124.538 E | profile T/S/O2/pCO2 (TimeSeriesProfile) | 2026-10-08 22:00 Z | asset list says it also reports wind/pressure; the live met stream was not found on this server. |
| `ocnms_ce42_lander_*`, `ocnms_mb42_lander_*`, `quileute2/3_lander_*` | bottom landers Cape Elizabeth 47.353 N -124.489 E, Makah Bay 48.324 N -124.735 E, Quileute 47.72-47.77 N | bottom CTD, ADCP currents | all ended 2026-09-19 | **seasonal (May-Sept)**; sea-floor, not surface. |
| `orca_hydro_*`, `APL_NPB*`, `ORCA_*` | ORCA profiler hydrography | depth-gridded T/S/O2 profiles | to 2026-10-08 | science product; not for the map. |
| `CMOP_Ogi02`, `CMOP_Saturn03`, `CMOP_Saturn07` | SATURN-02/03/07 Columbia estuary 46.17-46.29 N | T/S profiles | Oct-Nov 2025 | retired; see §6. |
| `glider_lapush_*`, `glider_washelf_*`, `glider_OSU_Trinidad1_*` | mission archives | profiles | mostly delayed mode | live missions are on gliders.ioos.us, §5. |
| `dogami_beachmapping` | DOGAMI Oregon beach/shoreline surveys | trajectories | 2026-01-28 | not real time. |

Cadence and latency: APL moorings post 10-min data roughly hourly (observed 20 min to 2 h behind); Backyard Buoys
30-min data 1-2 h behind. An hourly job is the right cadence; nothing here justifies 15-min pulls.

## 2. HF radar surface currents (HFRNet via NDBC THREDDS, HFRNet radials ERDDAP)

HFRNet (CORDC/UCSD, operated for IOOS; `cordc.ucsd.edu/projects/mapping/` now redirects to `hfradar.ioos.us/hfrnet/`).
The old `hfrnet-tds.ucsd.edu` THREDDS is **gone** (connection failed today); the portal links to NDBC's THREDDS
instead. Totals are hourly u/v on 500 m / 1 km / 2 km / 6 km grids for the US West Coast (`uswc`) plus 25-h averages.

**Endpoint pattern.** Aggregations: `https://dods.ndbc.noaa.gov/thredds/dodsC/hfradar_uswc_{500m|1km|2km|6km}[_25hravg]`
(OPeNDAP; `.das`/`.dds` for metadata; ~92 days deep, 2,205 hourly steps today). The useful one is the NetCDF Subset
Service: `https://dods.ndbc.noaa.gov/thredds/ncss/grid/hfradar_uswc_6km?var=u&var=v&north=49.7&south=41.0&west=-126.6&east=-122.5&time=2026-10-13T17:00:00Z&accept=netcdf`
(only `netcdf` is accepted for grids; `accept=csv` returns "Format csv is not supported for Grid data request";
`time=latest` is rejected, so read `time_coverage_end` from the `.das` first). Catalog of individual hourly files:
`.../thredds/catalog/hfradar/catalog.html` (6.5 MB; file names like `rtv-uswc-6km-uwls_v1r0_hfr_s<YYYYMMDDHHMM>...nc`). A
7-day KML exists at `hfradar.ioos.us/hfrnet/assets/rtv7day.kml` (2.9 KB network link, last modified 2026-07-29).
Radials and radar-derived waves per site: `https://hfradar.ioos.us/radials-erddap/erddap/tabledap/<NET>_<SITE>` and
`OSU_WSH1_hfr_wave` (CSV/JSON like any ERDDAP). Station list with lat/lon and last-radial date:
`https://hfradar.ioos.us/hfrnet/sitediag/stationList.php` (HTML; a CSV link on the page).

**Licence** (hfradar.ioos.us/hfrnet, Disclaimer box, read 2026-10-13): "The information on the High Frequency Radar
Network (HFRNet) web page is supported by the U.S. Integrated Ocean Observing System (IOOS) and is in the public
domain, unless specifically noted otherwise, and may be used without charge for any lawful purpose so long as you do
not: Claim it as your own". Credit line they ask for: "Data provided by the U.S. Integrated Ocean Observing System
(IOOS) High Frequency Radar Network (HFRNet)". Also "Timely delivery of data and products from this server through
the Internet is not guaranteed." NetCDF global attributes name NOAA/NESDIS/OSPO as publisher (no licence attribute).

**Fetched today.** `.das` 200 (title "Near-Real Time Surface Ocean Velocity, U.S. West Coast, 2km Resolution",
30.25-49.99 N, u/v in m s-1 scaled Int16, `min_radar_sites 2`, `max_rtv_speed 100 cm/s`); NCSS 6 km box over the
whole window at 17:00 Z: 200, 95 KB, 10,921 cells, **1,662 valid, spanning 41.31-45.89 N, -126.36..-123.99 E, max
speed 0.82 m/s**; NCSS 2 km Oregon box: 305 KB, 1,336 valid cells confined to 43.95-44.83 N (the Newport
standard-range pair); NCSS 2 km Washington box (45.5-48.5 N): 138 KB, **0 valid cells**. The 17:00 Z file was created
18:38 Z and was still the newest at 19:47 Z: latency 2-3 h. NCSS sends no CORS header.

Radar sites in the window (stationList.php, 2026-10-13; codes are the official ids, place names are my reading of
the coordinates and unverified):

| Site | Network | Band | Lat, lon | Last radial | Note |
|---|---|---|---|---|---|
| KAL1 | OSU | 4.46 MHz long range (6 km) | 47.567, -124.362 (Kalaloch?) | 2026-10-13 | added 2026-03-26; site computer replaced per NANOOS 2026 report |
| WSP1 | OSU | long range | 46.903, -124.132 (Westport) | 2026-10-13 | added 2023 |
| LOO1 | OSU | long range | 46.433, -124.059 (Loomis Lake, Long Beach peninsula) | 2026-10-13 | re-tuned and reinstalled mid-2026 |
| STV2 | OSU | 12.2 MHz standard | 46.176, -123.978 | 2025-03-12 | down |
| SEA1 | OSU | standard | 45.975, -123.945 | 2021-04-28 | removed |
| MAN1 | OSU | long range | 45.640, -123.942 (Tillamook coast) | 2026-10-13 | |
| YHL1 / YHS2 | OSU | long / standard | 44.676, -124.077 (Yaquina Head) | 2026-10-13 | |
| WLD2 | OSU | standard | 44.384, -124.090 (Waldport) | 2026-09-11 | down a month; its `_hfr_wave` dataset too |
| WSH1 | OSU | 13.5 MHz standard | 44.162, -124.118 | 2026-10-13 | also `OSU_WSH1_hfr_wave`: 18:40 Z today, `PMWH 1.32 m, WNDB 274` (radar-derived wave height) |
| WIN1 | OSU | long range | 43.666, -124.207 (Winchester Bay) | 2026-10-13 | |
| CBL1 | OSU | long range | 42.837, -124.566 (Cape Blanco) | 2026-10-13 | |
| PSG1 | OSU | long range | 41.785, -124.255 (Pt St George) | 2022-07-05 | down |
| TRIN | BML | long range | 41.074, -124.158 (Trinidad) | 2026-03-05 | down |

Caveats: totals need two overlapping radars, so WA coverage depends on LOO1+WSP1+KAL1 all running and on
sea state; today they gave nothing. The 6 km product is the one to draw (long-range sites); the 2 km product only
fills around Newport. Surface currents represent the top ~1 m; coastal cells within ~5 km of shore are usually
missing. Nothing in the Strait of Juan de Fuca or Puget Sound (no radars). Vancouver Island: none in HFRNet; Ocean
Networks Canada's Tofino radar is outside this note. Radials ERDDAP sends no CORS header.

## 3. OOI Coastal Endurance Array

Ocean Observatories Initiative (NSF; Endurance Array run by OSU/UW). Surface moorings in the window: CE01ISSM
Oregon Inshore 44.659 N -124.096 E, CE02SHSM Oregon Shelf 44.635 N -124.304 E, CE04OSSM Oregon Offshore 44.37 N
-124.95 E, CE06ISSM Washington Inshore 47.13 N -124.27 E, CE07SHSM Washington Shelf 46.987 N -124.564 E, CE09OSSM
Washington Offshore 46.85 N -124.97 E (positions from the NVS asset list and ERDDAP). Cabled Oregon Shelf/Offshore
benthic packages and the Washington Offshore profiler also stream.

**Endpoint pattern.** `https://erddap.dataexplorer.oceanobservatories.org/erddap/tabledap/<id>.csv?...` with ids like
`ooi-ce02shsm-sbd11-06-metbka000` (bulk met: `air_temperature`, `sea_surface_temperature`, `eastward_wind`,
`northward_wind`, `air_pressure`, RH, precipitation, fluxes, surface salinity) and `ooi-ce07shsm-sbd12-05-wavssa000`
(`sea_surface_wave_significant_height`, `_significant_period`, `_mean_period`, `_maximum_height`, `_to_direction`).
The "gold copy" host `erddap-goldcopy.dataexplorer.oceanobservatories.org` returned **502** today. OOI's M2M API and
Data Portal need a free login: not used.
**Fetched today.** allDatasets filtered to `ce0*` with data since 2026-09-01: 200, 46 datasets (ce02shsm 11,
ce07shsm 17, ce02shbp 4, ce04osbp 5, ce04osps 3, ce09ospm 4; **nothing from CE01ISSM, CE04OSSM, CE06ISSM or CE09OSSM
surface buoys**, so those are off or not telemetering). Samples: CE02SHSM met `2026-10-13T02:06Z Ta 12.5, SST 12.2,
p 1018.0, wind NaN`; CE07SHSM waves `2026-10-12T03:23Z Hs 1.54 m, Ts 10.3 s, to-dir 289`. At 19:47 Z that is
**18 h and 40 h behind**: the ERDDAP mirrors the daily telemetered dump, not the hourly Iridium feed. No CORS header.
**Licence.** oceanobservatories.org/how-to-use-acknowledge-and-cite-data (read 2026-10-13): "All OOI data are freely
available to everyone who has an Internet connection." and "The only requirement for use of OOI data is to
acknowledge OOI as its source, provide citations where appropriate". Acknowledgement text: "This material is based
upon work supported by the Ocean Observatories Initiative (OOI)... under Cooperative Agreement No. 2244833". The
ERDDAP datasets carry the standard "may be used and redistributed for free" licence attribute.
**Use instead:** NDBC relays the same buoys hourly as 46097 (OOI Oregon Shelf? not verified), 46098, 46099 "OOI
Westport Shelf" (station page confirms "owned and maintained by NSF Ocean Observatories Initiative") and 46100; the
NDBC note should carry them. Take wave spectra or pCO2/pH from OOI ERDDAP only for a "yesterday" panel.

## 4. IOOS national ERDDAPs and the Sensor Map

| Server | What it holds for the window | Fetched today | Licence / CORS |
|---|---|---|---|
| `https://erddap.sensors.ioos.us/erddap` (Axiom, behind sensors.ioos.us) | 1,017 datasets with data since 2026-10-01 in the window: 311 SNOTEL, 231 CO-OPS, 159 BC hydrometric, 124 USGS, 95 airports, 19 NDBC, 6 CDIP, 7 USCRN, 4 live gliders, Humboldt `edu_humboldt_tdp`, Klamath-Yurok. **No NANOOS mooring, no OOI, no Backyard Buoy.** | `allDatasets` box query 200 (115 KB) | legal.html: dataset `license` attribute governs. **Sends `Access-Control-Allow-Origin`** (echoed the test origin, with credentials). |
| `https://erddap.ioos.us/erddap` | 10 datasets: RA boundaries, asset inventories, GTS reports, ETOPO5. Nothing live. | info list 200 | n/a |
| `https://sensors.ioos.us/` (IOOS Sensor Map) | RequireJS app; the HTML names only Axiom's `cam-api.srv.axds.co` (webcams). Its data path is the ERDDAP above. | 200 | no separate API to use |
| `https://gliders.ioos.us/erddap` (Glider DAC) | see §5 | 200 | **`Access-Control-Allow-Origin: *`** |
| `https://hfradar.ioos.us/radials-erddap/erddap` | HF radar radials and `*_hfr_wave` | 200 | public domain (§2) |

The Sensor Map is therefore not a shortcut: for NANOOS assets go to §1, for federal stations use the agencies.

## 5. Gliders (IOOS Glider DAC)

`https://gliders.ioos.us/erddap/tabledap/<deployment>.csv?time,latitude,longitude,depth,temperature,salinity&time>=now-1day`
and `allDatasets` with a bounding box. Live in the window today: `sg263-20260831T1514` (UW La Push line, last
2026-10-08), `sg272-20260203T1845` (La Push, to 2026-08-31), `osu592-20260915T1700` (OSU Washington shelf line,
46.8-47.5 N, to 2026-10-01), `ce_1137-20260727T1719` and `ce_320-20261003T1834` (OOI Endurance, 44.6-47 N, today),
`sg686-20260918T0700` (Trinidad Head line, 41 N, today), DFO Canadian gliders off Vancouver Island (summer).
Licence (`sg263` attributes): "Creative Commons Attribution 4.0 International Public License"; institution UW-APL.
Map value: a track with last surfacing position and surface temperature; a novelty rather than a need. Hourly pull
of `allDatasets` plus the newest point per deployment is cheap.

## 6. Columbia River plume and estuary: CMOP / SATURN

`https://critfcweb.ohsu.edu/erddap` (CRITFC-CMOP) returned **503** today. Its out-of-date report (June 2026, from
search) flags most SATURN-03 sensors stale since 2023; the NANOOS mirror holds SATURN-02 to 2025-10-25 and
SATURN-03/07 to 2025-11-14. NVS still references CMOP forecast hosts (`amb6400b.stccmop.org/wms/fcastjson.php`), which
did not respond. Treat SATURN as retired; for the bar use NDBC 46029, CDIP 46243 Clatsop Spit and CO-OPS.

## 7. NVS front end (nvs.nanoos.org) and asset catalogue

- The app loads `/local/apps/<App>/cache/merged.js` and sets `PARAMS.geoserver_url = https://data.nanoos.org/geoserver/`
  (every GeoServer URL tried: 404; the 52North SOS at `data.nanoos.org/52nsos`: 404) and `PARAMS.tile_server_url =
  https://coral.apl.uw.edu/eis-live/` (403 at the root; it serves the model/satellite overlay tiles).
- Data calls are `PARAMS.url_base + "ssa/<name>.php"`: `get_platform_data.php`, `get_recent_measurements.php`,
  `get_platform_values.php`, `get_platform_info.php`, `get_grid_data.php`, `get_siso_list.php` (station list),
  `get_retired_platform_list.php`, `get_ajax_cross_domain.php` (a proxy), `transects.php`, `routes.php`. A bare GET on
  `get_recent_measurements.php` returned `{"success": false, "result": []}` (200): they take POST parameters the
  bundle builds, and nothing documents them. Not a stable base to build on; use ERDDAP.
- **Asset list CSV: `https://nvs.nanoos.org/services/download_asset_list.php`** (GET, 200, 94 KB, octet-stream).
  Columns `ID, Name, Description, Type, Lat, Lon, URL, Region, State / Province, Provider, Provider Type, Provider URL,
  Measurements`. 266 assets: 84 fixed shore platforms, 79 buoys, 37 river gauges, 12 land stations, 11 shellfish
  rafts, 10 models, 7 gliders, 7 satellites, 6 cabled platforms, 2 radars. Providers include USGS, CO-OPS, CMOP
  (retired ones still listed), WA DOH (19 HAB/beach sampling sites), CDIP, OSU, NDBC, OOI, NERRS, Environment
  Canada, ONC, King County, Hakai. This is the documented "Asset List" download (NANOOS Asset Inventory PDF) and is
  the quickest way to get ids and coordinates for everything NANOOS shows, including the Canadian buoys
  (EC 46206 La Perouse Bank 48.834 N -126.0 E, 46146, 46303/46304 Strait of Georgia).
- `nvs.nanoos.org/Surfers` and `/BeachView` are app shells (Map, Beach Closures, Articles tabs); the measurement
  dictionary in the Surfers bundle includes wind, air temperature, pressure, CO2 and domoic acid. Beach View lists
  Washington and Oregon beach closures (WA DOH biotoxin, OR advisories) inside the app only.
- Terms: the Disclaimer page quoted in §1; no robots or terms text forbids reading these pages. The per-source
  licences still apply to the data.

## 8. HAB, beach and ocean-acidification products

| Product | Form | Fetched | Use |
|---|---|---|---|
| PNW HAB Bulletin (NANOOS, UW ORHAB, NOAA) `nanoos.org/products/habs/forecasts/bulletins.php` | PDF per issue; 2026 issues 05-12, 05-26, 09-24, **10-04** (latest); roughly fortnightly in razor-clam seasons | index 200 | link out from a "beach notices" line; nothing to poll |
| NVS Beach View closures | in-app lists for WA and OR | page 200 | link out; WA DOH shellfish/biotoxin map is the primary source (other note) |
| IPACOA `www.ipacoa.org` (IOOS Partners Across Coasts OA) | NVS-framework portal; OA data (pCO2, pH, aragonite) from shore stations and buoys | 200 | no API; the live OA streams for the window are `chaba_hydro` pH and the OOI pco2/ph datasets (§1, §3) |
| PMEL La Push MAPCO2 (on Cha'ba) `data.pmel.noaa.gov/co2/story/La+Push` | pages/plots | not fetched | science product; skip |
| Averages & Anomalies (`nvs.nanoos.org/AveragesAnomalies`) | NVS app: NDBC climatologies, MODIS SST/chl monthly means | not fetched | a "normal for this date" SST could come from here but only through the app |

Washington water temperature for surfers: the live numbers are Cha'ba `chaba_hydro.sea_water_temperature`, the
Backyard Buoys `sea_water_temperature`, OOI CE07SHSM SST (day old), plus NDBC/CDIP (other note).

---

## What to use first (ranked)

1. **NANOOS/APL ERDDAP, Cha'ba met + hydro** (`chaba_met_all`, `chaba_hydro`): the only wind, pressure, SST and pH
   buoy on the north Washington coast; JSON in one request; free-redistribution licence; 1-2 h latency.
2. **Backyard Buoys** (`backyardbuoys_quileute_center` first; the other five when their `maxTime` is fresh): inshore
   wave height/period/direction and water temperature exactly where La Push and Quinault surfers stand. CC BY-NC:
   credit the Quileute Tribe / Quinault Indian Nation and keep the site non-commercial.
3. **HF radar 6 km surface currents** via NDBC NCSS: a true map layer (arrows or speed raster) for rips, bar
   crossings and kiters; one ~100 KB NetCDF per hour for the whole window; public domain with the HFRNet credit.
   Draw Oregon; show Washington when cells appear; label the hour.
4. **Puget Sound / Hood Canal met buoys** (ORCA Twanoh, Hansville, Point Wells, Carr Inlet; PISCES-North/East;
   Se'lhaem Bellingham): inland wind for kiters, one ERDDAP call each, 20 min to 1 h latency.
5. **OOI Endurance via NDBC 46097-46100** for hourly shelf wind/waves (NDBC note); OOI ERDDAP only for
   day-old wave spectra, pCO2 and pH.
6. **NVS asset list CSV** as a one-off seed for ids and coordinates (and the Canadian buoys), refreshed by hand.
7. **Gliders** (Glider DAC, CC BY 4.0, CORS `*`): optional track layer.
8. Link-outs only: PNW HAB Bulletin, Beach View, IPACOA. Skip: CMOP/SATURN, sensors.ioos.us as a NANOOS route,
   GeoServer/SOS, NVS `ssa/*.php`.

## Open questions

1. Is the Backyard Buoys CC BY-NC licence compatible with how Chris wants to run the site (no ads, no paid tier)?
   If yes, what credit line do the tribes want shown? (Contact via NANOOS or the dataset `creator_name`.)
2. Which host to poll: `erddap.nanoos.org` (branded, but 302s some ids to plain-http `nwem.apl.washington.edu`) or
   `nwem.apl.washington.edu` directly (same data, more datasets, no redirect)? Suggest the APL host with the NANOOS
   one as fallback, and re-check the 302 behaviour before building.
3. HF radar: how often does Washington get total vectors now that KAL1 is up (2026-03)? A week of hourly NCSS
   pulls would answer it before deciding whether to promise a WA layer.
4. OOI: confirm the NDBC ids for the four Endurance surface buoys (46099 = Westport Shelf confirmed; 46097/46098/46100
   not checked) and whether CE01/CE04/CE06/CE09 surface buoys are deployed this season (no data since Sept).
5. Backyard Buoys and OCNMS landers are seasonal; the map needs a "last reported" age rule (the webcams layer's
   36 h stale rule would hide most of them for half the year, which is probably right).
6. Is there appetite for the Canadian side (ONC Tofino HF radar, EC 46206, DFO gliders)? None of it is in HFRNet or
   the NANOOS ERDDAP; it would be a separate note.
