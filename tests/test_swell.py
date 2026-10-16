"""Swell forecast layer (swell.py): .idx byte ranges, GRIB decode, resampling, stacked encoding, points, index, skip and
abandon (no network). The fixtures are real: the f000 .idx of the GFS-Wave 18Z 2026-10-15 west-coast run and its
"SWELL:1 in sequence" message, fetched by byte range."""
import datetime as dt
import json
import os

import numpy as np
import pytest
from PIL import Image

import swell

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "coastal")
UTC = dt.timezone.utc
CYCLE = dt.datetime(2026, 10, 15, 18, tzinfo=UTC)
NOW = dt.datetime(2026, 10, 16, 0, 45, tzinfo=UTC).timestamp()
CYC = "gfswave_t18z_20261015"
LAT = np.linspace(25.0, 50.0, 151)          # the west-coast grid, ascending, lon converted
LON = np.linspace(-150.0, -110.0, 241)


def idx_text():
    with open(os.path.join(FIX, "gfswave_wcoast_t18z_f000.idx"), encoding="utf-8") as f:
        return f.read()


def msg():
    with open(os.path.join(FIX, "gfswave_wcoast_t18z_f000_swell1.grib2"), "rb") as f:
        return f.read()


def index(path, name):
    with open(path, encoding="utf-8") as f:
        text = f.read()
    assert text.startswith("window.%s = " % name)
    return json.loads(text[len("window.%s = " % name):].rstrip().rstrip(";"))


def test_idx_ranges_for_the_twelve_fields():
    r = swell.idx_ranges(idx_text())
    assert len(r) == 12 and set(r) == set(swell.FIELDS)
    assert r[("SWELL", "1 in sequence")] == (115837, 126422)
    assert r[("SWPER", "2 in sequence")] == (170656, 185534)
    assert r[("HTSGW", "surface")] == (66700, 76677)
    assert r[("DIRPW", "surface")] == (88160, 106933)
    assert r[("SWDIR", "3 in sequence")] == (256029, None)          # the file's last message: to the end
    with pytest.raises(KeyError, match="SWDIR:3 in sequence"):
        swell.idx_ranges("\n".join(idx_text().splitlines()[:-1]))


def test_decode_fixture_to_lat_lon_with_lon_converted():
    lat, lon, v, t = swell.decode(msg(), ("SWELL", "1 in sequence"))
    assert v.shape == (151, 241) and v.dtype == np.float32
    assert lat[0] == pytest.approx(25.0) and lat[-1] == pytest.approx(50.0)          # flipped to ascending
    assert lon[0] == pytest.approx(-150.0) and lon[-1] == pytest.approx(-110.0)      # 210..250 E -> -150..-110
    assert t == int(CYCLE.timestamp())
    i, j = int(np.argmin(abs(lat - 47.0))), int(np.argmin(abs(lon + 125.0)))
    assert 0.1 < v[i, j] < 15                                         # open ocean off Washington: a swell height in m
    assert np.isnan(v[int(np.argmin(abs(lat - 47.5))), int(np.argmin(abs(lon + 120.0)))])     # inland: missing
    with pytest.raises(ValueError):
        swell.decode(msg(), ("SWELL", "2 in sequence"))               # wrong sequence number
    with pytest.raises(ValueError):
        swell.decode(msg(), ("SWPER", "1 in sequence"))               # wrong parameter


def test_window_grid_and_bilinear_resampling():
    lat_c, lon_c, bbox = swell.out_grid()
    assert (len(lat_c), len(lon_c)) == (235, 351)
    assert lat_c[0] == pytest.approx(bbox[1] - 0.02) and lon_c[0] == pytest.approx(bbox[2] + 0.02)
    la, lo = np.meshgrid(lat_c, lon_c, indexing="ij")
    f = (LAT[:, None] + 2 * LON[None, :]).astype(np.float32)          # linear: bilinear is exact
    got, = swell.interp(LAT, LON, [f], la, lo)
    inside = la <= 50.0                                               # the model stops at 50 N; the pnw window reaches 52.5
    assert np.isnan(got[~inside]).all() and inside.sum() > 0.7 * inside.size
    assert np.allclose(got[inside], (la + 2 * lo)[inside], atol=1e-3)
    g = f.copy(); g[90, 120] = np.nan                                  # one nodata corner: the other three carry it
    a, = swell.interp(LAT, LON, [g], [LAT[90] + 0.05], [LON[120] + 0.05])
    three = [f[90, 121], f[91, 120], f[91, 121]]
    assert min(three) <= a[0] <= max(three)                           # a weighted mean of the valid corners
    nan, = swell.interp(LAT, LON, [np.full_like(f, np.nan)], [47.0], [-125.0])
    assert np.isnan(nan[0])
    out, = swell.interp(LAT, LON, [f], [10.0], [-125.0])               # outside the model
    assert np.isnan(out[0])
    d = np.where(np.arange(241)[None, :] % 2 == 0, 350.0, 10.0) * np.ones((151, 1))
    _, dd = swell.interp(LAT, LON, [f, d], [47.0], [LON[100] + (LON[1] - LON[0]) / 2], angular=(1,))
    assert min(dd[0], 360 - dd[0]) < 0.01                              # 350 and 10 average to north, not 180


