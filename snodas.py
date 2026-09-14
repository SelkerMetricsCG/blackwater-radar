"""
SNODAS modeled snow (NOAA National Snow Analysis): daily 1 km snow depth and
snow water equivalent, which blends SNOTEL, satellite snow cover and a weather
model, so it fills the terrain between SNOTEL sites.

Downloads the daily masked-CONUS tar from NSIDC (G02158), reads products 1036
(snow depth) and 1034 (SWE), cuts to the map window, and writes
frames/snodas/depth.webp, frames/snodas/swe.webp, value grids, and data/snodas.js.
Skips the download when the latest available day is already on disk.

Run standalone:  python snodas.py
"""
import datetime as dt
import gzip
import io
import json
import os
import tarfile
import time
import urllib.request

import numpy as np
from PIL import Image

import region

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = region.data_dir()
OUT_DIR = os.path.join(region.frames_dir(), "snodas")
OUT = os.path.join(DATA, "snodas.js")
UA = "RadarTracker/1.0 (personal weather map; chris.gabrielli@gmail.com)"
Z, X0, X1, Y0, Y1 = region.window()
T = 256
W = (X1 - X0 + 1) * T
H = (Y1 - Y0 + 1) * T

import values  # noqa: E402

DEPTH_BINS = [(1, (222, 235, 247)), (6, (198, 219, 239)), (12, (158, 202, 225)), (24, (107, 174, 214)), (36, (66, 146, 198)),
              (48, (33, 113, 181)), (72, (8, 81, 156)), (96, (8, 48, 107)), (120, (74, 20, 134)), (180, (140, 20, 120))]
SWE_BINS = [(0.5, (222, 235, 247)), (1, (198, 219, 239)), (2, (158, 202, 225)), (4, (107, 174, 214)), (8, (66, 146, 198)),
            (12, (33, 113, 181)), (16, (8, 81, 156)), (24, (8, 48, 107)), (32, (74, 20, 134)), (48, (140, 20, 120))]


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=300) as r:
        return r.read()


def latest_available():
    """try today then back a few days; return (date, tar bytes)"""
    today = dt.date.today()
    for back in range(0, 5):
        d = today - dt.timedelta(days=back)
        url = "https://noaadata.apps.nsidc.org/NOAA/G02158/masked/%s/SNODAS_%s.tar" % (d.strftime("%Y/%m_%b"), d.strftime("%Y%m%d"))
        try:
            return d, fetch(url)
        except Exception:  # noqa: BLE001
            continue
    raise RuntimeError("no recent SNODAS file")


def read_product(tar, code, mask_mm=10000):
    names = tar.getnames()
    hdr = gzip.decompress(tar.extractfile([n for n in names if code in n and n.endswith(".txt.gz")][0]).read()).decode("utf-8", "ignore")
    keys = dict((k.strip(), v.strip()) for k, v in (line.split(":", 1) for line in hdr.splitlines() if ":" in line))
    rows, cols = int(keys["Number of rows"]), int(keys["Number of columns"])
    x0, y1 = float(keys["Minimum x-axis coordinate"]), float(keys["Maximum y-axis coordinate"])
    res = float(keys["X-axis resolution"])
    raw = gzip.decompress(tar.extractfile([n for n in names if code in n and n.endswith(".dat.gz")][0]).read())
    a = np.frombuffer(raw, dtype=">i2").reshape(rows, cols).astype(np.float32)
    a[(a < 0) | (a >= mask_mm)] = np.nan      # negative = missing; very deep cells are glacier ice, not seasonal snow
    return a / 1000.0 * 39.3701, (x0, y1, res)      # inches


def window_grid(a, geo):
    x0, y1, res = geo
    n = 2 ** Z
    ys = (np.arange(H) + 0.5) / T + Y0
    xs = (np.arange(W) + 0.5) / T + X0
    lon = xs / n * 360.0 - 180.0
    lat = np.degrees(np.arctan(np.sinh(np.pi - 2 * np.pi * ys / n)))
    ix = np.round((lon - x0) / res - 0.5).astype(int)
    iy = np.round((y1 - lat) / res - 0.5).astype(int)
    okx = (ix >= 0) & (ix < a.shape[1])
    oky = (iy >= 0) & (iy < a.shape[0])
    g = np.full((H, W), np.nan, np.float32)
    sub = a[np.ix_(np.clip(iy, 0, a.shape[0] - 1), np.clip(ix, 0, a.shape[1] - 1))]
    g[np.ix_(oky, okx)] = sub[np.ix_(oky, okx)]
    return g


def colorize(v, bins):
    x = np.nan_to_num(v, nan=0.0)
    rgb = np.zeros(x.shape + (3,), np.uint8)
    a = np.zeros(x.shape, np.uint8)
    for lo, color in bins:
        m = x >= lo
        rgb[m] = color
        a[m] = 200
    return Image.fromarray(np.dstack([rgb, a]), "RGBA")


def build(log=print):
    os.makedirs(OUT_DIR, exist_ok=True)
    have = None
    try:
        with open(OUT, encoding="utf-8") as f:
            s = f.read()
        have = json.loads(s[s.index("{"):s.rindex("}") + 1]).get("date")
    except (OSError, ValueError):
        pass
    d, blob = latest_available()
    if have == d.isoformat():
        log("snodas: %s already current" % have)
        return have
    tar = tarfile.open(fileobj=io.BytesIO(blob))
    meta = {"date": d.isoformat(), "layers": {}}
    mask_mm = 3000 if 7 <= d.month <= 11 else 10000     # Jul-Nov nothing seasonal is 3 m deep; winter allows 10 m
    for key, code, bins in (("depth", "1036", DEPTH_BINS), ("swe", "1034", SWE_BINS)):
        a, geo = read_product(tar, code, mask_mm)
        g = window_grid(a, geo)
        img = colorize(g, bins)
        fn = key + ".webp"
        img.save(os.path.join(OUT_DIR, fn + ".tmp.webp"), "WEBP", quality=80, method=4)
        os.replace(os.path.join(OUT_DIR, fn + ".tmp.webp"), os.path.join(OUT_DIR, fn))
        values.write_grid("snodas_" + key, g, unit="in", scale=0.1)
        meta["layers"][key] = {"file": "frames/snodas/%s?v=%d" % (fn, int(time.time())), "max_in": round(float(np.nanmax(g)), 1),
                               "legend": [{"min": lo, "color": "#%02x%02x%02x" % c} for lo, c in bins]}
    meta["updated"] = dt.datetime.now().strftime("%a %b %d %I:%M %p")
    meta["updated_t"] = int(time.time())
    with open(OUT + ".tmp", "w", encoding="utf-8") as f:
        f.write("window.SNODAS = %s;\n" % json.dumps(meta, separators=(",", ":")))
    os.replace(OUT + ".tmp", OUT)
    log("snodas: %s, depth max %.1f in, swe max %.1f in" % (d, meta["layers"]["depth"]["max_in"], meta["layers"]["swe"]["max_in"]))
    return d.isoformat()


if __name__ == "__main__":
    t0 = time.time()
    build()
    print("done in %.0fs" % (time.time() - t0))
