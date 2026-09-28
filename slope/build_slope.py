"""
Slope-angle tiles for the radar map: WA Cascades, from USGS 1 m lidar averaged to 3 m.

Stages (each appends an accounting line to work/accounting.log and draws a figure in work/diag/):
  selftest   known-answer tests: synthetic planes and a cone must come back at their true angle and band
  inventory  which lidar flights cover each 10 km cell (USGS TNM API), the 10 m fallback tiles, download size
  dem        per cell: lidar flights newest first, each filling only what newer ones left empty, averaged to
             3 m on the UTM 10N grid; what is still empty comes from the 10 m fallback
  slope      per cell: slope in degrees from the 3 m mosaic (with a 3-pixel border from the neighbours),
             classed into CalTopo's bands
  tiles      XYZ PNG tiles in web mercator for the map; tiles with nothing steeper than 27 degrees are skipped

Every parameter comes from slope_config.yaml. Nothing here uploads anything.
Run with QGIS Python from this folder:
  "C:\\Program Files\\QGIS 3.34.13\\bin\\python-qgis-ltr.bat" build_slope.py selftest inventory
Stages are resumable: a cell with its .json written is skipped.
"""
import concurrent.futures as cf
import datetime as dt
import json
import math
import os
import re
import shutil
import sys
import time
import urllib.parse
import urllib.request

import numpy as np
import yaml
from osgeo import gdal, ogr, osr

gdal.UseExceptions()
ogr.UseExceptions()
osr.UseExceptions()

HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(HERE, "slope_config.yaml"), encoding="utf-8") as _f:
    CFG = yaml.safe_load(_f)
WORK = os.path.join(HERE, CFG["work"]["dir"])
DIAG = os.path.join(WORK, "diag")
TNM = "https://tnmaccess.nationalmap.gov/api/v1/products?"
UA = "BlackwaterRadar-slope/1.0"
RES = CFG["dem"]["res_m"]
CELL = CFG["area"]["cell_m"]
BANDS = CFG["slope"]["bands_deg"]
COLORS = [tuple(int(c[i:i + 2], 16) for i in (0, 2, 4)) for c in CFG["slope"]["colors"]]
NODATA = -9999.0


def _srs(epsg):
    s = osr.SpatialReference()
    s.ImportFromEPSG(epsg)
    s.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    return s


LL = _srs(4326)
UTM = _srs(int(CFG["area"]["crs"].split(":")[1]))
TO_UTM = osr.CoordinateTransformation(LL, UTM)


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


# ---------------------------------------------------------------- geometry
def rect(x0, y0, x1, y1):
    ring = ogr.Geometry(ogr.wkbLinearRing)
    for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)):
        ring.AddPoint_2D(x, y)
    p = ogr.Geometry(ogr.wkbPolygon)
    p.AddGeometry(ring)
    return p


def area_poly_utm():
    w, s, e, n = CFG["area"]["bbox_lonlat"]
    pts = ([(w + (e - w) * i / 100, s) for i in range(101)] + [(e, s + (n - s) * i / 100) for i in range(101)] +
           [(e - (e - w) * i / 100, n) for i in range(101)] + [(w, n - (n - s) * i / 100) for i in range(101)])
    ring = ogr.Geometry(ogr.wkbLinearRing)
    for lon, lat in pts:
        x, y, _ = TO_UTM.TransformPoint(lon, lat)
        ring.AddPoint_2D(x, y)
    poly = ogr.Geometry(ogr.wkbPolygon)
    poly.AddGeometry(ring)
    return poly


