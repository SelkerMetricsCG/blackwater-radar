"""
Surface-state model: one day per cell of the terrain lattice, from the season archive.

State (per cell, carried day to day in <region>/snow/state/latest.npz):
  cls        surface class (CLASSES index; 255 off the lattice)
  days       days since the last fresh snowfall (capped at 250)
  hn24_cm    yesterday's new snow on the cell (MRMS liquid x snow fraction x SLR from temperature); the snow fraction is
             taken hour by hour from the HRRR freezing level, weighted by each hour's MRMS 1 h precipitation (day_forcing)
  solar_mj   MJ/m2 on the cell since the last fresh snow (snow/solar.py, NDFD sky cover)
  wind_h     hours of NDFD 10 m wind above the surface's transport threshold since the last fresh snow (wind_mph_dry
             for dry snow, wind_mph_wet for a wet or melt-freeze surface; crusts never transport)
  wind_lee_h / wind_wwd_h   of those, the hours the cell was in the lee (aspect within wind_sector of the downwind
             direction: loading) or windward (facing the wind: scouring), from NDFD wind direction
  rain       1 when rain fell on the cell since the last fresh snow; rain_refrozen 1 once the band min has dropped
             below rain_refreeze_tmin_c since (rain_wet until then, rain_crust after)
  canopy_load  snow held on the trees (0..1): grows with new snow that fell near 0 C, drops to 0 when wind or
             warmth releases it; a release under dense canopy makes the surface `tree_debris` for a day
  melt_days  consecutive days of surface melt without a solid overnight refreeze
  refreeze   last night's refreeze index (0..1)
  depth_in   SNODAS snow depth

Rules and parameters: snow_config.yaml `state` (all placeholders until the residual ledger exists; see the spec).
Any new snow of fresh_cm or more shows (fresh), even where SNODAS, dated the evening before, still calls the ground
bare; under bury_cm on a crust it is dust_on_crust and the crust's clocks keep running.
Class priority, first match wins: no_snow, fresh, dust_on_crust, tree_debris, isothermal, melt_freeze, rain_crust,
rain_wet, sun_crust, wind_scoured, wind_loaded, wind (direction unknown), fresh (the storm day and the next),
settled (powder 2-7 days old), settled_late (8-14 days), old (over 14 days with no crust trigger: the north-facing
pocket). The day's sun is also cut by the terrain's horizon (lattice `horizon`), the snow's albedo ages from fresh
(USACE 1956 decay, faster when the surface melts), and under a canopy part of what the dark trees absorb reaches the
snow as longwave (canopy_lw_fraction).

Per cell before the rules: the band temperatures are lapsed from the band's sites to the cell's elevation
(lapse_c_per_km); the day's solar is cut by the canopy (canopy_solar_tau) and counts toward a sun crust only in
proportion to how warm the day was (crust_tmin_c..crust_tfull_c); the refreeze index is reduced under canopy.

  python -m snow.state --date 2026-01-15      run one day (yesterday by default); reads and writes R2 through snow/store.py
  python -m snow.state --start 2026-09-28 --date 2026-10-10    re-run a range from a fresh state (after a fix)
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
           "wind_loaded", "wind_scoured", "tree_debris", "rain_wet", "settled_late"]
CID = {c: i for i, c in enumerate(CLASSES)}
CRUSTS = (CID["sun_crust"], CID["rain_crust"], CID["melt_freeze"], CID["isothermal"], CID["wind"], CID["wind_loaded"], CID["wind_scoured"])
WET = CID["rain_wet"]
WET_SURFACE = (CID["rain_wet"], CID["melt_freeze"], CID["isothermal"])          # transport only above wind_mph_wet
NO_TRANSPORT = (CID["sun_crust"], CID["rain_crust"])                             # a crust does not blow around
OLD_DAYS = 14
# fresh and dust_on_crust were near-white until 2026-10-11 and vanished on the site's light topo basemap (judgment call)
PALETTE = {"no_snow": "transparent", "fresh": "#00c3ff", "settled": "#6baed6", "wind": "#969696", "sun_crust": "#fdae6b",
           "rain_crust": "#e6550d", "melt_freeze": "#fee08b", "isothermal": "#a63603", "dust_on_crust": "#9e9ac8", "old": "#2171b5",
           "wind_loaded": "#636363", "wind_scoured": "#bdbdbd", "tree_debris": "#74c476", "rain_wet": "#a1d99b", "settled_late": "#4292c6"}
PNG_WIDTH = 1200
FIELDS = {"cls": np.uint8, "days": np.uint8, "hn24_cm": np.float32, "solar_mj": np.float32, "wind_h": np.float32,
          "wind_lee_h": np.float32, "wind_wwd_h": np.float32, "canopy_load": np.float32,
          "rain": np.uint8, "rain_refrozen": np.uint8, "melt_days": np.uint8, "refreeze": np.float32, "depth_in": np.float32}


def cfg_lattice(path=CONFIG):
    import yaml
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)["lattice"]


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


def prev_shape(s):
    return s["cls"].shape


def albedo_aged(days, cls, tmax_c, p):
    """USACE (1956) snow albedo decay as in VIC and FSM: albedo_fresh x A^(t^B), the cold pair (A, B) where the day's
    max stays below 0 C, the melting pair where it does not (melt roughens and wets the surface faster than dry aging)"""
    t = np.asarray(days, np.float32)
    melting = np.asarray(tmax_c, np.float32) >= 0.0
    a = np.where(melting, p["albedo_melt_a"], p["albedo_cold_a"]).astype(np.float32)
    b = np.where(melting, p["albedo_melt_b"], p["albedo_cold_b"]).astype(np.float32)
    return (p["albedo_fresh"] * a ** (t ** b)).astype(np.float32)


def snow_fraction(elev_ft, fzl_ft, p):
    """share of precipitation falling as snow at elev_ft under a freezing level: the snow level sits rain_line_margin_ft
    below it, mixed rain and snow within rain_mix_ft of the snow level"""
    snow_level = fzl_ft - p["rain_line_margin_ft"]
    return np.clip((elev_ft - snow_level + p["rain_mix_ft"]) / (2.0 * p["rain_mix_ft"]), 0, 1)


def step(s, f, lat, p, scfg):
    """advance one day. f: forcing dict of per-cell arrays (see day_forcing); lat: dict of lattice arrays"""
    valid = lat["elev"] != -32768
    elev_ft = lat["elev"].astype(np.float32) * 3.28084
    snowfrac = snow_fraction(elev_ft, f["fzl_ft"], p)
    snowfrac = np.where(np.isnan(f["fzl_ft"]), 1.0, snowfrac)          # no freezing level: assume snow (winter default)
    if "snow_frac" in f:                                                # hour by hour, weighted by when the precipitation fell
        snowfrac = np.where(np.isfinite(f["snow_frac"]), f["snow_frac"], snowfrac)
    precip = np.nan_to_num(f["precip_in"], nan=0.0)
    # temperatures lapsed from the band's sites to the cell (only where the band value came from sites)
    dz_km = np.nan_to_num(f.get("site_elev_m", np.full(precip.shape, np.nan)) - lat["elev"].astype(np.float32), nan=0.0) / 1000.0
    tmax = np.nan_to_num(f["tmax_c"], nan=-5.0) + p["lapse_c_per_km"] * dz_km
    tmin = np.nan_to_num(f["tmin_c"], nan=-10.0) + p["lapse_c_per_km"] * dz_km
    t_mean = 0.5 * (tmax + tmin)
    canopy = lat["canopy"].astype(np.float32) / 100.0 if "canopy" in lat else np.zeros(precip.shape, np.float32)
    canopy = np.where(canopy > 2.0, 0.0, canopy)                               # 255 = no data
    # the day's sun: cut by the canopy, and counting toward a crust only in proportion to the day's warmth
    under = p["canopy_solar_tau"] + p["canopy_lw_fraction"] * (1 - p["canopy_solar_tau"])   # sun through, plus longwave off the trees
    solar_cell = np.nan_to_num(f["solar_mj"], nan=0.0) * ((1 - canopy) + canopy * under)
    warm = np.clip((tmax - p["crust_tmin_c"]) / max(p["crust_tfull_c"] - p["crust_tmin_c"], 0.1), 0, 1)
    albedo = np.clip(albedo_aged(s["days"], s["cls"], tmax, p), p["albedo_min"], p["albedo_fresh"])
    absorbed = (1 - albedo) / (1 - p["albedo_ref"])                                       # 1 at the reference albedo
    solar_crusting = solar_cell * warm * absorbed
    slr = np.clip(p["slr_at_0c"] + p["slr_per_c"] * np.maximum(-t_mean, 0), p["slr_at_0c"], p["slr_max"])
    hn24 = precip * snowfrac * slr * 2.54
    rain_in = precip * (1 - snowfrac)
    prev = s["cls"]
    new_snow = hn24 >= p["fresh_cm"]                                   # any measurable new snow
    dust = new_snow & (hn24 < p["bury_cm"]) & np.isin(prev, CRUSTS)    # thin new snow on a crust: the crust's history stands
    fresh = new_snow & ~dust                                           # a fresh surface: the clocks restart
    days = np.where(fresh, 0, np.minimum(s["days"].astype(np.int32) + 1, 250))
    solar_mj = np.where(fresh, 0, s["solar_mj"] + solar_crusting)
    # the day's transporting hours depend on yesterday's surface: dry snow moves at wind_mph_dry, a wet or melt-freeze
    # surface at wind_mph_wet, a crust not at all (Li & Pomeroy 1997); the forcing carries both counts
    wet = np.isin(s["cls"], WET_SURFACE)
    crust = np.isin(s["cls"], NO_TRANSPORT)

    def todays(key):
        dry = np.nan_to_num(f.get(key, 0.0), nan=0.0)
        w = np.nan_to_num(f.get(key + "_wet", dry), nan=0.0)
        return np.where(crust, 0.0, np.where(wet, w, dry))
    wind_h = np.where(fresh, 0, s["wind_h"] + todays("wind_h"))
    wind_lee_h = np.where(fresh, 0, s.get("wind_lee_h", 0) + todays("wind_lee_h"))
    wind_wwd_h = np.where(fresh, 0, s.get("wind_wwd_h", 0) + todays("wind_wwd_h"))
    rained_today = rain_in >= p["rain_in"]
    rain = np.where(fresh, 0, np.maximum(s["rain"], rained_today)).astype(np.uint8)
    refrozen = np.where(fresh, 0, np.maximum(s.get("rain_refrozen", np.zeros(rain.shape, np.uint8)), (rain == 1) & (tmin < p["rain_refreeze_tmin_c"]))).astype(np.uint8)
    refreeze = solar.refreeze_index(tmin, np.nan_to_num(f["cloud_night"], nan=0.5),
                                    np.nan_to_num(f["td_night_c"], nan=-5.0), np.nan_to_num(f["wind_night_ms"], nan=2.0))
    refreeze = refreeze * (1 - p["canopy_refreeze_loss"] * canopy)
    melt = (tmax > p["melt_tmax_c"]) & (solar_cell > 1.0)
    solid = refreeze >= p["refreeze_good"]
    corn = melt & solid
    melt_days = np.where(melt & ~solid, np.minimum(s["melt_days"].astype(np.int32) + 1, 250), 0)
    depth = np.where(np.isnan(f["depth_in"]), s["depth_in"], f["depth_in"]).astype(np.float32)
    sticky = (t_mean >= p["tree_load_tmin_c"]) & (t_mean <= p["tree_load_tmax_c"])
    carried = s.get("canopy_load", np.zeros(canopy.shape, np.float32)) * (1 - p["tree_load_decay"])   # quiet shedding
    load = np.clip(carried + np.where(sticky, hn24 / p["tree_load_full_cm"], 0.0) * (canopy > 0.1), 0, 1)
    release = (load >= p["tree_release_load"]) & ((np.nan_to_num(f["wind_h"], nan=0.0) >= p["tree_release_wind_h"]) | (tmax > p["tree_release_tmax_c"]))
    load = np.where(release, 0.0, load)
    cls = np.full(prev.shape, CID["old"], np.uint8)
    cls[days <= OLD_DAYS] = CID["settled_late"]
    cls[days <= p["settled_days"]] = CID["settled"]
    cls[days < p["settle_days"]] = CID["fresh"]
    cls[wind_h >= p["wind_hours"]] = CID["wind"]
    cls[wind_lee_h >= p["wind_hours"]] = CID["wind_loaded"]
    cls[wind_wwd_h >= p["wind_hours"]] = CID["wind_scoured"]
    cls[solar_mj >= p["solar_crust_mj"]] = CID["sun_crust"]
    cls[(rain == 1) & (refrozen == 0)] = CID["rain_wet"]
    cls[(rain == 1) & (refrozen == 1)] = CID["rain_crust"]
    cls[corn] = CID["melt_freeze"]
    cls[melt_days >= p["isothermal_days"]] = CID["isothermal"]
    cls[release & (canopy >= p["tree_debris_canopy"]) & ~new_snow] = CID["tree_debris"]
    cls[dust] = CID["dust_on_crust"]
    cls[fresh] = CID["fresh"]
    # SNODAS is dated the evening before the day, so it cannot know about the day's own snow: that shows regardless
    cls[(depth < p["min_depth_in"]) & ~new_snow] = CID["no_snow"]
    cls[~valid] = 255
    return {"cls": cls, "days": days.astype(np.uint8), "hn24_cm": hn24.astype(np.float32), "solar_mj": solar_mj.astype(np.float32),
            "wind_h": wind_h.astype(np.float32), "wind_lee_h": wind_lee_h.astype(np.float32), "wind_wwd_h": wind_wwd_h.astype(np.float32),
            "canopy_load": load.astype(np.float32), "rain": rain, "rain_refrozen": refrozen, "melt_days": melt_days.astype(np.uint8),
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
    """zone and band are the FULL lattice rasters (sites are located on the lattice), whatever subset the model runs on"""
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
        rec = {"lat": site.get("lat"), "lon": site.get("lon"), "elev_m": (site.get("elev") * 0.3048) if site.get("elev") is not None else None}
        depth = [(_utc(t), v) for t, v in ser.get("SNWD", []) if v is not None and v >= 0]
        if depth:
            rec["hn24"] = newsnow.new_snow(depth, t_end, [24], cfg).get(24)
        temps = [v for t, v in ser.get("TOBS", []) if t_start <= _utc(t) <= t_end and -60 < v < 130]
        if temps:
            rec["tmax"], rec["tmin"] = max(temps), min(temps)
        pts.append(rec)
    for p_ in pts:
        p_["elev_m"] = p_.get("elev_m")
    return {k: forcing.band_values(pts, zone, band, k, meta) for k in ("hn24", "tmax", "tmin", "elev_m")}


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


def _iso_utc(s):
    """naive UTC datetime from an archive time string ('2026-10-09T18:00'), or None"""
    try:
        return dt.datetime.fromisoformat(s) if isinstance(s, str) and s else None
    except ValueError:
        return None


def precip_hours(hourlies, backfill, end_utc):
    """[(valid time, MRMS 1 h grid)] in the 24 h ending at end_utc, each valid hour once: the archive's hourly files
    first (a stalled feed repeats its last hour in later files), then the hours snow/backfill.py filled in"""
    out = {}
    for h in hourlies:
        g = h.get("mrms1") or {}
        v = _iso_utc(g.get("valid_utc"))
        if v and v not in out:
            out[v] = g
    for k, g in ((backfill or {}).get("hours") or {}).items():
        v = _iso_utc(k)
        if v and v not in out:
            out[v] = g
    return sorted((v, g) for v, g in out.items() if end_utc - dt.timedelta(hours=24) < v <= end_utc)


def day_forcing(day, lat, meta, latlon, tz_offset_h, scfg, p, log=print, locate=None):
    """per-cell forcing arrays for `day` from the archive (day's hourlies and daily, next day's daily). `lat` may be a
    subset of the lattice (1-D arrays, snow/replay.py); then `locate` = (zone, band) of the full lattice for site lookup"""
    zone_full, band_full = locate if locate else (lat["zone"], lat["band"])
    latg, long_ = latlon
    d, dn = day.isoformat(), (day + dt.timedelta(days=1)).isoformat()
    daily = store.read_json("archive/%s/daily.json.gz" % d, log) or {}
    daily_next = store.read_json("archive/%s/daily.json.gz" % dn, log) or {}
    names = sorted(store.listing("archive/%s/" % d))
    hourlies = [store.read_json("archive/%s/%s" % (d, n), log) for n in names if n[:2].isdigit() and n.endswith(".json.gz")]
    hourlies = [h for h in hourlies if h]
    backfill = store.read_json("archive/%s/mrms1h.json.gz" % d, log) if "mrms1h.json.gz" in names else None
    f = {}
    # the 24 h the day's precipitation covers: up to the next day's 24 h MRMS valid time, else local midnight
    end_utc = _iso_utc((daily_next.get("mrms24") or {}).get("valid_utc")) or (dt.datetime.combine(day + dt.timedelta(days=1), dt.time())
                                                                           - dt.timedelta(hours=tz_offset_h))
    wet = precip_hours(hourlies, backfill, end_utc)
    # precipitation: the sum of the 1 h grids when all 24 hours of the window are there (each valid hour once; the
    # nightly job backfills the gaps first), else the next day's 24 h MRMS (valid at that day's first run), else the
    # hours there are. NOAA's 24 h Pass 2 total drops hours its own feed skipped: 2026-10-10 it read 0 at Snoqualmie
    # and Sasse Ridge where the hours (Pass 1) held 0.13-0.19 in
    if len(wet) >= 24:
        f["precip_in"] = sum(np.nan_to_num(forcing.sample(g, latg, long_), nan=0.0) for _, g in wet).astype(np.float32)
    elif daily_next.get("mrms24"):
        f["precip_in"] = forcing.sample(daily_next["mrms24"], latg, long_).astype(np.float32)
    elif wet:
        f["precip_in"] = sum(np.nan_to_num(forcing.sample(g, latg, long_), nan=0.0) for _, g in wet).astype(np.float32)
    else:
        f["precip_in"] = np.full(latg.shape, np.nan, np.float32)
    # freezing level: mean of the day's HRRR analyses; and the snow fraction hour by hour: each wet hour's MRMS 1 h
    # under the HRRR analysis nearest its middle, weighted by that hour's precipitation (a front that drops the freezing
    # level from 14,000 to 5,000 ft in a day puts its evening precipitation down as snow, not as the day-mean's rain)
    fzs = [(_iso_utc(h["fz0"].get("run_utc")), h["fz0"]) for h in hourlies if h.get("fz0")]
    timed = [i for i, (r, _) in enumerate(fzs) if r]
    pair = {}
    for v, g in wet:
        if timed and max(g.get("data") or [0]) > 0:
            mid = v - dt.timedelta(minutes=30)
            i = min(timed, key=lambda i: (abs((fzs[i][0] - mid).total_seconds()), fzs[i][0]))
            pair.setdefault(i, []).append(g)
    elev_ft = lat["elev"].astype(np.float32) * 3.28084
    fz_sum, fz_n = np.zeros(latg.shape, np.float64), np.zeros(latg.shape, np.int32)
    w_sum, wf_sum = np.zeros(latg.shape, np.float32), np.zeros(latg.shape, np.float32)
    for i, (_, g) in enumerate(fzs):
        fz = forcing.sample(g, latg, long_)
        ok = np.isfinite(fz)
        fz_sum[ok] += fz[ok]
        fz_n += ok
        for pg in pair.get(i, []):
            w = np.nan_to_num(forcing.sample(pg, latg, long_), nan=0.0).astype(np.float32)
            m = ok & (w > 0)
            w_sum[m] += w[m]
            wf_sum[m] += (w * snow_fraction(elev_ft, np.nan_to_num(fz), p))[m]
    f["fzl_ft"] = np.where(fz_n > 0, fz_sum / np.maximum(fz_n, 1), np.nan).astype(np.float32)
    f["snow_frac"] = np.where(w_sum > 0, wf_sum / np.maximum(w_sum, 1e-9), np.nan).astype(np.float32)
    f["phase_hours"] = sum(len(v) for v in pair.values())
    # NDFD sky, dewpoint, wind from the day's own file
    nd = (daily.get("ndfd") or {}).get("fields") or {}
    sky, td, ws = nd.get("sky") or {}, nd.get("td") or {}, nd.get("wspd") or {}
    day_idx = _steps_in(sky, day, p["cloud_day_hours"], tz_offset_h) if sky else []
    night_idx = _steps_in(sky, day, p["cloud_night_hours"], tz_offset_h) if sky else []
    cloud_day = _mean_grid(sky, day_idx, latg, long_, 0.01)
    f["cloud_night"] = _mean_grid(sky, night_idx, latg, long_, 0.01)
    f["td_night_c"] = _mean_grid(td, _steps_in(td, day, p["cloud_night_hours"], tz_offset_h) if td else [], latg, long_, 5 / 9.0, -32 * 5 / 9.0)
    f["wind_night_ms"] = _mean_grid(ws, _steps_in(ws, day, p["cloud_night_hours"], tz_offset_h) if ws else [], latg, long_, 0.44704)
    # hours above each transport threshold (dry snow, wet surface); step() picks per cell by yesterday's surface
    thr = {"": p["wind_mph_dry"], "_wet": p["wind_mph_wet"]}
    wh = {k: np.zeros(latg.shape, np.float32) for k in thr}
    lee = {k: np.zeros(latg.shape, np.float32) for k in thr}
    wwd = {k: np.zeros(latg.shape, np.float32) for k in thr}
    wd = nd.get("wdir") or {}
    aspect = lat["aspect"].astype(np.float32)
    if ws:
        idx = [i for i, v in enumerate(ws.get("valid_utc") or []) if _local_hour(v, tz_offset_h).date() == day and str(ws["steps"][i]) in ws.get("grids", {})]
        for i in idx:
            sk = str(ws["steps"][i])
            speed = forcing.sample(ws["grids"][sk], latg, long_)
            wdir = forcing.sample(wd["grids"][sk], latg, long_) if sk in wd.get("grids", {}) else None   # direction the wind comes from
            if wdir is not None and "sx" in lat:
                # Winstral shelter toward the wind's octant: sheltered cells see less wind, exposed ridges more
                k = (np.round(np.nan_to_num(wdir, nan=0.0) / 45.0).astype(np.int64)) % 8
                sxk = np.take_along_axis(lat["sx"].astype(np.float32), k[None, ...], axis=0)[0]
                speed = speed * np.clip(1.0 - p["wind_sx_per_deg"] * sxk, p["wind_expo_min"], p["wind_expo_max"])
            for k, mph in thr.items():
                strong = speed >= mph
                wh[k] += 3.0 * strong
                if wdir is not None:
                    lee[k] += 3.0 * (strong & aspect_within(aspect, wdir + 180.0, p["wind_sector_deg"]))
                    wwd[k] += 3.0 * (strong & aspect_within(aspect, wdir, p["wind_sector_deg"]))
    for k in thr:
        f["wind_h" + k], f["wind_lee_h" + k], f["wind_wwd_h" + k] = wh[k], lee[k], wwd[k]
    # temperature by zone x band from SNOTEL, NDFD max/min where no site
    sn = snotel_day(daily_next, day, tz_offset_h, zone_full, band_full, meta, log)
    fc = (daily.get("forecast") or {}).get("grids") or {}
    fb_max = forcing.sample(fc["maxt"], latg, long_) if fc.get("maxt") else np.full(latg.shape, np.nan, np.float32)
    fb_min = forcing.sample(fc["mint"], latg, long_) if fc.get("mint") else np.full(latg.shape, np.nan, np.float32)
    f["tmax_c"] = (fill_by_band(sn.get("tmax", {}), lat["zone"], lat["band"], fb_max) - 32) * 5 / 9
    f["tmin_c"] = (fill_by_band(sn.get("tmin", {}), lat["zone"], lat["band"], fb_min) - 32) * 5 / 9
    f["snotel_hn24_in"] = fill_by_band(sn.get("hn24", {}), lat["zone"], lat["band"], np.nan)
    f["site_elev_m"] = fill_by_band({k: v for k, v in sn.get("elev_m", {}).items() if k in sn.get("tmax", {})}, lat["zone"], lat["band"], np.nan)
    # the station network's own temperature field (elevation regression per zone + interpolated residuals) beats
    # band means where enough stations reported; it also says where cold air pooled overnight
    try:
        from snow import tfield
        tf = tfield.fields(hourlies, daily_next, day, tz_offset_h, lat, meta, latg, long_, zone_full, band_full, p, log)
        if tf:
            f["tmax_c"], f["tmin_c"], f["tmin_resid_c"] = tf["tmax_c"], tf["tmin_c"], tf["tmin_resid_c"]
            f["site_elev_m"] = np.full(latg.shape, np.nan, np.float32)          # already at the cell's elevation
            f["tfield"] = {"n": tf["n"], "loo_mae": tf.get("loo_mae"), "lapse_min": tf.get("lapse_min"),
                           "pooled_lapse_min": tf.get("pooled_lapse_min"), "inversions": tf.get("inversions")}
    except Exception as e:  # noqa: BLE001
        log("state: station temperature field failed (%r); band means used" % e)
    # snow depth: SNODAS dated this day (valid 06Z, the evening before), filed in the day's folder by the run that
    # downloaded it (or by snow/backfill.py); the daily files' copies were empty until 2026-10-11
    own = store.read_json("archive/%s/snodas.json.gz" % d, log) if "snodas.json.gz" in names else None
    sd = next((g for g in (((src or {}).get("grids") or {}) for src in (own, daily_next.get("snodas"), daily.get("snodas"))) if g.get("depth")), {})
    f["depth_in"] = forcing.sample(sd["depth"], latg, long_).astype(np.float32) if sd.get("depth") else np.full(latg.shape, np.nan, np.float32)
    # solar on the cell under the day's cloud
    t0 = time.time()
    # direct sun cut by the terrain's horizon, diffuse sky by the sky-view factor, plus what the surrounding slopes
    # reflect (Dozier & Frew 1990); the lattice stores svf in percent
    parts = solar.daily_components_binned(latg, long_, day, lat["slope"].astype(np.float32), lat["aspect"].astype(np.float32),
                                          np.maximum(lat["elev"], 0).astype(np.float32), np.nan_to_num(cloud_day, nan=0.5), scfg)
    tf = solar.terrain_factor(lat["horizon"], latg, day, scfg, direct_share=1.0) if "horizon" in lat else 1.0
    svf = lat["svf"].astype(np.float32) / 100.0 if "svf" in lat else 1.0
    f["solar_mj"] = solar.terrain_irradiance(parts, tf, svf, cfg=scfg)
    f["solar_mj"][lat["elev"] == -32768] = 0
    log("state: forcing for %s: %d hourlies, precip max %.2f in (%s), fzl %s ft, %d wet hours for the snow fraction (%d backfilled), "
        "snodas %s, solar %.0f s"
        % (d, len(hourlies), np.nanmax(f["precip_in"]) if np.isfinite(f["precip_in"]).any() else 0,
           "24 hourly grids" if len(wet) >= 24 else "24 h grid" if daily_next.get("mrms24") else "%d hourly grids" % len(wet),
           "%.0f-%.0f" % (np.nanmin(f["fzl_ft"]), np.nanmax(f["fzl_ft"])) if np.isfinite(f["fzl_ft"]).any() else "none",
           f["phase_hours"], len((backfill or {}).get("hours") or {}), "yes" if sd.get("depth") else "none", time.time() - t0))
    return f


# ---------------------------------------------------------------- run

def octants(aspect):
    return np.where(aspect < 0, 8, ((aspect + 22.5) // 45) % 8).astype(np.int64)


def summary(s, lat, meta, day, new_cm=1.0):
    """class fractions by zone x band x aspect octant, for the site; and per zone and band (by_band: below, near, above
    treeline) the day's new snow: mean, 90th percentile and max cm, and the share of cells with new_cm or more"""
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
    hn = np.nan_to_num(np.asarray(s["hn24_cm"], np.float32), nan=0.0)
    for z in zs:
        zm = ok & (zone == z)
        bands = []
        for b in range(3):
            h = hn[zm & (lat["band"] == b)]
            bands.append({"cells": int(h.size)} if not h.size else
                         {"cells": int(h.size), "hn24_mean": round(float(h.mean()), 1), "hn24_p90": round(float(np.percentile(h, 90)), 1),
                          "hn24_max": round(float(h.max()), 1), "new_share": round(float((h >= new_cm).mean()), 3)})
        out["zones"][str(z)]["by_band"] = bands
    return out


