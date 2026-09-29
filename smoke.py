"""
Smoke forecast: NOAA HRRR near-surface smoke (MASSDEN, 8 m above ground), the map's "Smoke & fires" section, phase 3.

In the hourly job, for the region in REGION, whenever a newer complete 48 h run (00/06/12/18Z) is posted:
  frames/smoke/<slot><hh>.webp   smoke categories for forecast hours 1..48 (lossless, 640 px)
  data/values/smoke_<slot>.js    window.VALUES["smoke_<slot>"]: 128 x 128 cells x 48 hours, tenths of ug/m3, click-anywhere
  data/smoke.js                  window.SMOKE = {run_utc, run_t, updated, updated_t, slot, floor, coverage, hours, series, edge}
  data/smoke_cache.json          private (cloud.py STATE_FILES): the run on the map, its slot, when it was built
A new run goes into the slot ("a" or "b") the page is not using, and smoke.js switches last, so the page never pairs one
run's image with another run's time. Hours with no new run write nothing.

Source: AWS open data (noaa-hrrr-bdp-pds), one byte-range request per hour found through the .idx file.
Requests reuse airquality's User-Agent, timeout, runner cache and hung-host rule.
Design: docs/superpowers/specs/2026-09-28-hrrr-smoke-layer-design.md; sources: smoke_research/sources_notes.md.

Run standalone (writes local files, uploads nothing):  python smoke.py
"""
import datetime as dt
import hashlib
import json
import math
import os
import time
import urllib.error
import urllib.request
import warnings

import numpy as np

import region
from airquality import AQ_COLORS, CACHE_DIR, CACHE_MAX_AGE_S, HostDown, NotPosted, UA, _open, fetch  # noqa: F401  (shared request helpers)

SRC = "https://noaa-hrrr-bdp-pds.s3.amazonaws.com/hrrr.%s/conus/hrrr.t%02dz.wrfsfcf%02d.grib2"
RECORD = ":MASSDEN:8 m above ground:"        # found by its .idx text, never by record number
HOURS = tuple(range(1, 49))                  # f01..f48 of the 00/06/12/18Z runs (Chris, decision 2; f00 left out)
RUN_EVERY_H = 6
FIRST_CHECK = dt.timedelta(minutes=100)      # f48 is posted ~1 h 49 min after the run (checked 2026-09-29)
LOOKBACK_H = 30                              # oldest run still worth showing (18 h of forecast left)
DEADLINE_S = 240                             # per region step (judgment call; the hourly job has 45 min)
FLOOR = 2.0                                  # ug/m3: transparent below (judgment call, spec decision 4)
EDGES = (FLOOR, 9.1, 35.5, 55.5, 125.5, 225.5)   # light smoke, then EPA's 2024 PM2.5 AQI category starts
LIGHT = (150, 140, 128, 110)                 # light smoke (still AQI Good): translucent warm grey (judgment call)
SIZE = 640                                   # frame and computation size: half the 1280 px window, like freezing.py
CELLS = 128                                  # value cells per side for click-anywhere (~9-12 km)
EDGE_MARGIN = 0.3                            # degrees: the model-edge line runs this far past the window

DATA = region.data_dir()
OUT = os.path.join(DATA, "smoke.js")
STORE = os.path.join(DATA, "smoke_cache.json")
FRAME_DIR = os.path.join(region.frames_dir(), "smoke")
VALUES_DIR = os.path.join(DATA, "values")


# ---------- the .idx file ----------
def idx_range(text, record):
    """byte range (start, end) of the first message whose .idx line contains `record`; end None for the last message"""
    lines = [ln.split(":") for ln in text.splitlines() if ln.count(":") >= 2]
    for k, parts in enumerate(lines):
        if record in ":" + ":".join(parts[3:]):
            start = int(parts[1])
            for nxt in lines[k + 1:]:
                if int(nxt[1]) > start:
                    return start, int(nxt[1]) - 1
            return start, None
    return None


