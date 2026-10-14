"""Surface currents layer (currents.py): catalog cycles, compositing, encoding, index, skip and abandon (no network).
The model files are small synthetic NetCDF files written here with the real variable names, dims and attributes."""
import concurrent.futures as cf
import datetime as dt
import json
import os

import netCDF4
import numpy as np
import pytest
from PIL import Image

import currents

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "coastal", "sscofs_catalog_excerpt.xml")
UTC = dt.timezone.utc
S_CYCLE = dt.datetime(2026, 10, 13, 9, tzinfo=UTC)      # SSCOFS t09z
W_CYCLE = dt.datetime(2026, 10, 13, 3, tzinfo=UTC)      # WCOFS t03z
NOW = dt.datetime(2026, 10, 13, 18, tzinfo=UTC).timestamp()
FILL = np.float32(-99999.0)


# ---------- synthetic model files ----------
def write_nc(path, model, lat, lon, u, v, valid):
    """one regulargrid file: Latitude/Longitude [ny][nx], Depth (0, 1 m), u_eastward/v_northward [time][Depth][ny][nx]
    in m/s with -99999 fill, mask, time in s since the model's epoch, and (SSCOFS) the ISO Times string"""
    epoch = dt.datetime(2018 if model == "sscofs" else 2016, 1, 1, tzinfo=UTC)
    with netCDF4.Dataset(path, "w") as ds:
        ds.createDimension("time", 1)
        ds.createDimension("Depth", 2)
        ds.createDimension("ny", len(lat))
        ds.createDimension("nx", len(lon))
        d = ds.createVariable("Depth", "f8", ("Depth",))
        d.units = "m"
        d[:] = [0.0, 1.0]
        la, lo = np.meshgrid(lat, lon, indexing="ij")
        for name, val, units in (("Latitude", la, "degrees_north"), ("Longitude", lo, "degrees_east")):
            x = ds.createVariable(name, "f8", ("ny", "nx"))
            x.units = units
            x[:] = val
        ds.createVariable("mask", "f8", ("ny", "nx"))[:] = np.isfinite(u).astype(float)
        t = ds.createVariable("time", "f8", ("time",))
        t.long_name = "time since initialization"
        t.units = "seconds since %s 00:00:00" % epoch.strftime("%Y-%m-%d")
        t[:] = [(valid - epoch).total_seconds()]
        if model == "sscofs":
            ds.createDimension("maxStrlen64", 64)
            ts = ds.createVariable("Times", "S1", ("time", "maxStrlen64"))
            ts.set_auto_chartostring(False)
            ts[:] = np.frombuffer(valid.strftime("%Y-%m-%dT%H:%M:%S.000000").encode().ljust(64, b"\0"), dtype="S1").reshape(1, 64)
        for name, val in (("u_eastward", u), ("v_northward", v)):
            x = ds.createVariable(name, "f4", ("time", "Depth", "ny", "nx"), fill_value=FILL)
            x.units = "meters second-1"
            x[0, 0] = np.where(np.isfinite(val), val, FILL)
            x[0, 1] = np.full(val.shape, 9.9, dtype=np.float32)      # a deeper layer that must never be read


S_LAT, S_LON = np.arange(47.0, 49.0001, 0.01), np.arange(-124.0, -121.9999, 0.01)
W_LAT, W_LON = np.arange(44.0, 52.0001, 0.04), np.arange(-127.0, -121.9999, 0.04)
S_LAND = (48.0, 48.2, -123.0, -122.8)      # a patch SSCOFS has as land; WCOFS shows through


def s_field(h):
    u = np.full((len(S_LAT), len(S_LON)), 0.1 * h, dtype=np.float32)
    la, lo = np.meshgrid(S_LAT, S_LON, indexing="ij")
    u[(la >= S_LAND[0]) & (la <= S_LAND[1]) & (lo >= S_LAND[2]) & (lo <= S_LAND[3])] = np.nan
    return u, -u


