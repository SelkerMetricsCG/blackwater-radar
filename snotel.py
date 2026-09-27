"""
SNOTEL layer data from the NRCS AWDB API, rebuilt by the hourly job just before stations.py.

One pull per run:
  * US SNOTEL, hourly, the last 74 h: snow depth, SWE, precipitation, air temperature, and soil moisture
    and soil temperature at 2, 4, 8, 20 and 40 in
  * NRCS SCAN soil-climate sites, hourly, same window (the map shows them only for soil)
  * BC snow pillows, daily, the last 4 days
  * daily SWE and water-year precipitation medians (1991-2020) for yesterday
Writes data/snotel.js -> window.SNOTEL and keeps the pull in memory, so stations.py takes SNOTEL in its
own 1-24 h format (stations_records) without a second pull.

AWDB stamps hourly values in each station's standard time (dataTimeZone, e.g. -8) all year; everything
here is converted to naive UTC before windows are cut. New snow is newsnow.py's storm total.

Run standalone:  python snotel.py
"""
import collections
import datetime as dt
import json
import os
import time
import urllib.parse
import urllib.request

import newsnow
import region

DATA = region.data_dir()
OUT = os.path.join(DATA, "snotel.js")
META_CACHE = os.path.join(DATA, "snotel_meta_cache.json")
API = "https://wcc.sc.egov.usda.gov/awdbRestApi/services/v1/"
UA = "BlackwaterRadar/1.0 (weather map)"
WINDOWS = [12, 24, 36, 48, 60, 72]
BC_WINDOWS = [24, 48, 72]
SOIL_DEPTHS = [2, 4, 8, 20, 40]
PULL_H = 74
BC_FRESH_H = 36          # a BC daily value is current if it is at most this old
HOURLY = "SNWD,WTEQ,PREC,TOBS," + ",".join("%s:-%d" % (c, d) for c in ("SMS", "STO") for d in SOIL_DEPTHS)
CHUNK = 60
BASE_KEYS = {"id", "name", "net", "lat", "lon", "elev", "t"}
_LAST = {"t": 0, "sites": None, "series": None, "med": None, "now": None}


def fetch(url, timeout=120, tries=2):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())
        except Exception:  # noqa: BLE001
            if i == tries - 1:
                raise
            time.sleep(3)


def in_window(lat, lon):
    lat0, lat1, lon0, lon1 = region.bbox()
    return lat0 <= lat <= lat1 and lon0 <= lon <= lon1


def site_meta(log):
    """Active SNOTEL, SCAN and BC sites inside the map window; cached 7 days, only when every request worked."""
    try:
        with open(META_CACHE, encoding="utf-8") as f:
            c = json.load(f)
        if time.time() - c.get("_t", 0) < 7 * 86400:
            return c["sites"]
    except (OSError, ValueError, KeyError):
        pass
    sites, failed = [], False
    for st in region.cfg()["snotel_states"]:
        for net in (["*"] if st == "BC" else ["SNTL", "SCAN"]):
            try:
                rows = fetch(API + "stations?stationTriplets=*:%s:%s&activeOnly=true" % (st, net))
            except Exception as e:  # noqa: BLE001
                log("snotel meta %s:%s failed: %r" % (st, net, e))
                failed = True
                continue
            for s in rows:
                if in_window(s["latitude"], s["longitude"]):
                    sites.append({"id": s["stationTriplet"], "name": s["name"], "net": "BC" if st == "BC" else net,
                                  "lat": s["latitude"], "lon": s["longitude"], "elev": s.get("elevation"),
                                  "tz": s.get("dataTimeZone") or -8.0, "huc": (s.get("huc") or "")[:6]})
    if not failed:
        with open(META_CACHE, "w", encoding="utf-8") as f:
            json.dump({"_t": time.time(), "sites": sites}, f)
    return sites


def _key(se):
    """AWDB stationElement -> 'SNWD', 'SMS2', 'STO20', ..."""
    d = se.get("heightDepth")
    return se["elementCode"] + (str(abs(int(d))) if d not in (None, 0) else "")


