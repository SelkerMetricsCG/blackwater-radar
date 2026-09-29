"""
Surface-state model: one day per cell of the terrain lattice, from the season archive.

State (per cell, carried day to day in <region>/snow/state/latest.npz):
  cls        surface class (CLASSES index; 255 off the lattice)
  days       days since the last fresh snowfall (capped at 250)
  hn24_cm    yesterday's new snow on the cell (MRMS liquid x snow fraction from the freezing level x SLR from temperature)
  solar_mj   MJ/m2 on the cell since the last fresh snow (snow/solar.py, NDFD sky cover)
  wind_h     hours of NDFD 10 m wind above wind_mph since the last fresh snow
  wind_lee_h / wind_wwd_h   of those, the hours the cell was in the lee (aspect within wind_sector of the downwind
             direction: loading) or windward (facing the wind: scouring), from NDFD wind direction
  rain       1 when rain fell on the cell since the last fresh snow
  melt_days  consecutive days of surface melt without a solid overnight refreeze
  refreeze   last night's refreeze index (0..1)
  depth_in   SNODAS snow depth

Rules and parameters: snow_config.yaml `state` (all placeholders until the residual ledger exists; see the spec).
Class priority, first match wins: no_snow, fresh, dust_on_crust, isothermal, melt_freeze, rain_crust, sun_crust,
wind_scoured, wind_loaded, wind (direction unknown), fresh (settling), settled, old (aged powder with no crust
trigger: the north-facing pocket).

  python -m snow.state --date 2026-01-15      run one day (yesterday by default); reads and writes R2 through snow/store.py
"""
import argparse
import datetime as dt
import json
import os
import time

import numpy as np

import region
from snow import forcing, solar, store

ROOT = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(ROOT, "snow_config.yaml")
CLASSES = ["no_snow", "fresh", "settled", "wind", "sun_crust", "rain_crust", "melt_freeze", "isothermal", "dust_on_crust", "old",
           "wind_loaded", "wind_scoured"]
CID = {c: i for i, c in enumerate(CLASSES)}
CRUSTS = (CID["sun_crust"], CID["rain_crust"], CID["melt_freeze"], CID["isothermal"], CID["wind"], CID["wind_loaded"], CID["wind_scoured"])
OLD_DAYS = 14
FIELDS = {"cls": np.uint8, "days": np.uint8, "hn24_cm": np.float32, "solar_mj": np.float32, "wind_h": np.float32,
          "wind_lee_h": np.float32, "wind_wwd_h": np.float32,
          "rain": np.uint8, "melt_days": np.uint8, "refreeze": np.float32, "depth_in": np.float32}


def load_params(path=CONFIG):
    import yaml
    with open(path, encoding="utf-8") as f:
        c = yaml.safe_load(f)
    return {k: v["value"] for k, v in c["state"].items()}, c["solar"]


def new_state(shape, depth_in, min_depth_in, valid):
    s = {k: np.zeros(shape, t) for k, t in FIELDS.items()}
    s["days"][:] = 250
    s["depth_in"] = np.nan_to_num(np.asarray(depth_in, np.float32), nan=0.0)
    s["cls"] = np.where(s["depth_in"] < min_depth_in, CID["no_snow"], CID["old"]).astype(np.uint8)
    s["cls"][~valid] = 255
    return s


