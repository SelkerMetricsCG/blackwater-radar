"""
Terrain lattice for the snow-conditions model: one static grid of 100 m cells in UTM 10N over NWAC's area
(snow_config.yaml `lattice`), from the USGS 1 arc-second seamless DEM tiles on prd-tnm.s3.amazonaws.com.

Per cell: elevation (m), slope (deg, Horn on the 100 m grid), aspect (deg from N, -1 where flat), elevation
band (0 below / 1 near / 2 above treeline by `bands_ft`), and the avalanche zone id where the zone polygons
are available (avalanche.org map layer; -1 outside any zone). Canopy fraction (NLCD) is a later step.

Writes regions/<r>/snow/static/lattice.npz (int16/uint8 arrays) and lattice.json (grid geometry, tiles used,
config), and with --upload puts both in R2 under <r>/snow/static/. Downloads go to snow/work/ (gitignored).

  python -m snow.lattice                 build locally (20 tiles, ~1.1 GB download, a few minutes)
  python -m snow.lattice --tiles 2       the first two tiles only (a quick check)
  python -m snow.lattice --upload        build and push to R2 (the snow_static.yml workflow does this)
"""
import argparse
import datetime as dt
import json
import math
import os
import time
import urllib.request

import numpy as np

import region

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.path.join(ROOT, "snow", "snow_config.yaml")
WORK = os.path.join(ROOT, "snow", "work")
OUT_DIR = os.path.join(region.region_dir(), "snow", "static")
UA = "RadarTracker/1.0 (personal weather map; chris.gabrielli@gmail.com)"
ZONES_URL = "https://api.avalanche.org/v2/public/products/map-layer"


def load_config(path=CONFIG):
    import yaml
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)["lattice"]


def tile_names(bbox):
    """USGS 1 arc-second tile names covering bbox (west, south, east, north): nYYwXXX is the tile's NW corner"""
    w, s, e, n = bbox
    out = []
    for lat in range(math.floor(s), math.ceil(n)):
        for lon in range(math.floor(w), math.ceil(e)):
            out.append("n%02dw%03d" % (lat + 1, -lon))
    return out


def dest_grid(bbox, crs, cell):
    """(transform, height, width) of the UTM grid that covers bbox, edges on whole cells"""
    from pyproj import Transformer
    from rasterio.transform import from_origin
    tr = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    w, s, e, n = bbox
    lons = np.linspace(w, e, 50)
    lats = np.linspace(s, n, 50)
    xs, ys = [], []
    for lon in lons:
        for lat in (s, n):
            x, y = tr.transform(lon, lat)
            xs.append(x)
            ys.append(y)
    for lat in lats:
        for lon in (w, e):
            x, y = tr.transform(lon, lat)
            xs.append(x)
            ys.append(y)
    x0, x1 = math.floor(min(xs) / cell) * cell, math.ceil(max(xs) / cell) * cell
    y0, y1 = math.floor(min(ys) / cell) * cell, math.ceil(max(ys) / cell) * cell
    return from_origin(x0, y1, cell, cell), int((y1 - y0) / cell), int((x1 - x0) / cell)


def fetch_tile(url, dest, log):
    if os.path.exists(dest) and os.path.getsize(dest) > 1_000_000:
        return True
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=300) as r, open(dest + ".tmp", "wb") as f:
            while True:
                b = r.read(1 << 20)
                if not b:
                    break
                f.write(b)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            log("lattice: %s not available (404): ocean or outside coverage" % os.path.basename(dest))
            return False
        raise
    os.replace(dest + ".tmp", dest)
    return True


def mosaic(cfg, tiles, log):
    """elevation (m, float32, NaN where nothing) on the destination grid, plus (transform, tiles used)"""
    import rasterio
    from rasterio.warp import Resampling, reproject
    transform, h, w = dest_grid(cfg["bbox_lonlat"], cfg["crs"], cfg["cell_m"])
    dest = np.full((h, w), np.nan, np.float32)
    used = []
    os.makedirs(WORK, exist_ok=True)
    for t in tiles:
        path = os.path.join(WORK, "USGS_1_%s.tif" % t)
        t0 = time.time()
        if not fetch_tile(cfg["dem_url"].format(tile=t), path, log):
            continue
        with rasterio.open(path) as src:
            band = src.read(1).astype(np.float32)
            nod = src.nodata
            if nod is not None:
                band[band == nod] = np.nan
            band[(band < -100) | (band > 4500)] = np.nan
            reproject(band, dest, src_transform=src.transform, src_crs=src.crs, src_nodata=np.nan,
                      dst_transform=transform, dst_crs=cfg["crs"], dst_nodata=np.nan,
                      resampling=Resampling.average, init_dest_nodata=False)
        used.append(t)
        log("lattice: %s in %.0f s (%.1f MB)" % (t, time.time() - t0, os.path.getsize(path) / 1e6))
        try:
            os.remove(path)          # keep the runner's disk small; a rebuild re-downloads
        except OSError:
            pass
    return dest, transform, used