def resummarize_range(start, end, log=print, upload=True, png=False):
    """rebuild the zone summaries (state/<d>.json/.js, and latest.* for the newest day) from each day's class snapshot
    (<d>_cls.npz: class and hn24 per cell) after summary() gained a field; days since snowfall are not in the snapshot and
    are kept from the old summary, as are prev_day, tfield and the assimilation flag. The model is not stepped.
    png=True also redraws each day's class PNG (and its _cls.js) in the current PALETTE, under a new ?v= so caches let go."""
    p, _ = load_params()
    lp = store.fetch("static/lattice.npz", log)
    meta = store.read_json("static/lattice.json", log)
    if not lp or not meta:
        raise SystemExit("resummarize: no lattice")
    lat = dict(np.load(lp))
    if "zone" not in lat:
        lat["zone"] = np.full(lat["elev"].shape, -1, np.int32)
    latest = (store.read_json("state/index.json", log) or {}).get("latest")
    day = start
    while day <= end:
        d = day.isoformat()
        snap = store.fetch("state/%s_cls.npz" % d, log)
        if not snap:
            log("resummarize %s: no class snapshot" % d)
            day += dt.timedelta(days=1)
            continue
        z = np.load(snap)
        s = {"cls": z["cls"], "hn24_cm": z["hn24_cm"].astype(np.float32), "days": np.zeros(z["cls"].shape, np.uint8)}
        old = store.read_json("state/%s.json" % d, log) or {}
        summ = summary(s, lat, meta, day, p["fresh_cm"])
        for k, v in old.items():
            if k not in summ:
                summ[k] = v
        for zid, zz in summ["zones"].items():
            zz["days"] = ((old.get("zones") or {}).get(zid) or {}).get("days", zz["days"])
        write_js("state/%s" % d, "SNOW_STATE", summ)
        rels = [("state/%s.json" % d, "public, max-age=31536000, immutable"), ("state/%s.js" % d, "public, max-age=31536000, immutable")]
        if d == latest:
            write_js("state/latest", "SNOW_STATE", summ)
            rels += [("state/latest.json", "no-cache"), ("state/latest.js", "no-cache")]
        if png:
            img, bounds = class_png(s["cls"], meta, cfg_lattice())
            img.save(store.local("state/%s_cls.png" % d), "PNG", optimize=True)
            clsmeta = {"date": d, "bounds": bounds, "palette": PALETTE, "classes": CLASSES, "file": "state/%s_cls.png?v=%d" % (d, int(time.time()))}
            write_js("state/%s_cls" % d, "SNOW_CLS", clsmeta)
            rels += [("state/%s_cls.png" % d, "public, max-age=31536000, immutable"), ("state/%s_cls.js" % d, "public, max-age=31536000, immutable"),
                     ("state/%s_cls.json" % d, "public, max-age=31536000, immutable")]
            if d == latest:
                img.save(store.local("state/latest_cls.png"), "PNG", optimize=True)
                write_js("state/latest_cls", "SNOW_CLS", dict(clsmeta, file="state/latest_cls.png"))
                rels += [("state/latest_cls.png", "no-cache"), ("state/latest_cls.js", "no-cache"), ("state/latest_cls.json", "no-cache")]
        if upload:
            for rel, cache in rels:
                store.put(rel, cache, log)
        top = max(((zz["name"] or zid, zz["by_band"][2].get("new_share", 0)) for zid, zz in summ["zones"].items()), key=lambda t: t[1], default=("-", 0))
        log("resummarize %s: %d zones%s; most new snow above treeline: %s %.0f %%" % (d, len(summ["zones"]), " (latest)" if d == latest else "", top[0], 100 * top[1]))
        day += dt.timedelta(days=1)


