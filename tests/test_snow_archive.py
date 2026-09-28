"""snow/archive.py, snow/avyproducts.py, snow/observations.py and values.read_grid, all without the network."""
import datetime as dt
import gzip
import json
import os
import time

import numpy as np

import values
from snow import archive, avyproducts, observations


def test_read_grid_round_trips_write_grid(tmp_path, monkeypatch):
    monkeypatch.setattr(values, "OUT_DIR", str(tmp_path))
    a = np.full((512, 512), 12.34, np.float32)
    a[:256, :] = np.nan
    values.write_grid("t", a, unit="ft", scale=10)
    payload, q = values.read_grid("t")
    assert payload["unit"] == "ft" and payload["scale"] == 10 and q.shape == (256, 256)
    assert (q[:128] == -1).all() and (q[128:] == 1).all()          # 12.34 / 10 rounds to 1; NaN blocks are nodata
    assert values.read_grid("missing") is None


def test_block_mean_ignores_nodata():
    q = np.array([[-1, -1, 4, 6], [-1, -1, 4, 6], [2, 2, -1, -1], [4, 4, -1, -1]])
    m = archive.block_mean(q, 2)
    assert m.tolist() == [[-1, 5], [3, -1]]
    assert archive.block_mean(q, 4).tolist() == q.tolist()


def test_compact_station_keeps_the_current_reading_only():
    rec = {"id": "X", "name": "X", "src": "NWS", "lat": 47.0, "lon": -121.0, "elev": 4000,
           "temp": {"now": 28, "max": 33, "min": 20, "spark": [1, 2, 3]}, "wind": {"spd": 5, "gust": 12, "dir": 240, "max_gust": 30},
           "rh": 80, "precip": {"1": 0.05, "24": 1.2}, "snow": {"1": 0.5}, "swe": {}, "depth": 40}
    c = archive.compact_station(rec)
    assert c == {"id": "X", "name": "X", "src": "NWS", "lat": 47.0, "lon": -121.0, "elev": 4000, "depth": 40,
                 "temp": 28, "wind": {"spd": 5, "gust": 12, "dir": 240}, "rh": 80, "p1": 0.05, "s1": 0.5}
    assert archive.compact_station({"id": "Y", "precip": {}, "snow": {}, "swe": {}}) == {"id": "Y"}


def test_pack_snotel_epochs_and_staleness():
    t = dt.datetime(2026, 1, 5, 12, 0)
    last = {"t": time.time(), "now": t, "sites": [{"id": "A"}], "series": {"A": {"SNWD": [(t, 40.0)]}}, "med": {}}
    p = archive.pack_snotel(last)
    assert p["series"]["A"]["SNWD"] == [[int(t.replace(tzinfo=dt.timezone.utc).timestamp()), 40.0]]
    assert p["now_utc"] == "2026-01-05T12:00"
    assert archive.pack_snotel(dict(last, t=time.time() - 3 * 3600)) is None
    assert archive.pack_snotel({"t": 0, "series": None}) is None


def test_product_key_ignores_volatile_fields():
    p = {"id": 5, "published_time": "2026-01-05T18:00", "bottom_line": "Careful.", "danger": [1, 2, 2], "fetched_at": "x"}
    assert avyproducts.product_key(p) == avyproducts.product_key(dict(p, fetched_at="y"))
    assert avyproducts.product_key(p) != avyproducts.product_key(dict(p, bottom_line="Fine."))
    assert avyproducts.product_key(p).startswith("5_")
    assert avyproducts.product_key({"x": 1}).startswith("na_")