def test_stacked_encoding_round_trip_and_nodata():
    rng = np.random.default_rng(1)
    shape = (5, 7)
    parts = {p: (rng.uniform(0, 12, shape), rng.uniform(2, 25, shape), rng.uniform(0, 360, shape)) for p in range(3)}
    parts[0][0][0, 0] = np.nan                                         # nodata cell in partition 1
    parts[2] = tuple(np.full(shape, np.nan) for _ in range(3))         # partition 3 absent
    parts[1][0][0, 1], parts[1][1][0, 1] = 30.0, 70.0                  # past the caps
    rgb = swell.encode(parts)
    assert rgb.shape == (15, 7, 3) and rgb.dtype == np.uint8
    assert tuple(rgb[0, 0]) == (0, 0, 255) and (rgb[10:, :, 2] == 255).all()
    back = swell.decode_png(rgb)
    for p in (0, 1):
        h, per, d = back[p]
        ok = np.isfinite(parts[p][0]) & (parts[p][0] < 25)
        assert np.all(abs(h[ok] - parts[p][0][ok]) <= 0.05 + 1e-6)
        assert np.all(abs(per[ok] - parts[p][1][ok]) <= 0.25 + 1e-6)
        dd = abs(d[ok] - parts[p][2][ok]) % 360
        assert np.all(np.minimum(dd, 360 - dd) <= 1.0 + 1e-6)
        assert (rgb[p * 5:(p + 1) * 5, :, 2][ok] <= 179).all()
    assert np.isnan(back[0][0][0, 0]) and np.isnan(back[2][0]).all()
    assert back[1][0][0, 1] == pytest.approx(25.5) and back[1][1][0, 1] == pytest.approx(63.5)


def synthetic(fh):
    """{(var, level): [151, 241]} for one step: partition p height (p + 1) + fh / 100 m, period 10 + p s, direction
    270 + 10 p deg, partition 3 absent, land east of -124; combined sea 3 m at 12 s from 280"""
    land = np.zeros((151, 241), bool); land[:, LON > -124.0] = True
    val = {"SWELL": lambda p: p + 1 + fh / 100.0, "SWPER": lambda p: 10.0 + p, "SWDIR": lambda p: 270.0 + 10 * p}
    out = {}
    for p, lev in enumerate(swell.PARTS):
        for var, fn in val.items():
            out[(var, lev)] = np.where(land | (p == 2), np.nan, fn(p)).astype(np.float32)
    for var, x in (("HTSGW", 3.0), ("PERPW", 12.0), ("DIRPW", 280.0)):
        out[(var, "surface")] = np.where(land, np.nan, x).astype(np.float32)
    return out


def test_point_sampling_at_a_known_cell():
    f = synthetic(0)
    f[("SWELL", "1 in sequence")] = (LAT[:, None] * 0 + np.arange(241)[None, :] * 0.01).astype(np.float32)
    i, j = int(np.argmin(abs(LAT - 47.0))), 150                        # a model node at about -125 E
    got = swell.sample_points(LAT, LON, f, np.array([LAT[i], 47.0]), np.array([LON[j], -100.0]))
    assert got["p1"][0] == [round(j * 0.01 * 3.28084, 1), 10.0, 270]
    assert got["p2"][0] == [6.6, 11.0, 280] and got["p3"][0] is None
    assert got["hs"][0] == [9.8, 12.0, 280]
    assert got["p1"][1] is None and got["hs"][1] is None               # outside the grid


@pytest.fixture
def env(tmp_path, monkeypatch):
    """GFS-Wave served from synthetic fields: the cycle check sees 18Z, each step's messages decode to synthetic()"""
    calls = []
    monkeypatch.setattr(swell, "STEPS", (0, 3, 6))
    monkeypatch.setattr(swell, "posted", lambda url: "/18/" in url and "20261015" in url)
    monkeypatch.setattr(swell, "fetch_step", lambda pool, cyc, fh: calls.append(fh) or {f: (fh, f) for f in swell.FIELDS})
    monkeypatch.setattr(swell, "decode", lambda m, f: (LAT, LON, synthetic(m[0])[f], int(CYCLE.timestamp()) + 3600 * m[0]))
    monkeypatch.setattr(swell, "land_mask", lambda lat_c, lon_c: None)
    for name, p in (("OUT", "data/swell.js"), ("POINTS_OUT", "data/swell_points.js"), ("STORE", "data/swell_cache.json"),
                    ("BUOYS", "data/buoys.js"), ("FRAME_DIR", "frames/swell")):
        monkeypatch.setattr(swell, name, str(tmp_path / p))
    os.makedirs(tmp_path / "data")
    stations = [{"id": "46041", "lat": 47.353, "lon": -124.731, "hs_ft": 4.3},      # a wave buoy: gets a series
                {"id": "9447130", "lat": 47.603, "lon": -122.339}]                 # a tide gauge, no waves: left out
    with open(swell.BUOYS, "w") as f:
        f.write("window.BUOYS = %s;\n" % json.dumps({"updated_t": 0, "stations": stations}))
    return {"tmp": tmp_path, "calls": calls}


