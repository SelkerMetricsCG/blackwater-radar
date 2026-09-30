"""terrain/tilemath.py: tile arithmetic and the Terrarium encoding behind the sun & shade elevation tiles."""
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "terrain"))
import tilemath as tm  # noqa: E402


def test_terrarium_round_trip_within_half_a_step():
    e = np.array([[-5.0, 0.0, 350.3, 1238.06], [4392.1, np.nan, 2870.44, 12.5]], np.float32)
    d = tm.decode_terrarium(tm.encode_terrarium(e, 0.125))
    assert np.isnan(d[1, 1]) and np.isfinite(d).sum() == 7
    assert np.nanmax(np.abs(d - e)) <= 0.0625 + 1e-4


def test_terrarium_matches_the_published_formula():
    rgb = [int(v) for v in tm.encode_terrarium(np.array([[1000.5]]), 0.125)[0, 0]]
    assert rgb[0] * 256 + rgb[1] + rgb[2] / 256 - 32768 == 1000.5            # AWS / Mapzen terrarium


def test_tile_of_agrees_with_the_asinh_formula():
    for lon, lat, z in [(-120.6615, 47.5962, 14), (-121.7604, 46.8529, 10), (-122.2, 49.0, 12)]:
        n = 2 ** z
        want = (int((lon + 180) / 360 * n), int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n))
        assert tm.tile_of(lon, lat, z) == want


def test_tile_bounds_and_merc_round_trip():
    b = tm.tile_bounds(14, 2690, 5700)
    assert abs((b[2] - b[0]) - 256 * tm.res(14)) < 1e-6
    lon, lat = tm.merc_to_lonlat((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)
    assert tm.tile_of(lon, lat, 14) == (2690, 5700)


def test_block_mean_ignores_no_data():
    a = np.arange(16, dtype=np.float32).reshape(4, 4)
    a[0, 0] = np.nan
    a[2:, 2:] = np.nan
    m = tm.block_mean(a, 2)
    assert abs(m[0, 0] - 10 / 3) < 1e-6 and np.isnan(m[1, 1]) and m[1, 0] == 10.5


def test_margin_tiles_cover_the_grown_box():
    tiles = tm.margin_tiles(tm.grow_bbox((-122.2, 46.0, -120.0, 49.0), 30))
    assert len(tiles) == 20 and "n46w123" in tiles and "n50w120" in tiles and "n47w121" in tiles
