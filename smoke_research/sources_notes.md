# Smoke, fires and air quality: data sources (research 2026-09-27)

Research agents fetched each source 2026-09-28 01:40–01:55 UTC (evening of 2026-09-27 Pacific). **F** = fetched and
checked, **D** = from docs only. Nothing here is built yet; the design comes next and goes to Chris for approval.
Agents' scratch scripts were in the session scratchpad (deleted with it).

Chris's decisions so far (2026-09-27): AQI stations are the high priority; AQI stations plus an optional interpolated
AQI map get **their own panel section** ("Air quality"), separate from "Smoke & fires". At 19:10 he chose: Air quality
first, then fires, then the smoke forecast loop; AirNow's gridded AQI now, HRRR-fused surface later; official AQI
colours (AirNow guideline) over muted ones; PurpleAir left out.

## Already on the map
NWS alerts (`alerts.py`) keep every event type, so Red Flag Warnings (red), Fire Weather Watches (amber), Air Quality
Alerts and Dense Smoke Advisories (default blue) already show.

## Fires

| Source | Shows | Coverage | Latency (measured) | Key / terms | Size |
|---|---|---|---|---|---|
| WFIGS Incident Locations Current (NIFC ArcGIS) | US incidents: name, acres, % contained, discovery, IRWIN id, cause | US | layer edited 4 min before fetch; IRWIN sync every 5 min (D) | keyless, public | 108 KB all 5 regions, trimmed fields (F) |
| WFIGS Interagency Perimeters Current | US perimeters | US | newest polygon 12 h (IR flights ~daily) | keyless | 21 MB raw PNW; 724 KB all regions with `maxAllowableOffset=0.001&geometryPrecision=4` (F) |
| NOAA NGFS (fire.data.nesdis.noaa.gov OGC API) | GOES detections every 5 min, tracked features, typed (possible / known incident, with IRWIN) | CONUS + Canadian strips | ~6 min (F) | keyless; **beta**, "as is" | 718 KB West 24 h raw |
| NASA FIRMS keyless CSVs | VIIRS (S-NPP, NOAA-20, -21) + MODIS hotspots | US file to 49.8°N, Canada file from 40°N (dedupe) | NRT only: VIIRS 4.6–5.7 h, MODIS 2.4 h (F) | keyless; acknowledge FIRMS/LANCE | ~185 KB per satellite US 24 h |
| FIRMS area API (MAP_KEY) | same + URT/RT (under 60 s–30 min, D) | same | — | free key by email (Chris signs up); server-side only | small |
| CWFIF national active fires (NRCan GeoServer WFS) | Canadian incidents: size ha, stage of control | Canada | record 3 min old (F) | keyless, OGL-Canada, citation | 172 KB national |
| BCWS ArcGIS (fires, perimeters, EMBC evacuations) | names, `FIRE_URL`, perimeters, evacuation orders/alerts | BC | minutes (F) | keyless, OGL-BC | 23 / 111 / 26 KB |

Skipped: HMS fire points (lag, 86% from NGFS), GOES FDC raw (NGFS processes it), CWFIS hotspots (re-serves FIRMS),
InciWeb RSS (no IRWIN, bad coordinates; match by name only), CAL FIRE API (403 to scripts; WFIGS has CAL FIRE via IRWIN),
Esri Living Atlas VIIRS (re-serves FIRMS, unclear licence).
Not usable: Watch Duty (terms ban automated access; enterprise API only); US evacuation zones (Genasys/Zonehaven
layers embed county authkeys; not used). BC's EMBC layer is the only public keyless evacuation source found.

Endpoints (F):
- `https://services3.arcgis.com/T4QMspbfLg3qTGWY/arcgis/rest/services/WFIGS_Incident_Locations_Current/FeatureServer/0/query`
  (also `WFIGS_Interagency_Perimeters_Current`, `WFIGS_Incident_Locations_Last24h`); `f=geojson` ignores
  `quantizationParameters`, use `maxAllowableOffset`. Filter `IncidentTypeCategory IN ('WF','CX')`, drop `IsCpxChild`.