def step(s, f, lat, p, scfg):
    """advance one day. f: forcing dict of per-cell arrays (see day_forcing); lat: dict of lattice arrays"""
    valid = lat["elev"] != -32768
    elev_ft = lat["elev"].astype(np.float32) * 3.28084
    snow_level = f["fzl_ft"] - p["rain_line_margin_ft"]
    snowfrac = np.clip((elev_ft - snow_level + p["rain_mix_ft"]) / (2.0 * p["rain_mix_ft"]), 0, 1)
    snowfrac = np.where(np.isnan(f["fzl_ft"]), 1.0, snowfrac)          # no freezing level: assume snow (winter default)
    precip = np.nan_to_num(f["precip_in"], nan=0.0)
    t_mean = np.nan_to_num(0.5 * (f["tmax_c"] + f["tmin_c"]), nan=-2.0)
    slr = np.clip(p["slr_at_0c"] + p["slr_per_c"] * np.maximum(-t_mean, 0), p["slr_at_0c"], p["slr_max"])
    hn24 = precip * snowfrac * slr * 2.54
    rain_in = precip * (1 - snowfrac)
    fresh = hn24 >= p["fresh_cm"]
    days = np.where(fresh, 0, np.minimum(s["days"].astype(np.int32) + 1, 250))
    solar_mj = np.where(fresh, 0, s["solar_mj"] + np.nan_to_num(f["solar_mj"], nan=0.0))
    wind_h = np.where(fresh, 0, s["wind_h"] + np.nan_to_num(f["wind_h"], nan=0.0))
    wind_lee_h = np.where(fresh, 0, s.get("wind_lee_h", 0) + np.nan_to_num(f.get("wind_lee_h", 0.0), nan=0.0))
    wind_wwd_h = np.where(fresh, 0, s.get("wind_wwd_h", 0) + np.nan_to_num(f.get("wind_wwd_h", 0.0), nan=0.0))
    rain = np.where(fresh, 0, np.maximum(s["rain"], rain_in >= p["rain_in"])).astype(np.uint8)
    refreeze = solar.refreeze_index(np.nan_to_num(f["tmin_c"], nan=-5.0), np.nan_to_num(f["cloud_night"], nan=0.5),
                                    np.nan_to_num(f["td_night_c"], nan=-5.0), np.nan_to_num(f["wind_night_ms"], nan=2.0))
    melt = (np.nan_to_num(f["tmax_c"], nan=-5.0) > p["melt_tmax_c"]) & (np.nan_to_num(f["solar_mj"], nan=0.0) > 1.0)
    solid = refreeze >= p["refreeze_good"]
    corn = melt & solid
    melt_days = np.where(melt & ~solid, np.minimum(s["melt_days"].astype(np.int32) + 1, 250), 0)
    depth = np.where(np.isnan(f["depth_in"]), s["depth_in"], f["depth_in"]).astype(np.float32)
    prev = s["cls"]
    cls = np.full(prev.shape, CID["old"], np.uint8)
    cls[days <= OLD_DAYS] = CID["settled"]
    cls[days < p["settle_days"]] = CID["fresh"]
    cls[wind_h >= p["wind_hours"]] = CID["wind"]
    cls[wind_lee_h >= p["wind_hours"]] = CID["wind_loaded"]
    cls[wind_wwd_h >= p["wind_hours"]] = CID["wind_scoured"]
    cls[solar_mj >= p["solar_crust_mj"]] = CID["sun_crust"]
    cls[rain == 1] = CID["rain_crust"]
    cls[corn] = CID["melt_freeze"]
    cls[melt_days >= p["isothermal_days"]] = CID["isothermal"]
    dust = (hn24 >= p["dust_cm"]) & ~fresh & np.isin(prev, CRUSTS)
    cls[dust] = CID["dust_on_crust"]
    cls[fresh] = CID["fresh"]
    cls[depth < p["min_depth_in"]] = CID["no_snow"]
    cls[~valid] = 255
    return {"cls": cls, "days": days.astype(np.uint8), "hn24_cm": hn24.astype(np.float32), "solar_mj": solar_mj.astype(np.float32),
            "wind_h": wind_h.astype(np.float32), "wind_lee_h": wind_lee_h.astype(np.float32), "wind_wwd_h": wind_wwd_h.astype(np.float32),
            "rain": rain, "melt_days": melt_days.astype(np.uint8),
            "refreeze": refreeze.astype(np.float32), "depth_in": depth}


# ---------------------------------------------------------------- forcing from the archive

def _local_hour(valid_utc, tz_offset_h):
    t = dt.datetime.strptime(valid_utc[:16], "%Y-%m-%dT%H:%M") + dt.timedelta(hours=tz_offset_h)
    return t


def _steps_in(field, day, hours, tz_offset_h):
    """indices of NDFD steps valid on `day` whose local hour is in [h0, h1] (wrapping past midnight)"""
    h0, h1 = hours
    out = []
    for i, v in enumerate(field.get("valid_utc") or []):
        t = _local_hour(v, tz_offset_h)
        if t.date() != day:
            continue
        ok = h0 <= t.hour <= h1 if h0 <= h1 else (t.hour >= h0 or t.hour <= h1)
        if ok and str(field["steps"][i]) in field.get("grids", {}):
            out.append(i)
    return out


def _mean_grid(field, idx, lat, lon, k=1.0, b=0.0):
    if not idx:
        return np.full(lat.shape, np.nan, np.float32)
    acc = np.zeros(lat.shape, np.float32)
    for i in idx:
        acc += forcing.sample(field["grids"][str(field["steps"][i])], lat, lon).astype(np.float32)
    return acc / len(idx) * k + b