def test_index_shape_and_times(env):
    stale = env["tmp"] / "frames" / "swell"
    for k, name in enumerate(("gfswave_t06z_20261015", "gfswave_t12z_20261015")):
        os.makedirs(stale / name)
        os.utime(stale / name, (NOW - 7200 + k, NOW - 7200 + k))
    lines = []
    assert swell.build(log=lines.append, now=NOW) == CYC
    assert lines[-1].startswith("swell: %s 3 steps, " % CYC) and lines[-1].endswith(" s, 1 buoys")
    meta = index(swell.OUT, "SWELL")
    assert meta["cycle"] == CYC and meta["step"] == 0.04 and meta["bands"] == 3 and "GFS-Wave" in meta["credit"]
    assert (meta["ny"], meta["nx"]) == (235, 351) and len(meta["bbox"]) == 4
    t0 = int(CYCLE.timestamp())
    assert [h["t"] for h in meta["hours"]] == [t0, t0 + 10800, t0 + 21600]
    assert [h["file"] for h in meta["hours"]] == ["frames/swell/%s/s%02d.png" % (CYC, n) for n in range(3)]
    r = int((meta["bbox"][1] - 47.0) / 0.04); c = int((-125.0 - meta["bbox"][2]) / 0.04)
    for n, hr in enumerate(meta["hours"]):
        img = Image.open(env["tmp"] / hr["file"])
        assert img.mode == "RGB" and img.size == (351, 3 * 235)
        b1, b2, b3 = swell.decode_png(np.asarray(img))
        assert b1[0][r, c] == pytest.approx(1 + 3 * n / 100.0, abs=0.05) and b1[1][r, c] == 10.0 and b1[2][r, c] == 270
        assert b2[0][r, c] == pytest.approx(2 + 3 * n / 100.0, abs=0.05) and np.isnan(b3[0]).all()
        assert np.isnan(b1[0][r, int((-120.0 - meta["bbox"][2]) / 0.04)])            # land
    pts = index(swell.POINTS_OUT, "SWELL_POINTS")
    assert pts["cycle"] == CYC and list(pts["points"]) == ["46041"]                    # the inland gauge has no values
    p = pts["points"]["46041"]
    assert p["t0"] == t0 and p["dt"] == 10800 and all(len(p[k]) == 3 for k in ("p1", "p2", "p3", "hs"))
    assert p["p1"][0] == [3.3, 10.0, 270] and p["p3"] == [None] * 3 and p["hs"][2] == [9.8, 12.0, 280]
    assert sorted(os.listdir(stale)) == sorted(["gfswave_t12z_20261015", CYC])          # newest two cycles kept
    assert json.load(open(swell.STORE))["cycle"] == CYC


def test_unchanged_cycle_skips_fetching(env, monkeypatch):
    with open(swell.STORE, "w") as f:
        json.dump({"v": 1, "cycle": CYC}, f)

    def boom(*a, **k):
        raise AssertionError("fetched an unchanged cycle")
    monkeypatch.setattr(swell, "fetch_step", boom)
    monkeypatch.setattr(swell, "fetch_range", boom)
    lines = []
    assert swell.build(log=lines.append, now=NOW) == CYC
    assert lines == ["swell: unchanged %s" % CYC]
    assert not os.path.exists(swell.OUT)


def test_abandons_cycle_on_a_failed_step(env, monkeypatch):
    with open(swell.STORE, "w") as f:
        json.dump({"v": 1, "cycle": "gfswave_t12z_20261015"}, f)

    def flaky(pool, cyc, fh):
        if fh == 3:
            raise RuntimeError("gfswave.t18z.wcoast.0p16.f003.grib2 (115837, 126422): timed out")
        return {f: (fh, f) for f in swell.FIELDS}
    monkeypatch.setattr(swell, "fetch_step", flaky)
    lines = []
    assert swell.build(log=lines.append, now=NOW) == "failed"
    assert "abandoned at f003" in lines[-1] and "keeping gfswave_t12z_20261015" in lines[-1]
    assert not os.path.exists(swell.OUT) and json.load(open(swell.STORE))["cycle"] == "gfswave_t12z_20261015"
    assert os.listdir(swell.FRAME_DIR) == []


def test_land_mask_from_the_currents_mask():
    lat_c, lon_c, bbox = swell.out_grid()
    land = swell.land_mask(lat_c, lon_c)
    if land is None:
        pytest.skip("no currents land mask for this region")
    cell = lambda la, lo: (int((bbox[1] - la) / 0.04), int((lo - bbox[2]) / 0.04))  # noqa: E731
    assert land.shape == (235, 351)
    assert not land[cell(47.353, -124.731)] and not land[cell(44.669, -124.546)]       # buoys 46041, 46050
    assert land[cell(47.6, -120.7)]                                                     # Leavenworth