# ---------- the model's Lambert conformal grid (tangent cone, spherical earth) ----------
def _cone(grid):
    phi0 = math.radians(grid["latin"])
    n = math.sin(phi0)
    return n, grid["radius"] * math.cos(phi0) * math.tan(math.pi / 4 + phi0 / 2) ** n / n


def _xy(grid, lat, lon):
    n, rf = _cone(grid)
    dl = np.radians((np.asarray(lon, dtype=np.float64) - grid["lov"] + 180.0) % 360.0 - 180.0)
    rho = rf / np.tan(np.pi / 4 + np.radians(np.asarray(lat, dtype=np.float64)) / 2) ** n
    return rho * np.sin(n * dl), -rho * np.cos(n * dl)


def lcc_ij(grid, lat, lon):
    """latitude/longitude (degrees) -> fractional grid indices (i east, j north) of the first point's grid"""
    x0, y0 = _xy(grid, grid["lat1"], grid["lon1"])
    x, y = _xy(grid, lat, lon)
    return (x - x0) / grid["dx"], (y - y0) / grid["dx"]


def lcc_latlon(grid, fi, fj):
    """fractional grid indices -> latitude, longitude (degrees, longitude in -180..180)"""
    n, rf = _cone(grid)
    x0, y0 = _xy(grid, grid["lat1"], grid["lon1"])
    x = x0 + np.asarray(fi, dtype=np.float64) * grid["dx"]
    y = y0 + np.asarray(fj, dtype=np.float64) * grid["dx"]
    rho = np.sign(n) * np.hypot(x, y)
    lat = np.degrees(2 * np.arctan((rf / rho) ** (1 / n)) - np.pi / 2)
    lon = (grid["lov"] + np.degrees(np.arctan2(x, -y)) / n + 180.0) % 360.0 - 180.0
    return lat, lon


# ---------- the region window (5 x 5 zoom-7 Web Mercator tiles) ----------
def window_latlon(size=SIZE):
    """pixel-centre latitudes (top to bottom) and longitudes (left to right) of the window at size x size px"""
    z, x0, x1, y0, y1 = region.window()
    n = 2 ** z
    ys = (np.arange(size) + 0.5) / size * (y1 - y0 + 1) + y0
    xs = (np.arange(size) + 0.5) / size * (x1 - x0 + 1) + x0
    return np.degrees(np.arctan(np.sinh(np.pi - 2 * np.pi * ys / n))), xs / n * 360.0 - 180.0


def resample(field, grid, size=SIZE):
    """model field [nj, ni] -> window [size, size], bilinear; NaN outside the model's grid"""
    from scipy.ndimage import map_coordinates
    lat, lon = window_latlon(size)
    la, lo = np.meshgrid(lat, lon, indexing="ij")
    fi, fj = lcc_ij(grid, la, lo)
    out = map_coordinates(np.asarray(field, dtype=np.float32), [fj.ravel(), fi.ravel()], order=1, mode="constant",
                          cval=np.nan, prefilter=False)
    outside = (fi < 0) | (fj < 0) | (fi > grid["ni"] - 1) | (fj > grid["nj"] - 1)
    return np.where(outside.ravel(), np.nan, out).reshape(size, size).astype(np.float32)


# ---------- frames ----------
def category(ug):
    """ug/m3 -> -1 transparent (below the floor, or no value), 0 light smoke, 1..5 Moderate..Hazardous"""
    a = np.asarray(ug, dtype=np.float64)
    k = np.digitize(np.nan_to_num(a, nan=-1.0), EDGES) - 1
    return np.where(np.isnan(a), -1, k)


def frame_rgba(ug):
    table = np.array([(0, 0, 0, 0), LIGHT] + [c + (255,) for c in AQ_COLORS[1:]], dtype=np.uint8)
    return table[category(ug) + 1]


