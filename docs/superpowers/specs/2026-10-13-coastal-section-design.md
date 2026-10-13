# Coastal section: design (2026-10-13)

A new "Coastal" group in the radar map's layer panel for surfers, kiters and anyone on the salt water of the
Pacific Northwest: buoys and shore stations (waves, wind, water temperature), tides and tidal currents, the NWS
marine and surf-zone forecasts, and a satellite sea-surface-temperature overlay. Marine hazards join the existing
Alerts layer; ocean-facing webcams join the existing webcam lists. Research and the source catalogue:
`coastal_research/CATALOG.md` and the per-topic files there (every endpoint was fetched 2026-10-13).

Chris's decisions (2026-10-13): build it through to deployment; the site is non-commercial, so the CHS tide licence
(no navigation use, no commercial derivatives) and the Backyard Buoys CC BY-NC licence are accepted with credit;
use the rest of the site as the guide for content and presentation.

## 1. Scope

In this release:
1. **Buoys & shore stations** layer: every NDBC station in the window (NDBC's own buoys and C-MAN stations plus the
   CDIP, OOI, NANOOS and Environment Canada stations it relays), the six CDIP Waveriders from CDIP's own ERDDAP, the
   three Canadian buoys from ECCC's Datamart (NDBC's relay drops their direction and shows a wrong period), the
   NANOOS Cha'ba buoy and the Backyard Buoys Spotters from the NANOOS ERDDAP, and the NOAA CO-OPS stations that
   report wind or water temperature. Chips: **Waves** (default), **Wind**, **Water temp**. Popup: the full report,
   a 24 h wave-height trace, the swell / wind-wave split where the buoy gives it, credit and link.
2. **Tides & currents** layer: CO-OPS tide stations (observed water level and water temperature at the 24 live
   ones, high/low predictions for all 230) and CHS stations in BC (27 operating with observations, predictions for
   the rest), plus CO-OPS tidal-current prediction stations at the named passages and the CHS current stations at
   the BC passes. Popup: a 48 h tide curve (12 h back, 36 h ahead), the next highs and lows, "rising, high at 14:32
   (2 h 10 min)", water temperature, wind; for currents, today's and tomorrow's slack and max table and the state now.
3. **Marine forecast** layer: the NWS coastal-waters zones (PZZ) of the region's offices as polygons, coloured by
   the headline wind of the first forecast period, popup with the zone forecast periods and, where the office
   issues one, its Surf Zone Forecast text (PQR, MFR, EKA; SEW issues none). Environment Canada's marine areas are
   a second release (open item).
4. **Sea surface temperature** layer: NOAA's Geo-Polar Blended 5 km daily analysis as an image overlay with a
   legend, a click-anywhere row ("sea surface temp 52 °F (satellite, 2 days old)"), and the nearest buoy or
   station water temperature in the same click-anywhere row set.
5. **Alerts**: marine zone alerts (area `PZ`) added to `alerts.py` for regions with a coast, clipped to the window,
   so Small Craft Advisories, Gale Warnings, Beach Hazards Statements (sneaker waves), High Surf and Rip Current
   Statements show in the existing Hazards > Alerts layer. (Beach Hazards and High Surf are land-zone products that
   already arrive through the state filter; `PZ` adds the water zones.)
6. **Webcams**: the ranked ocean-facing cams from `coastal_research/webcams.md` added to `webcams_youtube.json`
   (18 streams, 4 id refreshes) and `webcams_extra.json` (Yaquina Bay bar, Point Roberts); the Kalaloch URL fixed;
   the dead Cannon Beach CBCC entry removed. No new layer: they are `kind: "water"` cams like the existing ones.

Deferred to a second release (recorded so nothing is lost):
- The evaluated **spot table** (54 surf, 38 kite spots drafted in `coastal_research/user_needs.md`): half is marked
  lore; it needs Chris's review before it is published, and a spot checklist UI is a design of its own.
- **HF radar surface currents** (NetCDF only; Washington coverage intermittent), **GFS-Wave swell raster**, **NWPS**
  nearshore waves, **HRDPS** wind for the Strait, the **biotoxin and beach-closure** layers, the Canadian marine
  forecast areas, per-spot wind timelines. Each is catalogued with endpoints in `coastal_research/`.
- Other regions: the modules are window-based (NDBC, CO-OPS and api.weather.gov are national), so `sierra` and
  `ne` can turn the section on later by setting `coastal` in `region.py`. Only `pnw` is on in this release.

## 2. Where it runs