def test_products_build_writes_new_versions_only(tmp_path, monkeypatch):
    monkeypatch.setattr(avyproducts, "zones", lambda log: [("NWAC", 1130, "Stevens Pass"), ("NWAC", 1131, "Snoqualmie Pass")])
    calls = []
    prods = {1130: {"id": 1, "bottom_line": "a"}, 1131: None}
    monkeypatch.setattr(avyproducts, "fetch", lambda c, z: calls.append(z) or prods[z])
    have = set()
    assert avyproducts.build(str(tmp_path), have, lambda *a: None) == 1
    fn = "products/NWAC_1130_" + avyproducts.product_key(prods[1130]) + ".json"
    assert have == {fn} and json.load(open(tmp_path / fn)) == prods[1130]
    assert avyproducts.build(str(tmp_path), have, lambda *a: None) == 0      # unchanged: nothing new
    prods[1130] = {"id": 1, "bottom_line": "b"}
    assert avyproducts.build(str(tmp_path), have, lambda *a: None) == 1      # edited: a second file
    have.update("products/NWAC_1130_%d" % i for i in range(avyproducts.MAX_PER_ZONE_DAY))
    prods[1130] = {"id": 1, "bottom_line": "c"}
    n = len(calls)
    assert avyproducts.build(str(tmp_path), have, lambda *a: None) == 0 and len(calls) == n + 1   # cap: 1131 still fetched, 1130 not


def test_products_fetch_failure_does_not_stop_the_rest(tmp_path, monkeypatch):
    monkeypatch.setattr(avyproducts, "zones", lambda log: [("NWAC", 1, "a"), ("NWAC", 2, "b")])

    def fetch(c, z):
        if z == 1:
            raise OSError("boom")
        return {"id": 2}
    monkeypatch.setattr(avyproducts, "fetch", fetch)
    assert avyproducts.build(str(tmp_path), set(), lambda *a: None) == 1


def test_observations_need_an_origin(tmp_path, monkeypatch):
    monkeypatch.delenv("NAC_OBS_ORIGIN", raising=False)
    msgs = []
    assert observations.build(str(tmp_path), msgs.append) == 0
    assert "skipped" in msgs[0] and not os.path.exists(tmp_path / "obs")


def _fake_data(data, vdir, monkeypatch):
    os.makedirs(data, exist_ok=True)
    monkeypatch.setattr(values, "OUT_DIR", vdir)

    def js(name, var, obj):
        with open(os.path.join(data, name), "w", encoding="utf-8") as f:
            f.write("window.%s = %s;\n" % (var, json.dumps(obj)))
    js("stations.js", "STATIONS", {"updated_t": 1, "windows": [1, 3, 6, 12, 24],
                                   "stations": [{"id": "S", "lat": 47, "lon": -121, "temp": {"now": 30}, "precip": {"1": 0.1}, "snow": {}, "swe": {}}]})
    js("freezing.js", "FREEZING", {"run_utc": "2026-01-05T12:00", "hours": [{"h": 0}]})
    js("mrms.js", "MRMS", {"windows": {"1": {"valid_utc": "2026-01-05T13:00"}, "24": {"valid_utc": "2026-01-05T13:00"}}})
    js("forecast.js", "FORECAST", {"issued_utc": "2026-01-05T11:00", "windows": {"snow_24": {"max": 3}}})
    js("snodas.js", "SNODAS", {"date": "2026-01-04"})
    js("avalanche.js", "AVALANCHE", {"features": [{"properties": {"zone_id": 1130, "name": "Stevens", "center_id": "NWAC", "danger": "high",
                                                                  "danger_level": 4, "start_date": "a", "end_date": "b", "warning": None}}]})
    fz = np.full((512, 512), 5000.0, np.float32)
    values.write_grid("fz_0", fz, unit="ft", scale=10)
    values.write_grid("fz_3", fz, unit="ft", scale=10)
    values.write_grid("mrms_1", np.zeros((512, 512), np.float32))
    values.write_grid("mrms_24", np.ones((512, 512), np.float32))
    values.write_grid("fc_snow_24", np.ones((512, 512), np.float32), unit="in")
    values.write_grid("snodas_depth", np.ones((512, 512), np.float32) * 30, unit="in", scale=0.1)


