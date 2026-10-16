"""
Swell forecast: NOAA GFS-Wave (WAVEWATCH III) on its west-coast 0.16 deg grid, for the map's "Swell forecast" layer and
the 7-day forecast in the buoy popups (Coastal group).

In the hourly job, for regions with "coastal", whenever a newer cycle (00/06/12/18Z) has posted f168:
  frames/swell/<cycle>/sNN.png   one per 3-h step, NN = 00..56 for f000..f168, on a 0.04 deg lat/lon window grid
                                 (RGB, no alpha), three bands stacked vertically: rows 0..ny-1 swell partition 1 (the
                                 primary), then partition 2, then 3. Per band R = height in 0.1 m (cap 25.5 m), G = period
                                 in 0.5 s (cap 63.5 s), B = direction (from, deg) / 2 (0..179); B = 255 where the
                                 partition is absent or the cell is nodata (land, outside the model). North-up: cell (r, c)
                                 is centred on (bbox[1] - (r + 0.5) * step, bbox[2] + (c + 0.5) * step), like currents.
  data/swell.js                  window.SWELL = {cycle, updated, updated_t, bbox, nx, ny, step, bands, hours: [{t, file}], credit}
  data/swell_points.js           window.SWELL_POINTS = {cycle, updated_t, points: {<buoy id>: {t0, dt, p1, p2, p3, hs}}}:
                                 [h_ft, per_s, dir_deg] or null per step, sampled from the model's own grid at each
                                 station of data/buoys.js (stations whose every value is null, e.g. inland gauges, left out)
  data/swell_cache.json          private (cloud.py STATE_FILES): the cycle on the map
<cycle> is "gfswave_tHHz_YYYYMMDD", so a cycle's files never change.

Each step is 12 byte-range requests found through the step's .idx (SWELL/SWPER/SWDIR for "1..3 in sequence", plus
HTSGW/PERPW/DIRPW). Any request failing TRIES times abandons the cycle and the previous one is kept; frames are written
to a .tmp folder and renamed only when every step succeeded.
Resampling is bilinear over the valid corners (weights renormalised, so the coast keeps its values; NaN only where all
four corners are nodata); directions are interpolated as unit vectors. The currents land mask (0.01 deg, GSHHG) blanks
cells whose centre is on land.
Design: docs/superpowers/specs/2026-10-15-swell-forecast-design.md.

Run standalone (writes local files, uploads nothing):  python swell.py
"""
import concurrent.futures as cf
import datetime as dt
import json
import os
import shutil
import time
import urllib.error
import urllib.request

import numpy as np

import region

SRC = "https://noaa-gfs-bdp-pds.s3.amazonaws.com/gfs.%s/%02d/wave/gridded/gfswave.t%02dz.wcoast.0p16.f%03d.grib2"
UA = "RadarTracker/1.0 (personal weather map)"
TIMEOUT = 20
TRIES = 2
RETRY_PAUSE = 3.0
WORKERS = 12                       # parallel range requests (one step's worth)
RUNS = (18, 12, 6, 0)
STEPS = tuple(range(0, 169, 3))    # f000..f168 every 3 h: 57 steps (spec decision 1)
DT = 10800
STEP = 0.04                        # output grid, degrees (spec decision 1)
M_TO_FT = 3.28084
CREDIT = "NOAA GFS-Wave (WAVEWATCH III)"
PARTS = ("1 in sequence", "2 in sequence", "3 in sequence")
# (idx variable, idx level) -> GRIB2 discipline 10 category 0 parameter number (WMO table 4.2-10-0)
FIELDS = tuple((v, lev) for lev in PARTS for v in ("SWELL", "SWPER", "SWDIR")) + \
    (("HTSGW", "surface"), ("PERPW", "surface"), ("DIRPW", "surface"))
PARAM = {"SWELL": 8, "SWPER": 9, "SWDIR": 7, "HTSGW": 3, "PERPW": 11, "DIRPW": 10}

DATA = region.data_dir()
OUT = os.path.join(DATA, "swell.js")
POINTS_OUT = os.path.join(DATA, "swell_points.js")
STORE = os.path.join(DATA, "swell_cache.json")
BUOYS = os.path.join(DATA, "buoys.js")
FRAME_DIR = os.path.join(region.frames_dir(), "swell")


class NotPosted(Exception):
    """the file is not on the server (yet)"""