def write_js(rel, var, obj):
    """<rel>.json and <rel>.js (window.<var> = ...) under the snow store; the page reads the .js (no CORS on R2)"""
    os.makedirs(os.path.dirname(store.local(rel + ".json")), exist_ok=True)
    with open(store.local(rel + ".json"), "w", encoding="utf-8") as f:
        json.dump(obj, f, separators=(",", ":"))
    with open(store.local(rel + ".js"), "w", encoding="utf-8") as f:
        f.write("window.%s = %s;\n" % (var, json.dumps(obj, separators=(",", ":"))))


def class_png(cls, meta, cfg, width=PNG_WIDTH):
    """RGBA image of the classes on a Web Mercator grid over the lattice bbox (transparent off the lattice), and
    its Leaflet bounds [[S, W], [N, E]]"""
    import math
    from PIL import Image
    w, s_, e, n = cfg["bbox_lonlat"]
    my = lambda lat: math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))  # noqa: E731
    y0, y1 = my(s_), my(n)
    height = int(round(width * (y1 - y0) / math.radians(e - w)))
    lon = np.linspace(w, e, width, endpoint=False) + (e - w) / width / 2
    ys = np.linspace(y1, y0, height, endpoint=False) - (y1 - y0) / height / 2
    lat = np.degrees(2 * np.arctan(np.exp(ys)) - np.pi / 2)
    LAT, LON = np.meshgrid(lat, lon, indexing="ij")
    r, c = forcing.cell_of(meta, LAT.ravel(), LON.ravel())
    v = np.full(r.shape, 255, np.uint8)
    ok = r >= 0
    v[ok] = cls[r[ok], c[ok]]
    v = v.reshape(height, width)
    rgba = np.zeros((height, width, 4), np.uint8)
    for i, name in enumerate(CLASSES):
        col = PALETTE.get(name, "#888888")
        if col == "transparent":
            continue
        rgb = tuple(int(col[j:j + 2], 16) for j in (1, 3, 5))
        m = v == i
        rgba[m, :3] = rgb
        rgba[m, 3] = 255
    return Image.fromarray(rgba, "RGBA"), [[s_, w], [n, e]]