Same free-tier pipeline as every other layer: Python modules under `radar/`, one per source family, run by
`capture.py` for the region in `REGION`, written to `data/*.js` (and `frames/sst/`) and uploaded by `r2sync`.

| Module | Writes | Cadence | Slot in `capture.py` |
|---|---|---|---|
| `buoys.py` | `data/buoys.js` -> `window.BUOYS` | every half hour (the buoys report hourly or every 30 min; wind at CO-OPS stations every 6 min) | the half-hour slot, after `rivers` |
| `tides.py` | `data/tides.js` -> `window.TIDES`; state `tides_cache.json` (predictions, fetched once a day per station) | every half hour for observations; predictions refreshed when the cache's day changes | the half-hour slot, after `buoys` |
| `marine.py` | `data/marine.js` -> `window.MARINE`; zone geometry in the existing `zone_cache.json` | hourly | the hourly slot, after `forecast` |
| `sst.py` | `frames/sst/sst.webp`, `data/values/sst.js`, `data/sst.js` -> `window.SST` | hourly job; downloads only when a newer analysis day is posted (like `snodas.py`) | the hourly slot, after `snodas` |
| `alerts.py` | unchanged file, `PZ` zones added | every 15 min (as now) | as now |

Each module runs only when `region.cfg().get("coastal")` is set (pnw: `"coastal": True`); `build_web.py` passes
`coastal` into the page's `REGIONS` table so the panel group is hidden for regions without it, the way
`REG.snotel === false` hides the SNOTEL layer. New state file: `tides_cache.json` (added to `cloud.py STATE_FILES`).

