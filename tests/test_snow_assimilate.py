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
