"""snow/state.py: class transitions on a synthetic lattice, the zone summary, forcing from a fake archive day."""
import datetime as dt
import gzip
import json
import os

import pytest

np = pytest.importorskip("numpy")
from snow import state  # noqa: E402


def _lattice(n=4):
    # four columns: N-facing 30 deg, S-facing 30 deg, flat, off-lattice; rows are elevations 500..3500 m
    elev = np.tile(np.array([[500], [1500], [2500], [3500]]), (1, n)).astype(np.int16)
    elev[:, 3] = -32768
    slope = np.array([[30, 30, 0, 255]] * 4, np.uint8)
    aspect = np.array([[0, 180, -1, -1]] * 4, np.int16)
    band = np.array([[0, 0, 0, 255], [1, 1, 1, 255], [2, 2, 2, 255], [2, 2, 2, 255]], np.uint8)
    zone = np.full((4, n), 1130, np.int32)
    zone[:, 3] = -1
    return {"elev": elev, "slope": slope, "aspect": aspect, "band": band, "zone": zone}


def _forcing(shape, **kw):
    f = {"precip_in": 0.0, "fzl_ft": 2000.0, "tmax_c": -5.0, "tmin_c": -10.0, "cloud_night": 0.0, "td_night_c": -12.0,
         "wind_night_ms": 1.0, "wind_h": 0.0, "solar_mj": 0.0, "depth_in": 40.0}
    f.update(kw)
    return {k: np.full(shape, v, np.float32) for k, v in f.items()}


def test_storm_then_sun_crust_on_south_and_pockets_on_north():
    p, scfg = state.load_params()
    lat = _lattice()
    valid = lat["elev"] != -32768
    s = state.new_state(lat["elev"].shape, np.full((4, 4), 40.0), p["min_depth_in"], valid)
    assert (s["cls"][valid] == state.CID["old"]).all() and s["cls"][0, 3] == 255
    # 1 in of liquid at -5 C, freezing level 4000 ft: snow level 3000 ft, so the 500 m (1640 ft) row gets rain
    s = state.step(s, _forcing((4, 4), precip_in=1.0, fzl_ft=4000.0), lat, p, scfg)
    assert s["cls"][2, 0] == state.CID["fresh"] and s["hn24_cm"][2, 0] > 20         # 1 in x SLR 13 x 2.54
    assert s["hn24_cm"][0, 0] == 0 and s["cls"][0, 0] == state.CID["rain_crust"]
    # then a week of clear cold days: the south slope crusts, the north slope stays powder
    for _ in range(7):
        solar = np.zeros((4, 4), np.float32)
        solar[:, 1] = 5.0
        s = state.step(s, _forcing((4, 4), solar_mj=solar), lat, p, scfg)
    assert s["cls"][2, 1] == state.CID["sun_crust"] and s["cls"][2, 0] == state.CID["settled"] and s["days"][2, 0] == 7
    # then wind: north slope goes wind-affected; with a direction it is loaded or scoured; then a dusting on the crust
    s = state.step(s, _forcing((4, 4), wind_h=9.0), lat, p, scfg)
    assert s["cls"][2, 0] == state.CID["wind"]
    lee = np.zeros((4, 4), np.float32)
    lee[:, 0] = 9.0
    s2 = state.step(s, dict(_forcing((4, 4), wind_h=9.0), wind_lee_h=lee), lat, p, scfg)
    assert s2["cls"][2, 0] == state.CID["wind_loaded"] and s2["cls"][2, 1] == state.CID["sun_crust"]
    s2 = state.step(s, dict(_forcing((4, 4), wind_h=9.0), wind_wwd_h=lee), lat, p, scfg)
    assert s2["cls"][2, 0] == state.CID["wind_scoured"]
    s = state.step(s, _forcing((4, 4), precip_in=0.1), lat, p, scfg)
    assert s["cls"][2, 1] == state.CID["dust_on_crust"] and s["cls"][2, 0] == state.CID["dust_on_crust"]
    # snow gone below
    s = state.step(s, _forcing((4, 4), depth_in=1.0), lat, p, scfg)
    assert (s["cls"][valid] == state.CID["no_snow"]).all() and s["cls"][0, 3] == 255