def w_field(fh):
    u = np.full((len(W_LAT), len(W_LON)), 0.1 * fh, dtype=np.float32)
    u[:, W_LON > -122.5] = np.nan                 # WCOFS land east of -122.5
    return u, np.full_like(u, 0.05)


def catalog_xml(model, cycle, keys):
    rows = "".join('    <dataset name="%s.t%02dz.%s.regulargrid.%s%03d.nc" />\n' % (model, cycle.hour, cycle.strftime("%Y%m%d"), k, n)
                   for k, n in keys)
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<catalog xmlns="http://www.unidata.ucar.edu/namespaces/thredds/InvCatalog/v1.0">\n'
            '  <dataset name="day/">\n%s  </dataset>\n</catalog>\n' % rows)


@pytest.fixture
def env(tmp_path, monkeypatch):
    """three SSCOFS hours of t09z and WCOFS t03z f003..f024 on disk; netCDF4.Dataset(url) opens them, catalogs
    come from catalog_xml, output goes to tmp_path, and the fetch runs serially in-process"""
    files = {}
    for h in (1, 2, 3):
        p = str(tmp_path / ("s%02d.nc" % h))
        write_nc(p, "sscofs", S_LAT, S_LON, *s_field(h), S_CYCLE + dt.timedelta(hours=h))
        files[currents.file_url("sscofs", S_CYCLE, ("f", h))] = p
    for fh in range(3, 25, 3):
        p = str(tmp_path / ("w%02d.nc" % fh))
        write_nc(p, "wcofs", W_LAT, W_LON, *w_field(fh), W_CYCLE + dt.timedelta(hours=fh))
        files[currents.file_url("wcofs", W_CYCLE, ("f", fh))] = p
    real = netCDF4.Dataset
    opened = []

    def fake(url, *a, **k):
        if url.startswith("http"):
            opened.append(url)
            if url not in files:
                raise OSError("NetCDF: file not found: %r" % url)
            return real(files[url])
        return real(url, *a, **k)

    cats = {"SSCOFS": catalog_xml("sscofs", S_CYCLE, [("f", h) for h in range(1, 25)]),
            "WCOFS": catalog_xml("wcofs", W_CYCLE, [("n", 24)] + [("f", h) for h in range(3, 73, 3)])}
    monkeypatch.setattr(netCDF4, "Dataset", fake)
    monkeypatch.setattr(currents, "fetch_text", lambda url: cats[url.split("/NOAA/")[1].split("/")[0]] if "/10/13/" in url else "")
    monkeypatch.setattr(currents, "_pool", lambda n: cf.ThreadPoolExecutor(1))     # netcdf-c is not thread-safe
    monkeypatch.setattr(currents, "HOURS", (1, 2, 3))
    monkeypatch.setattr(currents, "RETRY_PAUSE", 0)
    monkeypatch.setattr(currents, "OUT", str(tmp_path / "data" / "currents.js"))
    monkeypatch.setattr(currents, "STORE", str(tmp_path / "data" / "currents_cache.json"))
    monkeypatch.setattr(currents, "FRAME_DIR", str(tmp_path / "frames" / "currents"))
    return {"files": files, "opened": opened, "tmp": tmp_path}


def index(path):
    with open(path, encoding="utf-8") as f:
        s = f.read()
    assert s.startswith("window.CURRENTS = ")
    return json.loads(s[s.index("{"):s.rindex("}") + 1])


def cell(meta, lat, lon):
    lat0, lat1, lon0, lon1 = meta["bbox"]
    return int((lat1 - lat) / meta["step"]), int((lon - lon0) / meta["step"])