def update_index(day):
    rel = "state/index"
    cur = store.read_json(rel + ".json", lambda *a: None) or {"dates": []}
    dates = sorted(set(cur.get("dates", [])) | {day})
    obj = {"dates": dates, "latest": dates[-1]}
    write_js(rel, "SNOW_INDEX", obj)
    return obj


def reclassify(s, lat, p):
    """the class from the continuous fields alone (no new forcing): used after an assimilation nudge"""
    prev = s["cls"]
    valid = lat["elev"] != -32768
    cls = np.full(prev.shape, CID["old"], np.uint8)
    days = s["days"].astype(np.int32)
    cls[days <= OLD_DAYS] = CID["settled_late"]
    cls[days <= p["settled_days"]] = CID["settled"]
    cls[days < p["settle_days"]] = CID["fresh"]
    cls[s["wind_h"] >= p["wind_hours"]] = CID["wind"]
    cls[s["wind_lee_h"] >= p["wind_hours"]] = CID["wind_loaded"]
    cls[s["wind_wwd_h"] >= p["wind_hours"]] = CID["wind_scoured"]
    cls[s["solar_mj"] >= p["solar_crust_mj"]] = CID["sun_crust"]
    cls[(s["rain"] >= 0.5) & (s.get("rain_refrozen", np.zeros(prev.shape, np.uint8)) < 0.5)] = CID["rain_wet"]
    cls[(s["rain"] >= 0.5) & (s.get("rain_refrozen", np.zeros(prev.shape, np.uint8)) >= 0.5)] = CID["rain_crust"]
    cls[(s["refreeze"] >= p["refreeze_good"]) & np.isin(prev, [CID["melt_freeze"]])] = CID["melt_freeze"]
    cls[s["melt_days"] >= p["isothermal_days"]] = CID["isothermal"]
    keep = np.isin(prev, [CID["dust_on_crust"], CID["tree_debris"], CID["melt_freeze"]])   # the day's transient calls stand
    cls[keep] = prev[keep]
    cls[days == 0] = CID["fresh"]
    cls[(s["depth_in"] < p["min_depth_in"]) & (days != 0)] = CID["no_snow"]
    cls[~valid] = 255
    return cls


