"""Web export: everything the rivers dashboard draws, as one document.

Purely additive. Nothing here changes a number the report prints; it
serialises the same fitted objects the report and figures already use, plus
the daily series the browser needs to draw its own charts (hydrograph
envelope, snowpack traces, the analog fan, the season-end track).

Written as ``web.json`` and as ``web.js`` (``window.RIVER_DATA = {...}``).
The .js form exists because the public R2 bucket sends no CORS header, so a
static page on another hostname can only read it through a <script> tag.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from .config import MONTH_LABELS, MONTH_START_DOY, Config
from .core import (Analysis, af_per_basin_inch, basin_inches, date_from_doy,
                   doy_of_wy, equivalent_date, wy_bounds)
from .stats import envelope, trend

FIGURES = [
    ("01_forecast_summary.png", "Headline forecast: this year against the record, and every remaining-volume estimate"),
    ("02_hindcast_verification.png", "Hindcast verification: does the forecast actually work?"),
    ("03_snowpack_regression.png", "Snowpack to seasonal volume"),
    ("04_analog_forecast.png", "Analog ensemble"),
    ("05_kayaker_outlook.png", "Kayaker outlook: flow bands and season end"),
    ("06_snowpack_state.png", "Snowpack state and trends"),
    ("07_flow_regime.png", "Long-term flow regime"),
    ("08_water_temperature.png", "Water temperature and salmonid thermal stress"),
    ("09_data_inventory.png", "Data inventory and hydrologic context"),
    ("10_season_end_validation.png", "Predicted against actual end of the boating season"),
]


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _f(x, nd: int | None = None):
    """Finite float or None. NaN never reaches the page."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v):
        return None
    return round(v, nd) if nd is not None else v


def _i(x):
    v = _f(x)
    return None if v is None else int(round(v))


def _d(ts) -> str | None:
    if ts is None or (isinstance(ts, float) and not math.isfinite(ts)):
        return None
    try:
        ts = pd.Timestamp(ts)
    except (TypeError, ValueError):
        return None
    if pd.isna(ts):
        return None
    return ts.strftime("%Y-%m-%d")


def _doy_date(doy, wy: int) -> str | None:
    return _d(date_from_doy(doy, wy)) if _f(doy) is not None else None


def _lst(arr, nd: int | None = None) -> list:
    return [_f(v, nd) for v in np.asarray(arr, dtype=float)]


def _rows(df: pd.DataFrame, nd: int = 3) -> list[dict]:
    out = []
    for r in df.to_dict("records"):
        row = {}
        for k, v in r.items():
            if isinstance(v, (bool, np.bool_)):
                row[k] = bool(v)
            elif isinstance(v, (int, np.integer)):
                row[k] = int(v)
            elif isinstance(v, (float, np.floating)):
                row[k] = _f(v, nd)
            elif isinstance(v, pd.Timestamp):
                row[k] = _d(v)
            else:
                row[k] = v
        out.append(row)
    return out


def _station_doy_matrix(ana: Analysis, sid: int, col: str = "swe_in",
                        complete_only: bool = True) -> pd.DataFrame:
    df = ana.raw.snotel.get(sid)
    if df is None or col not in df.columns:
        return pd.DataFrame(index=range(1, 366))
    return ana.daily_matrix(df[col], complete_only=complete_only)


# --------------------------------------------------------------------------
# sections
# --------------------------------------------------------------------------
def _meta(cfg: Config, ana: Analysis, fc) -> dict:
    comp = ana.complete
    used = {}
    for st in ana.stations:
        used[st.site_id] = sum(1 for r in ana.records
                               if r.stations.get(st.site_id) and r.stations[st.site_id].usable)
    edges = [None if not math.isfinite(e) else e for e in cfg.flow_bin_edges]
    return {
        "generated": pd.Timestamp.now().isoformat(timespec="seconds"),
        "fetched_at": ana.raw.fetched_at.isoformat(timespec="seconds"),
        "reference_date": _d(ana.ref_date),
        "last_flow_date": _d(ana.raw.last_flow_date),
        "is_hindcast": bool(ana.is_hindcast),
        "water_year": int(ana.current_wy),
        "site": {"usgs": cfg.usgs_site, "name": cfg.usgs_site_name,
                 "drainage_mi2": cfg.drainage_mi2,
                 "af_per_basin_inch": _f(af_per_basin_inch(cfg.drainage_mi2), 0)},
        "record": {"start_wy": cfg.start_wy, "complete_years": len(comp),
                   "n_days_q": int(ana.q.notna().sum()),
                   "n_missing_days": int(ana.n_missing_days),
                   "first_wy": int(min(r.wy for r in ana.records)) if ana.records else None},
        "volume_window": ana.window_label,
        "snow_index": fc.index.chosen_label if fc is not None else cfg.snow_index,
        "snow_index_key": cfg.snow_index,
        "prediction_interval": cfg.prediction_interval,
        "runnable_cfs": cfg.runnable_cfs,
        "season_thresholds": [float(t) for t in cfg.season_thresholds],
        "sustained_below_days": cfg.sustained_below_days,
        "salmon_thresh_c": cfg.salmon_thresh_c,
        "season_issue": f"{pd.Timestamp(2001, cfg.season_issue_month, cfg.season_issue_day):%b %d}",
        "flow_bins": {"edges": edges, "labels": list(cfg.flow_bin_labels),
                      "desc": list(cfg.flow_bin_desc)},
        "stations": [{"id": st.site_id, "name": st.name, "elev_ft": st.elev_ft,
                      "in_basin": bool(st.in_basin), "note": st.note,
                      "years_used": used.get(st.site_id, 0), "years_total": len(ana.records)}
                     for st in ana.stations],
        "temp_station_ids": list(cfg.temp_station_ids),
        "month_ticks": [{"doy": d, "label": l} for d, l in zip(MONTH_START_DOY, MONTH_LABELS)],
    }


