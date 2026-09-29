"""smoke.py: HRRR near-surface smoke (spec docs/superpowers/specs/2026-09-28-hrrr-smoke-layer-design.md)."""
import datetime as dt
import json

import numpy as np
import pytest

import region
import smoke

# the HRRR CONUS grid as its GRIB2 messages describe it (read with ecCodes 2026-09-29)
G = dict(ni=1799, nj=1059, lat1=21.138123, lon1=237.280472, lov=262.5, latin=38.5, dx=3000.0, radius=6371229.0)
# (j, i) -> (lat, lon) from ecCodes' own coordinate arrays for the 2026-09-28 18Z f01 message
CORNERS = {(0, 0): (21.138123, -122.719528), (0, 1798): (21.140547, -72.289718), (1058, 0): (47.838623, -134.095480),
           (1058, 1798): (47.842195, -60.917193), (530, 900): (38.524222, -97.471495), (1058, 900): (52.615649, -97.464465)}

IDX = ("75:49000000:d=2026092818:TMP:2 m above ground:1 hour fcst:\n"
       "76:50312804:d=2026092818:MASSDEN:8 m above ground:1 hour fcst:\n"
       "77:50900000:d=2026092818:COLMD:entire atmosphere:1 hour fcst:\n")


@pytest.fixture
def at_region(monkeypatch):
    def go(key):
        monkeypatch.setattr(region, "KEY", key)
    return go


# ---------- index ----------
def test_idx_range_middle_last_and_missing():
    assert smoke.idx_range(IDX, ":MASSDEN:8 m above ground:") == (50312804, 50899999)
    assert smoke.idx_range(IDX, ":COLMD:") == (50900000, None)
    assert smoke.idx_range(IDX, ":MASSDEN:10 m above ground:") is None


def test_idx_range_skips_a_repeated_offset():
    idx = "1:100:a:X:\n2:100:b:Y:\n3:250:c:Z:\n"
    assert smoke.idx_range(idx, ":X:") == (100, 249)


# ---------- Lambert grid ----------
def test_lcc_matches_eccodes_coordinates():
    for (j, i), (lat, lon) in CORNERS.items():
        fi, fj = smoke.lcc_ij(G, np.array(lat), np.array(lon))
        assert float(fi) == pytest.approx(i, abs=0.01) and float(fj) == pytest.approx(j, abs=0.01), (j, i)


def test_lcc_inverse_round_trip():
    lat = np.array([21.2, 38.5, 47.8, 52.5, 45.0])
    lon = np.array([-122.7, -97.5, -60.9, -120.0, -75.0])
    fi, fj = smoke.lcc_ij(G, lat, lon)
    la, lo = smoke.lcc_latlon(G, fi, fj)
    assert np.allclose(la, lat, atol=1e-6) and np.allclose(lo, lon, atol=1e-6)


def test_window_latlon_is_inside_the_window_and_monotone(at_region):
    at_region("sierra")
    lat, lon = smoke.window_latlon(640)
    lat0, lat1, lon0, lon1 = region.bbox()
    assert lat.shape == (640,) and lon.shape == (640,)
    assert lat1 > lat[0] > lat[-1] > lat0            # north at the top
    assert lon0 < lon[0] < lon[-1] < lon1
    assert np.all(np.diff(lat) < 0) and np.all(np.diff(lon) > 0)


def test_resample_is_bilinear_and_nan_outside(at_region):
    at_region("sierra")
    jj, ii = np.mgrid[0:G["nj"], 0:G["ni"]]
    field = (ii + 1000.0 * jj).astype(np.float32)
    out = smoke.resample(field, G, 64)
    lat, lon = smoke.window_latlon(64)
    fi, fj = smoke.lcc_ij(G, np.array(lat[10]), np.array(lon[20]))
    assert out.shape == (64, 64)
    assert float(out[10, 20]) == pytest.approx(float(fi) + 1000.0 * float(fj), abs=0.05)
    small = {**G, "ni": 50, "nj": 50}                 # a grid that ends far south-east of the window
    out2 = smoke.resample(np.ones((50, 50), np.float32), small, 16)
    assert np.isnan(out2).all()