# ---------- requests ----------
def get(url, rng=None):
    """-> bytes; one try. 403/404 (S3's answer for a missing key) -> NotPosted"""
    headers = {"User-Agent": UA}
    if rng:
        headers["Range"] = "bytes=%d-%s" % (rng[0], "" if rng[1] is None else rng[1])
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=TIMEOUT) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        if e.code in (403, 404):
            raise NotPosted(url) from e
        raise


def get_retry(url, rng=None):
    """get with TRIES tries; NotPosted is raised at once (the key is not there, asking again won't help)"""
    err = None
    for k in range(TRIES):
        try:
            return get(url, rng)
        except NotPosted:
            raise
        except Exception as e:  # noqa: BLE001
            err = e
            if k < TRIES - 1:
                time.sleep(RETRY_PAUSE)
    raise RuntimeError("%s %s: %r" % (url.rsplit("/", 1)[-1], rng or "", err))


def fetch_range(url, rng):
    """one whole GRIB2 message by byte range (2 tries); RuntimeError unless it starts GRIB and ends 7777"""
    body = get_retry(url, rng)
    if body[:4] != b"GRIB" or body[-4:] != b"7777" or (rng[1] is not None and len(body) != rng[1] - rng[0] + 1):
        raise RuntimeError("not one whole GRIB message: %s %s (%d bytes)" % (url.rsplit("/", 1)[-1], rng, len(body)))
    return body


def url_for(cycle, fh):
    return SRC % (cycle.strftime("%Y%m%d"), cycle.hour, cycle.hour, fh)


def cycle_id(cycle):
    return "gfswave_t%s" % cycle.strftime("%Hz_%Y%m%d")


def posted(url):
    try:
        get_retry(url)
        return True
    except NotPosted:
        return False


def latest_cycle(now):
    """newest 00/06/12/18Z cycle, today then yesterday (UTC), whose f168 .idx is posted; None if none"""
    for back in (0, 1):
        day = (now - dt.timedelta(days=back)).replace(minute=0, second=0, microsecond=0)
        for hh in RUNS:
            cyc = day.replace(hour=hh)
            if cyc <= now and posted(url_for(cyc, STEPS[-1]) + ".idx"):
                return cyc
    return None


# ---------- the .idx file ----------
def idx_ranges(text, fields=FIELDS):
    """.idx text -> {(var, level): (start, end or None for the file's last message)} for every field; KeyError if one is
    missing. Lines look like '9:115837:d=2026101518:SWELL:1 in sequence:anl:'."""
    rows = [ln.split(":") for ln in text.splitlines() if ln.count(":") >= 4]
    starts = sorted({int(p[1]) for p in rows})
    out = {}
    for p in rows:
        key = (p[3], p[4])
        if key in fields and key not in out:
            start = int(p[1])
            later = [s for s in starts if s > start]
            out[key] = (start, later[0] - 1 if later else None)
    missing = [f for f in fields if f not in out]
    if missing:
        raise KeyError("not in the .idx: %s" % ", ".join("%s:%s" % m for m in missing))
    return out