def _current(cfg: Config, ana: Analysis) -> dict | None:
    cur = ana.current
    if cur is None:
        return None
    df = ana.frame()
    comp = df[df.complete]
    idx = cfg.snow_index
    snow_now = float(df.loc[cur.wy, idx]) if cur.wy in df.index else np.nan
    rank = (int((comp[idx] < snow_now).sum()) + 1) if np.isfinite(snow_now) else None

    q = ana.q.dropna()
    last_q = q.iloc[-1] if len(q) else np.nan
    last_q_date = q.index[-1] if len(q) else None
    ws, we = wy_bounds(cur.wy)
    q_wy = ana.q.loc[ws:ana.ref_date].dropna()

    # today's flow against the record on this calendar date
    mat = ana.daily_matrix(ana.q)
    ref_doy = int(round(ana.ref_doy))
    today_hist = mat.loc[ref_doy].dropna().to_numpy() if ref_doy in mat.index else np.array([])
    q_now = cur.q_mean_at_ref_cfs
    pct_rank = (float((today_hist < q_now).mean() * 100)
                if today_hist.size and np.isfinite(q_now) else np.nan)

    snapshot = []
    for st in ana.stations:
        sy = cur.stations.get(st.site_id)
        if sy is None:
            continue
        pk, now = sy.peak_swe_in, sy.swe_at_ref_in
        pct = (now / pk * 100) if (np.isfinite(pk) and pk > 0 and np.isfinite(now)) else np.nan
        status = ("no data" if not np.isfinite(now) else "melted out" if now < 0.5 else "active")
        snapshot.append({"id": st.site_id, "name": st.name, "elev_ft": st.elev_ft,
                         "in_basin": bool(st.in_basin), "usable": bool(sy.usable),
                         "peak_swe_in": _f(pk, 1), "peak_date": _d(sy.peak_date),
                         "now_in": _f(now, 1), "pct_of_peak": _f(pct, 0), "status": status,
                         "apr1_swe_in": _f(sy.apr1_swe_in, 1),
                         "precip_to_apr1_in": _f(sy.precip_to_apr1_in, 1)})

    edges = np.asarray(cfg.flow_bin_edges, float)
    band = int(np.searchsorted(edges, q_now, side="right") - 1) if np.isfinite(q_now) else None
    band = max(0, min(band, len(cfg.flow_bin_labels) - 1)) if band is not None else None

    return {
        "wy": int(cur.wy),
        "complete": bool(cur.complete),
        "n_days_q": int(cur.n_days_q),
        "flow_now_cfs": _f(q_now, 0),
        "flow_now_note": "7-day geometric mean ending on the reference date",
        "flow_band": band,
        "flow_pct_rank_today": _f(pct_rank, 0),
        "flow_median_today_cfs": _f(np.median(today_hist), 0) if today_hist.size else None,
        "flow_hist_n_today": int(today_hist.size),
        "last_daily_cfs": _f(last_q, 0),
        "last_daily_date": _d(last_q_date),
        "snow_index_in": _f(snow_now, 1),
        "snow_index_median_in": _f(comp[idx].median(), 1) if len(comp) else None,
        "snow_index_rank_lowest": rank,
        "snow_index_pct_of_median": _f(snow_now / comp[idx].median() * 100, 0) if len(comp) and np.isfinite(snow_now) else None,
        "snow_frac_remaining": _f(cur.swe_frac_at_ref, 3),
        "swe_now_in": _f(cur.swe_at_ref_in, 1),
        "composite_peak_date": _d(cur.composite_peak_date),
        "volume_to_date_kaf": _f(cur.v_to_ref_af / 1000, 0),
        "volume_to_date_in": _f(basin_inches(cur.v_to_ref_af, cfg.drainage_mi2), 1),
        "oct_mar_kaf": _f(cur.v_oct_mar_af / 1000, 0),
        "oct_mar_median_kaf": _f(comp["v_oct_mar_kaf"].median(), 0) if len(comp) else None,
        "peak_q_cfs": _f(cur.peak_q_cfs, 0),
        "peak_q_date": _d(cur.peak_q_date),
        "last_runnable_date": _d(cur.last_runnable_date),
        "sustained_below_date": _d(cur.sustained_below_date),
        "stations": snapshot,
        "n_stations_used": int(cur.n_stations_used),
        "days_in_bin_wy": [int(v) for v in cur.days_in_bin] if cur.days_in_bin is not None else None,
        "wy_days_observed": int(len(q_wy)),
    }


