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


def test_zones_from_geojson_rasterizes_a_polygon_onto_the_grid():
    pytest.importorskip("pyproj")
    rasterio = pytest.importorskip("rasterio")
    pytest.importorskip("shapely")
    from rasterio.transform import from_origin
    tr = from_origin(670000.0, 5280000.0, 1000, 1000)          # 10 x 10 km near Leavenworth, UTM 10N
    lat, lon = 47.62, -120.66
    g = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "id": 1130, "properties": {"name": "Stevens Pass", "center_id": "NWAC"},
         "geometry": {"type": "Polygon", "coordinates": [[[lon - 1, lat - 1], [lon + 1, lat - 1], [lon + 1, lat + 0.02], [lon - 1, lat + 0.02], [lon - 1, lat - 1]]]}},
        {"type": "Feature", "id": 7, "properties": {"name": "far away", "center_id": "X"},
         "geometry": {"type": "Polygon", "coordinates": [[[-110, 40], [-109, 40], [-109, 41], [-110, 41], [-110, 40]]]}},
        {"type": "Feature", "properties": {"name": "no id"}, "geometry": None}]}
    z, names = lattice.zones_from_geojson(g, tr, (10, 10), "EPSG:26910")
    assert z.shape == (10, 10) and names == {1130: {"name": "Stevens Pass", "center_id": "NWAC"}, 7: {"name": "far away", "center_id": "X"}}
    assert (z[-1] == 1130).all() and z[0, 0] == -1 and 7 not in z            # the polygon's top edge (47.64 N) cuts across the grid


def test_wc_tiles_cover_the_bbox():
    assert lattice.wc_tiles([-124.9, 45.2, -120.0, 49.0]) == ["N45W126", "N45W123", "N48W126", "N48W123"]
    assert lattice.wc_tiles([-121.5, 47.2, -120.5, 47.8]) == ["N45W123"]


def test_tree_fraction_blocks_average_the_classes(tmp_path):
    rasterio = pytest.importorskip("rasterio")
    from rasterio.transform import from_origin
    a = np.zeros((40, 30), np.uint8)
    a[:20, :] = 10           # top half trees
    a[20:, :10] = 30         # grass
    a[20:, 10:20] = 10       # trees
    a[20:, 20:] = 0          # nodata
    path = str(tmp_path / "wc.tif")
    with rasterio.open(path, "w", driver="GTiff", height=40, width=30, count=1, dtype="uint8", crs="EPSG:4326",
                       transform=from_origin(-121.0, 47.0, 0.0001, 0.0001)) as dst:
        dst.write(a, 1)
    with rasterio.open(path) as src:
        blocks = list(lattice.tree_fraction_blocks(src, block=20))
    assert len(blocks) == 2
    (tr0, f0), (tr1, f1) = blocks
    assert f0.shape == (2, 3) and (f0 == 1.0).all()
    assert f1[0, 0] == 0.0 and f1[0, 1] == 1.0 and np.isnan(f1[0, 2])
    assert tr0.a == pytest.approx(0.001) and tr1.f == pytest.approx(47.0 - 20 * 0.0001)


def test_treeline_and_bands():
    pytest.importorskip("scipy")
    cfg = {"treeline_canopy": 0.15, "near_width_m": 600, "smooth_cells": 1, "min_cells": 10, "min_cells_per_bin": 2, "bands_ft": [4000, 6000]}
    # zone 1: forest to 1700 m then bare; zone 2: forest all the way up (no treeline); cells outside any zone
    elev = np.tile(np.arange(0, 2500, 100, dtype=np.float32), (12, 1))       # 12 rows x 25 elevation columns
    zone = np.full(elev.shape, 1, np.int32)
    zone[6:] = 2
    zone[11] = -1
    canopy = np.where(elev < 1700, 0.6, 0.05).astype(np.float32)
    canopy[6:11] = 0.6
    tl = lattice.treeline_by_zone(canopy, elev, zone, cfg, lambda *a: None)
    assert tl == {1: 1700.0}
    band = lattice.bands_from_treeline(elev, zone, tl, cfg)
    assert band[0, 17] == 2 and band[0, 16] == 1 and band[0, 11] == 1 and band[0, 10] == 0     # 1000 m: 1700-600 = 1100 is near
    assert band[7, 20] == 2 and band[7, 13] == 1 and band[7, 5] == 0                            # zone 2: fixed 4000/6000 ft
    assert band[11, 24] == 2 and band[11, 0] == 0                                               # outside zones: fixed
