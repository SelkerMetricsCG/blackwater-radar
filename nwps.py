"""
Nearshore swell: NOAA NWPS (Nearshore Wave Prediction System) runs of the Seattle, Portland and Medford forecast
offices, for the map's swell layer (nearshore fill on top of GFS-Wave) and the "Surf beaches" layer.

In the hourly job, for regions with "coastal", whenever an office posts a newer complete run:
  frames/nwps/<cycle>/hNN.png   NN = 00..24: valid time = the newest run's hour 0 + 3 h x NN, on the currents 0.01 deg
                                window grid (currents.out_grid, north-up), RGB: R = height in 0.1 m, G = period in
                                0.5 s, B = direction (from, degrees) / 2 (0..179); nodata is (255, 255, 255).
                                Older runs are read at the step that lands on the same valid time.
  data/nwps.js                  window.NWPS = {cycle, runs: {wfo: {run, label}}, updated, updated_t, bbox, nx, ny, step,
                                hours: [{t, file}], credit}
  data/beaches.js               window.BEACHES = {cycle, updated, updated_t, spots: [{name, lat, lon, facing, sample,
                                wfo, series: {t0, dt, p: [[h_ft, per_s, dir_deg] | null, ...]} | null}]}
  data/nwps_wave_cache.json     private (cloud.py STATE_FILES): the cycle on the map and its runs. Not nwps_cache.json:
                                rivers.py already uses that name for the river-forecast NWPS (water.noaa.gov).
<cycle> is "nwps_sew_tHHz_YYYYMMDD-pqr_tHHz_YYYYMMDD-mfr_tHHz_YYYYMMDD" (offices without a run in two days are left
out), so a cycle's files never change.

What the files hold (checked 2026-10-15 with eccodes): one GRIB2 per office, run and grid, 145 hourly steps (0..144) of
swh, shts (total swell height), perpw, dirpw, ws, wdir, dirc, spc, zos at the surface; no partitioned swell. So the
"primary swell" is shts with the peak period perpw and peak direction dirpw (spec section 2's fallback). They are
fetched through the NOMADS filter CGI (those three fields only, about 40 % of the file), the whole file as fallback.

Grids: CG1 is each office's ~4 km outer grid; pqr and mfr CG2..CG4 are 0.4-0.7 km nests. sew CG2 and pqr/mfr CG5 are
~5 km copies of the CG1 domain whose heights run about a quarter of CG1's (median ratio 0.23-0.26 on 2026-10-15), a
different product, so they are not used. Finer grids win over coarser ones; CG1 fills where no nest covers (the whole
Washington coast, where sew has no nest). The currents land mask then blanks land cells.
Design: docs/superpowers/specs/2026-10-15-swell-forecast-design.md.

Run standalone (writes local files, uploads nothing):  python nwps.py
"""
import datetime as dt
import json
import math
import os
import re
import shutil
import time
import urllib.error
import urllib.request

import numpy as np

import currents
import region

BASE = "https://nomads.ncep.noaa.gov/pub/data/nccf/com/nwps/prod/"
FILTER = ("https://nomads.ncep.noaa.gov/cgi-bin/filter_wrnwps.pl?file=%s&var_SWELL=on&var_PERPW=on&var_DIRPW=on"
          "&lev_surface=on&dir=%%2Fwr.%s%%2F%s%%2F%s%%2F%s")
UA = "RadarTracker/1.0 (personal weather map)"
TIMEOUT = 20                  # listings; also the connect timeout of downloads
READ_TIMEOUT = 120            # downloads: per socket read (the filter CGI can think before the first byte)
TRIES = 2
RETRY_PAUSE = 5.0
OFFICES = ("sew", "pqr", "mfr")                     # north to south
GRIDS = {"sew": ("CG1",), "pqr": ("CG1", "CG2", "CG3", "CG4"), "mfr": ("CG1", "CG2", "CG3", "CG4")}
FIELDS = ("shts", "perpw", "dirpw")                 # height m, period s, direction (from) deg
N_HOURS = 25                  # 0..72 h, 3-hourly (spec decision 2)
DT = 10800
MAX_STEP = 144
MAX_AGE_H = 48               # an office whose newest complete run is older than the newest office's by more is left out
SAMPLE_M, SAMPLE_STEP_M = 3000, 100                 # beach sample search (spec decision 6)
FT = 3.28084
CREDIT = "NOAA NWPS (Seattle, Portland, Medford offices)"
STEP = currents.STEP