def _hydrograph(cfg: Config, ana: Analysis, fc) -> dict:
    mat = ana.daily_matrix(ana.q)
    env, counts = envelope(mat.to_numpy(), (0.1, 0.25, 0.5, 0.75, 0.9), min_count=20)
    doy = [int(v) for v in mat.index]
    cur = ana.current
    current = None
    if cur is not None:
        ws, _ = wy_bounds(cur.wy)
        q_cur = ana.q.loc[ws:ana.ref_date].dropna()
        current = {"doy": [int(round(v)) for v in doy_of_wy(q_cur.index, cur.wy)],
                   "cfs": _lst(q_cur.to_numpy(), 0),
                   "dates": [_d(t) for t in q_cur.index]}
    analog = None
    if fc is not None and fc.analogs is not None:
        a = fc.analogs
        analog = {"doy": [int(v) for v in a.q_median.index],
                  "median": _lst(a.q_median.to_numpy(), 0),
                  "lo": _lst(a.q_lo.to_numpy(), 0), "hi": _lst(a.q_hi.to_numpy(), 0),
                  "traces": {int(an.wy): {"doy": [int(v) for v in an.trace.index],
                                          "cfs": _lst(an.trace.to_numpy(), 0)}
                             for an in a.analogs}}
    # every year's daily flow, for the "compare with" picker
    full = ana.daily_matrix(ana.q, complete_only=False)
    years = {int(wy): [_i(v) for v in full[wy].to_numpy()] for wy in full.columns}
    return {
        "doy": doy,
        "envelope": {f"p{int(q * 100)}": _lst(env[q], 0) for q in env},
        "envelope_n": [int(c) for c in counts],
        "current": current,
        "analog": analog,
        "years": years,
        "thresholds": [cfg.runnable_cfs, 3000, 5000],
    }


def _snowpack(cfg: Config, ana: Analysis, melt) -> dict:
    cur = ana.current
    stations = {}
    for st in ana.stations:
        m = _station_doy_matrix(ana, st.site_id)
        env, counts = envelope(m.to_numpy(), (0.1, 0.5, 0.9), min_count=10)
        item = {"name": st.name, "elev_ft": st.elev_ft, "in_basin": bool(st.in_basin),
                "median": _lst(env[0.5], 1), "p10": _lst(env[0.1], 1), "p90": _lst(env[0.9], 1)}
        if cur is not None:
            df = ana.raw.snotel.get(st.site_id)
            if df is not None and "swe_in" in df.columns:
                ws, _ = wy_bounds(cur.wy)
                s = df.loc[ws:ana.ref_date, "swe_in"].dropna()
                item["current"] = {"doy": [int(round(v)) for v in doy_of_wy(s.index, cur.wy)],
                                   "swe_in": _lst(s.to_numpy(), 1)}
        stations[st.site_id] = item

    composite = None
    if melt is not None and melt.depletion is not None and not melt.depletion.empty:
        dep = melt.depletion
        comp_cols = [r.wy for r in ana.complete if r.wy in dep.columns]
        env, counts = envelope(dep[comp_cols].to_numpy(), (0.1, 0.5, 0.9), min_count=10)
        composite = {"doy": [int(v) for v in dep.index],
                     "median": _lst(env[0.5], 1), "p10": _lst(env[0.1], 1), "p90": _lst(env[0.9], 1),
                     "current": (_lst(dep[cur.wy].to_numpy(), 1)
                                 if cur is not None and cur.wy in dep.columns else None),
                     "years": {int(wy): _lst(dep[wy].to_numpy(), 1) for wy in dep.columns},
                     "melt_out": {k: _f(v, 2) for k, v in (melt.melt_out_estimate or {}).items()}}
    return {"stations": stations, "composite": composite,
            "note": "basin-mean SWE is the plain mean of the usable stations on each day"}


def _fit_dict(fit) -> dict | None:
    if fit is None:
        return None
    return {"n": int(fit.n), "r2": _f(fit.r2, 3), "adj_r2": _f(fit.adj_r2, 3),
            "loocv_r2": _f(fit.loocv_r2, 3), "rmse": _f(fit.rmse, 1), "mae": _f(fit.mae, 1),
            "slope": _f(fit.slope, 4), "intercept": _f(fit.intercept, 4),
            "p_value": _f(fit.p_value), "log_x": bool(fit.log_x), "log_y": bool(fit.log_y),
            "x_min": _f(np.exp(fit.x_min) if fit.log_x else fit.x_min, 3),
            "x_max": _f(np.exp(fit.x_max) if fit.log_x else fit.x_max, 3),
            "duan": _f(fit.duan, 4)}


def _pred_dict(p, scale: float = 1.0, nd: int = 1) -> dict | None:
    if p is None:
        return None
    return {"value": _f(p.value * scale, nd), "lo": _f(p.lo * scale, nd), "hi": _f(p.hi * scale, nd),
            "level": p.level, "leverage": _f(p.leverage, 3),
            "extrapolated": bool(p.extrapolated), "high_leverage": bool(p.high_leverage)}


