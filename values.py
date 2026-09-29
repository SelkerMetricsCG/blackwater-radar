"""
Compact value grids for click-anywhere sampling in the map.

write_grid(name, array) downsamples a (H, W) array in map-window pixel space to
256x256 (block mean), scales to integer hundredths, and writes
data/values/<name>.js -> window.VALUES["<name>"] = {w, h, scale, unit, nodata, data: "v,v,v,..."}
The map loads a grid on demand and samples it by pixel position.
"""
import json
import os

import numpy as np

import region

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(region.data_dir(), "values")
N = 256


def write_grid(name, arr, unit="in", scale=0.01, nodata=None, out_dir=None):
    out_dir = out_dir or OUT_DIR
    a = np.asarray(arr, dtype=np.float32)
    h, w = a.shape
    fy, fx = h // N, w // N
    if fy < 1 or fx < 1:
        raise ValueError("grid smaller than %d px" % N)
    a = a[:fy * N, :fx * N].reshape(N, fy, N, fx)
    with np.errstate(invalid="ignore"):
        m = np.nanmean(a, axis=(1, 3))
    q = np.where(np.isnan(m), -1, np.round(m / scale)).astype(np.int64)
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, name + ".js")
    body = ",".join(str(int(v)) for v in q.ravel())
    payload = {"w": N, "h": N, "scale": scale, "unit": unit, "nodata": -1}
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        f.write('window.VALUES=window.VALUES||{};window.VALUES[%s]=%s;window.VALUES[%s].data="%s";\n'
                % (json.dumps(name), json.dumps(payload), json.dumps(name), body))
    os.replace(path + ".tmp", path)
    return path


def read_grid(name, out_dir=None):
    """the grid write_grid wrote: (payload dict, (N, N) int64 array with -1 nodata), or None when missing"""
    import re
    path = os.path.join(out_dir or OUT_DIR, name + ".js")
    try:
        with open(path, encoding="utf-8") as f:
            s = f.read()
    except OSError:
        return None
    m = re.search(r'=(\{[^;]*\});window\.VALUES\[[^\]]+\]\.data="([^"]*)"', s)
    if not m:
        return None
    payload = json.loads(m.group(1))
    q = np.array(m.group(2).split(","), dtype=np.int64) if m.group(2) else np.zeros(0, np.int64)
    if q.size != payload["w"] * payload["h"]:
        return None
    return payload, q.reshape(payload["h"], payload["w"])
