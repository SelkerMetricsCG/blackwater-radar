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
    out = tfield.fields(hourlies, None, dt.date(2026, 1, 15), -8, lat, meta, latg, long_, lat["zone"], lat["band"], p, lambda *a: None)
    assert out and out["n"] == 20 and out["lapse_min"]["1130"] > 5          # +6 C/km: inverted
    assert out["tmin_c"][0, 0] < out["tmin_c"][9, 0] and abs(out["tmax_c"][0, 0] - 6.0) < 0.3
    assert abs(out["tmin_resid_c"]).max() < 0.5                             # a perfectly linear network leaves no residual
    assert tfield.fields(hourlies[:5], None, dt.date(2026, 1, 15), -8, lat, meta, latg, long_, lat["zone"], lat["band"], p, lambda *a: None) is None


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