def _forecast(cfg: Config, ana: Analysis, fc, bt, lead) -> dict | None:
    if fc is None:
        return None
    df = ana.frame()
    comp = df[df.complete]
    sep30 = pd.Timestamp(ana.current_wy, 9, 30)
    out: dict = {
        "question": f"volume passing the gauge from {ana.ref_date:%b %d} through Sep 30",
        "days_remaining": max(0, (sep30 - ana.ref_date).days),
        "headline": {"method": fc.primary_name, "basis": fc.primary_basis,
                     "remaining_kaf": _f(fc.primary_af / 1000, 0),
                     "lo_kaf": _f(fc.primary_lo_af / 1000, 0), "hi_kaf": _f(fc.primary_hi_af / 1000, 0),
                     "remaining_in": _f(basin_inches(fc.primary_af, cfg.drainage_mi2), 2),
                     "interval": cfg.prediction_interval},
        "estimates": [{"method": e["method"], "kaf": _f(e["af"] / 1000, 0),
                       "lo_kaf": _f(e["lo"] / 1000, 0), "hi_kaf": _f(e["hi"] / 1000, 0),
                       "basin_in": _f(basin_inches(e["af"], cfg.drainage_mi2), 2),
                       "skill": _f(e.get("skill"), 2), "note": e.get("note", ""),
                       "primary": e["method"].startswith(fc.primary_name.split(" (")[0])}
                      for e in fc.estimates()],
        "warning": fc.consistency_warning or None,
        "observed_to_date_kaf": _f(fc.v_observed_to_date_af / 1000, 0),
    }
    if fc.balance is not None:
        b = fc.balance
        out["balance"] = {"hist_min_kaf": _f(b.historical_min_af / 1000, 0),
                          "hist_median_kaf": _f(b.historical_median_af / 1000, 0),
                          "hist_max_kaf": _f(b.historical_max_af / 1000, 0),
                          "swe_remaining_in": _f(b.swe_remaining_in, 1),
                          "verdicts": {k: b.verdict(k) for k in b.forecasts}}
    if fc.seasonal is not None:
        s = fc.seasonal
        fit = s.fit
        lx, ly = fit.line(60)
        out["seasonal"] = {
            "fit": _fit_dict(fit),
            "exponent": _f(fit.slope, 3),
            "prediction_total": _pred_dict(s.prediction, 1 / 1000, 0),
            "intercept_kaf": _f(s.intercept_af / 1000, 0), "intercept_in": _f(s.intercept_basin_in, 1),
            "influential_wys": [int(s.years[i]) for i in fit.influential] if len(s.years) else [],
            "points": [{"wy": int(w), "x": _f(x, 2), "kaf": _f(y, 0)}
                       for w, x, y in zip(comp["wy"], comp[cfg.snow_index], comp["v_seasonal_kaf"])
                       if np.isfinite(x) and np.isfinite(y)],
            "line": [[_f(x, 2), _f(y / 1000, 1)] for x, y in zip(lx, ly)],
            "x_now": _f(df.loc[ana.current_wy, cfg.snow_index], 2) if ana.current_wy in df.index else None,
            "extras": {"snow_only": _f(getattr(s.fit_swe_only_multi, "loocv_r2", np.nan), 3),
                       "snow_precip": _f(getattr(s.fit_with_precip, "loocv_r2", np.nan), 3),
                       "snow_antecedent": _f(getattr(s.fit_with_antecedent, "loocv_r2", np.nan), 3)},
        }
    if fc.recession is not None:
        r = fc.recession
        lx, ly = r.fit.line(60)
        out["recession"] = {
            "fit": _fit_dict(r.fit), "q_now_cfs": _f(r.q_now_cfs, 0),
            "days_remaining": int(r.days_remaining),
            "prediction": _pred_dict(r.prediction, 1 / 1000, 0),
            "points": [{"wy": int(rr.wy), "q": _f(rr.q_at_ref_cfs, 0), "kaf": _f(rr.v_after_ref_kaf, 1)}
                       for rr in comp.itertuples()
                       if np.isfinite(rr.q_at_ref_cfs) and np.isfinite(rr.v_after_ref_kaf)],
            "line": [[_f(x, 1), _f(y / 1000, 2)] for x, y in zip(lx, ly)],
        }
    if fc.snowfrac is not None:
        sf = fc.snowfrac
        out["snowfrac"] = {"b": _f(sf.b, 3), "n": int(sf.n), "r2": _f(sf.r2, 3), "rmse": _f(sf.rmse, 3),
                           "swe_frac_now": _f(sf.swe_frac_now, 3), "vol_frac_pred": _f(sf.vol_frac_pred, 3),
                           "kaf": _f(sf.volume_af / 1000, 0), "lo_kaf": _f(sf.lo_af / 1000, 0),
                           "hi_kaf": _f(sf.hi_af / 1000, 0), "degenerate": bool(sf.degenerate), "note": sf.note}
    if fc.analogs is not None:
        a = fc.analogs
        out["analogs"] = {
            "n": len(a.analogs), "n_candidates": int(a.n_candidates), "note": a.biased_note,
            "volume_median_kaf": _f(a.volume_median_af / 1000, 0),
            "volume_lo_kaf": _f(a.volume_lo_af / 1000, 0), "volume_hi_kaf": _f(a.volume_hi_af / 1000, 0),
            "q_now_cfs": _f(a.q_now_cfs, 0),
            "years": [{"wy": int(an.wy), "snow_index": _f(an.swe_index, 1), "q_at_ref": _f(an.q_at_ref, 0),
                       "scale": _f(an.scale, 2), "clipped": bool(an.scale_clipped),
                       "distance": _f(an.distance, 2), "kaf": _f(an.volume_af / 1000, 0),
                       "last_runnable_doy": _f(an.last_runnable_doy, 0),
                       "last_runnable_date": _doy_date(an.last_runnable_doy, ana.current_wy),
                       "sustained_below_doy": _f(an.sustained_below_doy, 0),
                       "sustained_below_date": _doy_date(an.sustained_below_doy, ana.current_wy)}
                      for an in a.analogs],
        }
    if fc.index is not None:
        out["index_candidates"] = _rows(fc.index.table(), 3)
    if bt is not None:
        out["hindcast_at_issue"] = {"issue": bt.label, "scores": _rows(bt.scores(), 3),
                                    "years": _rows(bt.frame(), 1)}
    if lead is not None and not lead.empty:
        out["lead_curve"] = _rows(lead, 3)
    return out


