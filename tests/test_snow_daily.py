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


def test_layer_key_and_layers_merge_by_buried_date_and_grain():
    assert ledger.layer_key({"name": "Jan 30 facets", "buried": "2026-01-30", "grain": "FC"}) == "20260130_fc"
    assert ledger.layer_key({"name": "Jan 30 facets", "buried": None, "grain": "FC"}) == "Jan 30 facets"
    assert ledger.layer_key({"name": "Jan 30 facets", "buried": "2026-01-30", "grain": None}) == "Jan 30 facets"
    assert ledger.layer_key({"name": "odd", "buried": "late January", "grain": "FC"}) == "odd"
    recs = []
    ledger.append(recs, [{"name": "Dec 12 facets", "status": "active", "last": "2026-01-02"}], "2026-01-02", "layer")          # name only (old format)
    ledger.append(recs, [{"name": "Dec 12 facets", "status": "active", "buried": "2025-12-12", "grain": "FC", "last": "2026-01-05"}], "2026-01-05", "layer")
    ledger.append(recs, [{"name": "the December facets", "status": "dormant", "buried": "2025-12-12", "grain": "FC", "last": "2026-01-08"}], "2026-01-08", "layer")
    ledger.append(recs, [{"name": "Dec 12 facets", "status": "healed", "last": "2026-01-20"}], "2026-01-20", "layer")          # name only again
    ledger.append(recs, [{"name": "Jan 30 facets", "status": "active", "buried": "2026-01-30", "grain": "FC", "last": "2026-02-01"}], "2026-02-01", "layer")
    ledger.append(recs, [{"name": "Feb crust", "status": "active", "buried": None, "grain": "MFcr", "last": "2026-02-10"}], "2026-02-10", "layer")
    t = ledger.layers(recs)
    assert set(t) == {"20251212_fc", "20260130_fc", "Feb crust"}
    dec = t["20251212_fc"]
    assert dec["status"] == "healed" and dec["last"] == "2026-01-20" and dec["key"] == "20251212_fc"
    assert dec["buried"] == "2025-12-12" and dec["grain"] == "FC"           # carried onto the name-only snapshot
    assert t["Feb crust"]["key"] == "Feb crust" and t["Feb crust"]["grain"] == "MFcr"
    assert ledger.layers(recs, today="2026-03-15")["20260130_fc"]["status"] == "dormant"
    assert ledger.layers(recs, today="2026-02-15")["20260130_fc"]["status"] == "active"


def test_extract_schema_is_strict_and_carries_the_new_fields():
    def walk(node):
        if "properties" in node:
            assert node["additionalProperties"] is False
            assert list(node["properties"]) == node["required"]
            for v in node["properties"].values():
                walk(v)
        if "items" in node:
            walk(node["items"])
    walk(llm.EXTRACT_SCHEMA)
    walk(llm.BRIEF_SCHEMA)
    ob = llm.EXTRACT_SCHEMA["properties"]["observations"]["items"]["properties"]
    assert ob["surface"]["enum"] == state.CLASSES + ["unknown"]
    # nullable enums are anyOf: the API rejects an enum on a ["string", "null"] type (2026-09-30 run)
    assert ob["moisture"] == {"anyOf": [{"type": "string", "enum": ["dry", "moist", "wet"]}, {"type": "null"}]}
    assert ob["wind_effect"] == {"anyOf": [{"type": "string", "enum": ["none", "light", "heavy"]}, {"type": "null"}]}
    assert ob["band"] == {"anyOf": [{"type": "string", "enum": llm.BANDS}, {"type": "null"}]}
    assert ob["spatial_precision_m"] == {"type": ["number", "null"]}
    assert ob["source_tier"] == {"type": "string", "enum": ["center_product", "pro_obs", "public_obs", "trip"]}
    la = llm.EXTRACT_SCHEMA["properties"]["layers"]["items"]["properties"]
    assert la["buried"] == {"type": ["string", "null"]}
    assert la["grain"] == {"anyOf": [{"type": "string", "enum": ["SH", "FC", "DH", "MFcr", "IFrc", "PP", "DF", "RG"]}, {"type": "null"}]}
    for word in ("moisture", "wind_effect", "spatial_precision_m", "center_product", "pro_obs", "public_obs", "trip",
                 "reportedly", "possibly", "only a zone", "grain", "20220130_fcsf"):
        assert word in llm.EXTRACT_SYSTEM, word


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
    assert all(r["precision_m"] is None and r["tier"] is None for r in res)      # records without the new fields
    assert by["o1"]["radius_m"] == 300.0 and by["o2"]["radius_m"] == 1500.0


