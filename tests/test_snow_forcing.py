"""snow/forcing.py: window pixel mapping, grid sampling, zone x band reduction (no network)."""
import pytest

np = pytest.importorskip("numpy")
import region  # noqa: E402
from snow import forcing  # noqa: E402


def test_window_corners_map_to_grid_edges():
    lat0, lat1, lon0, lon1 = region.bbox()
    px, py = forcing.window_pixel([lat1, lat0], [lon0, lon1], 256)
    assert abs(px[0]) < 1e-6 and abs(py[0]) < 1e-6           # NW corner -> (0, 0)
    assert abs(px[1] - 256) < 1e-6 and abs(py[1] - 256) < 1e-6   # SE corner -> (256, 256)


def test_sample_applies_scale_and_nodata():
    n = 4
    data = [-1] * (n * n)
    data[0] = 500          # NW cell
    data[n * n - 1] = 120  # SE cell
    g = {"n": n, "scale": 10, "unit": "ft", "data": data}
    lat0, lat1, lon0, lon1 = region.bbox()
    v = forcing.sample(g, [lat1 - 0.01, lat0 + 0.01, (lat0 + lat1) / 2, 0.0], [lon0 + 0.01, lon1 - 0.01, (lon0 + lon1) / 2, 0.0])
    assert v[0] == 5000 and v[1] == 1200 and np.isnan(v[2]) and np.isnan(v[3])


def _meta():
    # a 10 x 10 lattice of 1 km cells in UTM 10N near Leavenworth
    return {"crs": "EPSG:26910", "shape": [10, 10], "transform": [1000.0, 0.0, 670000.0, 0.0, -1000.0, 5280000.0]}


def test_cell_of_and_lattice_latlon_agree():
    pytest.importorskip("pyproj")
    meta = _meta()
    lat, lon = forcing.lattice_latlon(meta)
    assert lat.shape == (10, 10) and 47 < lat[0, 0] < 48 and -121.5 < lon[0, 0] < -120
    r, c = forcing.cell_of(meta, [lat[3, 7], 0.0], [lon[3, 7], 0.0])
    assert (r[0], c[0]) == (3, 7) and (r[1], c[1]) == (-1, -1)


def test_band_values_averages_per_zone_and_band():
    pytest.importorskip("pyproj")
    meta = _meta()
    lat, lon = forcing.lattice_latlon(meta)
    zone = np.full((10, 10), 7, np.int32)
    zone[:, :5] = 3
    band = np.zeros((10, 10), np.uint8)
    band[5:, :] = 2
    pts = [{"lat": lat[1, 1], "lon": lon[1, 1], "temp": 20}, {"lat": lat[1, 2], "lon": lon[1, 2], "temp": 30},
           {"lat": lat[8, 8], "lon": lon[8, 8], "temp": 10}, {"lat": lat[8, 9], "lon": lon[8, 9], "temp": None},
           {"lat": 0.0, "lon": 0.0, "temp": 99}]
    out = forcing.band_values(pts, zone, band, "temp", meta)
    assert out == {(3, 0): 25.0, (7, 2): 10.0}