DATA = region.data_dir()
OUT = os.path.join(DATA, "nwps.js")
OUT_BEACHES = os.path.join(DATA, "beaches.js")
STORE = os.path.join(DATA, "nwps_wave_cache.json")
FRAME_DIR = os.path.join(region.frames_dir(), "nwps")
SPOTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "surf_spots.json")


# ---------- NOMADS ----------
def _get(url, timeout):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        try:
            r.fp.raw._sock.settimeout(timeout)          # connect with TIMEOUT, read with `timeout`
        except AttributeError:
            pass
        return r.read()


def _retry(fn):
    err = None
    for k in range(TRIES):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            err = e
            if isinstance(e, urllib.error.HTTPError) and e.code == 404:
                raise
            if k < TRIES - 1:
                time.sleep(RETRY_PAUSE)
    raise err


def fetch_text(url):
    """directory listing HTML; '' when the folder does not exist (404)"""
    try:
        return _retry(lambda: _get(url, TIMEOUT)).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return ""
        raise


def fetch_grib(wfo, cg, run):
    """GRIB2 bytes of one office/run/grid: the filter CGI subset, else the whole file"""
    name, d, hh = grib_name(wfo, cg, run), run.strftime("%Y%m%d"), run.strftime("%H")
    err = None
    for url in (FILTER % (name, d, wfo, hh, cg), "%swr.%s/%s/%s/%s/%s" % (BASE, d, wfo, hh, cg, name)):
        try:
            b = _retry(lambda: _get(url, READ_TIMEOUT))
            if b[:4] == b"GRIB":
                return b
            err = ValueError("not GRIB (%d bytes)" % len(b))
        except Exception as e:  # noqa: BLE001
            err = e
    raise RuntimeError("%s: %r" % (name, err))


def list_names(html):
    """relative link targets of an Apache listing ("00/", "CG2/", "x.grib2"); the parent link is absolute and dropped"""
    return [n for n in re.findall(r'<a href="([^"]+)"', html) if not n.startswith(("/", "?", "http"))]


def run_hours(names):
    return sorted(int(n[:2]) for n in names if re.fullmatch(r"\d\d/", n))


def grid_dirs(names):
    """nest discovery: the CGn folders of a run listing"""
    return sorted(n[:-1] for n in names if re.fullmatch(r"CG\d/", n))


def grib_name(wfo, cg, run):
    return "%s_nwps_%s_%s_%s00.grib2" % (wfo, cg, run.strftime("%Y%m%d"), run.strftime("%H"))


def find_run(wfo, now, cached=None, get=None):
    """newest run (aware UTC datetime) of `wfo` in today's or yesterday's (UTC) listing whose GRIDS files are all
    listed; a run not newer than `cached` (the run on the map, complete when built) is returned without checking; None"""
    get = get or fetch_text
    for back in (0, 1):
        day = (now - dt.timedelta(days=back)).replace(hour=0, minute=0, second=0, microsecond=0)
        d = day.strftime("%Y%m%d")
        for hh in reversed(run_hours(list_names(get("%swr.%s/%s/" % (BASE, d, wfo))))):
            run = day.replace(hour=hh)
            if cached is not None and run <= cached:
                return cached
            rdir = "%swr.%s/%s/%02d/" % (BASE, d, wfo, hh)
            if not set(GRIDS[wfo]) <= set(grid_dirs(list_names(get(rdir)))):
                continue
            if all(grib_name(wfo, cg, run) in list_names(get(rdir + cg + "/")) for cg in GRIDS[wfo]):
                return run
    return cached


# ---------- GRIB ----------
def split_messages(b):
    """GRIB2 bytes -> [message bytes] (section 0: 'GRIB', 2 reserved, discipline, edition 2, 8-byte total length)"""
    out, i = [], 0
    while True:
        i = b.find(b"GRIB", i)
        if i < 0 or i + 16 > len(b):
            return out
        n = int.from_bytes(b[i + 8:i + 16], "big")
        out.append(b[i:i + n])
        i += n


