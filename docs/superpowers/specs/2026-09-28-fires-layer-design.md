# Fires layer: design (2026-09-28)

Agreed with Chris in chat, 2026-09-28 06:16–07:07. Phase 2 of "Smoke & fires"; phase 1 (Air quality) went live 2026-09-28,
phase 3 (the smoke forecast loop) gets its own spec. Source research: `smoke_research/sources_notes.md` (2026-09-27);
every endpoint below was re-fetched 2026-09-28 13:22–13:24 UTC and the counts here are from that check.

## Goal
Answer "what is burning near where I'm going, how big is it, and is it active right now?" with agency incident
records, mapped perimeters and satellite heat detections, in a new **Smoke & fires** section of the panel between
Air quality and Hazards. NWS Red Flag Warnings, Fire Weather Watches and Dense Smoke Advisories already show under
Hazards and are not repeated.

## Decisions (Chris, 2026-09-28)
| # | Decision |
|---|---|
| 1 | Fires and smoke share one panel section, **Smoke & fires**, between Air quality and Hazards. Phase 2 fills it with fires; phase 3 adds the smoke forecast. |
| 2 | **No FIRMS MAP_KEY** and no key path in the code: hotspots come from the keyless FIRMS CSVs (VIIRS 3–5 h old, MODIS ~4 h) and NOAA NGFS (GOES, minutes old). |
| 3 | NGFS detections that NGFS has not tied to a known incident **are shown, marked unconfirmed** (hollow marker, "not yet tied to a known fire"). |
| 4 | Prescribed burns **are shown, greyed and labelled "prescribed burn"**. |
| 5 | **No evacuation layer**: BC's is the only open source and a BC-only layer would imply US fires have none. Fire cards link to the agency page instead. |
| 6 | **Every fire the agencies list as current is kept, styled by activity**; a "hide quiet fires" sub-control (default on) keeps the map clean. No size floor. |
| 7 | Data path: one job module, two output files (`fires.js` every run; `perimeters.js` only when the source edit stamps change), a private state file. Not one file per run, not browser-side fetches. |

## What the reader sees
```
Air quality
Smoke & fires                                  (new section, data-grp="fire")
  ☐ Fires (?)
      ☑ hide quiet fires                       (sub-control, default on)
      41 active of 186 · 21 prescribed · updated Mon Sep 28 06:45 AM
      Fires reported by US and Canadian agencies (NIFC, CWFIF, BC Wildfire Service). Sizes and containment are
      the agencies' latest reports; perimeters come from mapping flights and can be days old.
  ☐ Satellite hotspots (?)
      [< 6 h | 6–24 h | 24–48 h]
      Heat seen from satellites (NOAA GOES every few minutes; NASA VIIRS and MODIS a few hours old). Includes
      prescribed burns and industrial or farm heat sources. Hollow: GOES detection not yet tied to a known fire.
Hazards
```
- Both switches and the sub-control are off/on by default as shown and join `DEF_CHECKS`, so "Make current map &
  settings my default" keeps them.
- (?) tips: Fires: what "active" means (updated in the last 3 days, hotspots in the last 24 h, or out of control /
  being held in Canada) and that a quiet fire is still listed, not out. Hotspots: a VIIRS pixel is ~375 m, GOES ~2 km;
  a hotspot is heat, not a mapped fire edge.
- **Fire markers:** a flame divIcon in three sizes (under 100 acres, 100–9,999, 10,000 and over); red-orange for
  wildfires and complexes, grey for prescribed burns; quiet fires smaller and at 45 % opacity. From zoom 8 each
  active fire shows its name as an in-view-only label (the divIcon pattern the station labels use). Perimeters draw
  under the markers as a red outline with a light fill; hovering names the fire.
- **Fire card** (click or hover, like the AQI card): name and a type chip (wildfire / complex / prescribed burn);
  county and state or province, the incident management organisation where WFIGS gives one; acres with the
  containment percentage and a thin bar; "discovered Sep 12" and
  "last update 3 h ago"; behaviour and personnel when present; the short description; "perimeter mapped 14 h ago"
  when one exists; "12 hotspots in the last 24 h"; a link to the agency page when there is one; footer
  "Source: NIFC (WFIGS)" or "CWFIF (Natural Resources Canada), BC Wildfire Service".
- **Hotspot markers:** small circles coloured by age from the three chips; NGFS detections hollow when unconfirmed.
  Tooltip: satellite, time, fire radiative power (MW), "seen since 03:31 UTC" for GOES features, and the fire's name
  when linked.
- **Click anywhere:** a "Fires" block with the nearest active fire within 50 km (name, distance, acres, containment)
  and the count of hotspots within 10 km in the last 24 h.