def test_resample_pnw_is_partly_outside_the_model(at_region):
    at_region("pnw")
    out = smoke.resample(np.zeros((G["nj"], G["ni"]), np.float32), G, 64)
    share = float(np.isnan(out).mean())
    assert 0.1 < share < 0.3                           # southern BC, north of the model's edge
    assert np.isnan(out[0]).any() and not np.isnan(out[-1]).any()


# ---------- colours ----------
def test_category_edges():
    v = [1.99, 2.0, 9.0, 9.09, 9.1, 35.4, 35.5, 55.4, 55.5, 125.4, 125.5, 225.4, 225.5, float("nan"), -3.0, 5000.0]
    assert smoke.category(np.array(v)).tolist() == [-1, 0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, -1, -1, 5]


def test_frame_rgba_alpha_and_colours():
    ug = np.array([[0.5, 3.0, 20.0], [40.0, 100.0, float("nan")]])
    px = smoke.frame_rgba(ug)
    assert px.shape == (2, 3, 4) and px.dtype == np.uint8
    assert px[0, 0, 3] == 0 and px[1, 2, 3] == 0            # below the floor, outside the model
    assert tuple(px[0, 1]) == smoke.LIGHT
    assert tuple(px[0, 2, :3]) == (255, 255, 0) and px[0, 2, 3] == 255    # Moderate
    assert tuple(px[1, 0, :3]) == (255, 126, 0)                           # Unhealthy for sensitive groups
    assert tuple(px[1, 1, :3]) == (255, 0, 0)                             # Unhealthy


# ---------- value series ----------
def test_series_blocks_means_rounding_and_nan():
    a = np.zeros((640, 640), np.float32)
    a[0:5, 0:5] = np.nan                               # block (0, 0): outside the model
    a[0:5, 5:10] = 10.0
    a[0:5, 7] = np.nan                                 # a partly outside block keeps the mean of the rest
    a[5:10, 0:5] = 2.5                                 # rounds half up
    b = smoke.series_blocks(a, 128)
    assert b.shape == (128, 128) and b.dtype.kind == "i"
    assert b[0, 0] == -1 and b[0, 1] == 10 and b[1, 0] == 3 and b[5, 5] == 0


def test_series_js_layout():
    blocks = [np.full((4, 4), k, np.int64) for k in range(3)]
    blocks[1][0, 0] = -1
    js = smoke.series_js("smoke_a", blocks, t0=1000, unit="µg/m³")
    assert js.startswith('window.VALUES=window.VALUES||{};window.VALUES["smoke_a"]=')
    data = js.split('.data="')[1].split('"')[0].split(",")
    assert len(data) == 48 and data[:16] == ["0"] * 16 and data[16] == "-1" and data[17:32] == ["1"] * 15
    assert '"n":3' in js and '"t0":1000' in js and '"dt":3600' in js and '"w":4' in js and '"nodata":-1' in js


# ---------- the model's edge ----------
def test_edge_segments_cross_pnw_only(at_region):
    at_region("pnw")
    segs = smoke.edge_segments(G)
    pts = [p for s in segs for p in s]
    assert segs and len(pts) > 10
    assert all(p[0] > 49.0 for p in pts)
    lons = [p[1] for p in pts]
    assert min(lons) < -125.5 and max(lons) > -113.5   # spans the window west to east
    at_region("sierra")                                # only the open Pacific in the far south-west corner
    pts = [p for s in smoke.edge_segments(G) for p in s]
    assert pts and all(p[0] < 33.5 and p[1] < -126.0 for p in pts)
    for key in ("utco", "imw", "ne"):
        at_region(key)
        assert smoke.edge_segments(G) == [], key


# ---------- fetching, decoding, choosing the run ----------
UTC = dt.timezone.utc


