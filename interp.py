"""
Elevation-aware interpolation of station totals across the map window.

For a given set of station values (precipitation or new snow for one time window):
  1. fit value ~ elevation (slope forced >= 0: precipitation tends to rise with terrain)
  2. inverse-distance-weight the residuals from the nearest stations
  3. surface = fit(DEM) + IDW(residuals), clipped at zero, faded out where the
     nearest station is far away

Terrain comes from AWS Terrarium elevation tiles (same zoom-7 window as the radar),
cached in data/dem_z7.npy.  Output: frames/interp/<mode>_<window>.webp overlays.
"""
import io
import math
import os
import urllib.request

import numpy as np
from PIL import Image
from scipy.spatial import cKDTree

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data")
OUT_DIR = os.path.join(ROOT, "frames", "interp")
DEM_FILE = os.path.join(DATA, "dem_z7.npy")
UA = "RadarTracker/1.0 (personal weather map; chris.gabrielli@gmail.com)"

Z, X0, X1, Y0, Y1, T = 7, 19, 23, 42, 46, 256      # must match capture.py
W = (X1 - X0 + 1) * T                               # 1280
H = (Y1 - Y0 + 1) * T
STEP = 4                                            # compute on a 320x320 grid, upsample
MAX_DIST_PX = 110                                   # ~90 km: beyond this the surface fades out
K = 10                                              # neighbours for IDW

RAIN_BINS = [(0.01, (185, 240, 185)), (0.10, (80, 200, 80)), (0.25, (255, 240, 0)), (0.50, (255, 170, 0)),
             (0.75, (255, 90, 0)), (1.00, (220, 0, 0)), (1.50, (200, 0, 200)), (2.00, (120, 0, 180)), (3.00, (70, 0, 110))]
SNOW_BINS = [(0.1, (127, 191, 232)), (1, (63, 150, 214)), (3, (31, 111, 191)), (6, (11, 74, 153)), (12, (91, 47, 163)), (24, (58, 19, 112))]


def px_of(lat, lon):
    """lat/lon -> fractional pixel (x, y) in the window image"""
    n = 2 ** Z
    x = (lon + 180.0) / 360.0 * n
    y = (1 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi) / 2 * n
    return (x - X0) * T, (y - Y0) * T


def dem():
    if os.path.exists(DEM_FILE):
        return np.load(DEM_FILE)
    grid = np.zeros((H, W), np.float32)
    for x in range(X0, X1 + 1):
        for y in range(Y0, Y1 + 1):
            url = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/%d/%d/%d.png" % (Z, x, y)
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as r:
                a = np.asarray(Image.open(io.BytesIO(r.read())).convert("RGB")).astype(np.float32)
            e = a[..., 0] * 256 + a[..., 1] + a[..., 2] / 256 - 32768
            grid[(y - Y0) * T:(y - Y0 + 1) * T, (x - X0) * T:(x - X0 + 1) * T] = e
    grid = np.clip(grid, 0, None)          # sea level floor
    os.makedirs(DATA, exist_ok=True)
    np.save(DEM_FILE, grid)
    return grid


