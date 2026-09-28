# Air Quality Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A new "Air quality" panel section on radar.blackwaterlabs.org with AQI stations (AirNow permanent monitors plus AirFire temporary smoke monitors, 72 h history) and AirNow's interpolated AQI map.

**Architecture:** One new job module, `airquality.py`, runs in the 15-minute radar job for each region. It keeps a private rolling 72 h store in R2 state and writes `data/airquality.js` (`window.AIRQ`), `frames/aq/aqi.webp` and `data/values/aqi.js`. `map.html` gets a new panel group, a station layer with cards and charts, and an image overlay, all following the existing station, SNODAS and rivers patterns.

**Tech Stack:** Python 3 standard library (csv, urllib), numpy, Pillow and cfgrib (imported inside functions only), Leaflet 1.x in `map.html`, pytest, node for the `// BEGIN…END` block tests.

**Spec:** `docs/superpowers/specs/2026-09-27-air-quality-layer-design.md` (read it first; decisions 1–9 and the parameter ledger are binding). Sources and endpoints: `smoke_research/sources_notes.md`.

## Global Constraints

- Work in `C:\Users\16035\Desktop\BlackwaterLabs\radar` (its own git repo, branch `main`). Tests: `python -m pytest tests/ -v` from that folder, with the main Python `C:\Users\16035\anaconda3\python.exe`.
- **Other sessions have uncommitted edits here** (`CLAUDE.md`, `slope/build_slope.py`, the untracked `HANDOFF.md`). Never `git add -A` or `git add .`: stage only the files a task names. Before editing `CLAUDE.md` (Task 8), run `git diff CLAUDE.md` and leave other sessions' hunks alone.
- Every web request uses a plain Chrome User-Agent (`UA` in `airquality.py`). Never put Chris's email, name or other personal data in any request. `freezing.py` and `webcams.py` carry an email in their UA; do not copy it.
- 30 s timeout on every request (`TIMEOUT`).
- Free tier only; no keys. Sources: `files.airnowtech.org` and `airfire-data-exports.s3.us-west-2.amazonaws.com` only.
- CI installs only `pytest` and `pyyaml`. `airquality.py` imports only the standard library and `region` at module level; numpy, PIL, cfgrib and `values` are imported inside functions. Tests that need numpy or PIL call `pytest.importorskip`.
- Never print, open or grep `*.env` files. Never run `capture.capture_all()` or `cloud.py` locally: with `r2.env` present they upload to the live bucket. Call `airquality.build()` directly instead.
- AQI category edges 0/51/101/151/201/301, colours `#00e400 #ffff00 #ff7e00 #ff0000 #8f3f97 #7e0023`, names Good / Moderate / Unhealthy for sensitive groups / Unhealthy / Very unhealthy / Hazardous (EPA AQI TAD, May 2024).
- Permanent monitors show AirNow's `PM25_AQI` unchanged. Only temporary monitors get AQI from NowCast µg/m³ (`aqi_from_pm25`).
- Card footer wording: "Preliminary data, not verified. Source: AirNow (U.S. EPA), <agency>." (temporary monitors: "Source: AirNow (U.S. EPA) via USFS AirFire, <agency>."). No airnow.gov links.
- Stale after 3 h without a report. Trend: latest raw hour vs 3 h earlier, rising/falling if the change is ≥ 5 µg/m³ and ≥ 20 %. Click-anywhere nearest station within 100 km.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Chris runs `git push` and `npx --yes wrangler deploy` himself from Run-button blocks (root `CLAUDE.md`, "Commands for Chris to run").
- **Task 4 is a gate:** stop after it and show Chris the check output. Map work (Tasks 5–8) starts only after he says go.

## Review Focus

1. **Malformed rows in an AirNow file** (a truncated last line, empty numbers, a missing AQSID) must skip that row, not drop the file. Pinned in Task 1 (`test_malformed_rows_are_skipped`).
2. **The newest hour not posted yet** (S3 answers 403 or 404 at :05–:20 past the hour) must fall back to the two newest posted hours. Pinned in Task 2 (`test_unposted_top_hour_falls_back`).
3. **A corrupt or old-format `aq_cache.json`** (a partial upload, a schema change) must start a fresh store, not crash every run. Pinned in Task 2 (`test_corrupt_store_starts_fresh`).
4. **A grid with no data in the window** (AirNow blanks everything, e.g. an outage upstream) must give a transparent image and a no-data value grid, not an exception. Pinned in Task 3 (`test_all_blank_grid_is_transparent`).
5. **Station names containing HTML** (`<`, `&`, quotes in a site name or address) must show as text in cards and click panels. Pinned in Task 5 (`test_escape`).

---

### Task 1: Parse AirNow and AirFire files; AQI conversion; rolling store

**Files:**
- Create: `airquality.py`
- Test: `tests/test_airquality.py`

**Interfaces:**
- Produces:
  - `airquality.parse_hourly(text: str) -> list[dict]`, each `{id, name, agency, lat, lon, elev, t, aqi, pm}` (`t` = UTC hour start, epoch s; `aqi` int; `pm` float or None)
  - `airquality.parse_airfire(meta_text: str, raw_text: str, nowcast_text: str) -> list[dict]` (same keys, temporary monitors only)
  - `airquality.aqi_from_pm25(c: float | None) -> int | None`
  - `airquality.in_window(lat, lon, bbox) -> bool` (bbox = `(lat0, lat1, lon0, lon1)`, as `region.bbox()` returns)
  - `airquality.merge(store: dict, recs: list, temp: bool, bbox) -> dict`
  - `airquality.prune(store: dict, newest: int) -> dict`
  - `airquality.to_airq(store: dict, newest: int, now: float) -> dict` (the `window.AIRQ` object)
  - Store layout: `{"v": 1, "have": [hour starts], "st": {id: {name, agency, lat, lon, elev, temp, "h": {"<epoch>": [aqi, pm]}}}, "grid": {lm, t, file}}`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_airquality.py`:

```python
"""Air quality layer (airquality.py): AirNow HourlyAQObs, AirFire temporary monitors, store, AIRQ (no network)."""
import datetime as dt
import json

import pytest

import airquality

BBOX = (43.0, 52.5, -126.6, -112.5)          # the pnw window, rounded
T00 = int(dt.datetime(2026, 9, 28, 0, tzinfo=dt.timezone.utc).timestamp())
HDR = ('"AQSID","SiteName","Status","EPARegion","Latitude","Longitude","Elevation","GMTOffset","CountryCode","StateName",'
       '"ValidDate","ValidTime","DataSource","ReportingArea_PipeDelimited","OZONE_AQI","PM10_AQI","PM25_AQI","NO2_AQI",'
       '"OZONE_Measured","PM10_Measured","PM25_Measured","NO2_Measured","PM25","PM25_Unit","OZONE","OZONE_Unit","NO2",'
       '"NO2_Unit","CO","CO_Unit","SO2","SO2_Unit","PM10","PM10_Unit"')


def row(aqsid, name, lat, lon, when, aqi, pm, agency="Washington Dept. of Ecology", elev="30.0"):
    return ('"%s","%s","Active","R10","%s","%s","%s","-8","US","WA","%s","%s","%s","","","","%s","","0","0","1","0",'
            '"%s","UG/M3","","","","","","","","","",""' % (aqsid, name, lat, lon, elev, when.strftime("%m/%d/%Y"),
                                                           when.strftime("%H:%M"), agency, aqi, pm))


def hourly(t, rows):
    return "\n".join([HDR] + rows) + "\n"


def when(t):
    return dt.datetime.fromtimestamp(t, dt.timezone.utc)


def airfire(hours, temp_vals, perm_vals=None):
    """AirFire wide files: one temporary monitor inside the window, one outside, one permanent (ignored)."""
    meta = ("deviceDeploymentID,deviceID,locationName,longitude,latitude,elevation,address,airnow_agencyName,deploymentType\n"
            "d_tmp,840MMWA1,MMWA1,-120.66,47.60,350,\"Leavenworth Fish Hatchery, Icicle Road, Chelan County, WA\",USFS,Temporary\n"
            "d_far,840MMCA9,MMCA9,-119.6,37.7,2200,NA,California Air Resources Board,Temporary\n"
            "d_perm,530330080,Seattle,-122.3,47.6,30,NA,Washington Dept. of Ecology,Permanent\n")
    stamps = [when(t).strftime("%Y-%m-%dT%H:%M:%SZ") for t in hours]
    raw = ["datetime,d_tmp,d_far,d_perm"] + ["%s,%s,5,7" % (s, r) for s, (r, _) in zip(stamps, temp_vals)]
    nc = ["datetime,d_tmp,d_far,d_perm"] + ["%s,%s,5,7" % (s, n) for s, (_, n) in zip(stamps, temp_vals)]
    return meta, "\n".join(raw) + "\n", "\n".join(nc) + "\n"


# ---------- AQI conversion (EPA AQI TAD, May 2024) ----------
@pytest.mark.parametrize("c,aqi", [(0.0, 0), (4.6, 26), (6.6, 37), (9.0, 50), (9.1, 51), (12.0, 56), (35.4, 100),
                                   (35.5, 101), (55.4, 150), (125.4, 200), (225.4, 300), (325.4, 500), (9.05, 50)])
def test_aqi_from_pm25_breakpoints(c, aqi):
    # 4.6 -> 26 and 6.6 -> 37 are AirNow's own values for two temporary monitors (AirNowWildfire.csv, 2026-09-28)
    assert airquality.aqi_from_pm25(c) == aqi


def test_aqi_above_the_top_breakpoint_extends_the_last_segment():
    assert airquality.aqi_from_pm25(425.3) == 699
    assert airquality.aqi_from_pm25(None) is None and airquality.aqi_from_pm25(-1) is None


# ---------- parsing ----------
def test_parse_hourly_keeps_pm25_rows_with_utc_hour_start():
    text = hourly(T00, [row("530330080", "Seattle-10th & Weller", "47.5965", "-122.3197", when(T00), "44", "8.0"),
                        row("000010601", "Goose Bay", "53.3047", "-60.3644", when(T00), "", "")])
    recs = airquality.parse_hourly(text)
    assert [r["id"] for r in recs] == ["530330080"]
    r = recs[0]
    assert (r["t"], r["aqi"], r["pm"], r["agency"], r["elev"]) == (T00, 44, 8.0, "Washington Dept. of Ecology", 30.0)


def test_aqi_without_raw_value_is_kept_with_pm_none():
    # AirNow sometimes has PM25_AQI but a blank PM25 (seen at an Oakland site, 2026-09-28)
    recs = airquality.parse_hourly(hourly(T00, [row("060010011", "Oakland", "37.74", "-122.17", when(T00), "44", "")]))
    assert recs[0]["aqi"] == 44 and recs[0]["pm"] is None


def test_malformed_rows_are_skipped():
    good = row("530330080", "Seattle", "47.59", "-122.31", when(T00), "44", "8.0")
    bad_lat = row("530330081", "Bad lat", "x", "-122.31", when(T00), "44", "8.0")
    no_id = row("", "No id", "47.59", "-122.31", when(T00), "44", "8.0")
    truncated = good[:40]
    recs = airquality.parse_hourly(hourly(T00, [bad_lat, no_id, good, truncated]))
    assert [r["id"] for r in recs] == ["530330080"]


