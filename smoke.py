"""
Smoke forecast: NOAA HRRR near-surface smoke (MASSDEN, 8 m above ground), the map's "Smoke & fires" section, phase 3.

In the hourly job, for the region in REGION, whenever a newer complete 48 h run (00/06/12/18Z) is posted:
  frames/smoke/<slot><hh>.webp   smoke categories for forecast hours 1..48 (lossless, 640 px)
  data/values/smoke_<slot>.js    window.VALUES["smoke_<slot>"]: 128 x 128 cells x 48 hours, ug/m3, for click-anywhere
  data/smoke.js                  window.SMOKE = {run_utc, run_t, updated, updated_t, slot, floor, coverage, hours, series, edge}
  data/smoke_cache.json          private (cloud.py STATE_FILES): the run on the map, its slot, when it was built
A new run goes into the slot ("a" or "b") the page is not using, and smoke.js switches last, so the page never pairs one
run's image with another run's time. Hours with no new run write nothing.

Source: AWS open data (noaa-hrrr-bdp-pds), one byte-range request per hour found through the .idx file.
Requests reuse airquality's User-Agent, timeout, runner cache and hung-host rule.
Design: docs/superpowers/specs/2026-09-28-hrrr-smoke-layer-design.md; sources: smoke_research/sources_notes.md.

Run standalone (writes local files, uploads nothing):  python smoke.py
"""
import json
import math
import warnings

import numpy as np

import region

FLOOR = 2.0                                  # ug/m3: transparent below (judgment call, spec decision 4)
EDGES = (FLOOR, 9.1, 35.5, 55.5, 125.5, 225.5)   # light smoke, then EPA's 2024 PM2.5 AQI category starts
LIGHT = (150, 140, 128, 110)                 # light smoke (still AQI Good): translucent warm grey (judgment call)
AQ_COLORS = ((0, 228, 0), (255, 255, 0), (255, 126, 0), (255, 0, 0), (143, 63, 151), (126, 0, 35))   # airquality.AQ_COLORS
SIZE = 640                                   # frame and computation size: half the 1280 px window, like freezing.py
CELLS = 128                                  # value cells per side for click-anywhere (~9-12 km)
EDGE_MARGIN = 0.3                            # degrees: the model-edge line runs this far past the window


# ---------- the .idx file ----------
def idx_range(text, record):
    """byte range (start, end) of the first message whose .idx line contains `record`; end None for the last message"""
    lines = [ln.split(":") for ln in text.splitlines() if ln.count(":") >= 2]
    for k, parts in enumerate(lines):
        if record in ":" + ":".join(parts[3:]):
            start = int(parts[1])
            for nxt in lines[k + 1:]:
                if int(nxt[1]) > start:
                    return start, int(nxt[1]) - 1
            return start, None
    return None


# ---------- the model's Lambert conformal grid (tangent cone, spherical earth) ----------
def _cone(grid):
    phi0 = math.radians(grid["latin"])
    n = math.sin(phi0)
    return n, grid["radius"] * math.cos(phi0) * math.tan(math.pi / 4 + phi0 / 2) ** n / n


def _xy(grid, lat, lon):
    n, rf = _cone(grid)
    dl = np.radians((np.asarray(lon, dtype=np.float64) - grid["lov"] + 180.0) % 360.0 - 180.0)
    rho = rf / np.tan(np.pi / 4 + np.radians(np.asarray(lat, dtype=np.float64)) / 2) ** n
    return rho * np.sin(n * dl), -rho * np.cos(n * dl)


def lcc_ij(grid, lat, lon):
    """latitude/longitude (degrees) -> fractional grid indices (i east, j north) of the first point's grid"""
    x0, y0 = _xy(grid, grid["lat1"], grid["lon1"])
    x, y = _xy(grid, lat, lon)
    return (x - x0) / grid["dx"], (y - y0) / grid["dx"]


def lcc_latlon(grid, fi, fj):
    """fractional grid indices -> latitude, longitude (degrees, longitude in -180..180)"""
    n, rf = _cone(grid)
    x0, y0 = _xy(grid, grid["lat1"], grid["lon1"])
    x = x0 + np.asarray(fi, dtype=np.float64) * grid["dx"]
    y = y0 + np.asarray(fj, dtype=np.float64) * grid["dx"]
    rho = np.sign(n) * np.hypot(x, y)
    lat = np.degrees(2 * np.arctan((rf / rho) ** (1 / n)) - np.pi / 2)
    lon = (grid["lov"] + np.degrees(np.arctan2(x, -y)) / n + 180.0) % 360.0 - 180.0
    return lat, lon