- Data loads only when a switch is turned on (the page preloads the radar loop at open; nothing new waits behind
  it unless asked for), and reloads on the 15-minute timer while on.
- `terms.html`: credits for NIFC, NRCan CWFIF (Open Government Licence – Canada), BC Wildfire Service (OGL-BC),
  NASA FIRMS ("We acknowledge the use of data from NASA's Fire Information for Resource Management System") and
  NOAA NGFS (beta, provided as is).

## What runs behind it
New module `fires.py`, `build(log)`, called in `capture.py`'s 15-minute block after `airquality`. Requests use the
plain Chrome User-Agent, 30 s timeouts, the runner cache (`airquality.CACHE_DIR` pattern, so the five region steps
download each national file once) and the hung-host rule (`airquality._open`). Budget 150 s per region step.

1. **US incidents.** `WFIGS_Incident_Locations_Current/FeatureServer/0/query`, `where=1=1`, `f=geojson`, 26 fields
   (~340 KB nationally, 389 records 2026-09-28: 279 WF, 3 CX, 18 complex children, 89 RX; `maxRecordCount` 2000,
   paged with `resultOffset` if `exceededTransferLimit`). Keep `IncidentTypeCategory` in WF, CX, RX; drop
   `IsCpxChild`; drop rows with `FireOutDateTime`. Fields kept: `IncidentName`, `IrwinID`, `IncidentTypeCategory`,
   `IncidentSize`, `PercentContained`, `FireDiscoveryDateTime`, `ModifiedOnDateTime_dt`, `ContainmentDateTime`,
   `FireOutDateTime`, `FireBehaviorGeneral`, `TotalIncidentPersonnel`, `IncidentShortDescription`, `POOCounty`,
   `POOState`, `IncidentManagementOrganization`, `FireCause`. (The layer has no `DailyAcres`; `IncidentSize` is
   the reported size.)
2. **Canadian incidents.** CWFIF WFS `public:cwfif_national_activefires`, `CQL_FILTER=now()>=record_start AND
   now()<=record_end` (parameters URL-encoded; 167 KB, 233 fires: BC 103, QC 41, PC 30, ON 29, YT 17). Fields:
   `national_fire_id`, `agency_code`, `agency_fire_id`, `fire_size` (ha), `stage_of_control_status` (OC, BH, UC),
   `response_type` (FUL, MOD, MON), `percent_contained` (-1 = unknown), `status_date`, `fire_was_prescribed`.
   Then BCWS `BCWS_ActiveFires_PublicView`, `where=FIRE_STATUS<>'Out'` (70 KB, 98 fires), matched by fire number
   (CWFIF `agency_fire_id` `2026-V12186` ↔ BCWS `FIRE_NUMBER` `V12186`); adds `FIRE_URL`, `GEOGRAPHIC_DESCRIPTION`
   (the name; CWFIF has none), `FIRE_STATUS`, `FIRE_OF_NOTE_IND`, `FIRE_CAUSE`. A BC fire in only one list is kept.
   Hectares × 2.4711 → acres once, in the job.
3. **Perimeters.** `WFIGS_Interagency_Perimeters_Current` with `maxAllowableOffset=0.001&geometryPrecision=4`
   (766 KB nationally, 133 polygons; PNW 69 = 582 KB, newest 3 h, median 22 days), joined to incidents by
   `attr_IrwinID` (all 133 carry one). BCWS `BCWS_FirePerimeters_PublicView`, `FIRE_STATUS<>'Out'` (116 KB, 73),
   joined by fire number. Fetched only when the layer's `editingInfo.dataLastEditDate` (an 8 KB metadata call per
   layer) differs from the stamp in the state file; polygons whose bounding box misses the window are dropped.
4. **Hotspots.** FIRMS `{noaa-20|noaa-21|suomi-npp}-viirs-c2` and `modis-c6.1` 48 h CSVs, `USA_contiguous_and_Hawaii`
   and `Canada` (eight files, ~0.9 MB; the Canada files repeat ~90 % of their rows from the US files), de-duplicated
   by (latitude, longitude, acq_date, acq_time, satellite). NGFS `ngfs_features_scene_{west|east}_conus/items`,
   scene from the region's `goes` setting (`cfg().get("goes", "West")`: only ne sets it, East), `bbox` = the window,
   `datetime` = the last 24 h (a fresh range every call: responses carry `max-age=3600`), `limit=5000`; the newest
   detection per `feature_tracking_id` is kept (a feature is re-reported every ~5 min: 42 detections per id in 6 h),
   and the id's embedded timestamp is the first-seen time. `known_incident_id` is an IRWIN id and links the
   detection to its WFIGS fire; `type_description` "Possible Wildland Fire" = unconfirmed. Each FIRMS hotspot is
   linked to the nearest incident within 2 km, else to the perimeter containing it, else unlinked.
