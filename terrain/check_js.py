"""
Check 3 and 4 harness, page side: run map.html's own sun & shade walk (the `// BEGIN sunShade` block) under node on
grids decoded from the elevation tiles, for the cases in check_cases.json. Output: work/check/js_results.json
  {place: {date: {"windows": [[first, last], ...], "hours": h, "flat": [a, b],
                  "patch": {"540": "0110-...", ...}}}}      patch string: 1 sun, 0 shade, - no terrain (row-major)
Run from radar/ with the main (Anaconda) Python:  python terrain/check_js.py [--tiles DIR]
"""
import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import tilemath as tm  # noqa: E402

RUNNER = r"""
const fs = require('fs');
const meta = JSON.parse(fs.readFileSync(process.argv[2], 'utf8')), out = {};
function load(g) { const b = fs.readFileSync(g.file); return Object.assign({}, g, { data: new Float32Array(b.buffer, b.byteOffset, b.length / 4) }); }
for (const pl of meta.places) {
  const near = load(pl.near), far = load(pl.far), zmax = Math.max(near.zmax, far.zmax), res = out[pl.name] = {};
  for (const date of meta.dates) {
    const r = sunWindows(near, far, pl.lat, pl.lon, date, zmax);
    r.patch = {};
    for (const t of meta.times) {
      const S = sunTerms(sunPacificMs(date, t));
      r.patch[t] = pl.points.map(([lat, lon]) => { const [X, Y] = sunMerc(lat, lon), v = sunLit(near, far, X, Y, sunAt(lat, lon, S), zmax); return v === null ? '-' : v ? '1' : '0'; }).join('');
    }
    res[date] = r;
  }
}
process.stdout.write(JSON.stringify(out));
"""


def patch_points(pl, patch):
    n, sp = patch["n"], patch["spacing_m"]
    pts = []
    for j in range(n):
        for i in range(n):
            north, east = (n // 2 - j) * sp, (i - n // 2) * sp
            pts.append([pl["lat"] + north / 111320, pl["lon"] + east / (111320 * math.cos(math.radians(pl["lat"])))])
    return pts


def grid(tiles, z, lat, lon, half_km, path):
    """tiles of zoom z covering +-half_km (ground) around the point, as the page's sunPlan / sunGrid do"""
    X, Y = tm.lonlat_to_merc(lon, lat)
    h = half_km * 1000 * math.cosh(Y / tm.RM)
    T = tm.TILE * tm.res(z)
    tx0, tx1 = int((X - h + tm.ORIGIN) // T), int((X + h + tm.ORIGIN) // T)
    ty0, ty1 = int((tm.ORIGIN - (Y + h)) // T), int((tm.ORIGIN - (Y - h)) // T)
    w, hh = (tx1 - tx0 + 1) * 256, (ty1 - ty0 + 1) * 256
    a = np.full((hh, w), -32768.0, np.float32)
    for ty in range(ty0, ty1 + 1):
        for tx in range(tx0, tx1 + 1):
            p = os.path.join(tiles, str(z), str(tx), "%d.png" % ty)
            if os.path.exists(p):
                rgb = np.asarray(Image.open(p).convert("RGB")).astype(np.float64)
                a[(ty - ty0) * 256:(ty - ty0 + 1) * 256, (tx - tx0) * 256:(tx - tx0 + 1) * 256] = rgb[..., 0] * 256 + rgb[..., 1] + rgb[..., 2] / 256 - 32768
    a.tofile(path)
    return {"file": path, "z": z, "res": tm.res(z), "X0": -tm.ORIGIN + tx0 * T, "Y0": tm.ORIGIN - ty0 * T, "w": w, "h": hh,
            "zmax": float(a.max())}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tiles", default=os.path.join(HERE, "work", "tiles"))
    a = ap.parse_args()
    with open(os.path.join(HERE, "check_cases.json"), encoding="utf-8") as f:
        cases = json.load(f)
    html = open(os.path.join(ROOT, "map.html"), encoding="utf-8").read()
    block = re.search(r"// BEGIN sunShade[^\n]*\n(.*?)// END sunShade", html, re.S).group(1)
    tmp = tempfile.mkdtemp()
    try:
        meta = {"dates": cases["dates"], "times": cases["patch_times_min"], "places": []}
        for k, pl in enumerate(cases["places"]):
            meta["places"].append({"name": pl["name"], "lat": pl["lat"], "lon": pl["lon"], "points": patch_points(pl, cases["patch"]),
                                   "near": grid(a.tiles, 14, pl["lat"], pl["lon"], 3.5, os.path.join(tmp, "n%d.bin" % k)),
                                   "far": grid(a.tiles, 10, pl["lat"], pl["lon"], 27, os.path.join(tmp, "f%d.bin" % k))})
        mp = os.path.join(tmp, "meta.json")
        json.dump(meta, open(mp, "w"))
        js = os.path.join(tmp, "run.js")
        open(js, "w", encoding="utf-8").write(block + RUNNER)
        r = subprocess.run(["node", js, mp], capture_output=True, text=True, env=dict(os.environ, TZ="UTC"))
        if r.returncode:
            raise SystemExit(r.stderr)
        out = os.path.join(HERE, "work", "check")
        os.makedirs(out, exist_ok=True)
        with open(os.path.join(out, "js_results.json"), "w", encoding="utf-8") as f:
            f.write(r.stdout)
        print("wrote", os.path.join(out, "js_results.json"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
