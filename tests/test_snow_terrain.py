"""Terrain horizons and wind exposure (snow/lattice.py), terrain shading (snow/solar.py), the station
temperature field with its cold-pool diagnostic (snow/tfield.py), and the model's use of them."""
import datetime as dt

import pytest

np = pytest.importorskip("numpy")
from snow import lattice, solar, state  # noqa: E402


def test_octant_angles_on_a_ridge():
    z = np.zeros((21, 21), np.float32)
    z[:, 15:17] = 500.0                                 # a north-south wall 5 cells east of the centre, two cells thick
    hz, sx, svf = lattice.horizon_sx_svf(z, 100.0)
    c = (10, 10)
    assert hz.shape[0] == 16 and hz[4][c] == 45 and hz[12][c] == 0     # east: 500 m up over 500 m; west: flat
    assert hz[2][c] > 0 and hz[6][c] > 0 and hz[3][c] > hz[2][c]        # NE, SE, and ENE (closer to east) see the wall
    assert sx[2][c] == 0                                # the wall is beyond the 300 m shelter reach
    assert sx[2][10, 13] > 40 and sx[6][10, 15] < 0     # just west of the wall sheltered from the east; on its west edge exposed to the west
    assert svf[c] < 100 and svf[0, 0] <= 100


def test_shading_table_and_terrain_factor():
    d = dt.date(2026, 1, 15)
    t = solar.shading_table([47.5], d)
    assert t.shape == (1, 16, 47) and abs(t[0, :, -1].sum() - 1.0) < 1e-6     # everything is below 46 deg in January
    assert t[0, 0, -1] == 0 and t[0, 8, -1] > 0.15                             # nothing from the north, plenty from the south
    lat = np.array([47.5, 47.5, 47.5], np.float32)
    hz = np.zeros((16, 3), np.uint8)
    hz[:, 1] = 45                                       # a cell walled in on every side
    hz[7:10, 2] = 30                                    # a 30 deg wall to the south (SSE..SSW) only
    f = solar.terrain_factor(hz, lat, d)
    assert f[0] == pytest.approx(1.0) and f[1] == pytest.approx(0.1, abs=0.01) and 0.2 < f[2] < 0.8


def test_station_field_finds_an_inversion(monkeypatch):
    pytest.importorskip("pyproj")
    from snow import forcing, tfield
    meta = {"crs": "EPSG:26910", "shape": [10, 10], "transform": [1000.0, 0.0, 670000.0, 0.0, -1000.0, 5280000.0], "cell_m": 1000}
    latg, long_ = forcing.lattice_latlon(meta)
    elev = np.tile(np.linspace(500, 2300, 10, dtype=np.float32)[:, None], (1, 10)).astype(np.int16)   # rises southward
    lat = {"elev": elev, "zone": np.full((10, 10), 1130, np.int32), "band": np.ones((10, 10), np.uint8)}
    p, _ = state.load_params()
    # 24 hourly files, 25 stations along the west column: min temperature RISES with elevation (a cold pool)
    stations = []
    for i in range(10):
        for j in (0, 5):
            e = float(elev[i, j])
            stations.append({"id": "S%d%d" % (i, j), "src": "NWS", "lat": float(latg[i, j]), "lon": float(long_[i, j]), "elev": e, "tmin": -12 + 0.006 * e, "tmax": 5 + 0.002 * e})
    hourlies = []
    for h in range(24):
        recs = []
        for s_ in stations:
            t = s_["tmin"] if h < 6 else s_["tmax"]
            recs.append({"id": s_["id"], "src": "NWS", "lat": s_["lat"], "lon": s_["lon"], "elev": s_["elev"], "temp": t * 9 / 5 + 32})
        hourlies.append({"stations": recs})
    lines = []
    out = tfield.fields(hourlies, None, dt.date(2026, 1, 15), -8, lat, meta, latg, long_, lat["zone"], lat["band"], p, lines.append)
    # the whole network is inverted (+6 C/km), so nothing sits above the inversion top: the night fit falls back to the
    # free-air lapse anchored at the warmest bin, and the valley stations carry the pool as negative residuals
    assert out and out["n"] == 20 and out["lapse_min"]["1130"] == pytest.approx(-p["lapse_c_per_km"])
    assert "1130" in out["inversions"] and "anchored" in out["inversions"]["1130"]
    assert out["tmin_c"][0, 0] < out["tmin_c"][9, 0] and abs(out["tmax_c"][0, 0] - 6.0) < 0.3
    assert out["tmin_resid_c"][0, 0] < -8 and abs(out["tmin_resid_c"][9, 0]) < 1.0
    assert out["loo_mae"]["n"] == 20 and out["loo_mae"]["tmax"] < 0.2 and any("leave-one-out" in ln for ln in lines)
    assert tfield.fields(hourlies[:5], None, dt.date(2026, 1, 15), -8, lat, meta, latg, long_, lat["zone"], lat["band"], p, lambda *a: None) is None


