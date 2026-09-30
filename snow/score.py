"""
Residuals: each observation record against what the model said for its place and day. A report with coordinates
is scored over the cells within 300 m of them; one whose location text names a place in snow/places.json over the
cells within 1.5 km; only a report with neither is scored against its zone x band x aspect group. A report that
carries its own `spatial_precision_m` (the extraction's placing of it) uses that as the radius instead, clipped to
PRECISION_M. In every case the cells are kept to the band and aspects the report names, and the score is the share
of those cells in the observed class (a zone is never assumed uniform). Residual records carry both classes, the
share, how the cells were chosen, the precision and source tier, and the cell's state, so the fit, the assimilation
and the brief can weigh them.
"""
import json
import math
import os

import numpy as np

from snow import forcing
from snow.state import CLASSES, CID, octants

OCT = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
PRECISION_M = (100.0, 5000.0)


def precision_m(o):
    """a report's own spatial precision as the neighbourhood radius in m, clipped; None when it has none"""
    v = o.get("spatial_precision_m")
    if v is None:
        return None
    try:
        return float(min(max(float(v), PRECISION_M[0]), PRECISION_M[1]))
    except (TypeError, ValueError):
        return None


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


def places():
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "places.json"), encoding="utf-8") as f:
        p = json.load(f)
    return {k: v for k, v in p.items() if not k.startswith("_")}


def resolve_place(text, table=None):
    """(lat, lon, name) for the longest gazetteer name found in text, else None"""
    if not text:
        return None
    table = table or places()
    low = text.lower()
    for name in sorted(table, key=len, reverse=True):
        if name.lower() in low:
            lat, lon = table[name]
            return lat, lon, name
    return None


def neighbourhood(cls, lat, meta, latv, lonv, radius_m, band, aspects):
    """classes of the cells within radius_m of a point, kept to the band and aspects the report names when any
    cell there has them; -> (counts per class, n cells, filtered?) or None outside the lattice"""
    r, c = forcing.cell_of(meta, [latv], [lonv])
    if r[0] < 0:
        return None
    cell = float(meta.get("cell_m") or 100)
    k = max(1, int(math.ceil(radius_m / cell)))
    h, w = cls.shape
    r0, r1, c0, c1 = max(0, r[0] - k), min(h, r[0] + k + 1), max(0, c[0] - k), min(w, c[0] + k + 1)
    sub = cls[r0:r1, c0:c1]
    yy, xx = np.mgrid[r0:r1, c0:c1]
    m = (sub != 255) & (((yy - r[0]) ** 2 + (xx - c[0]) ** 2) * cell * cell <= radius_m * radius_m)
    filt = m.copy()
    applied = False
    if band is not None:
        filt &= lat["band"][r0:r1, c0:c1] == band
        applied = True
    if aspects and "all" not in aspects:
        oi = octants(lat["aspect"][r0:r1, c0:c1])
        filt &= np.isin(oi, [OCT.index(a) for a in aspects if a in OCT])
        applied = True
    used, filtered = (filt, True) if applied and filt.any() else (m, False)
    if not used.any():
        return None
    return np.bincount(sub[used], minlength=len(CLASSES)), int(used.sum()), filtered


def score(obs_records, cls, state, lat, meta, log=print, radius_point_m=300.0, radius_place_m=1500.0):
    """-> residual records (without kind/date/id: ledger.append adds them). A report with coordinates is scored
    over the cells within radius_point_m of them; one whose location text names a known place over
    radius_place_m; one with neither against its zone x band x aspect group. `frac` is the share of the scored
    cells in the observed class (the honest score for a heterogeneous area); `match` is frac >= 0.5."""
    out = []
    bands = {"below": 0, "near": 1, "above": 2}
    table = places()
    for o in obs_records:
        if o.get("surface") in (None, "unknown"):
            continue
        b = bands.get(o.get("band") or "")
        aspects = o.get("aspects") or []
        prec = precision_m(o)
        r_point, r_place = (prec, prec) if prec is not None else (radius_point_m, radius_place_m)
        counts, n, how, filtered, radius, place = None, 0, None, False, None, None
        if o.get("lat") is not None and o.get("lon") is not None:
            nb = neighbourhood(cls, lat, meta, o["lat"], o["lon"], r_point, b, aspects)
            if nb:
                counts, n, filtered = nb
                how, radius = "near", r_point
        if counts is None:
            hit = resolve_place(o.get("location"), table)
            if hit:
                nb = neighbourhood(cls, lat, meta, hit[0], hit[1], r_place, b, aspects)
                if nb:
                    counts, n, filtered = nb
                    how, radius, place = "place", r_place, hit[2]
        if counts is None:
            zid = zone_id_for(o.get("zone"), meta)
            if zid is not None and b is not None:
                m = (cls != 255) & (lat["zone"] == zid) & (lat["band"] == b)
                if aspects and "all" not in aspects:
                    m &= np.isin(octants(lat["aspect"]), [OCT.index(a) for a in aspects if a in OCT])
                if m.any():
                    counts, n, how, filtered = np.bincount(cls[m], minlength=len(CLASSES)), int(m.sum()), "group", True
        if counts is None:
            continue
        pred = int(counts.argmax())
        obs_i = CID.get(o["surface"])
        frac = float(counts[obs_i] / max(counts.sum(), 1)) if obs_i is not None else 0.0
        rec = {"obs_id": o.get("id"), "observed": o["surface"], "predicted": CLASSES[pred], "frac": round(frac, 3), "match": frac >= 0.5,
               "how": how, "n_cells": n, "filtered": filtered, "radius_m": radius, "place": place, "confidence": o.get("confidence"),
               "precision_m": prec, "tier": o.get("source_tier")}
        if how == "near":
            r, c = forcing.cell_of(meta, [o["lat"]], [o["lon"]])
            rec["cell"] = [int(r[0]), int(c[0])]
            rec["state"] = {k: float(state[k][r[0], c[0]]) for k in ("days", "hn24_cm", "solar_mj", "wind_h", "refreeze", "depth_in") if k in state}
        out.append(rec)
    log("score: %d reports scored (%s), %d match" % (len(out), ", ".join("%s %d" % (h, sum(1 for r in out if r["how"] == h)) for h in ("near", "place", "group") if any(r["how"] == h for r in out)) or "none", sum(1 for r in out if r["match"])))
    return out
