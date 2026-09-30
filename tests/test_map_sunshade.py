"""Sun & shade layer in map.html (the `// BEGIN sunShade` block), run under node; skipped where node is missing.

Known answers (terrain/METHOD.md): sun position against astropy (an independent ephemeris; values computed
2026-09-30 with astropy 7.0, geometric altitude, pressure 0) and against snow/solar.py; NOAA refraction by hand;
Pacific times whatever the device's zone; synthetic walls, slopes and plains with shadows computable by hand.
"""
import datetime as dt
import json
import math
import os
import re
import shutil
import subprocess

import pytest
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node not installed")

# name, lat, lon, UTC instant, astropy geometric altitude (deg), azimuth (deg)
ASTROPY = [
    ("Colchuck", 47.4960, -120.8345, "2026-12-21T20:00:00", 19.063, 179.620),
    ("Colchuck", 47.4960, -120.8345, "2026-03-20T16:00:00", 18.078, 110.834),
    ("Colchuck", 47.4960, -120.8345, "2026-06-21T13:00:00", 6.852, 62.498),
    ("Seattle", 47.6100, -122.3300, "2026-09-30T22:00:00", 32.827, 216.721),
    ("Baker", 48.7768, -121.8145, "2027-01-15T17:30:00", 10.891, 140.823),
    ("Colchuck low", 47.4960, -120.8345, "2026-12-21T16:10:00", 2.086, 128.967),
    ("Rainier", 46.8528, -121.7604, "2026-11-01T01:30:00", -6.990, 256.401),
]

# synthetic terrain for the walk: grids like the page's (zoom 14 near, zoom 10 far) around a point at 47.5 N
TERRAIN_JS = r"""
const P = { lat: 47.5, lon: -120.8 };
const [PX, PY] = sunMerc(P.lat, P.lon), SC = Math.cosh(PY / SUN_RM);
function mkGrid(z, halfKm, f) {          // f(east m, north m) -> elevation, sampled at pixel centres
  const res = sunTileRes(z), n = Math.ceil(halfKm * 1000 * SC / res) * 2, w = n, h = n;
  const X0 = PX - n / 2 * res, Y0 = PY + n / 2 * res, data = new Float32Array(w * h);
  let zmax = -Infinity;
  for (let j = 0; j < h; j++) for (let i = 0; i < w; i++) {
    const v = f((X0 + (i + 0.5) * res - PX) / SC, (Y0 - (j + 0.5) * res - PY) / SC);
    data[j * w + i] = v; if (v > zmax) zmax = v;
  }
  return { z, res, X0, Y0, w, h, data, zmax };
}
function world(f) { const near = mkGrid(14, 3, f), far = mkGrid(10, 40, f); return { near, far, zmax: Math.max(near.zmax, far.zmax) }; }
function lit(W, el, az) { return sunLit(W.near, W.far, PX, PY, { el, az }, W.zmax); }
function threshold(W, az, lo, hi) {      // the sun elevation where the point turns from shade to sun
  for (let k = 0; k < 40; k++) { const m = (lo + hi) / 2; if (lit(W, m, az)) hi = m; else lo = m; }
  return (lo + hi) / 2;
}
"""


def page():
    with open(os.path.join(ROOT, "map.html"), encoding="utf-8") as f:
        return f.read()


def block():
    return re.search(r"// BEGIN sunShade[^\n]*\n(.*?)// END sunShade", page(), re.S).group(1)