5. **Activity and cut.** `active` = updated in the last 72 h (WFIGS `ModifiedOnDateTime_dt`, CWFIF `status_date`),
   or ≥ 1 linked hotspot in the last 24 h, or Canadian stage OC / BH; a fire at 100 % contained is quiet unless it
   has hotspots. Everything is cut to `region.bbox()`. Agency links: BCWS `FIRE_URL`; for US fires the InciWeb RSS
   feed (`https://inciweb.wildfire.gov/incidents/rss.xml`, the 50 most recently updated incidents, 157 KB) matched by
   name and state after stripping the unit prefix and the words fire/complex (judgment call, ledger).
6. **Outputs.** `<region>/data/fires.js`, global `FIRES`:
   `{updated, updated_t, ngfs: bool, fires:[{id, name, type, src, lat, lon, acres, contained, discovered, modified,
   behaviour, personnel, desc, county, state, stage, response, url, note, active, perim, hot24}],
   hotspots:[[lat, lon, age_h, src, frp, fire_id|null, unconfirmed, since|null]]}` (`src` V/M/G; `since` = a GOES
   feature's first-seen time, from its tracking id; expected PNW ~60 KB, NE ~40 KB).
   `<region>/data/perimeters.js`, global `PERIMS`: a GeoJSON FeatureCollection with `id`, `name`, `acres`, `age_h`
   per polygon (PNW ~600 KB), rewritten each run from the state file, refetched only on a stamp change.
   `<region>/data/fires_cache.json` (private, `cloud.py STATE_FILES`): the WFIGS and BCWS edit stamps, the last
   perimeter set, the last NGFS detections with their fetch time.
7. **Failure.** A failed WFIGS or CWFIF fetch keeps the last good `fires.js` and logs why (one source down does not
   blank the other: the file is rewritten only when at least one incident source succeeded, and the log says which).
   A failed NGFS call reuses the cached detections for up to 1 h, then FIRMS alone, and `ngfs: false` makes the
   page drop the "every few minutes" wording. A failed perimeter fetch keeps the last set. Log line per run:
   `fires: 186 fires (41 active, 21 prescribed, 96 Canada), 69 perimeters (unchanged), hotspots 129 FIRMS + 287 NGFS`
   (PNW 2026-09-28: 69 WF/CX + 21 RX from WFIGS, 96 from CWFIF).

Page: `FIRES` and `PERIMS` join the script-tag globals; both files get the `no-cache` header like the other
`data/*.js` (`r2sync.py` already treats `data/*.js` that way; no image folder is added).

## Data check (gate before any map code)
`python smoke_research/fires_check.py <region>` runs `fires.build()` locally with no upload, then shows Chris:
1. **Accounting line:** WFIGS rows fetched, kept by type, complex children and out fires dropped, inside the window;
   CWFIF rows, BCWS matched and unmatched; perimeters with and without an incident; FIRMS rows per file, duplicates
   removed, inside the window; NGFS features, distinct tracked features, known vs possible; hotspots linked to a fire.
2. **MATLAB-style figure** (`plt.style.use('matlab')`), two panels: the window with perimeters, fire markers sized by
   acres and coloured by type and activity, hotspots as small dots by age; and the ten largest active fires as
   horizontal bars of acres with the contained share filled.
3. **Independent checks:** (a) hotspots against fires from a different pipeline: the share of VIIRS detections in
   the last 24 h within 2 km of a fire or inside a perimeter, and the share of active fires with at least one
   hotspot; big fires without hotspots and dense clusters without a fire are listed (no target; the NE window is
   expected low: its 152 VIIRS hotspots in 48 h have a median FRP of 1.2 MW, industrial and farm heat).
   (b) polygon area (`poly_GISAcres`, and our own planar area) against the incident's reported acres for every
   joined perimeter; outliers more than 25 % apart listed. (c) every NGFS `known_incident_id` exists in WFIGS.
4. Then `smoke_research/fires_serve.py` (the `aq_serve.py` pattern: `fires.js` and `perimeters.js` from this PC,
   everything else from live R2) for the page work, after Chris says go.

## Testing and release
- pytest (network blocked), small fixture files: WFIGS parsing, complex-child and out-fire drops, paging;
  CWFIF and BCWS join by fire number and the hectare conversion; FIRMS de-duplication across the US and Canada
  files; newest detection per NGFS tracked feature, first-seen time from the id, the known-incident link; hotspot
  to fire linking (2 km, then perimeter); the activity rule at its edges (72 h, 24 h, 100 % contained); window
  clipping; unchanged edit stamps skip the perimeter download; a failed fetch keeps the last good file; NGFS cache
  expiry at 1 h. Only json, csv, math and urllib at module level.
- node tests on a `// BEGIN fireHelpers` block in `map.html` (the `test_map_*.py` pattern): marker size steps at
  99 / 100 / 9,999 / 10,000 acres; hotspot age chips at 5.9 / 6 / 24 / 48 h; nearest active fire within 50 km and
  hotspots within 10 km; saving and restoring the three controls.
- Local build checked in the in-app browser against live data: markers, labels from zoom 8, cards and links,
  perimeters, hotspots and tooltips, hide-quiet toggle, click-anywhere, phone width, no console errors.
  (The worktree has no `web/`; `build_web.py` runs in `radar/` after the merge, or with `web/` copied in.)
- Release as before: Chris runs the push and deploy from Run-button blocks; then curl the live page and diff it
  against `web/index.html`, and read the first Actions runs' `fires:` lines for all five regions.

## Parameter ledger (judgment calls and sources; Chris to confirm at the gate)
| Parameter | Value | Source | Where |
|---|---|---|---|
| Incident types kept | WF, CX, RX; complex children dropped; `FireOutDateTime` set = dropped | WFIGS field meanings; sources_notes | fires.py |
| Active | updated ≤ 72 h, or ≥ 1 linked hotspot ≤ 24 h, or CWFIF stage OC/BH; 100 % contained = quiet unless hotspots | **judgment call** | fires.py, map.html |
| Hotspot windows | FIRMS 48 h (the 48h files), NGFS 24 h | **judgment call** (FIRMS also offers 24 h and 7 d) | fires.py |
| Hotspot age chips | < 6, 6–24, 24–48 h | **judgment call** | map.html |
| Hotspot → fire link | nearest incident point ≤ 2 km, else containing perimeter | **judgment call** (VIIRS pixel 375 m, GOES ~2 km) | fires.py |
| NGFS scene | region `goes` setting (West / East) | region.py; both scenes see the West, ids differ, so one scene per region avoids double counting | fires.py |
| NGFS de-duplication | newest detection per `feature_tracking_id` | checked 2026-09-28 (42 per id in 6 h) | fires.py |
| NGFS cache on failure | 1 h | **judgment call** | fires.py |
| Perimeter simplification | `maxAllowableOffset=0.001`, `geometryPrecision=4` | sources_notes (21 MB → 0.7 MB) | fires.py |
| Perimeter refetch | only when `editingInfo.dataLastEditDate` changes | ArcGIS layer metadata, checked 2026-09-28 | fires.py |
| Marker size steps | < 100, 100–9,999, ≥ 10,000 acres | **judgment call** | map.html |
| Quiet fire style | 45 % opacity, one size step down | **judgment call** | map.html |
| Label zoom | 8+ (active fires only) | **judgment call** (fires are sparser than stations, which label at 9) | map.html |
| Wildfire / prescribed colours | red-orange `#d1462f` / grey `#8a8f98`; perimeter outline `#c0392b`, fill 0.12 | **judgment call** (muted, in the site's palette) | map.html |
| Hectares → acres | × 2.4711 | definition | fires.py |
| InciWeb link match | RSS title minus the leading unit code, and the WFIGS name, both lower-cased with fire/complex and non-letters removed; state must match | **judgment call** (the feed has no IRWIN id) | fires.py |
| Click-anywhere | nearest active fire ≤ 50 km; hotspots ≤ 10 km in 24 h | **judgment call** | map.html |
| Fetch budget | 150 s per region step | airquality.DEADLINE_S | fires.py |

## Open items found while designing
- NGFS is beta and "as is"; its `type` codes seen so far are 0 (Possible Wildland Fire), 1 (Known Wildland Fire
  Incident), 4 and 7 (undocumented in the response; logged and shown as unconfirmed until described).
- The east scene's 24 h national query hits the 5000 cap (7,147 matched); with the region `bbox` it does not, but the
  job logs `numberMatched` against `numberReturned` and pages with `offset` if they differ.
- CWFIF `stage_of_control_status` and `agency_code` are the field names (the research notes' `stage_of_control` and
  `agency` do not exist).
- InciWeb's RSS covers only the 50 most recently updated incidents, so most quiet fires get no link.
- `alerts.py` still sends a User-Agent with Chris's email (api.weather.gov asks for contact details); untouched here.

## Out of scope
The smoke forecast loop, HMS smoke polygons, outlooks and blog feeds (phase 3); the HRRR-fused AQI surface;
evacuation zones; FIRMS MAP_KEY and URT data; fire history and burn scars; fire-weather indices.