def all_cells():
    poly = area_poly_utm()
    x0, x1, y0, y1 = poly.GetEnvelope()
    return [(i, j) for i in range(int(x0 // CELL), int(x1 // CELL) + 1) for j in range(int(y0 // CELL), int(y1 // CELL) + 1)
            if poly.Intersects(rect(i * CELL, j * CELL, (i + 1) * CELL, (j + 1) * CELL))]


def ckey(c):
    return "e%03dn%04d" % c          # e066n0526 = 660-670 km east, 5260-5270 km north (UTM 10N)


def cell_grid(c):
    """Cell bounds snapped outward to the global 3 m grid (multiples of RES), so neighbours share pixels exactly."""
    x0, y0 = c[0] * CELL, c[1] * CELL
    return (math.floor(x0 / RES) * RES, math.floor(y0 / RES) * RES, math.ceil((x0 + CELL) / RES) * RES, math.ceil((y0 + CELL) / RES) * RES)


# ---------------------------------------------------------------- raster helpers (shared with the self-test)
def warp_arr(src, bounds, alg):
    """Warp any raster onto the 3 m UTM grid over `bounds`; returns float32 with NaN for no data."""
    w, h = int(round((bounds[2] - bounds[0]) / RES)), int(round((bounds[3] - bounds[1]) / RES))
    ds = gdal.Warp("", src, format="MEM", outputBounds=bounds, width=w, height=h, dstSRS=UTM.ExportToWkt(),
                   resampleAlg=alg, outputType=gdal.GDT_Float32, dstNodata=NODATA, multithread=True)
    a = ds.GetRasterBand(1).ReadAsArray().astype(np.float32)
    a[a == NODATA] = np.nan
    return a


def mem_ds(a, x0, y1, res):
    ds = gdal.GetDriverByName("MEM").Create("", a.shape[1], a.shape[0], 1, gdal.GDT_Float32)
    ds.SetGeoTransform((x0, res, 0, y1, 0, -res))
    ds.SetProjection(UTM.ExportToWkt())
    b = ds.GetRasterBand(1)
    b.SetNoDataValue(NODATA)
    b.WriteArray(np.where(np.isnan(a), NODATA, a).astype(np.float32))
    return ds


def slope_deg(dem_ds):
    s = gdal.DEMProcessing("", dem_ds, "slope", format="MEM", alg=CFG["slope"]["algorithm"], slopeFormat="degree",
                           computeEdges=CFG["slope"]["compute_edges"])
    b = s.GetRasterBand(1)
    a = b.ReadAsArray().astype(np.float32)
    nd = b.GetNoDataValue()
    if nd is not None:
        a[a == nd] = np.nan
    return a


def classify(slope):
    """0 = flatter than the first band, 1..7 = CalTopo bands, 255 = no data."""
    c = np.zeros(slope.shape, np.uint8)
    for i, lo in enumerate(BANDS):
        c[slope >= lo] = i + 1
    c[np.isnan(slope)] = 255
    return c


def color_table():
    ct = gdal.ColorTable()
    ct.SetColorEntry(0, (0, 0, 0, 0))
    for i, rgb in enumerate(COLORS):
        ct.SetColorEntry(i + 1, rgb + (255,))
    for i in range(len(COLORS) + 1, 256):
        ct.SetColorEntry(i, (0, 0, 0, 0))
    return ct


def write_tif(path, a, bounds, dtype, nodata=None, ct=None):
    drv = gdal.GetDriverByName("GTiff")
    opts = ["COMPRESS=DEFLATE", "TILED=YES"] + (["PREDICTOR=3"] if dtype == gdal.GDT_Float32 else [])
    ds = drv.Create(path + ".tmp.tif", a.shape[1], a.shape[0], 1, dtype, opts)
    ds.SetGeoTransform((bounds[0], RES, 0, bounds[3], 0, -RES))
    ds.SetProjection(UTM.ExportToWkt())
    b = ds.GetRasterBand(1)
    if nodata is not None:
        b.SetNoDataValue(nodata)
    if ct is not None:
        b.SetRasterColorTable(ct)
    b.WriteArray(a)
    ds = None
    os.replace(path + ".tmp.tif", path)


# ---------------------------------------------------------------- stage: selftest
def selftest():
    """Known answers through the same functions the build uses."""
    res, n, results = RES, 200, []
    x = np.arange(n) * res
    # 0.02 deg either side of each band edge: a plane exactly on an edge comes back 0.00002 deg low from
    # float32 rounding and splits between bands, which real terrain never does
    for deg in (0.0, 26.98, 27.02, 29.98, 30.02, 31.98, 32.02, 34.98, 35.02, 45.98, 46.02, 50.98, 51.02, 59.98, 60.02, 75.0):
        dem = np.tile(np.tan(np.radians(deg)) * x, (n, 1)).astype(np.float32)       # plane rising to the east
        s = slope_deg(mem_ds(dem, 500000, 5200000, res))[5:-5, 5:-5]
        c = classify(s)
        want = sum(1 for lo in BANDS if deg >= lo)
        ok = abs(float(np.nanmedian(s)) - deg) < 0.05 and (c == want).mean() > 0.99
        results.append(("plane %.2f deg" % deg, round(float(np.nanmedian(s)), 3), int(np.bincount(c.ravel()).argmax()), want, ok))
    # 1 m plane averaged to 3 m keeps its angle (the averaging step must not flatten a uniform slope)
    n1 = 600
    dem1 = np.tile(np.tan(np.radians(40.0)) * np.arange(n1), (n1, 1)).astype(np.float32)
    src = gdal.GetDriverByName("MEM").Create("", n1, n1, 1, gdal.GDT_Float32)
    src.SetGeoTransform((500000, 1, 0, 5200600, 0, -1))
    src.SetProjection(UTM.ExportToWkt())
    src.GetRasterBand(1).WriteArray(dem1)
    a3 = warp_arr(src, (500000, 5200000, 500600, 5200600), CFG["dem"]["lidar_resampling"])
    s3 = slope_deg(mem_ds(a3, 500000, 5200600, RES))[5:-5, 5:-5]
    results.append(("1 m 40 deg plane -> 3 m", round(float(np.nanmedian(s3)), 3), None, None, abs(float(np.nanmedian(s3)) - 40) < 0.05))
    # cone: slope 45 everywhere except the apex
    yy, xx = np.mgrid[0:n, 0:n] * res
    r = np.hypot(xx - n * res / 2, yy - n * res / 2)
    s = slope_deg(mem_ds((1000 - r).astype(np.float32), 500000, 5200000 + n * res, res))
    ring = (r > 20) & (r < n * res / 2 - 20)
    results.append(("cone 45 deg", round(float(np.nanmedian(s[ring])), 3), None, None, abs(float(np.nanmedian(s[ring])) - 45) < 0.3))
    for name, got, cls, want, ok in results:
        print("  %-26s slope %-8s class %-4s expected %-4s %s" % (name, got, cls, want, "ok" if ok else "FAIL"))
    bad = [r for r in results if not r[-1]]
    account("selftest", "%d known-answer cases, %d failed" % (len(results), len(bad)))
    if bad:
        raise SystemExit("self-test failed")


# ---------------------------------------------------------------- stage: inventory
def fetch(url, timeout=120, tries=4):
    for k in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=timeout) as r:
                return r.read()
        except Exception:  # noqa: BLE001
            if k == tries - 1:
                raise
            time.sleep(5 * (k + 1))


def tnm_products(dataset, bbox):
    items, off = {}, 0
    while True:
        q = urllib.parse.urlencode({"datasets": dataset, "bbox": ",".join("%.4f" % v for v in bbox), "max": 500,
                                    "offset": off, "outputFormat": "JSON"})
        r = json.loads(fetch(TNM + q))
        got = r.get("items", [])
        for it in got:
            if it.get("downloadURL", "").lower().endswith(".tif"):
                items[it["downloadURL"]] = it
        off += len(got)
        if not got or off >= r.get("total", 0):
            return list(items.values())


def flight_year(it):
    """Acquisition year from the project name (e.g. WA_EasternCascades_2019_B19 -> 2019, WA_CentralWildfire_D22 -> 2022);
    the USGS publication year only if the name has neither."""
    t = it["title"] + " " + os.path.basename(it["downloadURL"])
    m = re.search(r"(?<!\d)(19[89]\d|20[0-4]\d)(?!\d)", t)
    if m:
        return int(m.group(1))
    m = re.search(r"_[A-Z](\d{2})(?![0-9])", t)
    if m:
        return 2000 + int(m.group(1))
    return int((it.get("publicationDate") or "1900")[:4])


def flight_order(p):
    """Sort key, highest first: newest flight, then files already on the zone-10 grid, then latest publication."""
    return (p["year"], "Meter 11 " not in p["title"], p["published"])


def product_cells(it, cellset):
    m = re.search(r"Meter 10 x(\d+)y(\d+)", it["title"]) or re.search(r"one meter x(\d+)y(\d+)", it["title"], re.I)
    if m:                                # 10 km square on the zone-10 grid: xNN = east km/10, yNNN = top north km/10
        c = (int(m.group(1)), int(m.group(2)) - 1)
        return [c] if c in cellset else []
    b = it["boundingBox"]                # anything else: every cell its footprint covers (shrunk to skip edge slivers)
    xs, ys = [], []
    for lon, lat in ((b["minX"], b["minY"]), (b["maxX"], b["minY"]), (b["maxX"], b["maxY"]), (b["minX"], b["maxY"])):
        x, y, _ = TO_UTM.TransformPoint(lon, lat)
        xs.append(x)
        ys.append(y)
    x0, x1, y0, y1 = min(xs) + 400, max(xs) - 400, min(ys) + 400, max(ys) - 400
    return [(i, j) for i in range(int(x0 // CELL), int(x1 // CELL) + 1) for j in range(int(y0 // CELL), int(y1 // CELL) + 1) if (i, j) in cellset]


def inventory():
    cells = all_cells()
    cellset = set(cells)
    bbox = CFG["area"]["bbox_lonlat"]
    lidar = tnm_products(CFG["source"]["lidar_dataset"], bbox)
    by_cell, unplaced = {ckey(c): [] for c in cells}, 0
    for it in lidar:
        cs = product_cells(it, cellset)
        unplaced += not cs
        for c in cs:
            by_cell[ckey(c)].append({"title": it["title"], "url": it["downloadURL"], "bytes": it.get("sizeInBytes") or 0,
                                     "year": flight_year(it), "published": it.get("publicationDate", "")})
    fb = {}
    for it in tnm_products(CFG["source"]["fallback_dataset"], bbox):
        m = re.search(r"n(\d+)w(\d+)", it["title"] + os.path.basename(it["downloadURL"]))
        w, s_, e, n = bbox                       # tile nNNwWWW covers NN-1..NN north, WWW..WWW-1 west
        if m and not (int(m.group(1)) - 1 < n and int(m.group(1)) > s_ and -int(m.group(2)) < e and -int(m.group(2)) + 1 > w):
            continue
        if m and (m.group(0) not in fb or it.get("publicationDate", "") > fb[m.group(0)]["published"]):
            fb[m.group(0)] = {"title": it["title"], "url": it["downloadURL"], "bytes": it.get("sizeInBytes") or 0,
                              "published": it.get("publicationDate", "")}
    inv = {"built": dt.datetime.now().isoformat(timespec="minutes"), "cells": by_cell, "fallback": fb}
    with open(os.path.join(WORK, "inventory.json"), "w", encoding="utf-8") as f:
        json.dump(inv, f, indent=1)
    with_lidar = sum(1 for v in by_cell.values() if v)
    n_prod = sum(len(v) for v in by_cell.values())
    gb_all = sum({p["url"]: p["bytes"] for v in by_cell.values() for p in v}.values()) / 1e9
    gb_newest = sum({max(v, key=flight_order)["url"]: max(v, key=flight_order)["bytes"] for v in by_cell.values() if v}.values()) / 1e9
    account("inventory", "%d cells in the area; %d with lidar, %d without (10 m fallback); %d lidar files from %d USGS items "
            "(%d not placed in any cell); download (unique files) %.1f GB if every flight is needed, %.1f GB if the first-choice flight covers each cell; "
            "fallback: %d tiles, %.1f GB" % (len(cells), with_lidar, len(cells) - with_lidar, n_prod, len(lidar), unplaced,
                                             gb_all, gb_newest, len(fb), sum(v["bytes"] for v in fb.values()) / 1e9))
    # figure: cells coloured by the newest flight year, grey where there is no lidar
    plt = plt_setup()
    from matplotlib.patches import Rectangle
    fig, ax = plt.subplots(figsize=(7, 10))
    years = sorted({max(p["year"] for p in v) for v in by_cell.values() if v})
    cmap = plt.get_cmap("viridis", max(len(years), 1))
    for c in cells:
        v = by_cell[ckey(c)]
        col = cmap(years.index(max(p["year"] for p in v))) if v else (0.8, 0.8, 0.8, 1)
        ax.add_patch(Rectangle((c[0] * 10, c[1] * 10), 10, 10, facecolor=col, edgecolor="white", lw=0.5))
        if len(v) > 1:
            ax.text(c[0] * 10 + 5, c[1] * 10 + 5, str(len(v)), ha="center", va="center", fontsize=5, color="white")
    ring = area_poly_utm().GetGeometryRef(0)
    ax.plot([ring.GetX(i) / 1000 for i in range(ring.GetPointCount())], [ring.GetY(i) / 1000 for i in range(ring.GetPointCount())], "k-", lw=1)
    for i, y in enumerate(years):
        ax.add_patch(Rectangle((0, 0), 0, 0, facecolor=cmap(i), label=str(y)))
    ax.add_patch(Rectangle((0, 0), 0, 0, facecolor=(0.8, 0.8, 0.8), label="no lidar (10 m)"))
    ax.legend(title="newest flight", fontsize=7, loc="upper left", bbox_to_anchor=(1.02, 1))
    ax.set_aspect("equal")
    ax.autoscale_view()
    ax.set_xlabel("UTM 10N east (km)")
    ax.set_ylabel("UTM 10N north (km)")
    ax.set_title("Lidar coverage by 10 km cell (number = flights available)")
    fig.savefig(os.path.join(DIAG, "1_inventory_coverage.png"), dpi=130, bbox_inches="tight")


# ---------------------------------------------------------------- stage: dem
import threading
_LOCK = threading.Lock()
_URL_LOCKS, _REFS = {}, {}


def acquire(p, dest):
    with _LOCK:
        lk = _URL_LOCKS.setdefault(p["url"], threading.Lock())
    with lk:
        return download(p["url"], p["bytes"], dest)


def release(p, dest):
    """One cell is done with this file; delete it when no cell still needs it."""
    with _LOCK:
        _REFS[p["url"]] = _REFS.get(p["url"], 1) - 1
        last = _REFS[p["url"]] <= 0
    fn = os.path.join(dest, os.path.basename(urllib.parse.urlparse(p["url"]).path))
    if last and not CFG["work"]["keep_downloads"] and os.path.exists(fn):
        os.remove(fn)


def download(url, size, dest):
    fn = os.path.join(dest, os.path.basename(urllib.parse.urlparse(url).path))
    if os.path.exists(fn):
        return fn
    for k in range(4):
        try:
            # check against the server's Content-Length: the TNM listing's sizeInBytes is stale for files USGS
            # re-saved later (2026-09-27: FEMAHQ_2018 tiles 12-15% smaller than listed, complete on S3)
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=300) as r, \
                    open(fn + ".part", "wb") as f:
                expect = int(r.headers.get("Content-Length") or 0)
                shutil.copyfileobj(r, f, 1 << 20)
            if expect and os.path.getsize(fn + ".part") != expect:
                raise IOError("got %d bytes, server said %d" % (os.path.getsize(fn + ".part"), expect))
            os.replace(fn + ".part", fn)
            return fn
        except Exception:  # noqa: BLE001
            if k == 3:
                raise
            time.sleep(15 * (k + 1))


def fallback_vrt(inv):
    d = os.path.join(WORK, "fallback")
    os.makedirs(d, exist_ok=True)
    files = [download(v["url"], v["bytes"], d) for v in inv["fallback"].values()]
    path = os.path.join(d, "fallback.vrt")
    gdal.BuildVRT(path, files)
    return path


def cell_dem(key, prods, fb_path):
    out = os.path.join(WORK, "dem3", key + ".tif")
    meta = out[:-4] + ".json"
    if os.path.exists(meta):
        with open(meta, encoding="utf-8") as f:
            return json.load(f)
    c = (int(key[1:4]), int(key[5:9]))
    g = cell_grid(c)
    t0, got_bytes = time.time(), 0
    dem, src, used, skipped = None, None, [], []
    dl = os.path.join(WORK, "downloads")
    for p in sorted(prods, key=flight_order, reverse=True):     # newest first
        if dem is not None and not np.isnan(dem).any():
            skipped.append(p["title"])
            release(p, dl)
            continue
        fn = acquire(p, dl)
        try:
            a = warp_arr(fn, g, CFG["dem"]["lidar_resampling"])
        except RuntimeError:                       # truncated file: fetch again once
            os.remove(fn)
            fn = download(p["url"], p["bytes"], dl)
            a = warp_arr(fn, g, CFG["dem"]["lidar_resampling"])
        got_bytes += os.path.getsize(fn)
        if dem is None:
            dem, src = np.full(a.shape, np.nan, np.float32), np.zeros(a.shape, np.uint8)
        fill = np.isnan(dem) & ~np.isnan(a)
        dem[fill], src[fill] = a[fill], 2
        used.append({"title": p["title"], "year": p["year"], "filled_pct": round(100 * float(fill.mean()), 2)})
        release(p, dl)
    fb = warp_arr(fb_path, g, CFG["source"]["fallback_resampling"])
    if dem is None:
        dem, src = np.full(fb.shape, np.nan, np.float32), np.zeros(fb.shape, np.uint8)
    fill = np.isnan(dem) & ~np.isnan(fb)
    dem[fill], src[fill] = fb[fill], 1
    lo, hi = CFG["dem"]["valid_range_m"]
    out_of_range = int(((dem < lo) | (dem > hi)).sum())
    os.makedirs(os.path.dirname(out), exist_ok=True)
    write_tif(out, np.where(np.isnan(dem), NODATA, dem).astype(np.float32), g, gdal.GDT_Float32, NODATA)
    write_tif(out[:-4] + "_src.tif", src, g, gdal.GDT_Byte, 0)       # 1 = 10 m fallback, 2 = lidar
    rec = {"cell": key, "lidar_pct": round(100 * float((src == 2).mean()), 2), "fallback_pct": round(100 * float((src == 1).mean()), 2),
           "nodata_pct": round(100 * float((src == 0).mean()), 3), "out_of_range_px": out_of_range, "flights_used": used,
           "flights_skipped": skipped, "bytes": got_bytes, "seconds": round(time.time() - t0),
           "elev_m": [round(float(np.nanmin(dem)), 1), round(float(np.nanmax(dem)), 1)] if not np.isnan(dem).all() else None}
    with open(meta, "w", encoding="utf-8") as f:
        json.dump(rec, f, indent=1)
    return rec


def dem():
    with open(os.path.join(WORK, "inventory.json"), encoding="utf-8") as f:
        inv = json.load(f)
    os.makedirs(os.path.join(WORK, "downloads"), exist_ok=True)
    fb = fallback_vrt(inv)
    for v in inv["cells"].values():             # how many cells use each lidar file
        for p in v:
            _REFS[p["url"]] = _REFS.get(p["url"], 0) + 1
    t0, recs, failed = time.time(), [], []
    keys = sorted(inv["cells"])
    with cf.ThreadPoolExecutor(CFG["work"]["download_workers"]) as ex:
        futs = {ex.submit(cell_dem, k, inv["cells"][k], fb): k for k in keys}
        for i, fu in enumerate(cf.as_completed(futs), 1):
            try:
                recs.append(fu.result())
            except Exception as e:  # noqa: BLE001
                failed.append((futs[fu], repr(e)))
                account("dem", "cell %s FAILED: %r" % (futs[fu], e))
            if i % 25 == 0:
                print("  %d/%d cells, %.0f min" % (i, len(keys), (time.time() - t0) / 60), flush=True)
    n = len(recs)
    lid = sum(r["lidar_pct"] for r in recs) / max(n, 1)
    fbp = sum(r["fallback_pct"] for r in recs) / max(n, 1)
    account("dem", "%d of %d cells built, %d failed; area from lidar %.1f%%, from 10 m fallback %.1f%%, no data %.3f%%; "
            "%d pixels outside %s m; %d flights skipped because newer ones covered the cell; %.1f GB downloaded; %.0f min"
            % (n, len(keys), len(failed), lid, fbp, sum(r["nodata_pct"] for r in recs) / max(n, 1),
               sum(r["out_of_range_px"] for r in recs), CFG["dem"]["valid_range_m"], sum(len(r["flights_skipped"]) for r in recs),
               sum(r["bytes"] for r in recs) / 1e9, (time.time() - t0) / 60))
    plt = plt_setup()
    from matplotlib.patches import Rectangle
    fig, ax = plt.subplots(figsize=(7, 10))
    for r in recs:
        c = (int(r["cell"][1:4]), int(r["cell"][5:9]))
        ax.add_patch(Rectangle((c[0] * 10, c[1] * 10), 10, 10, facecolor=plt.get_cmap("cividis")(r["lidar_pct"] / 100), edgecolor="white", lw=0.4))
    ax.autoscale_view()
    ax.set_aspect("equal")
    sm = plt.cm.ScalarMappable(cmap="cividis", norm=plt.Normalize(0, 100))
    fig.colorbar(sm, ax=ax, shrink=0.6, label="% of cell from lidar (rest from 10 m)")
    ax.set_xlabel("UTM 10N east (km)")
    ax.set_ylabel("UTM 10N north (km)")
    ax.set_title("3 m DEM source by cell")
    fig.savefig(os.path.join(DIAG, "2_dem_lidar_share.png"), dpi=130, bbox_inches="tight")


# ---------------------------------------------------------------- stage: slope
def cell_slope(key, vrt):
    out = os.path.join(WORK, "slope3", key + ".tif")
    meta = out[:-4] + ".json"
    if os.path.exists(meta):
        with open(meta, encoding="utf-8") as f:
            return json.load(f)
    c = (int(key[1:4]), int(key[5:9]))
    g = cell_grid(c)
    b = 3 * RES                                   # border from the neighbours so cell edges get true slopes
    a = warp_arr(vrt, (g[0] - b, g[1] - b, g[2] + b, g[3] + b), "near")      # same grid: an exact copy
    s = slope_deg(mem_ds(a, g[0] - b, g[3] + b, RES))[3:-3, 3:-3]
    cls = classify(s)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    write_tif(out, cls, g, gdal.GDT_Byte, None, color_table())
    ok = ~np.isnan(s)
    hist = np.histogram(s[ok], bins=np.arange(0, 91))[0].tolist()
    rec = {"cell": key, "valid_px": int(ok.sum()), "hist_deg": hist,
           "pct_ge": {str(t): round(100 * float((s[ok] >= t).mean()), 2) if ok.any() else None for t in (27, 30, 35, 45, 60)}}
    with open(meta, "w", encoding="utf-8") as f:
        json.dump(rec, f)
    return rec


def slope():
    dems = sorted(p for p in os.listdir(os.path.join(WORK, "dem3")) if re.fullmatch(r"e\d{3}n\d{4}\.tif", p))
    vrt = os.path.join(WORK, "dem3", "all.vrt")
    gdal.BuildVRT(vrt, [os.path.join(WORK, "dem3", p) for p in dems])
    t0, recs = time.time(), []
    with cf.ThreadPoolExecutor(6) as ex:
        recs = list(ex.map(lambda p: cell_slope(p[:-4], vrt), dems))
    hist = np.array([r["hist_deg"] for r in recs], dtype=np.int64).sum(axis=0)     # int64: ~2e9 pixels overflow int32 on Windows
    tot = hist.sum()
    shares = {t: 100 * hist[t:].sum() / tot for t in (27, 30, 35, 45, 60)}
    account("slope", "%d cells, %.2e valid pixels; share of the area >= 27/30/35/45/60 deg: %s; %.0f min"
            % (len(recs), tot, " / ".join("%.1f%%" % shares[t] for t in (27, 30, 35, 45, 60)), (time.time() - t0) / 60))
    plt = plt_setup()
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.bar(np.arange(90), hist / tot * 100, width=1, color="0.5")
    for lo, col in zip(BANDS, COLORS):
        ax.axvline(lo, color=[v / 255 for v in col], lw=1.5)
    ax.set_xlabel("slope (degrees)")
    ax.set_ylabel("% of area")
    ax.set_title("Slope distribution, WA Cascades at 3 m (lines: band edges)")
    fig.savefig(os.path.join(DIAG, "3_slope_histogram.png"), dpi=130, bbox_inches="tight")
    # overview: every cell decimated 30x (90 m) with nearest sampling, in band colours
    cls_vrt = gdal.BuildVRT("", [os.path.join(WORK, "slope3", p) for p in dems])
    ov = cls_vrt.GetRasterBand(1).ReadAsArray(buf_xsize=cls_vrt.RasterXSize // 30, buf_ysize=cls_vrt.RasterYSize // 30)
    rgb = np.ones(ov.shape + (3,))
    for i, col in enumerate(COLORS):
        rgb[ov == i + 1] = [v / 255 for v in col]
    rgb[ov == 255] = 0.85
    fig, ax = plt.subplots(figsize=(7, 11))
    gt = cls_vrt.GetGeoTransform()
    ax.imshow(rgb, extent=[gt[0] / 1000, (gt[0] + gt[1] * cls_vrt.RasterXSize) / 1000, (gt[3] + gt[5] * cls_vrt.RasterYSize) / 1000, gt[3] / 1000],
              interpolation="nearest")
    ax.set_xlabel("UTM 10N east (km)")
    ax.set_ylabel("UTM 10N north (km)")
    ax.set_title("Slope bands, 90 m overview (nearest sample)")
    fig.savefig(os.path.join(DIAG, "4_slope_overview.png"), dpi=150, bbox_inches="tight")


# ---------------------------------------------------------------- stage: tiles
def tiles():
    import osgeo_utils.gdal2tiles as g2t
    files = sorted(os.path.join(WORK, "slope3", p) for p in os.listdir(os.path.join(WORK, "slope3")) if p.endswith(".tif"))
    vrt = os.path.join(WORK, "slope3", "all.vrt")
    gdal.BuildVRT(vrt, files)
    # GeoTIFF palettes have no alpha, so the cell files carry "flatter than 27 = clear" as opaque black;
    # a VRT palette keeps alpha, so put the full table (clear for 0 and 255) back here (found 2026-09-28)
    ds = gdal.Open(vrt, gdal.GA_Update)
    ds.GetRasterBand(1).SetRasterColorTable(color_table())
    ds = None
    out = os.path.join(WORK, "tiles")
    if os.path.isdir(out):
        shutil.rmtree(out)                        # gdal2tiles would otherwise leave stale tiles that -x now skips
    rgba = os.path.join(WORK, "slope3", "all_rgba.vrt")
    gdal.Translate(rgba, vrt, format="VRT", rgbExpand="rgba")
    t = CFG["tiles"]
    t0 = time.time()
    args = ["gdal2tiles", "--xyz", "-z", "%d-%d" % (t["zoom_min"], t["zoom_max"]), "-r", t["resampling"], "-w", "none",
            "--processes=%d" % t["processes"], "-q"] + (["-x"] if t["exclude_empty"] else []) + [rgba, out]
    g2t.main(args)
    counts = {}
    for z in range(t["zoom_min"], t["zoom_max"] + 1):
        n = size = 0
        for d, _, fs in os.walk(os.path.join(out, str(z))):
            for f in fs:
                n += 1
                size += os.path.getsize(os.path.join(d, f))
        counts[z] = (n, size / 1e6)
    account("tiles", "zoom %s; %.0f MB total; %.0f min" % (", ".join("z%d %d tiles %.0f MB" % (z, n, mb) for z, (n, mb) in counts.items()),
                                                           sum(mb for _, mb in counts.values()), (time.time() - t0) / 60))


# ---------------------------------------------------------------- stage: check (after tiles)
def check():
    """Tiles against the UTM class raster: band agreement at random points, the best sub-pixel shift (a real
    georeferencing error would move the peak off zero), and flat ground (lake surfaces) must be clear."""
    from PIL import Image
    colours = {c: i + 1 for i, c in enumerate(COLORS)}
    z, cache = CFG["tiles"]["zoom_max"], {}

    def tile_px(lon, lat):
        n = 2 ** z
        return (lon + 180) / 360 * n * 256, (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n * 256

    def tile_class(gx, gy):
        p = os.path.join(WORK, "tiles", str(z), str(int(gx // 256)), "%d.png" % int(gy // 256))
        if p not in cache:
            cache[p] = np.asarray(Image.open(p).convert("RGBA")) if os.path.exists(p) else None
        a = cache[p]
        if a is None:
            return 0
        px = a[int(gy) % 256, int(gx) % 256]
        return 0 if px[3] == 0 else colours.get(tuple(int(v) for v in px[:3]), -1)

    src = gdal.Open(os.path.join(WORK, "slope3", "all.vrt"))
    band, gt = src.GetRasterBand(1), src.GetGeoTransform()
    rng = np.random.default_rng(1)
    w, s, e, n = CFG["area"]["bbox_lonlat"]
    pts = []
    while len(pts) < 2000:
        lon, lat = rng.uniform(w, e), rng.uniform(s, n)
        x, y, _ = TO_UTM.TransformPoint(lon, lat)
        v = int(band.ReadAsArray(int((x - gt[0]) / gt[1]), int((y - gt[3]) / gt[5]), 1, 1)[0, 0])
        pts.append((tile_px(lon, lat), 0 if v == 255 else v))
    grid = {(dx, dy): float(np.mean([tile_class(gx + dx, gy + dy) == v for (gx, gy), v in pts if v > 0]))
            for dx in range(-3, 4) for dy in range(-3, 4)}
    best = max(grid, key=grid.get)
    unmatched = sum(tile_class(gx, gy) == -1 for (gx, gy), _ in pts)
    allpts = np.mean([tile_class(gx, gy) == v for (gx, gy), v in pts])
    # lakes: lidar DEMs flatten water to one height, so search near each named lake for a 60 m box that varies
    # by under 0.5 m (open water, not shore) and require the tile to be clear there
    dem = gdal.Open(os.path.join(WORK, "dem3", "all.vrt"))
    dgt, dband = dem.GetGeoTransform(), dem.GetRasterBand(1)
    lakes = {"Colchuck Lake": (-120.8340, 47.4968), "Lake Chelan (Stehekin end)": (-120.6800, 48.2600),
             "Lake Wenatchee": (-120.80, 47.82), "Snow Lakes (Enchantments)": (-120.7700, 47.4920)}
    lake_txt = []
    for name, (lon, lat) in lakes.items():
        x, y, _ = TO_UTM.TransformPoint(lon, lat)
        c0, r0 = int((x - dgt[0]) / dgt[1]) - 333, int((y - dgt[3]) / dgt[5]) - 333      # 2 km search window
        elev = dband.ReadAsArray(c0, r0, 667, 667).astype(np.float64)
        spot = None
        for r in range(10, 657, 10):
            for c in range(10, 657, 10):
                box = elev[r - 10:r + 11, c - 10:c + 11]
                if box.min() > NODATA and box.max() - box.min() < 0.5:
                    spot = (r, c)
                    break
            if spot:
                break
        if not spot:
            lake_txt.append("%s: no flat water found" % name)
            continue
        ex, ny = dgt[0] + (c0 + spot[1] + 0.5) * dgt[1], dgt[3] + (r0 + spot[0] + 0.5) * dgt[5]
        lon2, lat2, _ = osr.CoordinateTransformation(UTM, LL).TransformPoint(ex, ny)          # LL uses lon, lat order
        gx, gy = tile_px(lon2, lat2)
        lake_txt.append("%s (water at %.1f m) %s" % (name, elev[spot], "clear" if tile_class(gx, gy) == 0 else "NOT CLEAR"))
    account("check", "2000 random points: tile band = raster band %.1f%% (steep points %.1f%% at zero shift); best shift %s tile px "
            "(%.1f%%); %d tile colours outside the palette; %s" % (100 * allpts, 100 * grid[(0, 0)], best, 100 * grid[best], unmatched,
                                                                   "; ".join(lake_txt)))


STAGES = {"selftest": selftest, "inventory": inventory, "dem": dem, "slope": slope, "tiles": tiles, "check": check}

if __name__ == "__main__":          # guard required: gdal2tiles workers re-import this file on Windows
    for name in sys.argv[1:] or ["selftest"]:
        STAGES[name]()