def parse(rows, tz_of, daily):
    """AWDB data rows -> {triplet: {key: sorted [(naive UTC datetime, value)]}}"""
    out = {}
    for s in rows:
        tz = tz_of.get(s["stationTriplet"], -8.0)
        ser = out.setdefault(s["stationTriplet"], {})
        for e in s.get("data", []):
            vals = []
            for v in e.get("values", []):
                if v.get("value") is None:
                    continue
                t = dt.datetime.strptime(v["date"], "%Y-%m-%d" if daily else "%Y-%m-%d %H:%M")
                vals.append((t - dt.timedelta(hours=tz), float(v["value"])))
            if vals:
                ser[_key(e["stationElement"])] = sorted(vals)
    return out


def pull(sites, now_utc, log):
    tz_of = {s["id"]: s["tz"] for s in sites}
    us = [s["id"] for s in sites if s["net"] != "BC"]
    bc = [s["id"] for s in sites if s["net"] == "BC"]
    # dates are station time; ask ~10 h wider than needed, windows are cut later in UTC
    begin = (now_utc - dt.timedelta(hours=PULL_H + 10)).strftime("%Y-%m-%d %H:00")
    end = (now_utc + dt.timedelta(hours=2)).strftime("%Y-%m-%d %H:00")
    series = {}
    for i in range(0, len(us), CHUNK):
        q = urllib.parse.urlencode({"stationTriplets": ",".join(us[i:i + CHUNK]), "elements": HOURLY,
                                    "duration": "HOURLY", "beginDate": begin, "endDate": end})
        try:
            series.update(parse(fetch(API + "data?" + q, 180), tz_of, False))
        except Exception as e:  # noqa: BLE001
            log("snotel hourly chunk %d failed: %r" % (i // CHUNK, e))
    for i in range(0, len(bc), CHUNK):
        q = urllib.parse.urlencode({"stationTriplets": ",".join(bc[i:i + CHUNK]), "elements": "SNWD,WTEQ,PREC",
                                    "duration": "DAILY", "beginDate": (now_utc - dt.timedelta(days=4)).strftime("%Y-%m-%d"),
                                    "endDate": now_utc.strftime("%Y-%m-%d")})
        try:
            series.update(parse(fetch(API + "data?" + q), tz_of, True))
        except Exception as e:  # noqa: BLE001
            log("snotel BC chunk failed: %r" % e)
    return series


def medians(sites, day, log):
    """{triplet: {"swe": (value, median), "wy": (value, median)}} for `day` (yesterday)"""
    ids = [s["id"] for s in sites if s["net"] == "SNTL"]
    out = {}
    for i in range(0, len(ids), CHUNK):
        q = urllib.parse.urlencode({"stationTriplets": ",".join(ids[i:i + CHUNK]), "elements": "WTEQ,PREC",
                                    "duration": "DAILY", "beginDate": day, "endDate": day, "centralTendencyType": "MEDIAN"})
        try:
            rows = fetch(API + "data?" + q)
        except Exception as e:  # noqa: BLE001
            log("snotel medians chunk failed: %r" % e)
            continue
        for s in rows:
            for e in s.get("data", []):
                key = "swe" if e["stationElement"]["elementCode"] == "WTEQ" else "wy"
                for v in e.get("values", []):
                    if v.get("value") is not None:
                        out.setdefault(s["stationTriplet"], {})[key] = (v["value"], v.get("median"))
    return out


def pct(val, med):
    return round(100.0 * val / med) if val is not None and med else None


def latest(ser, now_utc, max_age_h):
    """last value if it is at most max_age_h old, else None"""
    if not ser or (now_utc - ser[-1][0]).total_seconds() > max_age_h * 3600:
        return None
    return ser[-1][1]


def accum_change(ser, t_end, hours, cfg):
    """rise of an accumulating element (PREC, WTEQ) over the window, never below 0; None without coverage"""
    vals = newsnow.window_values(ser or [], t_end, hours, cfg["start_slack_h"], cfg["end_slack_h"])
    return None if vals is None else round(max(0.0, vals[-1] - vals[0]), 2)


def _new_snow(site, ser, now_utc, cfg):
    snwd = [p for p in ser.get("SNWD", []) if p[1] >= 0]
    if site["net"] != "BC":
        out = newsnow.new_snow(snwd, now_utc, WINDOWS, cfg)
    else:       # daily pillows: the last w/24 + 1 daily readings
        vals = [v for _, v in snwd]
        fresh = bool(snwd) and (now_utc - snwd[-1][0]).total_seconds() <= BC_FRESH_H * 3600
        out = {}
        for w in BC_WINDOWS:
            n = w // 24 + 1
            v = newsnow.storm_total(vals[-n:], cfg["noise_floor_in"], 1) if fresh and len(vals) >= n else None
            out[w] = None if v is None or v > cfg["max_new_base_in"] + cfg["max_new_per_h_in"] * w else v
    return {str(w): v for w, v in out.items() if v is not None}


def site_record(site, ser, med, now_utc, cfg):
    """one entry of window.SNOTEL.sites, or None when the site returned nothing"""
    last_t = max((s[-1][0] for s in ser.values() if s), default=None)
    if last_t is None:
        return None
    fresh_h = BC_FRESH_H if site["net"] == "BC" else cfg["end_slack_h"]
    rec = {"id": site["id"], "name": site["name"], "net": site["net"], "lat": site["lat"], "lon": site["lon"],
           "elev": site["elev"], "t": int(last_t.replace(tzinfo=dt.timezone.utc).timestamp())}
    m = med.get(site["id"], {})
    if site["net"] != "SCAN":
        swe = latest(ser.get("WTEQ"), now_utc, fresh_h)
        depth = latest([p for p in ser.get("SNWD", []) if p[1] >= 0], now_utc, fresh_h)
        if swe is not None:
            rec["swe"] = swe
        if "swe" in m and m["swe"][1] is not None:
            rec["swe_med"] = m["swe"][1]
            if pct(*m["swe"]) is not None:
                rec["swe_pct"] = pct(*m["swe"])
        if depth is not None:
            rec["depth"] = depth
        new = _new_snow(site, ser, now_utc, cfg)
        if new:
            rec["new"] = new
        if "wy" in m:
            rec["wy"] = m["wy"][0]
            if m["wy"][1] is not None:
                rec["wy_med"] = m["wy"][1]
                if pct(*m["wy"]) is not None:
                    rec["wy_pct"] = pct(*m["wy"])
    if site["net"] != "BC":
        p24 = accum_change(ser.get("PREC"), now_utc, 24, cfg)
        if p24 is not None:
            rec["p24"] = p24
    tv = [(t, v) for t, v in ser.get("TOBS", []) if -60 < v < 130 and t > now_utc - dt.timedelta(hours=25)]
    if tv and (now_utc - tv[-1][0]).total_seconds() <= cfg["end_slack_h"] * 3600:
        rec["temp"] = {"now": round(tv[-1][1]), "max": round(max(v for _, v in tv)),
                       "min": round(min(v for _, v in tv)), "spark": [round(v) for _, v in tv[-25:]]}
    soil = {}
    for d in SOIL_DEPTHS:
        mv = latest([p for p in ser.get("SMS%d" % d, []) if 0 <= p[1] <= 100], now_utc, cfg["end_slack_h"])
        st = latest([p for p in ser.get("STO%d" % d, []) if -40 <= p[1] <= 130], now_utc, cfg["end_slack_h"])
        if mv is not None or st is not None:
            soil[str(d)] = {"m": mv, "t": st}
    if soil:
        rec["soil"] = soil
    return rec


def _write(obj):
    tmp = OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("window.SNOTEL = " + json.dumps(obj, separators=(",", ":")) + ";")
    os.replace(tmp, OUT)


def build(log=print):
    now_utc = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None, second=0, microsecond=0)
    if not region.cfg()["snotel_states"]:          # e.g. New England
        _write({"note": "No SNOTEL network in this region", "sites": []})
        _LAST.update(t=time.time(), sites=[], series={}, med={}, now=now_utc)
        log("snotel: no SNOTEL network in this region")
        return 0
    cfg = newsnow.load_config()
    t0 = time.time()
    sites = site_meta(log)
    series = pull(sites, now_utc, log)
    day = (dt.datetime.now() - dt.timedelta(days=1)).strftime("%Y-%m-%d")
    med = medians(sites, day, log)
    recs, why = [], collections.Counter()
    for s in sites:
        ser = series.get(s["id"])
        r = site_record(s, ser, med, now_utc, cfg) if ser else None
        if r is None:
            why["no data returned"] += 1
        elif not set(r) - BASE_KEYS:
            why["nothing current"] += 1
        else:
            recs.append(r)
    _write({"updated": dt.datetime.now().strftime("%a %b %d %I:%M %p"), "updated_t": int(time.time()), "date": day,
            "windows": WINDOWS, "soil_depths": [2, 8, 20], "sites": recs})
    _LAST.update(t=time.time(), sites=sites, series=series, med=med, now=now_utc)
    log("snotel: %d sites requested, %d written %s, dropped %s, %.0f s, %d KB"
        % (len(sites), len(recs), dict(collections.Counter(r["net"] for r in recs)), dict(why) or "none",
           time.time() - t0, os.path.getsize(OUT) // 1024))
    return len(recs)


def _label(t_utc):
    return t_utc.replace(tzinfo=dt.timezone.utc).astimezone().strftime("%I:%M %p").lstrip("0")


def stations_records(windows, log=print, cfg=None):
    """SNOTEL and BC sites in stations.py's record format for `windows` (hours). Reuses this process's
    pull when build() ran in the last 90 minutes; otherwise runs build() first."""
    if _LAST["series"] is None or time.time() - _LAST["t"] > 90 * 60:
        build(log)
    cfg = cfg or newsnow.load_config()
    now_utc, out = _LAST["now"], []
    for s in _LAST["sites"] or []:
        ser = (_LAST["series"] or {}).get(s["id"])
        if not ser or s["net"] == "SCAN":
            continue
        rec = {"id": s["id"], "name": s["name"], "src": "SNOTEL", "lat": s["lat"], "lon": s["lon"], "elev": s["elev"],
               "precip": {}, "snow": {}, "swe": {}}
        snwd = [p for p in ser.get("SNWD", []) if p[1] >= 0]
        if s["net"] == "BC":        # daily pillows: 24 h change only
            for key, code in (("precip", "PREC"), ("swe", "WTEQ")):
                v = ser.get(code, [])
                if len(v) >= 2:
                    rec[key] = {24: round(max(0.0, v[-1][1] - v[-2][1]), 2)}
            if len(snwd) >= 2:
                rec["snow"] = {24: newsnow.storm_total([snwd[-2][1], snwd[-1][1]], cfg["noise_floor_in"], 1)}
            if snwd:
                rec["last"] = snwd[-1][0].strftime("%m-%d")
        else:
            rec["precip"] = {w: accum_change(ser.get("PREC"), now_utc, w, cfg) for w in windows}
            rec["swe"] = {w: accum_change(ser.get("WTEQ"), now_utc, w, cfg) for w in windows}
            rec["snow"] = newsnow.new_snow(snwd, now_utc, windows, cfg)
            if ser.get("PREC"):
                rec["last"] = _label(ser["PREC"][-1][0])
            tv = [(t, v) for t, v in ser.get("TOBS", []) if -60 < v < 130 and t > now_utc - dt.timedelta(hours=25)]
            if tv:
                rec["temp"] = {"now": round(tv[-1][1]), "max": round(max(v for _, v in tv)),
                               "min": round(min(v for _, v in tv)), "spark": [round(v) for _, v in tv[-25:]],
                               "t": _label(tv[-1][0])}
        if snwd:
            rec["depth"] = snwd[-1][1]
        if ser.get("WTEQ"):
            rec["swe_total"] = ser["WTEQ"][-1][1]
        m = (_LAST["med"] or {}).get(s["id"], {})
        if "swe" in m:
            rec["swe_median"], rec["swe_pct"] = m["swe"][1], pct(*m["swe"])
        if "wy" in m:
            rec["wy_total"], rec["wy_median"], rec["wy_pct"] = m["wy"][0], m["wy"][1], pct(*m["wy"])
        out.append(rec)
    return out


if __name__ == "__main__":
    build()
