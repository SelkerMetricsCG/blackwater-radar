"""snow/replay.py and snow/fit.py: subset windows, a replay over a fake archive, and a fit that recovers a lower
sun-crust threshold from residuals (forcing synthesised, so the test controls the solar load)."""
import datetime as dt
import gzip
import json
import os
import shutil

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("pyproj")
from snow import fit, ledger, replay, state, store  # noqa: E402

META = {"crs": "EPSG:26910", "shape": [12, 12], "transform": [1000.0, 0.0, 670000.0, 0.0, -1000.0, 5280000.0], "cell_m": 1000,
        "zones": {"1130": {"name": "Stevens Pass"}}}


def _lattice(n=12):
    elev = np.full((n, n), 1800, np.int16)
    aspect = np.zeros((n, n), np.int16)
    aspect[:, ::2] = 180                                         # even columns south, odd north
    return {"elev": elev, "slope": np.full((n, n), 30, np.uint8), "aspect": aspect, "band": np.full((n, n), 2, np.uint8),
            "zone": np.full((n, n), 1130, np.int32), "canopy": np.full((n, n), 10, np.uint8), "crest_km": np.zeros((n, n), np.int16)}


def _local_store(tmp_path, monkeypatch):
    import r2sync
    monkeypatch.setattr(r2sync, "load_env", lambda: None)
    monkeypatch.setattr(store, "_ENV", None)
    monkeypatch.setattr(store, "SNOW_DIR", str(tmp_path))


def test_subset_windows_index_and_near():
    lat = _lattice()
    sub = replay.Subset(lat, META, [(2, 2), (9, 9)], 1)
    assert len(sub.flat) == 18 and sub.lat["aspect"].shape == (18,) and sub.latlon[0].shape == (18,)
    assert sub.index_of(2, 2) >= 0 and sub.index_of(3, 3) >= 0 and sub.index_of(5, 5) == -1
    near = sub.near(2, 2, 1.0)
    assert near.sum() == 5                                        # the plus shape within one cell
    assert 47 < sub.latlon[0][0] < 48