def _utc(epoch):
    return dt.datetime.fromtimestamp(epoch, dt.timezone.utc).replace(tzinfo=None)


def snotel_day(daily_next, day, tz_offset_h, zone, band, meta, log):
    """{'hn24': {(zone, band): in}, 'tmax': {...F}, 'tmin': {...F}} for `day` from the next day's SNOTEL series"""
    import newsnow
    sn = (daily_next or {}).get("snotel")
    if not sn:
        return {}
    cfg = newsnow.load_config()
    t_end = dt.datetime(day.year, day.month, day.day, 23, 59) - dt.timedelta(hours=tz_offset_h)      # naive UTC
    t_start = t_end - dt.timedelta(hours=24)
    pts = []
    for site in sn.get("sites") or []:
        ser = (sn.get("series") or {}).get(site["id"]) or {}
        rec = {"lat": site.get("lat"), "lon": site.get("lon")}
        depth = [(_utc(t), v) for t, v in ser.get("SNWD", []) if v is not None and v >= 0]
        if depth:
            rec["hn24"] = newsnow.new_snow(depth, t_end, [24], cfg).get(24)
        temps = [v for t, v in ser.get("TOBS", []) if t_start <= _utc(t) <= t_end and -60 < v < 130]
        if temps:
            rec["tmax"], rec["tmin"] = max(temps), min(temps)
        pts.append(rec)
    return {k: forcing.band_values(pts, zone, band, k, meta) for k in ("hn24", "tmax", "tmin")}


def aspect_within(aspect, direction, half_width):
    """True where a cell's aspect (deg, -1 flat) is within half_width of `direction` (deg); flat cells never are"""
    diff = np.abs((np.asarray(aspect, np.float32) - np.asarray(direction, np.float32) + 180.0) % 360.0 - 180.0)
    return (aspect >= 0) & (diff <= half_width) & np.isfinite(diff)


def fill_by_band(values, zone, band, fallback):
    """per-cell array from {(zone, band): v}; cells without a value take `fallback` (array or scalar)"""
    out = np.array(np.broadcast_to(np.asarray(fallback, np.float32), zone.shape), np.float32, copy=True)
    for (z, b), v in values.items():
        out[(zone == z) & (band == b)] = v
    return out


