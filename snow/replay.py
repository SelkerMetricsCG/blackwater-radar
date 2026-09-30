"""
Replay: re-run the surface-state model over a date range from the archive, offline, on a subset of the lattice,
without touching the live state. Used by the fit (snow/fit.py) and for looking at what a parameter change does.

  Subset(lat, meta, centres, k)      the cells in (2k+1)-cell windows around the given (row, col) centres, as 1-D
                                     arrays the model steps directly (day_forcing and step are shape-agnostic)
  forcing_for(day, subset, p, ...)   the day's forcing on the subset, cached on disk per (day, subset, wind thresholds)
  run(start, end, p, subset, ...)    -> {date: cls array over the subset}, stepping from a fresh state at `start`
                                     (start SPINUP days before the first date that matters)

  python -m snow.replay --start 2026-01-05 --end 2026-01-15 --lat 47.7 --lon -121.1 [--k 20]
"""
import argparse
import datetime as dt
import hashlib
import os

import numpy as np

import region
from snow import forcing, state, store

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "snow", "work", "replay")
SPINUP = 10
FORCING_KEYS = ("precip_in", "fzl_ft", "cloud_night", "td_night_c", "wind_night_ms", "wind_h", "wind_lee_h", "wind_wwd_h",
                "wind_h_wet", "wind_lee_h_wet", "wind_wwd_h_wet", "tmax_c", "tmin_c", "tmin_resid_c", "snotel_hn24_in", "site_elev_m", "depth_in", "solar_mj")


class Subset:
    def __init__(self, lat, meta, centres, k):
        h, w = lat["elev"].shape
        rows, cols = [], []
        for r, c in centres:
            rr, cc = np.mgrid[max(0, r - k):min(h, r + k + 1), max(0, c - k):min(w, c + k + 1)]
            rows.append(rr.ravel())
            cols.append(cc.ravel())
        rows, cols = np.concatenate(rows), np.concatenate(cols)
        flat = np.unique(rows * w + cols)
        self.rows, self.cols = flat // w, flat % w
        self.flat = flat
        self.shape = (h, w)
        self.meta = meta
        self.k = k
        self.lat = {key: (np.asarray(v)[:, self.rows, self.cols] if np.ndim(v) == 3 else np.asarray(v)[self.rows, self.cols]) for key, v in lat.items()}
        self.full = (lat["zone"], lat["band"])
        self.latlon = self._latlon()
        self.key = hashlib.sha1(flat.tobytes()).hexdigest()[:10]

    def _latlon(self):
        from pyproj import Transformer
        a, b, c, d, e, f = self.meta["transform"]
        x = c + a * (self.cols + 0.5)
        y = f + e * (self.rows + 0.5)
        tr = Transformer.from_crs(self.meta["crs"], "EPSG:4326", always_xy=True)
        lon, lat = tr.transform(x, y)
        return np.asarray(lat, np.float32), np.asarray(lon, np.float32)

    def index_of(self, r, c):
        """position in the subset arrays of lattice cell (r, c), or -1"""
        i = np.searchsorted(self.flat, r * self.shape[1] + c)
        return int(i) if i < len(self.flat) and self.flat[i] == r * self.shape[1] + c else -1

    def near(self, r, c, radius_cells):
        """mask over the subset of the cells within radius_cells of (r, c)"""
        return np.hypot(self.rows - r, self.cols - c) <= radius_cells


def forcing_for(day, subset, p, scfg, tz, log=print, cache_dir=CACHE, use_cache=True):
    os.makedirs(cache_dir, exist_ok=True)
    path = os.path.join(cache_dir, "%s_%s_w%g-%g.npz" % (day.isoformat(), subset.key, p["wind_mph_dry"], p["wind_mph_wet"]))
    if use_cache and os.path.exists(path):
        z = np.load(path)
        return {k: z[k] for k in FORCING_KEYS if k in z}
    f = state.day_forcing(day, subset.lat, subset.meta, subset.latlon, tz, scfg, p, log, locate=subset.full)
    if use_cache:
        np.savez_compressed(path, **{k: f[k] for k in FORCING_KEYS if k in f})
    return f


def run(start, end, p, subset, scfg=None, tz=None, log=print, cache_dir=CACHE, use_cache=True, keep_state=False):
    """step the model on the subset from `start` to `end` inclusive; -> {iso date: cls} (and states if keep_state)"""
    if scfg is None:
        _, scfg = state.load_params()
    if tz is None:
        tz = region.cfg().get("tz_offset_h", -8)
    out, states = {}, {}
    s = None
    day = start
    while day <= end:
        f = forcing_for(day, subset, p, scfg, tz, log, cache_dir, use_cache)
        if s is None:
            s = state.new_state(subset.lat["elev"].shape, f["depth_in"], p["min_depth_in"], subset.lat["elev"] != -32768)
        s = state.step(s, f, subset.lat, p, scfg)
        out[day.isoformat()] = s["cls"].copy()
        if keep_state:
            states[day.isoformat()] = {k: v.copy() for k, v in s.items()}
        day += dt.timedelta(days=1)
    return (out, states) if keep_state else out


def load_lattice(log=print):
    lp = store.fetch("static/lattice.npz", log)
    meta = store.read_json("static/lattice.json", log)
    if not lp or not meta:
        raise SystemExit("replay: no lattice (run the snow static workflow first)")
    lat = dict(np.load(lp))
    if "zone" not in lat:
        lat["zone"] = np.full(lat["elev"].shape, -1, np.int32)
    return lat, meta


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--lat", type=float, required=True)
    ap.add_argument("--lon", type=float, required=True)
    ap.add_argument("--k", type=int, default=20, help="window half-width in cells (20 = 2 km each way)")
    a = ap.parse_args()
    lat, meta = load_lattice()
    r, c = forcing.cell_of(meta, [a.lat], [a.lon])
    sub = Subset(lat, meta, [(int(r[0]), int(c[0]))], a.k)
    p, scfg = state.load_params()
    cls = run(dt.date.fromisoformat(a.start), dt.date.fromisoformat(a.end), p, sub, scfg)
    i = sub.index_of(int(r[0]), int(c[0]))
    for d, arr in cls.items():
        counts = np.bincount(arr[arr != 255], minlength=len(state.CLASSES))
        print(d, "at point:", state.CLASSES[arr[i]] if i >= 0 else "?", "| window:", ", ".join("%s %d%%" % (state.CLASSES[j], 100 * n // max(counts.sum(), 1)) for j, n in enumerate(counts) if n))