def read_grib(b, steps):
    """GRIB2 bytes -> {"lat", "lon" (1-D ascending, lon in -180..180), "cell" (deg^2), "f": {step: (h, per, dir)}}
    for every step in `steps` (float32 [nlat, nlon], NaN nodata); raises when a field or step is missing"""
    import eccodes
    steps, got, grid = set(steps), {}, None
    for msg in split_messages(b):
        h = eccodes.codes_new_from_message(msg)
        try:
            name, step = eccodes.codes_get(h, "shortName"), int(eccodes.codes_get(h, "step"))
            if name not in FIELDS or step not in steps:
                continue
            if grid is None:
                g = {k: eccodes.codes_get(h, k) for k in ("gridType", "Ni", "Nj", "iScansNegatively", "jScansPositively",
                     "jPointsAreConsecutive", "latitudeOfFirstGridPointInDegrees", "latitudeOfLastGridPointInDegrees",
                     "longitudeOfFirstGridPointInDegrees", "longitudeOfLastGridPointInDegrees")}
                if g["gridType"] != "regular_ll" or g["iScansNegatively"] or g["jPointsAreConsecutive"]:
                    raise ValueError("unexpected grid %r" % g)
                lat = np.linspace(g["latitudeOfFirstGridPointInDegrees"], g["latitudeOfLastGridPointInDegrees"], g["Nj"])
                lon = np.linspace(g["longitudeOfFirstGridPointInDegrees"], g["longitudeOfLastGridPointInDegrees"], g["Ni"])
                lon = np.where(lon > 180, lon - 360, lon)
                grid = (lat, lon, g["Nj"], g["Ni"], not g["jScansPositively"])
            v = np.asarray(eccodes.codes_get_values(h), dtype=np.float64).reshape(grid[2], grid[3])
            if eccodes.codes_get(h, "bitmapPresent"):
                v[v == eccodes.codes_get(h, "missingValue")] = np.nan
            got[(name, step)] = v.astype(np.float32)
        finally:
            eccodes.codes_release(h)
    missing = [(n, s) for s in sorted(steps) for n in FIELDS if (n, s) not in got]
    if grid is None or missing:
        raise ValueError("missing fields %s" % missing[:4])
    lat, lon, _, _, flip = grid
    f = {s: tuple(got[(n, s)] for n in FIELDS) for s in steps}
    if flip:
        lat, f = lat[::-1], {s: tuple(a[::-1] for a in v) for s, v in f.items()}
    cell = abs(lat[-1] - lat[0]) / max(len(lat) - 1, 1) * abs(lon[-1] - lon[0]) / max(len(lon) - 1, 1)
    return {"lat": lat, "lon": lon, "cell": cell, "f": f}


# ---------- compositing, encoding ----------
def composite(layers, lat_c, lon_c):
    """[(lat, lon, (h, per, dir)), ...] in rising precedence -> (h, per, dir) on the window grid, NaN where no layer
    has a value; each layer is sampled at its nearest cell and overrides earlier ones where it is finite"""
    out = [np.full((len(lat_c), len(lon_c)), np.nan, dtype=np.float32) for _ in range(3)]
    for lat, lon, fields in layers:
        ri, ci = currents.nearest(lat, lat_c), currents.nearest(lon, lon_c)
        inside = (ri >= 0)[:, None] & (ci >= 0)[None, :]
        s = [np.asarray(a)[np.maximum(ri, 0)[:, None], np.maximum(ci, 0)[None, :]] for a in fields]
        ok = inside & np.isfinite(s[0]) & np.isfinite(s[1]) & np.isfinite(s[2])
        for o, x in zip(out, s):
            o[ok] = x[ok]
    return tuple(out)


def encode(h, per, d):
    """-> uint8 RGB: R = h / 0.1 m, G = per / 0.5 s (capped at 255), B = dir / 2 (0..179); (255, 255, 255) nodata"""
    ok = np.isfinite(h) & np.isfinite(per) & np.isfinite(d)
    rgb = np.full(np.shape(h) + (3,), 255, dtype=np.uint8)
    rgb[..., 0] = np.where(ok, np.clip(np.floor(np.nan_to_num(h) * 10 + 0.5), 0, 255), 255)
    rgb[..., 1] = np.where(ok, np.clip(np.floor(np.nan_to_num(per) * 2 + 0.5), 0, 255), 255)
    rgb[..., 2] = np.where(ok, np.floor(np.mod(np.nan_to_num(d), 360) / 2 + 0.5) % 180, 255)
    return rgb