def day_forcing(day, lat, meta, latlon, tz_offset_h, scfg, p, log=print):
    """per-cell forcing arrays for `day` from the archive (day's hourlies and daily, next day's daily)"""
    latg, long_ = latlon
    d, dn = day.isoformat(), (day + dt.timedelta(days=1)).isoformat()
    daily = store.read_json("archive/%s/daily.json.gz" % d, log) or {}
    daily_next = store.read_json("archive/%s/daily.json.gz" % dn, log) or {}
    hourlies = [store.read_json("archive/%s/%s" % (d, n), log) for n in sorted(store.listing("archive/%s/" % d)) if n[:2].isdigit() and n.endswith(".json.gz")]
    hourlies = [h for h in hourlies if h]
    f = {}
    # precipitation: the next day's 24 h MRMS (valid at that day's first run) covers this day; else the hourly 1 h sum
    if daily_next.get("mrms24"):
        f["precip_in"] = forcing.sample(daily_next["mrms24"], latg, long_).astype(np.float32)
    else:
        acc, n = np.zeros(latg.shape, np.float32), 0
        for h in hourlies:
            if h.get("mrms1"):
                acc += np.nan_to_num(forcing.sample(h["mrms1"], latg, long_), nan=0.0)
                n += 1
        f["precip_in"] = acc if n else np.full(latg.shape, np.nan, np.float32)
    # freezing level: mean of the day's HRRR analyses
    fz = [forcing.sample(h["fz0"], latg, long_) for h in hourlies if h.get("fz0")]
    f["fzl_ft"] = np.nanmean(np.stack(fz), axis=0).astype(np.float32) if fz else np.full(latg.shape, np.nan, np.float32)
    # NDFD sky, dewpoint, wind from the day's own file
    nd = (daily.get("ndfd") or {}).get("fields") or {}
    sky, td, ws = nd.get("sky") or {}, nd.get("td") or {}, nd.get("wspd") or {}
    day_idx = _steps_in(sky, day, p["cloud_day_hours"], tz_offset_h) if sky else []
    night_idx = _steps_in(sky, day, p["cloud_night_hours"], tz_offset_h) if sky else []
    cloud_day = _mean_grid(sky, day_idx, latg, long_, 0.01)
    f["cloud_night"] = _mean_grid(sky, night_idx, latg, long_, 0.01)
    f["td_night_c"] = _mean_grid(td, _steps_in(td, day, p["cloud_night_hours"], tz_offset_h) if td else [], latg, long_, 5 / 9.0, -32 * 5 / 9.0)
    f["wind_night_ms"] = _mean_grid(ws, _steps_in(ws, day, p["cloud_night_hours"], tz_offset_h) if ws else [], latg, long_, 0.44704)
    wh = np.zeros(latg.shape, np.float32)
    lee = np.zeros(latg.shape, np.float32)
    wwd = np.zeros(latg.shape, np.float32)
    wd = nd.get("wdir") or {}
    aspect = lat["aspect"].astype(np.float32)
    if ws:
        idx = [i for i, v in enumerate(ws.get("valid_utc") or []) if _local_hour(v, tz_offset_h).date() == day and str(ws["steps"][i]) in ws.get("grids", {})]
        for i in idx:
            strong = forcing.sample(ws["grids"][str(ws["steps"][i])], latg, long_) >= p["wind_mph"]
            wh += 3.0 * strong
            sk = str(ws["steps"][i])
            if sk in wd.get("grids", {}):
                d = forcing.sample(wd["grids"][sk], latg, long_)          # direction the wind comes from
                lee += 3.0 * (strong & aspect_within(aspect, d + 180.0, p["wind_sector_deg"]))
                wwd += 3.0 * (strong & aspect_within(aspect, d, p["wind_sector_deg"]))
    f["wind_h"], f["wind_lee_h"], f["wind_wwd_h"] = wh, lee, wwd
    # temperature by zone x band from SNOTEL, NDFD max/min where no site
    sn = snotel_day(daily_next, day, tz_offset_h, lat["zone"], lat["band"], meta, log)
    fc = (daily.get("forecast") or {}).get("grids") or {}
    fb_max = forcing.sample(fc["maxt"], latg, long_) if fc.get("maxt") else np.full(latg.shape, np.nan, np.float32)
    fb_min = forcing.sample(fc["mint"], latg, long_) if fc.get("mint") else np.full(latg.shape, np.nan, np.float32)
    f["tmax_c"] = (fill_by_band(sn.get("tmax", {}), lat["zone"], lat["band"], fb_max) - 32) * 5 / 9
    f["tmin_c"] = (fill_by_band(sn.get("tmin", {}), lat["zone"], lat["band"], fb_min) - 32) * 5 / 9
    f["snotel_hn24_in"] = fill_by_band(sn.get("hn24", {}), lat["zone"], lat["band"], np.nan)
    # snow depth: the next day's SNODAS (dated this day) else this day's
    sd = (daily_next.get("snodas") or daily.get("snodas") or {}).get("grids") or {}
    f["depth_in"] = forcing.sample(sd["depth"], latg, long_).astype(np.float32) if sd.get("depth") else np.full(latg.shape, np.nan, np.float32)
    # solar on the cell under the day's cloud
    t0 = time.time()
    f["solar_mj"] = solar.daily_mj_binned(latg, long_, day, lat["slope"].astype(np.float32), lat["aspect"].astype(np.float32),
                                          np.maximum(lat["elev"], 0).astype(np.float32), np.nan_to_num(cloud_day, nan=0.5), scfg)
    f["solar_mj"][lat["elev"] == -32768] = 0
    log("state: forcing for %s: %d hourlies, precip max %.2f in, fzl %s ft, solar %.0f s"
        % (d, len(hourlies), np.nanmax(f["precip_in"]) if np.isfinite(f["precip_in"]).any() else 0,
           "%.0f-%.0f" % (np.nanmin(f["fzl_ft"]), np.nanmax(f["fzl_ft"])) if np.isfinite(f["fzl_ft"]).any() else "none", time.time() - t0))
    return f


# ---------------------------------------------------------------- run