def test_parse_airfire_takes_temporary_monitors_hours_with_a_raw_value():
    hours = [T00 - 3600, T00, T00 + 3600]
    # the last row is the hour in progress: raw NA, NowCast carried forward
    meta, raw, nc = airfire(hours, [("15", "7.8"), ("9", "8.4"), ("NA", "8.4")])
    recs = airquality.parse_airfire(meta, raw, nc)
    tmp = [r for r in recs if r["id"] == "d_tmp"]
    assert [r["t"] for r in tmp] == [T00 - 3600, T00]
    assert [(r["pm"], r["aqi"]) for r in tmp] == [(15.0, 43), (9.0, 47)]
    assert tmp[0]["name"] == "Leavenworth Fish Hatchery" and tmp[0]["agency"] == "USFS" and tmp[0]["elev"] == 350.0
    assert {r["id"] for r in recs} == {"d_tmp", "d_far"}        # the permanent column is ignored


def test_parse_airfire_falls_back_to_location_name():
    meta, raw, nc = airfire([T00], [("9", "8.4")])
    far = [r for r in airquality.parse_airfire(meta, raw, nc) if r["id"] == "d_far"][0]
    assert far["name"] == "MMCA9"


# ---------- store ----------
def recs_at(t, aqi, pm=8.0, sid="530330080", lat=47.59, lon=-122.31):
    return [{"id": sid, "name": "Seattle", "agency": "Ecology", "lat": lat, "lon": lon, "elev": 30.0, "t": t,
             "aqi": aqi, "pm": pm}]


def test_merge_clips_to_the_region_window():
    store = airquality.merge({"v": 1}, recs_at(T00, 40) + recs_at(T00, 60, sid="080310026", lat=39.7, lon=-105.0),
                             False, BBOX)
    assert list(store["st"]) == ["530330080"]


def test_a_revised_hour_overwrites_the_older_value():
    store = airquality.merge({"v": 1}, recs_at(T00, 40, 7.9), False, BBOX)
    airquality.merge(store, recs_at(T00, 45, 9.2), False, BBOX)
    assert store["st"]["530330080"]["h"][str(T00)] == [45, 9.2]


def test_prune_drops_hours_older_than_72_and_empty_stations():
    store = airquality.merge({"v": 1, "have": [T00 - 72 * 3600, T00]}, recs_at(T00 - 72 * 3600, 30), False, BBOX)
    airquality.merge(store, recs_at(T00 - 71 * 3600, 31, sid="530330081"), False, BBOX)
    airquality.prune(store, T00)
    assert list(store["st"]) == ["530330081"] and store["have"] == [T00]


def test_to_airq_aligns_72_hours_ending_at_newest():
    store = airquality.merge({"v": 1}, recs_at(T00, 44, 8.0) + recs_at(T00 - 2 * 3600, 41, 7.0), False, BBOX)
    store["grid"] = {"lm": "x", "t": T00 + 3600, "file": "frames/aq/aqi.webp?v=1"}
    a = airquality.to_airq(store, T00, T00 + 5400)
    assert len(a["hours"]) == 72 and a["hours"][-1] == T00 and a["hours"][0] == T00 - 71 * 3600
    s = a["stations"][0]
    assert s["aqi"][-3:] == [41, None, 44] and s["pm"][-3:] == [7.0, None, 8.0] and s["temp"] is False
    assert a["grid"] == {"t": T00 + 3600, "file": "frames/aq/aqi.webp?v=1"}
    json.dumps(a)                                    # must serialise


def test_to_airq_of_an_empty_store_is_valid():
    a = airquality.to_airq({"v": 1}, T00, T00 + 5400)
    assert a["stations"] == [] and a["grid"] is None and len(a["hours"]) == 72
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_airquality.py -v`
Expected: collection error, `ModuleNotFoundError: No module named 'airquality'`.

- [ ] **Step 3: Write the implementation**

Create `airquality.py`:

```python
"""
Air quality stations and AirNow's interpolated AQI map (the map's "Air quality" section).

Every 15-minute radar run, for the region in REGION:
  data/airquality.js     window.AIRQ = {updated, updated_t, hours:[72 UTC hour starts, epoch s], grid, stations:[...]}
  data/aq_cache.json     private rolling store (cloud.py STATE_FILES): 72 h per station, the grid's Last-Modified
  frames/aq/aqi.webp     AirNow's gridded NowCast AQI in the official category colours (rewritten when it changes)
  data/values/aqi.js     the same grid for click-anywhere

Permanent monitors: AirNow's public HourlyAQObs files, values unchanged (PM25_AQI is AirNow's NowCast AQI).
Temporary smoke monitors: USFS AirFire's export of the same AirNow feed, which keeps true hour stamps
(AirNowWildfire.csv does not: see the spec, decision 9). Their AQI comes from NowCast PM2.5 with EPA's 2024 breakpoints.
Design: docs/superpowers/specs/2026-09-27-air-quality-layer-design.md; sources: smoke_research/sources_notes.md.

Run standalone (writes local files, uploads nothing):  python airquality.py
"""
import csv
import datetime as dt
import hashlib
import io
import json
import math
import os
import shutil
import tempfile
import time
import urllib.error
import urllib.request

import region

AIRNOW = "https://files.airnowtech.org/airnow"
AIRFIRE = "https://airfire-data-exports.s3.us-west-2.amazonaws.com/monitoring/v2/latest/data/"
GRID_URL = AIRNOW + "/today/current_pm25.grib2"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36"
TIMEOUT = 30
KEEP_H = 72                 # hours of history per station (AirNow keeps 72 h of hourly files)
BACKFILL_PER_RUN = 24       # missing AirNow hours fetched per run; an empty store fills in 3 runs
DEADLINE_S = 150            # stop backfilling after this long so the 15-minute job stays short
CACHE_MAX_AGE_S = 600       # the five region steps of one Actions job share each download
STEP = 2                    # grid computed at half the 1280 px window, like freezing.py
AQ_EDGES = (51, 101, 151, 201, 301)            # AQI category starts (EPA AQI TAD, May 2024)
AQ_COLORS = ((0, 228, 0), (255, 255, 0), (255, 126, 0), (255, 0, 0), (143, 63, 151), (126, 0, 35))
PM25_BP = ((0.0, 9.0, 0, 50), (9.1, 35.4, 51, 100), (35.5, 55.4, 101, 150), (55.5, 125.4, 151, 200),
           (125.5, 225.4, 201, 300), (225.5, 325.4, 301, 500))     # EPA AQI TAD, May 2024

DATA = region.data_dir()
OUT = os.path.join(DATA, "airquality.js")
STORE = os.path.join(DATA, "aq_cache.json")
FRAME_DIR = os.path.join(region.frames_dir(), "aq")
CACHE_DIR = os.path.join(os.environ.get("RUNNER_TEMP") or tempfile.gettempdir(), "airnow_cache")


class NotPosted(Exception):
    """the file is not on the server (yet)"""


def _num(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def aqi_from_pm25(c):
    """NowCast PM2.5 (ug/m3) -> AQI with EPA's 2024 breakpoints; above 325.4 the last segment is extended (judgment call)"""
    if c is None or c < 0:
        return None
    c = math.floor(c * 10 + 1e-9) / 10                   # EPA: truncate to 0.1 ug/m3
    for clo, chi, ilo, ihi in PM25_BP:
        if c <= chi:
            break
    return int(math.floor((ihi - ilo) / (chi - clo) * (c - clo) + ilo + 0.5))


def parse_hourly(text):
    """HourlyAQObs CSV -> [{id, name, agency, lat, lon, elev, t, aqi, pm}] for rows with a PM2.5 AQI (t = UTC hour start)"""
    out = []
    for r in csv.DictReader(io.StringIO(text)):
        aqi = _num(r.get("PM25_AQI"))
        if aqi is None or not r.get("AQSID"):
            continue
        try:
            t = dt.datetime.strptime(r["ValidDate"] + " " + r["ValidTime"], "%m/%d/%Y %H:%M").replace(tzinfo=dt.timezone.utc)
            lat, lon = float(r["Latitude"]), float(r["Longitude"])
        except (KeyError, TypeError, ValueError):
            continue
        out.append({"id": r["AQSID"], "name": (r.get("SiteName") or "").strip(), "agency": (r.get("DataSource") or "").strip(),
                    "lat": lat, "lon": lon, "elev": _num(r.get("Elevation")), "t": int(t.timestamp()),
                    "aqi": int(aqi), "pm": _num(r.get("PM25"))})
    return out


def _stamp(s):
    """'2026-09-28T01:00:00Z' -> epoch seconds"""
    return int(dt.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc).timestamp())


def parse_airfire(meta_text, raw_text, nowcast_text):
    """AirFire's wide hourly files -> the same records for temporary monitors. An hour counts only with a raw value:
    the newest row is the hour in progress, raw all NA and NowCast carried forward (checked 2026-09-28)."""
    raw = list(csv.reader(io.StringIO(raw_text)))
    nc = list(csv.reader(io.StringIO(nowcast_text)))
    if not raw or not nc:
        return []
    rcol = {d: i for i, d in enumerate(raw[0])}
    ncol = {d: i for i, d in enumerate(nc[0])}
    nrow = {r[0]: r for r in nc[1:] if r}
    out = []
    for m in csv.DictReader(io.StringIO(meta_text)):
        dev = m.get("deviceDeploymentID")
        if m.get("deploymentType") != "Temporary" or dev not in rcol or dev not in ncol:
            continue
        lat, lon = _num(m.get("latitude")), _num(m.get("longitude"))
        if lat is None or lon is None:
            continue
        addr = (m.get("address") or "").strip()
        name = addr.split(",")[0].strip() if addr and addr != "NA" else (m.get("locationName") or dev)
        agency = m.get("airnow_agencyName") or ""
        for r in raw[1:]:
            if len(r) <= rcol[dev]:
                continue
            n = nrow.get(r[0])
            pm = _num(r[rcol[dev]])
            c = _num(n[ncol[dev]]) if n and len(n) > ncol[dev] else None
            if pm is None or c is None:
                continue
            try:
                t = _stamp(r[0])
            except ValueError:
                continue
            out.append({"id": dev, "name": name, "agency": "" if agency == "NA" else agency, "lat": lat, "lon": lon,
                        "elev": _num(m.get("elevation")), "t": t, "aqi": aqi_from_pm25(c), "pm": pm})
    return out


def in_window(lat, lon, bbox):
    lat0, lat1, lon0, lon1 = bbox
    return lat0 <= lat <= lat1 and lon0 <= lon <= lon1


def merge(store, recs, temp, bbox):
    """add records to the store (a revised hour overwrites); records outside the region window are dropped"""
    st = store.setdefault("st", {})
    for r in recs:
        if not in_window(r["lat"], r["lon"], bbox):
            continue
        s = st.setdefault(r["id"], {"h": {}})
        s.update(name=r["name"], agency=r["agency"], lat=r["lat"], lon=r["lon"], elev=r["elev"], temp=temp)
        s["h"][str(r["t"])] = [r["aqi"], None if r["pm"] is None else round(r["pm"], 1)]
    return store


def prune(store, newest):
    """drop hours older than the 72 h window ending at newest (a UTC hour start), then stations left empty"""
    first = newest - (KEEP_H - 1) * 3600
    st = store.get("st", {})
    for sid in list(st):
        h = st[sid]["h"]
        for k in [k for k in h if int(k) < first]:
            del h[k]
        if not h:
            del st[sid]
    store["have"] = sorted(t for t in store.get("have", []) if t >= first)
    return store


