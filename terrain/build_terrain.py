"""
Elevation tiles for the map's Sun & shade layer: WA Cascades from the slope build's 3 m DEMs, plus a ring of
USGS 1 arc-second terrain around the box for distant peaks. Method: METHOD.md; parameters: terrain_config.yaml.

Stages (each appends an accounting line to work/accounting.log and draws a figure in work/diag/):
  selftest  known answers: Terrarium round trip (numpy and through a PNG), tile arithmetic against a second
            formula, NaN-aware block means, and a warp of a synthetic UTM plane onto the mercator grid
            (a georeferencing error would show as a height error)
  margin    download the USGS 1 arc-second tiles around the box (skips files already complete)
  mosaic    z14.tif: the 3 m DEM averaged onto the zoom-14 mercator grid over the box;
            z10.tif: margin + 10 m fallback + z14.tif averaged onto the zoom-10 grid over the box plus the margin
  tiles     Terrarium PNGs: zoom 14 from z14.tif, 13-11 by 2x2 means of it, zoom 10 from z10.tif
  check     published elevations at known points, the tiles against z14.tif, zoom 10 against zoom 14

Nothing here uploads anything (upload_tiles.py does). Run with QGIS Python from this folder:
  "C:\\Program Files\\QGIS 3.34.13\\bin\\python-qgis-ltr.bat" build_terrain.py selftest margin mosaic tiles check
"""
import concurrent.futures as cf
import datetime as dt
import math
import os
import shutil
import sys
import threading
import time
import urllib.error
import urllib.request

import numpy as np
import yaml
from osgeo import gdal, osr

import tilemath as tm

gdal.UseExceptions()
osr.UseExceptions()
gdal.SetConfigOption("GDAL_PAM_ENABLED", "NO")        # no .aux.xml files next to the outputs

HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(HERE, "terrain_config.yaml"), encoding="utf-8") as _f:
    CFG = yaml.safe_load(_f)
WORK = os.path.join(HERE, CFG["work"]["dir"])
DIAG = os.path.join(WORK, "diag")
TILES = os.path.join(WORK, "tiles")
NODATA = float(CFG["source"]["nodata"])
BBOX = tuple(CFG["area"]["bbox_lonlat"])
FAR_BBOX = tm.grow_bbox(BBOX, CFG["area"]["margin_km"])
ZN0, ZN1 = CFG["tiles"]["near_zooms"]
ZF = CFG["tiles"]["far_zoom"]
STEP = CFG["tiles"]["vertical_step_m"]
UA = "BlackwaterRadar-terrain/1.0"


def _srs(epsg):
    s = osr.SpatialReference()
    s.ImportFromEPSG(epsg)
    s.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    return s


MERC = _srs(3857)
UTM = _srs(26910)


def src_path(key):
    return os.path.normpath(os.path.join(HERE, CFG["source"][key]))


def account(stage, line):
    os.makedirs(WORK, exist_ok=True)
    msg = "%s  %-9s %s" % (dt.datetime.now().strftime("%Y-%m-%d %H:%M"), stage, line)
    print(msg, flush=True)
    with open(os.path.join(WORK, "accounting.log"), "a", encoding="utf-8") as f:
        f.write(msg + "\n")


def plt_setup():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    try:
        plt.style.use("matlab")
    except OSError:
        pass
    os.makedirs(DIAG, exist_ok=True)
    return plt


def grid_for(bbox, z):
    """(outputBounds, width, height, (x0, y0, x1, y1)) of the tile-aligned mercator grid covering bbox at zoom z"""
    x0, y0, x1, y1 = tm.tile_range(bbox, z)
    b0, b1 = tm.tile_bounds(z, x0, y1), tm.tile_bounds(z, x1, y0)
    bounds = (b0[0], b0[1], b1[2], b1[3])
    return bounds, (x1 - x0 + 1) * tm.TILE, (y1 - y0 + 1) * tm.TILE, (x0, y0, x1, y1)


