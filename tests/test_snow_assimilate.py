"""snow/assimilate.py: similarity by aspect, elevation, canopy and crest side; the nudge changes the class of
similar cells only, weighted by distance and the model's prior agreement."""
import pytest

np = pytest.importorskip("numpy")
from snow import assimilate, state  # noqa: E402


def _lattice(n=40):
    # a 40 x 40 lattice of 100 m cells: left half west of the crest, right half east; two aspect stripes;
    # elevation rising northward
    elev = np.tile(np.linspace(2000, 1000, n).astype(np.int16)[:, None], (1, n))
    aspect = np.zeros((n, n), np.int16)
    aspect[:, ::2] = 180                       # even columns south, odd north
    crest = np.tile(((np.arange(n) - n / 2) * 0.1 * 10).astype(np.int16)[None, :], (n, 1))   # tenths of km, -20..+19
    canopy = np.full((n, n), 20, np.uint8)
    return {"elev": elev, "slope": np.full((n, n), 30, np.uint8), "aspect": aspect, "band": np.ones((n, n), np.uint8),
            "zone": np.full((n, n), 1, np.int32), "canopy": canopy, "crest_km": crest}


def test_similar_respects_aspect_elevation_and_crest_side():
    p, _ = state.load_params()
    lat = _lattice()
    m, dist, win = assimilate.similar(lat, 20, 4, p, radius_cells=100)      # west side, north-facing (odd column? col 4 is even = south)
    sub = lat["aspect"][win][m]
    assert (sub == 180).all()                                                # only south-facing cells
    rows = np.mgrid[win][0][m]
    assert np.abs(lat["elev"][rows, 0].astype(int) - int(lat["elev"][20, 4])).max() <= p["assim_elev_m"]
    cols = np.mgrid[win][1][m]
    assert cols.max() < 20 + p["crest_same_km"] * 10                        # never far onto the east side
    # a cell right at the crest reaches both sides
    m2, _, win2 = assimilate.similar(lat, 20, 20, p, radius_cells=100)
    cols2 = np.mgrid[win2][1][m2]
    assert cols2.min() < 15 and cols2.max() > 25
    # a flat cell matches only flat cells
    lat["aspect"][20, 6] = -1
    m3, _, win3 = assimilate.similar(lat, 20, 6, p, radius_cells=100)
    assert m3.sum() == 1


def test_apply_moves_similar_cells_toward_the_observation():
    p, _ = state.load_params()
    lat = _lattice()
    s = state.new_state(lat["elev"].shape, np.full(lat["elev"].shape, 60.0), p["min_depth_in"], lat["elev"] != -32768)
    s["days"][:] = 5
    s["cls"][:] = state.CID["settled"]
    meta = {"cell_m": 100}
    obs = {"o1": {"id": "o1", "confidence": 1.0, "lat": None, "lon": None}}
    res = [{"obs_id": "o1", "observed": "sun_crust", "frac": 0.0, "how": "near", "cell": [20, 4]}]
    out = assimilate.apply(s, res, obs, lat, meta, p, lambda *a: None)
    assert len(out) == 1 and out[0]["cells"] > 10 and out[0]["max_w"] == pytest.approx(p["assim_weight"])
    cls = state.reclassify(s, lat, p)
    assert cls[20, 4] == state.CID["sun_crust"]                              # the report's own cell
    assert cls[20, 5] == state.CID["settled"]                                # north-facing neighbour untouched
    assert cls[20, 36] == state.CID["settled"]                               # far east side untouched
    assert s["solar_mj"][20, 4] >= p["solar_crust_mj"] and s["solar_mj"][20, 5] == 0
    # a report the model already agreed with nudges nothing
    before = s["solar_mj"].copy()
    assert assimilate.apply(s, [dict(res[0], frac=1.0)], obs, lat, meta, p, lambda *a: None) == []
    assert (s["solar_mj"] == before).all()


def _settled_state(lat, p):
    s = state.new_state(lat["elev"].shape, np.full(lat["elev"].shape, 60.0), p["min_depth_in"], lat["elev"] != -32768)
    s["days"][:] = 5
    s["cls"][:] = state.CID["settled"]
    return s


