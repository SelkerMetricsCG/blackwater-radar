"""
Assimilation: a scored field report nudges the model where the terrain is like the report's own.

Similar cells: within assim_radius_km of the report, aspect within assim_aspect_deg (flat only with flat),
elevation within assim_elev_m, canopy fraction within assim_canopy, and on the same side of the Cascade crest
(crest_km of the same sign, or both within crest_same_km of it). A west-side and an east-side slope at the same
elevation and aspect are different snow; near the crest they are close to the same.

The nudge moves the state's continuous fields toward values that classify as the observed class, blended by
w = assim_weight * confidence * exp(-d / radius) * (1 - frac) where frac is how much the model already agreed
(from the residual). A report that matched nudges nothing. Nudged fields:
  fresh          days 0, hn24 fresh_cm, solar 0, wind hours 0, rain 0
  settled / old  solar below the crust threshold, wind hours below wind_hours, rain 0, melt_days 0
  sun_crust      solar to solar_crust_mj      rain_crust   rain 1, refrozen 1   rain_wet  rain 1, refrozen 0   wind*  wind hours to wind_hours
  melt_freeze    refreeze to refreeze_good, melt_days 0   isothermal   melt_days to isothermal_days
  no_snow        depth 0                       dust / tree_debris     left to the day's rules (transient)
Returns records of what was nudged for the ledger.
"""
import numpy as np

from snow import forcing
from snow.state import CID


def similar(lat, r0, c0, p, radius_cells):
    """boolean mask of the cells similar to (r0, c0), and the distance (cells) inside the window; window slice"""
    h, w = lat["elev"].shape
    k = int(radius_cells)
    rs, re, cs, ce = max(0, r0 - k), min(h, r0 + k + 1), max(0, c0 - k), min(w, c0 + k + 1)
    win = (slice(rs, re), slice(cs, ce))
    elev = lat["elev"][win].astype(np.float32)
    ok = elev > -30000
    yy, xx = np.mgrid[rs:re, cs:ce]
    dist = np.hypot(yy - r0, xx - c0)
    m = ok & (dist <= radius_cells)
    e0 = float(lat["elev"][r0, c0])
    m &= np.abs(elev - e0) <= p["assim_elev_m"]
    a0 = float(lat["aspect"][r0, c0])
    asp = lat["aspect"][win].astype(np.float32)
    if a0 < 0:
        m &= asp < 0
    else:
        diff = np.abs((asp - a0 + 180.0) % 360.0 - 180.0)
        m &= (asp >= 0) & (diff <= p["assim_aspect_deg"])
    if "canopy" in lat:
        c = lat["canopy"][win].astype(np.float32) / 100.0
        c0v = float(lat["canopy"][r0, c0]) / 100.0
        if c0v <= 1.0:
            m &= (c <= 1.0) & (np.abs(c - c0v) <= p["assim_canopy"])
    if "crest_km" in lat:
        ck = lat["crest_km"][win].astype(np.float32) / 10.0
        ck0 = float(lat["crest_km"][r0, c0]) / 10.0
        near = p["crest_same_km"]
        same = (np.sign(ck) == np.sign(ck0)) | (np.abs(ck) <= near) | (abs(ck0) <= near)
        m &= same
    return m, dist, win


