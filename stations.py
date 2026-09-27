"""
Precipitation and snow station layer for the map.

Pulls the last ~25 hours from:
  * NRCS SNOTEL, from snotel.py (one pull per run, shared with the SNOTEL layer)
  * NWS HADS gauges for the SEW, OTX, PDT, PQR forecast offices (precip accumulators,
    increments, snow depth, snow water equivalent)
  * CoCoRaHS daily 24 h reports for central and western Washington counties
  * NWS airport observations (hourly precipitation)
and writes data/stations.js  ->  window.STATIONS = {...}
with totals for 1, 3, 6, 12 and 24 hour windows per station.
New snow from depth sensors (SNOTEL, HADS SD) is newsnow.py's storm total.

Run standalone:  python stations.py
"""
import collections
import csv
import datetime as dt
import io
import json
import os
import time
import urllib.parse
import urllib.request

import newsnow
import region

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = region.data_dir()
OUT = os.path.join(DATA, "stations.js")
CACHE = os.path.join(DATA, "station_meta_cache.json")
UA = "RadarTracker/1.0 (personal weather map; chris.gabrielli@gmail.com)"

# map window (same as capture.py)
LAT0, LAT1, LON0, LON1 = region.bbox()
WINDOWS = [1, 3, 6, 12, 24]
HADS_STATES = [s for s in region.cfg()["states"] if s != "BC"]
ASOS = region.cfg()["asos"]
# NWS observation network (RAWS, WSDOT, airports, citizen stations) is pulled in full only inside this box
FOCUS = region.cfg()["focus"]      # lat0, lat1, lon0, lon1
NWS_CACHE = os.path.join(DATA, "nws_stations_cache.json")
NWS_WORKERS = 8


def c_to_f(c):
    return None if c is None else round(c * 9 / 5 + 32)


def kmh_to_mph(v):
    return None if v is None else round(v * 0.621371)


def fetch(url, timeout=90, tries=2, data=None):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA}, data=data)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(3 + 3 * i)
    raise last


def in_window(lat, lon):
    return LAT0 <= lat <= LAT1 and LON0 <= lon <= LON1


def local(ts_utc):
    """naive UTC datetime -> naive local (Pacific) datetime"""
    return ts_utc.replace(tzinfo=dt.timezone.utc).astimezone().replace(tzinfo=None)


def window_totals(series, now, mode):
    """series: sorted [(local datetime, value)].
    mode 'accum': value is a cumulative accumulator -> total = last - value at (now - w).
    mode 'incr':  value is an increment -> total = sum over window.
    Returns dict window_hours -> total (None if no data in that span)."""
    out = {}
    if not series:
        return out
    last_t, last_v = series[-1]
    for w in WINDOWS:
        t0 = now - dt.timedelta(hours=w)
        if mode == "accum":
            before = [v for t, v in series if t <= t0]
            if not before or last_t < t0:
                out[w] = None
            else:
                out[w] = round(max(0.0, last_v - before[-1]), 2)
        else:
            vals = [v for t, v in series if t > t0 and v is not None and v >= 0]
            out[w] = round(sum(vals), 2) if vals else None
    return out


def _cache():
    try:
        with open(CACHE, encoding="utf-8") as f:
            c = json.load(f)
        if time.time() - c.get("_t", 0) < 7 * 86400:
            return c
    except (OSError, ValueError):
        pass
    return {"_t": 0}


def _save_cache(c):
    c["_t"] = time.time()
    with open(CACHE, "w", encoding="utf-8") as f:
        json.dump(c, f)


# ---------------------------------------------------------------- SNOTEL
def snotel(now, log):
    if not region.cfg()["snotel_states"]:          # e.g. New England: no SNOTEL network
        return []
    import snotel as sn                               # one NRCS pull per run, shared with the SNOTEL layer
    out = sn.stations_records(WINDOWS, log)
    log("snotel: %d stations" % len(out))
    return out


