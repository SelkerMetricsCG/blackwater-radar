"""smoke.py: HRRR near-surface smoke (spec docs/superpowers/specs/2026-09-28-hrrr-smoke-layer-design.md)."""
import math

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
