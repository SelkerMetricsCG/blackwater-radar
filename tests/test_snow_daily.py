"""snow/ledger.py, snow/llm.py (with a fake API), snow/score.py and snow/daily.py end to end on a fake archive."""
import datetime as dt
import gzip
import json
import os

import pytest

np = pytest.importorskip("numpy")
from snow import daily, ledger, llm, score, state, store  # noqa: E402


def _local_store(tmp_path, monkeypatch):
    import r2sync
    monkeypatch.setattr(r2sync, "load_env", lambda: None)
    monkeypatch.setattr(store, "_ENV", None)
    monkeypatch.setattr(store, "SNOW_DIR", str(tmp_path))


def test_ledger_append_recent_layers(tmp_path, monkeypatch):
    _local_store(tmp_path, monkeypatch)
    recs = ledger.load(lambda *a: None)
    assert recs == []
    ledger.append(recs, [{"name": "Dec 12 facets", "status": "active", "last": "2026-01-02"}], "2026-01-02", "layer")
    ledger.append(recs, [{"surface": "fresh"}, {"surface": "wind"}], "2026-01-10", "obs")
    ledger.append(recs, [{"name": "Dec 12 facets", "status": "active", "last": "2026-01-10"}], "2026-01-10", "layer")
    assert [r["id"] for r in recs] == ["layer_2026-01-02_0", "obs_2026-01-10_0", "obs_2026-01-10_1", "layer_2026-01-10_0"]
    assert len(ledger.recent(recs, "2026-01-10", 5)) == 3 and len(ledger.recent(recs, "2026-01-10", 5, ("obs",))) == 2
    assert ledger.layers(recs)["Dec 12 facets"]["last"] == "2026-01-10"
    assert ledger.layers(recs, today="2026-02-15")["Dec 12 facets"]["status"] == "dormant"
    assert ledger.layers(recs, today="2026-01-20")["Dec 12 facets"]["status"] == "active"
    ledger.save(recs, upload=False)
    assert len(ledger.load()) == 4