- `https://firms.modaps.eosdis.nasa.gov/data/active_fire/{noaa-20-viirs-c2|noaa-21-viirs-c2|suomi-npp-viirs-c2|modis-c6.1}/csv/{J1|J2|SUOMI}_VIIRS_C2_{USA_contiguous_and_Hawaii|Canada}_{24h|48h|7d}.csv`
- `https://fire.data.nesdis.noaa.gov/api/ogc/detections/collections/ngfs_schema.ngfs_features_scene_{west|east}_conus/items?f=json&bbox=...&datetime=T0/T1&datetime-column=acq_date_time&limit=5000`
  (responses carry `max-age=3600`: always send a fresh datetime range; fall back to FIRMS on failure).
- `https://geoserver.cwfif.nrcan.gc.ca/geoserver/wfs?service=WFS&version=2.0.1&request=GetFeature&outputFormat=application/json&typeName=public:cwfif_national_activefires&CQL_FILTER=now()>=record_start AND now()<=record_end&srsName=EPSG:4326`
  (the old CWFIS `activefires.csv` is stale since 16 Jul 2026).
- `https://services6.arcgis.com/ubm4tcTYICKBpist/arcgis/rest/services/{BCWS_ActiveFires_PublicView|BCWS_FirePerimeters_PublicView|Evacuation_Orders_and_Alerts}/FeatureServer/0/query`
  with `where=FIRE_STATUS<>'Out'` (else the 1000-record cap fills with out fires).

Open for Chris: FIRMS MAP_KEY for URT? Show unconfirmed NGFS detections publicly? Hide or grey prescribed burns?
Show BC evacuation orders when the US side has none?

## Smoke

The three sites Chris named (F):
- weather.gov/boi/smoke: "Experimental Smoke Forecast", two Idaho loops (near-surface, vertically integrated) from
  **RRFS 84 h** (`rrfs_id_84hr_nssmoke.mp4`, `_vismoke.mp4`), hourly. Pre-drawn maps without georeferencing: link only.
- rapidrefresh.noaa.gov/hrrr/HRRRsmoke: GSL research plots of operational HRRR smoke, "research purposes only", some
  runs missing. Link only; use HRRR itself.
- wasmoke.blogspot.com: human forecasts; Atom feed `/feeds/posts/default` works (newest post 2026-09-18). Siblings:
  oregonsmoke.org (2026-08-31), idsmoke.blogspot.com (2026-09-03), colosmokeoutlook.blogspot.com (2026-09-18);
  californiasmokeinfo dormant since 2025-09; Montana DEQ 403s scripts; none for UT or the Northeast.
  AirFire outlooks JSON is the better headline source: `https://airfire-data-exports.s3.us-west-2.amazonaws.com/outlooks/v7/latest_outlooks.json`
  (plain-language point forecasts with AQ category today/tomorrow, near active incidents only).

| Source | Shows | Coverage | Cadence / latency | Effort | Terms |
|---|---|---|---|---|---|
| HRRR MASSDEN 8 m (AWS `noaa-hrrr-bdp-pds`, `wrfsfc`) | near-surface smoke forecast, 3 km | 4 regions fully; PNW ~82% (grid ends ~50°N in BC) | hourly; 48 h at 00/06/12/18Z; f01 ~51 min, f48 ~1 h 48 min after run (F) | GRIB byte range 0.80 MB/hour (COLMD 0.93 MB) | public domain |
| ECCC RAQDPS `Sfc_PM2.5-WildfireSmokePlume` (GeoMet WMS) | near-surface forecast, 10 km | all 5 incl. BC | 00/12Z, 72 h, ~3.6 h (F) | none: browser WMS with TIME | attribution "Data Source: Environment and Climate Change Canada" |
| HMS smoke polygons (NOAA ArcGIS / KML) | observed column smoke, light/medium/heavy | all | ~2 issues/day (D) | none (ArcGIS returns GeoJSON) | free |
| NDGD surface smoke (NWS ImageServer WMS) | near-surface forecast | US | once a day, ~21 h old (F) | none | free |
| RRFS (NOMADS `rrfs/v1.0`, parallel) | smoke + dust + PM2.5; 3 km CONUS, 13 km N. America | all (13 km) | 84 h at 00/06/12/18Z; gaps in the parallel feed (F) | as HRRR; smoke 0.67 MB (3 km) / 0.25 MB (13 km) per hour; pick the `MASSDEN` record by aerosol text | free; NOMADS only (not on AWS in real time), rate limits |