def octants(aspect):
    return np.where(aspect < 0, 8, ((aspect + 22.5) // 45) % 8).astype(np.int64)


def summary(s, lat, meta, day):
    """class fractions by zone x band x aspect octant, for the site"""
    valid = s["cls"] != 255
    zone = lat["zone"] if "zone" in lat else np.full(s["cls"].shape, -1, np.int32)
    uz, inv = np.unique(zone, return_inverse=True)
    zs = [int(z) for z in uz if z >= 0]
    zi = {z: i for i, z in enumerate(zs)}
    zcell = np.array([zi.get(int(z), -1) for z in uz])[inv.reshape(zone.shape)]
    ok = valid & (zcell >= 0) & (lat["band"] != 255)
    key = ((zcell[ok] * 3 + lat["band"][ok].astype(np.int64)) * 9 + octants(lat["aspect"][ok])) * len(CLASSES) + s["cls"][ok]
    counts = np.bincount(key, minlength=len(zs) * 3 * 9 * len(CLASSES)).reshape(len(zs), 3, 9, len(CLASSES))
    out = {"date": day.isoformat(), "classes": CLASSES, "octants": ["N", "NE", "E", "SE", "S", "SW", "W", "NW", "flat"],
           "bands": ["below", "near", "above"], "zones": {}}
    names = meta.get("zones") or {}
    for z in zs:
        c = counts[zi[z]]
        tot = c.sum(axis=2, keepdims=True)
        frac = np.where(tot > 0, c / np.maximum(tot, 1), 0)
        out["zones"][str(z)] = {"name": (names.get(str(z)) or {}).get("name"), "cells": int(c.sum()),
                                "frac": np.round(frac, 3).tolist(), "hn24_cm": round(float(np.nanmean(s["hn24_cm"][ok & (zone == z)])), 1),
                                "days": round(float(np.mean(s["days"][ok & (zone == z)])), 1)}
    return out


def run(day, log=print, upload=True, force=False):
    t0 = time.time()
    p, scfg = load_params()
    lp = store.fetch("static/lattice.npz", log)
    meta = store.read_json("static/lattice.json", log)
    if not lp or not meta:
        raise SystemExit("state: no lattice (run the snow static workflow first)")
    lat = dict(np.load(lp))
    if "zone" not in lat:
        lat["zone"] = np.full(lat["elev"].shape, -1, np.int32)
    tz = region.cfg().get("tz_offset_h", -8)
    latlon = forcing.lattice_latlon(meta)
    f = day_forcing(day, lat, meta, latlon, tz, scfg, p, log)
    prev_path = store.fetch("state/latest.npz", log)
    if prev_path:
        prev = np.load(prev_path)
        prev_day = str(prev["day"]) if "day" in prev else None
        if prev_day and prev_day >= day.isoformat() and not force:
            log("state: latest state is for %s, nothing to do for %s (use --force to step again)" % (prev_day, day))
            return None
        s = {k: (prev[k] if k in prev else np.zeros(prev["cls"].shape, t)) for k, t in FIELDS.items()}
    else:
        s = new_state(lat["elev"].shape, f["depth_in"], p["min_depth_in"], lat["elev"] != -32768)
        prev_day = None
    s = step(s, f, lat, p, scfg)
    os.makedirs(store.local("state"), exist_ok=True)
    np.savez_compressed(store.local("state/latest.npz"), day=day.isoformat(), **s)
    np.savez_compressed(store.local("state/%s_cls.npz" % day.isoformat()), cls=s["cls"], hn24_cm=s["hn24_cm"].astype(np.float16))
    summ = summary(s, lat, meta, day)
    summ["prev_day"] = prev_day
    for fn in ("state/%s.json" % day.isoformat(), "state/latest.json"):
        with open(store.local(fn), "w", encoding="utf-8") as fh:
            json.dump(summ, fh, separators=(",", ":"))
    if upload:
        for rel, cache in (("state/latest.npz", "private, max-age=0"), ("state/%s_cls.npz" % day.isoformat(), "public, max-age=31536000, immutable"),
                           ("state/%s.json" % day.isoformat(), "public, max-age=31536000, immutable"), ("state/latest.json", "no-cache")):
            store.put(rel, cache, log)
    ok = s["cls"] != 255
    dist = {CLASSES[i]: round(float((s["cls"][ok] == i).mean()), 3) for i in range(len(CLASSES))}
    log("state %s: prev %s, %s, %.0f s" % (day, prev_day, ", ".join("%s %.0f%%" % (k, v * 100) for k, v in dist.items() if v >= 0.005), time.time() - t0))
    return summ


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None, help="YYYY-MM-DD (default: yesterday, local)")
    ap.add_argument("--no-upload", action="store_true")
    ap.add_argument("--force", action="store_true", help="step even when the saved state is already at or past this date")
    a = ap.parse_args()
    d = dt.date.fromisoformat(a.date) if a.date else dt.date.today() - dt.timedelta(days=1)
    run(d, upload=not a.no_upload, force=a.force)
