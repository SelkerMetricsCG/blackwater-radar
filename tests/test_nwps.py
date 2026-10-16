"""Nearshore swell (nwps.py): NOMADS listings, GRIB decode, compositing, land mask, beach sample search, encoding,
index shapes and the unchanged-run skip (no network). Fixtures: three real NOMADS listing excerpts (pqr, 2026-10-15)
and six real GRIB2 messages (pqr CG2 18Z run, shts/perpw/dirpw at steps 0 and 3, from the filter CGI)."""
import datetime as dt
import json
import math
import os
import re

import numpy as np
import pytest
from PIL import Image

import currents
import nwps

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "coastal")
UTC = dt.timezone.utc
NOW = dt.datetime(2026, 10, 16, 0, 50, tzinfo=UTC)
RUN18 = dt.datetime(2026, 10, 15, 18, tzinfo=UTC)


def _fix(name, mode="r"):
    with open(os.path.join(FIX, name), mode, encoding=None if "b" in mode else "utf-8") as f:
        return f.read()


def fake_get(missing=(), calls=None):
    """NOMADS listings for pqr on 2026-10-15 built from the fixtures; (hour, grid) pairs in `missing` lack their file"""
    day, run, cg2 = _fix("nwps_listing_pqr_day.html"), _fix("nwps_listing_pqr_run.html"), _fix("nwps_listing_pqr_cg2.html")

    def get(url):
        if calls is not None:
            calls.append(url)
        if url.endswith("wr.20261015/pqr/"):
            return day
        m = re.search(r"wr\.20261015/pqr/(\d\d)/(?:(CG\d)/)?$", url)
        if not m:
            return ""
        hh, cg = m.groups()
        if cg is None:
            return run
        if (int(hh), cg) in missing:
            return cg2.replace("pqr_nwps_CG2_20261015_1800.grib2", "")
        return cg2.replace("CG2", cg).replace("_20261015_1800", "_20261015_%s00" % hh)
    return get


# ---------- listings ----------
def test_listing_parse_and_nest_discovery():
    assert nwps.run_hours(nwps.list_names(_fix("nwps_listing_pqr_day.html"))) == [0, 2, 6, 12, 14, 18]
    assert nwps.grid_dirs(nwps.list_names(_fix("nwps_listing_pqr_run.html"))) == ["CG0", "CG1", "CG2", "CG3", "CG4", "CG5"]
    names = nwps.list_names(_fix("nwps_listing_pqr_cg2.html"))
    assert nwps.grib_name("pqr", "CG2", RUN18) == "pqr_nwps_CG2_20261015_1800.grib2" in names
    assert not any(n.startswith("/") for n in names)                     # the parent link is dropped


def test_find_run_newest_complete():
    assert nwps.find_run("pqr", NOW, get=fake_get()) == RUN18
    # 18Z still posting its CG4 -> the 14Z run
    assert nwps.find_run("pqr", NOW, get=fake_get({(18, "CG4")})) == dt.datetime(2026, 10, 15, 14, tzinfo=UTC)
    assert nwps.find_run("pqr", NOW, get=fake_get({(h, "CG1") for h in (0, 2, 6, 12, 14, 18)})) is None


def test_find_run_cached_needs_no_grid_listings():
    calls = []
    assert nwps.find_run("pqr", NOW, cached=RUN18, get=fake_get(calls=calls)) == RUN18
    assert not any("/CG" in u for u in calls)


# ---------- GRIB ----------
def test_decode_fixture_messages():
    g = nwps.read_grib(_fix("nwps_pqr_CG2_excerpt.grib2", "rb"), [0, 3])
    assert (len(g["lat"]), len(g["lon"])) == (38, 25)
    assert g["lat"][0] == pytest.approx(46.84) and g["lat"][-1] == pytest.approx(47.01)
    assert g["lon"][0] == pytest.approx(-124.26) and g["lon"][-1] == pytest.approx(-124.10)
    assert set(g["f"]) == {0, 3}
    h, per, d = g["f"][0]
    ok = np.isfinite(h)
    assert 600 < ok.sum() < 950 and np.array_equal(ok, np.isfinite(per))
    assert 0 < np.nanmax(h) < 10 and 2 < np.nanmedian(per) < 25 and 0 <= np.nanmin(d) and np.nanmax(d) <= 360
    with pytest.raises(ValueError):
        nwps.read_grib(_fix("nwps_pqr_CG2_excerpt.grib2", "rb"), [0, 6])     # a missing step is an error


# ---------- compositing, encoding ----------
def _grid(lat0, lat1, lon0, lon1, step):
    return np.arange(lat0, lat1 + 1e-9, step), np.arange(lon0, lon1 + 1e-9, step)


