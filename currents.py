"""
Surface currents: NOAA CO-OPS operational forecast models, surface layer, for the map's "Surface currents (model)"
layer in the Coastal group. SSCOFS (Salish Sea and Columbia River, FVCOM, 03/09/15/21Z) on its regular 0.005 deg
product and WCOFS (West Coast shelf, ROMS, 03Z) on its regular 0.04 deg product, read as surface slices over the
CO-OPS OPeNDAP server.

In the hourly job, for regions with "coastal", whenever a newer SSCOFS or WCOFS cycle is fully posted:
  frames/currents/<cycle>/hNN.png   hours 1..24 of the SSCOFS cycle on one 0.01 deg lat/lon grid (RGB, no alpha):
                                    R = u, G = v as round(cm/s / 2) + 128 clipped to 1..255, B = 255 valid; nodata is
                                    (0, 0, 0). North-up: cell (row r, col c) is centred on
                                    (bbox[1] - (r + 0.5) * step, bbox[2] + (c + 0.5) * step)
  data/currents.js                  window.CURRENTS = {cycle, updated, updated_t, bbox: [lat0, lat1, lon0, lon1], nx, ny,
                                    step, scale_cms, hours: [{t, file}], credit}
  data/currents_cache.json          private (cloud.py STATE_FILES): the cycle on the map
<cycle> is "sscofs_tHHz_YYYYMMDD-wcofs_tHHz_YYYYMMDD", so a cycle's files never change.

SSCOFS wins wherever it has a value (nearest cell of its stride-2 sub-box), WCOFS elsewhere (nearest cell). WCOFS's
regular-grid product is 3-hourly and runs once a day, so its field at each SSCOFS hour is interpolated linearly in time
between the bracketing 3-hourly files (n024 = the cycle time), from the newest WCOFS cycle that covers all 24 hours.
A cycle with any file failing twice is abandoned and the previous one kept.

netcdf-c is not thread-safe, so the parallel reads run in worker processes (3 per model), not threads.
Design: docs/superpowers/specs/2026-10-13-currents-flow-layer-design.md.

Run standalone (writes local files, uploads nothing):  python currents.py
"""
import concurrent.futures as cf
import datetime as dt
import json
import os
import re
import shutil
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

import netCDF4
import numpy as np

import region

CATALOG = "https://opendap.co-ops.nos.noaa.gov/thredds/catalog/NOAA/%s/MODELS/%s/catalog.xml"
DODS = "https://opendap.co-ops.nos.noaa.gov/thredds/dodsC/NOAA/%s/MODELS/%s/%s"
UA = "RadarTracker/1.0 (personal weather map)"
TIMEOUT = 20                  # catalog requests (urllib)
HOURS = tuple(range(1, 25))   # SSCOFS f001..f024 (spec decision 2)
SSCOFS_BOX = (46.0, 50.2, -125.3, -121.9)   # lat0, lat1, lon0, lon1: the Sound, the Strait and the Columbia
SSCOFS_STRIDE = 2             # 0.005 deg -> about 1 km
WCOFS_EVERY = 3               # hours between WCOFS regular-grid files
WCOFS_PAD = 0.1               # degrees of WCOFS read around the window, so edge cells find a nearest neighbour
WORKERS = 3                   # per model
TRIES = 2
RETRY_PAUSE = 5.0
STEP = 0.01                   # output grid, degrees (spec decision 1)
SCALE_CMS = 2                 # cm/s per count (spec decision 3)
CREDIT = "NOAA CO-OPS SSCOFS and WCOFS operational forecast models"

DATA = region.data_dir()
OUT = os.path.join(DATA, "currents.js")
STORE = os.path.join(DATA, "currents_cache.json")
FRAME_DIR = os.path.join(region.frames_dir(), "currents")


# ---------- the THREDDS day catalogs ----------
def fetch_text(url):
    """catalog XML text; '' when the day's folder does not exist yet (404)"""
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return ""
        raise


def parse_catalog(text, model):
    """catalog XML -> {cycle (aware UTC datetime): {("f" | "n", hour), ...}} of the listed regulargrid files"""
    out = {}
    if not text.strip():
        return out
    pat = re.compile(r"^%s\.t(\d\d)z\.(\d{8})\.regulargrid\.([fn])(\d{3})\.nc$" % re.escape(model.lower()))
    for el in ET.fromstring(text).iter():
        m = pat.match(el.get("name") or "") if el.tag.endswith("dataset") else None
        if m:
            cyc = dt.datetime.strptime(m.group(2) + m.group(1), "%Y%m%d%H").replace(tzinfo=dt.timezone.utc)
            out.setdefault(cyc, set()).add((m.group(3), int(m.group(4))))
    return out