def to_airq(store, newest, now):
    """the window.AIRQ object: 72 hour slots ending at newest, one aqi and one pm value per slot (None = no report)"""
    hours = [newest - (KEEP_H - 1 - i) * 3600 for i in range(KEEP_H)]
    stations = []
    for sid in sorted(store.get("st", {})):
        s = store["st"][sid]
        vals = [s["h"].get(str(t)) for t in hours]
        stations.append({"id": sid, "name": s["name"], "agency": s["agency"], "lat": s["lat"], "lon": s["lon"],
                         "elev": s["elev"], "temp": s["temp"],
                         "aqi": [v[0] if v else None for v in vals], "pm": [v[1] if v else None for v in vals]})
    g = store.get("grid")
    return {"updated": dt.datetime.fromtimestamp(now).strftime("%a %b %d %I:%M %p"), "updated_t": int(now),
            "hours": hours, "grid": {"t": g["t"], "file": g["file"]} if g else None, "stations": stations}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_airquality.py -v`
Expected: all PASS (24 tests, 13 of them the parametrized breakpoint cases).

- [ ] **Step 5: Commit**

```bash
git add airquality.py tests/test_airquality.py
git commit -m "airquality: parse AirNow hourly files and AirFire temporary monitors; 72 h store; AIRQ object

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Fetching, backfill and `build()` (stations only)

**Files:**
- Modify: `airquality.py` (append after `to_airq`)
- Test: `tests/test_airquality.py` (append)

**Interfaces:**
- Consumes: everything from Task 1.
- Produces:
  - `airquality.fetch(url: str) -> tuple[bytes, str]` (body, Last-Modified). Raises `airquality.NotPosted` on HTTP 403/404.
  - `airquality.head_last_modified(url: str) -> str`
  - `airquality.hourly_url(t: int) -> str`
  - `airquality.load_store() -> dict`
  - `airquality.build(log=print, now: float | None = None) -> int` (number of stations written). Raises `RuntimeError` and leaves `OUT` untouched when neither AirNow nor AirFire returned anything.
  - `airquality.build_grid(store: dict, log=print) -> bool` is called by `build()`. Task 2 adds a stub that returns `False`; Task 3 replaces it.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_airquality.py`:

```python
# ---------- build(): fetch, backfill, keep last good ----------
import urllib.error          # noqa: E402

NOW = T00 + 2 * 3600 + 1800          # 02:30 UTC: 01 UTC may not be posted yet, 00 and 23 are
LM = "Mon, 28 Sep 2026 01:44:48 GMT"


def serve(files, calls=None):
    """fake airquality.fetch: url -> text (or an Exception to raise); anything else is not posted"""
    def fetch(url):
        if calls is not None:
            calls.append(url)
        v = files.get(url)
        if v is None:
            raise airquality.NotPosted(url)
        if isinstance(v, Exception):
            raise v
        return v.encode(), LM
    return fetch


def af_urls(meta, raw, nc):
    return {airquality.AIRFIRE + "airnow_PM2.5_latest_meta.csv": meta,
            airquality.AIRFIRE + "airnow_PM2.5_latest_data.csv": raw,
            airquality.AIRFIRE + "airnow_PM2.5_nowcast_latest_data.csv": nc}


def seattle(t, aqi, pm="8.0"):
    return hourly(t, [row("530330080", "Seattle-10th & Weller", "47.5965", "-122.3197", when(t), str(aqi), pm)])


@pytest.fixture
def job(tmp_path, monkeypatch):
    monkeypatch.setattr(airquality, "OUT", str(tmp_path / "airquality.js"))
    monkeypatch.setattr(airquality, "STORE", str(tmp_path / "aq_cache.json"))
    monkeypatch.setattr(airquality.region, "bbox", lambda: BBOX)
    monkeypatch.setattr(airquality, "build_grid", lambda store, log=print: False)
    return tmp_path


def read_airq(path):
    text = path.read_text(encoding="utf-8")
    assert text.startswith("window.AIRQ = ")
    return json.loads(text[len("window.AIRQ = "):].rstrip().rstrip(";"))


def test_first_run_writes_permanent_and_temporary_monitors(job, monkeypatch):
    files = {airquality.hourly_url(T00): seattle(T00, 44), airquality.hourly_url(T00 - 3600): seattle(T00 - 3600, 40)}
    files.update(af_urls(*airfire([T00, T00 + 3600, T00 + 7200], [("9", "8.4"), ("2", "4.3"), ("NA", "4.3")])))
    monkeypatch.setattr(airquality, "fetch", serve(files))
    assert airquality.build(log=lambda *a: None, now=NOW) == 2
    a = read_airq(job / "airquality.js")
    assert a["hours"][-1] == T00 + 3600                     # newest: the temporary monitor's 01 UTC hour
    by = {s["id"]: s for s in a["stations"]}
    assert by["530330080"]["aqi"][-3:] == [40, 44, None]
    assert by["d_tmp"]["aqi"][-2:] == [47, 24] and by["d_tmp"]["temp"] is True   # NowCast 8.4 and 4.3 ug/m3
    assert "d_far" not in by                               # outside the window


def test_unposted_top_hour_falls_back(job, monkeypatch):
    calls = []
    files = {airquality.hourly_url(T00): seattle(T00, 44), airquality.hourly_url(T00 - 3600): seattle(T00 - 3600, 40)}
    monkeypatch.setattr(airquality, "fetch", serve(files, calls))
    airquality.build(log=lambda *a: None, now=NOW)
    hourly_calls = [u for u in calls if "HourlyAQObs" in u]
    assert hourly_calls[:3] == [airquality.hourly_url(T00 + 3600), airquality.hourly_url(T00), airquality.hourly_url(T00 - 3600)]


def test_backfill_is_capped_per_run_and_remembered(job, monkeypatch):
    calls = []
    files = {airquality.hourly_url(T00): seattle(T00, 44), airquality.hourly_url(T00 - 3600): seattle(T00 - 3600, 40)}
    monkeypatch.setattr(airquality, "fetch", serve(files, calls))
    airquality.build(log=lambda *a: None, now=NOW)
    first = [u for u in calls if "HourlyAQObs" in u]
    assert len(first) == 3 + airquality.BACKFILL_PER_RUN      # 01 (not posted), 00, 23, then 24 older hours
    calls.clear()
    airquality.build(log=lambda *a: None, now=NOW + 900)
    second = [u for u in calls if "HourlyAQObs" in u]
    assert airquality.hourly_url(T00 - 3 * 3600) not in second   # asked last run: not again
    assert len(second) == 3 + airquality.BACKFILL_PER_RUN        # the next 24 missing hours


def test_second_run_takes_the_revised_hour(job, monkeypatch):
    files = {airquality.hourly_url(T00): seattle(T00, 44), airquality.hourly_url(T00 - 3600): seattle(T00 - 3600, 40)}
    monkeypatch.setattr(airquality, "fetch", serve(files))
    airquality.build(log=lambda *a: None, now=NOW)
    files[airquality.hourly_url(T00)] = seattle(T00, 47, "9.9")
    airquality.build(log=lambda *a: None, now=NOW + 900)
    s = read_airq(job / "airquality.js")["stations"][0]
    assert s["aqi"][-1] == 47 and s["pm"][-1] == 9.9


def test_everything_down_keeps_the_last_good_file(job, monkeypatch):
    out = job / "airquality.js"
    out.write_text('window.AIRQ = {"stations": [1]};\n', encoding="utf-8")
    monkeypatch.setattr(airquality, "fetch", serve({}))
    with pytest.raises(RuntimeError):
        airquality.build(log=lambda *a: None, now=NOW)
    assert out.read_text(encoding="utf-8") == 'window.AIRQ = {"stations": [1]};\n'


def test_airfire_down_still_writes_permanent_monitors(job, monkeypatch):
    logs = []
    files = {airquality.hourly_url(T00): seattle(T00, 44)}
    files.update({u: urllib.error.URLError("timed out") for u in af_urls("", "", "")})
    monkeypatch.setattr(airquality, "fetch", serve(files))
    assert airquality.build(log=logs.append, now=NOW) == 1
    assert any("AirFire" in m and "failed" in m for m in logs)


def test_grid_failure_still_writes_stations(job, monkeypatch):
    logs = []

    def broken(store, log=print):
        raise RuntimeError("cfgrib exploded")
    monkeypatch.setattr(airquality, "build_grid", broken)
    monkeypatch.setattr(airquality, "fetch", serve({airquality.hourly_url(T00): seattle(T00, 44)}))
    assert airquality.build(log=logs.append, now=NOW) == 1
    assert "grid FAILED" in logs[-1]