def test_finer_nest_wins():
    lat_c, lon_c = np.array([47.0, 46.99, 46.98]), np.array([-124.2, -124.19, -124.18])
    clat, clon = _grid(46.9, 47.1, -124.3, -124.1, 0.05)
    flat, flon = _grid(46.99, 47.01, -124.19, -124.17, 0.01)
    coarse = tuple(np.full((len(clat), len(clon)), v, np.float32) for v in (1.0, 10.0, 270.0))
    fine = [np.full((len(flat), len(flon)), v, np.float32) for v in (2.0, 12.0, 280.0)]
    fine[0][0, 0] = np.nan                                                # a dry fine cell leaves the coarse value
    h, per, d = nwps.composite([(clat, clon, coarse), (flat, flon, tuple(fine))], lat_c, lon_c)
    assert h[2, :].tolist() == [1.0, 1.0, 1.0]                            # 46.98: outside the fine grid
    assert h[0, 1] == 2.0 and per[0, 1] == 12.0 and d[0, 1] == 280.0
    assert h[1, 1] == 1.0                                                 # the NaN fine cell (46.99, -124.19)
    assert h[0, 0] == 1.0                                                 # -124.2: outside the fine grid


def test_encode_round_trip():
    h = np.array([[1.23, np.nan, 30.0]], np.float32)
    per = np.array([[14.2, 10.0, 100.0]], np.float32)
    d = np.array([[359.4, 90.0, 271.0]], np.float32)
    rgb = nwps.encode(h, per, d)
    assert rgb.dtype == np.uint8 and rgb.shape == (1, 3, 3)
    assert rgb[0, 0].tolist() == [12, 28, 0] and rgb[0, 1].tolist() == [255, 255, 255] and rgb[0, 2].tolist() == [255, 200, 136]
    hh, pp, dd = nwps.decode(rgb)
    assert hh[0, 0] == pytest.approx(1.2) and pp[0, 0] == 14.0 and dd[0, 0] == 0.0 and np.isnan(hh[0, 1])


# ---------- beaches ----------
def test_seaward_sample_search():
    lat, lon = _grid(46.85, 46.95, -124.25, -124.05, 0.002)
    water = np.zeros((len(lat), len(lon)), bool)
    spot = (46.90, -124.10)
    r_out = int(currents.nearest(lat, [spot[0]])[0])
    c_1km = int(currents.nearest(lon, [spot[1] - 1000 / (111320 * math.cos(math.radians(46.9)))])[0])
    assert nwps.sample_cell(lat, lon, water, *spot, 270) is None          # all land within 3 km
    water[r_out, c_1km] = True
    assert nwps.sample_cell(lat, lon, water, *spot, 270) == (r_out, c_1km)
    assert nwps.sample_cell(lat, lon, water, *spot, 90) is None           # facing away from the water
    water[:] = False
    water[:, : int(currents.nearest(lon, [spot[1] - 0.06])[0])] = True   # water only from ~4.6 km west
    assert nwps.sample_cell(lat, lon, water, *spot, 270) is None


# ---------- the job ----------
def _synthetic(key, steps):
    """grids for the build test: pqr CG1 coarse everywhere off 47-48 N, pqr CG2 a fine patch; h = step / 10 + 1 (CG2: + 2)"""
    w, cg = key
    if cg == "CG1":
        lat, lon = _grid(47.0, 48.0, -125.0, -124.0, 0.05)
    else:
        lat, lon = _grid(47.40, 47.50, -124.60, -124.40, 0.005)
    f = {}
    for s in steps:
        h = np.full((len(lat), len(lon)), s / 10 + (3.0 if cg == "CG2" else 1.0), np.float32)
        if cg == "CG2":
            h[:, -5:] = np.nan                                          # the nest's own shoreline (east edge)
        f[s] = (h, np.full_like(h, 12.0), np.full_like(h, 280.0))
    return {"lat": lat, "lon": lon, "cell": (lat[1] - lat[0]) * (lon[1] - lon[0]), "f": f}


@pytest.fixture
def job(tmp_path, monkeypatch):
    for name, sub in (("OUT", "nwps.js"), ("OUT_BEACHES", "beaches.js"), ("STORE", "nwps_wave_cache.json"),
                      ("FRAME_DIR", "frames"), ("SPOTS", "surf_spots.json")):
        monkeypatch.setattr(nwps, name, str(tmp_path / sub))
    lat_c = 48.0 - (np.arange(100) + 0.5) * 0.01
    lon_c = -125.0 + (np.arange(100) + 0.5) * 0.01
    monkeypatch.setattr(currents, "out_grid", lambda: (lat_c, lon_c, [47.0, 48.0, -125.0, -124.0]))
    land = np.zeros((100, 100), bool)
    land[:, 80:] = True                                                   # east of -124.2 is land
    monkeypatch.setattr(currents, "land_mask", lambda shape: land)
    monkeypatch.setattr(nwps, "GRIDS", {"sew": (), "pqr": ("CG1", "CG2"), "mfr": ()})
    runs = {"sew": None, "pqr": RUN18, "mfr": None}
    monkeypatch.setattr(nwps, "find_run", lambda w, now, cached=None: runs[w])
    fetched = []
    monkeypatch.setattr(nwps, "fetch_grib", lambda w, cg, run: fetched.append((w, cg)) or (w, cg))
    monkeypatch.setattr(nwps, "read_grib", _synthetic)
    with open(str(tmp_path / "surf_spots.json"), "w", encoding="utf-8") as f:
        json.dump([{"name": "Nest Beach", "lat": 47.45, "lon": -124.40, "facing": 270},
                   {"name": "Inland", "lat": 40.0, "lon": -120.0, "facing": 270}], f)
    return tmp_path, fetched


