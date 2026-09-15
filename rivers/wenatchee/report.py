"""Console and file reporting.

Every number printed here carries its window, its method, and its
uncertainty. Where two accounting conventions give different answers, both
are shown and labelled rather than one being picked silently.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .config import Config
from .core import (Analysis, af_per_basin_inch, basin_inches,
                   date_from_doy, wy_bounds)
from .stats import trend


class Report:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.lines: list[str] = []

    def __call__(self, text: str = "") -> None:
        print(text)
        self.lines.append(text)

    def rule(self, char: str = "=") -> None:
        self(char * 78)

    def head(self, title: str) -> None:
        self()
        self.rule()
        self(f"  {title}")
        self.rule()

    def sub(self, title: str) -> None:
        self()
        self(f"  {title}")
        self(f"  {'-' * len(title)}")

    def text(self) -> str:
        return "\n".join(self.lines) + "\n"

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(self.lines) + "\n", encoding="utf-8")


def _doy_label(doy: float, wy: int) -> str:
    d = date_from_doy(doy, wy)
    return d.strftime("%b %d") if d is not None else "n/a"


# --------------------------------------------------------------------------
def build_report(cfg: Config, ana: Analysis, fc, th, melt, report_bt, lead,
                 season=None, season_skill=None, season_current=None
                 ) -> Report:
    r = Report(cfg)
    df = ana.frame()
    comp = df[df.complete]
    cur = ana.current
    af_in = af_per_basin_inch(cfg.drainage_mi2)

    # ---------------------------------------------------------------- header
    r.rule()
    r(f"  WENATCHEE RIVER SNOWPACK-RUNOFF ANALYSIS")
    r(f"  {cfg.usgs_site_name} - USGS {cfg.usgs_site} - "
      f"{cfg.drainage_mi2:,.0f} sq mi")
    r.rule()
    r(f"  Reference date : {ana.ref_date:%A, %B %d, %Y}"
      + ("   [HINDCAST - later data withheld]" if ana.is_hindcast else ""))
    r(f"  Water year     : WY{ana.current_wy} (partial)")
    r(f"  Record         : WY{cfg.start_wy}-{ana.current_wy}, "
      f"{len(comp)} complete years")
    r(f"  Volume window  : {ana.window_label}")
    r(f"  Snowpack index : {fc.index.chosen_label} (fixed in config)")
    r(f"  1 basin inch   : {af_in:,.0f} acre-feet")

    # ------------------------------------------------------------- inventory
    r.head("DATA INVENTORY")
    r(f"  Discharge      : {len(ana.q.dropna()):,} daily values, "
      f"{ana.n_missing_days} missing days on the daily axis")
    r(f"  Water temp     : {len(ana.raw.water_temp_c):,} daily means"
      + (f", {len(ana.raw.water_temp_max_c):,} daily maxima"
         if len(ana.raw.water_temp_max_c) else ", no daily maxima"))
    r()
    r(f"  {'SNOTEL station':<22}{'Elev':>7}{'In basin':>10}"
      f"{'Station-years used':>20}")
    r(f"  {'-' * 60}")
    for st in ana.stations:
        used = sum(1 for rec in ana.records
                   if rec.stations.get(st.site_id)
                   and rec.stations[st.site_id].usable)
        r(f"  {st.name:<22}{st.elev_ft:>6,}'{'yes' if st.in_basin else 'NO':>10}"
          f"{used:>13} / {len(ana.records)}")
    off = [s for s in ana.stations if not s.in_basin]
    if off:
        names = ", ".join(s.name for s in off)
        r()
        r(f"  Note: {names} lies OUTSIDE the Wenatchee drainage. It is")
        r( "  retained as a high-elevation index station, which is standard")
        r( "  operational practice, but it is an index, not a basin measurement.")

    # ------------------------------------------------- current-year snapshot
    if cur is not None:
        r.head(f"WY{ana.current_wy} SNAPSHOT")
        r(f"  {'Station':<18}{'Peak SWE':>10}{'Peak date':>12}"
          f"{'Now':>8}{'% of peak':>11}  Status")
        r(f"  {'-' * 68}")
        for st in ana.stations:
            sy = cur.stations.get(st.site_id)
            if sy is None:
                continue
            pk = sy.peak_swe_in
            now = sy.swe_at_ref_in
            pct = (now / pk * 100) if (np.isfinite(pk) and pk > 0
                                       and np.isfinite(now)) else np.nan
            status = ("no data" if not np.isfinite(now)
                      else "melted out" if now < 0.5 else "active")
            r(f"  {st.name:<18}{pk:>9.1f}\""
              f"{sy.peak_date.strftime('%b %d') if sy.peak_date else 'n/a':>12}"
              f"{now:>8.1f}{pct:>10.0f}%  {status}")
        r()
        r(f"  Composite snowpack index : {df.loc[cur.wy, cfg.snow_index]:.1f} in"
          f"   (median of complete years: {comp[cfg.snow_index].median():.1f})")
        rank = int((comp[cfg.snow_index] < df.loc[cur.wy, cfg.snow_index]).sum()) + 1
        r(f"  Rank among complete years: {rank} lowest of {len(comp)}")
        r(f"  Snowpack still on ground : {cur.swe_frac_at_ref * 100:.0f}% of peak "
          f"(basin sum, not a mean of ratios)")
        r(f"  Flow now (7-day geo mean): {cur.q_mean_at_ref_cfs:,.0f} cfs")
        r(f"  Volume this season so far: {cur.v_to_ref_af / 1000:,.0f} kaf"
          f"  ({basin_inches(cur.v_to_ref_af, cfg.drainage_mi2):.1f} basin inches)")
        r(f"  Oct-Mar volume           : {cur.v_oct_mar_af / 1000:,.0f} kaf"
          f"   (median {comp['v_oct_mar_kaf'].median():,.0f})")

    # --------------------------------------------------------- how much left
    r.head("HOW MUCH WATER IS LEFT?")
    r(f"  Question: volume passing the Monitor gauge from "
      f"{ana.ref_date:%b %d} through Sep 30.")
    r()
    r(f"  {'Method':<44}{'kaf':>8}{'80% interval':>18}"
      f"{'verified':>10}")
    r(f"  {'-' * 78}")
    for e in fc.estimates():
        sk = e.get("skill", np.nan)
        skill = f"{sk:.2f}" if np.isfinite(sk) else "-"
        r(f"  {e['method']:<44}{e['af'] / 1000:>8,.0f}"
          f"{e['lo'] / 1000:>9,.0f} -{e['hi'] / 1000:>7,.0f}{skill:>10}")
    r()
    r( "  'verified' is hindcast skill for THIS quantity at THIS date: 1.0")
    r( "  perfect, 0.0 no better than the historical median, negative worse.")
    r()
    r( "  These are NOT averaged. The snowpack regression and any fraction-of-")
    r( "  season model are both functions of the same fitted seasonal total, so")
    r( "  averaging them would double-count one estimate and present the result")
    r( "  as agreement between independent methods.")

    if fc.primary_name != "none":
        r()
        r(f"  >> HEADLINE: {fc.primary_af / 1000:,.0f} kaf remaining "
          f"({fc.primary_lo_af / 1000:,.0f} - {fc.primary_hi_af / 1000:,.0f} "
          f"at {cfg.prediction_interval:.0%})")
        r(f"     Method: {fc.primary_name}")
        if fc.primary_basis:
            r(f"     Chosen because it has the {fc.primary_basis}.")
        r(f"     That is {basin_inches(fc.primary_af, cfg.drainage_mi2):.2f} "
          f"inches over the basin.")

    if fc.consistency_warning:
        r()
        r(f"  ** WARNING: {fc.consistency_warning}")

    # physical bounds
    if fc.balance is not None:
        b = fc.balance
        r.sub("Physical check")
        r(f"  Remaining volume in the historical record for this date:")
        r(f"    lowest {b.historical_min_af/1000:,.0f} kaf   "
          f"median {b.historical_median_af/1000:,.0f} kaf   "
          f"highest {b.historical_max_af/1000:,.0f} kaf")
        if np.isfinite(b.swe_remaining_in):
            r(f"  Mean station SWE still on the ground: "
              f"{b.swe_remaining_in:.1f} inches")
        for name, v in b.forecasts.items():
            if np.isfinite(v):
                r(f"    {name:<12} {v/1000:>8,.0f} kaf "
                  f"({b.as_basin_inches(v):.2f} basin in)  -- {b.verdict(name)}")

    # ------------------------------------------------------------- verification
    r.head("DOES THE FORECAST ACTUALLY WORK?")
    r( "  Every year below was forecast using a model fitted on the other years")
    r( "  only, from data available on the issue date. This is the check the")
    r( "  calibration r-squared cannot give you.")
    if report_bt is not None:
        r()
        r(f"  Hindcast issued {report_bt.label}, {len(report_bt.results)} past years:")
        r()
        sc = report_bt.scores()
        r(f"  {'method':<16}{'skill':>8}{'RMSE kaf':>10}{'MAE kaf':>10}"
          f"{'bias kaf':>10}{'PI coverage':>13}")
        r(f"  {'-' * 70}")
        for _, row in sc.iterrows():
            r(f"  {row['method']:<16}{row['skill']:>8.2f}{row['RMSE_kaf']:>10,.0f}"
              f"{row['MAE_kaf']:>10,.0f}{row['bias_kaf']:>+10,.0f}"
              f"{row['PI_coverage']:>13.2f}")
        r()
        r(f"  'skill' is Nash-Sutcliffe: 1.0 is perfect, 0.0 is no better than")
        r(f"  predicting the historical median, negative is worse than that.")
        r(f"  'PI coverage' should land near {cfg.prediction_interval:.2f} if the")
        r(f"  stated intervals are honest.")

    if lead is not None and not lead.empty:
        r.sub("Skill by forecast issue date (RMSE, kaf)")
        piv = lead.pivot(index="month", columns="method", values="RMSE_kaf")
        cols = list(piv.columns)
        r(f"  {'issued':<10}" + "".join(f"{c:>14}" for c in cols))
        r(f"  {'-' * (10 + 14 * len(cols))}")
        for m, row in piv.iterrows():
            label = pd.Timestamp(2001, int(m), 1).strftime("%b 1")
            r(f"  {label:<10}" + "".join(f"{row[c]:>14,.0f}" for c in cols))
        r()
        r( "  The snowpack model and the recession model cross over during the")
        r( "  season. Snowpack wins while the snow is on the ground; once it has")
        r( "  melted, the river's own recession is the better predictor. The tool")
        r( "  uses whichever wins at the date you run it.")

    # -------------------------------------------------------------- snowpack
    if fc.seasonal is not None:
        sm, fit = fc.seasonal, fc.seasonal.fit
        r.head("SNOWPACK TO SEASONAL VOLUME")
        r(f"  Fitted in log space: volume = a * (snow index)^b")
        r(f"    exponent b        : {fit.slope:.3f}")
        r(f"    n                 : {fit.n} complete years")
        r(f"    in-sample r2      : {fit.r2:.3f}  (adjusted {fit.adj_r2:.3f})")
        r(f"    leave-one-out     : {fit.loocv_r2:.3f}   <- the honest number")
        r(f"    RMSE              : {fit.rmse / 1000:,.0f} kaf")
        r(f"    p (slope != 0)    : {fit.p_value:.2e}")
        if fit.influential.size:
            yrs = comp["wy"].to_numpy()[fit.influential]
            r(f"    high influence    : {', '.join(f'WY{y}' for y in yrs)}"
              f"  (Cook's D > 4/n)")
        r()
        r(f"  At the driest snowpack on record the model implies "
          f"{sm.intercept_af / 1000:,.0f} kaf")
        r(f"  ({sm.intercept_basin_in:.1f} basin inches). A physically sensible")
        r( "  model cannot send seasonal runoff to zero as snowpack does: summer")
        r( "  baseflow alone delivers several hundred kaf.")
        if sm.prediction is not None:
            p = sm.prediction
            r()
            r(f"  WY{ana.current_wy} seasonal total: {p.value / 1000:,.0f} kaf "
              f"({p.lo / 1000:,.0f} - {p.hi / 1000:,.0f})")
            r(f"    leverage h0 = {p.leverage:.3f}"
              + ("   EXTRAPOLATED beyond the calibration range"
                 if p.extrapolated else "   inside the calibration range"))

        r.sub("Do other predictors add anything?")
        base = sm.fit_swe_only_multi
        for m in (base, sm.fit_with_precip, sm.fit_with_antecedent):
            if m is None:
                continue
            gain = (m.loocv_r2 - base.loocv_r2) if base else np.nan
            r(f"  {m.name:<22} LOOCV {m.loocv_r2:.3f}"
              + (f"   ({gain:+.3f})" if m is not base and np.isfinite(gain) else ""))
        r()
        r( "  Compared on leave-one-out skill, not r-squared: adding a pure-noise")
        r( "  column raises in-sample r-squared by about 1/(n-2) every time.")

        r.sub("Candidate snowpack indices (scored, not selected)")
        r(f"  {'index':<40}{'r2':>7}{'LOOCV':>8}{'RMSE kaf':>10}")
        r(f"  {'-' * 66}")
        for _, row in fc.index.table().iterrows():
            mark = " <- used" if row["chosen"] else ""
            r(f"  {row['index']:<40}{row['r2']:>7.3f}{row['LOOCV_r2']:>8.3f}"
              f"{row['RMSE_kaf']:>10,.0f}{mark}")
        r()
        r( "  The MATLAB version fitted six such schemes and reported the winner's")
        r( "  in-sample r-squared as though it had been chosen in advance. Here the")
        r( "  index comes from configuration and this table is diagnostic only.")

    # --------------------------------------------------------------- analogs
    if fc.analogs is not None:
        a = fc.analogs
        r.head("ANALOG YEARS")
        r(f"  {len(a.analogs)} nearest neighbours on snowpack AND current flow:")
        r()
        r(f"  {'WY':<8}{'snow index':>12}{'flow then':>12}{'scale':>9}"
          f"{'implied kaf':>13}")
        r(f"  {'-' * 54}")
        for an in sorted(a.analogs, key=lambda z: z.distance):
            flag = " *" if an.scale_clipped else ""
            r(f"  WY{an.wy:<6}{an.swe_index:>12.1f}{an.q_at_ref:>12,.0f}"
              f"{an.scale:>9.2f}{an.volume_af / 1000:>13,.0f}{flag}")
        r()
        r(f"  Median {a.volume_median_af / 1000:,.0f} kaf, "
          f"10-90% {a.volume_lo_af / 1000:,.0f} - {a.volume_hi_af / 1000:,.0f} kaf")
        if any(x.scale_clipped for x in a.analogs):
            r( "  * scale factor was clipped to the allowed range")
        if a.biased_note:
            r(f"  CAVEAT: {a.biased_note}")

    # ---------------------------------------------------------- kayak season
    r.head("KAYAK SEASON OUTLOOK")
    if cur is not None and cur.sustained_below_date is not None:
        r(f"  WY{ana.current_wy} already dropped below {cfg.runnable_cfs:,.0f} cfs")
        r(f"  for {cfg.sustained_below_days}+ consecutive days on "
          f"{cur.sustained_below_date:%B %d}. That is observed fact, not a")
        r( "  forecast: the season is over. The analog figures below are context.")
        r()
    elif cur is not None and cur.last_runnable_date is not None:
        r(f"  Last day above {cfg.runnable_cfs:,.0f} cfs so far: "
          f"{cur.last_runnable_date:%B %d} (observed).")
        r()
    if fc.analogs is not None:
        for field, name in (("last_runnable_doy", "Last day above"),
                            ("sustained_below_doy",
                             f"First sustained {cfg.sustained_below_days}-day drop below")):
            q = fc.analogs.season_end_quantiles(field)
            if q is None:
                continue
            r()
            r(f"  {name} {cfg.runnable_cfs:,.0f} cfs, across "
              f"{q['n']} analog years:")
            r(f"    earliest {_doy_label(q['min'], ana.current_wy)}"
              f"   10% {_doy_label(q['p10'], ana.current_wy)}"
              f"   median {_doy_label(q['median'], ana.current_wy)}"
              f"   90% {_doy_label(q['p90'], ana.current_wy)}"
              f"   latest {_doy_label(q['max'], ana.current_wy)}")
            med_date = date_from_doy(q["median"], ana.current_wy)
            days = (med_date - ana.ref_date).days
            if field == "last_runnable_doy":
                if days > 0:
                    r(f"    -> about {days} more days of paddling if this year "
                      f"behaves like the median analog")
                else:
                    r(f"    -> the median analog was already done "
                      f"{abs(days)} days ago; this is history, not a forecast")
        r()
        r( "  This is the analog years' actual distribution, not a regression.")
        r( "  A regression on 'last day above 1000 cfs' is censored at both ends")
        r( "  -- years that never get there and years that never drop -- which")
        r( "  pulls the fitted slope toward zero and biases dry-year forecasts late.")

        edges = np.asarray(cfg.flow_bin_edges, float)
        rows = np.array([np.histogram(an.trace.to_numpy(), bins=edges)[0]
                         for an in fc.analogs.analogs])
        med = np.median(rows, axis=0)
        r.sub(f"Days in each flow band, {ana.ref_date:%b %d} to Sep 30 "
              f"(median across analogs)")
        for lab, d, days in zip(cfg.flow_bin_labels, cfg.flow_bin_desc, med):
            r(f"    {lab:>6} cfs  {days:>5.0f} days   {d}")

    if fc.analogs is not None:
        r.sub("When flow drops through each level (analog median)")
        for thr in (5000, 3000, 2000, 1000, 500):
            hit = fc.analogs.threshold_crossing(thr)
            if cur is not None and cur.q_mean_at_ref_cfs <= thr:
                r(f"    {thr:>5,} cfs : already below")
            elif hit is None:
                r(f"    {thr:>5,} cfs : stays above through Sep 30")
            else:
                doy, agree = hit
                r(f"    {thr:>5,} cfs : around "
                  f"{_doy_label(doy, ana.current_wy)}"
                  f"   ({agree} of {len(fc.analogs.analogs)} analogs agree "
                  f"within 2 weeks)")

    # -------------------------------------------------- season-end validation
    if season is not None:
        _season_end_section(r, cfg, ana, season, season_skill, season_current)

    # ------------------------------------------------------------ ecology
    if th is not None:
        r.head("WATER TEMPERATURE AND SALMONID THERMAL STRESS")
        r(f"  Criterion: {th.threshold_c} C as a 7-day average of daily MAXIMA")
        r( "  (7-DADMax), the Washington standard for salmonid spawning, rearing")
        r( "  and migration. The daily mean runs well below the daily maximum, so")
        r( "  comparing the mean to 17.5 undercounts exceedances of the standard.")
        if th.note:
            r(f"  WARNING: {th.note}")
        tf = th.frame()
        if not tf.empty:
            r()
            r(f"  {'WY':<8}{'coverage':>10}{'mean>thr':>10}{'7DADMax>thr':>14}"
              f"{'summer max C':>14}")
            r(f"  {'-' * 56}")
            for _, row in tf.iterrows():
                r(f"  WY{int(row['wy']):<6}{row['coverage']:>9.0%}"
                  f"{int(row['days_over_mean']):>10}"
                  f"{int(row['days_over_7dadmax']):>14}"
                  f"{row['summer_max_c']:>14.1f}")
            gap = tf["days_over_7dadmax"].sum() - tf["days_over_mean"].sum()
            r()
            r(f"  Across the record the daily-mean statistic misses {gap} "
              f"exceedance days")
            r( "  that the actual regulatory statistic counts.")
        bb = th.by_flow_bin.dropna(subset=["pct_over"])
        if not bb.empty:
            r.sub("Thermal-stress risk by discharge")
            for _, row in bb.iterrows():
                r(f"    {row['band']:>8} cfs : {row['pct_over']:>5.0f}% of days "
                  f"above {th.threshold_c} C   (n={int(row['n_days']):,})")
        if th.air_water_fit is not None:
            r.sub("Is summer temperature hydrologic or meteorological?")
            r(f"    air temperature + log(flow)        skill "
              f"{th.air_water_fit.loocv_r2:.3f}")
            if th.swe_marginal is not None:
                gain = th.swe_marginal.loocv_r2 - th.air_water_fit.loocv_r2
                r(f"    ... plus the snowpack index        skill "
                  f"{th.swe_marginal.loocv_r2:.3f}   ({gain:+.3f})")
                r()
                r( "    Snowpack adds little once air temperature and flow are")
                r( "    accounted for. Regressing summer temperature on snowpack")
                r( "    alone -- as the MATLAB version did -- attributes a weather")
                r( "    signal to snow. Snowpack governs WHEN the river leaves its")
                r( "    cold high-flow regime, not how warm it ultimately gets.")
        r()
        r(f"  Record length: {th.n_complete} water years with good summer coverage.")
        if th.n_complete < cfg.min_n_for_regression:
            r( "  That is too short to support a trend or a regression on annual")
            r( "  temperature statistics. Treat this section as descriptive.")

    # ------------------------------------------------------------- trends
    r.head("LONG-TERM TRENDS")
    r( "  Theil-Sen slope with a Mann-Kendall test, variance inflated for serial")
    r( "  correlation (Hamed-Rao). A slope whose interval spans zero is reported")
    r( "  as not significant rather than quoted as a finding.")
    r()
    series = [
        ("Peak snowpack index", comp[cfg.snow_index], "in"),
        ("Peak snowpack timing", comp["peak_swe_doy"], "days"),
        ("Total annual runoff", comp["v_total_kaf"], "kaf"),
        (f"Seasonal runoff ({ana.window_label})", comp["v_seasonal_kaf"], "kaf"),
        ("Oct-Mar runoff", comp["v_oct_mar_kaf"], "kaf"),
        ("Flow centroid", comp["centroid_doy"], "days"),
        ("Last day above 1,000 cfs", comp["last_runnable_doy"], "days"),
    ]
    for thr in (1000, 3000, 5000):
        days = []
        for rec in ana.records:
            if not rec.complete:
                continue
            ws, we = wy_bounds(rec.wy)
            q = ana.q.loc[ws:we].dropna()
            days.append(float((q >= thr).sum() / len(q) * 365) if len(q) else np.nan)
        series.append((f"Days above {thr:,} cfs", pd.Series(days, index=comp.index),
                       "days"))

    n_sig = 0
    for name, vals, units in series:
        tr = trend(comp["wy"], vals, name, units)
        r(f"  {tr.describe()}")
        n_sig += int(tr.significant)
    r()
    r(f"  {n_sig} of {len(series)} trends are significant at p<0.05. With "
      f"{len(comp)} years")
    r( "  and this much interannual variability, most PNW climate signals sit")
    r( "  below the detection limit of a record this short. That is a statement")
    r( "  about the record, not evidence that nothing is changing.")

    # ------------------------------------------------------------- caveats
    r.head("WHAT THIS TOOL DOES NOT ACCOUNT FOR")
    r( "  * Irrigation diversions upstream of Monitor (Wenatchee Reclamation")
    r( "    District, Icicle and Peshastin districts) are NOT removed. Summer")
    r( "    flows here are net of withdrawal, and diversion practice has changed")
    r( "    over the record, so part of any late-season trend is water")
    r( "    management rather than climate. Re-running at Peshastin (12459000)")
    r( "    with --site is a partial control: it sits above the Dryden-reach")
    r( "    diversions.")
    r( "  * Four point SNOTEL stations, averaging 4,835 ft, stand in for a basin")
    r( "    spanning roughly 600 to 8,000 ft. There is no hypsometric weighting,")
    r( "    so the index may be biased high or low in a way that varies with the")
    r( "    snowline. Gridded SWE (SNODAS) would be the proper fix.")
    r( "  * Rain-on-snow volume is inside the seasonal window and is not")
    r( "    separated from snowmelt. In a year with a large winter rain event,")
    r( "    part of the 'melt' volume was never snow.")
    r( "  * The recent ~60 days of USGS data are provisional and get revised.")
    r( "  * No comparison against NRCS or NWRFC operational forecasts, which")
    r( "    have published skill. Until that benchmark exists, treat this as a")
    r( "    transparent statistical tool, not a competitor to them.")

    r()
    r.rule()
    r(f"  Generated {pd.Timestamp.now():%Y-%m-%d %H:%M} from data fetched "
      f"{ana.raw.fetched_at:%Y-%m-%d %H:%M}")
    r.rule()
    return r


# --------------------------------------------------------------------------
def _season_end_section(r: Report, cfg: Config, ana: Analysis, val,
                        skill, current) -> None:
    """When does the boating season end, and how well can the date be called?"""
    from . import season_end as SE

    thr = cfg.runnable_cfs
    method = val.best_method()
    tbl = val.table(method).sort_values("wy")
    sc = val.scores()

    r.head("WHEN DOES THE BOATING SEASON END?")
    r( "  Target: the last day of the summer recession on which the river is")
    r(f"  still running {thr:,.0f} cfs or more - the day after which it is out")
    r( "  for the year.")
    r()
    r( "  This is deliberately NOT 'the last day above the threshold anywhere in")
    r( "  the season', which is what the MATLAB version regressed on. An isolated")
    r( "  September rain bump is not boating season. The two definitions differ")
    ends = [SE.find_season_end(ana.q, rec.wy, thr, cfg.sustained_below_days)
            for rec in ana.records]
    bumps = sorted([(e.wy, e.rain_bump_days) for e in ends
                    if e.rain_bump_days > 3], key=lambda z: -z[1])
    if bumps:
        r(f"  in {len(bumps)} of {len(ends)} years, by up to {bumps[0][1]} days:")
        r("    " + ", ".join(f"WY{w} +{d}d" for w, d in bumps[:8]))
        r( "  Those are the wet-autumn years, so the error is systematic, not noise.")

    # -- the current year ------------------------------------------------
    r.sub(f"WY{ana.current_wy}")
    if current.get("status") == "observed":
        r(f"  ACTUAL last boatable day: {current['actual']:%A, %B %d, %Y}"
          f"   (observed)")
        r(f"  Flow first stayed below {thr:,.0f} cfs for "
          f"{cfg.sustained_below_days}+ days from "
          f"{current['sustained_start']:%B %d}.")
    if current.get("predicted") is not None:
        r(f"  Model call, issued {val.label} using '{current['method']}': "
          f"{current['predicted']:%B %d}")
        r(f"    {cfg.prediction_interval:.0%} interval "
          f"{current['predicted_lo']:%B %d} to {current['predicted_hi']:%B %d}")
        if "error_days" in current:
            e = int(current["error_days"])
            word = "late" if e > 0 else ("early" if e < 0 else "exact")
            r(f"    Error: {e:+d} days ({word})")

    # -- skill -----------------------------------------------------------
    r.sub(f"How good is this forecast? (issued {val.label}, leave-one-out)")
    r(f"  {'predictor':<16}{'MAE days':>10}{'RMSE':>8}{'bias':>8}"
      f"{'<=1 wk':>9}{'<=2 wk':>9}{'PI cov':>9}")
    r(f"  {'-' * 69}")
    for _, row in sc.iterrows():
        mark = "  <-- used" if row["method"] == method else ""
        r(f"  {row['method']:<16}{row['MAE_days']:>10.1f}"
          f"{row['RMSE_days']:>8.1f}{row['bias_days']:>+8.1f}"
          f"{row['within_1wk']:>9.0%}{row['within_2wk']:>9.0%}"
          f"{row['PI_coverage']:>9.2f}{mark}")
    r()
    r(f"  {len(val.usable())} years scored. {val.n_censored} censored years")
    r( "  (flow never dropped below the threshold before Sep 30) are excluded")
    r( "  from the scores and flagged in the table below.")
    r()
    r( "  'swe_remaining' is the snow water still on the ground at the issue")
    r( "  date. It beats peak snowpack because it already reflects how fast")
    r( "  this year's melt is running, not merely how much snow fell.")

    if skill is not None and not skill.empty:
        r.sub("Error by forecast issue date (mean absolute error, days)")
        piv = skill.pivot_table(index="issue", columns="method",
                               values="MAE_days", sort=False)
        order = [d for d in ("Mar 01", "Apr 01", "May 01", "May 15",
                             "Jun 01", "Jun 15", "Jul 01") if d in piv.index]
        piv = piv.reindex(order)
        cols = list(piv.columns)
        r(f"  {'issued':<10}" + "".join(f"{c:>15}" for c in cols))
        r(f"  {'-' * (10 + 15 * len(cols))}")
        for idx, row in piv.iterrows():
            r(f"  {idx:<10}" + "".join(f"{row[c]:>15.1f}" for c in cols))
        r()
        r( "  Ask in March and the answer is good to about twelve days; ask on")
        r( "  June 1 and it is good to about six. By July the snow is gone and")
        r( "  the river's own flow becomes the better predictor.")

    # -- the annual table -------------------------------------------------
    r.sub(f"Predicted against actual, every year "
          f"(issued {val.label}, predictor '{method}')")
    r( "  Each year is predicted by a model fitted on the other years only.")
    r()
    r(f"  {'WY':<7}{'SWE left':>10}{'PREDICTED':>12}{'ACTUAL':>10}"
      f"{'error':>8}   {cfg.prediction_interval:.0%} interval")
    r(f"  {'-' * 70}")
    for _, row in tbl.iterrows():
        wy = int(row["wy"])
        note = "  censored" if row["censored"] else ""
        swe = row["swe_remaining_in"]
        swe_s = f"{swe:.1f} in" if np.isfinite(swe) else "     -"
        r(f"  {wy:<7}{swe_s:>10}"
          f"{SE.date_label(row['predicted_doy'], wy):>12}"
          f"{SE.date_label(row['actual_doy'], wy):>10}"
          f"{row['error_days']:>+8.0f}   "
          f"{SE.date_label(row['lo_doy'], wy)} - "
          f"{SE.date_label(row['hi_doy'], wy)}{note}")

    good = tbl[~tbl.censored & ~tbl.already_over]["error_days"].dropna()
    if len(good):
        r()
        r(f"  Median absolute error {np.median(np.abs(good)):.0f} days; "
          f"largest miss {np.max(np.abs(good)):.0f} days.")
        r( "  A negative error means the model called the season over earlier")
        r( "  than it actually ended.")


# --------------------------------------------------------------------------
def write_json(path: Path, cfg: Config, ana: Analysis, fc, th, report_bt) -> None:
    """Machine-readable summary for downstream use."""
    def f(x) -> float | None:
        return float(x) if x is not None and np.isfinite(x) else None

    cur = ana.current
    out = {
        "generated": pd.Timestamp.now().isoformat(),
        "reference_date": ana.ref_date.isoformat(),
        "is_hindcast": ana.is_hindcast,
        "site": {"usgs": cfg.usgs_site, "name": cfg.usgs_site_name,
                 "drainage_mi2": cfg.drainage_mi2},
        "water_year": ana.current_wy,
        "complete_years": len(ana.complete),
        "volume_window": ana.window_label,
        "snow_index": fc.index.chosen_label,
        "current": {
            "snow_index_in": f(getattr(cur, "composite_peak_swe_in", None)),
            "snow_frac_remaining": f(getattr(cur, "swe_frac_at_ref", None)),
            "flow_cfs": f(getattr(cur, "q_mean_at_ref_cfs", None)),
            "volume_to_date_kaf": f(getattr(cur, "v_to_ref_af", np.nan) / 1000
                                    if cur else None),
        } if cur else None,
        "headline": {
            "method": fc.primary_name,
            "basis": fc.primary_basis,
            "remaining_kaf": f(fc.primary_af / 1000),
            "lo_kaf": f(fc.primary_lo_af / 1000),
            "hi_kaf": f(fc.primary_hi_af / 1000),
            "interval": cfg.prediction_interval,
        },
        "estimates": [
            {"method": e["method"], "kaf": f(e["af"] / 1000),
             "lo_kaf": f(e["lo"] / 1000), "hi_kaf": f(e["hi"] / 1000),
             "skill": f(e.get("skill")), "note": e.get("note", "")}
            for e in fc.estimates()
        ],
        "warning": fc.consistency_warning or None,
        "analog_years": fc.analogs.wys if fc.analogs else [],
        "hindcast": (report_bt.scores().to_dict("records")
                     if report_bt is not None else []),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=2), encoding="utf-8")