def test_spring_corn_then_isothermal():
    p, scfg = state.load_params()
    lat = _lattice()
    s = state.new_state(lat["elev"].shape, np.full((4, 4), 60.0), p["min_depth_in"], lat["elev"] != -32768)
    s = state.step(s, _forcing((4, 4), tmax_c=6.0, tmin_c=-4.0, solar_mj=15.0), lat, p, scfg)
    assert s["cls"][2, 1] == state.CID["melt_freeze"] and s["refreeze"][2, 1] >= p["refreeze_good"]
    for _ in range(p["isothermal_days"]):
        s = state.step(s, _forcing((4, 4), tmax_c=10.0, tmin_c=4.0, cloud_night=1.0, solar_mj=15.0), lat, p, scfg)
    assert s["cls"][2, 1] == state.CID["isothermal"] and s["melt_days"][2, 1] == p["isothermal_days"]


def test_fill_by_band_and_summary():
    lat = _lattice()
    f = state.fill_by_band({(1130, 0): 30.0, (1130, 2): 10.0}, lat["zone"], lat["band"], 20.0)
    assert f[0, 0] == 30 and f[1, 0] == 20 and f[3, 2] == 10
    p, scfg = state.load_params()
    s = state.new_state(lat["elev"].shape, np.full((4, 4), 40.0), p["min_depth_in"], lat["elev"] != -32768)
    out = state.summary(s, lat, {"zones": {"1130": {"name": "Stevens Pass"}}}, dt.date(2026, 1, 15))
    z = out["zones"]["1130"]
    assert z["name"] == "Stevens Pass" and z["cells"] == 12
    frac = np.array(z["frac"])                          # (band, octant, class)
    assert frac.shape == (3, 9, len(state.CLASSES)) and frac[0, 0, state.CID["old"]] == 1.0 and frac[0, 4, state.CID["old"]] == 1.0
    assert frac[0, 8, state.CID["old"]] == 1.0 and frac[0, 1].sum() == 0    # flat column counted; no NE cells