def surface(points, elev):
    """points: list of (x_px, y_px, value). elev: DEM (H, W). -> (H//STEP, W//STEP) array or None"""
    if len(points) < 6:
        return None
    P = np.array(points, np.float64)
    xs, ys, vs = P[:, 0], P[:, 1], P[:, 2]
    ok = (xs >= 0) & (xs < W) & (ys >= 0) & (ys < H)
    xs, ys, vs = xs[ok], ys[ok], vs[ok]
    if len(vs) < 6:
        return None
    st_elev = elev[np.clip(ys.astype(int), 0, H - 1), np.clip(xs.astype(int), 0, W - 1)]
    # elevation trend, slope not allowed to be negative; ignore if it explains nothing
    e0 = st_elev.mean()
    slope = 0.0
    if st_elev.std() > 100:
        cov = np.mean((st_elev - e0) * (vs - vs.mean()))
        slope = max(0.0, cov / (st_elev.var() + 1e-9))
        pred = vs.mean() + slope * (st_elev - e0)
        if np.var(vs - pred) > 0.95 * np.var(vs):
            slope = 0.0
    resid = vs - (vs.mean() + slope * (st_elev - e0))

    coarse = elev[::STEP, ::STEP]
    hh, ww = coarse.shape
    gy, gx = np.mgrid[0:hh, 0:ww]
    q = np.column_stack([(gx.ravel() + 0.5) * STEP, (gy.ravel() + 0.5) * STEP])
    tree = cKDTree(np.column_stack([xs, ys]))
    k = min(K, len(vs))
    d, idx = tree.query(q, k=k)
    if k == 1:
        d, idx = d[:, None], idx[:, None]
    wgt = 1.0 / (d + 3.0) ** 2
    r = (wgt * resid[idx]).sum(1) / wgt.sum(1)
    e_clip = np.clip(coarse.ravel(), st_elev.min(), st_elev.max())
    val = vs.mean() + slope * (e_clip - e0) + r
    val = np.clip(val, 0, None)
    # fade with distance to nearest station
    near = d[:, 0]
    alpha = np.clip(1.0 - (near - MAX_DIST_PX * 0.6) / (MAX_DIST_PX * 0.4), 0, 1)
    return val.reshape(hh, ww), alpha.reshape(hh, ww)


def colorize(val, alpha, bins):
    h, w = val.shape
    rgb = np.zeros((h, w, 3), np.uint8)
    a = np.zeros((h, w), np.float32)
    for lo, color in bins:
        m = val >= lo
        rgb[m] = color
        a[m] = 1.0
    a = (a * alpha * 175).astype(np.uint8)
    img = Image.fromarray(np.dstack([rgb, a]), "RGBA")
    return img.resize((w * STEP, h * STEP), Image.BILINEAR)


def build(stations, windows, log=print):
    """stations: list of dicts from stations.py (precip/snow keyed by window string). -> meta dict"""
    elev = dem()
    os.makedirs(OUT_DIR, exist_ok=True)
    meta = {}
    for mode, bins in (("precip", RAIN_BINS), ("snow", SNOW_BINS)):
        for w in windows:
            pts = []
            for s in stations:
                v = (s.get(mode) or {}).get(str(w))
                if v is None:
                    continue
                if mode == "snow" and v < 0:
                    v = 0.0
                x, y = px_of(s["lat"], s["lon"])
                pts.append((x, y, float(v)))
            res = surface(pts, elev)
            if res is None:
                continue
            val, alpha = res
            img = colorize(val, alpha, bins)
            try:
                import values
                full = np.where(alpha > 0.3, val, np.nan)
                values.write_grid("interp_%s_%d" % (mode, w), np.kron(full, np.ones((STEP, STEP))))
            except Exception as e:  # noqa: BLE001
                log("interp values %s %d failed: %r" % (mode, w, e))
            fn = "%s_%dh.webp" % (mode, w)
            tmp = os.path.join(OUT_DIR, fn + ".tmp.webp")
            img.save(tmp, "WEBP", quality=80, method=4)
            os.replace(tmp, os.path.join(OUT_DIR, fn))
            meta.setdefault(mode, {})[str(w)] = {"file": "frames/interp/%s?v=%d" % (fn, int(os.path.getmtime(os.path.join(OUT_DIR, fn)))),
                                                 "n": len(pts), "max": round(float(val.max()), 2)}
    log("interp: %s" % ", ".join("%s %s" % (m, "/".join(sorted(v))) for m, v in meta.items()))
    return meta


if __name__ == "__main__":
    import json
    s = open(os.path.join(DATA, "stations.js"), encoding="utf-8").read()
    d = json.loads(s[s.index("{"):s.rindex("}") + 1])
    print(json.dumps(build(d["stations"], d["windows"]), indent=1))