def T(h, m=0, day=28):
    return dt.datetime(2026, 9, day, h, m, tzinfo=UTC)


class FakeIdx:
    """smoke.fetch stand-in: answers .idx URLs of the runs in `posted` ('YYYYMMDDHH'), else NotPosted;
    hours in `missing` ('YYYYMMDDHHfNN') answer an index without the smoke record"""
    def __init__(self, posted, missing=()):
        self.posted, self.missing, self.calls = set(posted), set(missing), []

    def __call__(self, url):
        self.calls.append(url)
        run = url.split("hrrr.")[1][:8] + url.split(".t")[1][:2]
        if run not in self.posted:
            raise smoke.NotPosted(url)
        if run + "f" + url.split("wrfsfcf")[1][:2] in self.missing:
            return IDX.replace("MASSDEN", "XXXX").encode(), ""
        return IDX.encode(), ""


def test_latest_run_skips_young_and_unposted(monkeypatch):
    net = FakeIdx({"2026092812"})
    monkeypatch.setattr(smoke, "fetch", net)
    assert smoke.latest_run(T(20, 30)) == T(12)            # 18Z not posted yet, 12Z is
    assert any("t18z.wrfsfcf48" in u for u in net.calls)
    net.calls.clear()
    assert smoke.latest_run(T(19, 30)) == T(12)            # 18Z is only 90 min old: not even asked for
    assert not any("t18z" in u for u in net.calls)
    net = FakeIdx(set())
    monkeypatch.setattr(smoke, "fetch", net)
    assert smoke.latest_run(T(20, 30)) is None
    assert all("wrfsfcf48" in u for u in net.calls)
    assert not any("hrrr.20260927/conus/hrrr.t12z" in u for u in net.calls)     # 30 h back at most


def test_slot_is_the_one_not_in_use():
    assert smoke.next_slot({}, "2026092818") == "a"
    assert smoke.next_slot({"run": "2026092806", "slot": "b"}, "2026092818") == "a"     # 12Z never built: still not b
    assert smoke.next_slot({"run": "2026092812", "slot": "a"}, "2026092818") == "b"
    assert smoke.next_slot({"run": "2026092818", "slot": "b"}, "2026092818") == "b"     # rebuilding the same run


class FakeResp:
    def __init__(self, body):
        self.body = body

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_fetch_range_checks_the_message(monkeypatch, tmp_path):
    monkeypatch.setattr(smoke, "CACHE_DIR", str(tmp_path))
    sent = []

    def opener(body):
        def _open(req):
            sent.append(req)
            return FakeResp(body)
        return _open
    good = b"GRIB" + b"x" * 8 + b"7777"
    monkeypatch.setattr(smoke, "_open", opener(good))
    assert smoke.fetch_range("https://h/a.grib2", 100, 115) == good
    assert sent[0].get_header("Range") == "bytes=100-115" and "Mozilla" in sent[0].get_header("User-agent")
    for bad in (b"<html>nope</html>", b"GRIB" + b"x" * 8 + b"77", b"GRIB" + b"x" * 20 + b"7777"):
        monkeypatch.setattr(smoke, "_open", opener(bad))
        with pytest.raises(RuntimeError):
            smoke.fetch_range("https://h/b.grib2", 100, 115)
    monkeypatch.setattr(smoke, "_open", opener(good))
    assert smoke.fetch_range("https://h/c.grib2", 100, None) == good            # the last message: open-ended range
    assert sent[-1].get_header("Range") == "bytes=100-"