def read_catalogs(model, now):
    """merged listing of today's and yesterday's (UTC) catalogs for one model"""
    out = {}
    for back in (0, 1):
        day = (now - dt.timedelta(days=back)).strftime("%Y/%m/%d")
        for cyc, hrs in parse_catalog(fetch_text(CATALOG % (model.upper(), day)), model).items():
            out.setdefault(cyc, set()).update(hrs)
    return out


def newest_cycle(cycles, need):
    """newest cycle whose listing contains every file key in `need`; None if none"""
    ok = [c for c, hrs in cycles.items() if set(need) <= hrs]
    return max(ok) if ok else None


def _wkey(fh):
    return ("n", 24) if fh == 0 else ("f", fh)


def wcofs_plan(s_cycle, w_cycles, hours=None):
    """newest WCOFS cycle with f024 listed whose 3-hourly files bracket every SSCOFS hour ->
    (cycle, {h: (lo_key, hi_key or None, weight of hi)}); (None, None) if none"""
    hours = hours or HOURS
    for w in sorted(w_cycles, reverse=True):
        plan = {}
        for h in hours:
            fh = (s_cycle + dt.timedelta(hours=h) - w).total_seconds() / 3600.0
            if fh < 0 or fh != int(fh):
                plan = None
                break
            lo = int(fh) // WCOFS_EVERY * WCOFS_EVERY
            frac = (fh - lo) / WCOFS_EVERY
            plan[h] = (_wkey(lo), _wkey(lo + WCOFS_EVERY) if frac else None, frac)
        if plan is None:
            continue
        need = {k for lo, hi, _ in plan.values() for k in (lo, hi) if k} | {("f", 24)}
        if need <= w_cycles[w]:
            return w, plan
    return None, None


MASK_VERSION = "m1"           # bump when the land mask or compositing changes: a cycle already on R2 is then rebuilt


def cycle_id(s_cycle, w_cycle):
    tag = "-" + MASK_VERSION if os.path.exists(LANDMASK) else ""
    return "sscofs_t%s-wcofs_t%s%s" % (s_cycle.strftime("%Hz_%Y%m%d"), w_cycle.strftime("%Hz_%Y%m%d"), tag)


def file_url(model, cycle, key):
    name = "%s.t%02dz.%s.regulargrid.%s%03d.nc" % (model.lower(), cycle.hour, cycle.strftime("%Y%m%d"), key[0], key[1])
    return DODS % (model.upper(), cycle.strftime("%Y/%m/%d"), name)


# ---------- reading one file's surface slice ----------
_UNITS = {"second": 1, "seconds": 1, "minute": 60, "minutes": 60, "hour": 3600, "hours": 3600, "day": 86400, "days": 86400}