def test_corrupt_store_starts_fresh(job, monkeypatch):
    (job / "aq_cache.json").write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(airquality, "fetch", serve({airquality.hourly_url(T00): seattle(T00, 44)}))
    assert airquality.build(log=lambda *a: None, now=NOW) == 1
    assert json.loads((job / "aq_cache.json").read_text(encoding="utf-8"))["v"] == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_airquality.py -v -k "build or run or posted or backfill or down or grid_failure or corrupt"`
Expected: FAIL with `AttributeError: module 'airquality' has no attribute 'hourly_url'` (or `build_grid`, `AIRFIRE` use).

- [ ] **Step 3: Write the implementation**

Append to `airquality.py`:

```python
def fetch(url):
    """-> (bytes, Last-Modified). The five region steps of one Actions job share each download for CACHE_MAX_AGE_S."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = os.path.join(CACHE_DIR, hashlib.sha1(url.encode()).hexdigest())
    if os.path.exists(path) and os.path.exists(path + ".lm") and time.time() - os.path.getmtime(path) < CACHE_MAX_AGE_S:
        with open(path, "rb") as f, open(path + ".lm", encoding="utf-8") as g:
            return f.read(), g.read()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=TIMEOUT) as r:
            body, lm = r.read(), r.headers.get("Last-Modified") or ""
    except urllib.error.HTTPError as e:
        if e.code in (403, 404):          # S3 answers 403 for a key that does not exist
            raise NotPosted(url) from e
        raise
    with open(path + ".lm", "w", encoding="utf-8") as g:
        g.write(lm)
    with open(path + ".tmp", "wb") as f:
        f.write(body)
    os.replace(path + ".tmp", path)
    return body, lm


def head_last_modified(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA}, method="HEAD")
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.headers.get("Last-Modified") or ""


def hourly_url(t):
    d = dt.datetime.fromtimestamp(t, dt.timezone.utc)
    return "%s/%s/%s/HourlyAQObs_%s.dat" % (AIRNOW, d.strftime("%Y"), d.strftime("%Y%m%d"), d.strftime("%Y%m%d%H"))


def load_store():
    try:
        with open(STORE, encoding="utf-8") as f:
            s = json.load(f)
        if isinstance(s, dict) and s.get("v") == 1:
            return s
    except (OSError, ValueError):
        pass
    return {"v": 1}


def _write(path, text):
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(path + ".tmp", path)


def _name(url):
    return url.rsplit("/", 1)[-1]


def build_grid(store, log=print):
    """replaced in Task 3"""
    return False


def build(log=print, now=None):
    t_start = time.time()
    now = now or time.time()
    bbox = region.bbox()
    store = load_store()
    have = set(store.get("have", []))
    top = int(now) // 3600 * 3600 - 3600          # newest hour AirNow could have posted (UTC hour start)
    got = []
    for t in (top, top - 3600, top - 7200):       # the two newest posted hours, every run (AirNow revises the older one)
        if len(got) == 2:
            break
        try:
            body, _ = fetch(hourly_url(t))
        except NotPosted:
            continue
        except Exception as e:  # noqa: BLE001
            log("airquality: %s failed: %r" % (_name(hourly_url(t)), e))
            continue
        merge(store, parse_hourly(body.decode("utf-8", "replace")), False, bbox)
        got.append(t)
    newest = max(got) if got else None
    n_back = 0
    if newest is not None:
        have.update(got)
        for t in range(newest - 3600, newest - KEEP_H * 3600, -3600):
            if n_back >= BACKFILL_PER_RUN or time.time() - t_start > DEADLINE_S:
                break
            if t in have:
                continue
            try:
                body, _ = fetch(hourly_url(t))
                merge(store, parse_hourly(body.decode("utf-8", "replace")), False, bbox)
            except NotPosted:
                pass                                   # a missing old hour stays missing; don't ask again
            except Exception as e:  # noqa: BLE001
                log("airquality: backfill %s failed: %r" % (_name(hourly_url(t)), e))
                continue
            have.add(t)
            n_back += 1
    temps = []
    try:
        texts = [fetch(AIRFIRE + fn)[0].decode("utf-8", "replace") for fn in
                 ("airnow_PM2.5_latest_meta.csv", "airnow_PM2.5_latest_data.csv", "airnow_PM2.5_nowcast_latest_data.csv")]
        temps = [r for r in parse_airfire(*texts) if in_window(r["lat"], r["lon"], bbox)]
        merge(store, temps, True, bbox)
    except Exception as e:  # noqa: BLE001
        log("airquality: AirFire temporary monitors failed: %r" % e)
    t_temp = max((r["t"] for r in temps), default=None)
    if newest is None and t_temp is None:
        raise RuntimeError("no AirNow or AirFire data this run; keeping the last good file")
    newest = max(t for t in (newest, t_temp) if t is not None)
    store["have"] = sorted(have)
    prune(store, newest)
    try:
        grid = "new" if build_grid(store, log) else "unchanged"
    except Exception as e:  # noqa: BLE001
        grid = "FAILED %r" % e
    airq = to_airq(store, newest, now)
    _write(OUT, "window.AIRQ = %s;\n" % json.dumps(airq, separators=(",", ":")))
    _write(STORE, json.dumps(store, separators=(",", ":")))
    n_temp = sum(1 for s in airq["stations"] if s["temp"])
    log("airquality: %d stations (%d temporary), newest %sZ, %d backfilled, grid %s" % (
        len(airq["stations"]), n_temp, dt.datetime.fromtimestamp(newest, dt.timezone.utc).strftime("%H"), n_back, grid))
    return len(airq["stations"])


if __name__ == "__main__":
    t0 = time.time()
    build()
    print("done in %.0fs" % (time.time() - t0))
```

Note on `test_backfill_is_capped_per_run_and_remembered`: on the second run the loop skips the 24 hours already in `have` without counting them, then asks for the next 24 missing hours (only 70 − 24 = 46 remain, so 24 are asked).

- [ ] **Step 4: Run all the tests**

Run: `python -m pytest tests/ -v`
Expected: all PASS (the whole suite, to catch collisions with `conftest.py`'s network block).

- [ ] **Step 5: Commit**

```bash
git add airquality.py tests/test_airquality.py
git commit -m "airquality: fetch with a runner-shared cache, backfill 24 h a run, keep the last good file

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Interpolated AQI grid (image, value grid) and R2 upload of `frames/aq`

**Files:**
- Modify: `airquality.py` (replace the `build_grid` stub; add `aq_category`, `window_latlon`, `resample`, `colorize`)
- Modify: `r2sync.py:132` (add `"aq"` to the overwritten-image folders)
- Test: `tests/test_airquality.py` (append)

**Interfaces:**
- Consumes: `fetch`, `head_last_modified`, `CACHE_DIR`, `FRAME_DIR`, `STEP`, `AQ_EDGES`, `AQ_COLORS`, `GRID_URL`; `values.write_grid(name, arr, unit, scale)` from `values.py`.
- Produces:
  - `airquality.aq_category(a) -> numpy int array` (0 = Good … 5 = Hazardous; rounds half up)
  - `airquality.window_latlon() -> (lat_rows, lon_cols)` for the region window at `STEP`
  - `airquality.resample(a, lat, lon) -> float32 array (640, 640)`, NaN outside the source grid
  - `airquality.colorize(aqi) -> PIL.Image RGBA`
  - `airquality.build_grid(store, log=print) -> bool`: writes `frames/aq/aqi.webp` and `data/values/aqi.js`, sets `store["grid"] = {"lm", "t", "file"}`; returns False without downloading when Last-Modified is unchanged.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_airquality.py`:

```python
# ---------- grid ----------
def test_unchanged_grid_is_not_downloaded(monkeypatch):
    monkeypatch.setattr(airquality, "head_last_modified", lambda url: LM)

    def no_fetch(url):
        raise AssertionError("downloaded an unchanged grid")
    monkeypatch.setattr(airquality, "fetch", no_fetch)
    store = {"v": 1, "grid": {"lm": LM, "t": T00, "file": "frames/aq/aqi.webp?v=1"}}
    assert airquality.build_grid(store) is False and store["grid"]["lm"] == LM


def test_category_rounds_half_up_like_the_map():
    np = pytest.importorskip("numpy")
    got = airquality.aq_category(np.array([0, 50, 50.4, 50.5, 51, 100, 101, 150, 151, 200, 201, 300, 301, 500]))
    assert got.tolist() == [0, 0, 0, 1, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5]


def test_resample_known_answer():
    np = pytest.importorskip("numpy")
    # a regular grid like AirNow's (latitude ascending, longitude 0..360) that stops at -125 E: AQI 120 north of 48 N, 20 south
    lat = np.arange(40.0, 55.0001, 0.25)
    lon = np.arange(235.0, 250.0001, 0.25)
    a = np.where(lat[:, None] >= 48.0, 120.0, 20.0) * np.ones((1, lon.size))
    g = airquality.resample(a, lat, lon)
    lat_w, lon_w = airquality.window_latlon()
    assert g.shape == (lat_w.size, lon_w.size)
    r_n, r_s = np.argmin(abs(lat_w - 50.0)), np.argmin(abs(lat_w - 45.0))
    c_in, c_out = np.argmin(abs(lon_w + 120.0)), np.argmin(abs(lon_w + 126.0))
    assert g[r_n, c_in] == 120 and g[r_s, c_in] == 20
    assert np.isnan(g[r_n, c_out])                          # west of the source grid


def test_colorize_uses_the_official_colours_and_hides_nan():
    np = pytest.importorskip("numpy")
    pytest.importorskip("PIL")
    img = airquality.colorize(np.array([[0, 51, 101], [151, 201, 301], [np.nan, 50, 100]], dtype=np.float32))
    px = np.asarray(img)
    assert [tuple(px[0, 0, :3]), tuple(px[0, 1, :3]), tuple(px[1, 2, :3])] == [(0, 228, 0), (255, 255, 0), (126, 0, 35)]
    assert px[2, 0, 3] == 0 and px[2, 1, 3] == 255


def test_all_blank_grid_is_transparent(tmp_path, monkeypatch):
    np = pytest.importorskip("numpy")
    pytest.importorskip("PIL")
    import values
    img = airquality.colorize(np.full((640, 640), np.nan, dtype=np.float32))
    assert np.asarray(img)[..., 3].max() == 0
    monkeypatch.setattr(values, "OUT_DIR", str(tmp_path))
    path = values.write_grid("aqi", np.full((640, 640), np.nan, dtype=np.float32), unit="AQI", scale=1)
    assert set(open(path, encoding="utf-8").read().split('data="')[1].split('"')[0].split(",")) == {"-1"}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_airquality.py -v -k "grid or category or resample or colorize"`
Expected: `test_unchanged_grid_is_not_downloaded` FAILS (the stub never calls `head_last_modified`, so the assertion `store["grid"]["lm"] == LM` still passes but `build_grid` returns False for the wrong reason; the other four FAIL with `AttributeError: ... 'aq_category'`). If the first one passes against the stub, that is expected; it pins the behaviour for Step 3.

- [ ] **Step 3: Write the implementation**

In `airquality.py`, replace the `build_grid` stub with:

```python
def aq_category(a):
    """AQI (number or numpy array) -> category 0 (Good) .. 5 (Hazardous), after rounding half up like the map does"""
    import numpy as np
    return np.digitize(np.floor(np.asarray(a, dtype=float) + 0.5), AQ_EDGES)


def window_latlon():
    """latitudes (rows) and longitudes (columns) of the map window's pixel centres, every STEP pixels"""
    import numpy as np
    z, x0, x1, y0, y1 = region.window()
    n, tile = 2 ** z, 256
    ys = (np.arange(0, (y1 - y0 + 1) * tile, STEP) + STEP / 2) / tile + y0
    xs = (np.arange(0, (x1 - x0 + 1) * tile, STEP) + STEP / 2) / tile + x0
    return np.degrees(np.arctan(np.sinh(np.pi - 2 * np.pi * ys / n))), xs / n * 360.0 - 180.0


def resample(a, lat, lon):
    """nearest-neighbour lookup of a regular lat/lon grid onto the window (either latitude order; longitude 0..360 or
    -180..180), as mrms.py does; NaN outside the source grid"""
    import numpy as np
    lat_w, lon_w = window_latlon()
    lon = np.where(lon > 180, lon - 360, lon)
    iy = np.round((lat_w - lat[0]) / (lat[1] - lat[0])).astype(int)
    ix = np.round((lon_w - lon[0]) / (lon[1] - lon[0])).astype(int)
    oky, okx = (iy >= 0) & (iy < len(lat)), (ix >= 0) & (ix < len(lon))
    g = np.asarray(a, dtype=np.float32)[np.ix_(np.clip(iy, 0, len(lat) - 1), np.clip(ix, 0, len(lon) - 1))]
    g[~oky, :] = np.nan
    g[:, ~okx] = np.nan
    return g


def colorize(aqi):
    """(H, W) AQI -> RGBA image in the official category colours; NaN (AirNow's blanked cells) transparent"""
    import numpy as np
    from PIL import Image
    ok = ~np.isnan(aqi)
    cat = aq_category(np.where(ok, aqi, 0))
    rgb = np.zeros(aqi.shape + (3,), np.uint8)
    for i, c in enumerate(AQ_COLORS):
        rgb[cat == i] = c
    return Image.fromarray(np.dstack([rgb, np.where(ok, 255, 0).astype(np.uint8)]), "RGBA")


def build_grid(store, log=print):
    """AirNow's interpolated NowCast AQI -> frames/aq/aqi.webp and data/values/aqi.js. False (nothing downloaded) when
    its Last-Modified is the one in the store. Checked 2026-09-28: one variable 'aerot', regular lat/lon 1778 x 3700,
    latitude ascending from 20 N, longitude 0..360, blanked cells NaN, valid_time one hour after the data hour."""
    lm = head_last_modified(GRID_URL)
    if lm and lm == (store.get("grid") or {}).get("lm"):
        return False
    import cfgrib
    import numpy as np
    from PIL import Image
    import values
    body, lm2 = fetch(GRID_URL)
    work = os.path.join(CACHE_DIR, "grid")
    os.makedirs(work, exist_ok=True)
    path = os.path.join(work, "current_pm25.grib2")
    with open(path, "wb") as f:
        f.write(body)
    try:
        ds = cfgrib.open_datasets(path)[0]
        lat, lon = ds.latitude.values, ds.longitude.values
        if lat.ndim != 1:
            raise RuntimeError("AirNow grid is not regular lat/lon")
        a = ds[list(ds.data_vars)[0]].values.astype(np.float32)
        with np.errstate(invalid="ignore"):
            a[(a < 0) | (a >= 9999)] = np.nan
        grid = resample(a, lat, lon)
        valid = int(np.datetime64(ds.valid_time.values, "s").astype("int64"))
    finally:
        shutil.rmtree(work, ignore_errors=True)            # the GRIB and cfgrib's .idx files
    os.makedirs(FRAME_DIR, exist_ok=True)
    img = colorize(grid)
    img = img.resize((img.width * STEP, img.height * STEP), Image.NEAREST)
    tmp = os.path.join(FRAME_DIR, "aqi.tmp.webp")
    img.save(tmp, "WEBP", lossless=True)
    os.replace(tmp, os.path.join(FRAME_DIR, "aqi.webp"))
    values.write_grid("aqi", grid, unit="AQI", scale=1)
    store["grid"] = {"lm": lm or lm2, "t": valid, "file": "frames/aq/aqi.webp?v=%d" % int(time.time())}
    log("airquality: grid valid %s, %d%% of the window has data" % (
        dt.datetime.fromtimestamp(valid, dt.timezone.utc).strftime("%H:%MZ"), round(100 * float(np.isfinite(grid).mean()))))
    return True