def test_decode_lambert_message():
    eccodes = pytest.importorskip("eccodes")
    g = eccodes.codes_grib_new_from_samples("GRIB2")
    eccodes.codes_set(g, "gridDefinitionTemplateNumber", 30)
    for k, v in (("shapeOfTheEarth", 6), ("Nx", 4), ("Ny", 3), ("latitudeOfFirstGridPointInDegrees", 21.138123),
                 ("longitudeOfFirstGridPointInDegrees", 237.280472), ("LaDInDegrees", 38.5), ("LoVInDegrees", 262.5),
                 ("Latin1InDegrees", 38.5), ("Latin2InDegrees", 38.5), ("DxInMetres", 3000), ("DyInMetres", 3000),
                 ("iScansNegatively", 0), ("jScansPositively", 1), ("discipline", 0), ("parameterCategory", 20), ("parameterNumber", 0)):
        eccodes.codes_set(g, k, v)
    eccodes.codes_set(g, "bitsPerValue", 16)
    eccodes.codes_set_values(g, (np.arange(12) * 1e-9).astype(float))
    ug, grid = smoke.decode(eccodes.codes_get_message(g))
    assert ug.shape == (3, 4) and ug[0, 1] == pytest.approx(1.0, abs=1e-3) and ug[2, 3] == pytest.approx(11.0, abs=1e-3)
    assert grid == {**G, "ni": 4, "nj": 3}
    eccodes.codes_set(g, "parameterNumber", 1)                                   # not the mass density field
    with pytest.raises(ValueError):
        smoke.decode(eccodes.codes_get_message(g))
    eccodes.codes_release(g)


# ---------- the build ----------
RUN_T = int(T(18).timestamp())


def build_env(monkeypatch, tmp_path, store=None, fail_hour=None, remote=None):
    for name, rel in (("DATA", ""), ("OUT", "smoke.js"), ("STORE", "smoke_cache.json"), ("FRAME_DIR", "frames"), ("VALUES_DIR", "values")):
        monkeypatch.setattr(smoke, name, str(tmp_path / rel) if rel else str(tmp_path))
    monkeypatch.setattr(smoke, "SIZE", 64)
    monkeypatch.setattr(smoke, "CELLS", 16)
    monkeypatch.setattr(smoke.region, "KEY", "sierra")
    if store:
        (tmp_path / "smoke_cache.json").write_text(json.dumps(store), encoding="utf-8")
    net = FakeIdx({"2026092818"}, missing={"2026092818f%02d" % fail_hour} if fail_hour else ())
    monkeypatch.setattr(smoke, "fetch", net)
    monkeypatch.setattr(smoke, "fetch_range", lambda url, a, b: b"GRIB" + url.split("wrfsfcf")[1][:2].encode() + b"7777")

    def decode(msg):                    # hour h: h ug/m3 everywhere, 300 over part of the window at hour 5
        h = int(msg[4:6])
        f = np.full((G["nj"], G["ni"]), float(h), np.float32)
        if h == 5:
            f[500:700, 100:300] = 300.0
        return f, dict(G)
    monkeypatch.setattr(smoke, "decode", decode)
    import r2sync
    monkeypatch.setattr(r2sync, "REMOTE", remote or {})
    return net


def read_js(path, prefix="window.SMOKE = "):
    return json.loads(path.read_text(encoding="utf-8")[len(prefix):].rstrip().rstrip(";"))


def test_build_writes_frames_series_js_and_state(monkeypatch, tmp_path):
    build_env(monkeypatch, tmp_path)
    lines = []
    assert smoke.build(log=lines.append, now=RUN_T + 2 * 3600) == "18Z new"
    assert sorted(p.name for p in (tmp_path / "frames").iterdir()) == ["a%02d.webp" % h for h in range(1, 49)]
    d = read_js(tmp_path / "smoke.js")
    assert d["run_t"] == RUN_T and d["run_utc"] == "2026-09-28T18:00Z" and d["slot"] == "a" and d["series"] == "smoke_a"
    assert [h["h"] for h in d["hours"]] == list(range(1, 49)) and d["hours"][0]["t"] == RUN_T + 3600
    assert d["hours"][0]["file"] == "frames/smoke/a01.webp?v=%d" % RUN_T
    assert d["hours"][47]["max"] == 48 and d["hours"][4]["max"] == 300
    assert d["floor"] == 2.0 and d["coverage"] == 1.0 and isinstance(d["edge"], list)
    js = (tmp_path / "values" / "smoke_a.js").read_text(encoding="utf-8")
    body = js.split('.data="')[1].split('"')[0].split(",")
    assert len(body) == 48 * 16 * 16 and body[0] == "1" and body[-1] == "48"
    assert '"t0":%d' % (RUN_T + 3600) in js
    s = json.loads((tmp_path / "smoke_cache.json").read_text(encoding="utf-8"))
    assert s["v"] == 1 and s["run"] == "2026092818" and s["slot"] == "a" and s["built_t"] > 0
    assert lines[-1].startswith("smoke: HRRR 18Z Sep 28 -> slot a, 48 h, peak 300 ug/m3 (f05), 100% of window in the model")