# ---------- the region window (5 x 5 zoom-7 Web Mercator tiles) ----------
def window_latlon(size=SIZE):
    """pixel-centre latitudes (top to bottom) and longitudes (left to right) of the window at size x size px"""
    z, x0, x1, y0, y1 = region.window()
    n = 2 ** z
    ys = (np.arange(size) + 0.5) / size * (y1 - y0 + 1) + y0
    xs = (np.arange(size) + 0.5) / size * (x1 - x0 + 1) + x0
    return np.degrees(np.arctan(np.sinh(np.pi - 2 * np.pi * ys / n))), xs / n * 360.0 - 180.0


def resample(field, grid, size=SIZE):
    """model field [nj, ni] -> window [size, size], bilinear; NaN outside the model's grid"""
    from scipy.ndimage import map_coordinates
    lat, lon = window_latlon(size)
    la, lo = np.meshgrid(lat, lon, indexing="ij")
    fi, fj = lcc_ij(grid, la, lo)
    out = map_coordinates(np.asarray(field, dtype=np.float32), [fj.ravel(), fi.ravel()], order=1, mode="constant",
                          cval=np.nan, prefilter=False)
    outside = (fi < 0) | (fj < 0) | (fi > grid["ni"] - 1) | (fj > grid["nj"] - 1)
    return np.where(outside.ravel(), np.nan, out).reshape(size, size).astype(np.float32)


# ---------- frames ----------
def category(ug):
    """ug/m3 -> -1 transparent (below the floor, or no value), 0 light smoke, 1..5 Moderate..Hazardous"""
    a = np.asarray(ug, dtype=np.float64)
    k = np.digitize(np.nan_to_num(a, nan=-1.0), EDGES) - 1
    return np.where(np.isnan(a), -1, k)


def frame_rgba(ug):
    table = np.array([(0, 0, 0, 0), LIGHT] + [c + (255,) for c in AQ_COLORS[1:]], dtype=np.uint8)
    return table[category(ug) + 1]


# ---------- click-anywhere values ----------
def series_blocks(ug, n=CELLS):
    """window field [size, size] -> [n, n] block means as integers (ug/m3, half up); -1 where the block is all NaN"""
    a = np.asarray(ug, dtype=np.float64)
    f = a.shape[0] // n
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)       # all-NaN blocks (outside the model)
        m = np.nanmean(a[:f * n, :f * n].reshape(n, f, n, f), axis=(1, 3))
    return np.where(np.isnan(m), -1, np.floor(np.nan_to_num(m) + 0.5)).astype(np.int64)


def series_js(name, blocks, t0, unit="µg/m³"):
    """hour-major value series -> the window.VALUES script the page loads for click-anywhere"""
    h, w = blocks[0].shape
    head = {"w": int(w), "h": int(h), "n": len(blocks), "t0": int(t0), "dt": 3600, "scale": 1, "unit": unit, "nodata": -1}
    body = ",".join(str(int(v)) for b in blocks for v in np.asarray(b).ravel())
    key = json.dumps(name)
    return ('window.VALUES=window.VALUES||{};window.VALUES[%s]=%s;window.VALUES[%s].data="%s";\n'
            % (key, json.dumps(head, ensure_ascii=False, separators=(",", ":")), key, body))


# ---------- the model's edge inside the window ----------
def edge_segments(grid, step=10):
    """the model grid's boundary as [[lat, lon], ...] runs inside the window (+ EDGE_MARGIN); [] if it misses it"""
    lat0, lat1, lon0, lon1 = region.bbox()
    ni, nj = grid["ni"] - 1, grid["nj"] - 1
    si, sj = np.arange(0, ni + 1, step, dtype=float), np.arange(0, nj + 1, step, dtype=float)
    sides = [(si, np.zeros_like(si)), (np.full_like(sj, ni), sj), (si[::-1], np.full_like(si, nj)), (np.zeros_like(sj), sj[::-1])]
    segs = []
    for fi, fj in sides:
        la, lo = lcc_latlon(grid, fi, fj)
        inside = (la >= lat0 - EDGE_MARGIN) & (la <= lat1 + EDGE_MARGIN) & (lo >= lon0 - EDGE_MARGIN) & (lo <= lon1 + EDGE_MARGIN)
        run = []
        for ok, a, b in zip(inside, la, lo):
            if ok:
                run.append([round(float(a), 3), round(float(b), 3)])
            elif run:
                segs.append(run)
                run = []
        if run:
            segs.append(run)
    return [s for s in segs if len(s) >= 2]