def test_build_writes_hourly_then_daily_once(tmp_path, monkeypatch):
    import r2sync
    import snotel
    data = str(tmp_path / "data")
    _fake_data(data, os.path.join(data, "values"), monkeypatch)
    monkeypatch.setattr(archive, "DATA", data)
    monkeypatch.setattr(archive, "ARCHIVE", str(tmp_path / "archive"))
    monkeypatch.setattr(r2sync, "load_env", lambda: None)           # local mode: the day folder on disk is the inventory
    t = dt.datetime(2026, 1, 5, 12, 0)
    monkeypatch.setattr(snotel, "_LAST", {"t": time.time(), "now": t, "sites": [{"id": "A"}], "series": {"A": {"WTEQ": [(t, 10.0)]}}, "med": {}})
    monkeypatch.setattr(avyproducts, "zones", lambda log: [("NWAC", 1130, "Stevens Pass")])
    monkeypatch.setattr(avyproducts, "fetch", lambda c, z: {"id": 9, "bottom_line": "x"})
    monkeypatch.delenv("NAC_OBS_ORIGIN", raising=False)
    msgs = []
    out = archive.build(msgs.append)
    day = dt.datetime.now().strftime("%Y-%m-%d")
    ddir = tmp_path / "archive" / day
    hh = dt.datetime.now().strftime("%H") + ".json.gz"
    assert (ddir / hh).exists() and (ddir / "daily.json.gz").exists()
    assert "daily" in out and "products +1" in out
    h = json.load(gzip.open(ddir / hh, "rt"))
    assert h["stations"] == [{"id": "S", "lat": 47, "lon": -121, "temp": 30, "p1": 0.1}]
    assert h["fz0"]["n"] == 64 and len(h["fz0"]["data"]) == 64 * 64 and h["fz0"]["data"][0] == 500 and h["fz0"]["run_utc"] == "2026-01-05T12:00"
    assert h["mrms1"]["n"] == 256 and h["mrms1"]["valid_utc"] == "2026-01-05T13:00"
    assert h["zones"][0]["zone_id"] == 1130 and h["zones"][0]["danger_level"] == 4
    d = json.load(gzip.open(ddir / "daily.json.gz", "rt"))
    assert d["snotel"]["series"]["A"]["WTEQ"][0][1] == 10.0
    assert set(d["freezing"]["grids"]) == {"0", "3"} and d["forecast"]["grids"]["snow_24"]["data"][0] == 100
    assert d["mrms24"]["data"][0] == 100 and d["snodas"]["grids"]["depth"]["n"] == 128 and d["snodas"]["grids"]["depth"]["data"][0] == 300
    assert d["stations"][0]["id"] == "S" and d["windows"] == [1, 3, 6, 12, 24]
    assert len(list((ddir / "products").iterdir())) == 1
    # a second run in the same day: another hourly file at most, no second daily, no duplicate product
    out2 = archive.build(msgs.append)
    assert "daily" not in out2 and "products +0" in out2
    assert (ddir / "daily.json.gz").exists() and len(list((ddir / "products").iterdir())) == 1


def test_build_survives_missing_inputs(tmp_path, monkeypatch):
    import r2sync
    monkeypatch.setattr(archive, "DATA", str(tmp_path / "nodata"))
    monkeypatch.setattr(archive, "ARCHIVE", str(tmp_path / "archive"))
    monkeypatch.setattr(values, "OUT_DIR", str(tmp_path / "nodata" / "values"))
    monkeypatch.setattr(r2sync, "load_env", lambda: None)
    monkeypatch.setattr(avyproducts, "zones", lambda log: [])
    out = archive.build(lambda *a: None)
    assert "daily" in out
    day = dt.datetime.now().strftime("%Y-%m-%d")
    d = json.load(gzip.open(tmp_path / "archive" / day / "daily.json.gz", "rt"))
    assert "stations" not in d and "freezing" not in d