Skipped: NAQFC (total PM2.5, 65 MB files, no idx, slower), GOES ADP/AOD (column, daytime only).
RRFS goes operational **2026-10-14** (D: SCN 26-48 update); HRRR stays, no retirement date. ECCC FireWork (`RAQDPS-FW.*`)
is historical only now; live smoke is the RAQDPS `WildfireSmokePlume` layers. Don't request GeoMet's full GetCapabilities (40 MB).

Endpoints (F):
- `https://noaa-hrrr-bdp-pds.s3.amazonaws.com/hrrr.YYYYMMDD/conus/hrrr.tHHz.wrfsfcfFF.grib2.idx`: `MASSDEN:8 m above ground`
  record 76, `COLMD` record 112; byte ranges return 206; decodes as 1799×1059 kg/m³ (eccodes shortName `unknown`, cat 20 par 0).
- `https://nomads.ncep.noaa.gov/pub/data/nccf/com/rrfs/v1.0/rrfs.YYYYMMDD/HH/rrfs.tHHz.2dfld.{3km.fFFF.conus|13km.fFFF.na}.grib2.idx`
- `https://services2.arcgis.com/C8EMgrsFcRFL6LrL/arcgis/rest/services/NOAA_Satellite_Smoke_Detection_(v1)/FeatureServer/0/query?where=1%3D1&outFields=Satellite,Start,End_,Density&f=geojson`
- `https://satepsanone.nesdis.noaa.gov/pub/FIRE/web/HMS/Smoke_Polygons/KML/YYYY/MM/hms_smokeYYYYMMDD.kml`
- `https://geo.weather.gc.ca/geomet?SERVICE=WMS&VERSION=1.3.0&REQUEST=GetMap&LAYERS=RAQDPS.Sfc_PM2.5-WildfireSmokePlume&STYLES=PM2.5_1e-9to2.5e-7kgm3&CRS=EPSG:4326&...&TIME=...`
- `https://mapservices.weather.noaa.gov/raster/services/air_quality/ndgd_smoke_sfc_1hr_avg_time/ImageServer/WMSServer`
- `https://services.arcgis.com/cJ9YHowT8TU7DUyn/ArcGIS/rest/services/Air_Now_Current_Monitors_PM25/FeatureServer/0/query`
  (PM25, PM25_AQI, ValidTime; 01:00Z data up by 01:47Z)

Cross-check 2026-09-27: every source put the one big plume near Yosemite (~37.7°N 119.6°W): HRRR peak 461 µg/m³,
HMS "Heavy" polygon, ECCC plume, AirFire outlooks for Tuolumne Meadows and Yosemite Valley.

Open for Chris: HRRR in Actions vs ECCC WMS with no code; when to move to RRFS; colour scale (AQI breakpoints vs µg/m³)
and transparency floor; show column smoke (HMS) at all, labelled "smoke aloft"?

## Air quality stations

| Source | Coverage in the 5 boxes | Latency | History | Key / terms |
|---|---|---|---|---|
| **AirNow `HourlyAQObs`** (files.airnowtech.org) | 729 PM2.5 sites (637 US, 92 Canada incl. ~44 BC): PNW 242, Sierra 162, UT/CO 104, IMW 100, NE 218; no temporary monitors | 00Z hour first at 01:23, re-posted 01:45; last 72 h rewritten hourly (F) | 72 h of files, ~1 MB each | keyless; AirNow Data Exchange Guidelines |
| **AirNow `AirNowWildfire.csv`** | 37 temporary smoke monitors (35 in boxes): NowCast conc + AQI | hourly (F) | latest hour only | keyless; same |
| **USFS AirFire exports** (`airfire-data-exports`, monitoring/v2/latest) | 853 in boxes incl. 43 temporary, 77 SensWA, 32 SensOR | ~45 min after the hour (F) | **10 days hourly**, raw and NowCast | keyless; "provisional, use at own risk"; undocumented bucket |
| AirNow API | same monitors (+ mobile via `monitorType=2`) | hourly | date ranges | free key; 500 req/h; AirNow recommends the files for big areas |
| PurpleAir | ~16,500 sensors in boxes (PNW 3,511, Sierra 6,616, UT/CO 1,450, IMW 920, NE 2,519) | 10 min | API | **paid points** (1M free once, then 100k/$; est. 1–2M/day); terms limit end users to "internal, non-commercial, non-public use", distribution needs notice to PurpleAir |
| OpenAQ v3 | re-serves AirNow; PurpleAir left | extra hop | yes | free key; adds nothing |
| ECCC AQHI / BC Current_Hour.xml | AQHI only / 48 BC PM2.5 (mostly already in AirNow) | ~40 min | — | skip |