def decode(rgb):
    """inverse of encode -> (h m, per s, dir deg), NaN where B is 255"""
    rgb = np.asarray(rgb).astype(np.float32)
    ok = rgb[..., 2] < 255
    return tuple(np.where(ok, rgb[..., k] * s, np.nan) for k, s in ((0, 0.1), (1, 0.5), (2, 2.0)))


# ---------- beaches ----------
def sample_cell(lat, lon, water, spot_lat, spot_lon, facing):
    """(row, col) of the first water cell of a grid met walking from the spot along its facing bearing in
    SAMPLE_STEP_M steps out to SAMPLE_M; None when there is none or the spot is off the grid"""
    k = math.radians(facing)
    for d in range(0, SAMPLE_M + 1, SAMPLE_STEP_M):
        la = spot_lat + d * math.cos(k) / 111320.0
        lo = spot_lon + d * math.sin(k) / (111320.0 * math.cos(math.radians(spot_lat)))
        r, c = int(currents.nearest(lat, [la])[0]), int(currents.nearest(lon, [lo])[0])
        if r >= 0 and c >= 0 and water[r, c]:
            return r, c
    return None


def load_spots(log):
    try:
        with open(SPOTS, encoding="utf-8") as f:
            s = json.load(f)
    except OSError:
        log("nwps: no %s; writing an empty beach list" % os.path.basename(SPOTS))
        return []
    s = s.get("spots", []) if isinstance(s, dict) else s
    return [x for x in s if isinstance(x, dict) and {"name", "lat", "lon", "facing"} <= set(x)]