# ---------- click-anywhere values ----------
def series_blocks(ug, n=CELLS):
    """window field [size, size] -> [n, n] block means in tenths of ug/m3, truncated like EPA's AQI rule (so a cell's
    category on the page matches the frame's for the same value); -1 where the block is all NaN (outside the model)"""
    a = np.asarray(ug, dtype=np.float64)
    f = a.shape[0] // n
    if a.ndim != 2 or a.shape[0] != a.shape[1] or f < 1:
        raise ValueError("need a square field of at least %d px, got %s" % (n, a.shape))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)       # all-NaN blocks (outside the model)
        m = np.nanmean(a[:f * n, :f * n].reshape(n, f, n, f), axis=(1, 3))
    tenths = np.floor(np.maximum(np.nan_to_num(m), 0.0) * 10 + 1e-6)
    return np.where(np.isnan(m), -1, tenths).astype(np.int64)


def series_js(name, blocks, t0, unit="µg/m³"):
    """hour-major value series -> the window.VALUES script the page loads for click-anywhere"""
    h, w = blocks[0].shape
    head = {"w": int(w), "h": int(h), "n": len(blocks), "t0": int(t0), "dt": 3600, "scale": 0.1, "unit": unit, "nodata": -1}
    body = ",".join(str(int(v)) for b in blocks for v in np.asarray(b).ravel())
    key = json.dumps(name)
    return ('window.VALUES=window.VALUES||{};window.VALUES[%s]=%s;window.VALUES[%s].data="%s";\n'
            % (key, json.dumps(head, separators=(",", ":")), key, body))


# ---------- the model's edge inside the window ----------
def edge_segments(grid, step=10):
    """the model grid's boundary as [[lat, lon], ...] runs inside the window (+ EDGE_MARGIN); [] if it misses it"""
    lat0, lat1, lon0, lon1 = region.bbox()
    ni, nj = grid["ni"] - 1, grid["nj"] - 1
    si, sj = np.arange(0, ni + 1, step, dtype=float), np.arange(0, nj + 1, step, dtype=float)
    sides = [(si, np.zeros_like(si)), (np.full_like(sj, ni), sj), (si[::-1], np.full_like(si, nj)), (np.zeros_like(sj), sj[::-1])]
    segs = []
    for fi, fj in sides:
        la, lo = lcc_latlon(grid, fi, fj)
        inside = (la >= lat0 - EDGE_MARGIN) & (la <= lat1 + EDGE_MARGIN) & (lo >= lon0 - EDGE_MARGIN) & (lo <= lon1 + EDGE_MARGIN)
        run = []
        for ok, a, b in zip(inside, la, lo):
            if ok:
                run.append([round(float(a), 3), round(float(b), 3)])
            elif run:
                segs.append(run)
                run = []
        if run:
            segs.append(run)
    return [s for s in segs if len(s) >= 2]


# ---------- fetching and decoding ----------
def url_for(run, fh):
    return SRC % (run.strftime("%Y%m%d"), run.hour, fh)


def fetch_range(url, start, end):
    """one GRIB2 message by HTTP Range (end None = to the end of the file). It must start with GRIB, end with 7777 and,
    for a closed range, have exactly that many bytes; else RuntimeError. Shared through the runner cache like fetch()."""
    rng = "bytes=%d-%s" % (start, "" if end is None else end)
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = os.path.join(CACHE_DIR, hashlib.sha1((url + "#" + rng).encode()).hexdigest())
    if os.path.exists(path) and time.time() - os.path.getmtime(path) < CACHE_MAX_AGE_S:
        with open(path, "rb") as f:
            return f.read()
    try:
        with _open(urllib.request.Request(url, headers={"User-Agent": UA, "Range": rng})) as r:
            body = r.read()
    except urllib.error.HTTPError as e:
        if e.code in (403, 404):          # S3 answers 403 for a key that does not exist
            raise NotPosted(url) from e
        raise
    if body[:4] != b"GRIB" or body[-4:] != b"7777" or (end is not None and len(body) != end - start + 1):
        raise RuntimeError("not one whole GRIB message: %s %s (%d bytes)" % (url.rsplit("/", 1)[-1], rng, len(body)))
    with open(path + ".tmp", "wb") as f:
        f.write(body)
    os.replace(path + ".tmp", path)
    return body


