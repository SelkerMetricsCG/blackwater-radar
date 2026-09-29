"""snow/lattice.py: tile naming, grid geometry, slope and aspect (no downloads)."""
import pytest

np = pytest.importorskip("numpy")
from snow import lattice  # noqa: E402


def test_tile_names_cover_the_bbox():
    t = lattice.tile_names([-124.9, 45.2, -120.0, 49.0])
    assert len(t) == 20 and t[0] == "n46w125" and t[-1] == "n49w121"
    assert lattice.tile_names([-121.5, 47.2, -120.5, 47.8]) == ["n48w122", "n48w121"]


def test_slope_aspect_conventions():
    z = np.array([[3., 2., 1.], [3., 2., 1.], [3., 2., 1.]]) * 100      # falls to the east
    s, a = lattice.slope_aspect(z, 100, 2)
    assert a[1, 1] == 90 and abs(s[1, 1] - 45) < 1e-6
    z = np.array([[1., 1., 1.], [2., 2., 2.], [3., 3., 3.]]) * 100      # rises to the south: faces north
    assert lattice.slope_aspect(z, 100, 2)[1][1, 1] == 0
    z = np.array([[3., 3., 3.], [2., 2., 2.], [1., 1., 1.]]) * 10       # gentle, faces south
    s, a = lattice.slope_aspect(z, 100, 2)
    assert a[1, 1] == 180 and 5 < s[1, 1] < 6
    s, a = lattice.slope_aspect(np.ones((3, 3)) * 500, 100, 2)
    assert (a == -1).all() and (s == 0).all()
    z = np.ones((3, 3)) * 500
    z[1, 1] = np.nan
    s, a = lattice.slope_aspect(z, 100, 2)
    assert np.isnan(s[1, 1]) and a[1, 1] == -1


def test_dest_grid_is_whole_cells_and_covers_the_box():
    pytest.importorskip("pyproj")
    pytest.importorskip("rasterio")
    tr, h, w = lattice.dest_grid([-121.5, 47.2, -120.5, 47.8], "EPSG:26910", 100)
    assert h > 600 and w > 700 and tr.a == 100 and tr.e == -100 and tr.c % 100 == 0 and tr.f % 100 == 0
