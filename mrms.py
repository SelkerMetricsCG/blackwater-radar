"""
NOAA MRMS gauge-corrected precipitation (MultiSensor QPE, Pass 2; Pass 1, then radar-only, when Pass 2 is more
than STALE_H behind) as map overlays:
1, 3, 6, 12 and 24 hour totals on the 1 km CONUS grid, cut to the map window.

Writes frames/mrms/<w>h.webp, data/values/mrms_<w>.js, and data/mrms.js.
US coverage only (nothing north of the border).

Run standalone:  python mrms.py
"""
import datetime as dt
import gzip
import json
import math
import os
import time
import urllib.request
import warnings

import numpy as np
from PIL import Image

warnings.filterwarnings("ignore")

import region

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = region.data_dir()
OUT_DIR = os.path.join(region.frames_dir(), "mrms")
TMP = os.path.join(OUT_DIR, "_grib")
OUT = os.path.join(DATA, "mrms.js")
UA = "RadarTracker/1.0 (personal weather map; chris.gabrielli@gmail.com)"
WINDOWS = (1, 3, 6, 12, 24)
SOURCES = (("Pass2", "MultiSensor_QPE_%02dH_Pass2"), ("Pass1", "MultiSensor_QPE_%02dH_Pass1"), ("RadarOnly", "RadarOnly_QPE_%02dH"))
STALE_H = 2          # judgment call: Pass 2 posts about 1 h after its hour; 2 h behind means it missed an update
Z, X0, X1, Y0, Y1 = region.window()
T = 256
W = (X1 - X0 + 1) * T
H = (Y1 - Y0 + 1) * T

from interp import RAIN_BINS  # noqa: E402
import values  # noqa: E402


def fetch(url, dest):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=180) as r, open(dest, "wb") as f:
        f.write(r.read())


def window_latlon():
    n = 2 ** Z
    ys = (np.arange(H) + 0.5) / T + Y0
    xs = (np.arange(W) + 0.5) / T + X0
    lon = xs / n * 360.0 - 180.0
    lat = np.degrees(np.arctan(np.sinh(np.pi - 2 * np.pi * ys / n)))
    return lat, lon


def colorize(inches):
    v = np.nan_to_num(inches, nan=0.0)
    rgb = np.zeros(v.shape + (3,), np.uint8)
    a = np.zeros(v.shape, np.uint8)
    for lo, color in RAIN_BINS:
        m = v >= lo
        rgb[m] = color
        a[m] = 185
    return Image.fromarray(np.dstack([rgb, a]), "RGBA")


def read_grib(path, lat_w, lon_w):
    """window grid (inches, NaN outside coverage) and valid time (naive UTC) of an MRMS QPE GRIB2 file"""
    import cfgrib
    ds = cfgrib.open_datasets(path)[0]
    da = ds[list(ds.data_vars)[0]]
    lat = ds.latitude.values                       # descending, 0.01 deg
    lon = ds.longitude.values                      # 0..360
    lon = np.where(lon > 180, lon - 360, lon)
    a = da.values.astype(np.float32)
    a[a < 0] = np.nan                              # missing / no coverage
    # nearest-neighbour index lookup on the regular grid
    iy = np.clip(np.round((lat[0] - lat_w) / (lat[0] - lat[1])).astype(int), 0, len(lat) - 1)
    ix = np.clip(np.round((lon_w - lon[0]) / (lon[1] - lon[0])).astype(int), 0, len(lon) - 1)
    inside_y = (lat_w <= lat[0]) & (lat_w >= lat[-1])
    grid = a[np.ix_(iy, ix)] / 25.4                # inches
    grid[~inside_y, :] = np.nan
    valid = dt.datetime.fromisoformat(np.datetime_as_string(ds.time.values, unit="m"))
    ds.close()
    return grid, valid


def gunzip_read(gz, lat_w, lon_w):
    grib = gz[:-3]
    try:
        with gzip.open(gz, "rb") as f, open(grib, "wb") as g:
            g.write(f.read())
        return read_grib(grib, lat_w, lon_w)
    finally:
        for p in (grib, gz):
            try:
                os.remove(p)
            except OSError:
                pass


def read_latest(name, lat_w, lon_w):
    gz = os.path.join(TMP, "MRMS_%s.grib2.gz" % name)
    fetch("https://mrms.ncep.noaa.gov/2D/%s/MRMS_%s.latest.grib2.gz" % (name, name), gz)
    return gunzip_read(gz, lat_w, lon_w)


def choose(hrs, now_utc, read, log=print):
    """(label, grid, valid) for one window: Pass 2 while it is within STALE_H of now, else Pass 1, then radar-only,
    the first that is; when none is, the newest that could be read. NOAA's Pass 2 stopped for 21 h on 2026-10-09
    (19Z to 15Z) while Pass 1 and radar-only kept coming; the map and the snow archive froze on its last hour."""
    best = None
    for label, pat in SOURCES:
        name = pat % hrs
        try:
            grid, valid = read(name)
        except Exception as e:  # noqa: BLE001
            log("mrms: %s unavailable (%r)" % (name, e))
            continue
        if best is None or valid > best[2]:
            best = (label, grid, valid)
        if now_utc - valid <= dt.timedelta(hours=STALE_H):
            return label, grid, valid
        log("mrms: %s is %.1f h old" % (name, (now_utc - valid).total_seconds() / 3600.0))
    if best is None:
        raise RuntimeError("mrms: no %d h product could be read" % hrs)
    return best


def build(log=print):
    os.makedirs(TMP, exist_ok=True)
    os.makedirs(OUT_DIR, exist_ok=True)
    lat_w, lon_w = window_latlon()
    meta = {"windows": {}}
    now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    for hrs in WINDOWS:
        label, grid, valid = choose(hrs, now, lambda name: read_latest(name, lat_w, lon_w), log)
        img = colorize(grid)
        fn = "%dh.webp" % hrs
        img.save(os.path.join(OUT_DIR, fn + ".tmp.webp"), "WEBP", quality=80, method=4)
        os.replace(os.path.join(OUT_DIR, fn + ".tmp.webp"), os.path.join(OUT_DIR, fn))
        values.write_grid("mrms_%d" % hrs, grid)
        meta["windows"][str(hrs)] = {"file": "frames/mrms/%s?v=%d" % (fn, int(time.time())), "hours": hrs,
                                     "valid_utc": valid.strftime("%Y-%m-%dT%H:%M"), "source": label,
                                     "max_in": round(float(np.nanmax(grid)), 2)}
    meta["updated"] = dt.datetime.now().strftime("%a %b %d %I:%M %p")
    meta["updated_t"] = int(time.time())
    with open(OUT + ".tmp", "w", encoding="utf-8") as f:
        f.write("window.MRMS = %s;\n" % json.dumps(meta, separators=(",", ":")))
    os.replace(OUT + ".tmp", OUT)
    log("mrms: " + ", ".join("%sh max %.2f in%s" % (k, v["max_in"], "" if v["source"] == "Pass2" else " (" + v["source"] + ")")
                             for k, v in meta["windows"].items()))
    return meta


if __name__ == "__main__":
    t0 = time.time()
    build()
    print("done in %.0fs" % (time.time() - t0))
