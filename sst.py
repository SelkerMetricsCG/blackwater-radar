"""
Sea surface temperature: NOAA Geo-Polar Blended SST, 5 km daily, gap-free (CoastWatch ERDDAP).

Reads the dataset's .das for the newest analysis day (time_coverage_end), and when it is newer than the date in
data/sst.js downloads the CSV subset for the map window, turns it into a north-up grid, resamples it to the window's
pixel space (nearest neighbour), and writes frames/sst/sst.webp, data/values/sst.js (click-anywhere, F) and
data/sst.js -> window.SST = {date, file, min_f, max_f, legend, updated, updated_t}. Land and cloud are transparent.

Runs only for regions with "coastal". Run standalone:  python sst.py
"""
import datetime as dt
import json
import os
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
import warnings

import numpy as np
from PIL import Image

import region
import values

ERDDAP = "https://coastwatch.noaa.gov/erddap/griddap/"
DATASET = "noaacwBLENDEDsstDaily"      # night-only analysis, 2002-present, analysed_sst in kelvin; the day+night
                                        # sibling noaacwBLENDEDsstDNDaily (degree_C) posts a day later
UA = "RadarTracker/1.0 (personal weather map)"
TIMEOUT = 20
TRIES = 2
T = 256
FRAME_DIR = os.path.join(region.frames_dir(), "sst")
OUT = os.path.join(region.data_dir(), "sst.js")


def _ramp(n):
    """n muted colours from blue through sand to red"""
    stops = [(0.0, (62, 84, 130)), (0.25, (98, 137, 170)), (0.45, (160, 185, 196)), (0.55, (205, 200, 180)),
             (0.75, (205, 150, 115)), (1.0, (160, 75, 70))]
    out = []
    for i in range(n):
        t = i / (n - 1)
        for (t0, c0), (t1, c1) in zip(stops, stops[1:]):
            if t0 <= t <= t1:
                f = (t - t0) / (t1 - t0)
                out.append(tuple(int(round(a + (b - a) * f)) for a, b in zip(c0, c1)))
                break
    return out


SST_BINS = list(zip(range(40, 70, 2), _ramp(15)))      # (min F, colour); 40-70 F in 2 F steps (spec section 6 row 8)
_down = set()                                           # hosts that timed out in this run


class HostDown(Exception):
    """an earlier request to this host timed out or failed to connect in this run"""


def fetch(url):
    host = urllib.parse.urlsplit(url).netloc
    if host in _down:
        raise HostDown(url)
    err = None
    for _ in range(TRIES):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                return r.read().decode("utf-8")
        except urllib.error.HTTPError:
            raise
        except (OSError, socket.timeout) as e:     # URLError, timeouts, refused connections
            err = e
    _down.add(host)
    raise err


def latest_date():
    """'YYYY-MM-DD' of the newest analysis on the server, from the .das time_coverage_end"""
    m = re.search(r'time_coverage_end "(\d{4}-\d\d-\d\d)T', fetch(ERDDAP + DATASET + ".das"))
    if not m:
        raise ValueError("no time_coverage_end in %s.das" % DATASET)
    return m.group(1)


def have_date():
    try:
        with open(OUT, encoding="utf-8") as f:
            s = f.read()
        return json.loads(s[s.index("{"):s.rindex("}") + 1]).get("date")
    except (OSError, ValueError):
        return None


def csv_url(day):
    lat0, lat1, lon0, lon1 = region.bbox()
    return (ERDDAP + DATASET + ".csv?analysed_sst[(%sT12:00:00Z)][(%.2f):(%.2f)][(%.2f):(%.2f)]"
            % (day, lat0, lat1, lon0, lon1))


def parse_csv(text):
    """ERDDAP griddap CSV (names row, units row, then time,lat,lon,value) -> (lats N->S, lons W->E, grid_c) with
    grid_c a north-up (nlat, nlon) float32 array in degrees C, NaN for land and cloud; either latitude order in"""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    names = lines[0].split(",")
    units = lines[1].split(",")
    iv = len(names) - 1
    kelvin = units[iv].strip().lower() in ("kelvin", "k")
    rows = [ln.split(",") for ln in lines[2:]]
    la = np.array([float(r[1]) for r in rows])
    lo = np.array([float(r[2]) for r in rows])
    v = np.array([float(r[iv]) if r[iv] not in ("NaN", "") else np.nan for r in rows], dtype=np.float64)
    lats = np.unique(la)[::-1]
    lons = np.unique(lo)
    g = np.full((len(lats), len(lons)), np.nan, np.float32)
    iy = np.searchsorted(-lats, -la)
    ix = np.searchsorted(lons, lo)
    g[iy, ix] = v - 273.15 if kelvin else v
    return lats.astype(np.float32), lons.astype(np.float32), g