def run(js, tz="America/Los_Angeles"):
    env = dict(os.environ, TZ=tz)
    out = subprocess.run([NODE, "-e", block() + "\n" + js], capture_output=True, text=True, env=env)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_constants_match_the_config():
    with open(os.path.join(ROOT, "terrain", "terrain_config.yaml"), encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    r, t = cfg["render"], cfg["tiles"]
    sun = run("process.stdout.write(JSON.stringify(SUN))")
    assert sun["reachKm"] == r["reach_km"] and sun["nearReachKm"] == r["near_reach_km"]
    assert sun["growth"] == r["growth"] and sun["biasM"] == r["bias_m"]
    assert sun["earthR"] == r["earth_radius_m"] and sun["refrK"] == r["refraction_k"]
    assert sun["readoutStepMin"] == r["readout_step_min"] and sun["slider"] == r["slider_min"]
    assert sun["tz"] == r["timezone"] and sun["minZoom"] == r["min_zoom"]
    assert sun["shadeRgb"] == r["shade_rgb"] and sun["opacity"] == r["opacity"]
    assert sun["nearZooms"] == t["near_zooms"] and sun["farZoom"] == t["far_zoom"]
    assert sun["bbox"] == cfg["area"]["bbox_lonlat"] and sun["marginKm"] == cfg["area"]["margin_km"]
    assert "/dem/v1/" in page() and cfg["upload"]["prefix"] == "pnw/dem/v1/"


def test_sun_position_matches_astropy_and_the_snow_model():
    import sys
    sys.path.insert(0, ROOT)
    from snow import solar
    js = "const out = %s.map(([n, lat, lon, t]) => sunAt(lat, lon, sunTerms(Date.parse(t + 'Z'))));" \
         "process.stdout.write(JSON.stringify(out));" % json.dumps([p[:4] for p in ASTROPY])
    got = run(js)
    for (name, lat, lon, t, alt, az), g in zip(ASTROPY, got):
        assert abs(g["el0"] - alt) < 0.02, (name, g, alt)
        assert abs((g["az"] - az + 180) % 360 - 180) < 0.03, (name, g, az)
        el, a = solar.sun_position(lat, lon, dt.datetime.fromisoformat(t))
        assert abs(g["el0"] - float(el)) < 0.001 and abs(g["az"] - float(a)) < 0.001, (name, g, float(el), float(a))


def test_refraction_by_hand():
    got = run("process.stdout.write(JSON.stringify([sunRefraction(0), sunRefraction(10), sunRefraction(90), sunRefraction(-2)]))")
    assert abs(got[0] - 1735 / 3600) < 1e-9                       # 0.482 deg at the horizon
    t = math.tan(math.radians(10))
    assert abs(got[1] - (58.1 / t - 0.07 / t ** 3 + 0.000086 / t ** 5) / 3600) < 1e-9 and abs(got[1] - 0.0881) < 0.0002
    assert got[2] == 0 and abs(got[3] - (-20.772 / math.tan(math.radians(-2)) / 3600)) < 1e-9


@pytest.mark.parametrize("tz", ["America/Los_Angeles", "UTC", "Asia/Tokyo"])
def test_pacific_times_whatever_the_device_zone(tz):
    cases = [("2026-07-01", 720, "2026-07-01T19:00:00Z"), ("2026-12-21", 720, "2026-12-21T20:00:00Z"),
             ("2026-03-07", 300, "2026-03-07T13:00:00Z"), ("2026-03-08", 300, "2026-03-08T12:00:00Z"),
             ("2026-10-31", 300, "2026-10-31T12:00:00Z"), ("2026-11-01", 300, "2026-11-01T13:00:00Z"),
             ("2026-11-01", 1320, "2026-11-02T06:00:00Z")]
    got = run("process.stdout.write(JSON.stringify(%s.map(([d, m]) => new Date(sunPacificMs(d, m)).toISOString())))" % json.dumps(cases), tz)
    assert got == [c[2].replace("Z", ".000Z") for c in cases]


def test_a_wall_to_the_south_shades_below_its_angle():
    # 100 m wall 500-600 m south of a flat plain; sun due south. Hand answer: atan((100 - bias - curvature) / 500)
    got = run(TERRAIN_JS + """
      const W = world((e, n) => (n <= -500 && n >= -600 ? 100 : 0));
      process.stdout.write(JSON.stringify({ t: threshold(W, 180, 1, 30), open: lit(world(() => 0), 1, 180) }));""")
    hand = math.degrees(math.atan((100 - 0.5 - 500 ** 2 * 0.87 / (2 * 6371000)) / 500))
    assert abs(got["t"] - hand) < 0.25, (got, hand)        # the wall's edge is smeared over one 6.5 m pixel
    assert got["open"] is True                             # a flat plain is in sun even at 1 degree


def test_earth_curvature_lowers_a_distant_wall():
    # 1000 m wall 20-21 km south (the far grid). With curvature and refraction the threshold is 2.74-2.79 deg
    # (step and pixel slack); without curvature it would be 2.82-2.86 deg.
    got = run(TERRAIN_JS + """
      const W = world((e, n) => (n <= -20000 && n >= -21000 ? 1000 : 0));
      process.stdout.write(JSON.stringify(threshold(W, 180, 1, 10)));""")
    assert 2.735 < got < 2.79, got


def test_a_slope_facing_away_is_in_shade():
    # north-facing 40 degree plane, sun from the south: shade below 40 degrees, sun above
    got = run(TERRAIN_JS + """
      const W = world((e, n) => -n * Math.tan(40 * Math.PI / 180));
      process.stdout.write(JSON.stringify([lit(W, 38, 180), lit(W, 42, 180), lit(W, 30, 0)]));""")
    assert got == [False, True, True]


def test_night_and_no_data():
    got = run(TERRAIN_JS + """
      const W = world(() => 0), none = world(() => -32768);
      process.stdout.write(JSON.stringify([lit(W, -0.1, 90), sunLit(none.near, none.far, PX, PY, { el: 30, az: 180 }, 0)]));""")
    assert got == [False, None]


def test_windows_on_a_plain_and_behind_an_east_ridge():
    # a plain sees the sun from flat sunrise to flat sunset; a 1500 m ridge 3 km east delays the first window
    got = run(TERRAIN_JS + """
      const flat = world(() => 0), ridge = world((e, n) => (e >= 3000 && e <= 3500 ? 1500 : 0));
      const a = sunWindows(flat.near, flat.far, P.lat, P.lon, '2026-12-21', flat.zmax);
      const b = sunWindows(ridge.near, ridge.far, P.lat, P.lon, '2026-12-21', ridge.zmax);
      process.stdout.write(JSON.stringify({ a, b }));""")
    a, b = got["a"], got["b"]
    assert len(a["windows"]) == 1 and a["windows"][0] == a["flat"]
    # NOAA sunrise / sunset there are 7:48 / 16:14 PST (the page's sunTimes, itself tested against NOAA's calculator);
    # "flat" counts from the sun's centre clearing the horizon, a few minutes inside those (the 2-minute steps add up to 2)
    assert 7 * 60 + 48 <= a["flat"][0] <= 7 * 60 + 54 and 16 * 60 + 8 <= a["flat"][1] <= 16 * 60 + 14
    assert abs(a["hours"] - (a["flat"][1] - a["flat"][0] + 2) / 60) < 1e-9
    assert b["windows"][0][0] > a["flat"][0] + 120 and b["windows"][-1][1] == a["flat"][1]