def test_night_fit_refits_above_a_valley_pool():
    from snow import tfield
    p, _ = state.load_params()
    rng = np.random.default_rng(1)
    elev = np.linspace(400, 2400, 21)
    # free-air lapse -5 C/km above 1000 m, a 6 C cold pool below it
    t = 2.0 - 5.0 * elev / 1000.0 + rng.normal(0, 0.2, elev.size)
    t[elev < 1000] -= 6.0
    a, b, note = tfield._fit_night(elev, t, p)
    assert note and "refit above" in note and -5.6 < b < -4.4
    # a plain profile is left alone
    a, b, note = tfield._fit_night(elev, 2.0 - 5.0 * elev / 1000.0, p)
    assert note is None and b == pytest.approx(-5.0, abs=0.05)


def test_residual_distance_is_elevation_aware():
    from snow import tfield
    p, _ = state.load_params()
    k = p["tfield_vertical_k"]
    # one station at (0, 0, 1000 m) with residual -6: two cells 2 km away, one at its height and one 500 m higher
    qx, qy, qz = np.array([2000.0, 2000.0]), np.array([0.0, 0.0]), np.array([1000.0, 1500.0])
    (r,) = tfield._idw([0.0], [0.0], [1000.0], [np.array([-6.0])], qx, qy, qz, 40_000.0, k)
    assert r[0] == pytest.approx(-6.0) and r[1] == pytest.approx(-6.0)       # one station: it is the only value
    # add a second station at 1500 m with residual 0, 2 km the other way: the high cell listens to it, the low cell to the first
    (r,) = tfield._idw([0.0, -2000.0], [0.0, 0.0], [1000.0, 1500.0], [np.array([-6.0, 0.0])], qx, qy, qz, 40_000.0, k)
    assert r[0] < -5.0 and r[1] > -2.0                                         # k 15: 500 m counts like 7.5 km
    # the 2-D windowed path agrees with the point path
    X, Y = np.meshgrid(np.arange(-5000.0, 5001.0, 1000.0), np.arange(5000.0, -5001.0, -1000.0))
    Z = np.full(X.shape, 1000.0)
    Z[:, 8:] = 1500.0
    (g,) = tfield._idw([0.0, -2000.0], [0.0, 0.0], [1000.0, 1500.0], [np.array([-6.0, 0.0])], X, Y, Z, 40_000.0, k)
    (pnt,) = tfield._idw([0.0, -2000.0], [0.0, 0.0], [1000.0, 1500.0], [np.array([-6.0, 0.0])], X.ravel(), Y.ravel(), Z.ravel(), 40_000.0, k)
    assert np.allclose(g.ravel(), pnt, atol=1e-4)


def test_settled_split_and_albedo_aging():
    p, scfg = state.load_params()
    from tests.test_snow_state import _lattice, _forcing
    lat = _lattice()
    s = state.new_state(lat["elev"].shape, np.full((4, 4), 60.0), p["min_depth_in"], lat["elev"] != -32768)
    s = state.step(s, _forcing((4, 4), precip_in=1.5), lat, p, scfg)
    for _ in range(7):
        s = state.step(s, _forcing((4, 4)), lat, p, scfg)
    assert s["days"][2, 0] == 7 and s["cls"][2, 0] == state.CID["settled"]
    s = state.step(s, _forcing((4, 4)), lat, p, scfg)
    assert s["cls"][2, 0] == state.CID["settled_late"]
    for _ in range(7):
        s = state.step(s, _forcing((4, 4)), lat, p, scfg)
    assert s["cls"][2, 0] == state.CID["old"]
    # the same sun crusts old snow faster than fresh (lower albedo absorbs more)
    fresh = state.new_state(lat["elev"].shape, np.full((4, 4), 60.0), p["min_depth_in"], lat["elev"] != -32768)
    fresh["days"][:] = 0
    aged = state.new_state(lat["elev"].shape, np.full((4, 4), 60.0), p["min_depth_in"], lat["elev"] != -32768)
    aged["days"][:] = 10
    f = _forcing((4, 4), solar_mj=6.0, tmax_c=1.0, tmin_c=-4.0)
    assert state.step(aged, f, lat, p, scfg)["solar_mj"][2, 1] > state.step(fresh, f, lat, p, scfg)["solar_mj"][2, 1]