# ---------- tests ----------
def test_cycle_from_catalog():
    with open(FIX, encoding="utf-8") as f:
        cycles = currents.parse_catalog(f.read(), "sscofs")
    t15 = dt.datetime(2026, 10, 13, 15, tzinfo=UTC)
    assert set(cycles) == {dt.datetime(2026, 10, 13, h, tzinfo=UTC) for h in (3, 9, 15)}
    assert ("f", 24) not in cycles[t15] and ("f", 10) in cycles[t15] and ("n", 6) in cycles[t15]   # fields.f024 is not regulargrid
    assert currents.newest_cycle(cycles, {("f", 24)}) == S_CYCLE
    assert currents.newest_cycle({}, {("f", 24)}) is None


def test_wcofs_plan_brackets_each_hour():
    w = {W_CYCLE: {("n", 24)} | {("f", h) for h in range(3, 73, 3)}}
    cyc, plan = currents.wcofs_plan(S_CYCLE, w, hours=(1, 2, 3, 24))
    assert cyc == W_CYCLE
    assert plan[1] == (("f", 6), ("f", 9), pytest.approx(1 / 3)) and plan[3] == (("f", 9), None, 0)
    assert plan[24] == (("f", 30), None, 0)
    early = currents.wcofs_plan(dt.datetime(2026, 10, 13, 3, tzinfo=UTC), w, hours=(1,))[1]
    assert early[1][0] == ("n", 24)                       # f000 is the cycle's last nowcast file
    assert currents.wcofs_plan(S_CYCLE, {W_CYCLE: {("f", 24)}}) == (None, None)


def test_composite_sscofs_wins_and_nodata():
    lat_c, lon_c = np.array([48.5, 47.5, 46.5]), np.array([-124.5, -123.5, -122.0])
    wl, wo = np.array([46.0, 47.0, 48.0, 49.0]), np.array([-125.0, -124.0, -123.0])     # WCOFS: lon -125..-123
    wu = np.full((4, 3), 0.3, dtype=np.float32)
    sl, so = np.array([47.5, 48.5]), np.array([-124.5, -123.5])                          # SSCOFS: the NW 2x2
    su = np.array([[1.0, np.nan], [1.0, 1.0]], dtype=np.float32)                         # land at (47.5, -123.5)
    u, v = currents.composite([(wl, wo, wu, -wu), (sl, so, su, -su)], lat_c, lon_c)
    assert u[0, 0] == 1.0 and u[1, 0] == 1.0 and v[0, 1] == -1.0                         # SSCOFS wins
    assert u[1, 1] == np.float32(0.3) and u[2, 0] == np.float32(0.3)                     # SSCOFS land / outside: WCOFS
    assert np.isnan(u[:, 2]).all() and np.isnan(v[:, 2]).all()                           # east of both: nodata
    rgb = currents.encode(u, v)
    assert rgb[0, 2].tolist() == [0, 0, 0] and rgb[0, 0, 2] == 255


def test_encode_decode_roundtrip_and_saturation():
    rng = np.random.default_rng(1)
    u, v = rng.uniform(-2.5, 2.5, (40, 50)), rng.uniform(-2.5, 2.5, (40, 50))
    du, dv = currents.decode(currents.encode(u, v))
    assert np.abs(du - u).max() <= 0.01 + 1e-6 and np.abs(dv - v).max() <= 0.01 + 1e-6
    rgb = currents.encode(np.array([3.0, -3.0, 0.0, np.nan]), np.array([0.0, 0.0, -3.0, 0.0]))
    assert rgb[0].tolist() == [255, 128, 255] and rgb[1].tolist() == [1, 128, 255] and rgb[2].tolist() == [128, 1, 255]
    assert rgb[3].tolist() == [0, 0, 0]
    assert np.isnan(currents.decode(rgb)[0][3])