def _js(path, var):
    with open(path, encoding="utf-8") as f:
        text = f.read()
    assert text.startswith("window.%s = " % var)
    return json.loads(text[len("window.%s = " % var):].rstrip().rstrip(";"))


def test_build_composite_mask_index_and_skip(job):
    tmp_path, fetched = job
    logs = []
    cycle = nwps.build(logs.append, now=NOW.timestamp())
    assert cycle == "nwps_pqr_t18z_20261015" and sorted(fetched) == [("pqr", "CG1"), ("pqr", "CG2")]
    meta = _js(str(tmp_path / "nwps.js"), "NWPS")
    assert set(meta) == {"cycle", "runs", "updated", "updated_t", "bbox", "nx", "ny", "step", "hours", "credit"}
    t0 = int(RUN18.timestamp())
    assert meta["runs"] == {"pqr": {"run": t0, "label": "18Z 2026-10-15"}}
    assert (meta["nx"], meta["ny"], meta["step"]) == (100, 100, 0.01) and len(meta["hours"]) == 25
    assert meta["hours"][24] == {"t": t0 + 72 * 3600, "file": "frames/nwps/%s/h24.png" % cycle}
    rgb = np.asarray(Image.open(str(tmp_path / "frames" / cycle / "h01.png")))
    assert rgb.shape == (100, 100, 3)
    h, per, d = nwps.decode(rgb)
    assert h[50, 10] == pytest.approx(1.3)                               # CG1 at step 3
    assert h[52, 50] == pytest.approx(3.3)                               # CG2 nest (47.475, -124.495) wins
    assert h[52, 59] == pytest.approx(1.3)                               # nest NaN near its shore -> CG1 underneath
    assert np.isnan(h[:, 80:]).all()                                     # land mask
    assert per[52, 50] == 12.0 and d[52, 50] == 280.0

    beaches = _js(str(tmp_path / "beaches.js"), "BEACHES")
    assert beaches["cycle"] == cycle and len(beaches["spots"]) == 2
    nest, inland = beaches["spots"]
    assert nest["wfo"] == "pqr" and nest["sample"] is not None and nest["sample"][1] < -124.40
    assert nest["series"]["t0"] == t0 and nest["series"]["dt"] == 10800 and len(nest["series"]["p"]) == 25
    assert nest["series"]["p"][1] == [round(3.3 * nwps.FT, 1), 12.0, 280]
    assert inland["sample"] is None and inland["series"] is None
    assert any(m.startswith("nwps: %s 25 hours, 2 nests, 1 beaches with a series" % cycle) for m in logs)

    fetched.clear()
    assert nwps.build(logs.append, now=NOW.timestamp()) == cycle         # unchanged runs: nothing fetched
    assert fetched == [] and logs[-1] == "nwps: unchanged %s" % cycle


def test_build_abandons_and_keeps(job, monkeypatch):
    tmp_path, _ = job
    cycle = nwps.build(lambda m: None, now=NOW.timestamp())
    before = open(str(tmp_path / "nwps.js"), encoding="utf-8").read()
    runs = {"sew": None, "pqr": RUN18 + dt.timedelta(hours=6), "mfr": None}
    monkeypatch.setattr(nwps, "find_run", lambda w, now, cached=None: runs[w])

    def boom(w, cg, run):
        raise RuntimeError("NOMADS down")
    monkeypatch.setattr(nwps, "fetch_grib", boom)
    assert nwps.build(lambda m: None, now=NOW.timestamp()) == "failed"
    assert open(str(tmp_path / "nwps.js"), encoding="utf-8").read() == before
    assert os.listdir(str(tmp_path / "frames")) == [cycle]


def test_missing_spots_file_gives_empty_list(job):
    tmp_path, _ = job
    os.remove(str(tmp_path / "surf_spots.json"))
    logs = []
    nwps.build(logs.append, now=NOW.timestamp())
    assert _js(str(tmp_path / "beaches.js"), "BEACHES")["spots"] == []
    assert any("surf_spots.json" in m for m in logs)