```

In `r2sync.py`, line 132, change:

```python
    for sub in ("accum", "interp", "forecast", "mrms", "freezing", "snodas"):
```

to:

```python
    for sub in ("accum", "interp", "forecast", "mrms", "freezing", "snodas", "aq"):
```

- [ ] **Step 4: Run all the tests**

Run: `python -m pytest tests/ -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add airquality.py r2sync.py tests/test_airquality.py
git commit -m "airquality: AirNow's interpolated AQI as a category image and click-anywhere grid; r2sync uploads frames/aq

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Wire into the 15-minute job, then the data check (GATE: stop for Chris)

**Files:**
- Modify: `capture.py:220-224` (call `airquality.build` after alerts, inside `if not HOURLY_ONLY`)
- Modify: `cloud.py:18-20, 38-39, 111-113` (docstring, `STATE_FILES`, comment)
- Create: `smoke_research/aq_check.py` (the data check; its PNG output is gitignored by `*.png`)

**Interfaces:**
- Consumes: `airquality.build`, `airquality.fetch`, `airquality.parse_hourly`, `airquality.parse_airfire`, `airquality.aqi_from_pm25`, `airquality.hourly_url`, `airquality.in_window`, `airquality.AIRFIRE`, `airquality.OUT`, `airquality.FRAME_DIR`, `region.bbox()`, `region.window()`.
- Produces: the live job writes the three files for every region; `aq_cache.json` persists in R2 state.

- [ ] **Step 1: Wire the job**

In `capture.py`, after the alerts block (currently lines 220-224):

```python
        try:
            import alerts
            ok.append("alerts %d" % alerts.build(log))
        except Exception as e:  # noqa: BLE001
            log("alerts FAILED: %r" % e)
```

add, at the same indentation:

```python
        try:
            import airquality
            ok.append("airquality %d" % airquality.build(log))
        except Exception as e:  # noqa: BLE001
            log("airquality FAILED: %r" % e)
```

Also update the comment on `HOURLY_ONLY` (line 65) to read:

```python
HOURLY_ONLY = False      # hourly job: skip radar, satellite, accumulation, manifest, alerts and air quality (the radar job owns those)
```

In `cloud.py`, change lines 18-20 of the docstring to:

```
The two modes write disjoint sets of files (radar: frames, accumulation, manifest, alerts, air quality;
hourly: stations, rivers, forecast, MRMS QPE, freezing level, SNODAS, webcams, avalanche,
basins), so they run at the same time without sharing a lock.
```

append `"aq_cache.json"` to `STATE_FILES` (lines 38-39):

```python
STATE_FILES = ["dem_z7.npy", "huc6.geojson", "station_meta_cache.json", "snotel_meta_cache.json", "usgs_median_cache.json", "nwps_cache.json",
               "usgs_lid_cache.json", "nws_stations_cache.json", "zone_cache.json", "snodas.js", "youtube_cache.json", "aq_cache.json"]
```

and change the comment at lines 111-113 to:

```python
    # ---- 3. one cycle: "radar" mode is the quick 15-minute pass (radar, satellite, accumulation,
    #         alerts, air quality); "hourly" mode also runs stations, rivers, forecast, MRMS, freezing level,
    #         SNODAS, webcams, avalanche and basins ----
```

Run: `python -m pytest tests/ -v`
Expected: all PASS.

- [ ] **Step 2: Write the data check script**

Create `smoke_research/aq_check.py`:

```python
"""
Data check for the air quality layer (spec: "Data check (gate before any map code)").

Runs airquality.build() for one region WITHOUT uploading (it never calls r2sync), then:
  1. accounting: rows read, PM2.5 rows, inside the window, temporary monitors, skipped and why
  2. independent check: our AQI per permanent station vs USFS AirFire's NowCast for the same monitor and hour,
     converted with the 2024 breakpoints; grid value at each station vs its station AQI
  3. temporary monitors: our breakpoint conversion vs AirNow's own NowCast AQI in AirNowWildfire.csv
  4. a MATLAB-style figure: the grid with stations on top, and three stations' 72 h series

Usage (from radar/):  python smoke_research/aq_check.py [region]      figure -> smoke_research/checks/aq_check_<region>.png
"""
import csv
import io
import json
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ["REGION"] = (sys.argv[1] if len(sys.argv) > 1 else "pnw")
sys.path.insert(0, ROOT)

import airquality  # noqa: E402
import region  # noqa: E402


def text(url):
    return airquality.fetch(url)[0].decode("utf-8", "replace")


def main():
    bbox = region.bbox()
    n = airquality.build(log=print)
    with open(airquality.OUT, encoding="utf-8") as f:
        airq = json.loads(f.read()[len("window.AIRQ = "):].rstrip().rstrip(";"))
    hours = airq["hours"]

    # ---- 1. accounting (newest AirNow file) ----
    perm = [s for s in airq["stations"] if not s["temp"]]
    newest_perm = max((i for s in perm for i, v in enumerate(s["aqi"]) if v is not None), default=len(hours) - 1)
    t = hours[newest_perm]
    body = text(airquality.hourly_url(t))
    lines = body.strip().splitlines()
    recs = airquality.parse_hourly(body)
    inside = [r for r in recs if airquality.in_window(r["lat"], r["lon"], bbox)]
    print("\n== accounting, HourlyAQObs %s ==" % airquality.hourly_url(t).rsplit("_", 1)[1])
    print("rows %d; with a PM2.5 AQI %d; skipped (no PM2.5 AQI, bad or missing fields) %d; inside the %s window %d"
          % (len(lines) - 1, len(recs), len(lines) - 1 - len(recs), region.KEY, len(inside)))
    meta = list(csv.DictReader(io.StringIO(text(airquality.AIRFIRE + "airnow_PM2.5_latest_meta.csv"))))
    tmp = [m for m in meta if m.get("deploymentType") == "Temporary"]
    tmp_in = [m for m in tmp if airquality.in_window(float(m["latitude"]), float(m["longitude"]), bbox)]
    print("AirFire temporary monitors: %d nationally, %d inside the window, %d with a raw value in the last 72 h (on the map)"
          % (len(tmp), len(tmp_in), sum(1 for s in airq["stations"] if s["temp"])))
    print("AIRQ: %d stations written (%d permanent, %d temporary)" % (n, len(perm), n - len(perm)))

    # ---- 2. independent check: AirNow's AQI vs AirFire NowCast -> 2024 breakpoints, same monitor, same hour ----
    # (AirFire's hourly NowCast file, not its "latest" GeoJSON: AirFire's latest hour often runs one ahead of AirNow's newest file)
    nc_rows = list(csv.reader(io.StringIO(text(airquality.AIRFIRE + "airnow_PM2.5_nowcast_latest_data.csv"))))
    perm_dev = {m["deviceDeploymentID"]: m.get("AQSID") for m in meta if m.get("deploymentType") != "Temporary"}
    col = {}
    for i, d in enumerate(nc_rows[0]):
        if d in perm_dev and perm_dev[d] not in col:
            col[perm_dev[d]] = i
    byhour = {}
    for r in nc_rows[1:]:
        try:
            byhour[airquality._stamp(r[0])] = r
        except (ValueError, IndexError):
            pass
    same = within2 = compared = 0
    outliers = []
    for s in perm:
        last = max((i for i, v in enumerate(s["aqi"]) if v is not None), default=None)
        if last is None or s["id"] not in col or hours[last] not in byhour:
            continue
        nc = airquality._num(byhour[hours[last]][col[s["id"]]])
        if nc is None:
            continue
        ours, theirs = s["aqi"][last], airquality.aqi_from_pm25(nc)
        compared += 1
        same += ours == theirs
        within2 += abs(ours - theirs) <= 2
        if abs(ours - theirs) > 5:
            outliers.append((s["name"], ours, theirs, nc))
    print("\n== independent check: AirNow PM25_AQI vs AirFire NowCast (2024 breakpoints), same monitor and hour ==")
    print("compared %d stations: exact %d (%.0f%%), within 2 AQI %d (%.0f%%); research expectation ~93%% / ~97%%"
          % (compared, same, 100 * same / max(compared, 1), within2, 100 * within2 / max(compared, 1)))
    for o in outliers[:15]:
        print("  outlier: %s  AirNow %d  ours-from-AirFire %d  (NowCast %.1f)" % o)

    # grid value at each station vs station AQI (newest hour with both)
    vals_path = os.path.join(region.data_dir(), "values", "aqi.js")
    if airq["grid"] and os.path.exists(vals_path):
        with open(vals_path, encoding="utf-8") as f:
            vt = f.read()
        data = [int(v) for v in vt.split('.data="')[1].split('"')[0].split(",")]
        z, x0, x1, y0, y1 = region.window()
        nn = 2 ** z
        diffs = []
        for s in perm:
            v = s["aqi"][-1] if s["aqi"][-1] is not None else s["aqi"][-2]
            if v is None:
                continue
            mx = (s["lon"] + 180) / 360 * nn
            my = (1 - math.log(math.tan(math.radians(s["lat"])) + 1 / math.cos(math.radians(s["lat"]))) / math.pi) / 2 * nn
            px, py = int((mx - x0) / (x1 - x0 + 1) * 256), int((my - y0) / (y1 - y0 + 1) * 256)
            if 0 <= px < 256 and 0 <= py < 256 and data[py * 256 + px] >= 0:
                diffs.append(abs(data[py * 256 + px] - v))
        diffs.sort()
        if diffs:
            print("grid at %d stations: mean |grid - station| %.1f AQI, median %.0f, 90th pct %.0f (research: mean 1.0 at 713 sites;"
                  " the value grid is 256 x 256 block means, so expect more here)"
                  % (len(diffs), sum(diffs) / len(diffs), diffs[len(diffs) // 2], diffs[int(0.9 * (len(diffs) - 1))]))

    # ---- 3. temporary monitors: our conversion vs AirNow's own NowCast AQI ----
    wf = list(csv.DictReader(io.StringIO(text("https://files.airnowtech.org/airnow/today/AirNowWildfire.csv"))))
    agree = total = 0
    for r in wf:
        c, a = airquality._num(r.get("NowCast Concentration")), airquality._num(r.get("NowCast AQI"))
        if c is None or a is None:
            continue
        total += 1
        agree += airquality.aqi_from_pm25(c) == int(a)
    print("\n== temporary monitors: aqi_from_pm25(NowCast conc) vs AirNow's NowCast AQI (AirNowWildfire.csv, all rows) ==")
    print("%d of %d agree exactly" % (agree, total))

    # ---- 4. figure ----
    figure(airq)


def figure(airq):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from PIL import Image
    plt.style.use("matlab")
    z, x0, x1, y0, y1 = region.window()
    nn, W = 2 ** z, (x1 - x0 + 1) * 256

    def px(lat, lon):
        mx = (lon + 180) / 360 * nn
        my = (1 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi) / 2 * nn
        return (mx - x0) * 256, (my - y0) * 256

    fig = plt.figure(figsize=(13, 6.5))
    ax = fig.add_axes([0.03, 0.06, 0.5, 0.88])
    img = os.path.join(airquality.FRAME_DIR, "aqi.webp")
    if os.path.exists(img):
        ax.imshow(Image.open(img), extent=(0, W, W, 0), alpha=0.55)
    cols = ["#00e400", "#ffff00", "#ff7e00", "#ff0000", "#8f3f97", "#7e0023"]
    for s in airq["stations"]:
        v = next((x for x in reversed(s["aqi"]) if x is not None), None)
        if v is None:
            continue
        cat = sum(v >= e for e in airquality.AQ_EDGES)
        x, y = px(s["lat"], s["lon"])
        ax.scatter([x], [y], s=30, c=cols[cat], edgecolors="k", linewidths=0.5, marker="s" if s["temp"] else "o", zorder=3)
    ax.set_xlim(0, W)
    ax.set_ylim(W, 0)
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_title("%s: AirNow interpolated AQI with stations (squares = temporary)" % region.KEY, fontsize=10)

    def pick(pred):
        return next((s for s in airq["stations"] if pred(s) and sum(v is not None for v in s["aqi"]) > 12), None)
    picks = [("urban", pick(lambda s: not s["temp"] and any(k in s["name"] for k in ("Seattle", "Portland", "Boise", "Reno", "Salt Lake", "Denver", "Boston")))),
             ("mountain valley", pick(lambda s: not s["temp"] and any(k in s["name"] for k in ("Winthrop", "Twisp", "Leavenworth", "Wenatchee", "Cle Elum", "Ellensburg", "Truckee", "Mammoth", "Missoula", "Hamilton", "Aspen", "Steamboat")))),
             ("temporary", pick(lambda s: s["temp"]))]
    hrs = [(t - airq["hours"][-1]) / 3600 for t in airq["hours"]]
    for k, (label, s) in enumerate(picks):
        a = fig.add_axes([0.6, 0.72 - k * 0.31, 0.37, 0.22])
        if not s:
            a.set_title("%s: none in this region" % label, fontsize=9)
            continue
        a.bar(hrs, [v if v is not None else 0 for v in s["aqi"]], width=0.9, color="#8fa7c7", label="AQI")
        a2 = a.twinx()
        a2.plot(hrs, [v if v is not None else float("nan") for v in s["pm"]], color="#b5654a", lw=1.2, label="raw PM2.5")
        a.set_ylabel("AQI", fontsize=8)
        a2.set_ylabel("ug/m3", fontsize=8)
        a.set_title("%s: %s (%s)" % (label, s["name"], s["id"]), fontsize=9)
        a.set_xlim(-72, 1)
    fig.axes[-1].set_xlabel("hours before newest")
    out = os.path.join(ROOT, "smoke_research", "checks", "aq_check_%s.png" % region.KEY)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    fig.savefig(out, dpi=110)
    print("\nfigure:", out)


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Run the data check for pnw, twice**

Run (from `radar/`): `python smoke_research/aq_check.py pnw`
Expected on the first run: an `airquality:` log line with "24 backfilled" and "grid new", the accounting block, the independent check at roughly 90 % exact or better, "N of N agree exactly" for the temporary conversion (any disagreement is a bug in `aqi_from_pm25`: stop and fix), and the figure path.
Run it a second and third time: backfill finishes (70 hours in `have`) and the grid shows "unchanged" unless AirNow posted a new one.
Then run `python smoke_research/aq_check.py ne` once, to see a region with Canadian stations and no temporary monitors.

- [ ] **Step 4: Commit**

```bash
git add capture.py cloud.py smoke_research/aq_check.py
git commit -m "airquality: run in the 15-minute radar job; aq_cache.json in R2 state; data check script

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 5: GATE: show Chris, then stop**

