"""snow/solar.py: sun position against hand calculation, irradiance by aspect, cloud scaling."""
import datetime as dt

import pytest

np = pytest.importorskip("numpy")
from snow import solar  # noqa: E402

LAT, LON = 47.6, -120.66      # Leavenworth


def test_solar_noon_elevation_matches_declination():
    # solar noon at 120.66 W on Dec 21 is about 20:05 UTC; elevation = 90 - lat - 23.44
    el, az = solar.sun_position(LAT, LON, dt.datetime(2026, 12, 21, 20, 5))
    assert abs(el - (90 - LAT - 23.44)) < 0.3 and abs(az - 180) < 2
    el, az = solar.sun_position(LAT, LON, dt.datetime(2026, 6, 21, 20, 5))
    assert abs(el - (90 - LAT + 23.44)) < 0.3 and abs(az - 180) < 2


def test_morning_sun_is_in_the_east_and_below_horizon_at_night():
    el, az = solar.sun_position(LAT, LON, dt.datetime(2026, 3, 20, 16, 0))     # 08:00 PST
    assert 10 < el < 25 and 95 < az < 125
    el, _ = solar.sun_position(LAT, LON, dt.datetime(2026, 3, 20, 9, 0))       # 01:00 PST
    assert el < -30


def test_sun_position_takes_arrays():
    el, az = solar.sun_position(np.array([47.0, 48.0]), np.array([-121.0, -121.0]), dt.datetime(2026, 1, 15, 20, 0))
    assert el.shape == (2,) and el[0] > el[1]           # farther north, lower sun


def test_clear_sky_direct_is_zero_below_horizon_and_rises_with_altitude():
    assert solar.clear_sky_direct(-5.0) == 0
    lo, hi = solar.clear_sky_direct(30.0, 0.0), solar.clear_sky_direct(30.0, 2000.0)
    assert 500 < lo < hi < 1100


def test_january_south_slope_gets_far_more_than_north():
    d = dt.date(2026, 1, 15)
    n = solar.daily_mj(LAT, LON, d, 30, 0, 1500)
    s = solar.daily_mj(LAT, LON, d, 30, 180, 1500)
    e = solar.daily_mj(LAT, LON, d, 30, 90, 1500)
    w = solar.daily_mj(LAT, LON, d, 30, 270, 1500)
    flat = solar.daily_mj(LAT, LON, d, 0, -1, 1500)
    assert s > 2 * flat > 5 * n and n < 1.0                 # north 30 deg: diffuse only in mid-January
    assert abs(e - w) < 0.2 * e                              # symmetric about solar noon
    assert solar.daily_mj(LAT, LON, dt.date(2026, 7, 1), 0, -1, 1500) > 4 * flat


def test_daily_mj_broadcasts_over_cells():
    d = dt.date(2026, 3, 1)
    out = solar.daily_mj(LAT, LON, d, np.array([0, 30, 30]), np.array([-1, 0, 180]), 1200)
    assert out.shape == (3,) and out[2] > out[0] > out[1]


def test_cloud_factor_endpoints():
    assert solar.cloud_factor(0) == 1 and abs(solar.cloud_factor(1) - 0.25) < 1e-9
    assert solar.daily_mj(LAT, LON, dt.date(2026, 3, 1), 0, -1, 0, cloud=1.0) == pytest.approx(
        0.25 * solar.daily_mj(LAT, LON, dt.date(2026, 3, 1), 0, -1, 0), rel=1e-6)


def test_refreeze_index_ordering():
    clear_cold = solar.refreeze_index(-6, 0.0, -10, 0)
    cloudy_cold = solar.refreeze_index(-6, 1.0, -10, 0)
    clear_warm = solar.refreeze_index(4, 0.0, -10, 0)
    assert solar.refreeze_index(-6, 0.0, -10, 4) < clear_cold
    assert clear_cold == pytest.approx(1.0) and 0 < cloudy_cold < clear_cold and clear_warm == 0


def test_binned_daily_matches_direct_within_a_few_percent():
    d = dt.date(2026, 2, 10)
    rng = np.random.default_rng(1)
    n = 200
    lat = rng.uniform(45.5, 48.9, n).astype(np.float32)
    lon = rng.uniform(-124.5, -120.2, n).astype(np.float32)
    slope = rng.uniform(0, 45, n).astype(np.float32)
    aspect = rng.uniform(0, 360, n).astype(np.float32)
    aspect[:20] = -1
    alt = rng.uniform(200, 3000, n).astype(np.float32)
    cloud = rng.uniform(0, 1, n).astype(np.float32)
    direct = np.array([solar.daily_mj(lat[i], lon[i], d, slope[i], aspect[i], alt[i], cloud[i]) for i in range(n)])
    binned = solar.daily_mj_binned(lat, lon, d, slope, aspect, alt, cloud)
    assert binned.shape == (n,) and binned.dtype == np.float32
    err = np.abs(binned - direct)
    rel = err / np.maximum(direct, 0.5)
    assert ((err < 0.6) | (rel < 0.08)).all() and np.median(rel) < 0.03      # a 5 deg aspect bin on a steep slope
    flat_direct = solar.daily_mj(47.0, -121.0, d, 0, -1, 1000)
    assert abs(solar.daily_mj_binned(47.0, -121.0, d, 30.0, -1.0, 1000.0) - flat_direct) < 0.05 * flat_direct   # flat ignores slope