def _season(cfg: Config, ana: Analysis, fc, season, season_skill, season_current) -> dict | None:
    from . import season_end as SE
    wy = ana.current_wy
    ends = SE.all_season_ends(ana)
    mismatch = sorted(
        [{"wy": int(w), "recession_end": _d(se.recession_end), "last_any": _d(se.last_any),
          "days": int(se.rain_bump_days)} for w, se in ends.items() if se.rain_bump_days > 0],
        key=lambda r: -r["days"])
    # What a boater needs to expect at this threshold: years the river never
    # reached it in the May-Sep season at all, years it never dropped below
    # it before Sep 30, and how many days a year it spends at or above it.
    thr = cfg.runnable_cfs
    by_year = []
    for rec in ana.records:
        ws, we = wy_bounds(rec.wy)
        q_wy = ana.q.loc[ws:we].dropna()
        season_q = q_wy.loc[pd.Timestamp(rec.wy, 5, 1):we]
        se = ends.get(rec.wy)
        above = q_wy[q_wy >= thr]
        by_year.append({
            "wy": int(rec.wy), "complete": bool(rec.complete),
            "days_above": int((q_wy >= thr).sum()),
            "days_above_season": int((season_q >= thr).sum()),
            "first_above": _d(above.index.min()) if len(above) else None,
            "last_above": _d(above.index.max()) if len(above) else None,
            "peak_cfs": _f(rec.peak_q_cfs, 0),
            "recession_end": _d(se.recession_end) if se else None,
            "censored": bool(se.censored) if se else False,
            "never_in_season": bool(se is not None and se.last_any is None),
            "never_at_all": bool(np.isfinite(rec.peak_q_cfs) and rec.peak_q_cfs < thr),
        })
    comp_years = [y for y in by_year if y["complete"]]
    out: dict = {
        "threshold_cfs": cfg.runnable_cfs,
        "sustained_days": cfg.sustained_below_days,
        "by_year": by_year,
        "never_in_season": [y["wy"] for y in comp_years if y["never_in_season"]],
        "never_at_all": [y["wy"] for y in comp_years if y["never_at_all"]],
        "censored_years": [y["wy"] for y in comp_years if y["censored"]],
        "days_above_median": _f(np.median([y["days_above"] for y in comp_years]), 0) if comp_years else None,
        "days_above_season_median": _f(np.median([y["days_above_season"] for y in comp_years]), 0) if comp_years else None,
        "n_complete": len(comp_years),
        "definition": (f"the last day of the summer recession at or above {cfg.runnable_cfs:,.0f} cfs, "
                       f"i.e. the last day above the threshold before the first run of "
                       f"{cfg.sustained_below_days} consecutive days below it"),
        "mismatch_years": mismatch,
        "n_years": len(ends),
    }
    sc = season_current or {}
    cur = {"wy": int(wy), "status": sc.get("status"), "method": sc.get("method"),
           "actual": _d(sc.get("actual")), "sustained_start": _d(sc.get("sustained_start")),
           "last_any": _d(sc.get("last_any")), "rain_bump_days": sc.get("rain_bump_days"),
           "predicted": _d(sc.get("predicted")), "predicted_lo": _d(sc.get("predicted_lo")),
           "predicted_hi": _d(sc.get("predicted_hi")),
           "error_days": sc.get("error_days"), "snow_index": _f(sc.get("snow_index"), 1),
           "flow_at_issue": _f(sc.get("flow_at_issue"), 0),
           "issue": out.get("issue")}
    out["current"] = cur
    if season is not None:
        best = season.best_method()
        out["issue"] = season.label
        cur["issue"] = season.label
        out["best_method"] = best
        out["scores"] = _rows(season.scores(), 3)
        out["n_censored"] = int(season.n_censored)
        out["n_already_over"] = int(season.n_already_over)
        out["n_scored"] = len(season.usable())
        tbl = season.table(best).sort_values("wy")
        rows = []
        for r in tbl.itertuples():
            rows.append({"wy": int(r.wy), "snow_index_in": _f(r.snow_index_in, 1),
                         "swe_remaining_in": _f(r.swe_remaining_in, 1),
                         "flow_at_issue_cfs": _f(r.flow_at_issue_cfs, 0),
                         "predicted_doy": _f(r.predicted_doy, 1), "actual_doy": _f(r.actual_doy, 0),
                         "predicted": _doy_date(r.predicted_doy, int(r.wy)),
                         "actual": _doy_date(r.actual_doy, int(r.wy)),
                         "lo": _doy_date(r.lo_doy, int(r.wy)), "hi": _doy_date(r.hi_doy, int(r.wy)),
                         "lo_doy": _f(r.lo_doy, 1), "hi_doy": _f(r.hi_doy, 1),
                         "error_days": _f(r.error_days, 1),
                         "censored": bool(r.censored), "already_over": bool(r.already_over)})
        out["years"] = rows
        # Trend in the actual season-end day (Theil-Sen, Mann-Kendall, the
        # same test the record page uses), uncensored complete years only.
        good = [(r["wy"], r["actual_doy"]) for r in rows
                if r["actual_doy"] is not None and not r["censored"] and r["wy"] != wy]
        if len(good) >= 10:
            t = trend(np.array([g[0] for g in good], float), np.array([g[1] for g in good], float),
                      f"Actual last day above {cfg.runnable_cfs:,.0f} cfs", "days")
            out["actual_trend"] = {"slope": _f(t.slope, 4), "intercept": _f(t.intercept, 4),
                                   "lo": _f(t.lo, 4), "hi": _f(t.hi, 4), "p_value": _f(t.p_value, 4),
                                   "n": int(t.n), "significant": bool(t.significant),
                                   "describe": t.describe(),
                                   "x0": good[0][0], "x1": good[-1][0]}
        fits = {}
        for k, f in (season.fits or {}).items():
            fits[k] = _fit_dict(f)
        out["fits"] = fits
    if season_skill is not None and not season_skill.empty:
        out["skill_by_issue"] = _rows(season_skill, 3)

    # analog outlook (empirical, from the analog years' actual dates)
    if fc is not None and fc.analogs is not None:
        a = fc.analogs
        edges = np.asarray(cfg.flow_bin_edges, float)
        rows = [np.histogram(an.trace.to_numpy(), bins=edges)[0] for an in a.analogs]
        med = np.median(np.array(rows), axis=0) if rows else np.zeros(len(cfg.flow_bin_labels))
        q_last = a.season_end_quantiles("last_runnable_doy")
        q_sus = a.season_end_quantiles("sustained_below_doy")

        def qd(q):
            if q is None:
                return None
            return {k: {"doy": _f(q[k], 0), "date": _doy_date(q[k], wy)}
                    for k in ("min", "p10", "median", "p90", "max")} | {"n": q["n"]}
        crossings = []
        for level in (5000, 3000, 2000, 1000, 500):
            if np.isfinite(a.q_now_cfs) and a.q_now_cfs < level:
                crossings.append({"cfs": level, "status": "already below"})
                continue
            c = a.threshold_crossing(level)
            if c is None:
                crossings.append({"cfs": level, "status": "not before Sep 30"})
            else:
                crossings.append({"cfs": level, "status": "forecast", "doy": _f(c[0], 0),
                                  "date": _doy_date(c[0], wy), "agree": int(c[1]), "of": len(a.analogs)})
        out["analog_outlook"] = {
            "from": _d(ana.ref_date), "n": len(a.analogs),
            "band_days_median": [_f(v, 0) for v in med],
            "band_days_by_year": {int(an.wy): [int(v) for v in r] for an, r in zip(a.analogs, rows)},
            "last_runnable": qd(q_last), "sustained_below": qd(q_sus),
            "crossings": crossings,
        }
    return out


