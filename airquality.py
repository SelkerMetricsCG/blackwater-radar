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
