"""
Web-mercator tile arithmetic and the Terrarium elevation encoding for the sun & shade tiles. Pure numpy (no GDAL),
so tests/test_terrain_tiles.py runs it anywhere. Definitions: METHOD.md "Inputs".
"""
import math

import numpy as np

RM = 6378137.0                  # web-mercator sphere radius (EPSG:3857)
ORIGIN = math.pi * RM           # half the world's width in mercator metres
TILE = 256
OFFSET = 32768.0                # Terrarium: elev = R*256 + G + B/256 - 32768


def res(z):
    """mercator metres per pixel at zoom z"""
    return 2 * ORIGIN / (TILE * 2 ** z)


def lonlat_to_merc(lon, lat):
    x = math.radians(lon) * RM
    y = RM * math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))
    return x, y


def merc_to_lonlat(x, y):
    return math.degrees(x / RM), math.degrees(2 * math.atan(math.exp(y / RM)) - math.pi / 2)


def tile_of(lon, lat, z):
    """(x, y) of the tile holding the point"""
    x, y = lonlat_to_merc(lon, lat)
    n = 2 ** z
    return int((x + ORIGIN) / (2 * ORIGIN) * n), int((ORIGIN - y) / (2 * ORIGIN) * n)


def tile_range(bbox, z):
    """(x0, y0, x1, y1) inclusive tile range covering bbox = (west, south, east, north) degrees"""
    w, s, e, n = bbox
    x0, y0 = tile_of(w, n, z)
    x1, y1 = tile_of(e, s, z)
    return x0, y0, x1, y1


def tile_bounds(z, x, y):
    """(xmin, ymin, xmax, ymax) mercator metres of tile (z, x, y)"""
    r = res(z) * TILE
    return -ORIGIN + x * r, ORIGIN - (y + 1) * r, -ORIGIN + (x + 1) * r, ORIGIN - y * r


def grow_bbox(bbox, km):
    """bbox grown by km on every side (at the box's mid latitude)"""
    w, s, e, n = bbox
    dlat = km / 111.32
    dlon = km / (111.32 * math.cos(math.radians((s + n) / 2)))
    return w - dlon, s - dlat, e + dlon, n + dlat


def encode_terrarium(elev, step=0.125):
    """float array (m, NaN = no data) -> uint8 (h, w, 3) Terrarium RGB, quantised to `step` metres; no data -> 0,0,0"""
    e = np.asarray(elev, np.float64)
    ok = np.isfinite(e)
    v = np.where(ok, np.round((e + OFFSET) / step) * step, 0.0)
    v = np.clip(v, 0, 65535.99)
    whole = np.floor(v)
    rgb = np.zeros(e.shape + (3,), np.uint8)
    rgb[..., 0] = (whole // 256).astype(np.uint8)
    rgb[..., 1] = (whole % 256).astype(np.uint8)
    rgb[..., 2] = np.round((v - whole) * 256).astype(np.uint8)
    rgb[~ok] = 0
    return rgb


def decode_terrarium(rgb):
    """uint8 (h, w, 3) -> float32 metres, NaN where R = G = B = 0"""
    a = np.asarray(rgb).astype(np.float64)
    e = a[..., 0] * 256 + a[..., 1] + a[..., 2] / 256 - OFFSET
    nod = (a[..., 0] == 0) & (a[..., 1] == 0) & (a[..., 2] == 0)
    return np.where(nod, np.nan, e).astype(np.float32)


def block_mean(a, f):
    """NaN-aware mean over f x f blocks (shape must divide); a block with no data stays NaN"""
    h, w = a.shape
    b = a.reshape(h // f, f, w // f, f)
    ok = np.isfinite(b)
    cnt = ok.sum(axis=(1, 3))
    tot = np.where(ok, b, 0).sum(axis=(1, 3), dtype=np.float64)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(cnt > 0, tot / np.maximum(cnt, 1), np.nan).astype(np.float32)


def margin_tiles(bbox):
    """USGS 1 arc-second tile names (NW corner, e.g. n47w121) covering bbox (west-hemisphere, north-latitude only)"""
    w, s, e, n = bbox
    out = []
    for lat in range(math.floor(s) + 1, math.ceil(n) + 1):
        for lon in range(math.ceil(-e), math.floor(-w) + 2):
            out.append("n%02dw%03d" % (lat, lon))
    return out