def warp_to(path, srcs, bbox, z, progress=True):
    bounds, w, h, rng = grid_for(bbox, z)
    t0 = [time.time(), -1]

    def cb(frac, *_):
        k = int(frac * 20)
        if progress and k != t0[1]:
            t0[1] = k
            print("  %s %3d%%  %.0f min" % (os.path.basename(path), 5 * k, (time.time() - t0[0]) / 60), flush=True)
        return 1

    gdal.Warp(path, srcs, format="GTiff", outputBounds=bounds, width=w, height=h, dstSRS=MERC.ExportToWkt(),
              resampleAlg=CFG["tiles"]["resampling"], outputType=gdal.GDT_Float32, srcNodata=NODATA, dstNodata=NODATA,
              multithread=True, warpMemoryLimit=4096, warpOptions=["NUM_THREADS=ALL_CPUS"],
              creationOptions=["TILED=YES", "BLOCKXSIZE=256", "BLOCKYSIZE=256", "COMPRESS=DEFLATE", "PREDICTOR=3",
                               "BIGTIFF=YES", "NUM_THREADS=ALL_CPUS"], callback=cb)
    return rng


def read_window(ds, col, row, w, h):
    """float32 window with NaN for no data; the parts outside the raster are NaN too"""
    out = np.full((h, w), np.nan, np.float32)
    c0, r0 = max(col, 0), max(row, 0)
    c1, r1 = min(col + w, ds.RasterXSize), min(row + h, ds.RasterYSize)
    if c1 <= c0 or r1 <= r0:
        return out
    a = ds.GetRasterBand(1).ReadAsArray(c0, r0, c1 - c0, r1 - r0).astype(np.float32)
    a[a == NODATA] = np.nan
    out[r0 - row:r1 - row, c0 - col:c1 - col] = a
    return out


def write_png(path, elev):
    from PIL import Image
    os.makedirs(os.path.dirname(path), exist_ok=True)
    Image.fromarray(tm.encode_terrarium(elev, STEP), "RGB").save(path, compress_level=CFG["tiles"]["png_compress_level"])


def read_png(path):
    from PIL import Image
    return tm.decode_terrarium(np.asarray(Image.open(path).convert("RGB")))