def test_wind_exposure_scales_the_speed(tmp_path, monkeypatch):
    pytest.importorskip("pyproj")
    from tests.test_snow_state import _lattice, _write_gz
    import r2sync
    from snow import forcing, store
    monkeypatch.setattr(r2sync, "load_env", lambda: None)
    monkeypatch.setattr(store, "_ENV", None)
    monkeypatch.setattr(store, "SNOW_DIR", str(tmp_path))
    meta = {"crs": "EPSG:26910", "shape": [4, 4], "transform": [1000.0, 0.0, 670000.0, 0.0, -1000.0, 5280000.0], "zones": {}}
    lat = _lattice()
    lat["sx"] = np.zeros((8, 4, 4), np.int8)
    lat["sx"][4, 1, :] = 30                              # row 1 sheltered from a south wind (Sx +30 toward S)
    lat["sx"][4, 2, :] = -20                             # row 2 exposed to it
    lat["horizon"] = np.zeros((8, 4, 4), np.uint8)
    latlon = forcing.lattice_latlon(meta)
    day = dt.date(2026, 1, 15)
    grid = lambda v, n=64, scale=1: {"n": n, "scale": scale, "unit": "x", "data": [v] * (n * n)}  # noqa: E731
    valid = ["2026-01-15T%02d:00" % h for h in range(0, 24, 3)]
    steps = list(range(3, 27, 3))
    ndfd = {"sky": {"steps": steps, "valid_utc": valid, "grids": {str(s): grid(50) for s in steps}},
            "wspd": {"steps": steps, "valid_utc": valid, "grids": {str(s): grid(28) for s in steps}},       # 28 mph: just over wind_mph
            "wdir": {"steps": steps, "valid_utc": valid, "grids": {str(s): grid(180) for s in steps}}}
    _write_gz(str(tmp_path / "archive" / "2026-01-15" / "daily.json.gz"), {"ndfd": {"fields": ndfd}})
    p, scfg = state.load_params()
    f = state.day_forcing(day, lat, meta, latlon, -8, scfg, p, lambda *a: None)
    assert f["wind_h"][0, 0] == 15 and f["wind_h"][1, 0] == 0 and f["wind_h"][2, 0] == 15     # sheltered row drops below the threshold


def test_wind_threshold_depends_on_the_surface():
    """dry snow transports above wind_mph_dry, a wet surface only above wind_mph_wet, a crust never (Li & Pomeroy 1997)"""
    from tests.test_snow_state import _lattice, _forcing
    p, scfg = state.load_params()
    lat = _lattice()
    valid = lat["elev"] != -32768

    def surface(cls_name):
        s = state.new_state(lat["elev"].shape, np.full((4, 4), 60.0), p["min_depth_in"], valid)
        s["cls"][valid] = state.CID[cls_name]
        s["days"][:] = 5
        return s
    # a day with 9 h above the dry threshold, of which 3 h above the wet one
    f = _forcing((4, 4), wind_h=9.0, wind_h_wet=3.0)
    assert state.step(surface("settled"), f, lat, p, scfg)["wind_h"][2, 0] == 9
    assert state.step(surface("melt_freeze"), f, lat, p, scfg)["wind_h"][2, 0] == 3
    assert state.step(surface("rain_crust"), f, lat, p, scfg)["wind_h"][2, 0] == 0
    assert state.step(surface("rain_crust"), f, lat, p, scfg)["cls"][2, 0] != state.CID["wind"]
    # without the wet count in the forcing (old replay caches) the dry count stands in
    f1 = _forcing((4, 4), wind_h=9.0)
    assert state.step(surface("melt_freeze"), f1, lat, p, scfg)["wind_h"][2, 0] == 9


def test_albedo_decays_faster_when_melting():
    p, _ = state.load_params()
    days = np.array([0, 1, 8, 30], np.uint8)
    cold = state.albedo_aged(days, None, np.full(4, -3.0), p)
    melt = state.albedo_aged(days, None, np.full(4, 2.0), p)
    assert cold[0] == pytest.approx(p["albedo_fresh"]) and melt[0] == pytest.approx(p["albedo_fresh"])
    assert cold[2] == pytest.approx(0.85 * 0.94 ** (8 ** 0.58), rel=1e-3) and melt[2] == pytest.approx(0.85 * 0.82 ** (8 ** 0.46), rel=1e-3)
    assert (melt[1:] < cold[1:]).all() and (np.diff(cold) < 0).all()
    assert 0.65 < cold[2] < 0.72 and 0.48 < melt[2] < 0.55                 # 0.69 cold, 0.51 melting at 8 days (lit_review item 4)
