"""
Season archive for the snow-conditions model: a compact snapshot of every input the hourly job
already has in hand, written into

  regions/<r>/snow/archive/<YYYY-MM-DD>/          (the region's local date; TZ is set per region in hourly.yml)
    HH.json.gz          every run: station readings, HRRR freezing level (analysis hour), MRMS 1 h QPE,
                        zone danger ratings
    daily.json.gz       first run of the day that finds none in R2: the 74 h SNOTEL series (so each day's
                        file overlaps the last), NDFD forecast grids, NDFD sky cover, dewpoint and wind by
                        step to 48 h (forecast.snow_fields), HRRR freezing level f0..f18, MRMS 24 h, SNODAS,
                        full station records
    products/*.json     every avalanche.org forecast product touching the window, saved when it changes
                        (snow/avyproducts.py)
    obs/*.json          NAC observations (snow/observations.py); only with an allow-listed Origin from NWAC/NAC

r2sync uploads it (immutable: nothing here is ever rewritten, a bad run can only add a file). Only regions
with "snow": True in region.py get one. Grids come from the 256 px click-anywhere grids (values.read_grid),
block-averaged to 64 px for the smooth fields (freezing level, forecast) and kept at 256 px for
precipitation; nodata is -1, the scale and unit ride along.

Run standalone (writes locally, no upload):  python -m snow.archive
"""
import datetime as dt
import gzip
import json
import os
import time

import region
import values

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = region.data_dir()
ARCHIVE = os.path.join(region.region_dir(), "snow", "archive")
SMOOTH_N = 64          # freezing level, forecast temperature and wind: 64 px is ~17 km at this window
SNODAS_N = 128
FORECAST_KEYS = ("qpf_24", "qpf_48", "snow_24", "snow_48", "gust_24", "maxt", "mint")
FZ_HOURS = (0, 3, 6, 9, 12, 15, 18)
STATION_KEEP = ("id", "name", "src", "net", "lat", "lon", "elev", "depth")


def read_js(path):
    """the object literal of a `window.X = {...};` data file, or None"""
    try:
        with open(path, encoding="utf-8") as f:
            s = f.read()
        return json.loads(s[s.index("=") + 1:s.rindex(";")])
    except (OSError, ValueError):
        return None


def block_mean(q, n_out):
    """(N, N) int grid with -1 nodata -> (n_out, n_out) ints, mean of the valid cells in each block, -1 where none"""
    import numpy as np
    a = np.asarray(q)
    n = a.shape[0]
    if n == n_out:
        return a.astype(np.int64)
    f = n // n_out
    b = a[:f * n_out, :f * n_out].reshape(n_out, f, n_out, f).astype(np.float64)
    ok = b >= 0
    cnt = ok.sum(axis=(1, 3))
    s = np.where(ok, b, 0).sum(axis=(1, 3))
    with np.errstate(invalid="ignore", divide="ignore"):
        m = np.where(cnt > 0, np.round(s / np.maximum(cnt, 1)), -1)
    return m.astype(np.int64)


def grid(name, n_out, out_dir=None):
    """a value grid packed for the archive: {n, scale, unit, data:[...]} or None when the grid is missing"""
    g = values.read_grid(name, out_dir)
    if g is None:
        return None
    payload, q = g
    m = block_mean(q, n_out)
    return {"n": int(n_out), "scale": payload.get("scale"), "unit": payload.get("unit"), "data": [int(v) for v in m.ravel()]}


def compact_station(rec):
    """the hourly form of a stations.js record: the current reading only, 1 h totals, no sparks"""
    out = {k: rec[k] for k in STATION_KEEP if rec.get(k) is not None}
    t = rec.get("temp") or {}
    if t.get("now") is not None:
        out["temp"] = t["now"]
    w = rec.get("wind") or {}
    if w:
        out["wind"] = {k: w[k] for k in ("spd", "gust", "dir") if w.get(k) is not None}
    if rec.get("rh") is not None:
        out["rh"] = rec["rh"]
    for key, short in (("precip", "p1"), ("snow", "s1"), ("swe", "w1")):
        d = rec.get(key) or {}
        v = d.get("1", d.get(1))
        if v is not None:
            out[short] = v
    return out


def pack_snotel(last):
    """snotel._LAST -> {sites, now_utc, series: {id: {element: [[epoch, value], ...]}}} or None when stale"""
    if not last or last.get("series") is None or time.time() - last.get("t", 0) > 90 * 60:
        return None
    series = {}
    for sid, ser in (last["series"] or {}).items():
        series[sid] = {el: [[int(t.replace(tzinfo=dt.timezone.utc).timestamp()), v] for t, v in pts] for el, pts in ser.items()}
    now = last.get("now")
    return {"sites": last.get("sites") or [], "now_utc": now.strftime("%Y-%m-%dT%H:%M") if now else None, "series": series}


def zone_ratings(avy):
    feats = (avy or {}).get("features") or []
    out = []
    for f in feats:
        p = f.get("properties") or {}
        out.append({k: p.get(k) for k in ("zone_id", "name", "center_id", "danger", "danger_level", "start_date", "end_date", "warning")})
    return out