def test_tier_weight_scales_the_nudge():
    p, _ = state.load_params()
    lat = _lattice()
    meta = {"cell_m": 100}
    res = [{"obs_id": "o1", "observed": "sun_crust", "frac": 0.0, "how": "near", "cell": [20, 4]}]
    # the tier comes from the obs when the residual has none
    obs = {"o1": {"id": "o1", "confidence": 1.0, "lat": None, "lon": None, "source_tier": "public_obs"}}
    out = assimilate.apply(_settled_state(lat, p), res, obs, lat, meta, p, lambda *a: None)
    assert out[0]["max_w"] == pytest.approx(0.6 * p["assim_weight"]) and out[0]["tier"] == "public_obs" and out[0]["tier_w"] == 0.6
    assert out[0]["precision_m"] is None and out[0]["radius_km"] == p["assim_radius_km"]
    # the residual's own tier wins; an unknown tier weighs 1
    out = assimilate.apply(_settled_state(lat, p), [dict(res[0], tier="trip")], obs, lat, meta, p, lambda *a: None)
    assert out[0]["max_w"] == pytest.approx(0.8 * p["assim_weight"]) and out[0]["tier"] == "trip"
    out = assimilate.apply(_settled_state(lat, p), [dict(res[0], tier="martian")], obs, lat, meta, p, lambda *a: None)
    assert out[0]["max_w"] == pytest.approx(p["assim_weight"]) and out[0]["tier_w"] == 1.0
    assert assimilate.TIER_WEIGHT == {"center_product": 1.0, "pro_obs": 1.0, "public_obs": 0.6, "trip": 0.8}


def test_precision_flattens_the_nudge_inside_the_report_area():
    p, _ = state.load_params()
    lat = _lattice()
    meta = {"cell_m": 100}
    obs = {"o1": {"id": "o1", "confidence": 1.0, "lat": None, "lon": None}}
    res = {"obs_id": "o1", "observed": "sun_crust", "frac": 0.0, "how": "near", "cell": [20, 4]}
    s0 = _settled_state(lat, p)
    assimilate.apply(s0, [res], obs, lat, meta, p, lambda *a: None)
    s1 = _settled_state(lat, p)
    out = assimilate.apply(s1, [dict(res, precision_m=1500.0, tier="pro_obs")], obs, lat, meta, p, lambda *a: None)
    # (20, 14) is a similar cell 1 km away: without a precision it gets the decayed weight, inside a 1500 m report the full one
    assert s0["solar_mj"][20, 14] < s0["solar_mj"][20, 4]
    assert s1["solar_mj"][20, 14] == pytest.approx(s1["solar_mj"][20, 4]) and s1["solar_mj"][20, 14] > s0["solar_mj"][20, 14]
    assert s1["solar_mj"][20, 4] == pytest.approx(s0["solar_mj"][20, 4])       # the report's own cell is the same either way
    assert s1["solar_mj"][20, 5] == 0                                          # the north-facing neighbour still untouched
    assert out[0]["precision_m"] == 1500.0 and out[0]["max_w"] == pytest.approx(p["assim_weight"])
    # clipped to 100..5000 m; the obs's own field is the fallback for a residual from before precision was recorded
    out = assimilate.apply(_settled_state(lat, p), [dict(res, precision_m=99999)], obs, lat, meta, p, lambda *a: None)
    assert out[0]["precision_m"] == 5000.0
    obs2 = {"o1": dict(obs["o1"], spatial_precision_m=20)}
    out = assimilate.apply(_settled_state(lat, p), [res], obs2, lat, meta, p, lambda *a: None)
    assert out[0]["precision_m"] == 100.0


def test_old_records_nudge_exactly_as_before():
    p, _ = state.load_params()
    lat = _lattice()
    meta = {"cell_m": 100}
    obs = {"o1": {"id": "o1", "confidence": 0.7, "lat": None, "lon": None}}
    res = {"obs_id": "o1", "observed": "fresh", "frac": 0.2, "how": "near", "cell": [10, 8]}
    s0, s1 = _settled_state(lat, p), _settled_state(lat, p)
    a = assimilate.apply(s0, [res], obs, lat, meta, p, lambda *a: None)
    b = assimilate.apply(s1, [dict(res, precision_m=None, tier=None)], obs, lat, meta, p, lambda *a: None)
    assert a[0]["max_w"] == b[0]["max_w"] == pytest.approx(p["assim_weight"] * 0.7 * 0.8, abs=1e-3) and a[0]["cells"] == b[0]["cells"]
    for k in s0:
        assert (s0[k] == s1[k]).all(), k
