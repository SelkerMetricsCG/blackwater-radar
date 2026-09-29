"""
Forcing: puts the archive's inputs onto the terrain lattice for one day.

The archive's grids (`snow/archive.py`) are in the map window's Web Mercator pixel space: an N x N grid over
region.window(), the same space as the click-anywhere grids. The lattice (`snow/lattice.py`) is UTM. This module
maps between them and reduces station data to zone x band values.

  lattice_latlon(meta)                    -> (lat, lon) float32 arrays for every lattice cell
  window_pixel(lat, lon, n)               -> fractional (px, py) of a lat/lon in the n x n window grid
  sample(gridobj, lat, lon)               -> values (scale applied, NaN nodata) at lat/lon from an archive grid
  band_values(points, zone, band, key)    -> {(zone_id, band): mean of key over the points inside} from station records
                                             located on the lattice (a point's zone and band come from its cell)
"""
import math

import numpy as np

import region


def lattice_latlon(meta):
    """lat, lon (float32, lattice shape) of cell centres, from lattice.json's transform and crs"""
    from pyproj import Transformer
    a, b, c, d, e, f = meta["transform"]
    h, w = meta["shape"]
    xs = c + a * (np.arange(w) + 0.5)
    ys = f + e * (np.arange(h) + 0.5)
    X, Y = np.meshgrid(xs, ys)
    tr = Transformer.from_crs(meta["crs"], "EPSG:4326", always_xy=True)
    lon, lat = tr.transform(X.ravel(), Y.ravel())
    return np.asarray(lat, np.float32).reshape(h, w), np.asarray(lon, np.float32).reshape(h, w)


def window_pixel(lat, lon, n):
    """fractional pixel (px, py) in the region window's n x n grid; outside the window falls outside 0..n"""
    Z, X0, X1, Y0, Y1 = region.window()
    lat = np.radians(np.asarray(lat, float))
    lon = np.asarray(lon, float)
    tx = (lon + 180.0) / 360.0 * 2 ** Z
    ty = (1 - np.log(np.tan(lat) + 1 / np.cos(lat)) / math.pi) / 2 * 2 ** Z
    px = (tx - X0) / (X1 - X0 + 1) * n
    py = (ty - Y0) / (Y1 - Y0 + 1) * n
    return px, py


def sample(gridobj, lat, lon):
    """nearest-cell values of an archive grid ({n, scale, unit, data}) at lat/lon; NaN outside or nodata"""
    n = int(gridobj["n"])
    q = np.asarray(gridobj["data"], np.int64).reshape(n, n)
    px, py = window_pixel(lat, lon, n)
    ix, iy = np.floor(px).astype(int), np.floor(py).astype(int)
    inside = (ix >= 0) & (ix < n) & (iy >= 0) & (iy < n)
    v = np.full(np.shape(px), np.nan, np.float64)
    vals = q[np.clip(iy, 0, n - 1), np.clip(ix, 0, n - 1)]
    ok = inside & (vals >= 0)
    v[ok] = vals[ok] * float(gridobj.get("scale") or 1.0)
    return v


def cell_of(meta, lat, lon):
    """(row, col) of lat/lon points on the lattice, or (-1, -1) outside it"""
    from pyproj import Transformer
    a, b, c, d, e, f = meta["transform"]
    h, w = meta["shape"]
    tr = Transformer.from_crs("EPSG:4326", meta["crs"], always_xy=True)
    x, y = tr.transform(np.asarray(lon, float), np.asarray(lat, float))
    col = np.floor((np.asarray(x) - c) / a).astype(int)
    row = np.floor((np.asarray(y) - f) / e).astype(int)
    ok = (row >= 0) & (row < h) & (col >= 0) & (col < w)
    return np.where(ok, row, -1), np.where(ok, col, -1)


def band_values(points, zone, band, key, meta):
    """points: records with lat, lon and `key` (a number). zone/band: lattice arrays. -> {(zone_id, band): mean}"""
    pts = [p for p in points if p.get(key) is not None and p.get("lat") is not None and p.get("lon") is not None]
    if not pts:
        return {}
    r, c = cell_of(meta, [p["lat"] for p in pts], [p["lon"] for p in pts])
    acc = {}
    for p, ri, ci in zip(pts, r, c):
        if ri < 0:
            continue
        z, b = int(zone[ri, ci]), int(band[ri, ci])
        if z < 0 or b == 255:
            continue
        acc.setdefault((z, b), []).append(float(p[key]))
    return {k: float(np.mean(v)) for k, v in acc.items()}