# ---------- decoding ----------
def decode(msg, field=None):
    """one GRIB2 message on a regular lat/lon grid -> (lat ascending [nj], lon ascending in -180..180 [ni],
    values [nj, ni] float32, NaN where the bitmap says missing, valid time as epoch s). With `field` (var, level) the
    message must be that parameter (discipline 10, category 0) and, for a partition, that sequence number."""
    import eccodes
    g = eccodes.codes_new_from_message(msg)
    try:
        get_ = lambda k: eccodes.codes_get(g, k)  # noqa: E731
        if get_("gridType") != "regular_ll" or get_("iScansNegatively") != 0:
            raise ValueError("unexpected grid: %s" % get_("gridType"))
        if field is not None:
            var, lev = field
            got = (get_("discipline"), get_("parameterCategory"), get_("parameterNumber"))
            if got != (10, 0, PARAM[var]):
                raise ValueError("%s:%s message is parameter %s" % (var, lev, got))
            if lev in PARTS and get_("scaledValueOfFirstFixedSurface") != PARTS.index(lev) + 1:
                raise ValueError("%s:%s message is sequence %s" % (var, lev, get_("scaledValueOfFirstFixedSurface")))
        ni, nj = int(get_("Ni")), int(get_("Nj"))
        lat = np.linspace(get_("latitudeOfFirstGridPointInDegrees"), get_("latitudeOfLastGridPointInDegrees"), nj)
        lon = np.linspace(get_("longitudeOfFirstGridPointInDegrees"), get_("longitudeOfLastGridPointInDegrees"), ni)
        v = eccodes.codes_get_values(g).astype(np.float64)
        if get_("bitmapPresent"):
            v[v == get_("missingValue")] = np.nan
        vd, vt = str(get_("validityDate")), int(get_("validityTime"))
        t = int(dt.datetime.strptime(vd, "%Y%m%d").replace(hour=vt // 100, minute=vt % 100, tzinfo=dt.timezone.utc).timestamp())
    finally:
        eccodes.codes_release(g)
    v = v.reshape(nj, ni)
    if lat[0] > lat[-1]:                 # GFS-Wave scans north to south
        lat, v = lat[::-1], v[::-1]
    lon = (lon + 180.0) % 360.0 - 180.0  # 0-360 -> -180..180 (the west-coast grid, 210-250 E, does not wrap)
    if np.any(np.diff(lon) <= 0):
        raise ValueError("grid crosses the antimeridian")
    return lat, lon, v.astype(np.float32), t


# ---------- resampling ----------
def out_grid(step=STEP):
    """-> (lat centres N->S, lon centres W->E, bbox [lat0, lat1, lon0, lon1] of the grid's outer edges); currents.out_grid"""
    lat0, lat1, lon0, lon1 = region.bbox()
    ny, nx = int((lat1 - lat0) / step + 1e-6), int((lon1 - lon0) / step + 1e-6)
    lat_c = lat1 - (np.arange(ny) + 0.5) * step
    lon_c = lon0 + (np.arange(nx) + 0.5) * step
    return lat_c, lon_c, [round(lat1 - ny * step, 6), round(lat1, 6), round(lon0, 6), round(lon0 + nx * step, 6)]


def _corners(lat, lon, plat, plon):
    """points -> (4 flat corner indices [4, n], 4 weights [4, n]) on the ascending, evenly spaced grid; weight 0 outside"""
    fi = (np.asarray(plat, dtype=np.float64) - lat[0]) / ((lat[-1] - lat[0]) / (len(lat) - 1))
    fj = (np.asarray(plon, dtype=np.float64) - lon[0]) / ((lon[-1] - lon[0]) / (len(lon) - 1))
    inside = (fi >= 0) & (fi <= len(lat) - 1) & (fj >= 0) & (fj <= len(lon) - 1)
    i0 = np.clip(np.floor(fi).astype(int), 0, len(lat) - 2)
    j0 = np.clip(np.floor(fj).astype(int), 0, len(lon) - 2)
    a, b = np.clip(fi - i0, 0, 1), np.clip(fj - j0, 0, 1)
    idx = np.stack([i0 * len(lon) + j0, i0 * len(lon) + j0 + 1, (i0 + 1) * len(lon) + j0, (i0 + 1) * len(lon) + j0 + 1])
    w = np.stack([(1 - a) * (1 - b), (1 - a) * b, a * (1 - b), a * b]) * inside
    return idx, w


def interp(lat, lon, fields, plat, plon, angular=()):
    """bilinear values of each [nj, ni] field at the points, over the corners where every field is finite (weights
    renormalised); NaN where no corner is. Fields named in `angular` (indices) are directions in degrees, interpolated as
    unit vectors. -> list of arrays shaped like plat."""
    shape = np.shape(plat)
    idx, w = _corners(lat, lon, np.ravel(plat), np.ravel(plon))
    flat = [np.asarray(f, dtype=np.float64).ravel() for f in fields]
    ok = np.all([np.isfinite(f[idx]) for f in flat], axis=0)
    w = np.where(ok, w, 0.0)
    tot = w.sum(axis=0)
    good = tot > 1e-9
    out = []
    for k, f in enumerate(flat):
        v = np.nan_to_num(f[idx])
        if k in angular:
            r = np.radians(v)
            val = np.degrees(np.arctan2((w * np.sin(r)).sum(0), (w * np.cos(r)).sum(0))) % 360.0
        else:
            val = (w * v).sum(0) / np.where(good, tot, 1.0)
        out.append(np.where(good, val, np.nan).reshape(shape))
    return out


def land_mask(lat_c, lon_c):
    """bool [ny, nx], True where the cell centre falls in a land cell of the currents 0.01 deg GSHHG mask; None when the
    region has no mask (or it does not match the currents grid)"""
    import currents
    clat, clon, cbox = currents.out_grid()
    land = currents.land_mask((len(clat), len(clon)))
    if land is None:
        return None
    ri = np.clip(np.floor((cbox[1] - np.asarray(lat_c)) / currents.STEP).astype(int), 0, len(clat) - 1)
    ci = np.clip(np.floor((np.asarray(lon_c) - cbox[2]) / currents.STEP).astype(int), 0, len(clon) - 1)
    return land[ri[:, None], ci[None, :]]


def resample(lat, lon, step_fields, lat_c, lon_c, land=None):
    """{(var, level): [nj, ni]} -> {part (0..2): (h m, per s, dir deg) [ny, nx]} on the window grid; NaN = nodata"""
    la, lo = np.meshgrid(lat_c, lon_c, indexing="ij")
    out = {}
    for p, lev in enumerate(PARTS):
        h, per, d = interp(lat, lon, [step_fields[(v, lev)] for v in ("SWELL", "SWPER", "SWDIR")], la, lo, angular=(2,))
        if land is not None:
            h[land] = np.nan
        out[p] = (h, per, d)
    return out


# ---------- encoding ----------
def encode_band(h, per, d):
    """height m, period s, direction deg [ny, nx] -> uint8 RGB [ny, nx, 3]; (0, 0, 255) where any is NaN"""
    ok = np.isfinite(h) & np.isfinite(per) & np.isfinite(d)
    rgb = np.zeros(np.shape(h) + (3,), dtype=np.uint8)
    rgb[..., 0] = np.where(ok, np.clip(np.floor(np.nan_to_num(h) * 10 + 0.5), 0, 255), 0)
    rgb[..., 1] = np.where(ok, np.clip(np.floor(np.nan_to_num(per) * 2 + 0.5), 0, 127), 0)
    rgb[..., 2] = np.where(ok, np.floor(np.nan_to_num(d) % 360.0 / 2 + 0.5) % 180, 255)
    return rgb


def encode(parts):
    """{0: (h, per, d), 1: ..., 2: ...} -> RGB [3 * ny, nx, 3], partition 1 on top"""
    return np.concatenate([encode_band(*parts[p]) for p in range(len(PARTS))], axis=0)


def decode_png(rgb, bands=3):
    """inverse of encode -> [(h m, per s, dir deg) per band], NaN where B is 255"""
    rgb = np.asarray(rgb)
    ny = rgb.shape[0] // bands
    out = []
    for b in range(bands):
        x = rgb[b * ny:(b + 1) * ny].astype(np.float32)
        nd = rgb[b * ny:(b + 1) * ny, :, 2] == 255
        out.append(tuple(np.where(nd, np.nan, a) for a in (x[..., 0] / 10, x[..., 1] / 2, x[..., 2] * 2)))
    return out


# ---------- point series ----------
def read_buoys(path=None):
    """-> [(id, lat, lon)] from data/buoys.js (window.BUOYS); None when the file is missing or unreadable"""
    try:
        with open(path or BUOYS, encoding="utf-8") as f:
            text = f.read()
        data = json.loads(text[text.index("{"):text.rindex("}") + 1])
    except (OSError, ValueError):
        return None
    return [(str(s["id"]), float(s["lat"]), float(s["lon"])) for s in data.get("stations", [])
            if s.get("id") is not None and s.get("lat") is not None and s.get("lon") is not None]


def sample_points(lat, lon, step_fields, plat, plon):
    """-> {"p1", "p2", "p3", "hs": [[h_ft, per_s, dir_deg] or None per point]} at one step"""
    out = {}
    for name, (fh, fp, fd) in [("p%d" % (k + 1), tuple((v, lev) for v in ("SWELL", "SWPER", "SWDIR"))) for k, lev in enumerate(PARTS)] + \
            [("hs", (("HTSGW", "surface"), ("PERPW", "surface"), ("DIRPW", "surface")))]:
        h, per, d = interp(lat, lon, [step_fields[fh], step_fields[fp], step_fields[fd]], plat, plon, angular=(2,))
        out[name] = [None if not (np.isfinite(a) and np.isfinite(b) and np.isfinite(c))
                     else [round(float(a) * M_TO_FT, 1), round(float(b), 1), int(round(float(c))) % 360]
                     for a, b, c in zip(h, per, d)]
    return out


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
def fetch_step(pool, cycle, fh):
    """-> {(var, level): message bytes} for one step: the .idx, then the 12 ranges in parallel"""
    url = url_for(cycle, fh)
    ranges = idx_ranges(get_retry(url + ".idx").decode("utf-8", "replace"))
    futs = {f: pool.submit(fetch_range, url, ranges[f]) for f in FIELDS}
    return {f: fut.result() for f, fut in futs.items()}


def build(log=print, now=None):
    """build the newest complete GFS-Wave cycle if it is not on the map yet; -> the cycle, or a short status"""
    if not region.cfg().get("coastal"):
        return None
    from PIL import Image
    t_start = time.time()
    now_dt = dt.datetime.fromtimestamp(now or t_start, dt.timezone.utc)
    store = load_store()
    old = store.get("cycle") or "nothing"
    try:
        cyc = latest_cycle(now_dt)
    except Exception as e:  # noqa: BLE001  (a failing host must not stop the hourly job)
        log("swell: could not look for a GFS-Wave cycle (%r); keeping %s" % (e, old))
        return "failed"
    if cyc is None:
        log("swell: no GFS-Wave cycle with f%03d posted today or yesterday; keeping %s" % (STEPS[-1], old))
        return "no cycle"
    cycle = cycle_id(cyc)
    if store.get("cycle") == cycle:
        log("swell: unchanged %s" % cycle)
        return cycle

    lat_c, lon_c, bbox = out_grid()
    land = land_mask(lat_c, lon_c)
    buoys = read_buoys()
    if not buoys:
        log("swell: no stations in %s; writing no point series" % BUOYS)
        buoys = []
    plat, plon = np.array([b[1] for b in buoys]), np.array([b[2] for b in buoys])
    series = {b[0]: {"t0": int(cyc.timestamp()), "dt": DT, "p1": [], "p2": [], "p3": [], "hs": []} for b in buoys}
    tmp, final = os.path.join(FRAME_DIR, cycle + ".tmp"), os.path.join(FRAME_DIR, cycle)
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    hours, fh = [], STEPS[0]
    try:
        with cf.ThreadPoolExecutor(WORKERS) as pool:
            for n, fh in enumerate(STEPS):
                want_t = int(cyc.timestamp()) + 3600 * fh
                fields, grid = {}, None
                for f, msg in fetch_step(pool, cyc, fh).items():
                    lat, lon, v, t = decode(msg, f)
                    if t != want_t:
                        raise ValueError("f%03d %s:%s valid at %d, expected %d" % (fh, f[0], f[1], t, want_t))
                    if grid is not None and (lat.shape, lon.shape) != grid:
                        raise ValueError("grid changed within f%03d" % fh)
                    grid, fields[f] = (lat.shape, lon.shape), v
                rgb = encode(resample(lat, lon, fields, lat_c, lon_c, land))
                Image.fromarray(rgb, "RGB").save(os.path.join(tmp, "s%02d.png" % n), "PNG", optimize=True)
                hours.append({"t": want_t, "file": "frames/swell/%s/s%02d.png" % (cycle, n)})
                if buoys:
                    got = sample_points(lat, lon, fields, plat, plon)
                    for k, b in enumerate(buoys):
                        for key in ("p1", "p2", "p3", "hs"):
                            series[b[0]][key].append(got[key][k])
    except Exception as e:  # noqa: BLE001
        shutil.rmtree(tmp, ignore_errors=True)
        log("swell: %s abandoned at f%03d (%s); keeping %s" % (cycle, fh, e, old))
        return "failed"
    shutil.rmtree(final, ignore_errors=True)
    os.replace(tmp, final)

    points = {k: s for k, s in series.items() if any(x is not None for key in ("p1", "p2", "p3", "hs") for x in s[key])}
    updated_t = int(time.time())
    meta = {"cycle": cycle, "updated": dt.datetime.now().strftime("%a %b %d %I:%M %p"), "updated_t": updated_t,
            "bbox": bbox, "nx": len(lon_c), "ny": len(lat_c), "step": STEP, "bands": len(PARTS), "hours": hours,
            "credit": CREDIT}
    _write(OUT, "window.SWELL = %s;\n" % json.dumps(meta, separators=(",", ":")))
    _write(POINTS_OUT, "window.SWELL_POINTS = %s;\n" % json.dumps({"cycle": cycle, "updated_t": updated_t, "points": points},
                                                                  separators=(",", ":")))
    _write(STORE, json.dumps({"v": 1, "cycle": cycle, "built_t": int(t_start)}))
    prune_local(cycle)
    log("swell: %s %d steps, %d s, %d buoys" % (cycle, len(hours), time.time() - t_start, len(points)))
    return cycle


if __name__ == "__main__":
    build()