def test_llm_call_without_key_is_skipped(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    msgs = []
    assert llm.call("s", "u", llm.EXTRACT_SCHEMA, msgs.append) is None and "skipped" in msgs[0]


class _Block:
    type = "text"

    def __init__(self, text):
        self.text = text


class _Resp:
    def __init__(self, text, stop="end_turn"):
        self.content = [_Block(text)]
        self.stop_reason = stop
        self.usage = type("U", (), {"input_tokens": 10, "output_tokens": 5})()


def _fake_client(monkeypatch, payload, stop="end_turn"):
    calls = []

    class Msgs:
        def create(self, **kw):
            calls.append(kw)
            return _Resp(json.dumps(payload), stop)

    class C:
        messages = Msgs()
    monkeypatch.setattr(llm, "client", lambda: C())
    return calls


def test_llm_call_parses_and_handles_refusal(monkeypatch):
    calls = _fake_client(monkeypatch, {"a": 1})
    assert llm.call("sys", "usr", {"type": "object"}, lambda *a: None) == {"a": 1}
    assert calls[0]["output_config"]["format"]["type"] == "json_schema" and calls[0]["system"] == "sys"
    _fake_client(monkeypatch, {"a": 1}, stop="refusal")
    assert llm.call("sys", "usr", {"type": "object"}, lambda *a: None) is None


def _lattice():
    elev = np.tile(np.array([[500], [1500], [2500], [3500]]), (1, 4)).astype(np.int16)
    elev[:, 3] = -32768
    return {"elev": elev, "slope": np.array([[30, 30, 0, 255]] * 4, np.uint8), "aspect": np.array([[0, 180, -1, -1]] * 4, np.int16),
            "band": np.array([[0, 0, 0, 255], [1, 1, 1, 255], [2, 2, 2, 255], [2, 2, 2, 255]], np.uint8),
            "zone": np.where(elev == -32768, -1, 1130).astype(np.int32)}


def test_score_neighbourhood_place_and_group(monkeypatch):
    pytest.importorskip("pyproj")
    from snow import forcing
    meta = {"crs": "EPSG:26910", "shape": [4, 4], "transform": [1000.0, 0.0, 670000.0, 0.0, -1000.0, 5280000.0], "cell_m": 1000,
            "zones": {"1130": {"name": "Stevens Pass"}}}
    lat = _lattice()
    latg, long_ = forcing.lattice_latlon(meta)
    cls = np.full((4, 4), state.CID["settled"], np.uint8)
    cls[:, 1] = state.CID["sun_crust"]          # the south-facing column
    cls[:, 3] = 255
    st = {"days": np.full((4, 4), 5.0), "hn24_cm": np.zeros((4, 4))}
    monkey_places = {"Skyline Ridge": [float(latg[2, 0]), float(long_[2, 0])]}
    import snow.score as sc
    monkeypatch.setattr(sc, "places", lambda: monkey_places)
    obs = [{"id": "o1", "surface": "sun_crust", "lat": float(latg[2, 1]), "lon": float(long_[2, 1]), "aspects": ["S"], "band": "above", "confidence": 0.8},
           {"id": "o2", "surface": "settled", "lat": None, "lon": None, "location": "north side of Skyline Ridge", "aspects": ["N"], "band": "above"},
           {"id": "o3", "surface": "fresh", "zone": "Stevens Pass", "band": "above", "aspects": ["N"]},
           {"id": "o4", "surface": "unknown", "zone": "Stevens Pass", "band": "above", "aspects": ["N"]},
           {"id": "o5", "surface": "wind", "zone": "Nowhere", "band": "above", "aspects": []},
           {"id": "o6", "surface": "settled", "lat": float(latg[2, 1]), "lon": float(long_[2, 1]), "aspects": ["all"], "band": None}]
    res = sc.score(obs, cls, st, lat, meta, lambda *a: None, radius_point_m=300.0, radius_place_m=1500.0)
    by = {r["obs_id"]: r for r in res}
    assert set(by) == {"o1", "o2", "o3", "o6"}
    assert by["o1"]["how"] == "near" and by["o1"]["match"] and by["o1"]["frac"] == 1.0 and by["o1"]["state"]["days"] == 5.0
    assert by["o2"]["how"] == "place" and by["o2"]["place"] == "Skyline Ridge" and by["o2"]["filtered"] and by["o2"]["match"]
    assert by["o3"]["how"] == "group" and not by["o3"]["match"] and by["o3"]["predicted"] == "settled" and by["o3"]["frac"] == 0.0
    # o6 sits on the crusted south column but names no aspect: its 300 m neighbourhood is that one cell, so frac 0
    assert by["o6"]["how"] == "near" and by["o6"]["frac"] == 0.0 and not by["o6"]["filtered"]


def test_resolve_place_prefers_the_longest_name():
    from snow import score as sc
    table = {"Baker": [48.8, -121.7], "Mount Baker": [48.857, -121.679]}
    assert sc.resolve_place("skinned up toward mount baker today", table)[2] == "Mount Baker"
    assert sc.resolve_place("nothing here", table) is None and sc.resolve_place(None, table) is None
    assert len(sc.places()) > 30 and all(len(v) == 2 for v in sc.places().values())


def test_daily_end_to_end_with_fake_llm(tmp_path, monkeypatch):
    pytest.importorskip("pyproj")
    _local_store(tmp_path, monkeypatch)
    from snow import forcing
    d = "2026-01-15"
    meta = {"crs": "EPSG:26910", "shape": [4, 4], "transform": [1000.0, 0.0, 670000.0, 0.0, -1000.0, 5280000.0], "zones": {"1130": {"name": "Stevens Pass"}}}
    lat = _lattice()
    latg, long_ = forcing.lattice_latlon(meta)
    os.makedirs(tmp_path / "static"); os.makedirs(tmp_path / "state"); os.makedirs(tmp_path / "archive" / d / "products")
    json.dump(meta, open(tmp_path / "static" / "lattice.json", "w"))
    np.savez(tmp_path / "static" / "lattice.npz", **lat)
    cls = np.full((4, 4), state.CID["settled"], np.uint8)
    np.savez(tmp_path / "state" / ("%s_cls.npz" % d), cls=cls)
    np.savez(tmp_path / "state" / "latest.npz", day=d, cls=cls, days=np.full((4, 4), 3.0), hn24_cm=np.zeros((4, 4)))
    json.dump({"date": d, "zones": {"1130": {"name": "Stevens Pass", "frac": []}}}, open(tmp_path / "state" / ("%s.json" % d), "w"))
    json.dump({"id": 99, "bottom_line": "Careful out there.", "hazard_discussion": "Dec 12 facets remain reactive on N above treeline."},
              open(tmp_path / "archive" / d / "products" / "NWAC_1130_99_abcd1234.json", "w"))
    payloads = iter([
        {"observations": [{"source": "nwac_product", "source_id": "99", "obs_date": d, "location": "Stevens Pass", "lat": float(latg[2, 0]), "lon": float(long_[2, 0]),
                           "zone": "Stevens Pass", "elevation_ft": 6000, "band": "above", "aspects": ["N"], "surface": "settled", "confidence": 0.6, "quote": "soft snow on north aspects"}],
         "layers": [{"name": "Dec 12 facets", "status": "active", "zones": ["Stevens Pass"], "bands": ["above"], "buried": "2025-12-12", "last": d, "evidence": ["99"], "summary": "reactive on N"}],
         "notes": [{"text": "north aspects holding soft snow", "evidence": ["99"]}]},
        {"overview": "Soft snow on north aspects above treeline.", "zones": [{"zone": "Stevens Pass", "headline": "North holds", "text": "Settled powder N above treeline."}], "notes": []}])
    calls = []

    class Msgs:
        def create(self, **kw):
            calls.append(kw)
            return _Resp(json.dumps(next(payloads)))

    class C:
        messages = Msgs()
    monkeypatch.setattr(llm, "client", lambda: C())
    out = daily.run(dt.date(2026, 1, 15), lambda *a: None, upload=False)
    assert len(calls) == 2 and "Known weak layers" in calls[0]["messages"][0]["content"] and "Ledger, last weeks" in calls[1]["messages"][0]["content"]
    assert out["overview"].startswith("Soft snow") and out["layers"][0]["name"] == "Dec 12 facets"
    recs = ledger.load()
    kinds = [r["kind"] for r in recs]
    assert kinds.count("obs") == 1 and kinds.count("layer") == 1 and kinds.count("residual") == 1 and kinds.count("note") == 1
    res = next(r for r in recs if r["kind"] == "residual")
    assert res["match"] and res["predicted"] == "settled" and res["obs_id"] == "obs_%s_0" % d and res["how"] == "near"
    assert json.load(open(tmp_path / "brief" / "latest.json"))["date"] == d


def test_daily_without_key_still_writes_layers_and_ledger(tmp_path, monkeypatch):
    _local_store(tmp_path, monkeypatch)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    out = daily.run(dt.date(2026, 1, 15), lambda *a: None, upload=False)
    assert out["layers"] == [] and "overview" not in out and os.path.exists(tmp_path / "ledger" / "ledger.json")
