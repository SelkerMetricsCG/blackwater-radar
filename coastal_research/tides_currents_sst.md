# Coastal section: tides, currents, water temperature, ocean state, hazards

Research notes for radar.blackwaterlabs.org, window lat 41.0–49.7 N, lon -126.6 to -112.5. Written 2026-10-13 from
live fetches (generic `coastal-research/0.1` User-Agent, 20 s timeout, a handful of requests per host) plus page reads.
Every "fetched" claim below names the date, HTTP status and a sample. Other agents cover NANOOS/IOOS (HF radar),
NDBC/CDIP buoys, wind forecasts and webcams; they are referenced, not catalogued, here.

## Summary

- **NOAA CO-OPS** is the backbone: 24 real-time water-level stations in the window (15 with water temperature, 12 with
  wind), 230 tide-prediction stations (86 harmonic, 144 subordinate hi/lo-only), 220 tidal-current prediction stations
  (every passage asked about is present). Public domain, no key, no published numeric rate limit; CO-OPS throttles
  heavy clients and asks for sleeps between calls.
- **Real-time current meters: none usable today.** The only in-window PORTS current meters are Cherry Point (cp0101)
  and two new "CURBY" meters in Yaquina Bay (qr0401/qr0501, deployed April 2025); all three returned "No data was found"
  for latest/recent/explicit bins. The Columbia River PORTS has water-level gauges only, no current meter.
- **CHS IWLS** (Canada) works without a key and covers 124 stations in the window (27 operating, including Tofino,
  Ucluelet, Bamfield, Port Renfrew, Victoria, Point Atkinson, Vancouver) plus current predictions at Race Passage,
  Active Pass, Porlier, Dodd Narrows, First and Second Narrows. Its licence is the catch: "not to be used for
  navigation" and no commercial derivative products. A free public site needs a judgment call (open question 1).
- **SST:** NOAA Geo-Polar Blended 5 km daily (coastwatch.noaa.gov ERDDAP) is the reliable gap-free layer and already
  renders a window PNG in one request; MUR 1 km is better near breaks but the West Coast ERDDAP node was down today
  (502/503/timeouts), the UAF mirror `upwell.pfeg.noaa.gov` served it at ~20 s per request. GOES-West hourly 2 km is
  cloud-gapped. "Normal for this date" is easiest from Coral Reef Watch's 5 km anomaly or PSL's OISST 1991–2020 daily
  climatology over OPeNDAP.
- **Circulation:** NOAA has two operational OFS in the window: **WCOFS** (shelf, ROMS, 2-D surface files on AWS, small)
  and **SSCOFS** (Salish Sea + Columbia, FVCOM 100 m–10 km, 4 cycles/day, hourly 3-D files, heavy). RTOFS/HYCOM are
  8 km and only worth it as a fallback. OSCAR needs an Earthdata login (excluded). LiveOcean is "research use only" with
  no published forecast file endpoint; link out.
- **Columbia and Grays Harbor bars:** NWS writes a bar forecast with ebb timings into the CWF text (zone PZZ210
  Columbia River Bar, PZZ110 Grays Harbor Bar), fetchable from api.weather.gov. USCG restrictions have no public feed
  (phone recordings; the USCG D13 site returns 403 to a generic client).
- **Hazards:** NWS Surf Zone Forecast exists only for PQR (Long Beach WA to Lincoln City), MFR and EKA on this coast,
  not SEW; Beach Hazards Statements (sneaker waves live here), High Surf and Rip Current Statements come from the
  alerts API with a comma-separated `event=` filter; NTWC Atom and CAP feeds are live. Shellfish biotoxin closures are
  machine-readable for both states (WA DOH ArcGIS, ODA ArcGIS "Zone Status"); razor clams are closed on the whole
  Oregon coast and WA digs are postponed for domoic acid as of this week. Swimming-beach bacteria advisories: WA has a
  query-able layer (off-season now), OR is an HTML table with the season ended.

## 1. NOAA CO-OPS (tidesandcurrents.noaa.gov)

### 1.1 APIs, formats, terms

| Item | Detail |
|---|---|
| Metadata API | `https://api.tidesandcurrents.noaa.gov/mdapi/prod/webapi/stations.json?type=waterlevels\|tidepredictions\|currentpredictions\|currents&units=metric[&expand=sensors]`; per-station `stations/{id}/products.json`, `bins.json`, `sensors.json`, `tidepredoffsets.json`, `currentpredictionoffsets.json`, `harcon.json`. Fetched 2026-10-13, all 200: waterlevels count 302 (0.8 MB), tidepredictions 3502 (2.0 MB, 21 s), currentpredictions 4439 rows (3.8 MB), currents 87 (0.1 MB), waterlevels+sensors 1.2 MB. |
| Data API | `https://api.tidesandcurrents.noaa.gov/api/prod/datagetter?station=ID&product=P&date=latest\|today\|recent&begin_date=yyyymmdd&end_date=yyyymmdd&datum=MLLW&units=metric&time_zone=gmt\|lst\|lst_ldt&interval=hilo\|h\|6&bin=N&format=json\|csv\|xml`. Products: `water_level`, `hourly_height`, `high_low`, `predictions`, `air_temperature`, `water_temperature`, `wind`, `air_pressure`, `conductivity`, `salinity`, `currents`, `currents_predictions`, `currents_header`, `ofs_water_level`, `one_minute_water_level`, daily/monthly means. |
| Datums | `MLLW` is what every US tide table and the NWS surf forecast uses; `MSL`, `MHHW`, `NAVD`, `STND` also accepted. Subordinate (type S) prediction stations only answer `datum=MLLW` with `interval=hilo`. Use `units=metric` + `time_zone=gmt` for storage; `lst_ldt` gives local clock time with DST for display. |
| Fetched samples (2026-10-13, all HTTP 200) | Westport 9441102 `water_temperature&date=latest`: `{"t":"2026-10-13 19:36","v":"11.7"}` (°C). Seattle 9447130 `water_level&date=latest`: `v 2.06 m MLLW, s 0.007, q "p"` (preliminary). Astoria 9439040 `predictions&interval=hilo&date=today`: H 03:54 2.22 m, L 09:23 0.689, H 15:11 2.654, L 22:11 -0.16. Westport 6-min predictions (no `interval`): 240 rows, 9 KB. Bellingham 9449211 (subordinate) without `interval`: error "No Predictions data was found"; with `interval=hilo`: 4 rows OK. Deception Pass PUG1701 `currents_predictions&bin=33&interval=MAX_SLACK`: `units "meters, cm/s"`, meanFloodDir 108, meanEbbDir 277, flood 03:48 `Velocity_Major 24x` cm/s. Grays Harbor entrance PCT1291 MAX_SLACK: flood 00:45 115.1 cm/s (2.2 kt), slack 03:45. Astoria `conductivity`: "No data was found". cp0101/qr0401/qr0501 `currents` (latest, recent, bin=20, 2-day range): "No data was found. This product may not be offered at this station at the requested time." |
| Cadence/latency | Observations every 6 min, visible within a few minutes (Seattle 19:36 Z value fetched at ~19:45 Z). Predictions are static harmonic output (compute once per day or per week). |
| Limits (quoted from `https://api.tidesandcurrents.noaa.gov/api/prod/`) | "To prevent numerous large data requests slowing data access through the internet services; all internet data services have limits on the amount/length of data which can be retrieved per request." 6-minute data "Data length is limited to 1 month"; hourly and high/low 1 year; hi/lo tide predictions 10 years, other prediction intervals 1 year; `max_slack` current predictions 1 year, other current-prediction intervals 1 month; `bin=0` (all bins) 7 days. Throttling: "CO-OPS protects its APIs and systems when encountering heavy load … by limiting (throttling) the quantity / volume of data queries received from a singular customer." The page recommends "sleep statements" between calls and to "only download the data you need." No numeric requests-per-second figure is published anywhere official (checked docs and a web search). |
| Terms (quoted from `https://tidesandcurrents.noaa.gov/disclaimers.html`) | "The information on government servers are in the public domain, unless specifically annotated otherwise" and "may be used freely"; "NOS requests that attribution be given whenever NOS material is reproduced and re-disseminated"; "This information shall not be modified in content and then presented as official government material"; data are provided "as is", "The user assumes the entire risk related to its use of these data." Raw observations are "released for limited public use as preliminary data to be used only with appropriate caution." |
| Caveats | Metadata `type=tidepredictions` list is 2 MB and slow (21 s); cache it in the repo rather than re-fetching. Station names in that list are mixed case/upper case; `state` is blank for `TWC####` ids (Canadian-side subordinate entries). `currents` metadata `deployed`/`retrieved` fields tell you if a meter is in the water, but today's meters still returned no data. Metric current speeds come back in cm/s (divide by 51.44 for knots). |

### 1.2 Real-time water-level stations in the window (24, from `type=waterlevels&expand=sensors`)

Affiliations: NWLON = long-term network; PORTS = Physical Oceanographic Real-Time System; `cr` = Columbia River PORTS,
`ks` = Kitsap, `ta` = Tacoma, `cp` = Cherry Point. Sensors column is from the metadata; "WT" water temperature,
"AT" air temperature, "W" wind, "BP" barometric pressure. No station in the window reports conductivity/salinity.

| id | name | state | lat | lon | affiliation | PORTS | sensors |
|---|---|---|---|---|---|---|---|
| 9449424 | Cherry Point | WA | 48.8627 | -122.7586 | NWLORTS | cp | Pressure WL, BP |
| 9449880 | Friday Harbor | WA | 48.5453 | -123.0125 | NWLON |  | Microwave WL, AT, BP, WT, W |
| 9443090 | Neah Bay | WA | 48.3707 | -124.6016 | NWLON |  | Microwave WL, BP, WT |
| 9444090 | Port Angeles | WA | 48.1250 | -123.4400 | NWLON |  | Microwave WL, AT, BP, WT, W |
| 9444900 | Port Townsend | WA | 48.1112 | -122.7597 | NWLON |  | Microwave WL, AT, BP, WT, W |
| 9442396 | La Push, Quillayute River | WA | 47.9128 | -124.6357 | NWLON |  | Microwave WL, AT, BP, WT, W |
| 9447130 | Seattle | WA | 47.6026 | -122.3393 | NWLON |  | Microwave WL, BP |
| 9445958 | Bremerton | WA | 47.5617 | -122.6230 | PORTS | ks | Microwave WL, AT, BP, W |
| 9446484 | Tacoma | WA | 47.2667 | -122.4133 | PORTS,Global | ta | Microwave WL, BP, WT |
| 9441102 | Westport | WA | 46.9043 | -124.1051 | NWLON |  | Acoustic WL, AT, BP, WT, W |
| 9440910 | Toke Point | WA | 46.7075 | -123.9669 | NWLON |  | Microwave WL, AT, BP, WT, W |
| 9440581 | Cape Disappointment | WA | 46.2810 | -124.0463 | PORTS | cr | Microwave WL |
| 9440569 | Skamokawa | WA | 46.2703 | -123.4565 | PORTS | cr | Pressure WL |
| 9439040 | Astoria | OR | 46.2073 | -123.7683 | NWLORTS | cr | Microwave WL, AT, WT, W |
| 9439099 | Wauna | OR | 46.1600 | -123.4050 | PORTS | cr | Microwave WL |
| 9440422 | Longview | WA | 46.1061 | -122.9542 | NWLON,NWLORTS,PORTS | cr | Microwave WL, BP, WT |
| 9440357 | TEMCO Kalama Terminal | WA | 45.9867 | -122.8367 | PORTS | cr | Microwave WL, BP |
| 9439201 | St Helens | OR | 45.8650 | -122.7970 | PORTS | cr | Pressure WL |
| 9440083 | Vancouver | WA | 45.6312 | -122.6958 | PORTS | cr | Pressure WL |
| 9437540 | Garibaldi | OR | 45.5545 | -123.9189 | NWLON |  | Microwave WL |
| 9435380 | South Beach | OR | 44.6254 | -124.0449 | NWLON |  | Microwave WL, AT, BP, WT, W |
| 9432780 | Charleston | OR | 43.3450 | -124.3220 | NWLON |  | Acoustic WL, BP, WT, W |
| 9431647 | Port Orford | OR | 42.7390 | -124.4983 | NWLON |  | Microwave WL, AT, BP, WT, W |
| 9419750 | Crescent City | CA | 41.7456 | -124.1844 | NWLON |  | Microwave WL, AT, BP, WT, W |

Water temperature (15): Crescent City, Port Orford, Charleston, South Beach, Astoria, Longview, Toke Point, Westport,
La Push, Neah Bay, Port Angeles, Port Townsend, Tacoma, Friday Harbor, and none of Garibaldi, Wauna, St Helens,
Vancouver, Kalama, Skamokawa, Cape Disappointment, Bremerton, Seattle, Cherry Point.
Wind (12): Crescent City, Port Orford, Charleston, South Beach, Astoria, Toke Point, Westport, La Push, Port Angeles,
Port Townsend, Bremerton, Friday Harbor. Air temperature: the same minus Charleston.

### 1.3 Real-time current meters (PORTS) in the window

| id | name | project | lat | lon | deployed | API result today |
|---|---|---|---|---|---|---|
| cp0101 | Cherry Point | Cherry Point PORTS | 48.8628 | -122.7610 | 2023-11-17 | 30 bins × 4 m, `real_time_bin` 20; `currents` latest/recent/bin=20: no data |
| qr0401 | CURBY 4 | CURBY PORTS (Yaquina Bay, Newport OR) | 44.6258 | -124.0554 | 2025-04-24 | 9 bins × 2 m, real_time_bin 1; no data |
| qr0501 | CURBY 5 | CURBY PORTS | 44.6224 | -124.0336 | 2025-04-18 | no data |

The 87-station national `type=currents` list has no Columbia River, Grays Harbor, Admiralty Inlet, Tacoma Narrows or
Rich Passage meter. The Columbia River PORTS (`portscode cr`) consists of nine water-level gauges (Cape Disappointment,
Skamokawa, Astoria, Wauna, Longview, Kalama, St Helens, Vancouver; Astoria also wind/air temp). `ks0101` "Rich
Passage, LB 8" survives only as a harmonic prediction station (3 bins).

### 1.4 Tide-prediction stations in the window (230: 86 harmonic "R", 144 subordinate "S")

Type R stations give 6-minute and hi/lo predictions; type S only hi/lo, derived from the `reference` station via
`tidepredoffsets.json`. Ids `TWC####` are subordinate entries on the Canadian side of the line (Peavine Pass,
Point Migley, Ferndale) with no state code. Sorted north to south.