def rewrite_outputs(s, lat, meta, day, log=print, upload=True):
    """after assimilation: reclassify, save latest.npz and the day's class snapshot, regenerate summary, PNG, js"""
    p, _ = load_params()
    s["cls"] = reclassify(s, lat, p)
    d = day.isoformat()
    np.savez_compressed(store.local("state/latest.npz"), day=d, **{k: v for k, v in s.items() if k in FIELDS})
    np.savez_compressed(store.local("state/%s_cls.npz" % d), cls=s["cls"], hn24_cm=s["hn24_cm"].astype(np.float16))
    summ = summary(s, lat, meta, day, p["fresh_cm"])
    summ["assimilated"] = True
    write_js("state/%s" % d, "SNOW_STATE", summ)
    write_js("state/latest", "SNOW_STATE", summ)
    img, bounds = class_png(s["cls"], meta, cfg_lattice())
    img.save(store.local("state/%s_cls.png" % d), "PNG", optimize=True)
    img.save(store.local("state/latest_cls.png"), "PNG", optimize=True)
    if upload:
        imm, nc = "public, max-age=31536000, immutable", "no-cache"
        for rel, cache in (("state/latest.npz", "private, max-age=0"), ("state/%s_cls.npz" % d, imm), ("state/%s.json" % d, imm),
                           ("state/%s.js" % d, imm), ("state/%s_cls.png" % d, imm), ("state/latest.json", nc), ("state/latest.js", nc),
                           ("state/latest_cls.png", nc)):
            store.put(rel, cache, log)
    log("state: outputs rewritten after assimilation for %s" % d)
    return summ