def decode(msg):
    """one GRIB2 message -> (smoke ug/m3 [nj, ni] float32, grid dict). Only HRRR's kind of message is accepted: aerosol
    mass density (discipline 0, category 20, number 0) on a tangent Lambert grid scanning west-east, south-north."""
    import eccodes
    g = eccodes.codes_new_from_message(msg)
    try:
        get = lambda k: eccodes.codes_get(g, k)  # noqa: E731
        if (get("discipline"), get("parameterCategory"), get("parameterNumber")) != (0, 20, 0):
            raise ValueError("not aerosol mass density: %s %s %s" % (get("discipline"), get("parameterCategory"), get("parameterNumber")))
        if get("gridType") != "lambert" or get("Latin1InDegrees") != get("Latin2InDegrees") or get("DxInMetres") != get("DyInMetres") \
                or get("iScansNegatively") != 0 or get("jScansPositively") != 1:
            raise ValueError("unexpected grid: %s" % get("gridType"))
        grid = {"ni": int(get("Ni")), "nj": int(get("Nj")), "lat1": float(get("latitudeOfFirstGridPointInDegrees")),
                "lon1": float(get("longitudeOfFirstGridPointInDegrees")), "lov": float(get("LoVInDegrees")),
                "latin": float(get("Latin1InDegrees")), "dx": float(get("DxInMetres")), "radius": float(get("radius"))}
        v = eccodes.codes_get_values(g).astype(np.float64)
        if get("bitmapPresent"):
            v[v == get("missingValue")] = np.nan
    finally:
        eccodes.codes_release(g)
    ug = np.maximum(v * 1e9, 0.0)                      # kg/m3 -> ug/m3; packing can leave tiny negatives
    return ug.reshape(grid["nj"], grid["ni"]).astype(np.float32), grid


def latest_run(now):
    """newest 00/06/12/18Z run (aware UTC datetime) whose f48 is posted, at most LOOKBACK_H old; None if none"""
    run = now.replace(minute=0, second=0, microsecond=0)
    run -= dt.timedelta(hours=run.hour % RUN_EVERY_H)
    while now - run <= dt.timedelta(hours=LOOKBACK_H):
        if now - run >= FIRST_CHECK:
            try:
                fetch(url_for(run, HOURS[-1]) + ".idx")
                return run
            except NotPosted:
                pass
        run -= dt.timedelta(hours=RUN_EVERY_H)
    return None


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


def _write(path, data, mode="w"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".tmp", mode, **({} if "b" in mode else {"encoding": "utf-8"})) as f:
        f.write(data)
    os.replace(path + ".tmp", path)


def next_slot(store, rid):
    """the slot a build of run `rid` writes: the one the live smoke.js does not use (the stored one only when the
    stored run is being rebuilt, i.e. its upload never landed)"""
    if store.get("run") == rid and store.get("slot") in ("a", "b"):
        return store["slot"]
    return "b" if store.get("slot") == "a" else "a"


def remote_stale(store):
    """True when R2 is known (cloud.py listed it) and its smoke.js is missing or older than the stored build"""
    import r2sync
    if not r2sync.REMOTE:
        return False
    got = r2sync.REMOTE.get(region.prefix() + "data/smoke.js")
    return got is None or got[1].timestamp() < store.get("built_t", 0)