Checked by the main session 2026-09-28 02:00 UTC: `HourlyAQObs_2026092800.dat` 200, 1.0 MB, 4,434 rows, columns
SiteName, Latitude, Longitude, ValidDate, ValidTime, PM25_AQI, PM25_Measured, PM25, PM25_Unit; `AirNowWildfire.csv`
columns Latitude, Longitude, SiteName, Time, NowCast Concentration, NowCast AQI; `current_pm25.grib2` 2.6 MB, posted 01:44:48.

Recommendation (agent): colour by AirNow's own `PM25_AQI` (NowCast AQI; guidelines say don't alter values); add the
temporary monitors from `AirNowWildfire.csv`; keep our own rolling 72 h store in R2 (fetch the newest 1–2 hours each run,
late data backfills); bootstrap and back up temporary-monitor history from AirFire
(`monitoring/v2/latest/data/airnow_PM2.5_[nowcast_]latest_{data,meta}.csv`, wide CSV, ~1.3 MB each). Sparkline: hourly raw
µg/m³ with NowCast; trend from the last 3 raw hours (NowCast lags by design). Where we compute AQI, use the May 2024 PM2.5
breakpoints 9.0 / 35.4 / 55.4 / 125.4 / 225.4 / 325.4 (the Fire and Smoke Map uses the same). AirFire NowCast with those
breakpoints matched AirNow's AQI exactly at 93% of 1,215 stations, within 2 points at 97%.

AirNow guidelines: credit the reporting agencies and AirNow, label data **"preliminary"**, don't alter values, use the
official AQI colours; a form "to return" to dmc@airnowtech.org (Chris's call).

PurpleAir, if ever: EPA Eq. 4 (Oct 2021 extended), A/B average of cf_atm, valid if A and B agree within 5 µg/m³ or 70%;
below 30: 0.524·PA − 0.0862·RH + 5.75; 30–50 blend; 50–210: 0.786·PA − 0.0862·RH + 5.75; 210–260 blend;
260+: 2.966 + 0.69·PA + 8.84e-4·PA² (Fire and Smoke Map Q&A PDF). Re-serving the Fire and Smoke Map's PurpleAir tiles
without a PurpleAir licence is not OK.

Surprises: airnow.gov (www, fire., document.) fails to resolve through 1.1.1.1 and 8.8.8.8 (checked 02:00 UTC; agent
traced it to a DNSSEC signature that expired 2026-09-26 15:06 UTC); files.airnowtech.org is unaffected. Don't make
airnow.gov links load-bearing. AirFire's `.csv.gz` copies are stale (January data, fresh Last-Modified); use the plain
`.csv` and check dates inside. `HourlyAQObs` also misses 30 of 77 SensWA sensors (AirFire has them).
`near-me.airfire.org/fasm/monitor` is an undocumented API behind the Fire and Smoke Map: don't build on it.

### Interpolated AQI map
- **AirNow `current_pm25.grib2`** (archive `US-YYMMDDHH_pm25.grib2`): gridded NowCast AQI, 0.0225° (~2.5 km), 3700×1778,
  2.6 MB, far-from-monitor cells blanked (9999); keyless, hourly (F). Method (D, fact sheet): IDW power 5, 10 nearest
  monitors, monitors only. Grid vs station AQI at 713 sites: mean difference 1.0 (F). Unblanked share: PNW 0.83,
  Sierra 0.54, UT/CO 0.59, IMW 0.75, NE 0.80. A KML of AQI-category polygons also exists (1.4 MB).
- No monitor+sensor "fused" surface found in AirNow's files or the Fire and Smoke Map code.
- Plain IDW is not defensible across mountains on its own (spreads valley inversions onto ridges and clean ridge air into
  valleys; power-5 IDW is close to nearest-monitor patches). Defensible options: show AirNow's grid as is, labelled
  "monitors only, interpolated", keeping its blanking; or, better, HRRR near-surface smoke as the background field with
  monitor-minus-model residuals interpolated (standard data fusion), masked by distance (~25–50 km) and elevation
  difference (~300 m) from the nearest monitor.