# ---------------------------------------------------------------- stage: selftest
def selftest():
    fails = []
    # 1. Terrarium round trip, numpy and through a PNG file
    e = np.array([[-5.0, 0.0, 350.3, 1238.06], [4392.1, np.nan, 2870.44, 12.5]], np.float32)
    d = tm.decode_terrarium(tm.encode_terrarium(e, STEP))
    err = np.nanmax(np.abs(d - e))
    if not (err <= STEP / 2 + 1e-4 and np.isnan(d[1, 1]) and np.isfinite(d).sum() == 7):
        fails.append("terrarium round trip error %.4f m" % err)
    os.makedirs(DIAG, exist_ok=True)
    p = os.path.join(WORK, "selftest.png")
    big = np.random.default_rng(0).uniform(-50, 4400, (256, 256)).astype(np.float32)
    big[:3, :3] = np.nan
    write_png(p, big)
    back = read_png(p)
    perr = np.nanmax(np.abs(back - big))
    if not (perr <= STEP / 2 + 1e-4 and np.isnan(back[:3, :3]).all() and np.isfinite(back).sum() == 256 * 256 - 9):
        fails.append("PNG round trip error %.4f m" % perr)
    os.remove(p)
    # 2. tile arithmetic against the slope check's formula (asinh(tan)), and tile centres map back to their tile
    for lon, lat in [(-120.6615, 47.5962), (-121.7604, 46.8529), (-122.2, 49.0), (-120.0, 46.0)]:
        n = 2 ** 14
        want = (int((lon + 180) / 360 * n), int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n))
        if tm.tile_of(lon, lat, 14) != want:
            fails.append("tile_of %s %s: %s != %s" % (lon, lat, tm.tile_of(lon, lat, 14), want))
        b = tm.tile_bounds(14, *want)
        c = tm.merc_to_lonlat((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)
        if tm.tile_of(c[0], c[1], 14) != want:
            fails.append("tile centre of %s maps to %s" % (want, tm.tile_of(c[0], c[1], 14)))
    # 3. block means
    a = np.arange(16, dtype=np.float32).reshape(4, 4)
    a[0, 0] = np.nan
    a[2:, 2:] = np.nan
    m = tm.block_mean(a, 2)
    if not (abs(m[0, 0] - (1 + 4 + 5) / 3) < 1e-6 and np.isnan(m[1, 1]) and abs(m[1, 0] - 10.5) < 1e-6):
        fails.append("block_mean %s" % m.tolist())
    # 4. warp a synthetic UTM plane z = easting - 650000 (1 m per m, so a half-pixel shift would show as ~3 m)
    x0, y1, res, w, h = 648000.0, 5275000.0, 3.0, 1500, 1500           # 4.5 km square near Leavenworth
    src = gdal.GetDriverByName("MEM").Create("", w, h, 1, gdal.GDT_Float32)
    src.SetGeoTransform((x0, res, 0, y1, 0, -res))
    src.SetProjection(UTM.ExportToWkt())
    xs = x0 + (np.arange(w) + 0.5) * res
    src.GetRasterBand(1).WriteArray(np.tile((xs - 650000.0).astype(np.float32), (h, 1)))
    src.GetRasterBand(1).SetNoDataValue(NODATA)
    to_ll = osr.CoordinateTransformation(UTM, _srs(4326))
    lo0, la0, _ = to_ll.TransformPoint(x0 + 1500, y1 - 3000)
    lo1, la1, _ = to_ll.TransformPoint(x0 + 3000, y1 - 1500)
    tb = (lo0, la0, lo1, la1)
    path = os.path.join(WORK, "selftest_warp.tif")
    rng = warp_to(path, src, tb, 14, progress=False)
    ds = gdal.Open(path)
    gt = ds.GetGeoTransform()
    arr = ds.GetRasterBand(1).ReadAsArray().astype(np.float64)
    to_utm = osr.CoordinateTransformation(MERC, UTM)
    errs = []
    r = np.random.default_rng(2)
    for _ in range(200):
        i, j = int(r.integers(0, arr.shape[1])), int(r.integers(0, arr.shape[0]))
        if arr[j, i] == NODATA:
            continue
        X, Y = gt[0] + (i + 0.5) * gt[1], gt[3] + (j + 0.5) * gt[5]
        ux, uy, _ = to_utm.TransformPoint(X, Y)
        if x0 + 20 < ux < x0 + w * res - 20 and y1 - h * res + 20 < uy < y1 - 20:
            errs.append(arr[j, i] - (ux - 650000.0))
    ds = None
    os.remove(path)
    errs = np.array(errs)
    ok_grid = abs(gt[0] - tm.tile_bounds(14, rng[0], rng[1])[0]) < 1e-6 and abs(gt[1] - tm.res(14)) < 1e-9
    if len(errs) < 100 or np.abs(errs).max() > 0.5 or not ok_grid:
        fails.append("warp plane: %d points, max error %.3f m, grid aligned %s" % (len(errs), np.abs(errs).max() if len(errs) else -1, ok_grid))
    account("selftest", "%s; Terrarium max error %.4f m (numpy) %.4f m (PNG); warp of a 1 m/m plane: %d points, mean %+.3f m, max |%.3f| m"
            % ("PASS" if not fails else "FAIL: " + "; ".join(fails), err, perr, len(errs), errs.mean(), np.abs(errs).max()))
    if fails:
        raise SystemExit(1)


# ---------------------------------------------------------------- stage: margin
def fetch_to(url, dest):
    """download url to dest unless dest already matches the server's size; returns bytes or None on 404"""
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            size = int(r.headers.get("Content-Length", 0))
    except urllib.error.HTTPError as e:
        if e.code in (403, 404):
            return None
        raise
    if os.path.exists(dest) and os.path.getsize(dest) == size:
        return size
    for k in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=300) as r, \
                    open(dest + ".part", "wb") as f:
                shutil.copyfileobj(r, f, 1 << 20)
            if os.path.getsize(dest + ".part") != size:
                raise IOError("short download %d of %d" % (os.path.getsize(dest + ".part"), size))
            os.replace(dest + ".part", dest)
            return size
        except Exception:  # noqa: BLE001
            if k == 3:
                raise
            time.sleep(10 * (k + 1))


def margin():
    d = os.path.join(WORK, "margin")
    os.makedirs(d, exist_ok=True)
    t0, got, missing, files = time.time(), 0, [], []
    for t in tm.margin_tiles(FAR_BBOX):
        dest = os.path.join(d, "USGS_1_%s.tif" % t)
        n = fetch_to(CFG["source"]["margin_url"].format(tile=t), dest)
        if n is None:
            missing.append(t)
            continue
        got += n
        files.append(dest)
    gdal.BuildVRT(os.path.join(d, "margin.vrt"), files)
    account("margin", "%d USGS 1 arc-second tiles for %s (box + %d km), %d not published (%s), %.2f GB on disk, %.0f s"
            % (len(files), ", ".join("%.2f" % v for v in FAR_BBOX), CFG["area"]["margin_km"], len(missing),
               " ".join(missing) or "none", got / 1e9, time.time() - t0))