# ---------- the job ----------
def build(log=print, now=None):
    """build the newest complete run if it is not on the map yet; returns a short status for the cycle line"""
    from PIL import Image
    t_start = time.time()
    now_dt = dt.datetime.fromtimestamp(now or t_start, dt.timezone.utc)
    store = load_store()
    try:
        run = latest_run(now_dt)
    except Exception as e:  # noqa: BLE001  (a hung or failing host must not stop the hourly job)
        log("smoke: could not look for a new HRRR run: %r" % e)
        return "failed"
    if run is None:
        log("smoke: no complete HRRR run in the last %d h; the map keeps what it has" % LOOKBACK_H)
        return "no run"
    rid, name = run.strftime("%Y%m%d%H"), run.strftime("%HZ %b %d")
    if store.get("run") == rid and not remote_stale(store):
        log("smoke: HRRR %s already on the map; next run %02dZ" % (name, (run.hour + RUN_EVERY_H) % 24))
        return run.strftime("%HZ unchanged")
    slot, run_t = next_slot(store, rid), int(run.timestamp())
    grid, hours, blocks, nbytes, peak, coverage = None, [], [], 0, (-1.0, 0), None
    for fh in HOURS:
        url = url_for(run, fh)
        try:
            if time.time() - t_start > DEADLINE_S:
                raise RuntimeError("out of time (%d s)" % DEADLINE_S)
            rng = idx_range(fetch(url + ".idx")[0].decode("utf-8", "replace"), RECORD)
            if rng is None:
                raise RuntimeError("no %s record" % RECORD.strip(":"))
            msg = fetch_range(url, *rng)
            ug, g = decode(msg)
            if grid is not None and g != grid:
                raise RuntimeError("grid changed within the run")
        except Exception as e:  # noqa: BLE001
            log("smoke: HRRR %s f%02d failed (%r); keeping the run on the map" % (name, fh, e))
            return "failed"
        grid, nbytes = g, nbytes + len(msg)
        field = resample(ug, grid, SIZE)
        if coverage is None:
            coverage = float(np.mean(~np.isnan(field)))
        img = Image.fromarray(frame_rgba(field), "RGBA")
        fn = "%s%02d.webp" % (slot, fh)
        os.makedirs(FRAME_DIR, exist_ok=True)
        img.save(os.path.join(FRAME_DIR, fn + ".tmp.webp"), "WEBP", lossless=True, method=4)
        os.replace(os.path.join(FRAME_DIR, fn + ".tmp.webp"), os.path.join(FRAME_DIR, fn))
        blocks.append(series_blocks(field, CELLS))
        top = float(np.nanmax(field)) if coverage else 0.0
        peak = max(peak, (top, fh), key=lambda p: p[0])
        hours.append({"h": fh, "t": run_t + 3600 * fh, "file": "frames/smoke/%s?v=%d" % (fn, run_t), "max": int(math.floor(top + 0.5))})
    series = "smoke_" + slot
    _write(os.path.join(VALUES_DIR, series + ".js"), series_js(series, blocks, t0=run_t + 3600 * HOURS[0]))
    meta = {"run_utc": run.strftime("%Y-%m-%dT%H:%MZ"), "run_t": run_t, "updated": dt.datetime.now().strftime("%a %b %d %I:%M %p"),
            "updated_t": int(time.time()), "slot": slot, "floor": FLOOR, "coverage": round(coverage, 3), "hours": hours,
            "series": series, "edge": edge_segments(grid)}
    _write(OUT, "window.SMOKE = %s;\n" % json.dumps(meta, separators=(",", ":")))
    _write(STORE, json.dumps({"v": 1, "run": rid, "slot": slot, "built_t": int(t_start)}))
    log("smoke: HRRR %s -> slot %s, %d h, peak %d ug/m3 (f%02d), %d%% of window in the model, %.1f MB, %d s"
        % (name, slot, len(hours), math.floor(peak[0] + 0.5), peak[1], round(100 * coverage), nbytes / 1e6, time.time() - t_start))
    return run.strftime("%HZ new")


if __name__ == "__main__":
    build()