def to_window(lats, lons, grid_c):
    """nearest-neighbour lookup of the lat/lon grid at every pixel centre of the map window -> (H, W) float32, F;
    NaN outside the grid. Works for either latitude order."""
    z, x0, x1, y0, y1 = region.window()
    n = 2 ** z
    ys = (np.arange((y1 - y0 + 1) * T) + 0.5) / T + y0
    xs = (np.arange((x1 - x0 + 1) * T) + 0.5) / T + x0
    lat_w = np.degrees(np.arctan(np.sinh(np.pi - 2 * np.pi * ys / n)))
    lon_w = xs / n * 360.0 - 180.0
    lats = np.asarray(lats, np.float64)
    lons = np.asarray(lons, np.float64)
    iy = np.round((lat_w - lats[0]) / (lats[1] - lats[0])).astype(int)
    ix = np.round((lon_w - lons[0]) / (lons[1] - lons[0])).astype(int)
    oky, okx = (iy >= 0) & (iy < len(lats)), (ix >= 0) & (ix < len(lons))
    g = np.asarray(grid_c, np.float32)[np.ix_(np.clip(iy, 0, len(lats) - 1), np.clip(ix, 0, len(lons) - 1))]
    g = g * np.float32(9 / 5) + np.float32(32)
    g[~oky, :] = np.nan
    g[:, ~okx] = np.nan
    return g


def colorize(arr_f):
    """RGBA image: each value gets the colour of the highest bin it reaches (below 40 F: the first); NaN transparent"""
    a = np.asarray(arr_f, np.float32)
    ok = ~np.isnan(a)
    x = np.where(ok, a, -1e9)
    rgb = np.empty(a.shape + (3,), np.uint8)
    rgb[:] = SST_BINS[0][1]
    for lo, color in SST_BINS[1:]:
        rgb[x >= lo] = color
    alpha = np.where(ok, 200, 0).astype(np.uint8)
    return Image.fromarray(np.dstack([rgb, alpha]), "RGBA")


def legend():
    return [{"min": lo, "color": "#%02x%02x%02x" % c} for lo, c in SST_BINS]


def _write(path, text):
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(path + ".tmp", path)


def build(log=print):
    """-> the analysis date written, or None when the region is not coastal or nothing is new"""
    if not region.cfg().get("coastal"):
        return None
    day = latest_date()
    if have_date() == day:
        log("sst: unchanged %s" % day)
        return None
    lats, lons, g = parse_csv(fetch(csv_url(day)))
    arr = to_window(lats, lons, g)
    os.makedirs(FRAME_DIR, exist_ok=True)
    tmp = os.path.join(FRAME_DIR, "sst.tmp.webp")
    colorize(arr).save(tmp, "WEBP", lossless=True)
    os.replace(tmp, os.path.join(FRAME_DIR, "sst.webp"))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)      # all-land 5x5 blocks: mean of empty slice -> nodata
        values.write_grid("sst", arr, unit="F", scale=0.1)
    lo, hi = round(float(np.nanmin(arr)), 1), round(float(np.nanmax(arr)), 1)
    meta = {"date": day, "file": "frames/sst/sst.webp?v=%d" % int(time.time()), "min_f": lo, "max_f": hi,
            "legend": legend(), "updated": dt.datetime.now().strftime("%a %b %d %I:%M %p"), "updated_t": int(time.time())}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    _write(OUT, "window.SST = %s;\n" % json.dumps(meta, separators=(",", ":")))
    log("sst: analysis %s (%d cells, %.1f-%.1f F)" % (day, int((~np.isnan(g)).sum()), lo, hi))
    return day


if __name__ == "__main__":
    t0 = time.time()
    build()
    print("done in %.0fs" % (time.time() - t0))
