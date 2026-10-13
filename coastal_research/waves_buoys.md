# Waves, swell and buoy observations and forecasts: PNW coastal sources

Research for the Coastal section of radar.blackwaterlabs.org (surfers, kiteboarders). Window: lat 41.0-49.7 N, lon -126.6 to -112.5.
Everything below was checked on **2026-10-13 between 19:40 and 20:30 UTC** with Python `urllib`, User-Agent `coastal-research/0.1`, 20 s timeout, unless marked "read about only". Raw responses are in the session scratchpad (`dl/`), not in the repo.

## Summary

- **Observations.** NDBC is the one-stop relay: `latest_obs.txt` (one 100 KB file, refreshed about every 5 min) carries every station in the window, including the CDIP Waveriders, the ECCC Canadian buoys, OOI, NANOOS and NOS gauges. 78 active NDBC stations fall in the window; 20 of them report waves. Swell/wind-wave partitions need the per-station `realtime2/<ID>.spec` file (NDBC moored buoys and CDIP only; ECCC buoys have no `.spec`).
- **Surprises.** (1) `latest_obs.txt` shows `WVHT=MM` for every NDBC 3-m buoy because their latest row is a 10-minute met-only report; wave rows come hourly at :50 in `<ID>.txt` and every 30 min in `<ID>.spec`. Read the `.spec` file, not `latest_obs`, for those eight buoys. (2) ECCC buoys relayed through NDBC lose wave direction and carry an odd period (La Perouse Bank: NDBC says DPD 7 s, ECCC's own SWOB-ML record for the same hour says peak period 13.3 s, peak direction 264 deg). Use MSC Datamart SWOB-ML for the Canadian buoys. (3) Neah Bay 46087's spectral file has multi-hour gaps (nothing between 12 Oct 08:40 and 13 Oct 17:10 UTC). (4) Clatsop Spit 46243/CDIP 162 was 2-3 h stale (last 16:30-17:30 UTC) while its siblings were current.
- **CDIP** has six live PNW Waveriders (036 Grays Harbor, 162 Clatsop Spit, 179 Astoria Canyon, 270 Tillamook Bay South Jetty, 139 Umpqua Offshore, 248 Angeles Point in the Strait). The three PacWave/NLR stations off Newport (277, 278, 280) are listed by NDBC but report nothing. ERDDAP tabledap gives all six in one CSV request (`wave_agg`, licence attribute "These data may be redistributed and used without restriction").
- **Forecasts.** GFS-Wave `wcoast.0p16` on AWS (`noaa-gfs-bdp-pds`) is the cheapest grid: 267 KB per hourly step, 19 fields including three swell partitions, 25-50 N / 210-250 E, four runs a day; one f024 file was downloaded and read with cfgrib. NWPS (SWAN) for SEW/PQR/MFR is on NOMADS only, 15 MB per CG1 GRIB2, on demand 2-6 runs/day, with a `filter_wrnwps.pl` subsetter. ECCC's RDWPS (2.5 km, 48 h) and GDWPS (0.25 deg, 240 h) publish one variable per file (1.8 MB / 1.1 MB) on Datamart with first- and second-swell partitions.
- **Text forecasts.** api.weather.gov serves the Surf Zone Forecast (SRF) for PQR (Long Beach to Lincoln City) and MFR (Reedsport to Brookings); SEW issues no SRF. Coastal Waters Forecasts (CWF) exist for all three. Gridpoint JSON has `waveHeight` and `wavePeriod2` but the swell-partition fields are empty for SEW. ECCC marine forecasts (Juan de Fuca, West Coast Vancouver Island South, Strait of Georgia, Haro Strait) are XML on Datamart and GeoJSON on GeoMet OGC-API.
- **Do not use:** Surfline (terms forbid any automated access; Magicseaweed redirected to Surfline on 2023-05-15). **Usable with care:** Open-Meteo Marine API (CC BY 4.0, free only for non-commercial use, no key; it worked).

## 1. NDBC (National Data Buoy Center)

**Endpoints (all fetched 2026-10-13, HTTP 200):**

| product | URL | format / notes |
|---|---|---|
| Active station list | `https://www.ndbc.noaa.gov/activestations.xml` | XML, 1,354 stations, attrs id/lat/lon/name/owner/pgm/type/met/currents/waterquality/dart (no "waves" attribute). `created="2026-10-13T19:40:06UTC"`. Refreshed ~5 min as needed. |
| Station table | `https://www.ndbc.noaa.gov/data/stations/station_table.txt` | pipe-delimited; includes disestablished stations and hull type; the NOTE column explains outages. |
| Map JSON with status | `https://www.ndbc.noaa.gov/ndbcmapstations.json` | `status` "E" (established) / "D" (disestablished); 109 entries in the window incl. 31 disestablished. |
| Latest obs, all stations | `https://www.ndbc.noaa.gov/data/latest_obs/latest_obs.txt` | 103 KB, 869 lines, columns STN LAT LON YYYY MM DD hh mm WDIR WSPD GST WVHT DPD APD MWD PRES PTDY ATMP WTMP DEWP VIS TIDE; `MM` = missing. The NDBC Web Data Guide says it is "updated approximately every 5 minutes, so it would be a good source of data if you are interested in ... observations from multiple stations". |
| Standard met, 45 days | `https://www.ndbc.noaa.gov/data/realtime2/<ID>.txt` (ID upper-case) | 46050.txt was 609 KB, Last-Modified 19:30:46Z; rows every 10 min, WVHT/DPD/APD/MWD only on the :50 row. |
| Spectral summary | `realtime2/<ID>.spec` | columns WVHT SwH SwP WWH WWP SwD WWD STEEPNESS APD MWD; 30-min rows (46050: 18:40, 18:10, ...). Sample 46050 18:40Z: `1.3 1.3 12.9 0.3 3.0 WNW SW SWELL 8.0 290`. 150 KB. Exists for NDBC moored buoys and CDIP Waveriders; **404 for ECCC 46206**. |
| Raw spectra | `realtime2/<ID>.data_spec` (energy density), `.swdir` (alpha1), `.swdir2`, `.swr1`, `.swr2` | 46050.swdir fetched: 1.4 MB, 47 frequency bins 0.033-0.485 Hz, 999.0 = missing. Too big to pull every cycle; not needed for a surf map. |
| Continuous winds | `realtime2/<ID>.cwind` | 10-min winds (read about only). |
| Per-station RSS | `https://www.ndbc.noaa.gov/data/latest_obs/<ID>.rss` | RSS 2.0 with georss, `<ttl>30</ttl>`, HTML description (wind in knots, pressure in inHg/mb, wave height in ft when present). 2 KB. Fine for a popup link; worse than `latest_obs.txt` for parsing. |

**Licence / terms.** NWS disclaimer (https://www.weather.gov/disclaimer): "The information on National Weather Service (NWS) Web pages are in the public domain, unless specifically noted otherwise". NDBC Web Data Guide v2.0 (PDF, `https://www.ndbc.noaa.gov/docs/ndbc_web_data_guide.pdf`, read 2026-10-13): "We also ask that you consider the frequency of the data updates and limit your data request to conserve our bandwidth", and it discourages "developing unique processes (i.e. screen scrape mobile page)". Realtime data "have undergone automated quality control checks" only. Partner-station data (CDIP, ECCC, OOI, NANOOS) keep their owners' acknowledgement wishes (CDIP: see section 2).

**Cadence and latency observed 2026-10-13 ~19:45 UTC.** NDBC 3-m buoys: met rows at 19:10 (35 min old), wave rows at 18:50. CDIP Waveriders: 18:56-19:00 (46243 Clatsop: 17:30). ECCC: 19:00 hourly. OOI 46099/46097 and NANOOS 46119: 17:50-18:50. NOS gauges: 18:36-18:54 (6-min data).

### Station table: every active NDBC station in the window (78)

Source: `activestations.xml` joined to `station_table.txt` and `latest_obs.txt`, all fetched 2026-10-13 19:4x UTC. "reports (now)" is what the latest row carried plus whether a `.spec` file exists ("+spec" = swell/wind-wave split, direction). Times are UTC on 13 Oct. Blank sample = the latest row had `MM` in every wave field.

| id | name | lat | lon | type | owner / group | reports (now) | last obs UTC 13 Oct | notes |
|---|---|---|---|---|---|---|---|---|
| 46146 | Halibut Bank | 49.34 | -123.73 | 3-meter discus buoy | ECCC buoy (relayed) | waves, wind, pres, SST | 19:00 Hs 0.4 m, DPD 3 s, SST 12.6 | ECCC relay; Hs/DPD only |
| 46304 | Entrance To English Bay | 49.3 | -123.36 | 3-meter discus buoy | ECCC buoy (relayed) | waves, wind, pres, SST | 19:00 Hs 0.2 m, DPD 3 s, SST 12.2 | ECCC relay; Hs/DPD only |
| 46303 | Southern Georgia Strait | 49.02 | -123.43 | 3-meter discus buoy | ECCC buoy (relayed) | none | no obs in latest_obs | **offline**: no obs today anywhere |
| chyw1 | 9449424 - Cherry Point, WA | 48.863 | -122.759 | Water Level Observation Network | NOS tide gauge met | wind, pres | 18:54 |  |
| cpnw1 | 9449427 - Cherry Point North Dock Met | 48.863 | -122.758 | Water Level Observation Network | NOS PORTS met | wind | 18:54 wind 1.0 m/s |  |
| cpmw1 | 9449419 - Cherry Point South Dock Met, WA | 48.86 | -122.756 | Water Level Observation Network | NOS PORTS met | wind | 18:54 wind 1.5 m/s |  |
| 46206 | La Perouse Bank | 48.84 | -126 | 3-meter discus buoy | ECCC buoy (relayed) | waves, wind, pres, SST | 19:00 Hs 1.6 m, DPD 7 s, SST 11.4 | ECCC: no .spec (404); SWOB-ML has Tp 13.3 s / dir 264 at 19:05Z while NDBC shows DPD 7 |
| 46118 | Se'lhaem Bellingham Bay | 48.724 | -122.576 | Buoy | NANOOS (relayed) | wind, pres | 18:00 | NANOOS; all fields MM |
| pblw1 | Ploeg Channel, Padilla Bay Reserve, WA | 48.556 | -122.53 | NERRS Water Quality Station | NERRS | WQ | no obs in latest_obs |  |
| frdw1 | 9449880 - Friday Harbor, WA | 48.545 | -123.012 | Water Level Observation Network | NOS tide gauge met | wind, pres | 18:36 wind 1.0 m/s |  |
| pbjw1 | Joe Leary Tidegate, Padilla Bay Reserve, WA | 48.518 | -122.474 | NERRS Water Quality Station | NERRS | WQ | no obs in latest_obs |  |
| bvqw1 | Bayview Channel, Padilla Bay Reserve, WA | 48.496 | -122.501 | NERRS Water Quality Station | NERRS | WQ | no obs in latest_obs |  |
| 46087 | Neah Bay - 6 NM North of Cape Flattery, WA (Traffic Separation Lighted Buoy) | 48.493 | -124.727 | 3-meter discus buoy w/ seal cage | NDBC moored buoy / C-MAN | waves (+spec), wind, pres, SST | 19:10 wind 5.0 m/s, SST 10.4 | `.spec` had a 32 h gap ending 13 Oct 17:10Z; wave rows hourly :50 in .txt |
| pbfw1 | Padilla Bay Farm, Padilla Bay Reserve, WA | 48.464 | -122.469 | NERRS Weather Station | NERRS | wind, pres | 18:30 wind 3.1 m/s |  |
| neaw1 | 9443090 - Neah Bay, WA | 48.367 | -124.614 | Water Level Observation Network | NOS tide gauge met | wind, pres, SST | 18:54, SST 9.5 |  |
| 46088 | NEW DUNGENESS - 17 NM NE of Port Angeles, WA | 48.332 | -123.179 | 3-meter discus buoy w/ seal cage | NDBC moored buoy / C-MAN | waves (+spec), wind, currents | 19:20 Hs 0.1 m, DPD  s | Strait, sheltered; currents too |
| sisw1 | Smith Island, WA | 48.321 | -122.831 | C-MAN Station | NDBC moored buoy / C-MAN | wind | no obs in latest_obs | C-MAN; **no obs** |
| 46267 | Angeles Point, WA (248) | 48.171 | -123.6 | Waverider Buoy | CDIP Waverider (relayed) | waves (+spec), wind, SST, currents | 19:00 Hs 0.3 m, DPD 12 s, MWD 288, SST 9.6 | CDIP 248; currents too |
| ptaw1 | 9444090 - Port Angeles, WA | 48.125 | -123.441 | Water Level Observation Network | NOS tide gauge met | wind, pres, SST | 18:36 wind 1.0 m/s, SST 10.2 |  |
| ptww1 | 9444900 - Port Townsend, WA | 48.111 | -122.76 | Water Level Observation Network | NOS tide gauge met | wind, pres, SST | 18:54 wind 4.1 m/s, SST 12.0 |  |
| 46119 | Cha'Ba La Push | 47.967 | -124.95 | Buoy | NANOOS (relayed) | wind, pres | 17:50 wind 8.0 m/s | NANOOS Cha'Ba; wind only today |
| lapw1 | 9442396 - La Push, WA | 47.913 | -124.637 | Water Level Observation Network | NOS tide gauge met | wind, pres, SST | 18:36 wind 2.1 m/s, SST 9.8 |  |
| 46125 | Hansville - Hood Canal, WA | 47.907 | -122.627 | Buoy | UW ORCA (relayed) | none | no obs in latest_obs |  |
| 46122 | Dabob Bay, WA (U of Wash) | 47.803 | -122.803 | Buoy | UW ORCA (relayed) | none | no obs in latest_obs |  |
| 46120 | Pt Wells, WA (U of Wash) | 47.761 | -122.397 | Buoy | UW ORCA (relayed) | none | no obs in latest_obs |  |
| desw1 | Destruction Island, WA | 47.675 | -124.485 | C-MAN Station | NDBC moored buoy / C-MAN | wind, pres | 19:00 wind 7.2 m/s | C-MAN; wind/pressure |
| wpow1 | West Point, WA | 47.662 | -122.435 | C-MAN Station | NDBC moored buoy / C-MAN | wind, pres | 19:10 wind 4.1 m/s | C-MAN Seattle; wind |
| ebsw1 | 9447130 - Seattle, WA | 47.602 | -122.338 | Water Level Observation Network | NOS tide gauge met | wind, pres | 18:54 |  |
| bmtw1 | 9445958 - Bremerton, WA | 47.562 | -122.626 | Water Level Observation Network | NOS PORTS met | wind, pres | 18:54 wind 0.0 m/s |  |
| 46453 | Backyard Buoys - Quinault North | 47.45 | -124.43 | Spotter Buoy | Backyard Buoys Spotter | none | no obs in latest_obs | Spotter; **no obs** (out of water) |
| 46124 | Hoodsport - Hood Canal, WA (U of Wash) | 47.422 | -123.113 | Buoy | UW ORCA (relayed) | none | no obs in latest_obs |  |
| 46123 | Twanoh - Hood Canal, WA (U of Wash) | 47.375 | -123.008 | Buoy | UW ORCA (relayed) | none | no obs in latest_obs |  |
| 46041 | CAPE ELIZABETH - 45NM NW of Aberdeen, WA | 47.351 | -124.741 | 3-meter discus buoy w/ seal cage | NDBC moored buoy / C-MAN | waves (+spec), wind, pres, SST | 19:10 wind 3.0 m/s, SST 12.0 | wave rows hourly :50 in .txt, .spec every 30 min |
| 46121 | Carr Inlet, WA (U of Wash)  | 47.28 | -122.73 | Buoy | UW ORCA (relayed) | none | no obs in latest_obs |  |
| tcmw1 | 9446482 - Tacoma Met, WA | 47.276 | -122.418 | Water Level Observation Network | NOS PORTS met | wind | 18:54 wind 1.5 m/s |  |
| tcnw1 | 9446484 - Tacoma, WA | 47.267 | -122.413 | Water Level Observation Network | NOS PORTS met | wind, pres, SST | 18:54, SST 13.3 |  |
| 46099 | OOI Westport Shelf | 46.988 | -124.567 | Buoy | OOI (relayed) | wind, pres, SST, WQ | 17:50 wind 4.0 m/s, SST 13.2 | OOI; met + SST, no waves; 2 h lag |
| wptw1 | 9441102 - Westport, WA | 46.904 | -124.105 | Water Level Observation Network | NOS tide gauge met | wind, pres, SST | 18:36 wind 1.5 m/s, SST 11.7 |  |
| 46211 | Grays Harbor, WA (036) | 46.857 | -124.243 | Waverider Buoy | CDIP Waverider (relayed) | waves (+spec), wind, SST | 18:56 Hs 1.1 m, DPD 12 s, MWD 293, SST 12.5 | CDIP 036 |
| 46100 | OOI Westport Offshore | 46.851 | -124.964 | Buoy | OOI (relayed) | none | no obs in latest_obs | OOI; **no obs** |
| tokw1 | 9440910 - Toke Point, WA | 46.707 | -123.967 | Water Level Observation Network | NOS tide gauge met | wind, pres, SST | 18:54 wind 0.5 m/s, SST 12.5 |  |
| 46116 | SATURN Estuary Station #07, Baker Bay, WA | 46.287 | -124.016 | Buoy | CRITFC SATURN | none | no obs in latest_obs |  |
| 46243 | Clatsop Spit, OR (162) | 46.215 | -124.129 | Waverider Buoy | CDIP Waverider (relayed) | waves (+spec), wind, SST | 17:30 Hs 1.1 m, DPD 12 s, MWD 271, SST 12.0 | CDIP 162; **2 h stale** (17:30Z) |
| asto3 | 9439040 - Astoria, OR | 46.207 | -123.768 | Water Level Observation Network | NOS tide gauge met | wind | 18:54 wind 1.0 m/s |  |
| sefo3 | SATURN Estuary Station #04 at Mott Basin | 46.204 | -123.759 | Water Quality Station | CRITFC SATURN | none | no obs in latest_obs |  |
| seto3 | SATURN Estuary Station #03 | 46.2 | -123.941 | Water Quality Station | CRITFC SATURN | none | no obs in latest_obs |  |
| srfw1 | SATURN River Station #05 | 46.185 | -123.188 | Water Quality Station | CRITFC SATURN | none | no obs in latest_obs |  |
| 46117 | SATURN Estuary Station #09, Youngs Bay, OR | 46.176 | -123.869 | Buoy | CRITFC SATURN | none | no obs in latest_obs |  |
| 46096 | Columbia River Entrance - SATURN Station #02 Offshore | 46.173 | -124.127 | Buoy | CRITFC SATURN | none | no obs in latest_obs |  |
| 46029 | COLUMBIA RIVER BAR - 20NM West of Columbia River Mouth | 46.148 | -124.508 | 2.1-meter ionomer foam buoy w/ seal cage | NDBC moored buoy / C-MAN | waves (+spec), wind, pres, SST | 19:10 wind 5.0 m/s, SST 14.1 | 2.1-m foam hull; bar reference buoy |
| 46248 | Astoria Canyon, OR  (179) | 46.133 | -124.64 | Waverider Buoy | CDIP Waverider (relayed) | waves (+spec), wind, SST | 18:56 Hs 1.4 m, DPD 11 s, SST 14.6 | CDIP 179 |
| lopw1 | 9440422 - Longview, WA | 46.106 | -122.954 | Water Level Observation Network | NOS tide gauge met | wind, pres, SST | 18:54, SST 16.9 |  |
| klmw1 | 9440357 - TEMCO Kalama Terminal, WA | 45.983 | -122.835 | Water Level Observation Network | NOS PORTS met | wind, pres | 18:54 |  |
| 46089 | TILLAMOOK, OR - 85 NM WNW of Tillamook, OR | 45.928 | -125.815 | 3-meter discus buoy w/ seal cage | NDBC moored buoy / C-MAN | waves (+spec), wind, pres, SST | 19:10 wind 5.0 m/s, SST 15.1 | deep water, 85 NM offshore |
| sraw1 | SATURN River Station #08, Camas, WA | 45.572 | -122.379 | Water Quality Station | CRITFC SATURN | none | no obs in latest_obs |  |
| 46278 | Tillamook Bay South Jetty, OR (270) | 45.559 | -123.991 | Waverider Buoy | CDIP Waverider (relayed) | waves (+spec), wind, SST, currents | 19:00 Hs 1.3 m, DPD 14 s, MWD 283, SST 11.1 | CDIP 270; currents too |
| tlbo3 | 9437540 - Garibaldi, Tillamook Bay, OR | 45.555 | -123.919 | Water Level Observation Network | NOS tide gauge met | none | no obs in latest_obs |  |
| 46050 | STONEWALL BANK - 20NM West of Newport, OR | 44.679 | -124.535 | 3-meter foam buoy | NDBC moored buoy / C-MAN | waves (+spec), wind, pres | 19:10 wind 2.0 m/s | sample 18:50Z Hs 1.3 m DPD 13 s MWD 290; .spec 18:40 SwH 1.3 SwP 12.9 WWH 0.3 |
| 46097 | OOI Newport Shelf | 44.639 | -124.304 | Buoy | OOI (relayed) | wind, pres, SST, WQ | 18:50 wind 1.0 m/s, SST 11.8 | OOI; met + SST, no waves |
| sbeo3 | 9435380 - South Beach, OR | 44.625 | -124.045 | Water Level Observation Network | NOS tide gauge met | wind, pres | 18:54 |  |
| nwpo3 | Newport, OR | 44.613 | -124.067 | C-MAN Station | NDBC moored buoy / C-MAN | wind, pres | 19:10 wind 1.0 m/s | C-MAN; wind |
| 46280 | Newport PWS North (277) | 44.575 | -124.234 | Waverider Buoy | NLR/PacWave Waverider | none | no obs in latest_obs | CDIP 277, **no data** |
| 46283 | Yaquina Channel SW, OR (280) | 44.567 | -124.237 | Waverider Buoy | NLR/PacWave Waverider | none | no obs in latest_obs | CDIP 280, **no data** |
| 46281 | Newport PWS South, OR (278) | 44.559 | -124.233 | Waverider Buoy | NLR/PacWave Waverider | none | no obs in latest_obs | CDIP 278, **no data** |
| 46098 | OOI Waldport Offshore | 44.378 | -124.947 | Buoy | OOI (relayed) | none | no obs in latest_obs | OOI; **no obs** |
| 46229 | UMPQUA OFFSHORE, OR (139) | 43.772 | -124.549 | Waverider Buoy | CDIP Waverider (relayed) | waves (+spec), wind, SST | 18:56 Hs 1.5 m, DPD 13 s, MWD 295, SST 13.7 | CDIP 139 |
| chao3 | 9432780 - Charleston, OR | 43.351 | -124.337 | Water Level Observation Network | NOS tide gauge met | wind, pres | 18:36 wind 1.0 m/s |  |
| cwqo3 | Charleston Bridge, South Slough Reserve, OR | 43.338 | -124.321 | NERRS Water Quality Station | NERRS | none | no obs in latest_obs |  |
| soqo3 | Valino Island, South Slough Reserve, OR | 43.317 | -124.322 | NERRS Water Quality Station | NERRS | none | no obs in latest_obs |  |
| sloo3 | Elliot Creek - South Slough Reserve, OR | 43.296 | -124.311 | Water Quality Station | NERRS | WQ | no obs in latest_obs |  |
| 46128 | Buoy CB-06 - West of Coos Bay, OR | 43.292 | -124.538 | Buoy | NANOOS (relayed) | none | no obs in latest_obs | NANOOS; **no obs** |
| chqo3 | Winchester Arm, South Slough Reserve, OR | 43.282 | -124.32 | NERRS Water Quality Station | NERRS | none | no obs in latest_obs |  |
| snto3 | Tom's Creek, South Slough Reserve, OR | 43.279 | -124.318 | NERRS Weather Station | NERRS | wind, pres | 18:30 wind 1.0 m/s |  |
| 46015 | PORT ORFORD - 15 NM West of Port Orford, OR | 42.754 | -124.839 | 3-meter discus buoy w/ seal cage | NDBC moored buoy / C-MAN | waves (+spec), wind, pres, SST | 19:10 wind 7.0 m/s, SST 12.4 | wave rows hourly :50 |
| poro3 | 9431647 - Port Orford, OR | 42.739 | -124.498 | Water Level Observation Network | NOS tide gauge met | wind, pres, SST | 18:54 wind 2.1 m/s, SST 10.1 |  |
| 46027 | ST GEORGES - 8 NM NW of Crescent City, CA | 41.84 | -124.382 | 3-meter discus buoy w/ seal cage | NDBC moored buoy / C-MAN | waves (+spec), wind, pres | 19:10 wind 3.0 m/s | wave rows hourly :50; Crescent City |
| cecc1 | 9419750 - Crescent City, CA | 41.746 | -124.184 | Water Level Observation Network | NOS tide gauge met | wind, pres, SST | 18:54 wind 2.1 m/s, SST 10.6 |  |
| tdpc1 | Trinidad Pier Trinidad, CA | 41.055 | -124.147 | Water Quality Station | CeNCOOS | wind, SST, WQ | 19:00, SST 10.7 | CeNCOOS; met + SST |

**Wave-reporting stations only (20), north to south:** 46146, 46304 (ECCC, Georgia Strait, Hs/DPD only); 46206 La Perouse Bank (ECCC, Hs/DPD; direction only via SWOB-ML); 46087 Neah Bay, 46088 New Dungeness, 46267 Angeles Point (CDIP 248), 46041 Cape Elizabeth, 46211 Grays Harbor (CDIP 036), 46243 Clatsop Spit (CDIP 162), 46029 Columbia River Bar, 46248 Astoria Canyon (CDIP 179), 46089 Tillamook offshore, 46278 Tillamook Bay South Jetty (CDIP 270), 46050 Stonewall Bank, 46229 Umpqua Offshore (CDIP 139), 46015 Port Orford, 46027 St Georges (Crescent City). 46099 OOI Westport Shelf and 46097 OOI Newport Shelf report met/SST but no waves.

**In the window but adrift / offline / no current data (2026-10-13):**
- `46303` Southern Georgia Strait (ECCC): active list, no observation in `latest_obs`; also absent from today's Datamart SWOB folder.
- `SISW1` Smith Island C-MAN: active list, no observation.
- `46453` Backyard Buoys Quinault North (Sofar Spotter): no observation (seasonal/out of water).
- `46280`, `46281`, `46283` Newport PWS North/South, Yaquina Channel SW (NLR/PacWave Waveriders, CDIP 277/278/280): listed, no data; not in CDIP's realtime catalog.
- `46100` OOI Westport Offshore, `46098` OOI Waldport Offshore, `46128` NANOOS CB-06 Coos Bay, `46118` Se'lhaem Bellingham Bay (met only, all MM), `46116`/`46117`/`46096` CRITFC SATURN, UW ORCA profilers `46120`-`46125` (no met/wave payload), NERRS water-quality sites: nothing useful for waves.
- Disestablished but still in `station_table.txt` (status D): 46010, 46038, 46039, 46040, 46043, 46094 NH-10, 46109-46113 (Port Angeles/Sequim/Fort Worden/Marrowstone/Poulsbo), 46127, 46134 Pat Bay, 46139 La Perouse DWR (CDIP 195, superseded by 46206), 46260 Lakeside (CDIP 231), 46261 Reedsport (CDIP 232), 46451/46452 PMEL tests, 46T29, CARO3 Cape Arago (2012), TTIW1 Tatoosh Island (2017), DMNO3 (2019), LPOI1. Do not plot them.
- The offshore deep-water buoys surfers watch, 46005 (46.1 N 131 W) and 46002 (42.6 N 130.5 W), sit **outside** the window to the west; worth a one-line link in a popup but not a map marker.

**Caveats.** Station IDs in `realtime2` URLs must be upper case (`NWPO3.txt`). 46087's `.spec` file was intermittent (gap 12 Oct 08:40 to 13 Oct 17:10 UTC). `latest_obs.txt` only shows the newest row per station, so for the 8 NDBC moored buoys the wave fields are nearly always `MM`; read `.spec` (one 150 KB request per buoy, 8 per cycle) or the `.txt` :50 row. Spectral `.spec` directions are compass points (WNW), `MWD` is degrees.

## 2. CDIP (Coastal Data Information Program, Scripps)

**PNW realtime stations** (from THREDDS realtime catalog and ERDDAP `wave_agg`, fetched 2026-10-13):

| CDIP | NDBC | name | lat | lon | depth | last obs UTC | sample (Hs m / Tp s / Dp deg) |
|---|---|---|---|---|---|---|---|
| 248 | 46267 | Angeles Point, WA (Strait of Juan de Fuca) | 48.1706 | -123.6004 | - | 19:00 | 0.35 / 12.5 / 295 |
| 036 | 46211 | Grays Harbor, WA | 46.8568 | -124.2433 | 39 m MLLW | 19:00 | 1.11 / 11.1 / 291 |
| 162 | 46243 | Clatsop Spit, OR | 46.2151 | -124.1287 | - | 16:30 (stale) | 1.04 / 14.3 / 259 |
| 179 | 46248 | Astoria Canyon, OR | 46.1334 | -124.6443 | - | 19:00 | 1.41 / 13.3 / 279 |
| 270 | 46278 | Tillamook Bay South Jetty, OR | 45.5608 | -123.9905 | - | 19:00 | 1.51 / 13.3 / 283 |
| 139 | 46229 | Umpqua Offshore, OR | 43.7708 | -124.5535 | - | 19:00 | 1.42 / 14.3 / 292 |
| 277/278/280 | 46280/46281/46283 | Newport PWS N/S, Yaquina Channel SW (NLR/PacWave) | 44.56-44.58 | -124.23 | - | none | not in realtime catalog |
| 231, 232, 195 | 46260, 46261, 46139 | Lakeside, Reedsport, La Perouse DWR | - | - | - | - | historical only |

No CDIP buoy at Port Orford (NDBC 46015 is an NDBC 3-m buoy). Nothing CDIP north of Angeles Point on the Canadian side.

**Endpoints:**

| product | URL | fetched | notes |
|---|---|---|---|
| THREDDS realtime catalog | `https://thredds.cdip.ucsd.edu/thredds/catalog/cdip/realtime/catalog.xml` | 200, 41 KB | 84 `NNNp1_rt.nc` datasets. OPeNDAP at `/thredds/dodsC/cdip/realtime/036p1_rt.nc`. The NCSS path `/thredds/ncss/cdip/realtime/...` returned 404; use OPeNDAP or ERDDAP. CDIP says "Our THREDDS data server is the preferred method of accessing the data." |
| ERDDAP, all PNW buoys in one call | `https://erddap.cdip.ucsd.edu/erddap/tabledap/wave_agg.csv?station_id,time,latitude,longitude,waveHs,waveTp,waveDp&latitude>=41&latitude<=49.7&longitude>=-126.6&longitude<=-122&time>=2026-10-13T12:00:00Z&orderByMax("station_id,time")` | 200, 516 B, 6 rows | **best single request**; also `.json`, `.geoJson`. Other datasets: `sst_agg`, `cat4_agg` (air), `gps_agg`, `acm_agg` (currents). `time_coverage_resolution PT30M`. |
| Realtime text, parameters | `https://cdip.ucsd.edu/data_access/justdar.cdip?036+pm` | 200, 3.9 KB | HTML `<pre>` with YEAR MO DY HR MN Hs Tp Dp Depth Ta ... Temp; 30-min rows. |
| Realtime spectrum | `https://cdip.ucsd.edu/data_access/justdar.cdip?036+sp` | 200, 5.5 KB | header (Hs, Tp, Dp, Ta, depth) + 64 frequency bands with energy, Dmean, a1 b1 a2 b2. |
| Station page | `https://cdip.ucsd.edu/m/products/?stn=036p1` | read about only | human page, link target for popups. |

**Cadence.** "Realtime data is updated every 30 minutes" and sent to NDBC/NWS every 30 min (CDIP data_access page). Observed: 19:00 obs available by 19:44 (the `sp` header says `Analyzed(UTC): 2026 10/13 1944`).

**Licence.** ERDDAP `license` attribute: "These data may be redistributed and used without restriction." CDIP data access page: "CDIP data and products are freely available for public use, provided that they are not altered in any way." Web use: "please provide a link to the CDIP homepage", e.g. `Data courtesy of <a href=https://cdip.ucsd.edu/>CDIP</a>` (https://cdip.ucsd.edu/m/documents/data_access.html and ODIS record https://catalogue.odis.org/view/1078). DOI 10.18437/C7WC72. Sponsors: USACE and California State Parks.

**Caveats.** ERDDAP `waveTp` comes back as 11.111111 etc. (reciprocal of the band frequency); round to 0.1 s. The NDBC relay lags ERDDAP by a few minutes and drops the station's own Dp precision. Station 162 Clatsop Spit was behind the others today; check `time` per row rather than assuming all are current.

## 3. Environment and Climate Change Canada (MSC Datamart / GeoMet)

**Buoys in the window** (GeoMet `swob-marine-stations`, bbox query 2026-10-13, 4 matches):

| WMO | ECCC msc_id | name | lat | lon | NDBC relay | status today |
|---|---|---|---|---|---|---|
| 46206 | 9100580 | La Perouse Bank (off Ucluelet/Tofino) | 48.835 | -125.998 | 46206 | live, hourly; 19:05Z Hs 1.6 m, max 2.4 m, Tp 13.3 s, peak dir 264, wind 38.5 km/h, SST 11.4 |
| 46146 | 9100552 | Halibut Bank (Strait of Georgia) | 49.34 | -123.7267 | 46146 | live |
| 4600304 | 9102001 | Entrance to English Bay | 49.3017 | -123.3567 | 46304 | live |
| 4600303 | 9102000 | Southern Georgia Strait | 49.025 | -123.43 | 46303 | **no data** today (no Datamart folder, no NDBC obs) |

Other ECCC buoys surfers quote (46132 South Brooks 49.74 N 127.9 W, 46036 South Nomad, 46204 West Dixon, 46207 East Dellwood, 46208 West Moresby, 46131 Sentry Shoal 49.9 N) are just outside the window; 46132 and 46036 are the upstream swell indicators for Tofino and could be shown as off-map links.

**Endpoints (fetched 2026-10-13):**

| product | URL pattern | status | notes |
|---|---|---|---|
| SWOB-ML moored buoys, per day/station | `https://dd.weather.gc.ca/today/observations/swob-ml/marine/moored-buoys/YYYYMMDD/<7-digit WMO>/YYYY-MM-DD-HHMM-<WMO>-AUTO-swob.xml` e.g. `.../20261013/4600206/2026-10-13-1905-4600206-AUTO-swob.xml` | 200, 8 KB | 37 Canadian buoys present today (4600146, 4600206, 4600304 in window; 4600303 absent). Hourly at :05. Elements: `avg_sig_wave_hgt_pst20mts`, `spetrl_sig_wave_hgt_pst20mts`, `max_wave_hgt_pst20mts`, `pk_wave_pd_pst20mts`, `avg_wave_pd_pst20mts`, `avg_pk_wave_dir_pst20mts`, `avg_wave_dir_pst20mts`, `avg_wave_dir_sprd_pst20mts`, `avg_wnd_spd_pst10mts` (km/h), `max_wnd_spd_pst10mts`, `avg_wnd_dir_pst10mts`, `avg_mslp_pst10mts`, `avg_air_temp_pst10mts`, `avg_sea_sfc_temp_pst10mts`, `crnt_buoy_lat/long` (drift check). Also a `latest/` folder under `swob-ml/`. The old path `dd.weather.gc.ca/observations/...` without `today/` now 404s; dated roots `dd.weather.gc.ca/YYYYMMDD/...` also exist. |
| GeoMet OGC-API buoy stations | `https://api.weather.gc.ca/collections/swob-marine-stations/items?f=json&bbox=-126.6,48,-122,49.7` | 200 | metadata only. |
| GeoMet OGC-API realtime obs | `https://api.weather.gc.ca/collections/swob-realtime/items?...` | 200 but 0 buoy rows | land SWOB stations only in the bbox query; filtering by `stn_nam-value=LA PEROUSE BANK` matched 0. Buoys do not appear to be in `swob-realtime`; use Datamart XML. |
| Marine forecasts, XML | `https://dd.weather.gc.ca/today/marine_weather/pacific/<HH>/<ISO time>_MSC_MarineWeather_<areaCode>_en.xml`; areas in `https://dd.weather.gc.ca/today/marine_weather/regionList.xml` | 200 | Pacific area codes in/near window: `m0000009` Juan de Fuca Strait, `m0000065` West Coast Vancouver Island South, `m0000028` Strait of Georgia, `m0000064` Haro Strait, `m0000102` Howe Sound, `m0000043` WCVI North, `m0000087` Explorer (offshore). Issued ~4 times/day (folders 00, 04, 06, 09, 10, 17 UTC today). |
| Marine forecasts, GeoJSON | `https://api.weather.gc.ca/collections/marineweather-realtime/items?f=json&bbox=-126.6,47.5,-122,49.7` | 200, 49 KB, 6 features | properties `regularForecast`, `extendedForecast`, `waveForecast` (present for WCVI South / Explorer), `warnings`, `lastUpdated 2026-10-13T17:37Z`. Collection marked "[experimental]". |
| RDWPS regional wave model | `https://dd.weather.gc.ca/today/model_rdwps/national/2.5km/<HH>/YYYYMMDDTHHZ_MSC_RDWPS_<VAR>_Sfc_RLatLon0.0225_PTnnnH.grib2` | 200 listing | runs 00/06/12 listed (18 presumably), hourly to 48 h, 1.8 MB per variable per step, rotated lat-lon 0.0225 deg (~2.5 km). Variables: HTSGW, WVHGT, WVDIR, PWAVEDIR, PWPER, MZWPER, PPERWW, WWSDIR, **SWHFSWEL/PWPFSWEL/MWDFSWEL** (first swell), **SWHSSWEL/PWPSSWEL/MWDSSWEL** (second swell), UGRD/VGRD 10 m, USSD/VSSD (Stokes drift), ICEC. ECCC readme: domains include "Pacific North-East"; the `national` 2.5 km grid covers Canadian waters, so it should reach the Strait, WCVI and the Washington coast but **the extent was not read from a file** (open question). |
| GDWPS global wave model | `https://dd.weather.gc.ca/today/model_gdwps/25km/<HH>/YYYYMMDDTHHZ_MSC_GDWPS_<VAR>_Sfc_LatLon0.25_PTnnnH.grib2` | 200 listing | runs 00/12, to 240 h, 1.1 MB per variable-step, same 19 variables. |

**Licence.** ECCC Data Servers End-use Licence (https://eccc-msc.github.io/open-data/licence/readme_en/): licensee may "use the Information, including for commercial purposes, subject to the terms below"; attribution "Data Source: Environment and Climate Change Canada" or "Contains information licenced under the Data Server End-use Licence of Environment and Climate Change Canada"; alerts must be shown with "no alteration of the content or intent of the alert".

**Caveats.** SWOB-ML attribute order varies; parse with an XML parser, not regex. Wind is km/h, not m/s. Datamart folders are UTC-day based; at 00:0x UTC the new day's folder may not exist yet, so fall back to the previous day. Datamart also offers AMQP push (sarracenia), which a 15-min poll does not need.

## 4. Wave forecasts

### 4a. NOAA GFS-Wave (WAVEWATCH III coupled to GFS), AWS Open Data

| item | detail |
|---|---|
| Bucket | `s3://noaa-gfs-bdp-pds/gfs.YYYYMMDD/HH/wave/gridded/` (anonymous HTTPS: `https://noaa-gfs-bdp-pds.s3.amazonaws.com/...`). Listed 2026-10-13 06Z run: HTTP 200. |
| Grids present | `global.0p16` (11.0 MB/step), `global.0p25`, `wcoast.0p16` (**267 KB/step**), `epacif.0p16` (515 KB), `atlocn.0p16`, `arctic.9km`. |
| wcoast.0p16 extent | downloaded `gfswave.t06z.wcoast.0p16.f024.grib2` (270,619 bytes) and read with cfgrib: lat 25.0-50.0 N (151 rows), lon 210-250 E (-150 to -110, 241 cols), 0.1667 deg. Covers the whole window (Halibut Bank 49.34 N is inside). swh at 46.85 N 124.25 W, f024 = 1.15 m. |
| Fields (from `.idx`, 19 records) | WIND, WDIR, UGRD, VGRD, HTSGW (sig. height), PERPW (peak period), DIRPW (peak dir), WVHGT/WVPER/WVDIR (wind wave), SWELL 1/2/3, SWPER 1/2/3, SWDIR 1/2/3 (three swell partitions). cfgrib names: `swh perpw dirpw shww mpww wvdir shts mpts swdir`. |
| Steps / cadence | hourly f000-f120, 3-hourly to f384 (209 steps on global); runs 00/06/12/18 Z; 06Z files landed 09:31 Z (about 3.5 h after cycle). |
| Byte-range | every file has a `.idx`, so a single field can be fetched with an HTTP Range request (HTSGW in f024 is bytes 66587-76518, ~10 KB). |
| Licence | NOAA Open Data Dissemination; public domain US government data. |
| Also | GEFS-Wave ensemble: `s3://noaa-gefs-pds/gefs.YYYYMMDD/HH/wave/gridded/gefs.wave.tHHz.cNN.global.0p25.fNNN.grib2`, 13 MB per member-step (listed, 200). Only worth it for a spread/probability product later. |

### 4b. NWPS (Nearshore Wave Prediction System, SWAN per WFO)

| item | detail |
|---|---|
| Location | NOMADS only: `https://nomads.ncep.noaa.gov/pub/data/nccf/com/nwps/prod/wr.YYYYMMDD/<wfo>/<HH>/CGn/<wfo>_nwps_CGn_YYYYMMDD_HH00.grib2`. Western Region WFOs listed 2026-10-13: eka, lox, mfr, mtr, pqr, sew, sgx. No AWS bucket found (searched; EMC/NCO docs only point at NOMADS). |
| Runs today | sew: 00, 12; pqr: 00, 02, 06, 12, 14, 18; mfr: 00, 12 ("run 1-8 times per day, on demand, depending on the coastal WFO", NCO release notes). sew 12Z CG1 files appeared 18:56 Z (about 7 h after the nominal cycle, since the WFO submits wind grids first). |
| Grids | sew: CG0 (outer), CG1, CG2 (nested). CG1 GRIB2 = **15 MB**; plus `nwps.t12z.spc2d_<buoy>_CG1.sew.txt` 2-D spectra at 46041, 46087, 46088, 46206 (961 KB each). Nearshore resolution 1.8 km to 500 m, hourly to 144 h (read about). |
| Variables | HTSGW, PERPW, DIRPW, WVHGT/WVPER/WVDIR, SWELL/SWPER/SWDIR partitions, WIND/WDIR, sometimes water level and currents (read about; the NOMADS filter lists HTSGW, PERPW, DIRPW). |
| Subsetter | `https://nomads.ncep.noaa.gov/gribfilter.php?ds=wrnwps` / `cgi-bin/filter_wrnwps.pl` (page fetched, 200, lists sew/pqr/mfr and CG0-CG4): lets a job pull just HTSGW/PERPW/DIRPW for a lat/lon box, a few hundred KB instead of 15 MB. NOMADS asks users to "pause before resubmitting requests". |
| Caveat | NOMADS rate-limits aggressively and is less reliable than S3 for a cron job; keep to one filter request per WFO per cycle and cache. Cycles vary by day so the job must list the directory rather than assume 00/12. |

### 4c. NWS text products and API (api.weather.gov)

| product | URL | fetched | content |
|---|---|---|---|
| Surf Zone Forecast, Portland | `https://api.weather.gov/products/types/SRF/locations/PQR` then `/products/<id>` | 200; latest issued 2026-10-13T13:02Z (FZUS56 KPQR, "602 AM PDT") | zones WAZ201 Long Beach WA; ORZ101 Seaside/Cannon Beach; ORZ102 Manzanita/Rockaway/Pacific City; ORZ103 Lincoln City. Per day: "Surf Height...5 to 7 ft", "Offshore Swell...West 4 ft at 14 seconds" (two swell trains on Wednesday), thunderstorm potential, weather, high temp, wind, tides, sunrise/sunset. Once daily ~06:00 PDT, "automated product". |
| Surf Zone Forecast, Medford | `.../SRF/locations/MFR` | 200; latest 2026-10-13T09:40Z (240 AM PDT), several issuances/day | ORZ021 Reedsport to Port Orford, ORZ022 Port Orford to Brookings: "Surf Height...9 FT", water temperature, tides at Charleston. No swell line. |
| Surf Zone Forecast, Seattle | `.../SRF/locations/SEW` | 200, empty `@graph` | **SEW issues no SRF**; the WA coast north of Long Beach has no surf-zone text product. |
| Coastal Waters Forecast | `.../CWF/locations/SEW` (08:22Z), `PQR` (08:30Z), `MFR` (19:26Z) | 200 | zone text with wind, seas, swell ("W 6 ft at 13 seconds" style), 4x daily. Zone IDs confirmed via `https://api.weather.gov/zones?type=coastal&id=PZZ110,...`: PZZ110 Grays Harbor Bar; PZZ130/131/132 Strait of Juan de Fuca W/C/E; PZZ133 Northern Inland Waters incl. San Juans; PZZ134 Admiralty Inlet; PZZ135 Puget Sound and Hood Canal; PZZ150/153/156 WA coast out 10 nm (Cape Flattery-James Is., James Is.-Pt Grenville, Pt Grenville-Cape Shoalwater); PZZ170/173/176 same 10-60 nm; PZZ210 Columbia River Bar; PZZ251/252/253 OR coast out 10 nm (Cape Shoalwater-Cape Falcon, Cape Falcon-Cape Foulweather, Cape Foulweather-Florence); PZZ271/272/273 10-60 nm; PZZ350/356 Florence-Cape Blanco, Cape Blanco-Pt St George; PZZ370/376; PZZ450/470 Pt St George-Cape Mendocino. (`?area=WA,OR` returns nothing for marine zones; query by id.) Zone polygons: `https://api.weather.gov/zones/forecast/PZZ150` (GeoJSON). |
| Gridpoint marine forecast | `https://api.weather.gov/points/47.00,-124.60` -> `https://api.weather.gov/gridpoints/SEW/47,55` | 200, 157 KB | `waveHeight` (m, e.g. 1.524 for 13 Oct 12Z/P1DT6H), `wavePeriod2` (s, 15-16), `windSpeed` hourly, `validTimes` 7.5 days. `wavePeriod`, `waveDirection`, `primarySwellHeight/Direction`, `secondarySwell*`, `windWaveHeight` arrays were **empty** for this SEW ocean point. Documentation: "at this time coastal marine grid forecasts are only available from the forecastGridData property." |
| Other codes present in `/products/types` | OFF Offshore Forecast, MWW Marine Weather Message, SMW Special Marine Warning, HSF High Seas, MIM Marine Interpretation Message, NSH (Great Lakes only). |

**Terms.** api.weather.gov docs (https://www.weather.gov/documentation/services-web-api): "All of the information presented via the API is intended to be open data, free to use for any purpose"; "A User Agent is required to identify your application"; "there are reasonable rate limits in place". Products are also mirrored on `https://tgftp.nws.noaa.gov/data/raw/fz/fzus56.kpqr.srf.pqr.txt` (read about only).

### 4d. ECCC marine forecasts

See section 3: Datamart XML per area (`m0000009` Juan de Fuca Strait, `m0000065` WCVI South, `m0000028` Strait of Georgia, `m0000064` Haro Strait) and the GeoMet `marineweather-realtime` collection with a `waveForecast` block for the exposed areas. Fetched 2026-10-13, both 200.

## 5. Other free, legal sources a surfer would use

| source | verdict | evidence |
|---|---|---|
| **Open-Meteo Marine API** | usable for non-commercial; no key | `https://marine-api.open-meteo.com/v1/marine?latitude=46.85&longitude=-124.25&hourly=wave_height,wave_period,wave_direction,swell_wave_height,swell_wave_period,swell_wave_direction,wind_wave_height` returned 200 (1.8 KB; 13 Oct 00Z wave_height 1.6 m, period 13.3 s, dir 284). Terms (https://open-meteo.com/en/terms): "You may only use the free API services for non-commercial purposes"; "Less than 10'000 API calls per day"; data "provided under the terms of the CC-BY 4.0 licence". Commercial includes sites "with subscriptions or ads". radar.blackwaterlabs.org is free and ad-free, but it is run by a company; Chris should decide whether that counts. It is a repackaging of the same GFS-Wave/ECMWF WAM grids, so it adds little once 4a is wired. |
| **Surfline** (incl. former Magicseaweed) | do not use | Terms of Use (https://www.surfline.com/terms-of-use, fetched 2026-10-13, 200 with a plain client; WebFetch got 403): users may not "use any robot, spider, scraper or other automated means to access the Services" nor "use any manual, automated or programmatic method to crawl or extract data". No public API. Magicseaweed went dark 2023-05-15 and redirects to Surfline. |
| **NOAA CoastWatch ERDDAP `NWW3_Global_Best`** | gone | `https://coastwatch.pfeg.noaa.gov/erddap/info/NWW3_Global_Best/index.json` returned 404 on 2026-10-13. |
| **PacIOOS ERDDAP `ww3_global`** | untested | `https://pae-paha.pacioos.hawaii.edu/erddap/info/ww3_global/index.json` timed out twice (TLS handshake, 20 s). It is a WW3 0.5 deg global subset; redundant with 4a anyway. |
| **CDIP MOP / nearshore model** | California only | CDIP's nearshore (MOP) wave model covers California; nothing for OR/WA (read about). |
| **Sofar Spotter / Backyard Buoys** | not free as a feed | 46453 Quinault is relayed by NDBC when deployed; Sofar's own API needs a token. |
| **Buoy-to-break lore** (for popup text, not data) | - | Westport/Half Moon Bay watches 46211 (Grays Harbor) and 46041; Long Beach and Seaside/Cannon Beach watch 46029 and CDIP 162/179; Pacific City and Lincoln City watch 46089 and 46050; Newport/Otter Rock watch 46050; Florence/Umpqua watch 46229; Port Orford/Brookings watch 46015 and 46027; Neah Bay/Hobuck and La Push watch 46087 and 46119; the Strait (Crescent Bay, Twin Rivers) watches 46267 Angeles Point; Tofino/Cox Bay watches La Perouse 46206 and South Brooks 46132 (off-map). Rule of thumb surfers use: a 14+ s west swell at the offshore buoy means the long-period energy reaches the beaches a few hours later; wind-sea from the 3-m buoys (WWH in `.spec`) is what makes it messy. Kiteboarders care more about the wind agent's sources plus `WWH/WWP`. |

## What to use first (ranked)

1. **NDBC `latest_obs.txt` + the eight `.spec` files** (every 15 min; 9 requests, ~1.3 MB): one station layer for the whole window with Hs, period, direction, swell/wind-wave split, SST, wind, pressure; public domain; covers CDIP, ECCC, OOI, NOS via one host. Filter by the station list in this file and by the `status`/`created` fields.
2. **CDIP ERDDAP `wave_agg` CSV** (every 15 min; 1 request, 0.5 KB): authoritative, timestamped values for the six Waveriders with proper Dp; use it to overwrite the NDBC relay rows and show "Data courtesy of CDIP".
3. **ECCC SWOB-ML for 4600206, 4600146, 4600304** (hourly; 3 requests): adds peak period and peak direction at La Perouse Bank that NDBC drops; attribute "Data Source: Environment and Climate Change Canada".
4. **GFS-Wave `wcoast.0p16` from AWS** (hourly job; after each cycle lands ~3.5 h post-run; pull HTSGW/PERPW/DIRPW plus the three SWELL/SWPER/SWDIR partitions by byte range from the `.idx`, 24-48 steps): one raster layer for forecast swell height/period/direction to 10 days, same pipeline as HRRR smoke. ~100-300 KB per step with ranges.
5. **NWS SRF (PQR, MFR) and CWF (SEW, PQR, MFR) via api.weather.gov** (hourly; 5 requests): human-readable surf height and swell lines per beach zone for popups; public domain; needs the User-Agent header.
6. **NWPS CG1 via `filter_wrnwps.pl`** (hourly, only when a new cycle is listed; 3 requests): 500 m-1.8 km nearshore Hs for the Washington and Oregon surf zones, better than GFS-Wave at the beach. Second tier because NOMADS is flaky and runs are on demand.
7. **ECCC RDWPS 2.5 km** (every 6 h; 19 variables x 48 steps at 1.8 MB is too much; take HTSGW/PWPER/PWAVEDIR at 3-h steps, ~30 MB/run) for the Canadian side of the Strait and Vancouver Island where NWPS has no grid. Confirm the extent first.
8. **ECCC marine forecast XML / GeoJSON** (hourly, 4 areas): text for the Canadian zones.
9. Open-Meteo: only if Chris accepts the non-commercial reading; otherwise skip.

## Open questions

1. Does the RDWPS `national` 2.5 km grid cover the Strait of Juan de Fuca and the Washington coast, or only Canadian waters? Needs one GRIB2 download (1.8 MB) and an extent read.
2. Which NWPS CG grid (CG0/CG1/CG2) should feed the map for SEW/PQR/MFR, and what are their extents? Needs a `filter_wrnwps.pl` subset request or a GRIB header read; the full CG1 file is 15 MB.
3. 46087 Neah Bay's spectral gaps: hardware or telemetry? Worth a staleness badge rather than hiding the station.
4. Is the Open-Meteo "non-commercial" condition acceptable for a free site run by Blackwater Hydrology LLC? Chris's call; not needed if 4a is built.
5. Should off-window buoys 46005, 46002, 46132 and 46036 be shown as edge markers or popup links? They are the swell indicators surfers quote for Washington and Tofino.
6. Does the site want the NDBC raw spectra (`.data_spec`, 1.4 MB per buoy) for a period-energy plot? Not recommended for a 15-min job.
7. ECCC `swob-realtime` on GeoMet returned no buoy rows; confirm whether buoys are deliberately excluded from that collection or whether a different property filter is needed, before relying on Datamart XML alone.