def _track(ana: Analysis, tr) -> dict | None:
    if tr is None:
        return None
    wy = ana.current_wy
    dates = [f"{m:02d}-{d:02d}" for m, d in tr.issue_dates]
    years = {}
    for w, y in tr.years.items():
        years[int(w)] = {"pred": _lst(y["pred"], 1), "lo": _lst(y["lo"], 1), "hi": _lst(y["hi"], 1),
                         "actual_doy": _f(tr.actual_doy.get(w), 0),
                         "actual": _doy_date(tr.actual_doy.get(w), int(w)),
                         "censored": bool(tr.censored.get(w, False))}
    detail = {int(w): {m: {"pred": _lst(t["pred"], 1), "lo": _lst(t["lo"], 1), "hi": _lst(t["hi"], 1)}
                       for m, t in dd.items()} for w, dd in tr.detail.items()}
    # summary for the current year: first and last call, how far it moved
    summary = None
    cur = years.get(int(wy))
    if cur is not None:
        vals = [(i, v) for i, v in enumerate(cur["pred"]) if v is not None]
        if vals:
            i0, v0 = vals[0]
            i1, v1 = vals[-1]
            summary = {"first_issue": dates[i0], "first_call": _doy_date(v0, wy),
                       "last_issue": dates[i1], "last_call": _doy_date(v1, wy),
                       "range_days": _f(max(v for _, v in vals) - min(v for _, v in vals), 0),
                       "n_issues": len(vals)}
    return {"issue_dates": dates, "best_method": tr.best_method, "years": years,
            "detail": detail, "summary": summary, "threshold_cfs": tr.threshold,
            "note": ("each point is the forecast re-issued on that date, fitted on the other "
                     "years only and using only data available on that date")}


