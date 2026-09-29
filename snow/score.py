"""
Residuals: each observation record against what the model said for its place and day. An obs with coordinates is
scored at its cell; one with only zone/band/aspects is scored against the modal class of that group. Residual
records carry both classes, the cell's state and whether they match, so the fit and the brief can read them.
"""
import numpy as np

from snow import forcing
from snow.state import CLASSES, CID, octants

OCT = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]


def zone_id_for(name, meta):
    if name is None:
        return None
    for zid, info in (meta.get("zones") or {}).items():
        if (info.get("name") or "").lower() == str(name).lower():
            return int(zid)
    return None


def modal_class(cls, lat, zid, band, aspects):
    m = (cls != 255) & (lat["zone"] == zid) & (lat["band"] == band)
    if aspects and "all" not in aspects:
        oi = octants(lat["aspect"])
        m &= np.isin(oi, [OCT.index(a) for a in aspects if a in OCT])
    if not m.any():
        return None
    return int(np.bincount(cls[m], minlength=len(CLASSES)).argmax())


def score(obs_records, cls, state, lat, meta, log=print):
    """-> residual records (without kind/date/id: ledger.append adds them)"""
    out = []
    bands = {"below": 0, "near": 1, "above": 2}
    for o in obs_records:
        if o.get("surface") in (None, "unknown"):
            continue
        pred, how, cell = None, None, None
        if o.get("lat") is not None and o.get("lon") is not None:
            r, c = forcing.cell_of(meta, [o["lat"]], [o["lon"]])
            if r[0] >= 0 and cls[r[0], c[0]] != 255:
                pred, how, cell = int(cls[r[0], c[0]]), "cell", [int(r[0]), int(c[0])]
        if pred is None:
            zid = zone_id_for(o.get("zone"), meta)
            b = bands.get(o.get("band") or "")
            if zid is not None and b is not None:
                pred = modal_class(cls, lat, zid, b, o.get("aspects") or [])
                how = "group"
        if pred is None:
            continue
        rec = {"obs_id": o.get("id"), "observed": o["surface"], "predicted": CLASSES[pred], "match": CLASSES[pred] == o["surface"],
               "how": how, "cell": cell, "confidence": o.get("confidence")}
        if cell is not None:
            rec["state"] = {k: float(state[k][cell[0], cell[1]]) for k in ("days", "hn24_cm", "solar_mj", "wind_h", "refreeze", "depth_in") if k in state}
        out.append(rec)
    n = len(out)
    log("score: %d observations scored, %d match" % (n, sum(1 for r in out if r["match"])))
    return out
