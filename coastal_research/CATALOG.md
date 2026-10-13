# Coastal section: data catalogue and recommended first build (2026-10-13)

Six research agents fetched every source below on 2026-10-13 (generic User-Agent, 20 s timeouts, no accounts, no
tokens from pages). Detail, station tables, quoted terms and fetch logs are in the per-topic files:
`waves_buoys.md`, `tides_currents_sst.md`, `wind.md`, `nanoos_ioos.md`, `webcams.md`, and the gap analysis and
draft spot table in `user_needs.md`. Nothing here has been built or decided; Chris decides the open questions at the end.

Window: lat 41.0-49.7 N, lon -126.6 to -112.5 (Brookings to Tofino, the Strait, Puget Sound, San Juans; the Gorge as an annex).

## 1. Sources by what the user wants

| Want | Best free source | Coverage in window | Cadence / latency | Terms | Caveat |
|---|---|---|---|---|---|
| Buoy obs (Hs, period, dir, SST, wind) | NDBC `latest_obs.txt` + per-buoy `.spec` | 78 active stations, 20 with waves | 5 min file; waves hourly (:50), spec 30 min | public domain | 3 m buoys show no wave height in `latest_obs`; take `.spec`. 31 dead stations still in the station table |
| Swell split (swell vs wind wave) | NDBC `.spec` (8 buoys); CDIP ERDDAP `wave_agg` (6 Waveriders) | Angeles Pt, Grays Harbor, Clatsop, Astoria Canyon, Tillamook, Umpqua | 30 min | CDIP: "redistributed and used without restriction", credit asked | CDIP values overwrite the NDBC relay rows |
| Inshore waves at La Push / Quinault | NANOOS ERDDAP Backyard Buoys (6 Sofar Spotters) | 1 live today, others seasonal | ~1 h | **CC BY-NC 4.0** (Quileute Tribe / Quinault Nation) | non-commercial only, credit required |
| BC buoys | ECCC Datamart SWOB-ML (4600206 La Perouse, 4600146, 4600304) | WCVI and Strait | hourly | ECCC licence, attribution line | NDBC relay drops direction and shows a wrong period |
| Wave forecast raster | GFS-Wave `wcoast.0p16` on AWS (3 swell partitions) | whole window, 10 days | 4 runs/day, ~3.5 h after | public domain | ~270 KB/step, byte-range by `.idx` like HRRR smoke |
| Nearshore wave forecast | NWPS CG1 for SEW/PQR/MFR (NOMADS only) | WA/OR surf zones at 0.5-1.8 km | on demand, 2-6 cycles/day | public domain | 15 MB/run, NOMADS flaky; `filter_wrnwps.pl` subsets |
| Surf-zone text forecast | NWS SRF (PQR, MFR, EKA) via api.weather.gov | Long Beach WA to Brookings | daily 06:00 | public domain | **SEW issues none**: no SRF for north WA coast, Strait, Sound |
| Tides | NOAA CO-OPS Data API | 24 real-time WL (15 water temp, 12 wind), 230 prediction stations | 6 min obs; predictions daily | public domain, attribution asked, throttles abusers | 144 subordinate stations give hi/lo only |
| Tidal currents | CO-OPS `currents_predictions` MAX_SLACK | 220 stations: Admiralty, Deception Pass, Narrows, Rich Passage, San Juan Channel, Grays Harbor, Columbia entrance | daily | public domain | **no live current meter works anywhere in the window** (Cherry Point, Yaquina CURBY all empty) |
| BC tides and passes | CHS IWLS API (no key) | 124 stations, 27 live: Tofino, Ucluelet, Bamfield, Port Renfrew, Victoria, Point Atkinson | 1 min obs | **"shall not be used in the purpose of navigation"; bars commercial derivatives** | needs Chris's call; no water temp |
| Water temperature at the break | CO-OPS water temp (15), NDBC SST, Cha'ba, Backyard Buoys; satellite: NOAA Geo-Polar Blended 5 km (ready PNG), MUR 1 km (server flaky), CRW anomaly for "vs normal" | whole window | daily, ~2 d latency (satellite) | NOAA free and open | cloud gaps on GOES; MUR's main node was down today |
| Ocean currents | HF radar 6 km totals via NDBC THREDDS NCSS; WCOFS `2ds` surface files (AWS); SSCOFS Salish Sea (large) | HF radar today: 41.3-45.9 N only; WA intermittent | hourly, 2-3 h latency | public domain, HFRNet credit | real layer for OR; WA cells appear and vanish. RTOFS fallback. LiveOcean research-only, link out |
| Wind obs at the water | CO-OPS wind (16 tide stations), api.weather.gov (ASOS + CWOP + ODOT RWIS), NDBC C-MAN, ECCC SWOB-ML (Race Rocks, Pt Atkinson), NANOOS Sound buoys (ORCA, PISCES, Se'lhaem), Cha'ba | coast, Strait, Sound, west/mid Gorge | 6 min to 1 h | open | **no free sensor in the east Gorge** (Rufus, Arlington, Doug's); WSDOT RWIS needs an emailed access code |
| Wind forecast | NDFD wspd/wdir/wgust (already pulled), HRRR via NOMADS subregion (813 KB/h for u, v, gust, MSLP), ECCC HRDPS 2.5 km via GeoMet WCS (332 KB/var-hour), NBM, ECMWF open data | whole window | hourly | NOAA public domain; ECCC and ECMWF attribution | iKitesurf/WeatherFlow, Windy, Windguru, Windfinder all paid or forbid app use |
| Marine zone forecasts and advisories | api.weather.gov CWF (26 PZZ zone ids listed), `/alerts/active?area=PZ`; ECCC marine XML/GeoJSON | all | hourly | open | list PZ zones by id; the zones endpoint filters fail |
| Hazards | NWS alerts: Beach Hazards Statement (sneaker waves), High Surf, Rip Current Statement, Tsunami; NTWC CAP/Atom | all | 15 min | open | USCG bar restrictions have no feed; CWF PZZ210/PZZ110 carry bar seas and ebb timings |
| Water quality | WA DOH ArcGIS biotoxin closure zones + 502 rec shellfish beaches; ODA zone-status layer; WA Ecology beach status; OHA is HTML (season ended) | WA + OR | hourly is fine | public | razor clams closed coast-wide OR and WA digs postponed (domoic acid, 2026-10-02/06) |
| Upwelling | CUTI/BEUTI daily on upwell ERDDAP | 1-degree bins to 47 N | 2-week lag | public | indicator only |
| Webcams | 18 new YouTube live streams + 6 id refreshes (Ross Bay kite cam, Seaside beach, Port Angeles, Dungeness, Hood Canal, Port Ludlow, Orcas, Tofino Crystal Cove, Ucluelet Big Beach); 2 stills (Yaquina bar USCG, Point Roberts) | gaps: La Push, Neah Bay, Long Beach WA, Alki, Golden Gardens, Jetty Island, Sooke | hourly job | YouTube API path as now | 5 existing cams stale or 404 (Kalaloch URL moved, Cannon Beach CBCC dead); owner asks listed |

## 2. What was missing from the original six (from `user_needs.md`)
1. Swell period and direction per swell train, not just height.
2. Tide stage and trend at session time (rising/falling, hours to turn).
3. Daylight window (the site's sun engine already exists).
4. Water temperature with a wetsuit band; upwelling drop after north wind.
5. Hazards: sneaker waves, high surf, rips, tsunami, bar, lightning.
6. Water quality: biotoxin and beach closures, King County CSO status.
7. Seasonal closures and passes (snowy plover dry-sand closures Mar 15-Sep 15 ban kites; Makah, Discover, Parks Canada).
8. Kiter specifics: Portland-The Dalles gradient, gust factor, thermal onset, fog.
9. Logistics: coast roads and ferries (partly in the site).

Organising idea: raw layers the user reads (buoys, tide/current stations, wind stations, cams, SST, model fields,
alert polygons) plus a static spot table (54 surf, 38 kite drafted, each marked documented or lore) that the site
evaluates for a chosen time as a transparent checklist with the raw numbers. No star ratings or rating words
(Surfline's and Windguru's). A 48 h session slider (Sun & shade idiom) shading daylight, tide curve, spot colours.
Seasonal defaults: surf Oct-Apr, kite May-Sep.

## 3. Recommended first build (one hourly module per source, `data/coastal_*.js`, same shape as the other layers)
1. **Buoys**: NDBC `latest_obs` + 8 `.spec` + CDIP `wave_agg` + Cha'ba + ECCC SWOB (every 15 min in capture, or hourly). One marker layer: Hs, period, swell split, direction, SST, wind.
2. **Tides and currents**: CO-OPS hi/lo predictions daily for 230 stations, 6-min obs + water temp for the 24 live ones, MAX_SLACK current predictions for ~25 named passages. Tide curve and "rising/falling, turns in N h" in the popup.
3. **Wind at the water**: CO-OPS wind + api.weather.gov coastal ids + ECCC SWOB + NANOOS Sound buoys into the existing station layer or a coastal one; NDFD/HRRR timelines per spot.
4. **Hazards and text**: alert events already flow; add SRF/CWF text per zone and NTWC.
5. **SST overlay**: Geo-Polar Blended 5 km PNG now, MUR later.
6. **Webcams**: the ranked YouTube additions and two stills; fix Kalaloch; prune dead ones.
7. **Spots** (after Chris reviews the draft table): evaluated checklist per spot.
Later: GFS-Wave swell raster, HF radar currents, HRDPS, biotoxin layer, NWPS, WCOFS.

## 4. Open questions for Chris
1. CHS licence (no navigation use, no commercial derivatives): show BC tides or link out?
2. Backyard Buoys CC BY-NC: acceptable on a public, non-commercial page with credit?
3. Gorge in a "coastal" section, as an annex?
4. Spots-with-checklist or raw layers only for the first release?
5. Request the WSDOT RWIS access code (free, by email)?
6. Open-Meteo marine (non-commercial CC BY): skip, since GFS-Wave covers it?
7. Webcam owner asks worth sending: City of Westport (3 cams), Lane County Harbor Vista, Whidbey Telecom Double Bluff, Spyglass/Otter Crest, Newport Chowder Bowl; WebCOOS and Windy webcam registrations.
8. Which region(s): pnw only, or also the sierra window's coast (Crescent City is in pnw's window already)?