def slope_aspect(z, cell, flat_below_deg):
    """Horn slope (deg) and aspect (deg clockwise from N, -1 where flat or unknown), rows north to south"""
    zp = np.pad(z, 1, mode="edge")
    a, b, c = zp[:-2, :-2], zp[:-2, 1:-1], zp[:-2, 2:]
    d, f = zp[1:-1, :-2], zp[1:-1, 2:]
    g, h, i = zp[2:, :-2], zp[2:, 1:-1], zp[2:, 2:]
    dzdx = ((c + 2 * f + i) - (a + 2 * d + g)) / (8.0 * cell)          # eastward gradient
    dzdy = ((a + 2 * b + c) - (g + 2 * h + i)) / (8.0 * cell)          # northward gradient
    slope = np.degrees(np.arctan(np.hypot(dzdx, dzdy)))
    aspect = np.degrees(np.arctan2(-dzdx, -dzdy)) % 360.0             # direction of steepest descent
    aspect = np.where(slope < flat_below_deg, -1.0, aspect)
    bad = np.isnan(slope) | np.isnan(z)          # Horn ignores the centre cell, so mask it here
    return np.where(bad, np.nan, slope), np.where(bad, -1.0, aspect)


def zones_from_geojson(g, transform, out_shape, crs):
    """(zone id per cell int32, -1 outside; {id: {name, center_id}}) from the avalanche.org map layer GeoJSON"""
    from pyproj import Transformer
    from rasterio.features import rasterize
    from shapely.geometry import shape as shp_shape
    from shapely.ops import transform as shp_transform
    tr = Transformer.from_crs("EPSG:4326", crs, always_xy=True).transform
    shapes, names = [], {}
    for f in g.get("features", []):
        p = f.get("properties") or {}
        zid = f.get("id", p.get("id"))
        if zid is None or not f.get("geometry"):
            continue
        try:
            shapes.append((shp_transform(tr, shp_shape(f["geometry"])), int(zid)))
        except Exception:  # noqa: BLE001
            continue
        names[int(zid)] = {"name": p.get("name"), "center_id": p.get("center_id")}
    if not shapes:
        return None, None
    z = rasterize(shapes, out_shape=tuple(out_shape), transform=transform, fill=-1, dtype="int32")
    return z, names


def zones_raster(transform, out_shape, crs, log):
    """avalanche zone id per cell from the avalanche.org map layer, -1 outside; None when it cannot be fetched"""
    try:
        req = urllib.request.Request(ZONES_URL, headers={"User-Agent": UA, "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            g = json.load(r)
    except Exception as e:  # noqa: BLE001
        log("lattice: zones not fetched (%r); zone ids left out" % e)
        return None, None
    return zones_from_geojson(g, transform, out_shape, crs)


def build(tiles_limit=None, log=print, cfg=None, zones=True):
    cfg = cfg or load_config()
    tiles = tile_names(cfg["bbox_lonlat"])
    if tiles_limit:
        tiles = tiles[:tiles_limit]
    t0 = time.time()
    z, transform, used = mosaic(cfg, tiles, log)
    slope, aspect = slope_aspect(z, cfg["cell_m"], cfg["flat_below_deg"])
    ft = z * 3.28084
    band = np.digitize(np.nan_to_num(ft, nan=-1), cfg["bands_ft"]).astype(np.uint8)
    band[np.isnan(z)] = 255
    out = {"elev": np.where(np.isnan(z), -32768, np.round(z)).astype(np.int16),
           "slope": np.where(np.isnan(slope), 255, np.round(slope)).astype(np.uint8),
           "aspect": np.round(aspect).astype(np.int16), "band": band}
    meta = {"built_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M"), "config": cfg,
            "crs": cfg["crs"], "cell_m": cfg["cell_m"], "shape": list(z.shape), "transform": list(transform)[:6],
            "tiles": used, "nodata": {"elev": -32768, "slope": 255, "aspect": -1, "band": 255, "zone": -1},
            "cells_with_data": int(np.isfinite(z).sum())}
    if zones:
        zr, names = zones_raster(transform, z.shape, cfg["crs"], log)
        if zr is not None:
            out["zone"] = zr.astype(np.int32)
            meta["zones"] = {str(k): v for k, v in names.items()}
    os.makedirs(OUT_DIR, exist_ok=True)
    npz = os.path.join(OUT_DIR, "lattice.npz")
    np.savez_compressed(npz + ".tmp.npz", **out)
    os.replace(npz + ".tmp.npz", npz)
    with open(os.path.join(OUT_DIR, "lattice.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=1)
    log("lattice: %dx%d cells, %d with data, %d tiles, %.0f s, %.1f MB"
        % (z.shape[0], z.shape[1], meta["cells_with_data"], len(used), time.time() - t0, os.path.getsize(npz) / 1e6))
    return meta


def upload(log=print):
    import r2sync
    env = r2sync.load_env()
    if env is None:
        raise SystemExit("no R2 credentials")
    s3 = r2sync.client(env)
    for fn in ("lattice.npz", "lattice.json"):
        r2sync.put(s3, env["R2_BUCKET"], region.prefix() + "snow/static/" + fn, os.path.join(OUT_DIR, fn), "public, max-age=3600")
        log("lattice: uploaded %s" % fn)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--tiles", type=int, default=None, help="only the first N tiles (a quick check)")
    ap.add_argument("--upload", action="store_true")
    ap.add_argument("--no-zones", action="store_true")
    a = ap.parse_args()
    build(a.tiles, zones=not a.no_zones)
    if a.upload:
        upload()