Send Chris the figure (`smoke_research/checks/aq_check_pnw.png`) and paste the accounting and check blocks. Walk through: what was skipped and why; the agreement figures and any outliers (list rival explanations for each outlier: AirNow and AirFire on different hours, a revised hour, a monitor with two instruments, a real conversion bug); whether the three series look physically plausible (an urban diurnal cycle, a valley inversion building overnight). Log anything odd in `ANOMALY_LOG.md`. Do not start Task 5 until Chris says go. Nothing is pushed yet; the job only goes live when Chris pushes after Task 8.

---

### Task 5: Map helpers (categories, staleness, trend, escaping) with node tests

**Files:**
- Modify: `map.html` (insert the `aqHelpers` block just before `  // ---------- NWS alerts ----------`, currently line 1112)
- Test: `tests/test_map_airquality.py`

**Interfaces:**
- Produces (inside the map's IIFE, used by Tasks 6-7): `AQ_BINS` (`[[0,'#00e400'],…]`), `AQ_NAMES`, `aqCat(v) -> -1..5`, `aqLast(s) -> {i, aqi, pm} | null`, `aqStale(s, hours, nowSec) -> bool`, `aqTrend(pm) -> 'rising'|'falling'|'steady'|null`, `aqEsc(s) -> string`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_map_airquality.py`:

```python
"""Air quality helpers in map.html (aqHelpers block), run under node; skipped where node is missing."""
import json
import os
import re
import shutil
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node not installed")


def run(expr):
    with open(os.path.join(ROOT, "map.html"), encoding="utf-8") as f:
        html = f.read()
    block = re.search(r"// BEGIN aqHelpers[^\n]*\n(.*?)// END aqHelpers", html, re.S).group(1)
    js = block + "\nprocess.stdout.write(JSON.stringify(" + expr + "));"
    return json.loads(subprocess.run([NODE, "-e", js], capture_output=True, text=True, check=True).stdout)


def test_categories_at_every_edge():
    edges = [0, 50, 51, 100, 101, 150, 151, 200, 201, 300, 301, 500, 50.4, 50.5]
    assert run("[" + ",".join(map(str, edges)) + "].map(aqCat)") == [0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 0, 1]
    assert run("[null, NaN].map(aqCat)") == [-1, -1]


def test_colours_and_names_are_the_official_ones():
    assert run("AQ_BINS") == [[0, "#00e400"], [51, "#ffff00"], [101, "#ff7e00"], [151, "#ff0000"], [201, "#8f3f97"], [301, "#7e0023"]]
    assert run("AQ_NAMES") == ["Good", "Moderate", "Unhealthy for sensitive groups", "Unhealthy", "Very unhealthy", "Hazardous"]


def test_last_report_and_staleness():
    s = '{aqi: [40, 44, null, null], pm: [7, 8, null, null]}'
    hours = "[0, 3600, 7200, 10800]"
    assert run("aqLast(" + s + ")") == {"i": 1, "aqi": 44, "pm": 8}
    # last report is the hour 3600-7200; stale once more than 3 h have passed since 7200
    assert run("aqStale(" + s + ", " + hours + ", 7200 + 3 * 3600)") is False
    assert run("aqStale(" + s + ", " + hours + ", 7200 + 3 * 3600 + 1)") is True
    assert run("aqStale({aqi: [null], pm: [null]}, [0], 10)") is True


@pytest.mark.parametrize("pm,trend", [
    ([10, 10, 10, 16], "rising"),            # +6, and 6 >= 20 % of 10
    ([30, 30, 30, 35], "steady"),            # +5 but under 20 % of 30
    ([40, 40, 40, 30], "falling"),           # -10, and 10 >= 20 % of 40
    ([10, None, 10, 12], "steady"),
    ([None, 10, 10, 16], None),              # no value 3 h before the latest
    ([5, 5], None),
    ([10, 10, 10, 16, None], "rising"),      # trailing gap: the latest value is the one that counts
])
def test_trend(pm, trend):
    assert run("aqTrend(" + json.dumps(pm) + ")") == trend


def test_escape():
    assert run("aqEsc('<b>A & \"B\"</b>')") == "&lt;b&gt;A &amp; &quot;B&quot;&lt;/b&gt;"
    assert run("aqEsc(null)") == ""
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_map_airquality.py -v`
Expected: FAIL with `AttributeError: 'NoneType' object has no attribute 'group'` (the block is not in map.html yet).

- [ ] **Step 3: Write the implementation**

In `map.html`, insert just before `  // ---------- NWS alerts ----------`:

```js
  // ---------- Air quality: helpers ----------
  // BEGIN aqHelpers (tests/test_map_airquality.py runs this block under node)
  // EPA AQI categories and official colours (AQI Technical Assistance Document, May 2024); AirNow's guidelines ask for them
  const AQ_BINS = [[0, '#00e400'], [51, '#ffff00'], [101, '#ff7e00'], [151, '#ff0000'], [201, '#8f3f97'], [301, '#7e0023']];
  const AQ_NAMES = ['Good', 'Moderate', 'Unhealthy for sensitive groups', 'Unhealthy', 'Very unhealthy', 'Hazardous'];
  function aqCat(v) {      // AQI -> 0..5, -1 for no value; half rounds up (airquality.aq_category does the same)
    if (v == null || isNaN(v)) return -1;
    const r = Math.floor(v + 0.5); let i = 0;
    for (let k = 1; k < AQ_BINS.length; k++) if (r >= AQ_BINS[k][0]) i = k;
    return i;
  }
  function aqLast(s) { for (let i = s.aqi.length - 1; i >= 0; i--) if (s.aqi[i] != null) return { i, aqi: s.aqi[i], pm: s.pm[i] }; return null; }
  // stale: no report for more than 3 h after the end of the last reported hour (judgment call, spec ledger)
  function aqStale(s, hours, nowSec) { const l = aqLast(s); return !l || nowSec - (hours[l.i] + 3600) > 3 * 3600; }
  // latest raw hour vs 3 h earlier: rising / falling if the change is at least 5 ug/m3 and 20 % (judgment call, spec ledger)
  function aqTrend(pm) {
    let i = pm.length - 1; while (i >= 0 && pm[i] == null) i--;
    if (i < 3 || pm[i - 3] == null) return null;
    const a = pm[i - 3], d = pm[i] - a;
    if (d >= 5 && d >= 0.2 * a) return 'rising';
    if (-d >= 5 && -d >= 0.2 * a) return 'falling';
    return 'steady';
  }
  function aqEsc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])); }
  // END aqHelpers

```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_map_airquality.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add map.html tests/test_map_airquality.py
git commit -m "map: air quality helpers (AQI categories, staleness, trend, escaping) with node tests

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Map panel section, AQI stations layer, station card and 72 h chart

**Files:**
- Modify: `map.html:258-260` (new panel group between Water and Hazards)
- Modify: `map.html:823-832` (`attachTracker`: use a point's own label when it has one)
- Modify: `map.html` (station layer code right after the `// END aqHelpers` line from Task 5)
- Modify: `map.html:1303` (`DEF_CHECKS`)
- Test: `tests/test_map_defaults.py` (append one test)

**Interfaces:**
- Consumes: `AQ_BINS`, `AQ_NAMES`, `aqCat`, `aqLast`, `aqStale`, `aqTrend`, `aqEsc` (Task 5); existing `loadScript`, `legendHtml`, `map`, `$`, `attachTracker`, `.stlabel` CSS; `window.AIRQ` shape from Task 1 (`hours`, `stations[{id,name,agency,lat,lon,elev,temp,aqi[],pm[]}]`, `grid`, `updated`).
- Produces: `aqData` (the loaded `AIRQ`), `loadAq()`, `aqLegend()`, element ids `lyAqSt`, `lyAqGrid`, `aqStInfo`, `aqGridInfo` (Task 7 uses `aqData`, `loadAq`, `aqLegend`, `lyAqGrid`, `aqGridInfo`).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_map_defaults.py`:

```python
def test_air_quality_switches_are_saved_with_the_default():
    with open(os.path.join(ROOT, "map.html"), encoding="utf-8") as f:
        html = f.read()
    checks = re.search(r"const DEF_CHECKS = \[([^\]]*)\]", html).group(1)
    assert "'lyAqSt'" in checks and "'lyAqGrid'" in checks
```

Run: `python -m pytest tests/test_map_defaults.py -v`
Expected: the new test FAILS.

- [ ] **Step 2: Add the panel group**

In `map.html`, between the closing `</div>` of the Water group (line 258) and `<div class="sec grp" data-grp="hazards">` (line 260), insert:

```html
  <div class="sec grp" data-grp="air">
    <h2 class="grph"><span class="chev"></span>Air quality <span class="n"></span></h2>
    <div class="body">
    <label class="opt"><input type="checkbox" id="lyAqSt"> AQI stations
      <button type="button" class="help" aria-label="About the AQI stations" aria-expanded="false">?</button>
      <span class="helptip" role="tooltip">Air quality monitors run by state, local, tribal and Canadian agencies, from AirNow. The number is the NowCast AQI for fine particles (PM2.5), the pollutant in wildfire smoke. NowCast weights the latest hours, so it responds within a few hours when smoke arrives; the official daily AQI is a 24 h average and lags. Squares are temporary monitors set up near fires. Data are preliminary and not verified.</span></label>
    <div class="subwrap" data-for="lyAqSt">
      <div class="sub" id="aqStInfo" style="display:block"></div>
    </div>

    <label class="opt"><input type="checkbox" id="lyAqGrid"> Interpolated AQI (monitors only)</label>
    <div class="subwrap" data-for="lyAqGrid">
      <div class="sub" id="aqGridInfo" style="display:block"></div>
    </div>
    </div>
  </div>

```

- [ ] **Step 3: Let chart points carry their own hover label**

In `attachTracker` (around line 831), replace:

```js
      const label = best[2].toLocaleString() + ' cfs · ' + when + (best[4] === 'fc' ? ' (forecast)' : '');
```

with:

```js
      const label = best[5] || (best[2].toLocaleString() + ' cfs · ' + when + (best[4] === 'fc' ? ' (forecast)' : ''));
```

- [ ] **Step 4: Add the station layer, card and chart**

In `map.html`, right after the `  // END aqHelpers` line, insert:

```js
  // ---------- Air quality: AQI stations (AirNow monitors, AirFire temporary smoke monitors) ----------
  const aqLayer = L.layerGroup(), aqLabelLayer = L.layerGroup();
  let aqData = null, aqLabels = [];      // [latlng, label, label marker while shown], as for Weather stations
  function aqLegend() {
    return legendHtml(AQ_BINS, x => String(x)) + '<div class="note" style="margin-top:18px">' + AQ_NAMES.join(' · ') + '</div>';
  }
  function labelAq() {
    const show = map.hasLayer(aqLayer) && map.getZoom() >= 9, b = map.getBounds().pad(.1);
    for (const l of aqLabels) {
      const on = show && b.contains(l[0]);
      if (on && !l[2]) aqLabelLayer.addLayer(l[2] = L.marker(l[0], { interactive: false, keyboard: false, pane: 'tooltipPane', icon: L.divIcon({ className: '', html: '<div class="stlabel stlab">' + l[1] + '</div>', iconSize: null }) }));
      else if (!on && l[2]) { aqLabelLayer.removeLayer(l[2]); l[2] = null; }
    }
  }
  map.on('moveend', labelAq);
  function aqChart(s, hours) {
    const n = hours.length, w = 260, h = 64, bw = (w - 4) / n, base = h - 12;
    const top = Math.max(100, ...s.aqi.filter(v => v != null));
    const Y = v => base - (v / top) * (base - 8);
    let bars = '', ticks = '';
    const pts = [];
    s.aqi.forEach((v, i) => {
      const x = 2 + i * bw, d = new Date(hours[i] * 1000);
      if (d.getHours() === 0) ticks += '<line x1="' + x.toFixed(1) + '" y1="4" x2="' + x.toFixed(1) + '" y2="' + base + '" stroke="#ccc"/><text x="' + (x + 2).toFixed(1) + '" y="' + (h - 2) + '" font-size="9" fill="#666">' + d.toLocaleDateString([], { weekday: 'short' }) + '</text>';
      if (v == null) return;
      const y = Y(v);
      bars += '<rect x="' + x.toFixed(1) + '" y="' + y.toFixed(1) + '" width="' + Math.max(1, bw - 0.6).toFixed(1) + '" height="' + (base - y).toFixed(1) + '" fill="' + AQ_BINS[aqCat(v)][1] + '" stroke="#333" stroke-width=".3"/>';
      const when = d.toLocaleString([], { weekday: 'short', hour: 'numeric' });
      pts.push([+(x + bw / 2).toFixed(1), +y.toFixed(1), v, 0, 'obs', 'AQI ' + v + (s.pm[i] != null ? ' · ' + s.pm[i] + ' µg/m³' : '') + ' · ' + when]);
    });
    if (pts.length < 2) return '';
    return '<svg class="rvchart" width="' + w + '" height="' + h + '" style="display:block;margin:6px 0;cursor:crosshair;overflow:visible" data-pts=\'' + JSON.stringify(pts).replace(/'/g, '&#39;') + '\'>' + ticks + bars +
      '<g class="trk" style="display:none"><line y1="2" y2="' + (h - 2) + '" stroke="#333" stroke-dasharray="2 2"/><circle r="3.5" fill="#fff" stroke="#333" stroke-width="1.5"/><rect rx="3" fill="#111" opacity=".85" height="16"/><text fill="#fff" font-size="11" font-family="system-ui" dy="11.5"></text></g></svg>' +
      '<div style="font-size:11px;color:#666">hourly AQI, last 72 h · hover for values</div>';
  }
  function aqCard(s) {
    const hours = aqData.hours, last = aqLast(s);
    let html = '<div style="font:13px system-ui;min-width:230px"><b>' + aqEsc(s.name) + '</b> <span style="color:#666">' + (s.temp ? 'temporary smoke monitor' : aqEsc(s.agency)) + (s.elev != null ? ' · ' + Math.round(s.elev * 3.28084).toLocaleString() + ' ft' : '') + '</span>';
    if (!last) return html + '<div style="margin:6px 0;color:#666">no report in the last 72 h</div></div>';
    const c = aqCat(last.aqi), t0 = hours[last.i], ago = Math.round((Date.now() / 1000 - (t0 + 3600)) / 60);
    const hr = t => new Date(t * 1000).toLocaleTimeString([], { hour: 'numeric' });
    html += '<div style="display:flex;align-items:center;gap:8px;margin:6px 0"><span style="font-size:22px;font-weight:700">' + last.aqi + '</span><span style="background:' + AQ_BINS[c][1] + ';color:' + (c >= 3 ? '#fff' : '#111') + ';padding:1px 6px;border-radius:3px">' + AQ_NAMES[c] + '</span></div>';
    html += '<div>PM2.5 ' + (last.pm != null ? '<b>' + last.pm + ' µg/m³</b>, ' : '') + hr(t0) + '–' + hr(t0 + 3600) + ' <span style="color:#666">(' + (ago < 90 ? ago + ' min' : Math.round(ago / 60) + ' h') + ' ago)</span></div>';
    const tr = aqTrend(s.pm); if (tr) html += '<div>Last 3 h: <b>' + tr + '</b></div>';
    html += aqChart(s, hours);
    html += '<div style="font-size:11px;color:#666;margin-top:4px">Preliminary data, not verified. Source: AirNow (U.S. EPA)' + (s.temp ? ' via USFS AirFire' : '') + (s.agency ? ', ' + aqEsc(s.agency) : '') + '.</div></div>';
    return html;
  }
  function aqMarker(s, cat) {      // cat -1 = hollow grey (stale or no value)
    if (s.temp) {
      const fill = cat < 0 ? 'transparent' : AQ_BINS[cat][1], bd = cat < 0 ? '#6b7280' : '#111';
      return L.marker([s.lat, s.lon], { icon: L.divIcon({ className: '', iconSize: [12, 12], iconAnchor: [6, 6], popupAnchor: [0, -6], html: '<div style="width:10px;height:10px;background:' + fill + ';border:1px solid ' + bd + '"></div>' }) });
    }
    return cat < 0 ? L.circleMarker([s.lat, s.lon], { radius: 3, color: '#6b7280', weight: 1, fillColor: '#0b1220', fillOpacity: .35 })
                   : L.circleMarker([s.lat, s.lon], { radius: 6, color: '#111', weight: 1, fillColor: AQ_BINS[cat][1], fillOpacity: .95 });
  }
  function renderAq() {
    aqLayer.clearLayers(); aqLabelLayer.clearLayers(); aqLayer.addLayer(aqLabelLayer); aqLabels = [];
    if (!aqData) return;
    const now = Date.now() / 1000; let n = 0, nt = 0;
    for (const s of aqData.stations) {
      const last = aqLast(s), cat = last && !aqStale(s, aqData.hours, now) ? aqCat(last.aqi) : -1;
      const m = aqMarker(s, cat);
      if (cat >= 0) { n++; if (s.temp) nt++; aqLabels.push([m.getLatLng(), String(last.aqi), null]); }
      m.bindPopup(() => aqCard(s), { maxWidth: 300 });
      m.on('mouseover', () => { if (!m.isPopupOpen()) m.openPopup(); });
      aqLayer.addLayer(m);
    }
    labelAq();
    $('aqStInfo').innerHTML = '<div class="muted">' + n + ' of ' + aqData.stations.length + ' stations reporting (' + nt + ' temporary) · updated ' + aqData.updated + '</div>' + aqLegend() +
      '<div class="note">NowCast AQI for PM2.5 (smoke and fine particles), hourly; preliminary data from AirNow and reporting agencies. Squares: temporary smoke monitors. Hollow: no report for 3 h.</div>';
  }
  function loadAq() {
    loadScript('data/airquality.js', () => {
      aqData = window.AIRQ || aqData;
      if (map.hasLayer(aqLayer)) renderAq();
      if (window.renderAqGrid && $('lyAqGrid').checked) window.renderAqGrid();
    }, () => { $('aqStInfo').innerHTML = '<div class="muted">air quality data not available yet</div>'; });
  }
  $('lyAqSt').onchange = e => { if (e.target.checked) { aqLayer.addTo(map); if (!aqData) loadAq(); else renderAq(); } else map.removeLayer(aqLayer); };
  setInterval(() => { if (map.hasLayer(aqLayer) || $('lyAqGrid').checked) loadAq(); }, 15 * 60 * 1000);

```

(`window.renderAqGrid` is defined in Task 7; the guard keeps this task working on its own.)

- [ ] **Step 5: Save the switches with the default**

In `map.html`, line 1303, change:

```js
  const DEF_CHECKS = ['lyRadar', 'lySat', 'lyStations', 'lyCams', 'lyFz', 'fzBands', 'lyFcst', 'lyAvy', 'lyAccum', 'lySnodas', 'lySnotel', 'lyRivers', 'lyStf', 'lyAlerts'];
```

to:

```js
  const DEF_CHECKS = ['lyRadar', 'lySat', 'lyStations', 'lyCams', 'lyFz', 'fzBands', 'lyFcst', 'lyAvy', 'lyAccum', 'lySnodas', 'lySnotel', 'lyRivers', 'lyStf', 'lyAqSt', 'lyAqGrid', 'lyAlerts'];
```

- [ ] **Step 6: Run the tests**

Run: `python -m pytest tests/ -v`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add map.html tests/test_map_defaults.py
git commit -m "map: Air quality section with AQI stations, station card and 72 h chart

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Interpolated AQI overlay and the click-anywhere air quality line

**Files:**
- Modify: `map.html` (overlay code right after Task 6's station layer block; click handler after the avalanche line, currently ~1234; `applyData`, currently line 1255)

**Interfaces:**
- Consumes: `aqData`, `loadAq`, `aqLegend`, `aqLast`, `aqStale`, `aqCat`, `aqEsc`, `AQ_NAMES` (Tasks 5-6); existing `bounds()`, `nearest()`, `getGrid()`, `sample()`, `BASE`.
- Produces: `aqOv` (the `L.imageOverlay`), `window.renderAqGrid`.

- [ ] **Step 1: Add the overlay**

Right after Task 6's `setInterval(...)` line for the air quality layer, insert:

```js
  // ---------- Air quality: AirNow's interpolated AQI (monitors only) ----------
  const aqOv = L.imageOverlay('', bounds(), { opacity: .55, interactive: false, zIndex: 387 });
  window.renderAqGrid = function () {
    if (!aqData) return;
    const g = aqData.grid;
    if (!g) { $('aqGridInfo').innerHTML = '<div class="muted">interpolated map not available yet</div>'; return; }
    aqOv.setUrl(BASE + g.file);
    $('aqGridInfo').innerHTML = '<div class="muted">AirNow map for ' + new Date((g.t - 3600) * 1000).toLocaleString([], { weekday: 'short', hour: 'numeric' }) + '–' + new Date(g.t * 1000).toLocaleTimeString([], { hour: 'numeric' }) + '</div>' + aqLegend() +
      '<div class="note">Interpolated by AirNow from monitors only; it ignores terrain, so a valley and the ridge above it can differ from what’s shown. Blank where no monitor is near.</div>';
  };
  $('lyAqGrid').onchange = e => { if (e.target.checked) { aqOv.addTo(map); if (!aqData) loadAq(); else window.renderAqGrid(); } else map.removeLayer(aqOv); };

```

(`g.t` is the GRIB `valid_time`, one hour after the data hour, so the label shows the hour the map averages.)

- [ ] **Step 2: Keep the overlay on the region bounds**

In `applyData` (currently line 1255), change:

```js
  function applyData() { [radar, satOv, accum, fcst, fzBands, snodasOv].forEach(l => l.setBounds(bounds())); if ($('lyAccum').checked) { renderAccumUI(); showAccum(); } loadFrames(true); }
```

to:

```js
  function applyData() { [radar, satOv, accum, fcst, fzBands, snodasOv, aqOv].forEach(l => l.setBounds(bounds())); if ($('lyAccum').checked) { renderAccumUI(); showAccum(); } loadFrames(true); }
```

- [ ] **Step 3: Add the click-anywhere line**

In the `map.on('click', ...)` handler, right after the avalanche-zone line (`if (window.AVALANCHE) { ... }`), insert:

```js
    // air quality: nearest reporting station within 100 km (judgment call, spec ledger); AirNow's grid when that layer is on
    await new Promise(res => aqData ? res() : loadScript('data/airquality.js', () => { aqData = window.AIRQ || aqData; res(); }, res));
    if (aqData) {
      const nowS = Date.now() / 1000, rows = [];
      const a = nearest(aqData.stations, ll, s => !aqStale(s, aqData.hours, nowS));
      if (a && a.km <= 100) { const l = aqLast(a.s); rows.push('<div>' + aqEsc(a.s.name) + ' <span style="color:#666">(' + a.km.toFixed(0) + ' km' + (a.s.temp ? ', temporary' : '') + ')</span>: <b>AQI ' + l.aqi + '</b>, ' + AQ_NAMES[aqCat(l.aqi)] + '</div>'); }
      if ($('lyAqGrid').checked) { const v = sample(await getGrid('aqi'), ll); if (v != null) rows.push('<div>interpolated AQI <b>' + Math.round(v) + '</b>, ' + AQ_NAMES[aqCat(v)] + ' <span style="color:#666">(AirNow, monitors only)</span></div>'); }
      if (rows.length) sec.push('<div style="margin-top:6px;color:#666">Air quality</div>' + rows.join(''));
    }
```

- [ ] **Step 4: Run the tests**

Run: `python -m pytest tests/ -v`
Expected: all PASS (this task has no new unit test; Task 8 checks it in the browser).

- [ ] **Step 5: Commit**

```bash
git add map.html
git commit -m "map: AirNow interpolated AQI overlay and an air quality line in click-anywhere

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Terms page, docs, browser check against local data, release to Chris

**Files:**
- Modify: `terms.html:28-35` (AirNow credit and "preliminary")
- Modify: `CLAUDE.md` (What lives here, globals, rules, timeline; see the constraint on other sessions' hunks)
- Modify: `HANDOFF.md` item 7 (untracked; update in place, not committed)
- Create: `smoke_research/aq_serve.py` (local preview server: local AQ files, everything else from R2)

**Interfaces:**
- Consumes: the built page (`python build_web.py` → `web/index.html`, `web/terms.html`), local `regions/pnw/` files from Task 4's check.

- [ ] **Step 1: Terms page**

In `terms.html`, inside the "Terms of use" `<ul>`, after the first `<li>` (the "provided as is" line), add:

```html
  <li>Air quality readings come from AirNow (U.S. EPA) and the state, local, tribal and Canadian agencies that report to it;
    temporary smoke monitors come through the USFS AirFire program. They are preliminary, have not been verified, and may
    change. The interpolated air quality map is AirNow's, made from monitors only.</li>
```

and change `Updated 27 September 2026` to the date this ships.

- [ ] **Step 2: Local preview server**

Create `smoke_research/aq_serve.py`:

```python
"""
Preview the built page with this PC's air quality files before anything is published.

Serves web/index.html with the data base pointed at this server. Requests for the air quality files are answered from
regions/<region>/ (written by smoke_research/aq_check.py); every other data request is redirected to the live R2 URL
already baked into web/index.html by build_web.py. Nothing is uploaded.

Usage (from radar/):  python build_web.py; python smoke_research/aq_serve.py      then open http://127.0.0.1:8791/?r=pnw
"""
import http.server
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = 8791
LOCAL = ("data/airquality.js", "frames/aq/", "data/values/aqi.js")

with open(os.path.join(ROOT, "web", "index.html"), encoding="utf-8") as f:
    PAGE = f.read()
R2 = re.search(r'<meta name="radar-base" content="([^"]+)">', PAGE).group(1)
PAGE = PAGE.replace('<meta name="radar-base" content="%s">' % R2, '<meta name="radar-base" content="http://127.0.0.1:%d/d/">' % PORT)


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=os.path.join(ROOT, "web"), **k)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            body = PAGE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path.startswith("/d/"):
            reg, _, rest = path[3:].partition("/")
            local = os.path.join(ROOT, "regions", reg, *rest.split("/"))
            if rest.startswith(LOCAL) and os.path.isfile(local):
                with open(local, "rb") as f:
                    body = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "application/javascript" if local.endswith(".js") else "image/webp")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            self.send_response(302)
            self.send_header("Location", R2 + path[3:] + ("?" + self.path.split("?", 1)[1] if "?" in self.path else ""))
            self.end_headers()
            return
        super().do_GET()


if __name__ == "__main__":
    print("serving on http://127.0.0.1:%d/?r=pnw (air quality files local, the rest from %s)" % (PORT, R2))
    http.server.ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
```

- [ ] **Step 3: Browser check**

Run `python build_web.py`, re-run `python smoke_research/aq_check.py pnw` if the local files are more than an hour old, then start `python smoke_research/aq_serve.py` in the background and open `http://127.0.0.1:8791/?r=pnw` in the in-app browser. Check each item and fix before moving on:
1. The "Air quality" group sits between Water and Hazards; its badge counts the switches that are on.
2. AQI stations: coloured circles, squares for temporary monitors, hollow grey for stale ones; the info line counts match `aq_check.py`'s AIRQ line; the legend shows six colours with names.
3. Zoom 9: AQI numbers appear as labels, only for stations in view.
4. Hover a station: card with the AQI number, category chip, PM2.5 line with the hour and "min ago", the trend line when there is one, the 72 h bar chart with day ticks, and a hover readout like "AQI 44 · 8 µg/m³ · Sun 5 PM"; the footer credit. Hover a river gauge chart too: it still reads "… cfs · 3 h ago" (the `attachTracker` change).
5. Interpolated AQI: the overlay lines up with the stations (colours agree near monitors) and is transparent far from monitors; the info line shows the hour.
6. Click the map near a station: the point panel has an "Air quality" section; with the grid on, an "interpolated AQI" row too.
7. Save as default with both switches on, reload: both come back on.
8. `read_console_messages`: no errors. `resize_window` to mobile: the panel and the card fit at 375 px.
9. Region `ne` (`?r=ne`, after `python smoke_research/aq_check.py ne`): stations appear, including Canadian ones, and no temporary monitors (none deployed there right now).
Take a screenshot of the PNW map with both layers on and one card open, and send it to Chris.

- [ ] **Step 4: Docs**

`HANDOFF.md` item 7: replace with the current state (tasks done, commits, what Chris runs next, the open ledger items). `CLAUDE.md` (check `git diff CLAUDE.md` first; change only these lines):
- "What lives here": add "air quality (AirNow monitors, AirFire temporary smoke monitors, AirNow's interpolated AQI)" to the list of layers.
- `How it runs` table, `capture.yml` row: "…accumulation overlays, alerts, air quality, `<r>/frames.js`".
- `map.html conventions`, globals list: add `AIRQ`.
- Rules: "Air quality: permanent monitors show AirNow's `PM25_AQI` unchanged; only temporary monitors (AirFire) get AQI from `airquality.aqi_from_pm25`. Never use `AirNowWildfire.csv` for times (its rows carry the file's hour). Design and ledger: `docs/superpowers/specs/2026-09-27-air-quality-layer-design.md`."
- Timeline: "<the ship date, YYYY-MM-DD>: Air quality section (AQI stations, AirNow interpolated AQI); spec `docs/superpowers/specs/2026-09-27-air-quality-layer-design.md`."

- [ ] **Step 5: Commit**

```bash
git add terms.html smoke_research/aq_serve.py
git commit -m "Air quality: terms credit, local preview server

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Commit `CLAUDE.md` separately only if `git diff CLAUDE.md` shows no other session's hunks; otherwise ask that session (ListAgents) or leave it for Chris.

- [ ] **Step 6: Release (Chris runs these)**

Check `ListAgents` for sessions with unfinished changes in `radar/web/` (root `CLAUDE.md`), then run `python build_web.py` yourself and give Chris, each in its own `bash` block:

```bash
cd C:/Users/16035/Desktop/BlackwaterLabs/radar; git push
```

```bash
cd C:/Users/16035/Desktop/BlackwaterLabs/radar; npx --yes wrangler deploy
```

Say what success looks like (push: `main -> main`; deploy: "Deployed radar triggers" with a version id), read the terminal with `read_terminal`, then:
1. `curl https://radar.blackwaterlabs.org/` and diff it against `web/index.html` (identical).
2. After the next 15-minute run, the Actions log for each region has an `airquality:` line; the first runs show "24 backfilled".
3. `https://radar-files.blackwaterlabs.org/pnw/data/airquality.js` loads, and the live page shows the layer.
Update `HANDOFF.md`, then retire item 7 to one line once Chris has seen it live.