def test_index_shape_and_times(env):
    stale = env["tmp"] / "frames" / "currents"
    for k, name in enumerate(("old_a", "old_b")):
        os.makedirs(stale / name)
        os.utime(stale / name, (NOW - 7200 + k, NOW - 7200 + k))
    got = currents.build(log=lambda *a: None, now=NOW)
    cyc = "sscofs_t09z_20261013-wcofs_t03z_20261013"
    assert got == cyc
    meta = index(currents.OUT)
    assert meta["cycle"] == cyc and meta["step"] == 0.01 and meta["scale_cms"] == 2 and "SSCOFS and WCOFS" in meta["credit"]
    assert (meta["ny"], meta["nx"]) == (941, 1406)
    assert [h["t"] for h in meta["hours"]] == [int(S_CYCLE.timestamp()) + 3600 * h for h in (1, 2, 3)]
    assert [h["file"] for h in meta["hours"]] == ["frames/currents/%s/h%02d.png" % (cyc, h) for h in (1, 2, 3)]
    for h, hr in zip((1, 2, 3), meta["hours"]):
        img = Image.open(env["tmp"] / hr["file"])
        assert img.mode == "RGB" and img.size == (meta["nx"], meta["ny"])
        u, v = currents.decode(np.asarray(img))
        assert u[cell(meta, 48.5, -123.5)] == pytest.approx(0.1 * h, abs=0.01)           # SSCOFS (surface, not 9.9)
        assert v[cell(meta, 48.5, -123.5)] == pytest.approx(-0.1 * h, abs=0.01)
        assert u[cell(meta, 48.1, -122.9)] == pytest.approx(0.1 * (6 + h), abs=0.01)     # SSCOFS land: WCOFS in time
        assert u[cell(meta, 45.0, -125.0)] == pytest.approx(0.1 * (6 + h), abs=0.01)     # shelf: WCOFS f006/f009
        assert np.isnan(u[cell(meta, 47.0, -120.0)])                                   # inland: nodata
    assert sorted(os.listdir(stale)) == sorted(["old_b", cyc])                         # newest two cycles kept
    assert json.load(open(currents.STORE))["cycle"] == cyc


def test_unchanged_cycle_skips_fetch(env, monkeypatch):
    cyc = "sscofs_t09z_20261013-wcofs_t03z_20261013"
    os.makedirs(os.path.dirname(currents.STORE))
    with open(currents.STORE, "w") as f:
        json.dump({"v": 1, "cycle": cyc}, f)

    def boom(*a, **k):
        raise AssertionError("fetched an unchanged cycle")
    monkeypatch.setattr(currents, "fetch_all", boom)
    lines = []
    assert currents.build(log=lines.append, now=NOW) == cyc
    assert lines == ["currents: unchanged %s" % cyc]
    assert not os.path.exists(currents.OUT)


def test_abandons_cycle_on_missing_hour(env):
    os.makedirs(os.path.dirname(currents.OUT))
    with open(currents.OUT, "w") as f:
        f.write("window.CURRENTS = {\"cycle\": \"old\"};\n")
    with open(currents.STORE, "w") as f:
        json.dump({"v": 1, "cycle": "old"}, f)
    bad = currents.file_url("sscofs", S_CYCLE, ("f", 2))
    del env["files"][bad]
    lines = []
    assert currents.build(log=lines.append, now=NOW) == "failed"
    assert env["opened"].count(bad) == 2                                                  # two tries
    assert "abandoned" in lines[-1] and "keeping old" in lines[-1] and "f002" in lines[-1]
    assert index(currents.OUT)["cycle"] == "old" and json.load(open(currents.STORE))["cycle"] == "old"
    assert not os.path.exists(currents.FRAME_DIR) or os.listdir(currents.FRAME_DIR) == []


def test_cloud_prunes_current_cycles_by_their_start_hour():
    import datetime as dt
    import cloud
    assert cloud.currents_stamp("pnw/frames/currents/sscofs_t15z_20261013-wcofs_t03z_20261013/h07.png") == dt.datetime(2026, 10, 13, 15)
    assert cloud.currents_stamp("pnw/frames/radar/r20261013_1500.webp") is None
    assert cloud.currents_stamp("pnw/frames/currents/odd/h01.png") is None
