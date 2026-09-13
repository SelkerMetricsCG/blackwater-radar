"""
NWS forecast overlays (NDFD, Pacific Northwest grid, 2.5 km):
  rain and snow totals for the next 24 and 48 hours, peak wind gust in the next
  24 hours, today's high and tonight's low.

Downloads the NDFD GRIB2 files from tgftp.nws.noaa.gov, decodes with cfgrib,
re-samples onto the map window by nearest neighbour, and writes
frames/forecast/<key>.webp, data/values/fc_<key>.js and data/forecast.js.

Run standalone:  python forecast.py
"""
import datetime as dt
import json
import os
import time
import urllib.request
import warnings

import numpy as np
from PIL import Image
from scipy.spatial import cKDTree

warnings.filterwarnings("ignore")

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data")
OUT_DIR = os.path.join(ROOT, "frames", "forecast")
TMP = os.path.join(OUT_DIR, "_grib")
OUT = os.path.join(DATA, "forecast.js")
UA = "RadarTracker/1.0 (personal weather map; chris.gabrielli@gmail.com)"
BASE_URL = "https://tgftp.nws.noaa.gov/SL.us008001/ST.opnl/DF.gr2/DC.ndfd/AR.pacnwest/VP.001-003/"

Z, X0, X1, Y0, Y1, T = 7, 19, 23, 42, 46, 256
W = (X1 - X0 + 1) * T
H = (Y1 - Y0 + 1) * T
STEP = 2

from interp import RAIN_BINS, SNOW_BINS  # noqa: E402
import values  # noqa: E402

GUST_BINS = [(20, (255, 255, 178)), (30, (254, 217, 118)), (40, (254, 178, 76)), (50, (253, 141, 60)), (60, (240, 59, 32)), (75, (189, 0, 38))]
TEMP_BINS = [(-20, (49, 54, 149)), (0, (69, 117, 180)), (10, (116, 173, 209)), (20, (171, 217, 233)), (32, (224, 243, 248)),
             (40, (255, 255, 191)), (50, (254, 224, 144)), (60, (253, 174, 97)), (70, (244, 109, 67)), (80, (215, 48, 39)), (90, (165, 0, 38)), (100, (110, 0, 30))]


def fetch(url, dest):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120) as r, open(dest, "wb") as f:
        f.write(r.read())


def grid_latlon():
    n = 2 ** Z
    ys = (np.arange(0, H, STEP) + STEP / 2) / T + Y0
    xs = (np.arange(0, W, STEP) + STEP / 2) / T + X0
    lon = xs / n * 360.0 - 180.0
    lat = np.degrees(np.arctan(np.sinh(np.pi - 2 * np.pi * ys / n)))
    return np.meshgrid(lat, lon, indexing="ij")


_tree_cache = {}


def resample(field, lat2d, lon2d):
    key = lat2d.shape
    if key not in _tree_cache:
        src_lat = lat2d.ravel()
        src_lon = np.where(lon2d.ravel() > 180, lon2d.ravel() - 360, lon2d.ravel())
        k = np.cos(np.radians(47.0))
        tree = cKDTree(np.column_stack([src_lat, src_lon * k]))
        glat, glon = grid_latlon()
        d, idx = tree.query(np.column_stack([glat.ravel(), glon.ravel() * k]), k=1)
        _tree_cache[key] = (idx, d > 0.06, glat.shape)
    idx, outside, shape = _tree_cache[key]
    vals = field.ravel()[idx]
    return np.where(outside, np.nan, vals).reshape(shape)


def colorize(grid, bins, alpha=175):
    v = grid
    h, w = v.shape
    rgb = np.zeros((h, w, 3), np.uint8)
    a = np.zeros((h, w), np.uint8)
    for lo, color in bins:
        m = np.nan_to_num(v, nan=-1e9) >= lo
        rgb[m] = color
        a[m] = alpha
    return Image.fromarray(np.dstack([rgb, a]), "RGBA").resize((w * STEP, h * STEP), Image.BILINEAR)


def open_ndfd(fn):
    import cfgrib
    path = os.path.join(TMP, fn)
    fetch(BASE_URL + fn, path)
    ds = cfgrib.open_datasets(path)[0]
    da = ds[list(ds.data_vars)[0]]
    steps = da.step.values.astype("timedelta64[h]").astype(int)
    return ds, da, steps