def test_score_uses_the_report_precision_as_the_radius(monkeypatch):
    pytest.importorskip("pyproj")
    from snow import forcing
    meta = {"crs": "EPSG:26910", "shape": [4, 4], "transform": [1000.0, 0.0, 670000.0, 0.0, -1000.0, 5280000.0], "cell_m": 1000,
            "zones": {"1130": {"name": "Stevens Pass"}}}
    lat = _lattice()
    latg, long_ = forcing.lattice_latlon(meta)
    cls = np.full((4, 4), state.CID["settled"], np.uint8)
    cls[:, 1] = state.CID["sun_crust"]
    cls[:, 3] = 255
    import snow.score as sc
    monkeypatch.setattr(sc, "places", lambda: {"Skyline Ridge": [float(latg[2, 1]), float(long_[2, 1])]})
    at = {"lat": float(latg[2, 1]), "lon": float(long_[2, 1]), "aspects": ["all"], "band": None, "surface": "settled"}
    obs = [dict(at, id="p0"),                                                        # 300 m: the one crusted cell
           dict(at, id="p1", spatial_precision_m=1500, source_tier="pro_obs"),       # 1500 m: the 3 x 3 block, six of nine settled
           dict(at, id="p2", spatial_precision_m=50000, source_tier="public_obs"),   # clipped to 5 km
           dict(at, id="p3", spatial_precision_m=10),                                # clipped to 100 m
           dict(at, id="p4", spatial_precision_m="bad"),                             # unreadable: as if absent
           {"id": "p5", "lat": None, "lon": None, "location": "Skyline Ridge", "aspects": ["all"], "band": None, "surface": "settled",
            "spatial_precision_m": 300, "source_tier": "center_product"}]           # a place with its own precision
    by = {r["obs_id"]: r for r in sc.score(obs, cls, {}, lat, meta, lambda *a: None)}
    assert by["p0"]["frac"] == 0.0 and by["p0"]["radius_m"] == 300.0 and by["p0"]["precision_m"] is None
    assert by["p1"]["frac"] == 0.667 and by["p1"]["n_cells"] == 9 and by["p1"]["radius_m"] == 1500.0 and by["p1"]["precision_m"] == 1500.0 and by["p1"]["tier"] == "pro_obs"
    assert by["p2"]["radius_m"] == 5000.0 and by["p2"]["precision_m"] == 5000.0 and by["p2"]["n_cells"] == 12 and by["p2"]["tier"] == "public_obs"
    assert by["p3"]["radius_m"] == 100.0 and by["p3"]["frac"] == 0.0
    assert by["p4"]["radius_m"] == 300.0 and by["p4"]["precision_m"] is None
    assert by["p5"]["how"] == "place" and by["p5"]["radius_m"] == 300.0 and by["p5"]["frac"] == 0.0 and by["p5"]["tier"] == "center_product"


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
                           "zone": "Stevens Pass", "elevation_ft": 6000, "band": "above", "aspects": ["N"], "surface": "settled", "moisture": "dry", "wind_effect": None,
                           "spatial_precision_m": 1500, "source_tier": "center_product", "confidence": 0.6, "quote": "soft snow on north aspects"}],
         "layers": [{"name": "Dec 12 facets", "status": "active", "zones": ["Stevens Pass"], "bands": ["above"], "buried": "2025-12-12", "grain": "FC", "last": d, "evidence": ["99"], "summary": "reactive on N"}],
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
    # a trip from an older trips.json, without the new fields
    monkeypatch.setattr(ledger, "trips", lambda log=print: [{"source": "trip", "source_id": "skyline-" + d, "obs_date": d, "location": "Skyline Ridge",
                                                             "lat": float(latg[1, 0]), "lon": float(long_[1, 0]), "zone": "Stevens Pass", "elevation_ft": 5000,
                                                             "band": "near", "aspects": ["N"], "surface": "settled", "confidence": 0.9, "quote": "soft"}])
    out = daily.run(dt.date(2026, 1, 15), lambda *a: None, upload=False)
    assert len(calls) == 2 and "Known weak layers" in calls[0]["messages"][0]["content"] and "Ledger, last weeks" in calls[1]["messages"][0]["content"]
    assert out["overview"].startswith("Soft snow") and out["layers"][0]["name"] == "Dec 12 facets" and out["layers"][0]["key"] == "20251212_fc"
    recs = ledger.load()
    kinds = [r["kind"] for r in recs]
    assert kinds.count("obs") == 1 and kinds.count("layer") == 1 and kinds.count("residual") == 2 and kinds.count("note") == 1 and kinds.count("trip") == 1
    trip = next(r for r in recs if r["kind"] == "trip")
    assert trip["source_tier"] == "trip" and "spatial_precision_m" not in trip
    obs_rec = next(r for r in recs if r["kind"] == "obs")
    assert obs_rec["moisture"] == "dry" and obs_rec["wind_effect"] is None and obs_rec["spatial_precision_m"] == 1500
    res = {r["obs_id"]: r for r in recs if r["kind"] == "residual"}
    ro = res["obs_%s_0" % d]
    assert ro["match"] and ro["predicted"] == "settled" and ro["how"] == "near" and ro["radius_m"] == 1500.0 and ro["precision_m"] == 1500.0 and ro["tier"] == "center_product"
    rt = res["trip_%s_0" % d]
    assert rt["how"] == "near" and rt["radius_m"] == 300.0 and rt["precision_m"] is None and rt["tier"] == "trip"
    assert json.load(open(tmp_path / "brief" / "latest.json"))["date"] == d


def test_daily_without_key_still_writes_layers_and_ledger(tmp_path, monkeypatch):
    _local_store(tmp_path, monkeypatch)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    out = daily.run(dt.date(2026, 1, 15), lambda *a: None, upload=False)
    assert out["layers"] == [] and "overview" not in out and os.path.exists(tmp_path / "ledger" / "ledger.json")