def _thermal(cfg: Config, ana: Analysis, th) -> dict | None:
    if th is None:
        return {"available": False}
    cur = ana.current
    daily = None
    if cur is not None:
        d = th.daily.loc[pd.Timestamp(cur.wy, 6, 1):min(pd.Timestamp(cur.wy, 9, 30), ana.ref_date)]
        d = d.dropna(how="all", subset=["t_mean", "t_max", "dadmax7"])
        if len(d):
            daily = {"dates": [_d(t) for t in d.index], "t_mean": _lst(d["t_mean"], 1),
                     "t_max": _lst(d["t_max"], 1), "dadmax7": _lst(d["dadmax7"], 1),
                     "q_cfs": _lst(d["q_cfs"], 0)}
    return {
        "available": True, "have_daily_max": bool(th.have_daily_max), "note": th.note,
        "threshold_c": th.threshold_c, "n_complete": int(th.n_complete), "usable": bool(th.usable),
        "years": [{"wy": int(y.wy), "coverage": _f(y.coverage, 2), "n_days": int(y.n_days_observed),
                   "days_over_mean": int(y.days_over_mean), "days_over_7dadmax": int(y.days_over_7dadmax),
                   "frac_over_7dadmax": _f(y.frac_over_7dadmax, 3),
                   "summer_max_c": _f(y.summer_max_c, 1), "summer_mean_c": _f(y.summer_mean_c, 1),
                   "first_exceedance": _doy_date(y.first_exceedance_doy, int(y.wy))} for y in th.years],
        "by_flow_bin": _rows(th.by_flow_bin, 1),
        "fits": {"air_flow_skill": _f(getattr(th.air_water_fit, "loocv_r2", np.nan), 3),
                 "plus_snow_skill": _f(getattr(th.swe_marginal, "loocv_r2", np.nan), 3)},
        "current_daily": daily,
    }


def _record(cfg: Config, ana: Analysis) -> dict:
    df = ana.frame()
    comp = df[df.complete]
    rows = []
    for rec in ana.records:
        bins = rec.days_in_bin
        edges = list(cfg.flow_bin_edges)

        def days_above(thr):
            if bins is None:
                return None
            return int(sum(int(b) for e, b in zip(edges[:-1], bins) if e >= thr))
        r = df.loc[rec.wy]
        rows.append({
            "wy": int(rec.wy), "complete": bool(rec.complete), "n_days_q": int(rec.n_days_q),
            "n_stations": int(rec.n_stations_used),
            "peak_swe_in": _f(r["peak_swe_in"], 1), "peak_swe_pct": _f(r["peak_swe_pct"], 1),
            "apr1_swe_in": _f(r["apr1_swe_in"], 1), "precip_in": _f(r["precip_in"], 1),
            "peak_swe_date": _d(rec.composite_peak_date),
            "v_total_kaf": _f(r["v_total_kaf"], 0), "v_seasonal_kaf": _f(r["v_seasonal_kaf"], 0),
            "v_apr_sep_kaf": _f(r["v_apr_sep_kaf"], 0), "v_oct_mar_kaf": _f(r["v_oct_mar_kaf"], 0),
            "peak_q_cfs": _f(rec.peak_q_cfs, 0), "peak_q_date": _d(rec.peak_q_date),
            "centroid_doy": _f(rec.centroid_doy, 1), "centroid_date": _doy_date(rec.centroid_doy, rec.wy),
            "last_runnable_date": _d(rec.last_runnable_date),
            "sustained_below_date": _d(rec.sustained_below_date),
            "days_above_1k": days_above(1000), "days_above_3k": days_above(3000), "days_above_5k": days_above(5000),
            "swe_stations": {int(sid): _f(sy.peak_swe_in if sy.usable else np.nan, 1) for sid, sy in rec.stations.items()},
        })

    # the same ten trends the report prints
    series = [
        ("Peak snowpack index", comp[cfg.snow_index], "in"),
        ("Peak snowpack timing", comp["peak_swe_doy"], "days"),
        ("Total annual runoff", comp["v_total_kaf"], "kaf"),
        (f"Seasonal runoff ({ana.window_label})", comp["v_seasonal_kaf"], "kaf"),
        ("Oct-Mar runoff", comp["v_oct_mar_kaf"], "kaf"),
        ("Flow centroid", comp["centroid_doy"], "days"),
        (f"Last day above {cfg.runnable_cfs:,.0f} cfs", comp["last_runnable_doy"], "days"),
    ]
    for thr in (1000, 3000, 5000):
        days = []
        for rec in ana.records:
            if not rec.complete:
                continue
            ws, we = wy_bounds(rec.wy)
            q = ana.q.loc[ws:we].dropna()
            days.append(float((q >= thr).sum() / len(q) * 365) if len(q) else np.nan)
        series.append((f"Days above {thr:,} cfs", pd.Series(days, index=comp.index), "days"))
    trends = []
    for name, vals, units in series:
        t = trend(comp["wy"], vals, name, units)
        trends.append({"name": name, "units": units, "slope": _f(t.slope, 4), "intercept": _f(t.intercept, 4), "lo": _f(t.lo, 4),
                       "hi": _f(t.hi, 4), "p_value": _f(t.p_value, 4), "n": int(t.n),
                       "n_effective": _f(t.n_effective, 1), "significant": bool(t.significant),
                       "verdict": t.verdict, "describe": t.describe(),
                       "series": [{"wy": int(w), "v": _f(v, 2)} for w, v in zip(comp["wy"], vals)]})

    # decade median hydrographs
    mat = ana.daily_matrix(ana.q)
    decades = {}
    for wy in mat.columns:
        decades.setdefault(f"{(int(wy) // 10) * 10}s", []).append(wy)
    decade_median = {}
    with np.errstate(all="ignore"):
        for k, cols in sorted(decades.items()):
            decade_median[k] = {"n": len(cols), "median": _lst(np.nanmedian(mat[cols].to_numpy(), axis=1), 0)}
    return {"years": rows, "trends": trends, "decade_median": decade_median,
            "doy": [int(v) for v in mat.index]}


