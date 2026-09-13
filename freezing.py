"""
Freezing level (height of the 0 C isotherm) from the HRRR model, hourly runs,
forecast hours 0..18 every 3 h, pulled as a small subset from NOAA NOMADS.

For each forecast hour writes:
  frames/freezing/f<h>.webp        filled bands every STEP_FT
  data/fz_<h>.js                   contour lines (GeoJSON, feet) -> window.FZ_CONTOURS["<h>"]
  data/values/fz_<h>.js            value grid for click-anywhere (feet)
and data/freezing.js -> window.FREEZING = {run_utc, step_ft, hours:[...]}.

Run standalone:  python freezing.py
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

import region

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = region.data_dir()
OUT_DIR = os.path.join(region.frames_dir(), "freezing")
TMP = os.path.join(OUT_DIR, "_grib")
OUT = os.path.join(DATA, "freezing.js")
UA = "RadarTracker/1.0 (personal weather map; chris.gabrielli@gmail.com)"

STEP_FT = 500
BB = region.bbox()                       # contour and band interval
HOURS = (0, 3, 6, 9, 12, 15, 18)
Z, X0, X1, Y0, Y1 = region.window()
T = 256
W = (X1 - X0 + 1) * T
H = (Y1 - Y0 + 1) * T
STEP = 2                            # compute at 640x640

import values  # noqa: E402

# band colours from 0 ft (deep blue) to 14000 ft (dark red), one per STEP_FT
STOPS = [(0, (68, 1, 84)), (2000, (72, 40, 120)), (3000, (62, 74, 137)), (4000, (49, 104, 142)), (5000, (38, 130, 142)), (6000, (31, 158, 137)),
         (7000, (53, 183, 121)), (8000, (109, 205, 89)), (9000, (180, 222, 44)), (10000, (253, 231, 37)), (12000, (253, 174, 60)), (14000, (230, 80, 40))]


def band_color(ft):
    for (a, ca), (b, cb) in zip(STOPS, STOPS[1:]):
        if ft <= b:
            t = 0 if b == a else max(0.0, (ft - a) / (b - a))
            return tuple(int(ca[i] + (cb[i] - ca[i]) * t) for i in range(3))
    return STOPS[-1][1]


def fetch(url, dest):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=180) as r:
        b = r.read()
    if b[:4] != b"GRIB":
        raise RuntimeError("not a GRIB file (run not available yet?)")
    with open(dest, "wb") as f:
        f.write(b)


def grid_latlon():
    n = 2 ** Z
    ys = (np.arange(0, H, STEP) + STEP / 2) / T + Y0
    xs = (np.arange(0, W, STEP) + STEP / 2) / T + X0
    lon = xs / n * 360.0 - 180.0
    lat = np.degrees(np.arctan(np.sinh(np.pi - 2 * np.pi * ys / n)))
    return lat, lon


_tree = None


def resample(field, lat2d, lon2d):
    global _tree
    k = np.cos(np.radians(47.0))
    if _tree is None:
        src_lon = np.where(lon2d > 180, lon2d - 360, lon2d)
        tree = cKDTree(np.column_stack([lat2d.ravel(), src_lon.ravel() * k]))
        lat, lon = grid_latlon()
        glat, glon = np.meshgrid(lat, lon, indexing="ij")
        d, idx = tree.query(np.column_stack([glat.ravel(), glon.ravel() * k]), k=1)
        _tree = (idx, d > 0.06, glat.shape)
    idx, outside, shape = _tree
    v = field.ravel()[idx]
    return np.where(outside, np.nan, v).reshape(shape)


def bands_image(ft):
    h, w = ft.shape
    rgb = np.zeros((h, w, 3), np.uint8)
    a = np.where(np.isnan(ft), 0, 150).astype(np.uint8)
    q = np.floor(np.nan_to_num(ft, nan=0) / STEP_FT) * STEP_FT
    for lvl in np.unique(q):
        rgb[q == lvl] = band_color(float(lvl))
    return Image.fromarray(np.dstack([rgb, a]), "RGBA").resize((w * STEP, h * STEP), Image.NEAREST)


def contours(ft):
    """-> GeoJSON FeatureCollection of contour lines at STEP_FT intervals (lat/lon)"""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from scipy.ndimage import gaussian_filter
    lat, lon = grid_latlon()
    f = gaussian_filter(np.nan_to_num(ft, nan=np.nanmean(ft)), sigma=3.0)   # smooth the 3 km terrain noise
    lo, hi = np.nanmin(f), np.nanmax(f)
    levels = np.arange(np.floor(lo / STEP_FT) * STEP_FT, hi + STEP_FT, STEP_FT)
    fig, ax = plt.subplots()
    cs = ax.contour(lon, lat, f, levels=levels)
    feats = []
    for lvl, segs in zip(cs.levels, cs.allsegs):
        for seg in segs:
            if len(seg) < 12:
                continue
            seg = seg[::3] if len(seg) > 40 else seg
            feats.append({"type": "Feature", "properties": {"ft": int(lvl)},
                          "geometry": {"type": "LineString", "coordinates": [[round(float(x), 3), round(float(y), 3)] for x, y in seg]}})
    plt.close(fig)
    return {"type": "FeatureCollection", "features": feats}


def latest_run():
    """most recent HRRR run that has already posted the last forecast hour we need"""
    now = dt.datetime.now(dt.timezone.utc).replace(minute=0, second=0, microsecond=0)
    for back in range(1, 6):
        run = now - dt.timedelta(hours=back)
        try:
            fetch(url_for(run, HOURS[-1]), os.path.join(TMP, "probe.grib2"))
            return run
        except Exception:  # noqa: BLE001
            continue
    raise RuntimeError("no complete HRRR run available")


def url_for(run, fh):
    return ("https://nomads.ncep.noaa.gov/cgi-bin/filter_hrrr_2d.pl?file=hrrr.t%02dz.wrfsfcf%02d.grib2"
            "&var_HGT=on&lev_0C_isotherm=on&subregion=&leftlon=%.2f&rightlon=%.2f&toplat=%.2f&bottomlat=%.2f&dir=%%2Fhrrr.%s%%2Fconus"
            % (run.hour, fh, BB[2], BB[3], BB[1], BB[0], run.strftime("%Y%m%d")))


def build(log=print):
    import cfgrib
    os.makedirs(TMP, exist_ok=True)
    os.makedirs(OUT_DIR, exist_ok=True)
    run = latest_run()
    meta = {"run_utc": run.strftime("%Y-%m-%dT%H:%M"), "step_ft": STEP_FT, "hours": []}
    for fh in HOURS:
        path = os.path.join(TMP, "f%02d.grib2" % fh)
        try:
            fetch(url_for(run, fh), path)
        except Exception as e:  # noqa: BLE001
            log("freezing: f%02d failed: %r" % (fh, e))
            continue
        ds = cfgrib.open_datasets(path)[0]
        da = ds[list(ds.data_vars)[0]]
        ft = resample(da.values.astype(np.float32) * 3.28084, ds.latitude.values, ds.longitude.values)
        img = bands_image(ft)
        fn = "f%02d.webp" % fh
        img.save(os.path.join(OUT_DIR, fn + ".tmp.webp"), "WEBP", quality=80, method=4)
        os.replace(os.path.join(OUT_DIR, fn + ".tmp.webp"), os.path.join(OUT_DIR, fn))
        gj = contours(ft)
        with open(os.path.join(DATA, "fz_%d.js.tmp" % fh), "w", encoding="utf-8") as f:
            f.write('window.FZ_CONTOURS=window.FZ_CONTOURS||{};window.FZ_CONTOURS["%d"]=%s;\n' % (fh, json.dumps(gj, separators=(",", ":"))))
        os.replace(os.path.join(DATA, "fz_%d.js.tmp" % fh), os.path.join(DATA, "fz_%d.js" % fh))
        values.write_grid("fz_%d" % fh, np.kron(ft, np.ones((STEP, STEP))), unit="ft", scale=10)
        valid = run + dt.timedelta(hours=fh)
        meta["hours"].append({"h": fh, "valid_utc": valid.strftime("%Y-%m-%dT%H:%M"), "file": "frames/freezing/%s?v=%d" % (fn, int(time.time())),
                              "contours": "data/fz_%d.js" % fh, "min_ft": int(np.nanmin(ft)), "max_ft": int(np.nanmax(ft)), "lines": len(gj["features"])})
        try:
            os.remove(path)
        except OSError:
            pass
    meta["updated"] = dt.datetime.now().strftime("%a %b %d %I:%M %p")
    meta["updated_t"] = int(time.time())
    with open(OUT + ".tmp", "w", encoding="utf-8") as f:
        f.write("window.FREEZING = %s;\n" % json.dumps(meta, separators=(",", ":")))
    os.replace(OUT + ".tmp", OUT)
    log("freezing: HRRR %sZ, %d hours, now %d-%d ft" % (run.strftime("%H"), len(meta["hours"]),
        meta["hours"][0]["min_ft"] if meta["hours"] else 0, meta["hours"][0]["max_ft"] if meta["hours"] else 0))
    return meta


def elevation_grid(log=print):
    """one-time value grid of terrain elevation (ft) for the click panel"""
    dem = os.path.join(DATA, "dem_z7.npy")
    if os.path.exists(dem) and not os.path.exists(os.path.join(DATA, "values", "elev.js")):
        values.write_grid("elev", np.load(dem) * 3.28084, unit="ft", scale=10)
        log("freezing: wrote elevation grid")


if __name__ == "__main__":
    t0 = time.time()
    elevation_grid()
    build()
    print("done in %.0fs" % (time.time() - t0))