def save(key, grid, bins, unit, meta, extra):
    img = colorize(grid, bins)
    fn = key + ".webp"
    img.save(os.path.join(OUT_DIR, fn + ".tmp.webp"), "WEBP", quality=80, method=4)
    os.replace(os.path.join(OUT_DIR, fn + ".tmp.webp"), os.path.join(OUT_DIR, fn))
    values.write_grid("fc_" + key, np.kron(grid, np.ones((STEP, STEP))), unit=unit, scale=0.01 if unit == "in" else 0.1)
    meta["windows"][key] = dict(extra, file="frames/forecast/%s?v=%d" % (fn, int(time.time())), unit=unit,
                                max=round(float(np.nanmax(grid)), 1), min=round(float(np.nanmin(grid)), 1))


def build(log=print):
    os.makedirs(TMP, exist_ok=True)
    os.makedirs(OUT_DIR, exist_ok=True)
    meta = {"windows": {}}
    # precipitation and snow totals
    for kind, fn, bins, scale in (("qpf", "ds.qpf.bin", RAIN_BINS, 1 / 25.4), ("snow", "ds.snow.bin", SNOW_BINS, 39.37)):
        ds, da, steps = open_ndfd(fn)
        meta["issued_utc"] = np.datetime_as_string(ds.time.values, unit="m")
        for hours in (24, 48):
            sel = [i for i, s in enumerate(steps) if s <= hours]
            if not sel:
                continue
            total = np.nansum(da.values[sel], axis=0) * scale
            grid = resample(total, ds.latitude.values, ds.longitude.values)
            save("%s_%d" % (kind, hours), grid, bins, "in", meta,
                 {"kind": kind, "label": ("Rain" if kind == "qpf" else "Snow") + " next %d h" % hours,
                  "valid_to_utc": np.datetime_as_string(da.valid_time.values[sel[-1]], unit="m")})
    # peak gust next 24 h (m/s -> mph)
    ds, da, steps = open_ndfd("ds.wgust.bin")
    sel = [i for i, s in enumerate(steps) if s <= 26]
    gust = np.nanmax(da.values[sel], axis=0) * 2.23694
    save("gust_24", resample(gust, ds.latitude.values, ds.longitude.values), GUST_BINS, "mph", meta,
         {"kind": "gust", "label": "Peak gust next 24 h", "valid_to_utc": np.datetime_as_string(da.valid_time.values[sel[-1]], unit="m")})
    # today's high / tonight's low (K -> F)
    ds, da, steps = open_ndfd("ds.maxt.bin")
    hi = (da.values[0] - 273.15) * 9 / 5 + 32
    save("maxt", resample(hi, ds.latitude.values, ds.longitude.values), TEMP_BINS, "F", meta,
         {"kind": "temp", "label": "High temperature", "valid_to_utc": np.datetime_as_string(da.valid_time.values[0], unit="m")})
    ds, da, steps = open_ndfd("ds.mint.bin")
    lo = (da.values[0] - 273.15) * 9 / 5 + 32
    save("mint", resample(lo, ds.latitude.values, ds.longitude.values), TEMP_BINS, "F", meta,
         {"kind": "temp", "label": "Low temperature", "valid_to_utc": np.datetime_as_string(da.valid_time.values[0], unit="m")})
    meta["legends"] = {"gust": [{"min": lo_, "color": "#%02x%02x%02x" % c} for lo_, c in GUST_BINS],
                       "temp": [{"min": lo_, "color": "#%02x%02x%02x" % c} for lo_, c in TEMP_BINS]}
    meta["updated"] = dt.datetime.now().strftime("%a %b %d %I:%M %p")
    meta["updated_t"] = int(time.time())
    with open(OUT + ".tmp", "w", encoding="utf-8") as f:
        f.write("window.FORECAST = %s;\n" % json.dumps(meta, separators=(",", ":")))
    os.replace(OUT + ".tmp", OUT)
    log("forecast: issued %sZ, %s" % (meta.get("issued_utc"), ", ".join("%s max %.1f" % (k, v["max"]) for k, v in meta["windows"].items())))
    return meta


if __name__ == "__main__":
    t0 = time.time()
    build()
    print("done in %.0fs" % (time.time() - t0))