def _write_gz(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(obj, f)


def test_day_forcing_from_a_fake_archive(tmp_path, monkeypatch):
    pytest.importorskip("pyproj")
    import r2sync
    import region
    from snow import forcing, store
    monkeypatch.setattr(r2sync, "load_env", lambda: None)
    monkeypatch.setattr(store, "_ENV", None)
    monkeypatch.setattr(store, "SNOW_DIR", str(tmp_path))
    meta = {"crs": "EPSG:26910", "shape": [4, 4], "transform": [1000.0, 0.0, 670000.0, 0.0, -1000.0, 5280000.0], "zones": {}}
    lat = _lattice()
    latlon = forcing.lattice_latlon(meta)
    day = dt.date(2026, 1, 15)
    grid = lambda v, n=64, scale=1: {"n": n, "scale": scale, "unit": "x", "data": [v] * (n * n)}  # noqa: E731
    valid = ["2026-01-15T%02d:00" % h for h in range(0, 24, 3)]                    # UTC; local = h - 8
    steps = list(range(3, 27, 3))
    ndfd = {"sky": {"steps": steps, "valid_utc": valid, "grids": {str(s): grid(50) for s in steps}},
            "td": {"steps": steps, "valid_utc": valid, "grids": {str(s): grid(14) for s in steps}},          # 14 F = -10 C
            "wspd": {"steps": steps, "valid_utc": valid, "grids": {str(s): grid(30) for s in steps}},       # 30 mph: above wind_mph
            "wdir": {"steps": steps, "valid_utc": valid, "grids": {str(s): grid(180) for s in steps}}}      # from the south
    _write_gz(str(tmp_path / "archive" / "2026-01-15" / "daily.json.gz"),
              {"ndfd": {"fields": ndfd}, "forecast": {"grids": {"maxt": grid(20), "mint": grid(5)}}})
    t = lambda h: int(dt.datetime(2026, 1, 15, h, tzinfo=dt.timezone.utc).timestamp())  # noqa: E731
    site = {"id": "A", "lat": float(latlon[0][1, 1]), "lon": float(latlon[1][1, 1])}
    t16 = int(dt.datetime(2026, 1, 16, 7, tzinfo=dt.timezone.utc).timestamp())      # 23:00 local Jan 15: the window's end
    # newsnow needs a reading within its slack of both window ends (08:00 UTC Jan 15 .. 08:00 UTC Jan 16)
    series = {"A": {"SNWD": [[t(8), 40.0], [t(15), 44.0], [t(21), 52.0], [t16, 52.0]], "TOBS": [[t(9), 10.0], [t(15), 30.0], [t(21), 20.0]]}}
    _write_gz(str(tmp_path / "archive" / "2026-01-16" / "daily.json.gz"),
              {"snotel": {"sites": [site], "series": series}, "mrms24": grid(50, 256, 0.01), "snodas": {"grids": {"depth": grid(300, 128, 0.1)}}})
    for hh in ("06", "12"):
        _write_gz(str(tmp_path / "archive" / "2026-01-15" / ("%s.json.gz" % hh)), {"fz0": grid(300, 64, 10)})
    p, scfg = state.load_params()
    f = state.day_forcing(day, lat, meta, latlon, -8, scfg, p, lambda *a: None)
    assert f["precip_in"][1, 1] == pytest.approx(0.5) and f["fzl_ft"][1, 1] == 3000 and f["depth_in"][1, 1] == 30
    assert f["cloud_night"][1, 1] == pytest.approx(0.5) and f["td_night_c"][1, 1] == pytest.approx(-10, abs=0.01)
    assert f["wind_h"][1, 1] == 3 * 5 and f["wind_night_ms"][1, 1] == pytest.approx(30 * 0.44704)
    # south wind: the north-facing column is in the lee (loaded), the south-facing column windward (scoured), flat neither
    assert f["wind_lee_h"][1, 0] == 15 and f["wind_wwd_h"][1, 0] == 0
    assert f["wind_wwd_h"][1, 1] == 15 and f["wind_lee_h"][1, 1] == 0
    assert f["wind_lee_h"][1, 2] == 0 and f["wind_wwd_h"][1, 2] == 0
    # SNOTEL site sits in zone 1130 band 1: its day max/min (30/10 F) fill that band, NDFD (20/5 F) fills the others
    assert f["tmax_c"][1, 1] == pytest.approx((30 - 32) * 5 / 9) and f["tmax_c"][0, 0] == pytest.approx((20 - 32) * 5 / 9)
    assert f["snotel_hn24_in"][1, 1] == pytest.approx(12.0) and np.isnan(f["snotel_hn24_in"][0, 0])
    assert f["solar_mj"][1, 1] > f["solar_mj"][1, 0] > 0 and f["solar_mj"][0, 3] == 0


def test_aspect_within_wraps_around_north():
    a = np.array([350.0, 10.0, 90.0, -1.0, 180.0])
    assert state.aspect_within(a, 0.0, 30).tolist() == [True, True, False, False, False]
    assert state.aspect_within(a, 170.0, 60).tolist() == [False, False, False, False, True]


def test_class_png_and_index(tmp_path, monkeypatch):
    pytest.importorskip("pyproj")
    pytest.importorskip("PIL")
    import r2sync
    from snow import store
    monkeypatch.setattr(r2sync, "load_env", lambda: None)
    monkeypatch.setattr(store, "_ENV", None)
    monkeypatch.setattr(store, "SNOW_DIR", str(tmp_path))
    meta = {"crs": "EPSG:26910", "shape": [4, 4], "transform": [1000.0, 0.0, 670000.0, 0.0, -1000.0, 5280000.0]}
    cls = np.full((4, 4), state.CID["settled"], np.uint8)
    cls[:, 3] = 255
    cfg = {"bbox_lonlat": [-120.8, 47.6, -120.7, 47.7]}
    img, bounds = state.class_png(cls, meta, cfg, width=60)
    a = np.asarray(img)
    assert a.shape[2] == 4 and bounds == [[47.6, -120.8], [47.7, -120.7]] and 40 < a.shape[0] < 100
    assert (a[..., 3] == 255).sum() > 0 and (a[..., 3] == 0).sum() > 0        # some cells hit, some transparent
    hit = a[..., 3] == 255
    assert (a[hit][:, 0] == 0x6b).all()                                       # settled = #6baed6
    state.update_index("2026-01-15")
    idx = state.update_index("2026-01-14")
    assert idx == {"dates": ["2026-01-14", "2026-01-15"], "latest": "2026-01-15"}
    assert open(tmp_path / "state" / "index.js").read().startswith("window.SNOW_INDEX = ")