Request budget per region per half hour (pnw): NDBC `latest_obs.txt` (1) + `realtime2/<id>.txt` for each station
reporting waves (about 20) + `.spec` for the stations that have one (about 8) + CDIP (1) + ECCC SWOB-ML (3) + NANOOS
ERDDAP (about 8) + CO-OPS observations (24 water level + 15 water temperature + 12 wind, one request per product per
station, about 50) + CHS observations (27). About 140 small requests, under 4 MB; the daily prediction refresh adds
about 230 CO-OPS + 124 CHS + 25 current-station requests once a day, spread over the day by refreshing stations whose
cached day is stale (at most 60 per run), so no single run is long. Every fetch: plain `User-Agent`
(`RadarTracker/1.0 (personal weather map)`; the api.weather.gov calls keep the site's existing header), 20 s
timeout, two tries, a host that times out is skipped for the rest of the run (`airquality.HostDown` pattern).
No name or email address in any header (research-agent rule, kept here).

## 3. Data shapes

`data/buoys.js`:
```
window.BUOYS = {updated, updated_t, stations: [
  {id: "46041", name: "Cape Elizabeth", lat, lon, src: "NDBC"|"CDIP"|"ECCC"|"NANOOS"|"BYB"|"COOPS", owner, link,
   t: <epoch s of the newest report>,
   hs_ft, dpd_s, apd_s, mwd_deg,            // significant wave height, dominant and average period, mean direction
   swh_ft, swp_s, swd_deg, wwh_ft, wwp_s, wwd_deg, steep,   // swell / wind-wave split (NDBC .spec, CDIP), else absent
   wspd_mph, gust_mph, wdir_deg, wtmp_f, atmp_f, pres_mb,
   trace: [24 values or null, hourly hs_ft ending at the newest full hour],   // from realtime2 history
   trace_t0: <epoch s of trace[0]>,
   credit: "Data courtesy of CDIP" | "Data Source: Environment and Climate Change Canada" | "Quileute Tribe / Quinault Indian Nation (Backyard Buoys, CC BY-NC 4.0)" | "NANOOS / UW Applied Physics Laboratory" | null
  }]}
```
Units are the site's: feet, mph, °F, mb; the modules convert from metres, m/s, °C. A station appears when it has at
least one of waves, wind or water temperature within the last 6 h; older reports are kept with `stale: true` for up
to 24 h so an outage shows as a hollow dot rather than a gap.

`data/tides.js`:
```
window.TIDES = {updated, updated_t, stations: [
  {id: "9441102", name: "Westport", lat, lon, src: "COOPS"|"CHS", kind: "harmonic"|"subordinate"|"obs",
   datum: "MLLW"|"CD", link,
   hilo: [[epoch s, ft, "H"|"L"], ...],       // predictions from 12 h ago to 36 h ahead (CO-OPS interval=hilo; CHS wlp-hilo)
   obs: [[epoch s, ft], ...] | null,            // last 12 h of observed water level, 30-min samples (live stations)
   wl_ft, wl_t, wtmp_f, wspd_mph, gust_mph, wdir_deg,   // latest observations where the station has the sensor
  }],
 currents: [
  {id: "PUG1701", name: "Deception Pass", lat, lon, src: "COOPS"|"CHS", bin_depth_ft, flood_dir, ebb_dir, link,
   events: [[epoch s, "slack"|"flood"|"ebb", kt], ...]   // today and tomorrow, MAX_SLACK (CO-OPS) or wcp1-events (CHS)
  }]}
```
The page interpolates between highs and lows with a cosine (`h(t) = (h1 + h2)/2 - (h1 - h2)/2 * cos(pi * (t - t1)/(t2 - t1))`),
the standard sketch of a mixed semidiurnal tide between extremes, and says "curve drawn between predicted highs and
lows" in the popup. The extremes are exact; the curve between them is a judgment call (decision 4).

`data/marine.js`:
```
window.MARINE = {updated, updated_t, zones: [
  {id: "PZZ150", name: "Coastal waters from Cape Flattery to James Island out 10 nm", cwa: "SEW", geometry: GeoJSON,
   periods: [{name: "Tonight", text: "...", wind_kt_max: 25, seas_ft_max: 8}, ... up to 6],
   issued: epoch s, link}],
 srf: {"PQR": {text, issued: epoch s, link}, ...}}
```
`wind_kt_max` and `seas_ft_max` are parsed from the period text ("W wind 15 to 25 kt", "Seas 6 to 8 ft") with a
regular expression; when the text does not match, they are null and the zone is drawn grey.

`data/sst.js`: `window.SST = {date: "2026-10-11", file: "frames/sst/sst.webp", max_f, min_f, legend: [{min, color}]}`;
`data/values/sst.js` is the click-anywhere grid in °F (`values.write_grid`, scale 0.1, nodata -1 over land and cloud).

## 4. The page (`map.html`)

New group after **Water**: `<div class="sec grp" data-grp="coastal">` titled **Coastal**, hidden when
`REG.coastal` is not true. Layers, each a `label.opt` checkbox with a `.subwrap`:
- **Buoys & shore stations** (`lyBuoys`): chips Waves / Wind / Water temp (`buoyMode`, saved explicitly like `stMode`).
  Marker: a circle coloured by the mode's value (wave height bins in feet: 0, 2, 4, 6, 8, 10, 13, 16, 20+ in the
  site's rain-style blue-to-purple ramp; wind: the station layer's wind bins and downwind arrow icon; water temp:
  cold-to-warm muted ramp 40-70 °F). Hollow grey dot for a station without the mode's value or stale beyond 6 h.
  Label from zoom 8: "6.2 ft 14 s" (waves), "18 g24" (wind), "52°" (temp), using the station layer's label code.
  Popup card: name, owner, report age; waves: Hs, dominant period, mean direction (as a compass point and degrees),
  swell and wind-wave rows when present, 24 h Hs trace (the rivers chart with hover); wind: speed, gust, direction;
  water and air temperature, pressure; credit line; link to the station page.