| id | name | state | lat | lon | type | reference |
|---|---|---|---|---|---|---|
| 9449679 | Blaine, Semiahmoo Bay | WA | 48.9917 | -122.7650 | R |  |
| 9449639 | Point Roberts, Puget Sound | WA | 48.9750 | -123.0830 | R |  |
| 9449424 | Cherry Point | WA | 48.8627 | -122.7586 | R |  |
| TWC1189 | Ferndale |  | 48.8333 | -122.7167 | S | 9444900 |
| 9449292 | Sandy Point, Lummi Bay | WA | 48.7900 | -122.7080 | S | 9444900 |
| 9449704 | Patos Island Wharf | WA | 48.7867 | -122.9700 | S | 9444900 |
| 9449712 | Echo Bay, Sucia Islands | WA | 48.7567 | -122.8970 | S | 9444900 |
| TWC1173 | Point Migley |  | 48.7500 | -122.7167 | S | 9444900 |
| 9449211 | Bellingham | WA | 48.7450 | -122.4950 | S | 9444900 |
| 9449184 | Gooseberry Point | WA | 48.7300 | -122.6700 | S | 9444900 |
| 9449161 | Village Point, Lummi Island | WA | 48.7167 | -122.7080 | R |  |
| 9449746 | Waldron Island, Puget Sound | WA | 48.6868 | -123.0376 | R |  |
| 9449771 | Rosario, East Sound, Orcas Island | WA | 48.6467 | -122.8700 | R |  |
| 9449834 | Roche Harbor, San Juan Island | WA | 48.6100 | -123.1550 | S | 9444900 |
| 9449798 | Orcas, Orcas Island | WA | 48.6000 | -122.9500 | S | 9444900 |
| TWC1165 | Peavine Pass |  | 48.6000 | -122.8000 | S | 9444900 |
| 9448918 | Tide Point, Cypress Island | WA | 48.5867 | -122.7480 | S | 9444900 |
| 9449904 | Shaw Island, Ferry Terminal, Harney Channel | WA | 48.5850 | -122.9280 | S | 9444900 |
| 9449828 | Hanbury Point, Mosquito Pass, San Juan I. | WA | 48.5817 | -123.1700 | R |  |
| 9449911 | Upright Head, Lopez Island | WA | 48.5717 | -122.8850 | R |  |
| 9448876 | Strawberry Bay, Cypress Island | WA | 48.5650 | -122.7220 | S | 9444900 |
| 9449880 | Friday Harbor, San Juan Island | WA | 48.5453 | -123.0125 | R |  |
| 9449932 | Armitage Island, Thatcher Pass | WA | 48.5350 | -122.7970 | R |  |
| 9448794 | Anacortes, Guemes Channel | WA | 48.5183 | -122.6200 | S | 9444900 |
| 9448772 | Ship Harbor, Fidalgo Island | WA | 48.5067 | -122.6770 | S | 9444900 |
| 9449856 | Kanaka Bay, San Juan Island | WA | 48.4850 | -123.0830 | R |  |
| 9448683 | Burrows Bay (Allan Island) | WA | 48.4600 | -122.6950 | S | 9444900 |
| 9448682 | Swinomish Channel Ent., Padilla Bay | WA | 48.4583 | -122.5130 | R |  |
| 9449982 | Richardson, Lopez Island | WA | 48.4467 | -122.9000 | R |  |
| 9448657 | Turner Bay, Similk Bay | WA | 48.4450 | -122.5550 | R |  |
| 9449988 | Telegraph Bay, Puget Sound | WA | 48.4433 | -122.8050 | R |  |
| 9449994 | Aleck Bay, Lopez Island | WA | 48.4250 | -122.8530 | S | 9444900 |
| 9448614 | Deception Pass St. Park, Bowman Bay, Fidalgo I. | WA | 48.4150 | -122.6520 | R |  |
| 9448601 | Yokeko Point, Deception Pass | WA | 48.4133 | -122.6150 | S | 9447130 |
| 9447995 | Cornet Bay, Whidbey Island, Deception Pass | WA | 48.4017 | -122.6230 | S | 9447130 |
| 9448576 | Sneeoosh Point | WA | 48.4000 | -122.5480 | R |  |
| 9447993 | Ala Spit, Whidbey Island | WA | 48.3967 | -122.5870 | S | 9447130 |
| 9442971 | Tatoosh Island, Cape Flattery | WA | 48.3917 | -124.7370 | S | 9443090 |
| 9448558 | La Conner, Swinomish Channel | WA | 48.3917 | -122.4970 | S | 9447130 |
| 9443090 | Neah Bay | WA | 48.3707 | -124.6016 | R |  |
| 9447973 | Nas Whidbey Island | WA | 48.3428 | -122.6858 | R |  |
| 9447985 | Smith Island | WA | 48.3167 | -122.8370 | S | 9444900 |
| 9442861 | Makah Bay | WA | 48.2967 | -124.6720 | S | 9440910 |
| 9447952 | Crescent Harbor, N. Whidbey Island | WA | 48.2867 | -122.6170 | S | 9447130 |
| 9447951 | Sunset Beach, Whidbey Island | WA | 48.2833 | -122.7280 | S | 9444900 |
| 9443361 | Sekiu, Clallam Bay | WA | 48.2633 | -124.2970 | R |  |
| 9447934 | Point Partridge, Whidbey Island | WA | 48.2317 | -122.7650 | S | 9444900 |
| 9447929 | Coupeville, Penn Cove, Whidbey Island | WA | 48.2233 | -122.6900 | S | 9447130 |
| TWC1131 | Stanwood, Stillaguamish River |  | 48.2167 | -122.3667 | S | 9447130 |
| 9443551 | Jim Creek | WA | 48.1872 | -124.0625 | R |  |
| 9443644 | Twin Rivers | WA | 48.1750 | -123.9500 | S | 9443090 |
| 9442705 | Tskawahyah Island, Cape Alava | WA | 48.1711 | -124.7369 | R |  |
| 9444471 | Dungeness | WA | 48.1667 | -123.1170 | S | 9444900 |
| 9443826 | Crescent Bay | WA | 48.1617 | -123.7250 | S | 9444900 |
| 9447905 | Admiralty Head | WA | 48.1583 | -122.6680 | S | 9444900 |
| 9444122 | Ediz Hook, Port Angeles | WA | 48.1400 | -123.4130 | S | 9444900 |
| 9448094 | Kayak Point | WA | 48.1367 | -122.3670 | S | 9447130 |
| 9444090 | Port Angeles | WA | 48.1250 | -123.4400 | R |  |
| 9444900 | Port Townsend | WA | 48.1112 | -122.7597 | R |  |
| 9448043 | Tulare Beach, Port Susan | WA | 48.1068 | -122.3473 | R |  |
| 9447883 | Greenbank, Whidbey Island | WA | 48.1050 | -122.5700 | R |  |
| 9444972 | Marrowstone Point | WA | 48.0917 | -122.6900 | S | 9444900 |
| 9448009 | Spee-Bi-Dah | WA | 48.0883 | -122.3223 | R |  |
| 9444555 | Sequim Bay Entrance | WA | 48.0817 | -123.0430 | S | 9444900 |
| 9447773 | Tulalip | WA | 48.0650 | -122.2880 | R |  |
| 9444705 | Gardiner, Discovery Bay | WA | 48.0583 | -122.9170 | S | 9444900 |
| 9444971 | Mystery Bay, Marrowstone Island | WA | 48.0583 | -122.6920 | S | 9444900 |
| TWC1125 | Marysville, Quilceda Creek |  | 48.0450 | -122.2117 | S | 9447130 |
| 9447856 | Sandy Point, Whidbey Island | WA | 48.0350 | -122.3770 | S | 9447130 |
| 9447717 | Priest Point | WA | 48.0349 | -122.2272 | R |  |
| 9447854 | Bush Point, Whidbey Island | WA | 48.0333 | -122.6070 | S | 9444900 |
| 9447855 | Holly Farms Harbor, Holmes Harbor, Whidbey I. | WA | 48.0267 | -122.5350 | S | 9447130 |
| 9447659 | Everett | WA | 47.9800 | -122.2230 | R |  |
| 9447814 | Glendale, Whidbey Island | WA | 47.9400 | -122.3570 | S | 9447130 |
| 9445016 | Foulweather Bluff | WA | 47.9267 | -122.6170 | R |  |
| 9445017 | Port Ludlow | WA | 47.9250 | -122.6800 | S | 9447130 |
| 9445526 | Hansville | WA | 47.9183 | -122.5450 | S | 9447130 |
| 9442396 | La Push, Quillayute River | WA | 47.9128 | -124.6357 | R |  |
| 9442388 | James Island | WA | 47.9067 | -124.6470 | S | 9440910 |
| 9445059 | Port Gamble | WA | 47.8583 | -122.5800 | S | 9447130 |
| 9445088 | Lofall | WA | 47.8150 | -122.6570 | S | 9447130 |
| 9447427 | Edmonds | WA | 47.8133 | -122.3830 | S | 9447130 |
| 9445272 | Quilcene, Quilcene Bay, Dabob Bay | WA | 47.8000 | -122.8580 | R |  |
| 9445639 | Kingston, Appletree Cove | WA | 47.7967 | -122.4930 | S | 9447130 |
| 9445246 | Whitney Point, Dabob Bay | WA | 47.7617 | -122.8500 | S | 9447130 |
| 9445133 | Bangor Wharf | WA | 47.7483 | -122.7270 | R |  |
| 9445683 | Port Jefferson | WA | 47.7467 | -122.4770 | S | 9447130 |
| 9445719 | Poulsbo, Liberty Bay | WA | 47.7250 | -122.6380 | S | 9447130 |
| 9445269 | Zelatched Point, Dabob Bay | WA | 47.7117 | -122.8220 | S | 9447130 |
| 9445753 | Port Madison | WA | 47.7050 | -122.5250 | S | 9447130 |
| 9447265 | Meadow Point, Shilshole Bay | WA | 47.6883 | -122.4030 | S | 9447130 |
| TWC0965 | Destruction Island |  | 47.6667 | -124.4833 | S | 9440910 |
| 9445293 | Pleasant Harbor | WA | 47.6650 | -122.9120 | S | 9447130 |
| 9445832 | Brownsville, Port Orchard | WA | 47.6517 | -122.6150 | S | 9447130 |
| 9445303 | Seabeck, Seabeck Bay | WA | 47.6417 | -122.8280 | S | 9447130 |
| 9445882 | Eagle Harbor, Bainbridge Island | WA | 47.6200 | -122.5150 | S | 9447130 |
| 9445901 | Tracyton, Dyes Inlet | WA | 47.6100 | -122.6600 | S | 9447130 |
| 9445326 | Triton Head | WA | 47.6033 | -122.9820 | S | 9447130 |
| 9447130 | Seattle (Madison St.), Elliott Bay | WA | 47.6026 | -122.3393 | R |  |
| 9445913 | Port Blakely | WA | 47.5967 | -122.5100 | S | 9447130 |
| 9447110 | Lockheed Shipyard, Harbor Island | WA | 47.5850 | -122.3620 | S | 9447130 |
| 9445938 | Clam Bay, Rich Passage | WA | 47.5733 | -122.5430 | S | 9447130 |
| 9445958 | Bremerton, Sinclair Inlet, Port Orchard | WA | 47.5617 | -122.6230 | R |  |
| 9447029 | Duwamish Waterway, Eighth Ave. South | WA | 47.5350 | -122.3220 | S | 9447130 |
| 9445993 | Harper, Yukon Harbor | WA | 47.5233 | -122.5170 | S | 9447130 |
| 9446025 | Point Vashon, Vashon Island | WA | 47.5117 | -122.4630 | S | 9447130 |
| 9445388 | Ayock Point | WA | 47.5083 | -123.0520 | S | 9447130 |
| 9445441 | Lynch Cove Dock | WA | 47.4183 | -122.9000 | S | 9447130 |
| 9446248 | Des Moines, East Passage | WA | 47.4000 | -122.3280 | S | 9447130 |
| 9446254 | Burton, Quartermaster Hbr. (Inside), Vashon I. | WA | 47.3950 | -122.4630 | S | 9447130 |
| 9446281 | Allyn, Case Inlet | WA | 47.3833 | -122.8230 | S | 9447130 |
| 9446291 | Wauna, Carr Inlet | WA | 47.3783 | -122.6340 | R |  |
| 9445478 | Union | WA | 47.3583 | -123.0980 | R |  |
| 9446366 | Vaughn, Case Inlet | WA | 47.3417 | -122.7750 | S | 9447130 |
| 9446369 | Gig Harbor | WA | 47.3400 | -122.5880 | S | 9447130 |
| 9446375 | Tahlequah, Neil Pt., Dalco Passage, Vashon I. | WA | 47.3333 | -122.5070 | S | 9447130 |
| 9441627 | Point Grenville | WA | 47.3033 | -124.2700 | S | 9440910 |
| 9446451 | Horsehead Bay, Carr Inlet | WA | 47.3017 | -122.6820 | S | 9447130 |
| 9446489 | Walkers Landing, Pickering Passage | WA | 47.2817 | -122.9230 | S | 9447130 |
| 9446491 | Arletta, Hale Passage | WA | 47.2800 | -122.6520 | S | 9447130 |
| 9446500 | Home, Von Geldern Cove, Carr Inlet | WA | 47.2750 | -122.7580 | S | 9447130 |
| 9446486 | Tacoma Narrows Bridge | WA | 47.2717 | -122.5520 | S | 9447130 |
| 9446484 | Tacoma, Commencement Bay, Sitcum Waterway | WA | 47.2667 | -122.4133 | R |  |
| 9446583 | Mcmicken Island, Case Inlet | WA | 47.2467 | -122.8620 | S | 9447130 |
| 9446628 | Shelton, Oakland Bay | WA | 47.2150 | -123.0830 | S | 9447130 |
| 9446638 | Longbranch, Filucy Bay | WA | 47.2100 | -122.7530 | S | 9447130 |
| 9446666 | Arcadia, Totten Inlet | WA | 47.1967 | -122.9380 | S | 9447130 |
| 9446705 | Yoman Point, Anderson Island, Balch Passage | WA | 47.1800 | -122.6750 | R |  |
| 9446714 | Steilacoom, Cormorant Passage | WA | 47.1733 | -122.6030 | S | 9447130 |
| 9446671 | Devils Head, Drayton Passage | WA | 47.1667 | -122.7630 | S | 9447130 |
| 9446742 | Barron Point, Little Skookum Inlet Entrance | WA | 47.1567 | -123.0080 | S | 9447130 |
| 9446752 | Henderson Inlet | WA | 47.1550 | -122.8380 | S | 9447130 |
| 9446804 | Sandy Point Anderson Island, Puget Sound | WA | 47.1530 | -122.6751 | R |  |
| 9446800 | Dofflemeyer Point, Boston Hbr., Budd Inlet | WA | 47.1417 | -122.9030 | S | 9447130 |
| 9446828 | Dupont Wharf, Nisqually Reach | WA | 47.1183 | -122.6650 | S | 9447130 |
| 9446807 | Budd Inlet, Olympia Shoal | WA | 47.0983 | -122.8950 | R |  |
| TWC1115 | Rocky Point, Eld Inlet |  | 47.0817 | -123.0050 | S | 9447130 |
| 9446969 | Olympia, Budd Inlet | WA | 47.0600 | -122.9030 | S | 9447130 |
| TWC0959 | Montesano, Chehalis River |  | 46.9683 | -123.6000 | S | 9440910 |
| 9441187 | Aberdeen | WA | 46.9683 | -123.8530 | R |  |
| 9441158 | Cosmopolis, Chehalis River | WA | 46.9667 | -123.7780 | S | 9440910 |
| 9441156 | Point Brown | WA | 46.9500 | -124.1280 | S | 9440910 |
| 9441098 | Markham | WA | 46.9067 | -123.9980 | S | 9440910 |
| 9441102 | Westport, Point Chehalis | WA | 46.9043 | -124.1051 | R |  |
| 9441038 | Bay City, South Bay | WA | 46.8617 | -124.0600 | S | 9440910 |
| 9440910 | Toke Point | WA | 46.7075 | -123.9669 | R |  |
| TWC0940 | Mailboat Slough, Willapa River |  | 46.6883 | -123.8167 | S | 9440910 |
| 9440886 | Raymond, Willapa River | WA | 46.6833 | -123.7550 | S | 9440910 |
| 9440875 | South Bend, Willapa River | WA | 46.6633 | -123.7980 | R |  |
| 9440846 | Bay Center, Palix River | WA | 46.6233 | -123.9450 | S | 9440910 |
| 9440813 | Palix River, South Fork | WA | 46.5867 | -123.9100 | S | 9440910 |
| 9440747 | Nahcotta | WA | 46.5017 | -124.0230 | S | 9440910 |
| 9440723 | Paradise Point, Long Island | WA | 46.4683 | -123.9450 | S | 9440910 |
| 9440691 | Naselle River, Swing Bridge | WA | 46.4300 | -123.9030 | S | 9440910 |
| 9440662 | Naselle River, 4 Miles Above Swing Bridge | WA | 46.3883 | -123.8400 | S | 9440910 |
| 9440650 | Greenhead Slough | WA | 46.3722 | -123.9503 | R |  |
| TWC0933 | Tarlatt Slough |  | 46.3700 | -124.0050 | S | 9440910 |
| 9440597 | Ilwaco, Baker Bay, Wash. | WA | 46.3033 | -124.0400 | S | 9439040 |
| 9440581 | Cape Disappointment | WA | 46.2810 | -124.0463 | R |  |
| 9440574 | Columbia River Entrance (N. Jetty) | WA | 46.2733 | -124.0720 | S | 9439040 |
| 9440573 | Chinook, Baker Bay, Wash. | WA | 46.2717 | -123.9480 | S | 9439040 |
| 9440569 | Skamokawa | WA | 46.2703 | -123.4565 | R |  |
| 9440572 | Fort Canby, Jetty 'A', Wash. | WA | 46.2683 | -124.0370 | R |  |
| TWC0895 | Harrington Point, Wash. |  | 46.2667 | -123.6500 | S | 9439040 |
| 9440563 | Hungry Harbor, Wash. | WA | 46.2583 | -123.8480 | S | 9439040 |
| 9439040 | Astoria (Tongue Point), Oreg. | OR | 46.2073 | -123.7683 | R |  |
| 9439011 | Hammond, Oregon | OR | 46.2017 | -123.9450 | R |  |
| TWC0881 | Point Adams, Oreg. |  | 46.2000 | -123.9500 | S | 9439040 |
| 9439023 | Astoria (Port Docks), Oreg. | OR | 46.1867 | -123.8600 | S | 9439040 |
| 9439069 | Knappa, Knappa Slough | OR | 46.1867 | -123.5880 | S | 9439040 |
| 9439054 | Settlers Point, Oreg. | OR | 46.1750 | -123.6780 | S | 9439040 |
| 9439026 | Astoria (Youngs Bay), Oreg. | OR | 46.1717 | -123.8420 | S | 9439040 |
| TWC0883 | Warrenton, Skipanon River, Oreg. |  | 46.1667 | -123.9167 | S | 9439040 |
| 9439099 | Wauna | OR | 46.1600 | -123.4050 | R |  |
| 9440483 | Barlow Point | WA | 46.1522 | -123.0392 | R |  |
| 9440482 | Cape Horn | WA | 46.1517 | -123.2900 | R |  |
| 9438772 | Cathcart Landing, Youngs River | OR | 46.1243 | -123.8043 | R |  |
| 9440422 | Longview | WA | 46.1061 | -122.9542 | R |  |
| 9440357 | Temco Kalama Terminal | WA | 45.9867 | -122.8367 | R |  |
| 9439201 | Saint Helens | OR | 45.8650 | -122.7970 | R |  |
| 9438125 | Multnomah Channel | OR | 45.8117 | -122.8270 | R |  |
| 9440171 | Knapp Landing, Willow Bar | WA | 45.7417 | -122.7550 | R |  |
| 9437954 | North Fork, Nehalem River | OR | 45.7338 | -123.8764 | R |  |
| 9437908 | Nehalem | OR | 45.7100 | -123.8900 | S | 9419750 |
| 9439189 | Rocky Point | OR | 45.6967 | -122.8680 | R |  |
| 9437815 | Brighton | OR | 45.6700 | -123.9250 | S | 9419750 |
| 9440083 | Vancouver | WA | 45.6312 | -122.6958 | R |  |
| 9440079 | Beacon Rock State Park | WA | 45.6203 | -122.0203 | R |  |
| 9440047 | Washougal | WA | 45.5783 | -122.3820 | R |  |
| 9437585 | North Jetty, Tillamook Bay | OR | 45.5700 | -123.9650 | R |  |
| 9437581 | Barview | OR | 45.5683 | -123.9430 | S | 9419750 |
| 9437540 | Garibaldi | OR | 45.5545 | -123.9189 | R |  |
| TWC0863 | Miami Cove |  | 45.5500 | -123.9000 | S | 9419750 |
| TWC0865 | Bay City |  | 45.5167 | -123.9000 | S | 9419750 |
| 9439221 | Portland Morrison Street Bridge | OR | 45.5100 | -122.6730 | R |  |
| 9437381 | Dick Point | OR | 45.4817 | -123.9020 | R |  |
| 9437331 | Tillamook, Hoquarten Slough | OR | 45.4600 | -123.8450 | S | 9419750 |
| 9437262 | Netarts, Netarts Bay | OR | 45.4300 | -123.9450 | S | 9419750 |
| TWC0857 | Nestucca Bay Entrance |  | 45.1667 | -123.9667 | S | 9419750 |
| 9436381 | Cascade Head, Salmon River | OR | 45.0479 | -124.0073 | R |  |
| 9436101 | Taft, Siletz Bay | OR | 44.9267 | -124.0130 | S | 9419750 |
| 9436031 | Kernville, Siletz River | OR | 44.8967 | -124.0000 | S | 9419750 |
| 9435992 | Chinook Bend, Siletz River | OR | 44.8800 | -123.9636 | R |  |
| 9435827 | Depoe Bay | OR | 44.8100 | -124.0580 | R |  |
| 9435385 | Yaquina Uscg Sta, Newport | OR | 44.6267 | -124.0550 | S | 9419750 |
| 9435380 | Southbeach | OR | 44.6254 | -124.0449 | R |  |
| 9435362 | Toledo | OR | 44.6167 | -123.9370 | S | 9419750 |
| 9435308 | Weiser Point, Yaquina River | OR | 44.5933 | -124.0080 | R |  |
| 9434939 | Waldport, Alsea Bay | OR | 44.4344 | -124.0581 | R |  |
| 9434938 | Drift Creek, Alsea River | OR | 44.4133 | -123.9900 | S | 9432780 |
| 9434132 | Siuslaw River Entrance | OR | 44.0167 | -124.1300 | S | 9432780 |
| 9434098 | Florence Uscg Pier, Siuslaw River | OR | 44.0021 | -124.1230 | R |  |
| 9434068 | Cushman, Siuslaw River | OR | 43.9850 | -124.0450 | R |  |
| 9434032 | Florence, Siuslaw River | OR | 43.9667 | -124.1030 | S | 9432780 |
| TWC0831 | Gardiner |  | 43.7333 | -124.1167 | S | 9432780 |
| 9433501 | Reedsport | OR | 43.7083 | -124.0980 | R |  |
| 9433445 | Umpqua River Entrance, Half Moon Bay | OR | 43.6750 | -124.1920 | R |  |
| 9432864 | Empire | OR | 43.3917 | -124.2800 | S | 9432780 |
| 9432845 | Coos Bay | OR | 43.3800 | -124.2150 | S | 9432780 |
| 9432879 | Sitka Dock, Coos Bay | OR | 43.3767 | -124.2970 | S | 9432780 |
| 9432780 | Charleston | OR | 43.3450 | -124.3220 | R |  |
| 9432436 | Rink Creek Entrance, Coquille River | OR | 43.1579 | -124.1818 | R |  |
| 9432373 | Bandon, Coquille River | OR | 43.1200 | -124.4130 | S | 9432780 |
| 9431647 | Port Orford | OR | 42.7390 | -124.4983 | R |  |
| TWC0817 | Wedderburn, Rogue River |  | 42.4333 | -124.4167 | S | 9419750 |
| 9431011 | Gold Beach, Rogue River | OR | 42.4216 | -124.4187 | R |  |
| 9430104 | Brookings, Chetco Cove | OR | 42.0433 | -124.2850 | S | 9419750 |
| 9419945 | Pyramid Point, Smith River | CA | 41.9453 | -124.2009 | R |  |
| 9419750 | Crescent City | CA | 41.7456 | -124.1844 | R |  |
| 9419059 | Trinidad Harbor | CA | 41.0567 | -124.1470 | S | 9419750 |

