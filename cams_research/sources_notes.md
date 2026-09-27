# Webcam sources: research notes (agents, 2026-09-26)

Condensed from the research agents' reports. Every image pattern below was fetched with a browser UA,
`Referer: https://radar.blackwaterlabs.org/` and a `?t=` cache-buster unless marked otherwise.
Camera lists with coordinates: `feeds.json`, `towns.json` (and the others as they are copied in).

## Keyless feeds (in feeds.json, 304 cams)
| Source | Listing | Image | Verdict |
|---|---|---|---|
| USGS HIVIS river cams (137 + 4 beach) | `api.waterdata.usgs.gov/nims/cameras?enabled=true` | `usgs-nims-images.s3.amazonaws.com/720/{camId}/{camId}_newest.jpg` | use; 136 carry a gauge number |
| USGS volcano cams (44) | Ashcam | per camera | use; some re-host ski cams (Timberline, Bachelor, Crystal): credit the owner |
| NOAA NDBC BuoyCAMs (18) | buoycams listing | file name changes hourly | use; rebuild hourly |
| NPS webcams (101) | NPS API `/webcams` (free api.data.gov key; built once with the public DEMO_KEY) | images need no key | use with Chris's key; partner-hosted ones follow the partner's terms |
| Windy Webcams API | needs key | free-tier image URLs expire in 10–15 min | only via popup-time API call or embedded player; credit "Webcams provided by Windy.com" |
| HPWREN, FAA WeatherCams | | | already in AlertWest |
| PhenoCam (NAU) | `phenocam.nau.edu/api/cameras/?format=json&limit=1200` (keyless) | `phenocam.nau.edu/data/latest/<Sitename>.jpg` | curated subset (~30–40 conditions views of 208 active in boxes); CC BY 4.0; **robots.txt disallows /data/ except Google**, so the job must not fetch images: judge freshness from API `date_last`, let browsers hotlink |

## Provider networks
| Provider | Image pattern | Listing | Terms | Verdict |
|---|---|---|---|---|
| Roundshot | `https://backend.roundshot.com/cams/<id>/centerprev` (302 to latest; sizes thumbnail/centerprev/medium/default/full) | `backend.roundshot.com/schema_list/12/list_frame.json` (560 cams; lat/lon from `<link>settings.json` position) | Livecam Service Conditions (28 Jan 2026) allow third-party preview display; credit owner + Roundshot | **use**, automatic; 31 in boxes, 27 fresh; drop 403s; skip 32-hex hash ids |
| Brownrice | `https://player.brownrice.com/snapshot/<streamname>` (no Last-Modified; up to 3840x2160) or `liveN.brownrice.com/cam-images/<sn>.jpg` (has LM; some servers bad TLS) | none | TOS binds customers only | hand-pick |
| HDRelay | `https://img.hdrelay.com/frames/<camera uuid>/default/last.jpg` | player config `manage.hdrelay.com/player/<player uuid>` (lat/lon unreliable) | site-content reproduction clause, ambiguous | hand-pick; new watch.hdrelay.io player is signed, skip |
| Prism / Archr | `https://storage.googleapis.com/prism-cam-000NN/720-watermark.jpg` | none; don't enumerate ids | none found | hand-pick (Alta) |
| CamStreamer | YouTube `i.ytimg.com/vi/<id>/hqdefault_live.jpg` | `camstreamer.com/live/update-search-map` (1,880 streams, 224 in boxes, lat/lng) | YouTube terms | hand-pick, or with a YouTube Data API key; ids change when streams restart; freshness unprovable without the API |
| ipcamlive | `https://ipcamlive.com/player/snapshot.php?alias=<alias>` | login-only | viewing only on provider or owner's site | **owner consent needed** |
| webcam.io | `https://assets1.webcam.io/w/<id>/latest.jpg` | none | "any further use requires your consent" | **owner consent needed** |
| Wetmet/WMVision | signed S3 / HLS tokens | | | skip |
| EarthCam, OnTheSnow, SnoCountry, ResortCams, AmbientWeather.net, Weathercloud | | | terms forbid or paid | skip |

## Hand-pick sources (universities, avalanche centres, agencies)
- Univ. of Utah Horel/UUNET: `horel.chpc.utah.edu/data/station_cameras/<id>_cam/<id>_cam_current.jpg`; 12 fresh
  (salt flats, Gunnison Island, campus, La Sal Goldbasin snow plot). © all rights reserved: credit, consider emailing.
- Oregon State: `webcam.oregonstate.edu/cam/<path>/live/live.jpg` (Marys Peak, HJ Andrews HQ, flood cam). **Rate-limits
  (429 after 3 fast requests)**: space checks seconds apart.
- HJ Andrews: `andrewsforest.oregonstate.edu/sites/default/files/lter/data/weather/realtime/images/<name>.jpg`;
  Last-Modified is not reliable (images 5–6 h old); hand-set coordinates.
- Bridger-Teton avalanche station cams: `wxstns.net/wxstns/jhnet/<name>.jpg` (lava, boxy, cowboy, blindb, commrdg);
  no coordinates published.
- DRI/WRCC Reno: `wrcc.dri.edu/webcam/images/wrcc1w.jpg`, `wrcc3e.jpg`.
- UW rooftop west: resolve `atmos.uw.edu/roof-west/latest.php` → timestamped file.
- Montana Mesonet: keyless API `mesonet.climate.umt.edu/api/v2/photos/` (157 stations, N/S/E/W/snow views) but the
  photo pipeline has been stalled since 2026-09-20: re-check later.
- Boulder County Open Space Walker Ranch: `bouldercountyopenspace.org/photos/walker/live1.jpg`.
- Nothing usable: SNOTEL (static photos), CAIC, most avalanche centres (they link to ski/DOT cams), USFS, BLM, BPA,
  USBR, state parks, Weather Underground (dead). ALERTCalifornia is already inside AlertWest.

## Map-side facts
- `map.html` appends `'?t='` unconditionally (popup `src`), which breaks image URLs that already have a query
  (ipcamlive, Prism realtime_preview, NOAA fixed links). Use `&` when `?` is present.
- Some images are large (Rainier Longmire 1.8 MB, Brownrice 4K). Prefer small variants (Roundshot `centerprev`).