# ---------------------------------------------------------------- stage: mosaic
def mosaic():
    t0 = time.time()
    z14 = os.path.join(WORK, "z14.tif")
    warp_to(z14 + ".tmp.tif", src_path("dem3_vrt"), BBOX, ZN1)
    os.replace(z14 + ".tmp.tif", z14)
    t1 = time.time()
    z10 = os.path.join(WORK, "z10.tif")
    warp_to(z10 + ".tmp.tif", [os.path.join(WORK, "margin", "margin.vrt"), src_path("fallback_vrt"), z14], FAR_BBOX, ZF)
    os.replace(z10 + ".tmp.tif", z10)
    # coverage of the box at 1/16 resolution
    ds = gdal.Open(z14)
    small = ds.GetRasterBand(1).ReadAsArray(buf_xsize=ds.RasterXSize // 16, buf_ysize=ds.RasterYSize // 16).astype(np.float64)
    gt = ds.GetGeoTransform()
    xs = gt[0] + (np.arange(small.shape[1]) + 0.5) * gt[1] * 16
    ys = gt[3] + (np.arange(small.shape[0]) + 0.5) * gt[5] * 16
    wx0, wy0 = tm.lonlat_to_merc(BBOX[0], BBOX[1])
    wx1, wy1 = tm.lonlat_to_merc(BBOX[2], BBOX[3])
    inside = ((xs[None, :] >= wx0) & (xs[None, :] <= wx1)) & ((ys[:, None] >= wy0) & (ys[:, None] <= wy1))
    nod = (small == NODATA) & inside
    f = gdal.Open(z10)
    far = f.GetRasterBand(1).ReadAsArray().astype(np.float64)
    far_nod = float((far == NODATA).mean())
    account("mosaic", "z14.tif %d x %d px (%.1f GB), box no data %.3f%% (1/16 sample), elevation %.0f to %.0f m, %.0f min; "
            "z10.tif %d x %d px over box + margin, no data %.2f%% (north of 49 N expected), %.0f min"
            % (ds.RasterXSize, ds.RasterYSize, os.path.getsize(z14) / 1e9, 100 * nod.sum() / max(inside.sum(), 1),
               small[small != NODATA].min(), small[small != NODATA].max(), (t1 - t0) / 60,
               f.RasterXSize, f.RasterYSize, 100 * far_nod, (time.time() - t1) / 60))
    plt = plt_setup()
    fig, ax = plt.subplots(1, 2, figsize=(12, 8))
    fg = f.GetGeoTransform()
    ext = (fg[0] / 1e3, (fg[0] + fg[1] * f.RasterXSize) / 1e3, (fg[3] + fg[5] * f.RasterYSize) / 1e3, fg[3] / 1e3)
    im = ax[0].imshow(np.where(far == NODATA, np.nan, far), extent=ext, cmap="gray")
    ax[0].plot(np.array([wx0, wx1, wx1, wx0, wx0]) / 1e3, np.array([wy0, wy0, wy1, wy1, wy0]) / 1e3, color="#c0504d", lw=1)
    ax[0].set_title("z10.tif (box in red; blank = no data)")
    fig.colorbar(im, ax=ax[0], shrink=0.6, label="m")
    ax[1].imshow(np.where(small == NODATA, np.nan, small), extent=(xs[0] / 1e3, xs[-1] / 1e3, ys[-1] / 1e3, ys[0] / 1e3), cmap="gray")
    ax[1].imshow(np.where(nod, 1.0, np.nan), extent=(xs[0] / 1e3, xs[-1] / 1e3, ys[-1] / 1e3, ys[0] / 1e3), cmap="autumn", alpha=1)
    ax[1].set_title("z14.tif at 1/16 (no data inside the box in orange)")
    for a in ax:
        a.set_xlabel("mercator x (km)")
        a.set_ylabel("mercator y (km)")
    fig.savefig(os.path.join(DIAG, "1_mosaics.png"), dpi=130, bbox_inches="tight")


# ---------------------------------------------------------------- stage: tiles
_local = threading.local()


def _ds(path):
    cache = getattr(_local, "ds", None)
    if cache is None:
        cache = _local.ds = {}
    if path not in cache:
        cache[path] = gdal.Open(path)
    return cache[path]


def _tile_job(z, x, y, src, rng, f):
    """one tile of zoom z from the mosaic `src` whose tile range at its own zoom starts at rng; f = 2^(zoom diff)"""
    ds = _ds(src)
    col, row = (x * f - rng[0]) * tm.TILE, (y * f - rng[1]) * tm.TILE
    a = read_window(ds, col, row, tm.TILE * f, tm.TILE * f)
    if f > 1:
        a = tm.block_mean(a, f)
    if not np.isfinite(a).any():
        return z, 0, 0
    p = os.path.join(TILES, str(z), str(x), "%d.png" % y)
    write_png(p, a)
    return z, 1, os.path.getsize(p)


def tiles():
    if os.path.isdir(TILES):
        shutil.rmtree(TILES)                        # a rebuilt mosaic must not leave stale tiles behind
    t0 = time.time()
    z14, z10 = os.path.join(WORK, "z14.tif"), os.path.join(WORK, "z10.tif")
    rng14 = tm.tile_range(BBOX, ZN1)
    jobs = []
    for z in range(ZN0, ZN1 + 1):
        x0, y0, x1, y1 = tm.tile_range(BBOX, z)
        jobs += [(z, x, y, z14, rng14, 2 ** (ZN1 - z)) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)]
    rngf = tm.tile_range(FAR_BBOX, ZF)
    jobs += [(ZF, x, y, z10, rngf, 1) for x in range(rngf[0], rngf[2] + 1) for y in range(rngf[1], rngf[3] + 1)]
    stats = {}
    with cf.ThreadPoolExecutor(12) as ex:
        for k, (z, n, size) in enumerate(ex.map(lambda j: _tile_job(*j), jobs), 1):
            s = stats.setdefault(z, [0, 0, 0])
            s[0] += 1
            s[1] += n
            s[2] += size
            if k % 2000 == 0:
                print("  %d / %d tiles, %.0f min" % (k, len(jobs), (time.time() - t0) / 60), flush=True)
    account("tiles", "%s; %d tiles, %.0f MB in all; %.0f min"
            % ("; ".join("z%d %d written of %d (%d empty) %.0f MB" % (z, s[1], s[0], s[0] - s[1], s[2] / 1e6) for z, s in sorted(stats.items())),
               sum(s[1] for s in stats.values()), sum(s[2] for s in stats.values()) / 1e6, (time.time() - t0) / 60))