def valid_time(ds):
    """epoch second of the file's (single) time: `time` + its units, else the ISO `Times` string"""
    if "time" in ds.variables:
        var = ds.variables["time"]
        m = re.match(r"\s*(\w+)\s+since\s+(\d{4}-\d\d-\d\d)(?:[ T](\d\d:\d\d(?::\d\d)?))?", getattr(var, "units", ""))
        if m and m.group(1).lower() in _UNITS:
            hms = (m.group(3) or "00:00:00") + ("" if (m.group(3) or "").count(":") == 2 else ":00")
            base = dt.datetime.strptime(m.group(2) + " " + hms, "%Y-%m-%d %H:%M:%S").replace(tzinfo=dt.timezone.utc)
            return int(round(base.timestamp() + float(np.ravel(var[:])[0]) * _UNITS[m.group(1).lower()]))
    if "Times" in ds.variables:
        s = str(netCDF4.chartostring(np.asarray(ds.variables["Times"][:]).reshape(-1, ds.variables["Times"].shape[-1]))[0])
        return int(dt.datetime.strptime(s.strip()[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=dt.timezone.utc).timestamp())
    raise ValueError("no time or Times variable")


def _clean(a):
    a = np.ma.filled(np.ma.masked_invalid(np.ma.asarray(a, dtype=np.float32)), np.nan).astype(np.float32)
    a[np.abs(a) > 50] = np.nan          # unmasked fill values (-99999)
    return a


def read_surface(url, box, stride):
    """surface (Depth index 0) u, v [m/s] of one regulargrid file inside box (lat0, lat1, lon0, lon1) at `stride` ->
    {"lat", "lon" (1-D ascending), "u", "v" [nlat, nlon] float32 with NaN nodata, "t" epoch s}"""
    ds = netCDF4.Dataset(url)
    try:
        lat = np.asarray(ds.variables["Latitude"][:, 0], dtype=np.float64)
        lon = np.asarray(ds.variables["Longitude"][0, :], dtype=np.float64)
        i0, i1 = int(np.searchsorted(lat, box[0])), int(np.searchsorted(lat, box[1], "right"))
        j0, j1 = int(np.searchsorted(lon, box[2])), int(np.searchsorted(lon, box[3], "right"))
        if i1 - i0 < 2 or j1 - j0 < 2:
            raise ValueError("box %s misses the grid" % (box,))
        u = ds.variables["u_eastward"][0, 0, i0:i1:stride, j0:j1:stride]
        v = ds.variables["v_northward"][0, 0, i0:i1:stride, j0:j1:stride]
        t = valid_time(ds)
    finally:
        ds.close()
    return {"lat": lat[i0:i1:stride], "lon": lon[j0:j1:stride], "u": _clean(u), "v": _clean(v), "t": t}


def read_retry(url, box, stride):
    """read_surface with TRIES tries (the DAP server sometimes answers "DAP server error")"""
    err = None
    for k in range(TRIES):
        try:
            return read_surface(url, box, stride)
        except Exception as e:  # noqa: BLE001
            err = e
            if k < TRIES - 1:
                time.sleep(RETRY_PAUSE)
    raise RuntimeError("%s: %r" % (url.rsplit("/", 1)[-1], err))


def _pool(n):
    # spawned, not forked: netcdf-c/HDF5 state must not be inherited across a fork (Linux segfaults otherwise)
    import multiprocessing
    return cf.ProcessPoolExecutor(n, mp_context=multiprocessing.get_context("spawn"))


def fetch_all(jobs):
    """{key: (model, url, box, stride)} -> {key: read_surface result}, WORKERS processes per model; raises on the first
    file that failed TRIES times (the rest are cancelled)"""
    pools = {m: _pool(WORKERS) for m in sorted({j[0] for j in jobs.values()})}
    out = {}
    try:
        futs = {pools[m].submit(read_retry, url, box, stride): key for key, (m, url, box, stride) in jobs.items()}
        for f in cf.as_completed(futs):
            out[futs[f]] = f.result()
    finally:
        for p in pools.values():
            p.shutdown(wait=True, cancel_futures=True)
    return out


# ---------- the output grid ----------
def out_grid():
    """-> (lat centres N->S, lon centres W->E, bbox [lat0, lat1, lon0, lon1] of the grid's outer edges)"""
    lat0, lat1, lon0, lon1 = region.bbox()
    ny, nx = int((lat1 - lat0) / STEP + 1e-6), int((lon1 - lon0) / STEP + 1e-6)
    lat_c = lat1 - (np.arange(ny) + 0.5) * STEP
    lon_c = lon0 + (np.arange(nx) + 0.5) * STEP
    return lat_c, lon_c, [round(lat1 - ny * STEP, 6), round(lat1, 6), round(lon0, 6), round(lon0 + nx * STEP, 6)]


def nearest(axis, x):
    """indices of the cells of ascending, evenly spaced `axis` nearest each x; -1 beyond half a cell past either end"""
    axis, x = np.asarray(axis, dtype=np.float64), np.asarray(x, dtype=np.float64)
    d = (axis[-1] - axis[0]) / (len(axis) - 1)
    k = np.clip(np.searchsorted(axis, x), 1, len(axis) - 1)
    k = np.where(np.abs(x - axis[k - 1]) <= np.abs(axis[k] - x), k - 1, k)
    return np.where((x < axis[0] - d / 2) | (x > axis[-1] + d / 2), -1, k)


ROOT = os.path.dirname(os.path.abspath(__file__))
LANDMASK = os.path.join(ROOT, "currents_landmask_%s.png" % region.KEY)   # coastal_research/make_landmask.py (GSHHG)


def land_mask(shape):
    """-> bool [ny, nx], True where the cell centre is on land (GSHHG full-resolution shoreline), or None when the region
    has no mask file or its size does not match the grid. Without it the shelf model's 4 km cells reach ~2 mi inland."""
    try:
        from PIL import Image
        img = Image.open(LANDMASK).convert("L")
    except OSError:
        return None
    a = np.asarray(img)
    if a.shape != tuple(shape):
        return None
    return a < 128


def composite(layers, lat_c, lon_c):
    """[(lat, lon, u, v), ...] in rising precedence -> (u, v) [len(lat_c), len(lon_c)] float32, NaN where no layer has
    a value; each layer is sampled at its nearest cell and overrides earlier ones where it is finite"""
    u = np.full((len(lat_c), len(lon_c)), np.nan, dtype=np.float32)
    v = u.copy()
    for lat, lon, lu, lv in layers:
        ri, ci = nearest(lat, lat_c), nearest(lon, lon_c)
        inside = (ri >= 0)[:, None] & (ci >= 0)[None, :]
        su = np.asarray(lu)[np.maximum(ri, 0)[:, None], np.maximum(ci, 0)[None, :]]
        sv = np.asarray(lv)[np.maximum(ri, 0)[:, None], np.maximum(ci, 0)[None, :]]
        ok = inside & np.isfinite(su) & np.isfinite(sv)
        u[ok], v[ok] = su[ok], sv[ok]
    return u, v


def encode(u, v):
    """u, v [m/s] -> uint8 RGB [ny, nx, 3]: R, G = round(cm/s / SCALE_CMS) + 128 clipped to 1..255, B = 255; NaN -> 0,0,0"""
    ok = np.isfinite(u) & np.isfinite(v)
    rgb = np.zeros(np.shape(u) + (3,), dtype=np.uint8)
    for k, a in enumerate((u, v)):
        q = np.clip(np.floor(np.nan_to_num(a) * 100.0 / SCALE_CMS + 0.5) + 128, 1, 255)
        rgb[..., k] = np.where(ok, q, 0)
    rgb[..., 2] = np.where(ok, 255, 0)
    return rgb


def decode(rgb):
    """inverse of encode -> (u, v) m/s, NaN where B is 0"""
    rgb = np.asarray(rgb)
    ok = rgb[..., 2] > 0
    u = np.where(ok, (rgb[..., 0].astype(np.float32) - 128) * SCALE_CMS / 100.0, np.nan)
    v = np.where(ok, (rgb[..., 1].astype(np.float32) - 128) * SCALE_CMS / 100.0, np.nan)
    return u, v


# ---------- state ----------
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
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(path + ".tmp", path)


def prune_local(keep):
    """remove local cycle folders (and leftover .tmp folders) other than `keep` and the newest other one"""
    if not os.path.isdir(FRAME_DIR):
        return
    dirs = [d for d in os.listdir(FRAME_DIR) if os.path.isdir(os.path.join(FRAME_DIR, d))]
    others = sorted((d for d in dirs if d != keep and not d.endswith(".tmp")),
                    key=lambda d: os.path.getmtime(os.path.join(FRAME_DIR, d)), reverse=True)
    for d in others[1:] + [d for d in dirs if d.endswith(".tmp")]:
        shutil.rmtree(os.path.join(FRAME_DIR, d), ignore_errors=True)


# ---------- the job ----------
def build(log=print, now=None):
    """build the newest complete SSCOFS + WCOFS cycle if it is not on the map yet; -> the cycle, or a short status"""
    if not region.cfg().get("coastal"):
        return None
    from PIL import Image
    t_start = time.time()
    now_dt = dt.datetime.fromtimestamp(now or t_start, dt.timezone.utc)
    store = load_store()
    old = store.get("cycle") or "nothing"
    try:
        s_cycles, w_cycles = read_catalogs("sscofs", now_dt), read_catalogs("wcofs", now_dt)
    except Exception as e:  # noqa: BLE001  (a failing host must not stop the hourly job)
        log("currents: could not read the THREDDS catalogs (%r); keeping %s" % (e, old))
        return "failed"
    s = newest_cycle(s_cycles, {("f", HOURS[-1])})
    w, plan = wcofs_plan(s, w_cycles) if s else (None, None)
    if s is None or w is None:
        log("currents: no complete %s cycle listed today or yesterday; keeping %s" % ("SSCOFS" if s is None else "WCOFS", old))
        return "no cycle"
    cycle = cycle_id(s, w)
    if store.get("cycle") == cycle:
        log("currents: unchanged %s" % cycle)
        return cycle

    wbox = tuple(np.add(region.bbox(), (-WCOFS_PAD, WCOFS_PAD, -WCOFS_PAD, WCOFS_PAD)))
    jobs = {("sscofs", h): ("sscofs", file_url("sscofs", s, ("f", h)), SSCOFS_BOX, SSCOFS_STRIDE) for h in HOURS}
    for k in sorted({k for lo, hi, _ in plan.values() for k in (lo, hi) if k}):
        jobs[("wcofs", k)] = ("wcofs", file_url("wcofs", w, k), wbox, 1)
    try:
        got = fetch_all(jobs)
    except Exception as e:  # noqa: BLE001
        log("currents: %s abandoned, a file failed %d times (%s); keeping %s" % (cycle, TRIES, e, old))
        return "failed"

    lat_c, lon_c, bbox = out_grid()
    land = land_mask((len(lat_c), len(lon_c)))
    if land is None:
        log("currents: no land mask for %s (%s); coarse model cells may overlap the shore" % (region.KEY, os.path.basename(LANDMASK)))
    tmp, final = os.path.join(FRAME_DIR, cycle + ".tmp"), os.path.join(FRAME_DIR, cycle)
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    hours, n_h1 = [], 0
    try:
        for h in HOURS:
            S = got[("sscofs", h)]
            t = int((s + dt.timedelta(hours=h)).timestamp())
            lo, hi, f = plan[h]
            W = got[("wcofs", lo)]
            checks = [(S["t"], t, "sscofs f%03d" % h), (W["t"], int(w.timestamp()) + 3600 * (0 if lo[0] == "n" else lo[1]), "wcofs %s%03d" % lo)]
            uw, vw = W["u"], W["v"]
            if hi:
                W2 = got[("wcofs", hi)]
                checks.append((W2["t"], int(w.timestamp()) + 3600 * hi[1], "wcofs f%03d" % hi[1]))
                if W2["u"].shape != uw.shape:
                    raise ValueError("WCOFS grid changed within the cycle")
                uw, vw = (1 - f) * uw + f * W2["u"], (1 - f) * vw + f * W2["v"]
            for got_t, want_t, what in checks:
                if abs(got_t - want_t) > 60:
                    raise ValueError("%s valid time %d, expected %d" % (what, got_t, want_t))
            u, v = composite([(W["lat"], W["lon"], uw, vw), (S["lat"], S["lon"], S["u"], S["v"])], lat_c, lon_c)
            if land is not None:
                u[land], v[land] = np.nan, np.nan        # the shoreline, not the models' coarse cells, decides what is water
            rgb = encode(u, v)
            if h == HOURS[0]:
                n_h1 = int((rgb[..., 2] == 255).sum())
            Image.fromarray(rgb, "RGB").save(os.path.join(tmp, "h%02d.png" % h), "PNG", optimize=True)
            hours.append({"t": t, "file": "frames/currents/%s/h%02d.png" % (cycle, h)})
    except Exception as e:  # noqa: BLE001
        shutil.rmtree(tmp, ignore_errors=True)
        log("currents: %s abandoned while compositing (%r); keeping %s" % (cycle, e, old))
        return "failed"
    shutil.rmtree(final, ignore_errors=True)
    os.replace(tmp, final)

    meta = {"cycle": cycle, "updated": dt.datetime.now().strftime("%a %b %d %I:%M %p"), "updated_t": int(time.time()),
            "bbox": bbox, "nx": len(lon_c), "ny": len(lat_c), "step": STEP, "scale_cms": SCALE_CMS, "hours": hours,
            "credit": CREDIT}
    _write(OUT, "window.CURRENTS = %s;\n" % json.dumps(meta, separators=(",", ":")))
    _write(STORE, json.dumps({"v": 1, "cycle": cycle, "built_t": int(t_start)}))
    prune_local(cycle)
    log("currents: %s %d hours, %d s, %d valid cells at h%02d" % (cycle, len(hours), time.time() - t_start, n_h1, HOURS[0]))
    return cycle


if __name__ == "__main__":
    build()