def write_gz(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        json.dump(obj, f, separators=(",", ":"))
    os.replace(tmp, path)
    return os.path.getsize(path)


def existing(day, log):
    """names (relative to the day folder) already in R2 for this day; None when R2 cannot be listed"""
    import r2sync
    try:
        env = r2sync.load_env()
    except Exception as e:  # noqa: BLE001
        log("archive: r2.env unreadable: %r" % e)
        return None
    if env is None:
        local = os.path.join(ARCHIVE, day)
        return {os.path.relpath(os.path.join(r, f), local).replace(os.sep, "/") for r, _, fs in os.walk(local) for f in fs} if os.path.isdir(local) else set()
    try:
        s3 = r2sync.client(env)
        pre = region.prefix() + "snow/archive/%s/" % day
        return {k[len(pre):] for k in r2sync.list_keys(s3, env["R2_BUCKET"], pre)}
    except Exception as e:  # noqa: BLE001
        log("archive: R2 listing failed (%r); hourly file only" % e)
        return None


def hourly_snapshot(now_local, now_utc):
    snap = {"t_utc": now_utc.strftime("%Y-%m-%dT%H:%M"), "t_local": now_local.strftime("%Y-%m-%dT%H:%M"), "tz": os.environ.get("TZ")}
    st = read_js(os.path.join(DATA, "stations.js"))
    if st:
        snap["stations"] = [compact_station(r) for r in st.get("stations", [])]
        snap["stations_updated_t"] = st.get("updated_t")
    fz = read_js(os.path.join(DATA, "freezing.js"))
    g = grid("fz_0", SMOOTH_N)
    if fz and g:
        snap["fz0"] = dict(g, run_utc=fz.get("run_utc"))
    mr = read_js(os.path.join(DATA, "mrms.js"))
    g = grid("mrms_1", 256)
    if mr and g:
        snap["mrms1"] = dict(g, valid_utc=((mr.get("windows") or {}).get("1") or {}).get("valid_utc"))
    fc = read_js(os.path.join(DATA, "forecast.js"))
    if fc:
        snap["forecast_issued_utc"] = fc.get("issued_utc")
    snap["zones"] = zone_ratings(read_js(os.path.join(DATA, "avalanche.js")))
    return snap


def daily_snapshot(now_utc, log):
    snap = {"t_utc": now_utc.strftime("%Y-%m-%dT%H:%M"), "tz": os.environ.get("TZ")}
    try:
        import snotel
        sn = pack_snotel(snotel._LAST)
        if sn:
            snap["snotel"] = sn
        else:
            log("archive: no fresh SNOTEL series in memory, daily file has none")
    except Exception as e:  # noqa: BLE001
        log("archive: snotel pack failed: %r" % e)
    fc = read_js(os.path.join(DATA, "forecast.js"))
    if fc:
        snap["forecast"] = {"issued_utc": fc.get("issued_utc"), "windows": fc.get("windows"), "grids": {}}
        for k in FORECAST_KEYS:
            g = grid("fc_" + k, SMOOTH_N)
            if g:
                snap["forecast"]["grids"][k] = g
    sv = os.path.join(DATA, "snowvals")
    try:
        with open(os.path.join(sv, "meta.json"), encoding="utf-8") as f:
            m = json.load(f)
    except (OSError, ValueError):
        m = None
    if m:
        snap["ndfd"] = {"issued_utc": m.get("issued_utc"), "fields": {}}
        for key, info in (m.get("fields") or {}).items():
            fld = dict(info, grids={})
            for s in info.get("steps", []):
                g = grid("%s_%03d" % (key, s), SMOOTH_N, sv)
                if g:
                    fld["grids"][str(s)] = g
            snap["ndfd"]["fields"][key] = fld
    fz = read_js(os.path.join(DATA, "freezing.js"))
    if fz:
        snap["freezing"] = {"run_utc": fz.get("run_utc"), "hours": fz.get("hours"), "grids": {}}
        for h in FZ_HOURS:
            g = grid("fz_%d" % h, SMOOTH_N)
            if g:
                snap["freezing"]["grids"][str(h)] = g
    mr = read_js(os.path.join(DATA, "mrms.js"))
    g = grid("mrms_24", 256)
    if mr and g:
        snap["mrms24"] = dict(g, valid_utc=((mr.get("windows") or {}).get("24") or {}).get("valid_utc"))
    sd = read_js(os.path.join(DATA, "snodas.js"))
    if sd:
        snap["snodas"] = {"date": sd.get("date"), "grids": {}}
        for k in ("depth", "swe"):
            g = grid("snodas_" + k, SNODAS_N)
            if g:
                snap["snodas"]["grids"][k] = g
    st = read_js(os.path.join(DATA, "stations.js"))
    if st:
        snap["stations"] = st.get("stations", [])
        snap["windows"] = st.get("windows")
    return snap


def build(log=print):
    now_local = dt.datetime.now().replace(second=0, microsecond=0)
    now_utc = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None, second=0, microsecond=0)
    day = now_local.strftime("%Y-%m-%d")
    day_dir = os.path.join(ARCHIVE, day)
    have = existing(day, log)
    done = []
    n = write_gz(os.path.join(day_dir, now_local.strftime("%H") + ".json.gz"), hourly_snapshot(now_local, now_utc))
    done.append("%s:%dK" % (now_local.strftime("%H"), n // 1024))
    if have is not None:
        if "daily.json.gz" not in have:
            n = write_gz(os.path.join(day_dir, "daily.json.gz"), daily_snapshot(now_utc, log))
            done.append("daily:%dK" % (n // 1024))
            try:
                from snow import observations
                done.append("obs %d" % observations.build(day_dir, log))
            except Exception as e:  # noqa: BLE001
                log("archive: observations failed: %r" % e)
        try:
            from snow import avyproducts
            done.append("products +%d" % avyproducts.build(day_dir, have, log))
        except Exception as e:  # noqa: BLE001
            log("archive: products failed: %r" % e)
    log("archive %s: %s" % (day, ", ".join(done)))
    return " ".join(done)


if __name__ == "__main__":
    build()