# ---------------------------------------------------------------- stage: check
KNOWN = [   # name, lon, lat, published elevation m, source, search radius m (summits: the highest pixel nearby)
    ("Mount Rainier summit", -121.76044, 46.85283, 4392, "NGS 14,411 ft", 60),
    ("Mount Baker summit", -121.81446, 48.77685, 3286, "USGS 10,781 ft", 60),
    ("Glacier Peak summit", -121.11389, 48.11250, 3213, "USGS 10,541 ft", 60),
    ("Mount Stuart summit", -120.90245, 47.47511, 2870, "USGS 9,415 ft", 60),
    ("Stevens Pass (US 2)", -121.08900, 47.74650, 1238, "WSDOT 4,061 ft", 0),
    ("Leavenworth", -120.66150, 47.59620, 355, "USGS GNIS 1,165 ft", 0),
]


def tile_value(z, lon, lat):
    X, Y = tm.lonlat_to_merc(lon, lat)
    gx, gy = (X + tm.ORIGIN) / tm.res(z), (tm.ORIGIN - Y) / tm.res(z)
    p = os.path.join(TILES, str(z), str(int(gx // 256)), "%d.png" % int(gy // 256))
    if not os.path.exists(p):
        return None
    return float(read_png(p)[int(gy) % 256, int(gx) % 256])


def check():
    lines = []
    for name, lon, lat, want, src, rad in KNOWN:
        if rad:
            vals = []
            for dy in np.arange(-rad, rad + 1, 5.0):
                for dx in np.arange(-rad, rad + 1, 5.0):
                    if dx * dx + dy * dy <= rad * rad:
                        v = tile_value(ZN1, lon + dx / (111320 * math.cos(math.radians(lat))), lat + dy / 111320)
                        if v is not None and np.isfinite(v):
                            vals.append(v)
            got = max(vals) if vals else None
        else:
            got = tile_value(ZN1, lon, lat)
        far = tile_value(ZF, lon, lat)
        lines.append("%s %s m (%s) z14 %s z10 %s" % (name, want, src, "%.1f" % got if got is not None else "none",
                                                     "%.0f" % far if far is not None else "none"))
    # tiles vs z14.tif at random pixels: only the 1/8 m quantisation may differ
    ds = gdal.Open(os.path.join(WORK, "z14.tif"))
    rng14 = tm.tile_range(BBOX, ZN1)
    r = np.random.default_rng(3)
    diffs = []
    while len(diffs) < 2000:
        i, j = int(r.integers(0, ds.RasterXSize)), int(r.integers(0, ds.RasterYSize))
        v = float(ds.GetRasterBand(1).ReadAsArray(i, j, 1, 1)[0, 0])
        if v == NODATA:
            continue
        x, y = rng14[0] + i // 256, rng14[1] + j // 256
        t = read_png(os.path.join(TILES, str(ZN1), str(x), "%d.png" % y))
        diffs.append(t[j % 256, i % 256] - v)
    diffs = np.array(diffs)
    # zoom 10 against zoom 14 averaged, inside the box
    z10d = []
    w, s, e, n = BBOX
    while len(z10d) < 500:
        lon, lat = r.uniform(w + 0.05, e - 0.05), r.uniform(s + 0.05, n - 0.05)
        a, b = tile_value(ZN1, lon, lat), tile_value(ZF, lon, lat)
        if a is not None and b is not None and np.isfinite(a) and np.isfinite(b):
            z10d.append(b - a)
    z10d = np.array(z10d)
    account("check", "; ".join(lines) + "; tiles vs z14.tif at 2000 pixels: max |%.3f| m (quantisation %.4f m); "
            "z10 - z14 at 500 points: median %+.1f m, 5-95%% %+.0f to %+.0f m"
            % (np.abs(diffs).max(), STEP / 2, np.median(z10d), np.percentile(z10d, 5), np.percentile(z10d, 95)))
    # figure: a decoded zoom-13 hillshade of the Enchantments, with Colchuck Lake and Mt Stuart marked
    plt = plt_setup()
    z = 13
    cx, cy = tm.tile_of(-120.84, 47.48, z)
    rows = []
    for ty in range(cy - 2, cy + 3):
        row = []
        for tx in range(cx - 2, cx + 3):
            p = os.path.join(TILES, str(z), str(tx), "%d.png" % ty)
            row.append(read_png(p) if os.path.exists(p) else np.full((256, 256), np.nan, np.float32))
        rows.append(np.hstack(row))
    a = np.vstack(rows)
    g = tm.res(z) * math.cos(math.radians(47.48))
    dzdy, dzdx = np.gradient(a, g)
    az, el = math.radians(315), math.radians(35)
    # rows run south, so d/dnorth = -dzdy
    shade = np.clip((math.sin(el) - math.cos(el) * (dzdx * math.sin(az) - dzdy * math.cos(az))) / np.sqrt(1 + dzdx ** 2 + dzdy ** 2), 0, 1)
    b0 = tm.tile_bounds(z, cx - 2, cy + 2)
    b1 = tm.tile_bounds(z, cx + 2, cy - 2)
    fig, ax = plt.subplots(figsize=(8, 8))
    ax.imshow(shade, cmap="gray", extent=(b0[0] / 1e3, b1[2] / 1e3, b0[1] / 1e3, b1[3] / 1e3))
    for name, lon, lat in [("Colchuck Lake", -120.8345, 47.4960), ("Mt Stuart", -120.90245, 47.47511), ("Dragontail", -120.8356, 47.4804)]:
        X, Y = tm.lonlat_to_merc(lon, lat)
        ax.plot(X / 1e3, Y / 1e3, "o", color="#c0504d", ms=4)
        ax.annotate(name, (X / 1e3, Y / 1e3), xytext=(4, 4), textcoords="offset points", color="#c0504d", fontsize=9)
    ax.set_title("Decoded zoom-13 tiles, hillshade: features must sit under their markers")
    ax.set_xlabel("mercator x (km)")
    ax.set_ylabel("mercator y (km)")
    fig.savefig(os.path.join(DIAG, "2_enchantments_decoded.png"), dpi=130, bbox_inches="tight")


STAGES = {"selftest": selftest, "margin": margin, "mosaic": mosaic, "tiles": tiles, "check": check}

if __name__ == "__main__":
    for name in sys.argv[1:] or ["selftest"]:
        STAGES[name]()