# --------------------------------------------------------------------------
# assembly
# --------------------------------------------------------------------------
def build_web(cfg: Config, ana: Analysis, fc, th, melt, bt, lead, season,
              season_skill, season_current, track, report_text: str = "") -> dict:
    return {
        "meta": _meta(cfg, ana, fc),
        "current": _current(cfg, ana),
        "hydrograph": _hydrograph(cfg, ana, fc),
        "snowpack": _snowpack(cfg, ana, melt),
        "forecast": _forecast(cfg, ana, fc, bt, lead),
        "season": _season(cfg, ana, fc, season, season_skill, season_current),
        "track": _track(ana, track),
        "thermal": _thermal(cfg, ana, th),
        "record": _record(cfg, ana),
        "figures": [{"file": f, "title": t} for f, t in FIGURES],
        "report": report_text,
    }


def build_season_file(cfg: Config, raw, threshold: float) -> dict:
    """The season-end block recomputed at one threshold.

    A fresh Analysis at that threshold (the recession-end date per year
    depends on it), then the same validation, skill curve, current call,
    analog outlook and spring track the main run does at the default.
    """
    from dataclasses import replace
    from types import SimpleNamespace
    from . import models, season_end
    from .core import Analysis

    cfg_t = replace(cfg, runnable_cfs=float(threshold))
    ana_t = Analysis(cfg_t, raw)
    season = season_end.validate(ana_t, cfg_t.season_issue_month, cfg_t.season_issue_day)
    skill = season_end.skill_by_issue_date(ana_t)
    current = season_end.forecast_current(ana_t, season) if season is not None else {}
    track = None
    if cfg_t.make_track and season is not None:
        track = season_end.track_by_issue_date(ana_t, cfg_t.track_start, cfg_t.track_end,
                                               cfg_t.track_step_days)
    fc_t = SimpleNamespace(analogs=models.build_analogs(ana_t))
    return {
        "generated": pd.Timestamp.now().isoformat(timespec="seconds"),
        "threshold_cfs": float(threshold),
        "water_year": int(ana_t.current_wy),
        "reference_date": _d(ana_t.ref_date),
        "season": _season(cfg_t, ana_t, fc_t, season, skill, current),
        "track": _track(ana_t, track),
        "current": {"last_runnable_date": _d(ana_t.current.last_runnable_date) if ana_t.current else None,
                    "sustained_below_date": _d(ana_t.current.sustained_below_date) if ana_t.current else None},
    }


def write_season_file(out_dir: Path, doc: dict, stamp: str = "") -> tuple[Path, Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"season_{int(round(doc['threshold_cfs']))}{stamp}"
    text = json.dumps(doc, separators=(",", ":"), allow_nan=False)
    p_json = out_dir / f"{stem}.json"
    p_js = out_dir / f"{stem}.js"
    p_json.write_text(text, encoding="utf-8")
    p_js.write_text("window.RIVER_SEASON = " + text + ";\n", encoding="utf-8")
    return p_js, p_json


def write_web(out_dir: Path, data: dict, stem: str = "web") -> tuple[Path, Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, separators=(",", ":"), allow_nan=False)
    p_json = out_dir / f"{stem}.json"
    p_js = out_dir / f"{stem}.js"
    p_json.write_text(text, encoding="utf-8")
    p_js.write_text("window.RIVER_DATA = " + text + ";\n", encoding="utf-8")
    return p_js, p_json