# ---------------------------------------------------------------- HADS
def hads(now, log):
    cache = _cache()
    if "hads_meta" not in cache:
        meta = {}
        for st in HADS_STATES:
            txt = fetch("https://hads.ncep.noaa.gov/csv/%s.csv" % st).decode("utf-8", "ignore")
            for row in csv.DictReader(io.StringIO(txt)):
                try:
                    lat, lon = float(row["latitude_d"]), float(row["longitude_d"])
                except (ValueError, KeyError):
                    continue
                if in_window(lat, lon):
                    meta[row["nwsli"].strip()] = {"lat": lat, "lon": lon, "owner": row.get("owner_code", "").strip()}
        # names for USGS-operated sites
        try:
            for line in fetch("https://hads.ncep.noaa.gov/USGS/ALL_USGS-HADS_SITES.txt").decode("utf-8", "ignore").splitlines():
                p = [x.strip() for x in line.split("|")]
                if len(p) >= 7 and p[0] in meta:
                    meta[p[0]]["name"] = p[6].title()
        except Exception:  # noqa: BLE001
            pass
        cache["hads_meta"] = meta
        _save_cache(cache)
    meta = cache["hads_meta"]
    series = collections.defaultdict(lambda: collections.defaultdict(list))
    for st in HADS_STATES:
        try:
            txt = fetch("https://hads.ncep.noaa.gov/nexhads2/servlet/DecodedData?sinceday=1&hsa=nil&state=%s&nesdis_ids=nil&of=1" % st,
                        timeout=240).decode("utf-8", "ignore")
        except Exception as e:  # noqa: BLE001
            log("hads %s failed: %r" % (st, e))
            continue
        for line in txt.splitlines():
            p = line.split("|")
            if len(p) < 5:
                continue
            sid, pe, ts, val = p[1].strip(), p[2].strip(), p[3].strip(), p[4].strip()
            if sid not in meta or pe not in ("PC", "PP", "SD", "SW"):
                continue
            # parse before touching the defaultdict: series[sid][pe] would otherwise be created empty by a
            # blank value (Colorado VCRC2 sent only blanks on 2026-09-27) and s[-1] below failed every HADS station
            try:
                point = (local(dt.datetime.strptime(ts, "%Y-%m-%d %H:%M")), float(val))
            except ValueError:
                continue
            series[sid][pe].append(point)
    out = []
    for sid, pes in series.items():
        m = meta[sid]
        rec = {"id": sid, "name": m.get("name") or sid, "src": "HADS", "lat": m["lat"], "lon": m["lon"], "precip": {}, "snow": {}, "swe": {}}
        if "PC" in pes:
            s = sorted(pes["PC"])
            rec["precip"] = window_totals(s, now, "accum")
            rec["last"] = s[-1][0].strftime("%I:%M %p").lstrip("0")
        elif "PP" in pes:
            s = sorted(pes["PP"])
            rec["precip"] = window_totals(s, now, "incr")
            rec["last"] = s[-1][0].strftime("%I:%M %p").lstrip("0")
        if "SD" in pes:
            s = sorted(pes["SD"])
            rec["depth"] = s[-1][1]
            rec["snow"] = newsnow.new_snow([p for p in s if p[1] >= 0], now, WINDOWS, newsnow.load_config())
        if "SW" in pes:
            rec["swe"] = window_totals(sorted(pes["SW"]), now, "accum")
        if any(v is not None for v in rec["precip"].values()) or rec["snow"]:
            out.append(rec)
    log("hads: %d stations" % len(out))
    return out