def test_build_same_run_writes_nothing(monkeypatch, tmp_path):
    build_env(monkeypatch, tmp_path, store={"v": 1, "run": "2026092818", "slot": "b", "built_t": RUN_T + 7000})
    lines = []
    assert smoke.build(log=lines.append, now=RUN_T + 3 * 3600) == "18Z unchanged"
    assert not (tmp_path / "smoke.js").exists() and not (tmp_path / "frames").exists()
    assert "already on the map" in lines[-1]


def test_build_failed_hour_keeps_previous(monkeypatch, tmp_path):
    old = {"v": 1, "run": "2026092812", "slot": "b", "built_t": RUN_T - 4 * 3600}
    build_env(monkeypatch, tmp_path, store=old, fail_hour=17)
    (tmp_path / "smoke.js").write_text('window.SMOKE = {"run_utc": "old"};\n', encoding="utf-8")
    lines = []
    assert smoke.build(log=lines.append, now=RUN_T + 2 * 3600) == "failed"
    assert (tmp_path / "smoke.js").read_text(encoding="utf-8") == 'window.SMOKE = {"run_utc": "old"};\n'
    assert json.loads((tmp_path / "smoke_cache.json").read_text(encoding="utf-8")) == old
    assert not (tmp_path / "values" / "smoke_a.js").exists()
    assert any("f17" in ln and "keeping" in ln for ln in lines)


def test_build_rebuilds_when_remote_is_stale(monkeypatch, tmp_path):
    store = {"v": 1, "run": "2026092818", "slot": "b", "built_t": RUN_T + 7000}
    key = "sierra/data/smoke.js"
    old = dt.datetime.fromtimestamp(RUN_T + 100, UTC)                  # an earlier run's smoke.js: that upload failed
    build_env(monkeypatch, tmp_path, store=store, remote={key: ("etag", old), "sierra/data/other.js": ("e", old)})
    assert smoke.build(log=lambda m: None, now=RUN_T + 3 * 3600) == "18Z new"
    assert read_js(tmp_path / "smoke.js")["slot"] == "b"                  # the same slot: the live page does not use it
    fresh = dt.datetime.fromtimestamp(RUN_T + 7200, UTC)
    build_env(monkeypatch, tmp_path, store=store, remote={key: ("etag", fresh)})
    assert smoke.build(log=lambda m: None, now=RUN_T + 3 * 3600) == "18Z unchanged"
    build_env(monkeypatch, tmp_path, store=store, remote={"sierra/data/other.js": ("e", fresh)})   # R2 lacks smoke.js
    assert smoke.build(log=lambda m: None, now=RUN_T + 3 * 3600) == "18Z new"


def test_build_no_run_and_unreachable_host(monkeypatch, tmp_path):
    build_env(monkeypatch, tmp_path)
    monkeypatch.setattr(smoke, "fetch", FakeIdx(set()))
    lines = []
    assert smoke.build(log=lines.append, now=RUN_T + 2 * 3600) == "no run"

    def down(url):
        raise smoke.HostDown(url)
    monkeypatch.setattr(smoke, "fetch", down)
    assert smoke.build(log=lines.append, now=RUN_T + 2 * 3600) == "failed"
    assert not (tmp_path / "smoke.js").exists()