- **Tides & currents** (`lyTides`): tide stations as circles coloured by trend (rising: the site's blue, falling:
  the site's amber, slack within 20 min: grey), label from zoom 8 "↑ 6.3 ft"; current stations as small arrows
  pointing with the flow (flood or ebb direction) sized by speed, label "2.1 kt F". Popup: tide curve SVG (predicted
  line, observed overlay in blue where available, "now" line, next 4 extremes listed with times), stage sentence,
  water temperature and wind where the station has them, datum note, the CHS non-navigation notice for BC stations,
  link. Currents popup: events table for today and tomorrow, the state now (interpolated between events), depth of
  the bin, link.
- **Marine forecast** (`lyMarine`): zone polygons styled by `wind_kt_max` of the first period (under 15 grey-blue,
  15-24 blue, 25-33 amber (Small Craft), 34-47 red (Gale), 48+ purple), hover tooltip with the zone name and first
  period headline, popup with up to six periods and, for zones of an office with an SRF, a "Surf zone forecast"
  section with the product text (scrollable, 2,500 characters).
- **Sea surface temperature** (`lySst`): `L.imageOverlay` like SNODAS, legend, note with the analysis date and
  "NOAA Geo-Polar Blended 5 km; about two days behind; buoys show today's water".
Panel notes name the sources and credits: NOAA NDBC, CDIP ("Data courtesy of CDIP"), Environment and Climate Change
Canada, NANOOS / UW APL, Quileute Tribe and Quinault Indian Nation (Backyard Buoys, CC BY-NC 4.0), NOAA CO-OPS,
Canadian Hydrographic Service ("not for navigation"), NOAA NWS, NOAA CoastWatch.

Click-anywhere adds, inside the window and only for coastal regions: "Sea surface temp" (grid value when the SST
layer has data), "Nearest buoy" (within 60 km: Hs, period, wind, water temp), "Nearest tide station" (within 40 km:
stage sentence and next extreme). 60 and 40 km are judgment calls (decision 7).

Saved defaults: `lyBuoys`, `lyTides`, `lyMarine`, `lySst` join `DEF_CHECKS`; `buoyMode` is saved explicitly.
Helper blocks `// BEGIN coastalHelpers ... // END coastalHelpers` hold the pure functions (tide interpolation and
stage sentence, current state between events, wave and temperature bins, compass points, unit formatting) so
`tests/test_map_coastal.py` can run them under node like the other `test_map_*.py` files.

## 5. Sources and endpoints (detail in `coastal_research/`)

| Source | Endpoint | Notes |
|---|---|---|
| NDBC latest | `https://www.ndbc.noaa.gov/data/latest_obs/latest_obs.txt` | all stations, one file; filter by window; `MM` = missing |
| NDBC history | `https://www.ndbc.noaa.gov/data/realtime2/<id>.txt`, `.spec` | hourly rows (waves at :50), 45 days; take the last 25 h; `.spec` gives SwH/SwP/SwD/WWH/WWP/WWD/STEEPNESS; 404 for stations without one |
| NDBC station list | `https://www.ndbc.noaa.gov/data/stations/station_table.txt` | names, owners, positions; 31 disestablished ids are still listed: a station is shown only when it appears in `latest_obs` or `realtime2` |
| CDIP | `https://erddap.cdip.ucsd.edu/erddap/tabledap/wave_agg.csv?station_id,time,waveHs,waveTp,waveDp,waveTa&time>=now-2hours&station_id=~"(036\|162\|179\|248\|270\|139)"` | authoritative Dp; overwrite the NDBC relay rows (46211 Grays Harbor, 46243 Clatsop, 46248 Astoria Canyon, 46267 Angeles Point, 46278 Tillamook, 46229 Umpqua) |
| ECCC buoys | `https://dd.weather.gc.ca/today/observations/swob-ml/marine/moored-buoys/<YYYYMMDD>/<id>/` latest XML | ids 4600206 (La Perouse Bank), 4600146 (Halibut Bank), 4600304 (Neah Bay / Clallam); attribution line required |
| NANOOS ERDDAP | `https://erddap.nanoos.org/erddap/tabledap/<dataset>.json?...&time>=now-6hours` | `chaba_met_all`, `chaba_hydro`, `backyardbuoys_quileute_center` and the five other Spotters; ORCA / PISCES / Se'lhaem met buoys (wind) |
| CO-OPS metadata | `https://api.tidesandcurrents.noaa.gov/mdapi/prod/webapi/stations.json?type=waterlevels&expand=sensors`, `?type=tidepredictions`, `?type=currentpredictions` | filtered to the window; cached in `tides_cache.json` for 7 days |
| CO-OPS data | `https://api.tidesandcurrents.noaa.gov/api/prod/datagetter?product=<predictions\|water_level\|water_temperature\|wind\|currents_predictions>&station=<id>&datum=MLLW&units=english&time_zone=gmt&format=json&...` | `interval=hilo` for predictions (subordinate stations give nothing else), `interval=MAX_SLACK` for currents; `date=latest` for observations; `begin_date`/`range` for history |
| CHS IWLS | `https://api-iwls.dfo-mpo.gc.ca/api/v1/stations` (filter by window), `/stations/<id>/data?time-series-code=<wlo\|wlp-hilo\|wcp1-events>&from=..&to=..` | no key; metres and chart datum, converted to feet; the licence's "not for navigation" notice shown in the popup |
| NWS zones | `https://api.weather.gov/zones?type=coastal` (filter `cwa` in the region's offices), `/zones/forecast/<id>` (geometry), `/zones/forecast/<id>/forecast`, `/products/types/SRF/locations/<cwa>` then the latest product | region config `"marine_cwa": ["SEW", "PQR", "MFR", "EKA"]`; geometry cached in `zone_cache.json` under the zone's URL, as `alerts.py` does |
| SST | `https://coastwatch.noaa.gov/erddap/griddap/noaacwBLENDEDsstDaily.csv?analysed_sst[(last)][(41.0):(49.7)][(-126.6):(-112.5)]` (exact dataset id and the dimension order as the agent recorded; adjust to the server's `.das`) | daily, two days behind; land and cloud are NaN; rendered to a webp in the window's pixel space with a muted blue-to-red ramp |
| Alerts | `https://api.weather.gov/alerts/active?area=WA,OR,ID,MT,PZ&...` | features whose zone geometry falls entirely outside the region bbox are dropped (PZ covers the whole Pacific coast) |

## 6. Judgment calls (parameter ledger; none approved yet, Chris to confirm or change)

| # | Decision | Value | Why |
|---|---|---|---|
| 1 | Stale threshold for buoys and stations | hollow after 6 h, dropped after 24 h | buoys report hourly; a 6 h gap is an outage, not latency (NDBC's own pages grey a station after a few hours) |
| 2 | Wave height bins (ft) | 0, 2, 4, 6, 8, 10, 13, 16, 20 | surf-report conventions (knee, waist, head, overhead, double); colours from the site's rain ramp |
| 3 | Water temperature bins (°F) | 40, 45, 50, 55, 60, 65, 70 | wetsuit bands (5/4 hooded below 50, 4/3 to 58, 3/2 to 65) |
| 4 | Tide curve between extremes | cosine interpolation | exact at the predicted extremes; mixed tides deviate in between by inches, under the datum uncertainty of a subordinate station; labelled in the popup |
| 5 | "Slack" in the tide-station trend | within 20 min of an extreme | matches the roughly flat half hour around a turn |
| 6 | Marine zone colour | first period's max wind: <15, 15-24, 25-33, 34-47, 48+ kt | NWS advisory thresholds (Small Craft 25-33, Gale 34-47, Storm 48+) |
| 7 | Click-anywhere radii | nearest buoy 60 km, nearest tide station 40 km | buoys are offshore; a tide station more than 40 km away is a different water body |
| 8 | SST ramp | 40-70 °F, muted blue to red, 2 °F steps in the legend; nodata transparent | Chris's muted palette preference; the range covers PNW water year-round |
| 9 | Prediction horizon | 12 h back, 36 h ahead | the "deciding whether to go" window from the user walkthroughs |
| 10 | Prediction refresh | once a day per station, at most 60 stations per run | keeps the half-hour job short; predictions do not change |

## 7. Testing

- `tests/test_buoys.py`: parsers for `latest_obs.txt`, `realtime2` `.txt` and `.spec` (MM handling, unit
  conversion, the :50 wave rows), CDIP CSV, ECCC SWOB-ML XML, NANOOS ERDDAP JSON; merge rules (CDIP overwrites the
  relay; stale and drop thresholds); window filter; the output shape. Fixtures are short excerpts of the real files
  fetched 2026-10-13 (kept in `tests/fixtures/coastal/`).
- `tests/test_tides.py`: CO-OPS and CHS JSON parsing, datum and unit conversion, the hi/lo window, the daily refresh
  rule, the current events table, cache round-trip.
- `tests/test_marine.py`: zone filtering by `cwa`, period parsing (`wind_kt_max`, `seas_ft_max`) over a dozen real
  period texts, SRF selection.
- `tests/test_sst.py`: CSV grid to window-pixel raster, legend, nodata, °C to °F.
- `tests/test_map_coastal.py` (node): tide interpolation at the extremes and midpoint, stage sentence, current state
  between events, bins at every edge, compass points, the `coastal` flag hiding the group.
- `tests/test_map_defaults.py`: the new ids in `DEF_CHECKS`.
- Local check before deploy: `build_web.py`, serve `web/`, open in the in-app browser with live R2 data once the
  first runs land: markers, labels, popups, legends, no console errors; phone width.
- Independent check per headline number (verification protocol): Hs and period at 46041 against NDBC's station
  page; Westport's next high against CO-OPS's page; Deception Pass slack time against CO-OPS; Tofino's next high
  against the CHS page; the SST at a buoy against that buoy's water temperature. Logged in `coastal_research/CHECKS.md`.

## 8. Release

1. Push the modules, page and tests (tests green on Actions). The first half-hourly run writes `buoys.js` and
   `tides.js`; the first hourly run writes `marine.js` and `sst.js`.
2. `python build_web.py`, Chris runs `npx --yes wrangler deploy`; check the live page against `web/index.html`.
3. Handoff in `coastal_research/HANDOFF.md`; CLAUDE.md gets a "Coastal" rules paragraph and a timeline line.