def run(day, log=print, upload=True, force=False, fresh=False):
    """step one day from the saved state; fresh=True starts from SNODAS alone, as if the model began on `day`"""
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
    prev_path = None if fresh else store.fetch("state/latest.npz", log)
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
    summ = summary(s, lat, meta, day, p["fresh_cm"])
    summ["prev_day"] = prev_day
    if f.get("tfield"):
        summ["tfield"] = f["tfield"]                    # the station field's daily check (leave-one-out MAE, lapses, inversions)
    d = day.isoformat()
    write_js("state/%s" % d, "SNOW_STATE", summ)
    write_js("state/latest", "SNOW_STATE", summ)
    img, bounds = class_png(s["cls"], meta, cfg_lattice())
    img.save(store.local("state/%s_cls.png" % d), "PNG", optimize=True)
    img.save(store.local("state/latest_cls.png"), "PNG", optimize=True)
    # the day's PNG is cached as immutable; the version keeps a re-run day (run_range) from showing the old picture
    clsmeta = {"date": d, "bounds": bounds, "palette": PALETTE, "classes": CLASSES, "file": "state/%s_cls.png?v=%d" % (d, int(time.time()))}
    write_js("state/%s_cls" % d, "SNOW_CLS", clsmeta)
    write_js("state/latest_cls", "SNOW_CLS", dict(clsmeta, file="state/latest_cls.png"))
    update_index(d)
    if upload:
        imm, nc = "public, max-age=31536000, immutable", "no-cache"
        for rel, cache in (("state/latest.npz", "private, max-age=0"), ("state/%s_cls.npz" % d, imm),
                           ("state/%s.json" % d, imm), ("state/%s.js" % d, imm), ("state/%s_cls.png" % d, imm), ("state/%s_cls.js" % d, imm),
                           ("state/%s_cls.json" % d, imm), ("state/latest.json", nc), ("state/latest.js", nc), ("state/latest_cls.png", nc),
                           ("state/latest_cls.js", nc), ("state/latest_cls.json", nc), ("state/index.json", nc), ("state/index.js", nc)):
            store.put(rel, cache, log)
    ok = s["cls"] != 255
    dist = {CLASSES[i]: round(float((s["cls"][ok] == i).mean()), 3) for i in range(len(CLASSES))}
    log("state %s: prev %s, %s, %.0f s" % (day, prev_day, ", ".join("%s %.0f%%" % (k, v * 100) for k, v in dist.items() if v >= 0.005), time.time() - t0))
    return summ