def _write_gz(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(obj, f)


def test_replay_runs_on_a_fake_archive(tmp_path, monkeypatch):
    _local_store(tmp_path, monkeypatch)
    grid = lambda v, n=64, scale=1: {"n": n, "scale": scale, "unit": "x", "data": [v] * (n * n)}  # noqa: E731
    for d in ("2026-03-01", "2026-03-02", "2026-03-03"):
        steps = list(range(3, 27, 3))
        valid = ["%sT%02d:00" % (d, h) for h in range(0, 24, 3)]
        ndfd = {k: {"steps": steps, "valid_utc": valid, "grids": {str(s): grid(v) for s in steps}} for k, v in (("sky", 0), ("td", 10), ("wspd", 5), ("wdir", 180))}
        _write_gz(str(tmp_path / "archive" / d / "daily.json.gz"), {"ndfd": {"fields": ndfd}, "forecast": {"grids": {"maxt": grid(25), "mint": grid(10)}},
                                                                     "mrms24": grid(0, 256, 0.01), "snodas": {"grids": {"depth": grid(400, 128, 0.1)}}})
        _write_gz(str(tmp_path / "archive" / d / "12.json.gz"), {"fz0": grid(300, 64, 10)})
    lat = _lattice()
    sub = replay.Subset(lat, META, [(5, 5)], 2)
    p, scfg = state.load_params()
    cache = str(tmp_path / "cache")
    cls = replay.run(dt.date(2026, 3, 1), dt.date(2026, 3, 3), p, sub, scfg, tz=-8, log=lambda *a: None, cache_dir=cache)
    assert sorted(cls) == ["2026-03-01", "2026-03-02", "2026-03-03"] and cls["2026-03-03"].shape == (25,)
    assert set(np.unique(cls["2026-03-03"])) <= set(range(len(state.CLASSES)))
    assert len(os.listdir(cache)) == 3                          # one forcing file per day
    # cached forcing is reused: a second run with the archive gone still works
    shutil.rmtree(tmp_path / "archive")
    cls2 = replay.run(dt.date(2026, 3, 1), dt.date(2026, 3, 3), p, sub, scfg, tz=-8, log=lambda *a: None, cache_dir=cache)
    assert (cls2["2026-03-03"] == cls["2026-03-03"]).all()


def _synthetic_forcing(day, subset, p, scfg, tz, log=print, cache_dir=None, use_cache=True):
    n = len(subset.flat)
    f = {k: np.zeros(n, np.float32) for k in replay.FORCING_KEYS}
    f["fzl_ft"][:] = 3000
    f["tmax_c"][:] = 0            # warm enough that all the sun counts toward a crust
    f["tmin_c"][:] = -4
    f["td_night_c"][:] = -12
    f["depth_in"][:] = 40
    f["snotel_hn24_in"][:] = np.nan
    f["site_elev_m"][:] = np.nan          # no sites: no lapse to the cell
    if day >= dt.date(2026, 1, 14):                               # 3.5 MJ a day on the south-facing cells from Jan 14 (old snow absorbs 1.6x)
        f["solar_mj"] = np.where(subset.lat["aspect"] == 180, 3.5, 0.0).astype(np.float32)
    return f


def test_fit_lowers_the_sun_crust_threshold(tmp_path, monkeypatch):
    _local_store(tmp_path, monkeypatch)
    monkeypatch.setattr(replay, "forcing_for", _synthetic_forcing)
    lat = _lattice()
    from snow import forcing
    latg, long_ = forcing.lattice_latlon(META)
    recs = []
    d = "2026-01-15"                                              # two sunny days: ~10.4 MJ absorbed-equivalent on south cells, under the 12 MJ default
    obs = ledger.append(recs, [{"surface": "sun_crust", "lat": float(latg[5, 4]), "lon": float(long_[5, 4]), "band": "above", "aspects": ["S"], "confidence": 1.0}], d, "obs")
    ledger.append(recs, [{"obs_id": obs[0]["id"], "observed": "sun_crust", "predicted": "settled", "frac": 0.0, "match": False, "how": "near",
                          "cell": [5, 4], "radius_m": 300}], d, "residual")
    items = fit.residual_items(recs, META)
    assert len(items) == 1 and items[0]["r"] == 5 and items[0]["radius"] == 0.3
    out = fit.fit(recs, lat, META, log=lambda *a: None, min_residuals=1, tol=0.1, cache_dir=str(tmp_path / "c"), use_cache=False)
    assert out["loss_before"] == 1.0 and out["loss_after"] == 0.0
    assert out["changes"] and out["changes"][0]["param"] == "solar_crust_mj" and out["changes"][0]["to"] == 10.0
    assert out["params"]["solar_crust_mj"] == 10.0
    # apply: the config value line changes, everything else stays; a param record lands in the ledger
    cfg_copy = tmp_path / "snow_config.yaml"
    shutil.copyfile(fit.CONFIG, cfg_copy)
    monkeypatch.setattr(fit, "CONFIG", str(cfg_copy))
    before = open(cfg_copy, encoding="utf-8").read()
    n = fit.apply(dict(out, residual_ids=[items[0]["id"]]), recs, d, lambda *a: None)
    after = open(cfg_copy, encoding="utf-8").read()
    assert n == 1 and "  solar_crust_mj: {value: 10, bounds: [6, 30]" in after and before.count("\n") == after.count("\n")
    assert sum(1 for r in recs if r["kind"] == "param") == 1 and recs[-1]["from"] == 12 and recs[-1]["to"] == 10.0
    import yaml
    assert yaml.safe_load(after)["state"]["solar_crust_mj"]["value"] == 10


def test_fit_needs_enough_residuals(tmp_path, monkeypatch):
    _local_store(tmp_path, monkeypatch)
    out = fit.fit([], _lattice(), META, log=lambda *a: None)
    assert out["changes"] == [] and out["skipped"]