# ---------------------------------------------------------------- CoCoRaHS
def cocorahs(now, log):
    out = []
    for day in (now.date(), now.date() - dt.timedelta(days=1)):
        seen = {s["id"] for s in out}
        for state in region.cfg()["cocorahs_states"]:
            url = ("https://data.cocorahs.org/export/exportreports.aspx?ReportType=Daily&Format=CSV&State=%s"
                   "&ReportDateType=reportdate&Date=%s&TimesInGMT=False" % (state, day.strftime("%m/%d/%Y")))
            try:
                txt = fetch(url, timeout=90, tries=1).decode("utf-8", "ignore")
            except Exception:  # noqa: BLE001
                continue
            for row in csv.DictReader(io.StringIO(txt)):
                try:
                    sid = row["StationNumber"].strip()
                    if sid in seen:
                        continue
                    lat, lon = float(row["Latitude"]), float(row["Longitude"])
                    amt = row["TotalPrecipAmt"].strip()
                    amt = 0.001 if amt == "T" else float(amt)
                except (ValueError, KeyError):
                    continue
                if not in_window(lat, lon):
                    continue
                obs = "%s %s" % (row["ObservationDate"].strip(), row["ObservationTime"].strip())
                try:
                    t = dt.datetime.strptime(obs, "%Y-%m-%d %I:%M %p")
                except ValueError:
                    t = None
                if t and (now - t).total_seconds() > 30 * 3600:
                    continue
                rec = {"id": sid, "name": row["StationName"].strip(), "src": "CoCoRaHS", "lat": lat, "lon": lon,
                       "precip": {24: round(amt, 2)}, "snow": {}, "swe": {},
                       "last": t.strftime("%a %I:%M %p").lstrip("0") if t else obs}
                try:
                    sn = row.get("NewSnowDepth", "").strip()
                    if sn and sn not in ("NA", "T"):
                        rec["snow"] = {24: float(sn)}
                except ValueError:
                    pass
                out.append(rec)
                seen.add(sid)
    log("cocorahs: %d stations" % len(out))
    return out


# ---------------------------------------------------------------- NWS observation network
def nws_station_list(log):
    """All NWS API stations inside the map window (cached weekly) -> {id: {name, lat, lon, elev}}"""
    try:
        with open(NWS_CACHE, encoding="utf-8") as f:
            c = json.load(f)
        if time.time() - c.get("_t", 0) < 7 * 86400:
            return c["stations"]
    except (OSError, ValueError):
        pass
    stations = {}
    for st in [x for x in region.cfg()["states"] if x != "BC"]:
        url = "https://api.weather.gov/stations?state=%s&limit=500" % st
        for _ in range(12):
            try:
                d = json.loads(fetch(url, timeout=60))
            except Exception as e:  # noqa: BLE001
                log("nws station list %s failed: %r" % (st, e))
                break
            for f in d.get("features", []):
                lon, lat = f["geometry"]["coordinates"][:2]
                p = f["properties"]
                if in_window(lat, lon):
                    el = (p.get("elevation") or {}).get("value")
                    stations[p["stationIdentifier"]] = {"name": p.get("name") or p["stationIdentifier"], "lat": lat, "lon": lon,
                                                        "elev": round(el * 3.28084) if el is not None else None}
            url = (d.get("pagination") or {}).get("next")
            if not url or not d.get("features"):
                break
    with open(NWS_CACHE, "w", encoding="utf-8") as f:
        json.dump({"_t": time.time(), "stations": stations}, f)
    log("nws station list: %d in window" % len(stations))
    return stations


def _obs_record(sid, meta, feats, now):
    """Build a station record from a list of observation features (newest first or any order)."""
    rows = []
    for f in feats:
        p = f["properties"]
        try:
            t = local(dt.datetime.strptime(p["timestamp"][:19], "%Y-%m-%dT%H:%M:%S"))
        except (KeyError, ValueError):
            continue
        g = lambda k: (p.get(k) or {}).get("value")  # noqa: E731
        rows.append((t, g("temperature"), g("windSpeed"), g("windGust"), g("windDirection"), g("relativeHumidity"), g("precipitationLastHour")))
    rows.sort()
    rows = [r for r in rows if r[0] > now - dt.timedelta(hours=25)]
    if not rows:
        return None
    latest = rows[-1]
    if (now - latest[0]).total_seconds() > 3 * 3600:
        return None
    rec = {"id": sid, "name": meta["name"].replace("Airport", "AP"), "src": "NWS", "lat": meta["lat"], "lon": meta["lon"],
           "elev": meta.get("elev"), "precip": {}, "snow": {}, "swe": {}, "last": latest[0].strftime("%I:%M %p").lstrip("0")}
    temps = [(t, c_to_f(v)) for t, v, *_ in rows if v is not None and -60 < c_to_f(v) < 130]
    if temps:
        rec["temp"] = {"now": temps[-1][1], "max": max(v for _, v in temps), "min": min(v for _, v in temps), "t": temps[-1][0].strftime("%I:%M %p").lstrip("0")}
        if len(temps) > 3:
            # hourly sparkline: last value in each hour
            byh = {}
            for t, v in temps:
                byh[t.replace(minute=0, second=0)] = v
            rec["temp"]["spark"] = [byh[k] for k in sorted(byh)][-25:]
    if latest[2] is not None or latest[3] is not None:
        rec["wind"] = {"spd": kmh_to_mph(latest[2]), "gust": kmh_to_mph(latest[3]), "dir": latest[4]}
        gusts = [kmh_to_mph(r[3]) for r in rows if r[3] is not None]
        if gusts:
            rec["wind"]["max_gust"] = max(gusts)
    if latest[5] is not None:
        rec["rh"] = round(latest[5])
    pts = [(t, v / 25.4) for t, *_, v in rows if v is not None]
    if pts:
        rec["precip"] = window_totals(pts, now, "incr")
    return rec