### 1.5 Tidal-current prediction stations in the window (220 ids, 469 bin rows)

Type H = harmonic from an ADCP deployment, multiple depth bins (`bin@depth m`, B = below surface);
S = subordinate (single bin, referenced to a harmonic station); W = "weak and variable", no predictions.
`currents_predictions` accepts `interval=MAX_SLACK` (1 year max span) or 6/30/60-min series (1 month). Choose the
shallowest bin for a surface user. The passages asked about: Admiralty Inlet PUG1616/1617 (Bush Point), Point Wilson
PUG1623–1625, Marrowstone PUG1619/1620, Deception Pass PUG1701 (Narrows) and PUG1629 (Yokeko Point), Tacoma Narrows
PUG1524–1528, Rich Passage PUG1513/1514 and ks0101, Agate Passage PUG1501, San Juan Channel PUG1703, Cattle Point
PUG1742/1743, Haro Strait PUG1718/1724, Rosario Strait PUG1702, Strait of Juan de Fuca entrance PUG1642, Race Rocks
PUG1640, Columbia River entrance PCT1121 (Clatsop Spit), PCT1151 (Hammond), PCT1171 (Chinook Point) all subordinate,
Grays Harbor entrance PCT1291 (harmonic) plus PCT1276–1316 subordinates, Yaquina Bay entrance PCT1076, Tillamook Bay
entrance PCT1096, Coos Bay entrance PCT1061, Umpqua PCT1066, Coquille PCT1056, Quillayute PCT1321.