def run_range(start, end, log=print, upload=True):
    """re-run start..end in order from a fresh state on `start` (after a model or archive fix); each day's outputs and
    the carried state are replaced, so the next scheduled run steps on from `end`"""
    day = start
    while day <= end:
        run(day, log, upload, force=True, fresh=day == start)
        day += dt.timedelta(days=1)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None, help="YYYY-MM-DD (default: yesterday, local)")
    ap.add_argument("--start", default=None, help="re-run from this date (fresh state) through --date")
    ap.add_argument("--resummarize", action="store_true", help="with --start: only rebuild the zone summaries from the class snapshots")
    ap.add_argument("--png", action="store_true", help="with --resummarize: also redraw the class PNGs in the current palette")
    ap.add_argument("--no-upload", action="store_true")
    ap.add_argument("--force", action="store_true", help="step even when the saved state is already at or past this date")
    a = ap.parse_args()
    d = dt.date.fromisoformat(a.date) if a.date else dt.date.today() - dt.timedelta(days=1)
    if a.start and a.resummarize:
        resummarize_range(dt.date.fromisoformat(a.start), d, upload=not a.no_upload, png=a.png)
    elif a.start:
        run_range(dt.date.fromisoformat(a.start), d, upload=not a.no_upload)
    else:
        run(d, upload=not a.no_upload, force=a.force)