def nws_obs(now, log):
    from concurrent.futures import ThreadPoolExecutor
    stations = nws_station_list(log)
    lat0, lat1, lon0, lon1 = FOCUS
    focus = {sid: m for sid, m in stations.items() if lat0 <= m["lat"] <= lat1 and lon0 <= m["lon"] <= lon1}
    for sid in ASOS:
        if sid in stations:
            focus[sid] = stations[sid]
    # full 24 h series for the professional networks (airports, RAWS, DOT); latest-only for the rest
    def is_core(sid):
        return (len(sid) == 4 and sid.startswith("K")) or (len(sid) == 5 and not (sid[0] == "A" and sid[1:].isdigit()) and sid[:3] != "033")
    start = (now - dt.timedelta(hours=26)).astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def one(item):
        sid, m = item
        try:
            if is_core(sid):
                d = json.loads(fetch("https://api.weather.gov/stations/%s/observations?start=%s&limit=120" % (sid, start), timeout=30, tries=1))
                feats = d.get("features", [])
            else:
                d = json.loads(fetch("https://api.weather.gov/stations/%s/observations/latest" % sid, timeout=30, tries=1))
                feats = [d] if d.get("properties") else []
            return _obs_record(sid, m, feats, now)
        except Exception:  # noqa: BLE001
            return None

    out = []
    with ThreadPoolExecutor(max_workers=NWS_WORKERS) as ex:
        for rec in ex.map(one, sorted(focus.items())):
            if rec:
                out.append(rec)
    log("nws obs: %d of %d stations reporting" % (len(out), len(focus)))
    return out


def asos(now, log):   # kept for the build() call list
    return nws_obs(now, log)


def build(log=print):
    now = dt.datetime.now().replace(second=0, microsecond=0)
    stations = []
    for fn in (snotel, hads, cocorahs, asos):
        try:
            stations.extend(fn(now, log))
        except Exception as e:  # noqa: BLE001
            log("%s FAILED: %r" % (fn.__name__, e))
    # drop stations with nothing to show; drop implausible totals (sensor resets, bad decodes)
    keep = []
    for s in stations:
        for w in list(s["precip"]):
            v = s["precip"][w]
            if v is not None and (v < 0 or v > 3.0 + 0.25 * int(w)):
                s["precip"][w] = None
        for w in list(s["snow"]):
            v = s["snow"][w]
            if v is not None and abs(v) > 6.0 + 1.0 * int(w):
                s["snow"][w] = None
        s["precip"] = {str(k): v for k, v in s["precip"].items() if v is not None}
        s["snow"] = {str(k): v for k, v in s["snow"].items() if v is not None}
        s["swe"] = {str(k): v for k, v in s["swe"].items() if v is not None}
        if s["precip"] or s["snow"] or s.get("depth") is not None or s.get("temp") or s.get("wind"):
            keep.append(s)
    data = {"updated": now.strftime("%a %b %d %I:%M %p"), "updated_t": int(time.time()), "windows": WINDOWS, "stations": keep}
    try:
        import interp
        data["interp"] = interp.build(keep, WINDOWS, log)
    except Exception as e:  # noqa: BLE001
        log("interp FAILED: %r" % e)
    os.makedirs(DATA, exist_ok=True)
    tmp = OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("window.STATIONS = %s;\n" % json.dumps(data, separators=(",", ":")))
    os.replace(tmp, OUT)
    log("stations.js: %d stations" % len(keep))
    return len(keep)


if __name__ == "__main__":
    t = time.time()
    n = build()
    print("done in %.0fs" % (time.time() - t))