def nudge(s, m, w, cls_name, p):
    """blend the fields of the masked cells toward the target for cls_name; m and w are window-shaped"""
    def blend(field, target):
        field[...] = np.where(m, (1 - w) * field + w * target, field)

    def setmin(field, target):     # move up toward 1.5 x target where below it, so a confident report crosses the threshold
        field[...] = np.where(m & (field < target), (1 - w) * field + w * target * 1.5, field)

    def setmax(field, target):     # move down to at most target where above
        field[...] = np.where(m & (field > target), (1 - w) * field + w * target, field)

    if cls_name == "fresh":
        blend(s["days"], 0.0)
        setmin(s["hn24_cm"], p["fresh_cm"])
        blend(s["solar_mj"], 0.0)
        blend(s["wind_h"], 0.0)
        blend(s["wind_lee_h"], 0.0)
        blend(s["wind_wwd_h"], 0.0)
        blend(s["rain"], 0.0)
    elif cls_name in ("settled", "settled_late", "old"):
        setmax(s["solar_mj"], 0.5 * p["solar_crust_mj"])
        for k in ("wind_h", "wind_lee_h", "wind_wwd_h"):
            setmax(s[k], 0.5 * p["wind_hours"])
        blend(s["rain"], 0.0)
        blend(s["rain_refrozen"], 0.0)
        blend(s["melt_days"], 0.0)
        if cls_name == "old":
            setmin(s["days"], 15.0)
        elif cls_name == "settled_late":
            setmin(s["days"], p["settled_days"] + 1)
            setmax(s["days"], 14.0)
        else:
            setmin(s["days"], p["settle_days"])
            setmax(s["days"], p["settled_days"])
    elif cls_name == "sun_crust":
        setmin(s["solar_mj"], p["solar_crust_mj"])
    elif cls_name == "rain_crust":
        blend(s["rain"], 1.0)
        blend(s["rain_refrozen"], 1.0)
    elif cls_name == "rain_wet":
        blend(s["rain"], 1.0)
        blend(s["rain_refrozen"], 0.0)
    elif cls_name in ("wind", "wind_loaded", "wind_scoured"):
        key = {"wind": "wind_h", "wind_loaded": "wind_lee_h", "wind_scoured": "wind_wwd_h"}[cls_name]
        setmin(s[key], p["wind_hours"])
        setmin(s["wind_h"], p["wind_hours"])
    elif cls_name == "melt_freeze":
        setmin(s["refreeze"], p["refreeze_good"])
        blend(s["melt_days"], 0.0)
    elif cls_name == "isothermal":
        setmin(s["melt_days"], p["isothermal_days"])
        setmax(s["refreeze"], 0.5 * p["refreeze_good"])
    elif cls_name == "no_snow":
        blend(s["depth_in"], 0.0)


def apply(s, residuals, obs_by_id, lat, meta, p, log=print):
    """nudge the state in place for every residual that has a point; -> records for the ledger"""
    cell_m = float(meta.get("cell_m") or 100)
    radius_cells = p["assim_radius_km"] * 1000.0 / cell_m
    out = []
    for r in residuals:
        o = obs_by_id.get(r.get("obs_id")) or {}
        cls_name = r.get("observed")
        if cls_name not in CID or cls_name in ("dust_on_crust", "tree_debris", "unknown"):
            continue
        frac = float(r.get("frac") or 0.0)
        if frac >= 0.999:
            continue
        if r.get("how") == "near" and r.get("cell"):
            r0, c0 = r["cell"]
        else:
            latv = o.get("lat")
            lonv = o.get("lon")
            if r.get("place"):
                from snow.score import places
                hit = places().get(r["place"])
                if hit:
                    latv, lonv = hit
            if latv is None or lonv is None:
                continue
            rr, cc = forcing.cell_of(meta, [latv], [lonv])
            if rr[0] < 0:
                continue
            r0, c0 = int(rr[0]), int(cc[0])
        if lat["elev"][r0, c0] <= -30000:
            continue
        conf = float(o.get("confidence") if o.get("confidence") is not None else 0.6)
        m, dist, win = similar(lat, r0, c0, p, radius_cells)
        if not m.any():
            continue
        w = np.where(m, p["assim_weight"] * conf * (1 - frac) * np.exp(-dist / radius_cells), 0.0).astype(np.float32)
        sub = {k: v[win] for k, v in s.items() if k != "cls"}
        nudge(sub, m, w, cls_name, p)
        for k, v in sub.items():
            s[k][win] = v.astype(s[k].dtype)
        out.append({"obs_id": r.get("obs_id"), "observed": cls_name, "cells": int(m.sum()), "max_w": round(float(w.max()), 3),
                    "cell": [r0, c0], "radius_km": p["assim_radius_km"]})
    log("assimilate: %d reports nudged the state (%d cells in all)" % (len(out), sum(x["cells"] for x in out)))
    return out
