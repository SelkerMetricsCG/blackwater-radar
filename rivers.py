"""
River gauge layer: USGS streamflow and stage for every active gauge in the map
window, with 24-hour change and percent of the long-term median for the date.

Output: data/rivers.js -> window.RIVERS = {updated, sites:[...]}
Median flows (USGS daily statistics, 50th percentile by day of year) are cached
in data/usgs_median_cache.json and refreshed weekly.

Run standalone:  python rivers.py
"""
import datetime as dt
import io
import json
import os
import time
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data")
OUT = os.path.join(DATA, "rivers.js")
MEDIAN_CACHE = os.path.join(DATA, "usgs_median_cache.json")
UA = "RadarTracker/1.0 (personal weather map; chris.gabrielli@gmail.com)"

# map window split into boxes the USGS service accepts (each well under 25 square degrees)
LON_EDGES = [-126.6, -119.6, -112.5]
LAT_EDGES = [43.1, 46.3, 49.5, 52.5]


def fetch(url, timeout=120, tries=2):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(3 + 3 * i)
    raise last


def parse_iv(payload, sites):
    """Merge a USGS IV JSON payload into sites[siteno] = {name, lat, lon, flow:[(t,v)], stage:[(t,v)]}"""
    d = json.loads(payload)
    for ts in d["value"]["timeSeries"]:
        info = ts["sourceInfo"]
        sid = info["siteCode"][0]["value"]
        code = ts["variable"]["variableCode"][0]["value"]
        key = {"00060": "flow", "00065": "stage"}.get(code)
        if not key:
            continue
        loc = info["geoLocation"]["geogLocation"]
        s = sites.setdefault(sid, {"id": sid, "name": info["siteName"].title().replace(" Wa", " WA").replace(" Or", " OR").replace(" Id", " ID"),
                                   "lat": loc["latitude"], "lon": loc["longitude"], "flow": [], "stage": []})
        for v in ts["values"][0]["value"]:
            if v["value"] in ("-999999", "", None):
                continue
            try:
                t = dt.datetime.strptime(v["dateTime"][:16], "%Y-%m-%dT%H:%M")
                s[key].append((t, float(v["value"])))
            except ValueError:
                pass


def load_medians(site_ids, log):
    try:
        with open(MEDIAN_CACHE, encoding="utf-8") as f:
            cache = json.load(f)
    except (OSError, ValueError):
        cache = {"_t": 0, "sites": {}}
    missing = [s for s in site_ids if s not in cache["sites"]]
    stale = time.time() - cache.get("_t", 0) > 30 * 86400
    if stale:
        missing = list(site_ids)
    if missing:
        log("rivers: fetching median stats for %d gauges" % len(missing))
        for i in range(0, len(missing), 10):        # the statistics service accepts at most 10 sites per call
            chunk = missing[i:i + 10]
            url = ("https://waterservices.usgs.gov/nwis/stat/?format=rdb&sites=%s&statReportType=daily"
                   "&statTypeCd=p50&parameterCd=00060" % ",".join(chunk))
            try:
                txt = fetch(url).decode("utf-8", "ignore")
            except Exception as e:  # noqa: BLE001
                log("rivers: stats chunk failed: %r" % e)
                continue
            for s in chunk:
                cache["sites"].setdefault(s, {})
            cols = None
            for line in txt.splitlines():
                if line.startswith("#") or not line.strip():
                    continue
                p = line.split("\t")
                if cols is None:
                    cols = {c: k for k, c in enumerate(p)}
                    continue
                if p[0].startswith("5s") or p[0] == "":
                    continue
                try:
                    sid = p[cols["site_no"]]
                    key = "%02d%02d" % (int(p[cols["month_nu"]]), int(p[cols["day_nu"]]))
                    cache["sites"].setdefault(sid, {})[key] = float(p[cols["p50_va"]])
                except (KeyError, ValueError, IndexError):
                    continue
        cache["_t"] = time.time()
        with open(MEDIAN_CACHE + ".tmp", "w", encoding="utf-8") as f:
            json.dump(cache, f)
        os.replace(MEDIAN_CACHE + ".tmp", MEDIAN_CACHE)
    return cache["sites"]


def at_or_before(series, t):
    prev = [v for tt, v in series if tt <= t]
    return prev[-1] if prev else None


# ---------------------------------------------------------------- NWS river forecasts
NWPS_CACHE = os.path.join(DATA, "nwps_cache.json")


def usgs_to_lid():
    """USGS site number -> NWS location id, from the HADS site list (cached with the medians)"""
    path = os.path.join(DATA, "usgs_lid_cache.json")
    try:
        with open(path, encoding="utf-8") as f:
            c = json.load(f)
        if time.time() - c.get("_t", 0) < 30 * 86400:
            return c["map"]
    except (OSError, ValueError):
        pass
    m = {}
    try:
        txt = fetch("https://hads.ncep.noaa.gov/USGS/ALL_USGS-HADS_SITES.txt").decode("utf-8", "ignore")
        for line in txt.splitlines():
            p = [x.strip() for x in line.split("|")]
            if len(p) >= 4 and p[1].isdigit() and len(p[0]) == 5:
                m[p[1]] = p[0]
    except Exception:  # noqa: BLE001
        return m
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"_t": time.time(), "map": m}, f)
    return m