| id | name | lat | lon | type | bins (depth m) |
|---|---|---|---|---|---|
| PCT2301 | Drayton Harbor Entrance | 48.9908 | -122.7678 | S | 1@NoneU |
| PUG1726 | Strait of Georgia, 4.5 nm SW of Point Roberts | 48.9389 | -123.1651 | H | 35@9.449B, 29@21.336B, 11@57.608B |
| cp0101 | Cherry Point | 48.8627 | -122.7610 | H | 20@14.326S |
| PUG1725 | Cherry Point, 1.8 nm southeast of | 48.8338 | -122.7279 | H | 30@2.438B, 20@7.315B, 10@12.497B |
| PCT2166 | Puffin Island Light, 4.8 miles north of | 48.8222 | -122.8083 | S | 1@NoneU |
| PUG1711 | Matia Island, west of | 48.7749 | -122.8410 | H | 26@14.326B, 23@26.518B, 4@102.414B |
| PUG1714 | Patos Island Light, 1.4 nm west of | 48.7731 | -123.0058 | H | 27@14.021B, 23@30.176B, 16@58.218B |
| PUG1713 | Patos Island, south of Toe Point | 48.7721 | -122.9337 | H | 25@4.267B, 20@9.144B, 10@19.203B |
| PCT2286 | Alden Point, Patos Island, 2 miles S of | 48.7578 | -122.9803 | S | 1@NoneU |
| PCT2276 | Skipjack Island, 1.5 miles northwest of | 48.7495 | -123.0608 | S | 1@4.57U |
| PCT2086 | Matia Island, 0.8 mile west of | 48.7488 | -122.8658 | S | 1@NoneU |
| PUG1710 | Hale Passage, east of Lummi Point | 48.7349 | -122.6802 | H | 14@2.438B, 8@8.23B, 3@13.411B |
| PUG1712 | Parker Reef Light, north of | 48.7326 | -122.8864 | H | 25@9.449B, 23@13.716B, 10@39.624B |
| PCT2281 | Point Hammond, 1.1 miles northwest of | 48.7320 | -123.0253 | S | 1@4.57U |
| PUG1709 | Clark Island, 1.6 nm north of | 48.7313 | -122.7734 | H | 33@8.839B, 30@14.631B, 10@54.865B |
| PCT2076 | Raccoon Point, 0.6 mile NNE of | 48.7063 | -122.8292 | S | 1@NoneU |
| PUG1716 | Waldron Island, 1.7 nm west of | 48.7042 | -123.1048 | S | 23@8.23B, 13@28.347B, 3@48.464B |
| PUG1717 | Turn Point, Boundary Pass | 48.6912 | -123.2450 | H | 35@35.357B, 31@51.207B, 28@63.399B |
| PCT2071 | Barnes Island, 0.8 mile southwest of | 48.6858 | -122.7888 | S | 1@NoneU |
| PCT2266 | Johns Island, 0.8 mile north of | 48.6833 | -123.1500 | S | 1@NoneU |
| PUG1708 | Lawrence Point, Orcas Island, 1.3 nm NE of | 48.6794 | -122.7147 | H | 16@11.278B, 14@19.203B, 10@35.052B |
| PUG1715 | President Channel, East of Point Disney | 48.6734 | -123.0060 | H | 38@21.031B, 35@32.919B |
| PCT2116 | Eliza Island, 0.5 mile southeast of | 48.6500 | -122.5667 | W | 1@NoneU |
| PUG1707 | Sinclair Island, 1.0 nm NE of | 48.6442 | -122.6587 | H | 28@7.925B, 17@30.176B, 6@52.121B |
| PCT2241 | East Sound, 0.2 mile SW of Rosario Point | 48.6442 | -122.8813 | W | 1@NoneU |
| PUG1719 | Spieden Channel, north of Limestone Point | 48.6278 | -123.1116 | H | 19@14.326B, 18@18.288B, 7@62.485B |
| PUG1706 | Peapod Rocks Light, 1.2 nm south of | 48.6224 | -122.7476 | H | 11@11.887B, 8@23.775B, 1@51.817B |
| PCT2126 | Towhead Island, 0.4 mile east of | 48.6122 | -122.7022 | S | 1@NoneU |
| PUG1720 | Spring Passage, south entrance | 48.6115 | -123.0341 | H | 26@3.962B, 22@7.925B, 11@18.898B |
| PUG1705 | Obstruction Pass, north of Obstruction Island | 48.6033 | -122.8127 | H | 15@2.438B, 13@4.572B, 1@16.459B |
| PUG1741 | Bellingham Channel North Entrance | 48.5928 | -122.6577 | H | 27@8.23B, 24@14.326B, 5@52.121B |
| PUG1721 | Wasp Passage narrows | 48.5925 | -122.9896 | H | 17@3.353B, 11@9.449B, 2@18.288B |
| PUG1722 | Harney Channel, north of Point Hudson | 48.5897 | -122.9217 | H | 27@3.962B, 20@10.973B, 6@24.994B |
| PUG1718 | Haro Strait, 1.2 nm west of Kellett Bluff | 48.5887 | -123.2258 | H | 36@20.117B, 34@32.309B, 29@62.18B |
| PUG1704 | Peavine Pass, west entrance | 48.5871 | -122.8193 | H | 13@2.743B, 10@5.791B, 1@14.631B |
| PCT2236 | East Sound entrance | 48.5870 | -122.8570 | W | 1@NoneU |
| PUG1732 | Strawberry Island, west of | 48.5610 | -122.7543 | H | 25@10.059B, 23@14.021B, 5@49.988B |
| PUG1740 | Bellingham Channel, off Cypress Head Light | 48.5585 | -122.6618 | H | 19@9.449B, 17@15.24B, 10@36.272B |
| PUG1745 | Point George, west of | 48.5567 | -122.9985 | H | 24@16.155B, 20@36.272B, 10@86.259B |
| PUG1723 | Upright Channel narrows | 48.5538 | -122.9226 | H | 18@7.315B, 13@17.374B, 7@29.566B |
| PCT2106 | Huckleberry Island, 0.5 mile north of | 48.5458 | -122.5663 | S | 1@NoneU |
| PUG1739 | Bellingham Channel South | 48.5396 | -122.6834 | H | 31@5.791B, 27@10.059B, 1@35.967B |
| PCT2046 | Frost-Willow Island, between | 48.5392 | -122.8308 | S | 1@NoneU |
| PUG1736 | Saddle Bag Island Passage | 48.5359 | -122.5639 | H | 34@6.706B, 30@14.631B, 24@26.518B |
| PUG1735 | Guemes Channel, East Entrance | 48.5277 | -122.6060 | H | 14@2.743B, 9@7.62B, 1@15.85B |
| PUG1733 | Thatcher Pass | 48.5274 | -122.8040 | H | 22@8.535B, 17@18.593B, 4@44.501B |
| PUG1731 | Fauntleroy Point Light, east of | 48.5216 | -122.7707 | H | 18@6.401B, 13@16.459B, 7@28.347B |
| PUG1734 | Guemes Channel, West Entrance | 48.5212 | -122.6522 | H | 14@3.353B, 10@7.315B, 1@16.155B |
| PUG1746 | Pear Point, east of | 48.5114 | -122.9529 | H | 10@9.754B, 8@17.983B, 4@34.138B |
| PCT2026 | Green Point, 0.8 mile northwest of | 48.5047 | -122.7062 | S | 1@NoneU |
| PUG1724 | South Haro Strait, south of Lime Kiln Light | 48.4980 | -123.1599 | H | 31@32.614B, 29@48.464B, 27@64.618B |
| PUG1729 | Belle Rock Light, east of | 48.4968 | -122.7308 | H | 21@7.01B, 15@18.898B, 7@35.052B |
| PUG1738 | Burrows Pass | 48.4895 | -122.6867 | H | 27@4.572B, 23@8.535B, 1@30.48B |
| PCT2191 | Kings Point, Lopez Island, 1 mile NNW of | 48.4833 | -122.9558 | S | 1@4.57U |
| PUG1730 | Lopez Pass | 48.4797 | -122.8189 | H | 17@4.572B, 11@10.668B, 4@17.679B |
| PUG1737 | Allan Pass | 48.4716 | -122.6998 | H | 26@3.353B, 23@6.401B, 1@28.347B |
| PCT2006 | Burrows Bay, 0.5 mile east of Allan I | 48.4628 | -122.6828 | S | 1@NoneU |
| PUG1703 | San Juan Channel, south entrance | 48.4610 | -122.9520 | H | 17@22.86B, 16@28.042B, 13@34.748B |
| PUG1702 | Rosario Strait | 48.4581 | -122.7501 | H | 16@14.326B, 13@23.165B, 9@35.357B |
| PUG1744 | Discovery Island, 3.0 nm NE of | 48.4521 | -123.1554 | H | 22@12.497B, 20@20.727B, 13@48.769B |
| PUG1642 | Strait of Juan de Fuca Entrance | 48.4500 | -124.5838 | H | 49@31.09B |
| PUG1742 | Cattle Point, 1.2 nm SE of | 48.4344 | -122.9466 | H | 21@11.887B, 18@23.775B, 15@35.662B |
| PUG1728 | Point Colville, 1.4 nm east of | 48.4181 | -122.7812 | H | 26@8.839B, 22@17.069B, 10@40.844B |
| PUG1629 | Yokeko Point, Deception Pass | 48.4127 | -122.6132 | H | 9@2.13B, 7@4.27B, 3@8.23B |
| PUG1727 | Point Colville, 3.0 nm east of (Lawson Reef, 1 nm | 48.4125 | -122.7403 | H | 30@10.363B, 28@14.326B, 10@50.293B |
| PUG1701 | Deception Pass (Narrows) | 48.4062 | -122.6431 | H | 33@5.486B, 24@14.326B, 18@20.422B |
| PCT1416 | Cattle Point, 2.8 miles SSW of | 48.4000 | -123.0000 | S | 1@NoneU |
| PCT1971 | Colville Island, 1 mile SSE of | 48.4000 | -122.8167 | S | 1@NoneU |
| PUG1628 | Skagit Bay channel, SW of Hope Island | 48.3978 | -122.5796 | H | 13@3.05B, 8@7.92B, 4@11.89B |
| PUG1743 | Cattle Point, 4.6 nm SW of | 48.3840 | -123.0157 | H | 22@16.764B, 19@32.004B, 14@56.998B |
| PCT1411 | Discovery Island, 3 miles SSE of | 48.3833 | -123.2000 | S | 1@4.57U |
| PCT1966 | Iceberg Point, 2.1 miles SSW of | 48.3833 | -122.9167 | S | 1@NoneU |
| PUG1627 | Skagit Bay, 1 mi. south of Goat Island | 48.3448 | -122.5451 | H | 17@3.66B, 11@9.75B, 5@15.85B |
| PUG1632 | Smith Island, 5.5 mi. WNW of | 48.3246 | -122.9648 | H | 41@13.11B, 26@42.98B, 14@67.06B |
| PCT1391 | Trial Island, 5.2 miles SSW of | 48.3167 | -123.3667 | S | 1@4.57S |
| PUG1636 | Discovery Island, 7.6 mi. SSE of | 48.3002 | -123.1672 | H | 34@8.53B, 20@36.58B, 1@74.37B |
| PCT1451 | Smith Island, 1.4 miles SSW of | 48.3000 | -122.8500 | S | 1@NoneU |
| PUG1641 | Pillar Point, 6 mi. NNE of | 48.3000 | -124.0374 | H | 75@12.5B, 70@22.555B, 36@90.527B |
| PUG1634 | Smith Island, 3.4 mi. ESE of | 48.2964 | -122.7763 | H | 36@6.1B, 25@17.07B, 1@40.84B |
| PUG1626 | Skagit Bay, 1 mi. north of Rocky Point | 48.2671 | -122.5296 | H | 20@3.66B, 15@8.53B, 7@16.46B |
| PCT1401 | New Dungeness Light, 6 miles NNE of | 48.2667 | -123.0500 | S | 1@4.57U |
| PUG1635 | New Dungeness Light, 2.8 mi. NNW of | 48.2335 | -123.1334 | H | 58@15.85B, 55@21.64B, 11@109.73B |
| PCT1466 | Point Partridge, 3.7 miles west of | 48.2333 | -122.8667 | S | 1@NoneU |
| PUG1640 | Race Rocks, 4.5 mi. S of | 48.2232 | -123.5323 | H | 18@18.29B, 9@72.24B |
| PUG1637 | Ediz Hook Light, 5.3 mi. ENE of | 48.1823 | -123.2815 | H | 29@6.71B, 28@8.53B, 5@54.56B |
| PUG1639 | Angeles Pt., 2 mi. NNE of | 48.1770 | -123.5269 | H | 16@3.66B, 12@7.62B, 1@18.59B |
| PUG1622 | West of Camano Island | 48.1697 | -122.5532 | H | 27@7.01B, 20@21.03B, 3@54.86B |
| PUG1625 | Point Wilson, 2.7 mi. NE of | 48.1671 | -122.7074 | H | 45@6.1B, 34@17.07B, 15@35.97B |
| PUG1638 | Ediz Hook Light, 1.2 miles N of | 48.1667 | -123.4158 | H | 22@10.97B, 17@25.91B, 7@56.08B |
| PUG1631 | Violet Point, 3.7 mi. NW of Protection Island | 48.1614 | -122.9681 | H | 33@5.18B, 26@12.19B, 4@34.14B |
| PUG1624 | Point Wilson, 1.6 mi. NE of | 48.1569 | -122.7260 | H | 47@6.4B, 27@26.52B, 8@45.42B |
| PUG1623 | Point Wilson, 0.6 mi. NE of | 48.1501 | -122.7454 | H | 45@5.18B, 33@17.07B, 14@35.97B |
| PCT1496 | Point Wilson, 0.8 mile east of | 48.1500 | -122.7333 | S | 1@NoneU |
| PCT1371 | Port Angeles | 48.1333 | -123.4167 | W | 1@NoneU |
| PUG1620 | Marrowstone Point, 1.65 mi. NE of | 48.1193 | -122.6623 | H | 28@7.92B, 20@24.08B, 10@43.89B |
| PCT1376 | Ediz Hook Light, 1.4 miles southeast of | 48.1167 | -123.4000 | W | 1@NoneU |
| PCT1501 | Port Townsend, 0.5 mile S of Pt. Hudson | 48.1167 | -122.7500 | W | 1@NoneU |
| PCT1511 | Marrowstone Point, 1.1 miles northwest of | 48.1167 | -122.7000 | S | 1@NoneU |
| PUG1630 | Kanem Point, 1.5 mi. SW of Protection Island | 48.1077 | -122.9736 | H | 53@6.71B, 43@16.76B, 30@29.57B |
| PUG1619 | Marrowstone Point, 0.8 mi. NE of | 48.1063 | -122.6725 | H | 46@8.84B, 32@22.86B, 9@46.03B |
| PCT1926 | Port Susan | 48.1000 | -122.3667 | W | 1@NoneU |
| PUG1618 | Camano Head-Sandy Point, passage | 48.0479 | -122.3890 | H | 42@9.75B, 35@23.77B, 15@63.7B |
| PUG1616 | Admiralty Inlet (off Bush Point) | 48.0335 | -122.6376 | H | 31@8.84B, 25@20.73B, 6@58.83B |
| PUG1614 | Port Townsend Canal | 48.0325 | -122.7326 | H | 7@1.52B, 1@4.57B |
| PUG1617 | Bush Point Light, 0.5 mile NW of | 48.0308 | -122.6133 | H | 39@13.41B, 34@23.47B, 14@63.4B |
| PUG1615 | Nodule Point, 0.5 mi. SE of | 48.0287 | -122.6609 | H | 18@2.74B, 13@7.62B, 1@19.81B |
| PUG1611 | Olele Point, 1.8 mi. ENE of | 47.9788 | -122.6455 | H | 49@6.1B, 35@20.12B, 10@45.11B |
| PCT1606 | Useless Bay | 47.9783 | -122.4953 | W | 1@NoneU |
| PUG1613 | Everett | 47.9762 | -122.2382 | W | 29@7.62B |
| PUG1612 | Clinton Ferry Terminal | 47.9690 | -122.3451 | H | 10@6.4B, 6@14.33B, 1@24.38B |
| PUG1610 | Foulweather Bluff, 1.9 mi. NE of | 47.9543 | -122.5786 | H | 33@6.1B, 32@8.23B, 17@38.1B |
| PUG1609 | West of Mukilteo | 47.9490 | -122.3285 | H | 36@18.9B, 30@42.67B, 20@82.91B |
| PUG1608 | Hood Canal Entrance, Foulweather Bluff | 47.9284 | -122.6388 | H | 35@9.75B, 28@23.77B, 1@77.72B |
| PUG1607 | Point No Point, 2.1 mi. E of | 47.9189 | -122.4841 | H | 33@9.3B, 29@17.31B, 1@73.15B |
| PCT1321 | Quillayute River entrance | 47.9167 | -124.6333 | S | 1@NoneU |
| PUG1606 | Point No Point, 1.2 mi. E of | 47.9125 | -122.5020 | H | 39@21.03B, 36@32.92B, 1@172.82B |
| PUG1605 | Possession Sound Entrance | 47.8993 | -122.3601 | H | 40@17.98B, 30@57.91B, 20@98.15B |
| PCT1571 | Port Gamble Bay, 0.5 mile N of entrance | 47.8645 | -122.5772 | W | 1@NoneU |
| PUG1603 | Hood Canal Bridge | 47.8547 | -122.6294 | H | 20@6.71B, 11@33.83B, 1@63.7B |
| PUG1604 | Port Gamble Bay Entrance | 47.8547 | -122.5782 | H | 8@3.05B, 1@9.75B |
| PUG1602 | South Point | 47.8217 | -122.6767 | H | 48@7.32B, 42@13.11B, 1@54.26B |
| PUG1503 | Edmonds, 2.5 miles West of | 47.8071 | -122.4441 | H | 34@20.42B, 29@40.54B, 15@96.62B |
| PUG1511 | President Point, 1.5 miles east of | 47.7671 | -122.4319 | H | 38@21.64B, 30@53.65B, 20@93.88B |
| ks0201 | Bangor, Hood Canal LB B | 47.7578 | -122.7306 | H | 2@4.267S, 6@8.535S, 10@12.497S |
| PUG1509 | Point Jefferson, East of | 47.7445 | -122.4680 | H | 9@5.79B, 5@13.72B, 1@21.64B |
| PCT1636 | Agate Passage, north end | 47.7220 | -122.5550 | S | 1@NoneU |
| PUG1501 | Agate Passage, south end | 47.7110 | -122.5671 | H | 6@2.74B, 1@7.62B |
| PUG1508 | Liberty Bay (entrance), Port Orchard | 47.7068 | -122.6283 | H | 10@2.13B, 5@7.32B, 1@11.28B |
| PCT1651 | Port Orchard, off Keyport | 47.7003 | -122.6083 | W | 1@NoneU |
| PUG1601 | Hazel Point | 47.6912 | -122.7628 | H | 21@7.01B, 11@26.82B, 1@46.94B |
| PCT1661 | Shilshole Bay | 47.6833 | -122.4167 | W | 1@NoneU |
| PUG1504 | Entrance to Ballard Locks | 47.6710 | -122.4070 | W | 7@2.74B |
| PUG1515 | West Point, West of | 47.6621 | -122.4417 | H | 15@4.88B, 10@14.94B, 1@32.92B |
| PCT1671 | West Point, 1.2 miles west of | 47.6595 | -122.4653 | W | 1@NoneU |
| PCT1646 | Port Orchard | 47.6375 | -122.5847 | W | 1@NoneU |
| PUG1505 | Entrance to Eagle Harbor | 47.6196 | -122.4953 | H | 8@2.74B, 1@9.75B |
| PCT1676 | Elliott Bay entrance | 47.6120 | -122.4072 | W | 1@NoneU |
| ks0101 | Rich Passage, LB 8 | 47.5933 | -122.5426 | H | 1@3.414S, 2@4.389S, 7@9.388S |
| PUG1514 | Rich Passage, West end | 47.5899 | -122.5623 | H | 8@3.66B, 5@9.45B, 1@17.37B |
| PUG1506 | Harbor Island East | 47.5885 | -122.3440 | W | 12@1.83B |
| PUG1502 | Alki Point, 1 mile West of | 47.5837 | -122.4518 | H | 44@23.17B, 35@59.13B, 13@147.22B |
| PCT1701 | Off Pleasant Beach | 47.5833 | -122.5333 | S | 1@NoneU |
| PUG1507 | Harbor Island West | 47.5831 | -122.3602 | H | 13@2.74B, 9@6.71B |
| PUG1510 | Port Washington Narrows, Warren Ave. Bridge | 47.5796 | -122.6307 | H | 6@1.22B, 1@6.4B |
| PUG1512 | Restoration Point | 47.5788 | -122.4687 | H | 19@6.71B, 10@24.69B, 1@42.67B |
| PUG1516 | Alki Point, West of | 47.5761 | -122.4278 | H | 17@11.58B, 12@31.39B, 5@59.44B |
| PUG1513 | Rich Passage, East end | 47.5700 | -122.5298 | H | 10@3.35B, 6@11.58B, 1@21.34B |
| PCT1711 | Port Orchard, southwest of Waterman | 47.5667 | -122.6000 | W | 1@NoneU |
| PCT1596 | Chinom Point | 47.5333 | -123.0333 | W | 1@NoneU |
| PUG1517 | Blake Island, S of | 47.5203 | -122.4879 | H | 21@13.41B, 16@28.35B, 8@52.43B |
| PUG1520 | Dolphin Point, 1.3 miles East of | 47.5015 | -122.4236 | H | 35@14.63B, 28@42.37B |
| PUG1518 | Anderson Point, East of, Colvos Passage | 47.4394 | -122.5258 | H | 19@10.67B, 17@18.9B, 10@46.94B |
| PUG1519 | Point Richmond, East of, Colvos Passage | 47.3766 | -122.5287 | H | 18@13.41B, 13@33.53B, 3@73.46B |
| PUG1521 | Browns Point, 1.6 miles North of | 47.3287 | -122.4540 | H | 34@8.53B, 24@48.46B, 14@88.39B |
| PUG1522 | Dalco Passage | 47.3251 | -122.5247 | H | 12@39.01B, 3@57.0B |
| PUG1523 | Gig Harbor Entrance | 47.3242 | -122.5719 | H | 14@3.35B, 8@9.45B, 1@16.46B |
| PUG1524 | The Narrows, North end - midstream | 47.3060 | -122.5500 | H | 16@12.19B, 9@26.52B, 1@42.37B |
| PUG1548 | Pickering Passage, North end | 47.3057 | -122.8509 | H | 10@5.79B, 6@13.72B, 1@23.77B |
| PUG1526 | The Narrows, North End (west side) | 47.3040 | -122.5567 | H | 28@12.8B, 20@28.96B, 5@58.83B |
| PUG1530 | Hale Passage, West end | 47.2814 | -122.6631 | H | 18@4.27B, 10@12.19B, 1@21.34B |
| PUG1527 | The Narrows, 0.3 miles North of Bridge | 47.2743 | -122.5453 | H | 19@7.01B, 12@21.03B, 1@42.98B |
| PUG1528 | The Narrows, South end (midstream) | 47.2613 | -122.5583 | H | 17@7.92B, 13@15.85B, 1@39.93B |
| PUG1529 | Hale Passage, East end | 47.2479 | -122.5956 | H | 11@3.35B, 6@13.41B, 1@23.47B |
| PUG1547 | Pickering Passage, off Graham Point | 47.2472 | -122.9259 | H | 16@3.05B, 10@9.14B, 1@17.98B |
| PCT1916 | Case Inlet, 1 mile SE of McMicken Island | 47.2383 | -122.8437 | W | 1@NoneU |
| PUG1536 | Pitt Passage, NE of Pitt Island | 47.2238 | -122.7114 | H | 6@2.13B, 1@7.01B |
| PUG1546 | Pickering Passage, West of Squaxin Island | 47.2193 | -122.9345 | H | 14@2.74B, 8@8.84B, 1@15.85B |
| PUG1531 | Gibson Point, 0.8 miles East of | 47.2191 | -122.5887 | H | 18@9.45B, 13@24.69B, 6@45.42B |
| PUG1542 | Peale Passage, North end | 47.2175 | -122.9146 | H | 5@1.22B, 1@5.18B |
| PCT1896 | Hammersley Inlet, west of Skookum Point | 47.2070 | -123.0395 | S | 1@4.57U |
| PUG1545 | Libby Point, Hammersley Inlet | 47.1989 | -122.9890 | H | 10@1.52B, 1@5.79B |
| PUG1535 | Balch Passage, NE of Eagle Island | 47.1906 | -122.6916 | H | 16@3.35B, 10@9.14B, 1@18.29B |
| PUG1544 | Totten Inlet Entrance | 47.1883 | -122.9454 | H | 11@4.27B, 7@12.5B, 3@20.42B |
| PUG1532 | Steilacoom, 0.8 miles North of | 47.1824 | -122.6056 | H | 16@13.72B, 13@25.91B, 6@53.95B |
| PUG1543 | Squaxin Passage, North of Hunter Point | 47.1763 | -122.9190 | H | 9@1.52B, 5@5.49B, 1@9.75B |
| PUG1541 | Peale Passage, South end | 47.1749 | -122.8870 | H | 9@2.74B, 5@6.71B, 1@10.67B |
| PUG1537 | Drayton Passage | 47.1726 | -122.7415 | H | 20@5.79B, 15@15.85B, 5@35.97B |
| PUG1539 | Dana Passage | 47.1631 | -122.8681 | H | 12@4.88B, 8@13.11B, 1@26.82B |
| PUG1538 | Devils Head, West of | 47.1607 | -122.7894 | H | 22@7.32B, 16@25.3B, 5@58.22B |
| PUG1533 | Ketron Island, West of | 47.1486 | -122.6594 | H | 18@11.58B, 14@27.43B, 10@43.59B |
| PCT1861 | Eld Inlet entrance | 47.1463 | -122.9333 | S | 1@4.57U |
| PUG1540 | Budd Inlet Entrance | 47.1402 | -122.9214 | H | 10@3.66B, 7@9.75B, 1@21.64B |
| PUG1534 | Nisqually Reach, 0.5 miles South of Lyle Point | 47.1169 | -122.6989 | H | 16@8.84B, 12@20.73B, 1@53.95B |
| PCT1301 | Channel, 1.5 miles north of Westport | 46.9333 | -124.1000 | S | 1@NoneU |
| PCT1306 | Channel, 2.1 miles NNE of Westport | 46.9333 | -124.0833 | S | 1@NoneU |
| PCT1276 | Entrance, 0.2 mile south of north jetty | 46.9263 | -124.1613 | S | 1@NoneU |
| PCT1291 | Grays Harbor Entrance | 46.9225 | -124.1330 | H | 1@NoneU |
| PCT1296 | Entrance, 1.1 miles NW of Westport | 46.9167 | -124.1333 | S | 1@NoneU |
| PCT1286 | Entrance, 0.6 mile WNW of Westport | 46.9147 | -124.1250 | S | 1@NoneU |
| PCT1316 | Westport, channel 0.4 mile NE of | 46.9142 | -124.1083 | S | 1@NoneU |
| PCT1281 | Entrance, Point Chehalis Range | 46.9083 | -124.1555 | S | 1@NoneU |
| PCT1271 | South Bend, Willapa River | 46.6647 | -123.8013 | S | 1@NoneU |
| PCT1116 | Baker Bay entrance, E of Sand Island Tower | 46.2620 | -123.9980 | S | 1@7.01S |
| PCT1111 | Sand Island Tower, 0.9nm SE of (north channel) | 46.2578 | -123.9945 | S | 1@4.57S |
| PCT1126 | Sand Island, SSE of | 46.2555 | -123.9680 | S | 1@3.66S |
| PCT1106 | Sand Island Tower, 1nm SE of (midchannel) | 46.2528 | -123.9908 | S | 1@4.57S |
| PCT1121 | Clatsop Spit, NNE of | 46.2462 | -123.9942 | S | 1@4.57S |
| PCT1171 | Chinook Point, WSW of | 46.2422 | -123.9642 | S | 1@4.27S |
| PCT1161 | Point Ellice, east of | 46.2417 | -123.8483 | S | 1@5.18S |
| PCT1156 | McGowan, SSW of | 46.2395 | -123.9153 | S | 1@4.27S |
| PCT1186 | Woody Island Channel | 46.2395 | -123.6733 | S | 1@4.57S |
| PCT1201 | Quinn Island, Prairie Channel | 46.2372 | -123.5033 | S | 1@2.44S |
| PCT1166 | Point Adams, NNE OF | 46.2278 | -123.9675 | S | 1@4.27S |
| PCT1176 | Tongue Point, northwest of | 46.2192 | -123.7667 | S | 1@4.57S |
| PCT1206 | Clifton Channel | 46.2178 | -123.4653 | S | 1@3.05S |
| PCT1191 | Woody Island Channel (off Seal Island) | 46.2175 | -123.6292 | S | 1@3.66S |
| PCT1151 | Hammond, northeast of ship channel | 46.2112 | -123.9345 | S | 1@4.57S |
| PCT1216 | Hunting Island, south of | 46.2072 | -123.4042 | S | 1@6.1S |
| PCT1146 | Youngs Bay Bridge | 46.1778 | -123.8683 | S | 1@2.74S |
| PCT1231 | Cathlamet Channel, SE of Nassa Point | 46.1562 | -123.3150 | S | 1@5.79S |
| PCT1251 | Walker Island, south of | 46.1412 | -123.0458 | S | 1@3.66S |
| PCT1096 | Tillamook Bay entrance | 45.5622 | -123.9383 | S | 1@NoneU |
| PCT1081 | Yaquina Bay, Highway Bridge | 44.6233 | -124.0570 | S | 1@NoneU |
| PCT1076 | Yaquina Bay entrance | 44.6167 | -124.0667 | S | 1@NoneU |
| PCT1086 | Yaquina, Yaquina River | 44.6020 | -124.0113 | S | 1@NoneU |
| PCT1091 | Yaquina River, 1 mile below Toledo | 44.6005 | -123.9417 | S | 1@NoneU |
| PCT1071 | Heceta Head | 44.1333 | -124.1333 | S | 1@NoneU |
| PCT1066 | Umpqua River entrance | 43.6783 | -124.1933 | S | 1@NoneU |
| PCT1061 | Coos Bay entrance | 43.3550 | -124.3412 | S | 1@NoneU |
| PCT1056 | Coquille River entrance | 43.1217 | -124.4197 | S | 1@NoneU |

## 2. Canadian Hydrographic Service IWLS API (api-iwls.dfo-mpo.gc.ca)

| Item | Detail |
|---|---|
| Endpoints (OpenAPI at `https://api-iwls.dfo-mpo.gc.ca/v3/api-docs`, fetched 200) | `GET /api/v1/stations` (all stations, 0.85 MB; fields code, id, lat/lon, officialName, operating, timeSeries[]); `GET /api/v1/stations/{id}/metadata` (datums e.g. Tofino CGVD2013 offset -1.96 m, timeZoneCode, isTideTableReferencePort); `GET /api/v1/stations/{id}/data?time-series-code=CODE&from=ISO&to=ISO[&resolution=]`; `GET /api/v1/stations/data/latest?time-series-code=wlo` (returned all 118 reporting stations' last 20 one-minute values, 242 KB; a `station-codes` filter was ignored); `GET /api/v1/time-series-definitions`. Station ids are Mongo-style hex strings, not the 5-digit codes; the table below lists both. |
| Time-series codes | `wlo` official observed water level (1-min), `wlp` predictions, `wlp-hilo` high/low predictions, `wlf` model forecast (Sand Heads only in window), `wcsp1`/`wcdp1` predicted current speed/direction (15-min), `wcp1-events` slack/max events, `wcs1`/`wcd1` observed current (Calamity Point, Second Narrows, Johnson Street Bridge), `ap1` atmospheric pressure (Tofino, Port Alberni, Patricia Bay). No water-temperature series exists in IWLS. Allowed span per request: wlo/wlp/wcsp1 7 days, wlp-hilo and wcp1-events 366 days (from the definitions endpoint). |
| Fetched samples (2026-10-13, 200) | Tofino 08615 (`5cebf1e23d0f4a073c4bc07c`) `wlo` 12:00–20:00 Z: 59 KB of 1-min values, first `{"eventDate":"2026-10-13T12:00:00Z","qcFlagCode":"1","value":2.596}` (m above chart datum). Tofino `wlp-hilo` 13–15 Oct: 03:45 Z 0.52, 10:05 Z 3.156, 15:35 Z 1.503, 21:34 Z 3.52. Race Passage 07090 (`63aeee896a2b9417c034d337`) `wcsp1`: 15-min speeds (first 1.209, 0.595 …); `wcp1-events`: SLACK 00:28 Z 0.0, EXTREMA_EBB 03:51 Z 4.959, SLACK 07:52, EXTREMA_FLOOD 10:42 5.217 (values match the knots CHS current tables use; confirm units via the series metadata before display). A guessed id returned a clean 404 JSON error. |
| Cadence/latency | `wlo` is 1-minute and the `latest` call carried values 10 minutes old. Predictions are static. |
| Terms | OpenAPI description links "Terms of service" (`https://www.dfo-mpo.gc.ca/terms-avis/terms-conditions-avis-eng.htm`) and "License of API" (`https://www.tides.gc.ca/en/licence-agreement`). From the licence page: "The Data shall not be used in the purpose of navigation;" "The Data shall not be used in the purpose of producing derivative products for commercial purposes," data "shall not be sold, licensed, leased, assigned or given to a third party", derivative products must carry "This product is not to be used for navigation." and the attribution "contains intellectual property (Data) of the Canadian Hydrographic Service of the Department of Fisheries and Oceans." No API key is required and no rate limit is stated. |
| Caveats | 124 of the ~1000 stations fall in the window but only 27 are `operating`; the rest are prediction-only (`wlp`, `wlp-hilo`), which is still useful for Tofino-area breaks. Ucluelet is flagged `TEMPORARY`. Datum is Canadian chart datum (LLWLT-ish), not MLLW; do not mix with US numbers without the metadata offsets. For BC water temperature use NDBC/ECCC buoys (other agent) or DFO's BC Lightstation daily SST/salinity CSVs on open.canada.ca (Amphitrite Point, Race Rocks, Nootka; Open Government Licence; not fetched). |

### 2.1 CHS stations in the window (124; 27 operating)

| code | name | lat | lon | operating | id | time series |
|---|---|---|---|---|---|---|
| 07990 | Welcome Bay | 49.7000 | -124.5500 | False | `5cebf1de3d0f4a073c4bb97d` | wlp-hilo, wlp |
| 07811 | Squamish Inner | 49.6950 | -123.1550 | False | `5cebf1de3d0f4a073c4bb94e` | wlp-hilo, wlp |
| 08650 | Gold River | 49.6790 | -126.1260 | False | `5cebf1e23d0f4a073c4bc08c` | wlp-hilo, wlp |
| 07965 | Comox | 49.6700 | -124.9280 | False | `5cebf1de3d0f4a073c4bb979` | wlp-hilo, wlp |
| 07808 | Darrell Bay | 49.6690 | -123.1690 | True | `5cebf1e43d0f4a073c4bc40e` | wlo, wlp, wlp-hilo |
| 07847 | Storm Bay | 49.6620 | -123.8260 | False | `5dd3064ee0fdc4b9b4be670e` | wlp-hilo, wlp |
| 07836 | Irvines Landing | 49.6330 | -124.0580 | False | `5cebf1de3d0f4a073c4bb954` | wlp-hilo, wlp |
| 07837 | ḵalpilin | 49.6330 | -124.0320 | False | `5dd3064fe0fdc4b9b4be69da` | wlp-hilo, wlp |
| 07955 | Denman Island | 49.5345 | -124.8209 | False | `5cebf1de3d0f4a073c4bb977` | wlp-hilo, wlp |
| 07803 | Port Mellon | 49.5192 | -123.4853 | False | `638e5f11330a8d58a5b0882c` | wlp, wlp-hilo |
| 07830 | Halfmoon Bay | 49.5110 | -123.9120 | False | `5cebf1de3d0f4a073c4bb952` | wlp, wlp-hilo |
| 07985 | Skerry Bay | 49.5000 | -124.2370 | False | `5dd3064fe0fdc4b9b4be6ad7` | wlp-hilo, wlp |
| 07953 | Hornby Island | 49.4962 | -124.6760 | False | `5cebf1de3d0f4a073c4bb975` | wlp, wlp-hilo |
| 07982 | False Bay | 49.4830 | -124.3500 | False | `5cebf1de3d0f4a073c4bb97b` | wlp-hilo, wlp |
| 07852 | Porpoise Bay | 49.4820 | -123.7590 | False | `5cebf1de3d0f4a073c4bb958` | wlp, wlp-hilo |
| 07774 | Indian Arm Head | 49.4618 | -122.8861 | True | `5dd3064ee0fdc4b9b4be6717` | wlo, wlp, wlp-hilo |
| 07824 | Roberts Creek | 49.4190 | -123.6420 | False | `5dd3064ee0fdc4b9b4be670a` | wlp-hilo, wlp |
| 08634 | Sulphur Passage | 49.4040 | -126.0680 | False | `5cebf1e23d0f4a073c4bc086` | wlp-hilo, wlp |
| 07820 | Gibsons | 49.4020 | -123.5050 | False | `5cebf1de3d0f4a073c4bb950` | wlp-hilo, wlp |
| 08637 | Riley Cove | 49.3910 | -126.2250 | False | `5cebf1e23d0f4a073c4bc088` | wlp-hilo, wlp |
| 07940 | French Creek | 49.3496 | -124.3588 | False | `5dd30650e0fdc4b9b4be6e1a` | wlp-hilo, wlp |
| 08632 | Herbert Inlet | 49.3460 | -125.9840 | False | `5cebf1e23d0f4a073c4bc084` | wlp-hilo, wlp |
| 07786 | Sandy Cove | 49.3405 | -123.2319 | True | `5cebf1e43d0f4a073c4bc43b` | wlo, wlp, wlp-hilo |
| 07795 | Point Atkinson | 49.3375 | -123.2536 | True | `5cebf1de3d0f4a073c4bb94c` | wlo, wlp, wlp-hilo |
| 07765 | Deep Cove | 49.3268 | -122.9485 | False | `5dd3064ee0fdc4b9b4be6707` | wlp, wlp-hilo |
| 07780 | Ambleside | 49.3258 | -123.1546 | True | `5cebf1e43d0f4a073c4bc45a` | wlo, wlp, wlp-hilo |
| 07721 | First Narrows         | 49.3160 | -123.1401 | True | `5dd30650e0fdc4b9b4be6d24` | wcsp1, wcdp1, wcp1-events |
| 07720 | Lions Gate                 | 49.3154 | -123.1387 | True | `5dd3064fe0fdc4b9b4be6974` | dvc1 |
| 07724 | Calamity Point | 49.3126 | -123.1277 | True | `5cebf1e43d0f4a073c4bc434` | wlo, wlp, wlp-hilo, wcs1, wcd1, wcs2, wcd2, wcsp1, wcdp1, wcp1-events |
| 07938 | Northwest Bay | 49.3030 | -124.2020 | False | `5cebf1de3d0f4a073c4bb973` | wlp-hilo, wlp |
| 07935 | Winchelsea Island | 49.3000 | -124.0860 | False | `5cebf1de3d0f4a073c4bb971` | wlp, wlp-hilo |
| 07745 | Second Narrows | 49.2947 | -123.0245 | True | `5dd30650e0fdc4b9b4be6c2d` | wcd1, wcs1, wcsp1, wcdp1, wcp1-events |
| 07743 | Cascadia Terminals  | 49.2924 | -123.0284 | False | `5dd3064fe0fdc4b9b4be69d9` |  |
| 07747 | Stanovan | 49.2912 | -123.0046 | False | `5dd3064ee0fdc4b9b4be6705` |  |
| 07755 | Port Moody | 49.2877 | -122.8658 | True | `5cebf1de3d0f4a073c4bb94a` | wlo, wlp, wlp-hilo |
| 07735 | Vancouver | 49.2863 | -123.0997 | True | `5cebf1de3d0f4a073c4bb943` | wlo, wlp, wlp-hilo |
| 07707 | Kitsilano | 49.2766 | -123.1394 | True | `5cebf1e43d0f4a073c4bc404` | wlo, wlp, wlp-hilo |
| 07710 | False Creek | 49.2710 | -123.1200 | False | `5dd3064ee0fdc4b9b4be66ff` | wlp-hilo, wlp |
| 08630 | Cypress Bay | 49.2610 | -125.8710 | False | `5cebf1e23d0f4a073c4bc082` | wlp, wlp-hilo |
| 07930 | Nanoose Bay | 49.2500 | -124.1700 | False | `5cebf1de3d0f4a073c4bb96f` | wlp-hilo, wlp |
| 08626 | Warn Bay | 49.2389 | -125.7455 | False | `5cebf1e23d0f4a073c4bc080` | wlp, wlp-hilo |
| 08575 | Port Alberni | 49.2256 | -124.8136 | True | `5cebf1e23d0f4a073c4bc06f` | wlo, wlp, wlp-hilo, ap1 |
| 07654 | New Westminster | 49.2000 | -122.9100 | True | `5cebf1e13d0f4a073c4bbf93` | wlo, wlp, wlp-hilo |
| 07917 | Nanaimo Harbour | 49.1628 | -123.9235 | True | `5cebf1de3d0f4a073c4bb96d` | wlo, wlp, wlp-hilo |
| 08615 | Tofino | 49.1540 | -125.9130 | True | `5cebf1e23d0f4a073c4bc07c` | wlo, wlp, wlp-hilo, ap1 |
| 07550 | Silva Bay | 49.1500 | -123.7000 | False | `5cebf1de3d0f4a073c4bb9d3` | wlp-hilo, wlp |
| 08623 | Kennedy Cove | 49.1400 | -125.6710 | False | `5cebf1e23d0f4a073c4bc07e` | wlp, wlp-hilo |
| 07913 | Harmac | 49.1400 | -123.8460 | False | `5dd3064fe0fdc4b9b4be691a` | wlp-hilo, wlp |
| 07487 | Dodd Narrows | 49.1344 | -123.8171 | False | `63aef1866a2b9417c035030f` | wcsp1, wcdp1, wcp1-events |
| 07445 | Degnen Bay | 49.1333 | -123.7167 | False | `5dd3064fe0fdc4b9b4be6964` | wlp-hilo, wlp |
| 07545 | Gabriola Passage | 49.1291 | -123.7043 | False | `63aef12e84e5432cd3b6db8d` | wcsp1, wcdp1, wcp1-events |
| 07610 | Woodward's Landing | 49.1251 | -123.0754 | False | `5cebf1e43d0f4a073c4bc42d` | wlo, wlp, wlp-hilo, wcs1, wcd1 |
| 07607 | Steveston | 49.1245 | -123.1922 | True | `5cebf1e13d0f4a073c4bbf8c` | wlo, wlp, wlp-hilo |
| 07609 | Deas Basin | 49.1239 | -123.0834 | True | `69b2f92d83949b1d977dbe82` | wlo, wlp, wlp-hilo |
| 08565 | Franklin River | 49.1080 | -124.8120 | False | `5cebf1e23d0f4a073c4bc068` | wlp, wlp-hilo |
| 07594 | Sand Heads | 49.1052 | -123.3042 | True | `5cebf1de3d0f4a073c4bb93c` | wlo, wlp, wlf, wlp-hilo |
| 07480 | Boat Harbour | 49.0900 | -123.7982 | False | `5cebf1e13d0f4a073c4bbf83` | wlp-hilo, wlp |
| 07542 | Valdes Island | 49.0580 | -123.6200 | False | `5dd3064fe0fdc4b9b4be69d6` | wlp-hilo, wlp |
| 07579 | Crescent Beach | 49.0333 | -122.8833 | False | `5dd3064fe0fdc4b9b4be69d7` | wlp-hilo, wlp |
| 07577 | White Rock | 49.0167 | -122.8000 | False | `5cebf1de3d0f4a073c4bb933` | wlp-hilo, wlp |
| 08559 | Head of Uchucklesit | 49.0167 | -125.0500 | False | `5dd3064fe0fdc4b9b4be69df` | wlp-hilo, wlp |
| 07439 | Cardale Point | 49.0167 | -123.6167 | False | `5dd30650e0fdc4b9b4be6d4e` | wlp-hilo, wlp |
| 07592 | Roberts Bank | 49.0150 | -123.1560 | False | `5cebf1e13d0f4a073c4bbf85` | wlp, wlp-hilo |
| 07438 | Porlier Pass | 49.0150 | -123.5850 | False | `63aef0ed84e5432cd3b6c50b` | wcsp1, wcdp1, wcp1-events |
| 07535 | Dionisio Point | 49.0139 | -123.5739 | False | `5cebf1e03d0f4a073c4bbd51` | wlp, wlp-hilo |
| 07437 | Porlier Pass | 49.0113 | -123.5859 | False | `5dd3064fe0fdc4b9b4be6af4` | wlp-hilo, wlp |
| 07590 | Tsawwassen | 49.0068 | -123.1293 | False | `5cebf1de3d0f4a073c4bb935` | wlp, wlp-hilo |
| 07460 | Ladysmith | 48.9990 | -123.8153 | False | `5cebf1e03d0f4a073c4bbd47` | wlp-hilo, wlp |
| 07435 | North Galiano | 48.9947 | -123.5839 | False | `5dd3064fe0fdc4b9b4be6b0d` | wlp, wlp-hilo |
| 08588 | Stopper Islands | 48.9930 | -125.3460 | False | `5cebf1e23d0f4a073c4bc073` | wlp-hilo, wlp |
| 08558 | Brooksby Point | 48.9820 | -124.9850 | False | `5cebf1e23d0f4a073c4bc066` | wlp, wlp-hilo |
| 07471 | Preedy Harbour | 48.9802 | -123.6777 | False | `5cebf1e03d0f4a073c4bbd49` | wlp-hilo, wlp |
| 08595 | Ucluelet | 48.9470 | -125.5520 | True | `5cebf1e23d0f4a073c4bc075` | wlo, wlp, wlp-hilo |
| 08556 | Mutine Point | 48.9420 | -125.0190 | False | `5cebf1e23d0f4a073c4bc064` | wlp, wlp-hilo |
| 07455 | Chemainus | 48.9256 | -123.7144 | False | `5cebf1e03d0f4a073c4bbd45` | wlp-hilo, wlp |
| 07420 | Montague Harbour | 48.8927 | -123.3922 | False | `5cebf1e03d0f4a073c4bbd41` | wlp-hilo, wlp |
| 07532 | Whaler Bay | 48.8833 | -123.3167 | False | `5cebf1e03d0f4a073c4bbd4f` | wlp-hilo, wlp |
| 08585 | Effingham Bay | 48.8780 | -125.3130 | False | `5cebf1e23d0f4a073c4bc071` | wlp-hilo, wlp |
| 07450 | Crofton | 48.8746 | -123.6435 | False | `5cebf1e03d0f4a073c4bbd43` | wlp-hilo, wlp |
| 07525 | Georgina Point | 48.8725 | -123.2923 | False | `5cebf1e03d0f4a073c4bbd4d` | wlp-hilo, wlp |
| 07527 | Active Pass | 48.8604 | -123.3128 | False | `63aef09f84e5432cd3b6c509` | wcsp1, wcdp1, wcp1-events |
| 07407 | Ganges | 48.8534 | -123.4973 | False | `5cebf1e03d0f4a073c4bbd3d` | wlp, wlp-hilo |
| 07528 | Miners Bay | 48.8500 | -123.3000 | False | `5dd3064fe0fdc4b9b4be69d5` | wlp-hilo, wlp |
| 07414 | Village Bay | 48.8445 | -123.3241 | False | `5cebf1e03d0f4a073c4bbd3f` | wlp, wlp-hilo |
| 08545 | Bamfield | 48.8360 | -125.1360 | True | `5cebf1e23d0f4a073c4bc062` | wlo, wlp, wlp-hilo |
| 07370 | Samuel Island | 48.8217 | -123.2084 | False | `5dd3064ee0fdc4b9b4be66eb` | wlp-hilo, wlp |
| 07515 | Samuel Island | 48.8167 | -123.2000 | False | `5dd3064fe0fdc4b9b4be6b70` | wlp-hilo, wlp |
| 07315 | Maple Bay | 48.8157 | -123.6096 | False | `5cebf1df3d0f4a073c4bbd33` | wlp-hilo, wlp |
| 07360 | Hope Bay | 48.8034 | -123.2759 | False | `5cebf1e03d0f4a073c4bbd3b` | wlp-hilo, wlp |
| 07510 | Tumbo Channel | 48.7932 | -123.1088 | False | `5cebf1e03d0f4a073c4bbd4b` | wlp-hilo, wlp |
| 07345 | Narvaez Bay | 48.7743 | -123.0981 | False | `5cebf1df3d0f4a073c4bbd37` | wlp-hilo, wlp |
| 07330 | Fulford Harbour | 48.7690 | -123.4510 | False | `5cebf1df3d0f4a073c4bbd35` | wlp, wlp-hilo |
| 07350 | Bedwell Harbour | 48.7478 | -123.2273 | False | `5cebf1df3d0f4a073c4bbd39` | wlp-hilo, wlp |
| 07310 | Cowichan Bay | 48.7404 | -123.6184 | False | `5cebf1df3d0f4a073c4bbd31` | wlp-hilo, wlp |
| 07270 | Swartz Bay | 48.6892 | -123.4108 | False | `5dd3064ee0fdc4b9b4be6872` | wlp-hilo, wlp |
| 07277 | Patricia Bay | 48.6536 | -123.4515 | True | `5cebf1df3d0f4a073c4bbd2d` | wlo, wlp, wlp-hilo, ap1 |
| 07260 | Sidney | 48.6492 | -123.3929 | True | `5cebf1df3d0f4a073c4bbd26` | wlo, wlp, wlp-hilo |
| 07255 | Saanichton Bay | 48.5989 | -123.3885 | False | `5dd3064de0fdc4b9b4be66e4` | wlp-hilo, wlp |
| 07279 | Bamberton | 48.5887 | -123.5214 | True | `63a36881424d9e40dd99d14d` | wlo, wlp, wlp-hilo |
| 07280 | Brentwood Bay | 48.5780 | -123.4670 | False | `5dd30650e0fdc4b9b4be6b74` | wlp-hilo, wlp |
| 08525 | Port Renfrew | 48.5550 | -124.4210 | True | `5cebf1e23d0f4a073c4bc060` | wlo, wlp, wlp-hilo |
| 07284 | Finlayson Arm | 48.4966 | -123.5529 | False | `5cebf1df3d0f4a073c4bbd2f` | wlp-hilo, wlp |
| 07140 | Finnerty Cove | 48.4736 | -123.2961 | False | `5cebf1df3d0f4a073c4bbd24` | wlp-hilo, wlp |
| 07125 | Portage Inlet | 48.4571 | -123.4166 | False | `5cebf1df3d0f4a073c4bbd20` | wlp-hilo, wlp |
| 07124 | Gorge at Craigflower | 48.4509 | -123.4215 | False | `5dd3064de0fdc4b9b4be66e3` | wlp, wlp-hilo |
| 07123 | Gorge at Tillicum | 48.4477 | -123.4036 | False | `5dd30650e0fdc4b9b4be6be1` | wlp, wlp-hilo |
| 07129 | Tillicum Bridge | 48.4464 | -123.4002 | False | `64960066ebd87908f1fcb787` | wcs1, wcd1, wcsp1, wcdp1, wcp1-events |
| 07122 | Gorge at Aaron Point | 48.4444 | -123.3952 | False | `5dd3064de0fdc4b9b4be66e2` | wlp, wlp-hilo |
| 07109 | Esquimalt Harbour | 48.4404 | -123.4498 | False | `5cebf1e13d0f4a073c4bbf81` | wlp-hilo, wlp |
| 07121 | Selkirk Water | 48.4393 | -123.3795 | False | `5dd30650e0fdc4b9b4be6be0` | wlp, wlp-hilo |
| 07110 | Esquimalt Government  Hbr. | 48.4322 | -123.4385 | False | `5cebf1df3d0f4a073c4bbd17` | wlp, wlp-hilo |
| 07135 | Johnson Street Bridge | 48.4282 | -123.3721 | True | `67a52c150050c220dccd6e33` | wcs1, wcd1 |
| 07120 | Victoria Harbour | 48.4244 | -123.3708 | True | `5cebf1df3d0f4a073c4bbd1e` | wlo, wlp, wlp-hilo |
| 07130 | Oak Bay | 48.4237 | -123.3027 | False | `5cebf1df3d0f4a073c4bbd22` | wlp, wlp-hilo |
| 07115 | Clover Point | 48.4038 | -123.3486 | False | `5dd3064fe0fdc4b9b4be691e` | wlp-hilo, wlp |
| 07010 | Point No Point | 48.3951 | -123.9709 | False | `5dd30650e0fdc4b9b4be6c25` | wlp-hilo, wlp |
| 07013 | Sheringham Point | 48.3771 | -123.9212 | False | `5cebf1df3d0f4a073c4bbd0d` | wlp, wlp-hilo |
| 07024 | Sooke Basin | 48.3742 | -123.6818 | False | `5cebf1df3d0f4a073c4bbd11` | wlp, wlp-hilo |
| 07020 | Sooke | 48.3695 | -123.7260 | False | `5cebf1df3d0f4a073c4bbd0f` | wlp-hilo, wlp |
| 07082 | William Head | 48.3410 | -123.5369 | False | `5dd3064de0fdc4b9b4be66e0` | wlp-hilo, wlp |
| 07030 | Becher Bay | 48.3349 | -123.6038 | False | `5cebf1df3d0f4a073c4bbd13` | wlp-hilo, wlp |
| 07080 | Pedder Bay | 48.3317 | -123.5501 | False | `5cebf1df3d0f4a073c4bbd15` | wlp-hilo, wlp |
| 07090 | Race Passage | 48.3067 | -123.5367 | False | `63aeee896a2b9417c034d337` | wcsp1, wcdp1, wcp1-events |
| 07100 | Juan de Fuca - East | 48.2317 | -123.5300 | False | `63aeee1d84e5432cd3b6c500` | wcsp1, wcdp1, wcp1-events |

## 3. Sea surface temperature

| Source | Variables, resolution, cadence, latency | Endpoint and fetch | Terms | Caveats |
|---|---|---|---|---|
| CO-OPS station water temperature | 15 stations (section 1.2), 6-min, minutes latency | Data API `product=water_temperature&date=latest`; fetched Westport 11.7 °C | public domain | Harbour/estuary sensors (Astoria, Longview are river water), none at Seattle/Cherry Point; the only open-coast ones are Westport, La Push, Neah Bay, South Beach, Port Orford, Charleston, Crescent City. |
| NDBC buoy SST | catalogued by the buoy agent | NDBC realtime2 feeds | public domain | Reference only. 46029 (Columbia bar), 46041, 46050, 46087 etc. |
| NANOOS shore stations | catalogued by the NANOOS agent | NVS/ERDDAP | varies | Reference only. |
| NOAA Geo-Polar Blended SST (`noaacwBLENDEDsstDNDaily`, day+night, 2019–present; `noaacwBLENDEDsstDaily` night-only 2002–present) | `analysed_sst` °C, 0.05° (5 km) global L4 gap-free, daily; `time_coverage_end` 2026-10-11T12Z when read on 10-13 → about 2 days behind | `https://coastwatch.noaa.gov/erddap/griddap/noaacwBLENDEDsstDNDaily.json?analysed_sst[(last)][(46.0):(46.3)][(-124.3):(-124.0)]` fetched 200 (3 KB; 13.0 °C at 46.025 N -124.325); PNG: `…/noaacwBLENDEDsstDNDaily.transparentPng?analysed_sst[(last)][(41.0):(49.7)][(-126.6):(-122.0)]&.draw=surface&.vars=longitude\|latitude\|analysed_sst&.colorBar=Spectral\|\|\|8\|18\|&.size=400\|500` fetched 200, 27 KB, land transparent (inspected, renders correctly) | metadata `license`: "GHRSST protocol describes data use as free and open" | Inputs are GOES-18/19 ABI, Himawari-9, Metop AVHRR, NOAA-20/21 VIIRS; 5 km blurs the Strait and Puget Sound (odd warm pixels in Hood Canal/south Sound in today's PNG). Also on this server: Coral Reef Watch CoralTemp 5 km (`noaacrwsstDaily`) and its anomaly (`noaacrwsstanomalyDaily`). |
| JPL MUR SST v4.1 (`jplMURSST41`; also `jplMURSST41anom1day`, `jplMURSST41F` °F) | `analysed_sst` °C, 0.01° (1 km) global L4 gap-free, daily; `time_coverage_end` 2026-10-12T09Z (≈1 day behind) | West Coast node `https://coastwatch.pfeg.noaa.gov/erddap/griddap/jplMURSST41.json?…` returned 503 ("Service Unavailable: There was a (temporary?) problem"), `info` 502 Proxy Error, search timed out at 20 s (all 2026-10-13 ~20 Z). UAF mirror `https://upwell.pfeg.noaa.gov/erddap/griddap/jplMURSST41.json?analysed_sst[(last)][(46.0):(46.1)][(-124.2):(-124.0)]` fetched 200 (13 KB, 13.1 °C, 21 s). Same `.transparentPng` syntax works on ERDDAP. | "These data are available free of charge under the JPL PO.DAAC data policy. The data may be used and redistributed for free but is not intended for legal use"; acknowledgement "provided by JPL under support by NASA MEaSUREs program" | 1 km is interpolated, not resolved, inside Puget Sound; a 1-row subset took 21 s on upwell, so request a coarse stride (`[(41):10:(49.7)]`) or a PNG, not the full 1 km window (≈870×460 cells is fine as PNG, large as JSON). West Coast node reliability is an open question. |
| GOES-West ABI SST (`goes_west`, coastwatch.pfeg; `goes_west_Lon0360`) | hourly, 0.02° (~2 km), L3C clear-sky only, "2-6 hour latency"; `time_coverage_end` 2026-10-13T16Z read at 20 Z | `https://coastwatch.pfeg.noaa.gov/erddap/info/goes_west/index.json` fetched 200 after 20.5 s; no data pull attempted (server flaky) | "GHRSST protocol describes data use as free and open" | Cloud gaps most of the year on this coast; use for "latest clear look", not a base layer. |
| OISST v2.1 daily climatology, "normal for this date" | 0.25°, 1991–2020 daily LTM (366 days) and current-year daily means | PSL THREDDS catalog `https://psl.noaa.gov/thredds/catalog/Datasets/noaa.oisst.v2.highres/catalog.html` fetched 200; files `sst.day.mean.ltm.1991-2020.nc`, `sst.day.mean.ltm.1982-2010.nc`, `sst.day.mean.YYYY.nc`; OPeNDAP `https://psl.noaa.gov/thredds/dodsC/Datasets/noaa.oisst.v2.highres/sst.day.mean.ltm.1991-2020.nc` (subset with the `.ascii?sst[day][lat][lon]` form; lon 0–360). NCEI ERDDAP also lists `ncdc_oisst_v2_avhrr_amsr_by_time_zlev_lat_lon` (older). | NOAA public domain | 0.25° cells: only a few ocean cells touch the Strait and none resolve Puget Sound; pick the nearest offshore cell per break. Simpler alternative with the same meaning: Coral Reef Watch 5 km SST anomaly (`noaacrwsstanomalyDaily`, baseline 1985–2012). Download the LTM once (≈1.6 GB global) or subset by OPeNDAP each run (small). |

## 4. Ocean currents and circulation

| Source | What it is | Endpoint and fetch | Cadence | Terms | Caveats |
|---|---|---|---|---|---|
| **SSCOFS** Salish Sea and Columbia River OFS (NOAA CO-OPS, operational) | FVCOM, 239,734 nodes / 433,410 elements, 10 sigma layers, ~100 m shoreline, 500 m deep Puget Sound/Georgia, up to 10 km on the shelf, Columbia 100–200 m to Bonneville; water level, currents, T, S | AWS `https://noaa-nos-ofs-pds.s3.amazonaws.com/?list-type=2&prefix=sscofs/netcdf/2026/10/10/` fetched 200: `sscofs.t03z.20261010.fields.f000.nc … f0HH.nc` (info page: AWS carries the last 2 years with a 3-day delay; `sscofs.20261013/` under the old date-prefix layout is empty). NOMADS `https://nomads.ncep.noaa.gov/pub/data/nccf/com/nosofs/prod/` fetched 200, has `sscofs.20261012/`, `sscofs.20261013/` (latest 24 h). CO-OPS THREDDS `https://opendap.co-ops.nos.noaa.gov/thredds/catalog.html` (31 days). File names `sscofs.tCCz.YYYYMMDD.fields.[n\|f]HHH.nc`, `…stations.[nowcast\|forecast].nc`. Data API `product=ofs_water_level` gives modelled water level at stations. | 4 cycles/day (03, 09, 15, 21 Z), nowcast 6 h + forecast 72 h, hourly fields, 6-min station series | NOS disclaimer: "computer-generated forecast guidance", water levels "accurate to within 6 inches 90% of the time" | Unstructured grid: an hourly 3-D field file is large (not downloaded; expect 100 MB class) and needs a node-to-raster step. For a free-tier job, the stations file (surface current at named points) or NOMADS-only hourly pull of one forecast file per run is the realistic path. Replaces the old CREOFS. |
| **WCOFS** West Coast OFS (operational) | ROMS, whole US West Coast to >1000 km offshore; water level, currents, T, S | AWS `prefix=wcofs/netcdf/2026/10/10/` fetched 200: `wcofs.t03z.20261010.2ds.f001.nc …` (2-D surface files, small); NOMADS `wcofs.20261013/` present; `wcofs_da/` prefix empty for 10 Oct | once a day (03 Z) per the operational page; developmental page says 4/day | same NOS disclaimer | ~4 km, no Puget Sound/Strait detail; use for the shelf (upwelling fronts, Columbia plume). The `2ds` files are the ones to subset. |
| **RTOFS** global (NCEP) | HYCOM 1/12° (~8 km), surface u/v, SST, SSH | NOMADS `https://nomads.ncep.noaa.gov/pub/data/nccf/com/rtofs/prod/rtofs.20261013/` fetched 200 (558 .nc files, `rtofs_glo_2ds_f000_prog.nc`, `_diag.nc`, `_ice.nc`, forecast hours to day 8); AWS `https://noaa-nws-rtofs-pds.s3.amazonaws.com/?list-type=2&prefix=rtofs.20261013/rtofs_glo_2ds` fetched 200 (diag and ice 2ds files seen; listing truncated at 50 keys before `_prog`), plus the raw `archs/archv` binaries | daily 00 Z, hourly 2-D surface fields | NOAA public domain | Coarser than WCOFS; global file is ~100 MB+ per hour even for 2-D; needs `xarray`+`netCDF4` subsetting; no inland-water value. Keep as a fallback only. |
| HYCOM GOFS 3.1 (`tds.hycom.org`, GLBy0.08/expt_93.0) | same model family, 1/12° | root catalog `https://tds.hycom.org/thredds/catalog.html` fetched 200 and lists `catalogs/GLBy0.08/expt_93.0.html`; the guessed FMRC path 404'd | daily | HYCOM consortium, free | Read about only; duplicates RTOFS. |
| OSCAR (NASA/ESR, 0.25°, 5-day lag) | surface geostrophic+Ekman currents | PO.DAAC only (Earthdata login required; not on coastwatch.noaa.gov or upwell ERDDAP, both searches returned no match) | daily | NASA open but login-gated | Excluded by the no-registration rule; too coarse anyway. |
| LiveOcean (UW, Parker MacCready) | ROMS, 3-day forecasts, surface T/S/currents, Puget Sound/Willapa/Grays submodels | `https://faculty.washington.edu/pmacc/LO/LiveOcean.html` (read): links to NANOOS NVS viewer and in-house movies; `data_access.html` (read) lists only the cas7_t0_x4b hindcast (2012-10-07 to 2025-06-20) on `https://s3.kopah.uw.edu/cas7-t0-x4b/…` (780 MB monthly files, 13–17 GB surface files) and says that version "has been replaced with another version of the model for the daily forecasts" without naming a forecast endpoint. NANOOS THREDDS `https://nanoos.ceoas.oregonstate.edu/thredds/catalog/catalog.html` timed out at 20 s today. | daily | Quoted: "This is an experimental product and intended for research use only." "Any use of these forecasts is done at the risk of the user." | No public forecast file endpoint found; treat as a link-out or ask the NANOOS agent whether NVS exposes a tile/WMS layer. |
| Columbia River bar inputs | NWS bar forecast text; USGS discharge; CO-OPS gauges | api.weather.gov CWF for PQR: `https://api.weather.gov/products/types/CWF/locations/PQR` (list, 200) → latest `@graph[0]["@id"]` → `productText`; today's issue 08:30 Z contains zone `PZZ210 Columbia River Bar`: ".IN THE MAIN CHANNEL… .GENERAL SEAS…5 ft subsiding to 3 to 4 ft Wednesday morning. .FIRST EBB…Ebb current of 3.54 kt at 647 AM Tuesday. Seas 5 ft. .SECOND EBB…Strong ebb current of 5.61 kt at 658 PM Tuesday". SEW CWF (200) zone `PZZ110 Grays Harbor Bar`: "Combined seas 3 to 5 ft. Bar conditions light. Maximum ebb currents will occur around 645 AM Tuesday, 645 PM Tuesday…". USGS 14246900 Columbia River at Port Westward (Beaver Army Terminal) `https://waterservices.usgs.gov/nwis/iv/?format=json&sites=14246900&parameterCd=00060,00065` fetched 200: 270,000 ft³/s, gage 1.89 ft at 2026-10-13 11:50 PDT, qualifier P. CO-OPS 9440581 Cape Disappointment (WL only), 9439040 Astoria (WL, WT, wind, AT). | CWF ~4 issues/day; USGS 15-min; CO-OPS 6-min | public domain (api.weather.gov needs a User-Agent header) | USCG bar restrictions: no feed. NWS PQR `weather.gov/pqr/AllBars` (read) is only a phone list (Cape Disappointment 206-815-6708 style numbers vary by source) with "The information provided reflects conditions at the time the bar was observed and may not reflect current conditions." USCG D13 `pacificarea.uscg.mil/…/-dpw` returned 403 Access Denied to a generic client (2026-10-13). USGS WaterServices IV is the legacy endpoint (still answering); the OGC `api.waterdata.usgs.gov` is the successor. |
| CUTI / BEUTI upwelling indices (NOAA SWFSC ERD) | CUTI m² s⁻¹ (vertical transport), BEUTI mmol m⁻¹ s⁻¹ (nitrate flux), 1° latitude bins 31–47 N | `https://upwell.pfeg.noaa.gov/erddap/griddap/erdCUTIdaily.json?CUTI[(last)][(41.0):(47.0)]` fetched 200: 2026-09-27 values 41 N 1.86, 42 N 2.223, 43 N 1.947, 44 N 1.157, 45 N 1.099, 46 N 0.705, 47 N 0.221; `erdBEUTIdaily` same shape; `.csv`/`.nc` work with the same query. `oceanview.pfeg.noaa.gov/products/upwelling/cutibeuti` is a JS app with no scrape-able links. | daily series, but `time_coverage_end` 2026-09-27 on 2026-10-13 (≈2-week lag, batch updates) | quoted: "The data may be used and redistributed for free but is not intended for legal use, since it may contain inaccuracies." | Stops at 47 N (Washington north of Grays Harbor and all of BC uncovered). Good for a "upwelling this week → cold water" explainer, not for today. |

## 5. Hazards and water quality

| Source | What | Endpoint and fetch | Cadence | Terms | Caveats |
|---|---|---|---|---|---|
| NWS Surf Zone Forecast (SRF) | Surf height, offshore swell (height/period/dir), weather, high temp, wind, tides, sunrise/sunset per beach zone, today + tomorrow | `https://api.weather.gov/products/types/SRF/locations` fetched 200: West Coast offices are **PQR, MFR, EKA** (SEW returned an empty `@graph`, so no SRF for the WA coast north of Long Beach, the Strait or Puget Sound). `…/SRF/locations/PQR` → 7 recent products, latest 2026-10-13 13:02 Z `FZUS56 KPQR … SURF ZONE FORECAST`, zones WAZ201 Long Beach WA, ORZ101 Seaside/Cannon Beach, ORZ102 Manzanita/Rockaway/Pacific City, ORZ103 Lincoln City; sample ".TODAY… Surf Height…5 to 7 ft. Offshore Swell…West 4 ft at 14 seconds." Header: "This is an automated product." | 1–2 issues/day | public domain; api.weather.gov requires a `User-Agent` | PQR's SRF has no rip-current-risk line; rip risk arrives as a `Rip Current Statement` alert instead. MFR (Brookings–Florence) and EKA (Crescent City) SRFs not fetched. |
| NWS alerts (beach hazards, sneaker waves, high surf, rip currents, coastal flood, marine, tsunami) | GeoJSON alerts with `event`, `headline`, `description`, `areaDesc`, `geocode.UGC` | `https://api.weather.gov/alerts/active?area=WA,OR&status=actual` fetched 200 (only a Boise frost advisory today). Event filter confirmed: `…/alerts/active?event=Beach%20Hazards%20Statement,Rip%20Current%20Statement,High%20Surf%20Advisory&status=actual` returned 3 LA-area Beach Hazards Statements (200). `/alerts/types` (200) lists the coastal names: Beach Hazards Statement, High Surf Advisory/Warning, Rip Current Statement, Coastal Flood Advisory/Statement/Warning/Watch, Small Craft Advisory, Gale Warning/Watch, Storm Warning, Hurricane Force Wind Warning, Special Marine Warning, Marine Weather Statement, Tsunami Advisory/Warning/Watch. | real time | public domain | Sneaker-wave and "high surf/strong currents" warnings on this coast are issued as **Beach Hazards Statement**; there is no separate sneaker-wave event. Use `zone=` with the WAZ/ORZ/PZZ codes above to pin to the map. |
| NTWC tsunami feeds | Latest NTWC message as Atom and CAP 1.2 | `https://www.tsunami.gov/events/xml/PAAQAtom.xml` fetched 200 (today: "Tsunami Information Statement Number 1", Mid-Atlantic Ridge event, geo:lat/long, links to travel-time and energy maps); `https://www.tsunami.gov/events/xml/PAAQCAP.xml` fetched 200 (`<sender>ntwc@noaa.gov</sender>`, `<status>Actual</status>`). PTWC equivalents are `PHEBAtom.xml`/`PHEBCAP.xml`. | event-driven; feed holds the most recent message only | public domain | Pair with `api.weather.gov/alerts?event=Tsunami Warning` which carries the polygon/zones. |
| WA swimming-beach bacteria advisories (Ecology/DOH BEACH) | Beach status, action type, description | Map app `https://gis.ecology.wa.gov/portal/apps/webappviewer/index.html?id=e32edf4767184fd88e4ce2aa367ffd5c` → web map item `74158b4e…` → MapServer `https://gis.ecology.wa.gov/serverext/rest/services/GIS/CoastalAtlas/MapServer` (507 layers, fetched 200). Layer 8 "Beach status" query `…/MapServer/8/query?where=1%3D1&outFields=*&returnGeometry=false&f=json` fetched 200: 12 rows, fields BeachID, BeachActionTypeCode (`PERM_ADVISORY` today), ActionDescription, CountyName, BeachName (e.g. Windjammer Park, Walker County Park, Thea Foss Waterway). Layer 7 "Beaches" (geometry) rejected the same query form (400, needs a geometry or different params). | weekly in season (Memorial Day–Labor Day), otherwise static | no terms on the service or page | Off-season now, so only permanent advisories appear. Join layer 8 to layer 7/9 geometry by BeachID. |
| OR beach bacteria advisories (OHA Beach Monitoring Program) | Current advisories, 33 monitored beaches | `https://www.oregon.gov/oha/PH/HEALTHYENVIRONMENTS/RECREATION/BEACHWATERQUALITY/Pages/status.aspx` (read): static HTML tables (County, Beach, Status) per region, "The 2026 monitoring season has ended", all beaches NO MONITORING; GovDelivery subscription `https://public.govdelivery.com/accounts/ORHA/subscriber/new?topic_id=ORHA_190`; EPA BEACON `http://watersgeo.epa.gov/beacon2/reports.html` for history | May–September, weekly | state web page, no stated terms | No feed; scraping a small HTML table is feasible but check the site's terms first; in-season only. |
| WA shellfish biotoxin closures and beach status (DOH) | Biotoxin closure zones by species; recreational beach open/closed; Vibrio advisories | ArcGIS `https://services8.arcgis.com/rGGrs6HCnw87OFOT/ArcGIS/rest/services/` (services list fetched 200). `Biotoxin_Closure_Zones/FeatureServer/0` (fetched 200: fields C_ZNAME, ZONEID, SPECIEDESCRIPTION; `cacheMaxAge` 30 s; last edit 2026-10-13 11:02 Z; `where=SPECIEDESCRIPTION<>'None'` count = 88 zones closed for at least one species today). `Recreational_Shellfish_Beaches/FeatureServer/0` (502 beaches; fields BEACHNAME, COUNTYNAME, FINALSTATUS Open/Closed/Unclassified, DOHDFWStatus, REASONDESCRIPTION, ALLSPECIEDESCRIPTIONS, Vibrio, UPDATED 2026-10-13 03:01 Z). Also `Shellfish_Vibrio_Advisory_Areas_view`, `Shellfish_Advisory_Areas`, `Shellfish_Polluted_Areas_view`. Public front end `https://fortress.wa.gov/doh/biotoxin/biotoxin.html`. | hourly when changed (catalogue note); edits seen today | public ArcGIS layer, `copyrightText` empty; DOH is the authority, hotline is official | `f=geojson` supported; 2000-record cap per query. |
| OR shellfish biotoxin closures (ODA) | Zone status by species | ODA page `https://www.oregon.gov/oda/food-safety/shellfish/Pages/shellfish-closures.aspx` (read, updated 10/2/2026): razor clams **closed from the Washington border to the California border for domoic acid**; mussels, bay clams, crab open; dashboard `https://geo.maps.arcgis.com/apps/dashboards/2055b8d586a7496b8bd7362db231d936` → web map `e6e21740…` → feature layer `https://services.arcgis.com/uUvqNMGPm7axC2dD/arcgis/rest/services/ODA_FoodSafety_RecreationalShellfishBiotoxinClosureStatus2017_ViewLayer/FeatureServer/0` query fetched 200: 25 zones, fields ClosureName, Status (e.g. "Pistol River to Cape Blanco" `Closed_Razor`). PDFs `CurrentBiotoxinData.pdf`, `CurrentCrabBiotoxinData.pdf`. Hotline 1-800-448-2474. | as results arrive (weekly-ish) | public ArcGIS layer; ODA says the hotline is "the best source for up-to-date" status | The `maps.oda.oregon.gov` MapServer found by search is only the label basemap; the status layer above is the one to use. |
| WA razor clam / domoic acid (WDFW, ORHAB, NOAA PNW HAB Bulletin) | Dig status, per-beach domoic acid charts | `https://wdfw.wa.gov/fishing/shellfishing-regulations/razor-clams` (read; 2026-10-06: season "postponed until further notice", toxin bloom "moving up the coast", DOH needs two clean samples 7–10 days apart); `https://wdfw.wa.gov/fishing/basics/domoic-acid/levels` (read): links to six per-beach chart pages, no table, no feed; `…/razor-clams/domoic-acid` 404. ORHAB `orhab.uw.edu` bulletins and the NOAA PNW HAB Bulletin are PDFs/pages, no feed found. | weekly | state pages | Use the DOH ArcGIS beach layer (above) as the machine-readable proxy; link WDFW for digs. |
| WA Ecology spills | Spill incidents map | `https://ecology.wa.gov/spills-incidents-in-washington` 301 → `https://apps.ecology.wa.gov/coastalatlas/storymaps/spills/spills_sm.html` → Experience Builder `https://gis.ecology.wa.gov/portal/apps/experiencebuilder/experience/?id=591270509d254f189fb63d4c2d0af340`; app config fetched (104 KB) but its data-source item `e2cf47bd…/data` returned a PNG thumbnail, not JSON, so the layer URL was not recovered | unknown | none stated | Low value for a surf map; skip unless a layer URL turns up. |

## What to use first (ranked)

1. **CO-OPS tide predictions (`predictions`, `interval=hilo`, MLLW, metric) for all 230 stations, refreshed daily**, and the
   24 observed water-level/water-temperature stations every 15 min. Zero cost, public domain, proven today, and it is the
   number every surfer and kiter checks first. Cache the 2 MB station list in the repo.
2. **CO-OPS current predictions (`currents_predictions`, `interval=MAX_SLACK`)** for the ~25 named passages (section 1.5):
   slack/max tables are exactly what kiters at Deception Pass, Admiralty Inlet and the Narrows want; one request per
   station per day. Show cm/s converted to knots and the bin depth.
3. **api.weather.gov alerts + SRF (PQR, MFR, EKA) + CWF bar zones (PZZ210, PZZ110)**: already the site's data model
   (JSON, zones), gives sneaker-wave/high-surf/rip statements, the surf-height forecast and the only public Columbia
   and Grays Harbor bar forecasts, including ebb timings.
4. **Geo-Polar Blended SST 5 km from coastwatch.noaa.gov** as a transparent PNG overlay plus a JSON point sample per
   break; swap in **MUR 1 km** (upwell mirror) once the fetch time is acceptable, and **CRW anomaly** for "vs normal".
5. **CHS IWLS `wlp-hilo` (and `wlo` for the 27 live stations, `wcp1-events` for the passes)** for the BC side, after
   the licence question is settled (open question 1). The API itself is the easiest of the lot.
6. **WA DOH and ODA biotoxin/beach ArcGIS layers** as `f=geojson` once an hour: tiny, authoritative, and currently
   newsworthy (coast-wide razor clam closure).
7. **NTWC CAP feed** every 15 min (one 5 KB file) alongside the tsunami alert events.
8. **CUTI daily** (one 500 B request) for an upwelling indicator on the OR/WA coast.
9. **WCOFS `2ds` surface files from AWS** for a shelf current/temperature layer; **SSCOFS** only if a station file or
   a single-layer subset proves small enough for a 15-minute Actions job.
10. RTOFS/HYCOM as fallback only; LiveOcean and USCG bar restrictions as links.

## Open questions

1. **CHS licence.** The IWLS licence forbids "derivative products for commercial purposes" and requires a "not to be
   used for navigation" notice and the CHS attribution line. A free public site is non-commercial, but ask CHS
   (`chsinfo@dfo-mpo.gc.ca`) or confirm whether the Open Government Licence applies to API output before showing BC
   tides; until then show the two notices verbatim.
2. **CO-OPS real-time current meters** (cp0101, qr0401, qr0501) returned no data via the API today. Are they offline,
   or served only through the CDATA web plots? Re-test in a week; if dead, drop "live currents" from the plan.
3. **West Coast ERDDAP node reliability** (`coastwatch.pfeg.noaa.gov` 502/503/timeouts today). Is `upwell.pfeg.noaa.gov`
   an acceptable primary for MUR, given 20 s responses, or should MUR be a nightly job writing a PNG to R2?
4. **SSCOFS payload size.** Not downloaded; need one `fields.f001.nc` and one `stations.forecast.nc` size check before
   committing to it in Actions.
5. **Subordinate tide stations:** display hi/lo only (no curve), or interpolate a cosine curve between hi/lo for the
   144 type-S stations? CO-OPS does not provide 6-min series for them.
6. **Surf Zone Forecast gaps:** no SRF for the WA coast north of Long Beach, the Strait or Puget Sound; MFR/EKA SRFs
   not yet sampled. Confirm the MFR zone list (Brookings, Gold Beach, Bandon, Coos Bay, Florence).
7. **Oregon beach bacteria page** is HTML only and in-season only; decide whether to scrape the table (check site terms)
   or link out.
8. **CUTI stops at 47 N** and lags two weeks; is it worth a layer at all, or a text indicator only?
9. **NDBC/NANOOS SST** at the actual breaks (46029, 46041, 46050, 46087, Neah Bay, La Push, Westport) is the other
   agent's table; agree a single "water temperature at my break" precedence: buoy > CO-OPS gauge > MUR > Blended.
10. **USGS WaterServices** legacy endpoint is slated for replacement by `api.waterdata.usgs.gov`; note the date when it
    stops answering.

## Appendix: fetch log (2026-10-13, all with User-Agent `coastal-research/0.1`, 20 s timeout)

| Host | Requests | Outcome |
|---|---|---|
| api.tidesandcurrents.noaa.gov | 5 metadata lists, 4 per-station metadata, 14 Data API | all 200; "No data" for currents meters and conductivity |
| api-iwls.dfo-mpo.gc.ca | 9 | 200 except two guessed ids (404 JSON) |
| coastwatch.noaa.gov/erddap | 7 | all 200 (searches 404 when no match) |
| coastwatch.pfeg.noaa.gov/erddap | 5 | 503, 502, timeout, 404, then 200 after 20 s |
| upwell.pfeg.noaa.gov/erddap | 7 | 200 (3–21 s) |
| api.weather.gov | 10 | all 200 |
| noaa-nos-ofs-pds / noaa-nws-rtofs-pds (S3) | 9 | all 200 |
| nomads.ncep.noaa.gov | 4 | all 200 |
| tsunami.gov | 2 | 200 |
| waterservices.usgs.gov | 1 | 200 |
| psl.noaa.gov, ncei.noaa.gov, tds.hycom.org | 4 | 200 (HYCOM sub-catalog guesses 404) |
| services8.arcgis.com (WA DOH), services.arcgis.com / arcgis.com (ODA), gis.ecology.wa.gov, maps.oda.oregon.gov | 14 | all 200 |
| pacificarea.uscg.mil | 1 (+1 via page reader) | 403 |
| nanoos.ceoas.oregonstate.edu | 1 | timeout |
