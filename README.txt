BLACKWATER RADAR
================

What runs where
---------------
capture.py      (this PC, every 15 min)  pulls every new RainViewer scan for the
                Northwest window, stores it as a transparent map layer, rebuilds the
                rainfall accumulation overlays, refreshes station totals hourly,
                writes frames.js, and uploads everything to Cloudflare R2.
map.html        the interactive map (Leaflet). build_web.py bakes the R2 address in
                and writes web/, which is uploaded to the Cloudflare Worker that
                serves radar.blackwaterlabs.org.
R2 bucket       "radar", public at https://radar-files.blackwaterlabs.org
                frames/radar/*.webp   radar scans (10-min cadence)
                frames/dbz/           NOT uploaded (local only, for the math)
                frames/accum/*.webp   estimated rainfall overlays, 1h..24h and all
                frames.js             manifest the map reads
                data/stations.js      station totals (hourly)
                data/*.geojson        county outline, highways

Day to day
----------
start_capture.cmd   start capture (minimized window "Radar Capture", runs until 10 AM)
stop_capture.cmd    stop it
capture.log         one line per cycle; failures are logged, never fatal

After editing map.html:   python build_web.py   then drag the web\ folder onto the
radar Worker in Cloudflare (Workers & Pages -> radar -> Deployments -> upload).

Files
-----
capture.py      capture loop and manifest (radar every 15 min; hourly jobs below)
satellite.py    GOES-West GeoColor frames from NASA GIBS -> frames/sat
accumulate.py   dBZ -> rain rate (Marshall-Palmer) -> window totals -> overlays
mrms.py         NOAA MRMS gauge-corrected rainfall grids (1/3/6/12/24 h) -> frames/mrms
stations.py     SNOTEL (precip, snow, temp, % of median), NWS HADS, CoCoRaHS, and the NWS
                observation network (temp/wind/humidity, full detail inside the FOCUS box
                around Leavenworth) -> data/stations.js
interp.py       elevation-aware interpolation of station totals -> frames/interp
basins.py       NRCS-style basin snowpack / water-year precip % of median -> data/basins.js
rivers.py       USGS gauges, medians, NWS/NWRFC forecasts -> data/rivers.js
forecast.py     NDFD rain, snow, gust, high/low overlays -> frames/forecast
alerts.py       NWS watches/warnings with zone polygons -> data/alerts.js
avalanche.py    NWAC zones via avalanche.org -> data/avalanche.js
webcams.py      AlertWest cameras (fire PTZ + DOT) -> data/webcams.js
values.py       256x256 value grids for click-anywhere sampling -> data/values/
r2sync.py       uploader (reads r2.env; KEEP r2.env PRIVATE)
build_web.py    builds web/ from map.html (icons + manifest already in web/)
rv_palette.json RainViewer color -> dBZ lookup
viewer.html     legacy viewer for the pre-map frames (frames/rainviewer etc.)

Map window: zoom-7 tiles x 19..23, y 42..46 = lon -126.6..-112.5, lat 43.1..52.5.
Change Z/X0/X1/Y0/Y1 in capture.py to move it; accumulation and overlays follow.

Caveats
-------
Radar rainfall is an estimate from reflectivity; it reads low in Cascade valleys
where the beam overshoots, and high in convective cores. Use the station layer
for real totals. Station snow values only exist where a site measures snow depth
or snow water (SNOTEL, some NWS sites). BC snow pillows report daily, not hourly.

Data: RainViewer (NWS + Environment Canada radar), NRCS AWDB, NOAA HADS,
CoCoRaHS, NWS API, Esri and OpenTopoMap basemaps, OpenStreetMap roads,
US Census county boundary.