def nws_forecasts(site_ids, log):
    """-> {usgs_id: {issued, crest_flow, crest_stage, crest_t, series:[[t_local_iso, flow]...]}}
    Probes each gauge's NWPS record weekly to learn which ones carry forecasts;
    refreshes only those every run."""
    lids = usgs_to_lid()
    try:
        with open(NWPS_CACHE, encoding="utf-8") as f:
            cache = json.load(f)
    except (OSError, ValueError):
        cache = {"checked": {}}
    now = time.time()
    out = {}
    n_probe = 0
    for sid in site_ids:
        lid = lids.get(sid)
        if not lid:
            continue
        chk = cache["checked"].get(lid, {})
        has = chk.get("has")
        stale = now - chk.get("t", 0) > 7 * 86400
        if has is False and not stale:
            continue
        if has is None or stale:
            n_probe += 1
            if n_probe > 150:            # spread first-time probing over several runs
                continue
        try:
            d = json.loads(fetch("https://api.water.noaa.gov/nwps/v1/gauges/%s/stageflow" % lid, timeout=30, tries=1))
        except Exception:  # noqa: BLE001
            cache["checked"][lid] = {"has": False, "t": now}
            continue
        fc = d.get("forecast") or {}
        pts = fc.get("data") or []
        if not pts:
            cache["checked"][lid] = {"has": False, "t": now}
            continue
        cache["checked"][lid] = {"has": True, "t": now}
        series = []
        crest = None
        for p in pts:
            try:
                t = dt.datetime.strptime(p["validTime"][:16], "%Y-%m-%dT%H:%M").replace(tzinfo=dt.timezone.utc).astimezone().replace(tzinfo=None)
            except (KeyError, ValueError):
                continue
            flow = p.get("secondary")
            stage = p.get("primary")
            if flow is None or flow <= -999:
                flow = None
            elif fc.get("secondaryUnits") == "kcfs":
                flow = flow * 1000.0
            if stage is not None and stage <= -999:
                stage = None
            series.append([t.strftime("%Y-%m-%dT%H:%M"), None if flow is None else round(flow), stage])
            if flow is not None and (crest is None or flow > crest[1]):
                crest = (t, flow, stage)
        if series:
            out[sid] = {"lid": lid, "issued": (fc.get("issuedTime") or "")[:16], "series": series,
                        "crest_t": crest[0].strftime("%a %I:%M %p").lstrip("0") if crest else None,
                        "crest_flow": round(crest[1]) if crest else None, "crest_stage": crest[2] if crest else None}
    with open(NWPS_CACHE + ".tmp", "w", encoding="utf-8") as f:
        json.dump(cache, f)
    os.replace(NWPS_CACHE + ".tmp", NWPS_CACHE)
    log("rivers: NWS forecasts for %d gauges (%d probed this run)" % (len(out), n_probe))
    return out


def build(log=print):
    now = dt.datetime.now()
    sites = {}
    for i in range(len(LON_EDGES) - 1):
        for j in range(len(LAT_EDGES) - 1):
            bbox = "%.2f,%.2f,%.2f,%.2f" % (LON_EDGES[i], LAT_EDGES[j], LON_EDGES[i + 1], LAT_EDGES[j + 1])
            url = ("https://waterservices.usgs.gov/nwis/iv/?bBox=%s&parameterCd=00060,00065&siteStatus=active"
                   "&period=PT27H&format=json" % bbox)
            try:
                parse_iv(fetch(url), sites)
            except Exception as e:  # noqa: BLE001
                log("rivers: box %s failed: %r" % (bbox, e))
    flow_sites = sorted(s for s, v in sites.items() if v["flow"])
    medians = load_medians(flow_sites, log)
    try:
        forecasts = nws_forecasts(flow_sites, log)
    except Exception as e:  # noqa: BLE001
        log("rivers: forecasts failed: %r" % e)
        forecasts = {}
    key_today = now.strftime("%m%d")
    out = []
    for sid, s in sites.items():
        s["flow"].sort()
        s["stage"].sort()
        rec = {"id": sid, "name": s["name"], "lat": s["lat"], "lon": s["lon"]}
        if s["flow"]:
            t, v = s["flow"][-1]
            rec["flow"] = v
            rec["t"] = t.strftime("%I:%M %p").lstrip("0")
            rec["age_min"] = int((now - t).total_seconds() / 60)
            v24 = at_or_before(s["flow"], t - dt.timedelta(hours=24))
            v2 = at_or_before(s["flow"], t - dt.timedelta(hours=2))
            if v24 is not None:
                rec["flow24"] = v24
                rec["chg24"] = round(100.0 * (v - v24) / v24, 1) if v24 > 0 else None
            if v2 is not None:
                rec["chg2"] = round(v - v2, 1)
            med = (medians.get(sid) or {}).get(key_today)
            if med:
                rec["median"] = med
                rec["pctmed"] = round(100.0 * v / med) if med > 0 else None
            # 24 h sparkline, hourly samples
            spark = []
            for h in range(24, -1, -1):
                sv = at_or_before(s["flow"], t - dt.timedelta(hours=h))
                spark.append(None if sv is None else round(sv, 1))
            rec["spark"] = spark
            if sid in forecasts:
                rec["fc"] = forecasts[sid]
        if s["stage"]:
            t, v = s["stage"][-1]
            rec["stage"] = v
            v24 = at_or_before(s["stage"], t - dt.timedelta(hours=24))
            if v24 is not None:
                rec["stage24"] = round(v - v24, 2)
        if "flow" in rec or "stage" in rec:
            if rec.get("age_min", 0) < 24 * 60:
                out.append(rec)
    data = {"updated": now.strftime("%a %b %d %I:%M %p"), "updated_t": int(time.time()), "sites": out}
    os.makedirs(DATA, exist_ok=True)
    with open(OUT + ".tmp", "w", encoding="utf-8") as f:
        f.write("window.RIVERS = %s;\n" % json.dumps(data, separators=(",", ":")))
    os.replace(OUT + ".tmp", OUT)
    log("rivers: %d gauges" % len(out))
    return len(out)


if __name__ == "__main__":
    t0 = time.time()
    build()
    print("done in %.0fs" % (time.time() - t0))