def beach_series(spots, grids, runs, t0):
    """spots + {(wfo, cg): read_grib result} + {wfo: run epoch} -> spot rows for data/beaches.js"""
    out = []
    for sp in spots:
        lat0, lon0, fac = float(sp["lat"]), float(sp["lon"]), float(sp["facing"])
        row = {"name": sp["name"], "lat": lat0, "lon": lon0, "facing": fac, "sample": None, "wfo": None, "series": None}
        for k in ("state", "swell", "tide", "level", "hazards", "source"):      # the spot's notes, shown in its popup
            if sp.get(k):
                row[k] = sp[k]
        cover = [(g["cell"], key) for key, g in grids.items()
                 if currents.nearest(g["lat"], [lat0])[0] >= 0 and currents.nearest(g["lon"], [lon0])[0] >= 0]
        if cover:
            key = min(cover)[1]
            g, wfo = grids[key], key[0]
            steps = [(t0 + DT * n - runs[wfo]) // 3600 for n in range(N_HOURS)]
            rc = sample_cell(g["lat"], g["lon"], np.isfinite(g["f"][steps[0]][0]), lat0, lon0, fac)
            row["wfo"] = wfo
            if rc:
                r, c = rc
                p = []
                for s in steps:
                    v = [float(a[r, c]) for a in g["f"][s]] if s in g["f"] else [np.nan]
                    p.append([round(v[0] * FT, 1), round(v[1], 1), int(round(v[2])) % 360] if np.all(np.isfinite(v)) else None)
                row["sample"] = [round(float(g["lat"][r]), 4), round(float(g["lon"][c]), 4)]
                row["series"] = {"t0": t0, "dt": DT, "p": p}
        out.append(row)
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


def cycle_id(runs):
    """{wfo: aware datetime} -> "nwps_sew_t12z_20261015-pqr_t18z_20261015-..." in OFFICES order"""
    return "nwps_" + "-".join("%s_t%s" % (w, runs[w].strftime("%Hz_%Y%m%d")) for w in OFFICES if w in runs)


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
    """build the newest complete NWPS runs if they are not on the map yet; -> the cycle, or a short status"""
    if not region.cfg().get("coastal"):
        return None
    from PIL import Image
    t_start = time.time()
    now_dt = dt.datetime.fromtimestamp(now or t_start, dt.timezone.utc)
    store = load_store()
    old = store.get("cycle") or "nothing"
    cached = {w: dt.datetime.fromtimestamp(t, dt.timezone.utc) for w, t in (store.get("runs") or {}).items()}
    try:
        runs = {w: find_run(w, now_dt, cached.get(w)) for w in OFFICES}
    except Exception as e:  # noqa: BLE001  (a failing host must not stop the hourly job)
        log("nwps: could not read the NOMADS listings (%r); keeping %s" % (e, old))
        return "failed"
    newest = max([r for r in runs.values() if r is not None], default=None)
    runs = {w: r for w, r in runs.items() if r is not None and newest - r <= dt.timedelta(hours=MAX_AGE_H)}
    if not runs:
        log("nwps: no complete run listed today or yesterday; keeping %s" % old)
        return "no run"
    cycle = cycle_id(runs)
    if store.get("cycle") == cycle:
        log("nwps: unchanged %s" % cycle)
        return cycle

    rt = {w: int(r.timestamp()) for w, r in runs.items()}
    t0 = max(rt.values())
    times = [t0 + DT * n for n in range(N_HOURS)]
    grids = {}
    try:
        for w in OFFICES:
            if w not in runs:
                log("nwps: %s has no complete run today or yesterday; left out" % w)
                continue
            steps = [(t - rt[w]) // 3600 for t in times if (t - rt[w]) // 3600 <= MAX_STEP]
            for cg in GRIDS[w]:
                grids[(w, cg)] = read_grib(fetch_grib(w, cg, runs[w]), steps)
    except Exception as e:  # noqa: BLE001
        log("nwps: %s abandoned (%r); keeping %s" % (cycle, e, old))
        return "failed"

    lat_c, lon_c, bbox = currents.out_grid()
    land = currents.land_mask((len(lat_c), len(lon_c)))
    if land is None:
        log("nwps: no land mask for %s; coarse cells may overlap the shore" % region.KEY)
    order = sorted(grids, key=lambda k: -grids[k]["cell"])          # coarsest first: finer grids override
    tmp, final = os.path.join(FRAME_DIR, cycle + ".tmp"), os.path.join(FRAME_DIR, cycle)
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    hours = []
    try:
        for n, t in enumerate(times):
            layers = []
            for k in order:
                s = (t - rt[k[0]]) // 3600
                if s in grids[k]["f"]:
                    layers.append((grids[k]["lat"], grids[k]["lon"], grids[k]["f"][s]))
            h, per, d = composite(layers, lat_c, lon_c)
            if land is not None:
                h[land] = np.nan
            Image.fromarray(encode(h, per, d), "RGB").save(os.path.join(tmp, "h%02d.png" % n), "PNG", optimize=True)
            hours.append({"t": t, "file": "frames/nwps/%s/h%02d.png" % (cycle, n)})
        spots = beach_series(load_spots(log), grids, rt, t0)
    except Exception as e:  # noqa: BLE001
        shutil.rmtree(tmp, ignore_errors=True)
        log("nwps: %s abandoned while compositing (%r); keeping %s" % (cycle, e, old))
        return "failed"
    shutil.rmtree(final, ignore_errors=True)
    os.replace(tmp, final)

    upd, upd_t = dt.datetime.now().strftime("%a %b %d %I:%M %p"), int(time.time())
    meta = {"cycle": cycle, "runs": {w: {"run": rt[w], "label": runs[w].strftime("%HZ %Y-%m-%d")} for w in OFFICES if w in runs},
            "updated": upd, "updated_t": upd_t, "bbox": bbox, "nx": len(lon_c), "ny": len(lat_c), "step": STEP,
            "hours": hours, "credit": CREDIT}
    currents._write(OUT, "window.NWPS = %s;\n" % json.dumps(meta, separators=(",", ":")))
    beaches = {"cycle": cycle, "updated": upd, "updated_t": upd_t, "spots": spots}
    currents._write(OUT_BEACHES, "window.BEACHES = %s;\n" % json.dumps(beaches, separators=(",", ":")))
    currents._write(STORE, json.dumps({"v": 1, "cycle": cycle, "runs": rt, "built_t": int(t_start)}))
    prune_local(cycle)
    log("nwps: %s %d hours, %d nests, %d beaches with a series, %d s"
        % (cycle, len(hours), len(grids), sum(1 for s in spots if s["series"]), time.time() - t_start))
    return cycle


if __name__ == "__main__":
    build()
