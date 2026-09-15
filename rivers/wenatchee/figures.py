"""Figure generation.

Conventions that hold across every figure, because the MATLAB original broke
each of them somewhere:

* The partial current water year is drawn in red and labelled "(partial)". It
  never contributes to a median, an envelope, a regression or a trend.
* A fitted line is drawn only across the range of data it was fitted to.
  Extending it to the axis origin asserts a relationship the record cannot
  support.
* A percentile envelope is masked wherever fewer than 20 years back it, so a
  band cannot narrow or turn jagged merely because the record thinned.
* A trend line is drawn solid when Mann-Kendall says it is significant and
  dashed when it does not, with the p-value in the title either way.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.dates as mdates          # noqa: E402
import matplotlib.pyplot as plt            # noqa: E402
from matplotlib.patches import Patch       # noqa: E402

from .config import (CURRENT_COLOR, DECADE_COLORS, FLOW_BIN_COLORS, HIST_COLOR,
                     MONTH_LABELS, MONTH_START_DOY, STATION_COLORS, Config)
from .core import (Analysis, basin_inches, date_from_doy, doy_of_wy,
                   wy_bounds)
from .stats import envelope, trend

plt.rcParams.update({
    "figure.facecolor": "white",
    "axes.grid": True,
    "grid.alpha": 0.25,
    "axes.axisbelow": True,
    "font.size": 9,
    "axes.titlesize": 10,
    "figure.titlesize": 12,
    "legend.framealpha": 0.9,
})


class FigureSet:
    """Collects figures and writes them to the output directory."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.dir = cfg.figure_dir
        self.dir.mkdir(parents=True, exist_ok=True)
        self.paths: list[Path] = []

    def save(self, fig, name: str, title: str = "") -> Path:
        path = self.dir / f"{name}.png"
        fig.savefig(path, dpi=self.cfg.figure_dpi, bbox_inches="tight")
        if not self.cfg.show_figures:
            plt.close(fig)
        self.paths.append(path)
        print(f"    {path.name}" + (f"  -- {title}" if title else ""))
        return path


# --------------------------------------------------------------------------
# shared helpers
# --------------------------------------------------------------------------
def _month_axis(ax, lo: int = 1, hi: int = 365, which=slice(None)) -> None:
    ticks = list(MONTH_START_DOY)[which]
    labels = list(MONTH_LABELS)[which]
    keep = [(t, l) for t, l in zip(ticks, labels) if lo <= t <= hi]
    if keep:
        ax.set_xticks([t for t, _ in keep])
        ax.set_xticklabels([l for _, l in keep])
    ax.set_xlim(lo, hi)


def _doy_to_label(doy: float, wy: int) -> str:
    d = date_from_doy(doy, wy)
    return d.strftime("%b %d") if d is not None else "n/a"


def _trend_panel(ax, years, values, label: str, units: str, color: str) -> None:
    """Scatter plus a Theil-Sen trend, drawn dashed when not significant."""
    years = np.asarray(years, float)
    values = np.asarray(values, float)
    ok = np.isfinite(years) & np.isfinite(values)
    ax.scatter(years[ok], values[ok], s=26, color=color, zorder=3)
    tr = trend(years[ok], values[ok], label, units)
    if np.isfinite(tr.slope):
        xs = np.array([years[ok].min(), years[ok].max()])
        ax.plot(xs, tr.line(xs), "-" if tr.significant else "--",
                color="black", lw=1.6 if tr.significant else 1.2,
                label=("significant" if tr.significant else "not significant"))
        ax.set_title(f"{label}\n{tr.slope:+.3g} {units}/yr"
                     + (f", p={tr.p_value:.3f}" if np.isfinite(tr.p_value) else "")
                     + ("" if tr.significant else "  (n.s.)"))
    ax.set_xlabel("Water year")
    return tr


# ==========================================================================
# 1. Headline forecast
# ==========================================================================
def forecast_summary(fs: FigureSet, ana: Analysis, fc) -> None:
    cfg, cur = ana.cfg, ana.current
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 8.5),
                                   gridspec_kw={"height_ratios": [2, 1.4]})

    # --- hydrograph with historical envelope and analog forecast ---
    mat = ana.daily_matrix(ana.q)
    env, counts = envelope(mat.to_numpy(), (0.1, 0.5, 0.9), min_count=20)
    doy = mat.index.to_numpy()
    ax1.fill_between(doy, env[0.1] / 1000, env[0.9] / 1000, color=HIST_COLOR,
                     alpha=0.18, label="Historical 10-90%")
    ax1.plot(doy, env[0.5] / 1000, color=HIST_COLOR, lw=1.3,
             label="Historical median")

    ws, _ = wy_bounds(ana.current_wy)
    q_cur = ana.q.loc[ws:ana.ref_date].dropna()
    doy_cur = doy_of_wy(q_cur.index, ana.current_wy)
    ax1.plot(doy_cur, q_cur.to_numpy() / 1000, color=CURRENT_COLOR, lw=2.0,
             label=f"WY{ana.current_wy} (partial)")
    if len(q_cur):
        ax1.plot(doy_cur[-1], q_cur.iloc[-1] / 1000, "o", color=CURRENT_COLOR, ms=7)
        ax1.annotate(f"{q_cur.iloc[-1]:,.0f} cfs\n{ana.ref_date:%b %d}",
                     (doy_cur[-1], q_cur.iloc[-1] / 1000),
                     textcoords="offset points", xytext=(8, 4),
                     color=CURRENT_COLOR, fontweight="bold", fontsize=8)

    if fc.analogs is not None:
        a = fc.analogs
        ax1.fill_between(a.q_median.index, a.q_lo / 1000, a.q_hi / 1000,
                         color=CURRENT_COLOR, alpha=0.14,
                         label="Analog 10-90%")
        ax1.plot(a.q_median.index, a.q_median / 1000, "--",
                 color=CURRENT_COLOR, lw=1.6, label="Analog median forecast")
    for thr, name in ((5000, "5k"), (3000, "3k"), (1000, "1k")):
        ax1.axhline(thr / 1000, color="0.55", ls=":", lw=0.8)
        ax1.annotate(name, (0.995, thr / 1000),
                     xycoords=("axes fraction", "data"), fontsize=7,
                     color="0.4", va="bottom", ha="right")

    ax1.set_ylabel("Discharge (kcfs, log scale)")
    ax1.set_title(f"{cfg.usgs_site_name} - WY{ana.current_wy} against "
                  f"WY{cfg.start_wy}-{ana.current_wy - 1}"
                  + ("   [HINDCAST]" if ana.is_hindcast else ""))
    _month_axis(ax1)
    # Log scale: a single winter rain spike can be 50x baseflow, and on a
    # linear axis it flattens the entire melt season into the bottom inch of
    # the plot -- which is the part the forecast is about.
    ax1.set_yscale("log")
    ax1.set_ylim(0.15, None)
    ax1.yaxis.set_major_formatter(
        matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:g}"))
    ax1.yaxis.set_minor_formatter(
        matplotlib.ticker.FuncFormatter(
            lambda v, _: f"{v:g}" if v in (0.2, 0.5, 2, 5, 20, 50) else ""))
    ax1.legend(loc="upper right", fontsize=8)

    # --- remaining-volume estimates, side by side, never averaged ---
    est = fc.estimates()
    if est:
        ypos = np.arange(len(est))[::-1]
        for y, e in zip(ypos, est):
            lo, hi, v = e["lo"] / 1000, e["hi"] / 1000, e["af"] / 1000
            is_primary = e["method"].startswith(fc.primary_name.split(" (")[0])
            c = CURRENT_COLOR if is_primary else "#4C72B0"
            ax2.plot([lo, hi], [y, y], lw=6, color=c, alpha=0.28,
                     solid_capstyle="butt")
            ax2.plot(v, y, "o", color=c, ms=9, zorder=4)
            ax2.annotate(f"{v:,.0f} kaf", (v, y), textcoords="offset points",
                         xytext=(0, 10), ha="center", fontsize=8,
                         fontweight="bold", color=c)
        ax2.set_yticks(ypos)
        ax2.set_yticklabels([e["method"] for e in est], fontsize=8)
        ax2.set_xlabel(f"Volume remaining, {ana.ref_date:%b %d} to Sep 30 "
                       f"(kaf; bars are {cfg.prediction_interval:.0%} intervals)")
        ax2.set_title("Every estimate shown separately - they are NOT averaged, "
                      "because they are not independent", pad=16)
        ax2.margins(y=0.25)
        ax2.axvline(0, color="0.7", lw=0.8)
        ax2.grid(axis="y", alpha=0)
    fig.tight_layout()
    fs.save(fig, "01_forecast_summary", "headline forecast")


# ==========================================================================
# 2. Hindcast verification
# ==========================================================================
def hindcast_verification(fs: FigureSet, ana: Analysis, report, lead: pd.DataFrame
                          ) -> None:
    fig = plt.figure(figsize=(12, 8))
    gs = fig.add_gridspec(2, 2, height_ratios=[1.15, 1])
    ax1 = fig.add_subplot(gs[0, 0])
    ax2 = fig.add_subplot(gs[0, 1])
    ax3 = fig.add_subplot(gs[1, :])

    colors = {"recession": "#1F77B4", "snowpack": "#2CA02C",
              "climatology": "#999999"}

    if report is not None:
        df = report.frame()
        obs = df["observed_kaf"].to_numpy()
        lim = [0, float(np.nanmax(obs) * 1.25)]
        for m in report.methods:
            col = f"{m}_kaf"
            if col not in df:
                continue
            ax1.scatter(obs, df[col], s=34, alpha=0.8, label=m,
                        color=colors.get(m, None))
        ax1.plot(lim, lim, "k--", lw=1, label="perfect")
        ax1.set_xlim(lim)
        ax1.set_ylim(lim)
        ax1.set_xlabel("Observed remaining volume (kaf)")
        ax1.set_ylabel("Predicted (kaf)")
        ax1.set_title(f"Leave-one-out hindcast, issued {report.label}\n"
                      f"every year forecast without using itself")
        ax1.legend(fontsize=8)

        sc = report.scores()
        ax2.axis("off")
        rows = [["method", "skill", "RMSE", "MAE", "bias", "PI cov"]]
        for _, r in sc.iterrows():
            rows.append([r["method"], f"{r['skill']:.2f}",
                         f"{r['RMSE_kaf']:.0f}", f"{r['MAE_kaf']:.0f}",
                         f"{r['bias_kaf']:+.0f}", f"{r['PI_coverage']:.2f}"])
        tbl = ax2.table(cellText=rows[1:], colLabels=rows[0], loc="center",
                        cellLoc="center")
        tbl.auto_set_font_size(False)
        tbl.set_fontsize(8.5)
        tbl.scale(1, 1.6)
        ax2.set_title(f"Hindcast skill, issued {report.label}\n"
                      f"(volumes in kaf; PI coverage should be "
                      f"{ana.cfg.prediction_interval:.2f})")

    if lead is not None and not lead.empty:
        piv = lead.pivot(index="month", columns="method", values="RMSE_kaf")
        months = piv.index.to_numpy()
        for m in piv.columns:
            ax3.plot(months, piv[m], "o-", label=m, color=colors.get(m, None), lw=1.8)
        ax3.set_xticks(months)
        ax3.set_xticklabels([pd.Timestamp(2001, int(m), 1).strftime("%b 1")
                             for m in months])
        ax3.set_xlabel("Forecast issue date")
        ax3.set_ylabel("Hindcast RMSE (kaf)")
        ax3.set_title("Which model to trust depends on the date. The snowpack "
                      "regression wins in spring; once the snow is gone, the "
                      "river's own recession wins.")
        ax3.legend(fontsize=8)
        ax3.set_ylim(bottom=0)
    fig.tight_layout()
    fs.save(fig, "02_hindcast_verification", "does the forecast actually work?")


# ==========================================================================
# 3. Snowpack -> volume regression
# ==========================================================================
def snowpack_regression(fs: FigureSet, ana: Analysis, fc) -> None:
    cfg = ana.cfg
    sm = fc.seasonal
    if sm is None:
        return
    fit = sm.fit
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))

    ax1.scatter(fit.x, fit.y / 1000, s=42, color="0.45", label="Complete years",
                zorder=3)
    infl = fit.influential
    if infl.size:
        ax1.scatter(fit.x[infl], fit.y[infl] / 1000, s=110, facecolors="none",
                    edgecolors="#D62728", lw=1.4,
                    label=f"high influence (Cook's D > 4/n): n={infl.size}")
    xl, yl = fit.line()
    ax1.plot(xl, yl / 1000, "k-", lw=1.5,
             label=f"log-log fit (LOOCV skill {fit.loocv_r2:.2f})")

    if sm.prediction is not None:
        p = sm.prediction
        x_now = float(ana.frame().loc[ana.current_wy, cfg.snow_index])
        ax1.errorbar(x_now, p.value / 1000,
                     yerr=[[max(0, (p.value - p.lo) / 1000)],
                           [max(0, (p.hi - p.value) / 1000)]],
                     fmt="*", ms=18, color=CURRENT_COLOR, capsize=4, zorder=5,
                     label=f"WY{ana.current_wy} predicted (partial)")
        flag = "  EXTRAPOLATED" if p.extrapolated else ""
        ax1.annotate(f"WY{ana.current_wy}\n{p.value/1000:,.0f} kaf{flag}",
                     (x_now, p.value / 1000), textcoords="offset points",
                     xytext=(10, -6), color=CURRENT_COLOR, fontweight="bold",
                     fontsize=8)

    ax1.set_xlabel(f"{fc.index.chosen_label}")
    ax1.set_ylabel(f"Seasonal runoff volume, {sm.window_label} (kaf)")
    ax1.set_title(f"Snowpack vs seasonal runoff\n"
                  f"n={fit.n}, LOOCV skill {fit.loocv_r2:.2f}, "
                  f"RMSE {fit.rmse/1000:,.0f} kaf")
    ax1.legend(fontsize=7.5, loc="upper left")

    sec = ax1.secondary_yaxis(
        "right", functions=(lambda v: v * 1000 / (cfg.drainage_mi2 * 640 / 12),
                            lambda v: v * (cfg.drainage_mi2 * 640 / 12) / 1000))
    sec.set_ylabel("Runoff (inches over the basin)")

    # candidate index skill
    tbl = fc.index.table()
    y = np.arange(len(tbl))[::-1]
    cols = [CURRENT_COLOR if c else "#4C72B0" for c in tbl["chosen"]]
    ax2.barh(y, tbl["LOOCV_r2"], color=cols)
    ax2.set_yticks(y)
    ax2.set_yticklabels(tbl["index"], fontsize=8)
    ax2.set_xlabel("Leave-one-out skill")
    ax2.set_title("Candidate snowpack indices, scored out-of-sample.\n"
                  "The index used is fixed in config (red), not picked here.")
    ax2.set_xlim(0, 1)
    fig.tight_layout()
    fs.save(fig, "03_snowpack_regression", "snowpack to volume")


# ==========================================================================
# 4. Analogs
# ==========================================================================
def analog_detail(fs: FigureSet, ana: Analysis, fc) -> None:
    a = fc.analogs
    if a is None:
        return
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5),
                                   gridspec_kw={"width_ratios": [1.7, 1]})
    cmap = plt.get_cmap("viridis")
    for i, an in enumerate(a.analogs):
        ax1.plot(an.trace.index, an.trace.to_numpy() / 1000, lw=1.1,
                 color=cmap(i / max(1, len(a.analogs) - 1)), alpha=0.85,
                 label=f"WY{an.wy}")
    ws, _ = wy_bounds(ana.current_wy)
    q_cur = ana.q.loc[ws:ana.ref_date].dropna()
    ax1.plot(doy_of_wy(q_cur.index, ana.current_wy), q_cur.to_numpy() / 1000,
             color="black", lw=2.2, label=f"WY{ana.current_wy} observed")
    ax1.set_ylabel("Discharge (kcfs)")
    ax1.set_title(f"Analog years, rescaled to today's flow "
                  f"({len(a.analogs)} of {a.n_candidates} complete years)")
    _month_axis(ax1, lo=max(1, int(a.ref_doy) - 90), hi=365)
    ax1.legend(fontsize=7, ncol=2)

    vols = np.array([an.volume_af for an in a.analogs]) / 1000
    ax2.hist(vols, bins=max(4, len(vols) // 2), color="#4C72B0",
             edgecolor="white")
    ax2.axvline(a.volume_median_af / 1000, color=CURRENT_COLOR, lw=2,
                label=f"median {a.volume_median_af/1000:,.0f} kaf")
    ax2.axvspan(a.volume_lo_af / 1000, a.volume_hi_af / 1000,
                color=CURRENT_COLOR, alpha=0.12, label="10-90%")
    ax2.set_xlabel("Remaining volume implied by each analog (kaf)")
    ax2.set_ylabel("Analog years")
    ax2.set_title("Quantiles taken over analog VOLUMES,\n"
                  "not over daily flows that are then summed")
    ax2.legend(fontsize=8)
    if a.biased_note:
        fig.text(0.5, -0.02, "Note: " + a.biased_note, ha="center", fontsize=8.5,
                 color="#B03A2E")
    fig.tight_layout()
    fs.save(fig, "04_analog_forecast", "analog ensemble")


# ==========================================================================
# 5. Kayaker outlook
# ==========================================================================
def kayaker_outlook(fs: FigureSet, ana: Analysis, fc) -> None:
    cfg = ana.cfg
    fig, axes = plt.subplots(2, 2, figsize=(12, 8))
    ax1, ax2, ax3, ax4 = axes.ravel()

    # days per flow bin among analogs, for the remaining season
    if fc.analogs is not None:
        edges = np.asarray(cfg.flow_bin_edges, float)
        rows, labels = [], []
        for an in fc.analogs.analogs:
            rows.append(np.histogram(an.trace.to_numpy(), bins=edges)[0])
            labels.append(f"WY{an.wy}")
        arr = np.array(rows)
        bottom = np.zeros(len(rows))
        for b in range(arr.shape[1]):
            ax1.bar(labels, arr[:, b], bottom=bottom,
                    color=FLOW_BIN_COLORS[b], label=cfg.flow_bin_labels[b])
            bottom += arr[:, b]
        ax1.set_ylabel("Days")
        ax1.set_title(f"Days in each flow band, {ana.ref_date:%b %d} to Sep 30\n"
                      "(each analog year, rescaled)")
        ax1.tick_params(axis="x", rotation=60, labelsize=7)
        ax1.legend(fontsize=6.5, ncol=7, loc="upper center",
                   bbox_to_anchor=(0.5, -0.28), frameon=False)

        med = np.median(arr, axis=0)
        ax2.barh(list(cfg.flow_bin_labels), med, color=FLOW_BIN_COLORS)
        for i, (v, d) in enumerate(zip(med, cfg.flow_bin_desc)):
            ax2.annotate(f"  {v:.0f} d - {d}", (0, i), fontsize=7.5,
                         va="center", color="0.2")
        ax2.set_xlabel("Median days across analogs")
        ax2.set_title("What the rest of the season looks like")
        ax2.set_xlim(0, max(med.max() * 1.9, 1))
        ax2.set_yticklabels([])

    # season end: empirical distribution over analogs
    for ax, field, name in ((ax3, "last_runnable_doy", "Last day above"),
                            (ax4, "sustained_below_doy",
                             f"First sustained {cfg.sustained_below_days}-day drop below")):
        q = fc.analogs.season_end_quantiles(field) if fc.analogs else None
        if q is None:
            ax.axis("off")
            continue
        ax.hist(q["values"], bins=10, color="#4C72B0", edgecolor="white")
        for key, c, ls in (("p10", "0.4", ":"), ("median", CURRENT_COLOR, "-"),
                           ("p90", "0.4", ":")):
            ax.axvline(q[key], color=c, ls=ls,
                       lw=2 if key == "median" else 1.2)
        ax.set_title(f"{name} {cfg.runnable_cfs:,.0f} cfs\n"
                     f"median {_doy_to_label(q['median'], ana.current_wy)}, "
                     f"80% range {_doy_to_label(q['p10'], ana.current_wy)}"
                     f" - {_doy_to_label(q['p90'], ana.current_wy)}  (n={q['n']})")
        ax.set_ylabel("Analog years")
        lo = max(1, int(min(q["values"]) - 20))
        hi = min(365, int(max(q["values"]) + 20))
        _month_axis(ax, lo, hi)

    sub = ("Kayaker outlook - from the analog years' actual dates, "
           "not from a regression on a censored response")
    cur = ana.current
    if cur is not None and cur.sustained_below_date is not None:
        sub = (f"WY{ana.current_wy}: the river already dropped below "
               f"{cfg.runnable_cfs:,.0f} cfs for good on "
               f"{cur.sustained_below_date:%b %d} - this season is over.\n"
               "Panels below show what the analog years did, for context.")
    fig.suptitle(sub, fontweight="bold")
    fig.tight_layout()
    fs.save(fig, "05_kayaker_outlook", "flow bands and season end")


# ==========================================================================
# 6. Snowpack traces and trends
# ==========================================================================
def snowpack_state(fs: FigureSet, ana: Analysis, fc) -> None:
    cfg = ana.cfg
    fig, axes = plt.subplots(2, 2, figsize=(12, 8))
    ax1, ax2, ax3, ax4 = axes.ravel()

    for st in ana.stations:
        df = ana.raw.snotel.get(st.site_id)
        if df is None:
            continue
        color = STATION_COLORS.get(st.name, None)
        mat = ana.daily_matrix(df["swe_in"])
        if not mat.empty:
            env, _ = envelope(mat.to_numpy(), (0.5,), min_count=20)
            ax1.plot(mat.index, env[0.5], "--", color=color, lw=0.9, alpha=0.7)
        ws, _ = wy_bounds(ana.current_wy)
        cur = df.loc[ws:ana.ref_date, "swe_in"].dropna()
        if not cur.empty:
            ax1.plot(doy_of_wy(cur.index, ana.current_wy), cur.to_numpy(),
                     color=color, lw=2,
                     label=f"{st.name} ({st.elev_ft:,} ft)")
    ax1.set_ylabel("SWE (inches)")
    ax1.set_title(f"SNOTEL snow water equivalent\n"
                  f"WY{ana.current_wy} solid, historical median dashed")
    _month_axis(ax1)
    ax1.legend(fontsize=7.5)

    df = ana.frame()
    comp = df[df.complete]
    _trend_panel(ax2, comp["wy"], comp[cfg.snow_index],
                 "Composite peak snowpack", "in", "#4C72B0")
    ax2.set_ylabel("Peak SWE (in)")
    curv = df.loc[ana.current_wy, cfg.snow_index] if ana.current_wy in df.index else np.nan
    if np.isfinite(curv):
        ax2.scatter([ana.current_wy], [curv], s=90, color=CURRENT_COLOR,
                    zorder=5, marker="*", label=f"WY{ana.current_wy} (partial)")
        ax2.legend(fontsize=7.5)

    _trend_panel(ax3, comp["wy"], comp["peak_swe_doy"],
                 "Peak snowpack timing", "days", "#4C72B0")
    ax3.set_ylabel("Peak SWE date")
    yt = [t for t in MONTH_START_DOY if 120 <= t <= 250]
    ax3.set_yticks(yt)
    ax3.set_yticklabels([MONTH_LABELS[MONTH_START_DOY.index(t)] for t in yt])

    _trend_panel(ax4, comp["wy"], comp["centroid_doy"],
                 "Flow centroid (timing of the year's water)", "days", "#4C72B0")
    ax4.set_ylabel("Centroid day of water year")
    yt = [t for t in MONTH_START_DOY if 90 <= t <= 280]
    ax4.set_yticks(yt)
    ax4.set_yticklabels([MONTH_LABELS[MONTH_START_DOY.index(t)] for t in yt])

    fig.suptitle("Snowpack state and trends  (Theil-Sen slope, Mann-Kendall "
                 "test with autocorrelation correction)", fontweight="bold")
    fig.tight_layout()
    fs.save(fig, "06_snowpack_state", "snowpack traces and trends")


# ==========================================================================
# 7. Long-term flow regime
# ==========================================================================
def flow_regime(fs: FigureSet, ana: Analysis) -> None:
    cfg = ana.cfg
    fig, axes = plt.subplots(2, 2, figsize=(12, 8))
    ax1, ax2, ax3, ax4 = axes.ravel()
    df = ana.frame()
    comp = df[df.complete]

    _trend_panel(ax1, comp["wy"], comp["v_total_kaf"],
                 "Total annual runoff", "kaf", "#4C72B0")
    ax1.set_ylabel("Volume (kaf)")
    _trend_panel(ax2, comp["wy"], comp["v_seasonal_kaf"],
                 f"Seasonal runoff ({ana.window_label})", "kaf", "#2CA02C")
    ax2.set_ylabel("Volume (kaf)")

    # days above thresholds
    for thr, color in ((1000, "#2CA02C"), (3000, "#1A80E6"), (5000, "#E69919")):
        days = []
        for rec in ana.records:
            if not rec.complete:
                days.append(np.nan)
                continue
            ws, we = wy_bounds(rec.wy)
            q = ana.q.loc[ws:we].dropna()
            days.append(float((q >= thr).sum() / len(q) * 365) if len(q) else np.nan)
        days = np.asarray(days)
        m = np.isfinite(days) & df["complete"].to_numpy()
        ax3.scatter(df["wy"][m], days[m], s=22, color=color,
                    label=f">{thr//1000}k cfs")
        tr = trend(df["wy"][m], days[m], f">{thr}", "days")
        if np.isfinite(tr.slope):
            xs = np.array([df["wy"][m].min(), df["wy"][m].max()])
            ax3.plot(xs, tr.line(xs), "-" if tr.significant else "--",
                     color=color, lw=1.5)
    ax3.set_ylabel("Days per year (coverage-normalised)")
    ax3.set_title("High-flow days\nsolid = significant trend, dashed = not")
    ax3.set_xlabel("Water year")
    ax3.legend(fontsize=8)

    # decadal mean hydrographs -- nanmean, never nansum/n
    decades = [(1990, 1999), (2000, 2009), (2010, 2019),
               (2020, ana.current_wy - 1)]
    for (lo, hi), color in zip(decades, DECADE_COLORS):
        wys = [r.wy for r in ana.records
               if r.complete and lo <= r.wy <= hi]
        if not wys:
            continue
        sub = ana.daily_matrix(ana.q)[wys]
        with np.errstate(all="ignore"):
            mean = np.nanmean(sub.to_numpy(), axis=1)
            n = np.sum(np.isfinite(sub.to_numpy()), axis=1)
        mean = np.where(n >= max(2, len(wys) // 2), mean, np.nan)
        ax4.plot(sub.index, mean / 1000, color=color, lw=1.9,
                 label=f"{lo}s (n={len(wys)})")
    ax4.set_ylabel("Mean discharge (kcfs)")
    ax4.set_title("Mean hydrograph by decade\n(mean over observed years, "
                  "not a sum divided by all years)")
    _month_axis(ax4)
    ax4.legend(fontsize=8)

    fig.suptitle("Long-term flow regime  (complete water years only)",
                 fontweight="bold")
    fig.tight_layout()
    fs.save(fig, "07_flow_regime", "long-term trends")


# ==========================================================================
# 8. Water temperature and ecology
# ==========================================================================
def thermal(fs: FigureSet, ana: Analysis, th) -> None:
    if th is None:
        return
    cfg = ana.cfg
    fig, axes = plt.subplots(2, 2, figsize=(12, 8))
    ax1, ax2, ax3, ax4 = axes.ravel()
    d = th.daily.dropna(subset=["q_cfs", "dadmax7"])

    sc = ax1.scatter(d["q_cfs"] / 1000, d["dadmax7"], s=5, alpha=0.4,
                     c=d.index.month, cmap="twilight")
    plt.colorbar(sc, ax=ax1, label="Month")
    ax1.axhline(th.threshold_c, color="#D62728", ls="--", lw=1.4)
    ax1.annotate(f"{th.threshold_c} C  (WA 7-DADMax standard)",
                 (0.98, th.threshold_c), xycoords=("axes fraction", "data"),
                 xytext=(0, 5), textcoords="offset points", fontsize=8,
                 color="#D62728", va="bottom", ha="right")
    ax1.set_xlabel("Discharge (kcfs)")
    ax1.set_ylabel("7-DADMax water temperature (C)")
    ax1.set_title("Snowmelt is the river's air conditioning")

    bb = th.by_flow_bin.dropna(subset=["pct_over"])
    ax2.bar(bb["band"], bb["pct_over"], color="#E63333")
    for i, r in enumerate(bb.itertuples()):
        ax2.annotate(f"n={r.n_days}", (i, r.pct_over), ha="center",
                     va="bottom", fontsize=7.5, color="0.3")
    ax2.set_xlabel("Discharge band (cfs)")
    ax2.set_ylabel(f"% of days above {th.threshold_c} C")
    ax2.set_title("Thermal-stress risk by flow level\n"
                  "(7-DADMax, the actual regulatory statistic)")

    tf = th.frame()
    if not tf.empty:
        w = 0.4
        x = np.arange(len(tf))
        ax3.bar(x - w / 2, tf["days_over_mean"], w, label="daily mean > 17.5 C",
                color="#999999")
        ax3.bar(x + w / 2, tf["days_over_7dadmax"], w,
                label="7-DADMax > 17.5 C (the standard)", color="#D62728")
        ax3.set_xticks(x)
        ax3.set_xticklabels(tf["wy"], rotation=60, fontsize=7)
        ax3.set_ylabel("Days, Jun 15 - Sep 30")
        ax3.set_title("Using the daily mean understates exceedance of a\n"
                      "criterion defined on daily maxima")
        ax3.legend(fontsize=7.5)

    ax4.axis("off")
    lines = [
        "Is summer temperature a hydrologic or a meteorological variable?",
        "",
    ]
    if th.air_water_fit is not None:
        lines.append(f"  air temperature + log(flow):   skill "
                     f"{th.air_water_fit.loocv_r2:.2f}   (n={th.air_water_fit.n})")
    if th.swe_marginal is not None and th.air_water_fit is not None:
        gain = th.swe_marginal.loocv_r2 - th.air_water_fit.loocv_r2
        lines += [f"  ... plus the snowpack index:   skill "
                  f"{th.swe_marginal.loocv_r2:.2f}",
                  f"  snowpack's marginal contribution: {gain:+.3f}",
                  "",
                  "Snowpack adds little once air temperature and flow are in",
                  "the model. Summer maximum temperature is set by the weather;",
                  "snowpack governs WHEN the river leaves its cold, high-flow",
                  "regime, not how warm it eventually gets."]
    lines += ["",
              f"Water-temperature record: {th.n_complete} water years with good",
              "summer coverage. That is a short record; treat any regression",
              "on annual temperature statistics as indicative, not conclusive."]
    if th.note:
        lines += ["", "WARNING: " + th.note]
    ax4.text(0.0, 1.0, "\n".join(lines), va="top", fontsize=8.5, family="monospace")

    fig.suptitle("Water temperature and salmonid thermal stress",
                 fontweight="bold")
    fig.tight_layout()
    fs.save(fig, "08_water_temperature", "thermal stress")


# ==========================================================================
# 9. Data inventory / context
# ==========================================================================
def data_inventory(fs: FigureSet, ana: Analysis) -> None:
    cfg = ana.cfg
    fig, axes = plt.subplots(2, 2, figsize=(12, 8))
    ax1, ax2, ax3, ax4 = axes.ravel()
    df = ana.frame()

    # station-year availability - printed before anything is believed
    grid = np.zeros((len(ana.stations), len(df)))
    for i, st in enumerate(ana.stations):
        for j, rec in enumerate(ana.records):
            sy = rec.stations.get(st.site_id)
            grid[i, j] = 1.0 if (sy and sy.usable) else 0.0
    ax1.imshow(grid, aspect="auto", cmap="RdYlGn", vmin=0, vmax=1,
               interpolation="nearest")
    ax1.set_yticks(range(len(ana.stations)))
    ax1.set_yticklabels([f"{s.name} ({s.elev_ft:,}ft)" for s in ana.stations],
                        fontsize=8)
    step = max(1, len(df) // 12)
    ax1.set_xticks(range(0, len(df), step))
    ax1.set_xticklabels(df["wy"].to_numpy()[::step], rotation=60, fontsize=7)
    ax1.set_title("Station-year availability\ngreen = used in the composite")
    ax1.grid(False)

    # flow duration curves
    for rec in ana.records:
        ws, we = wy_bounds(rec.wy)
        q = ana.q.loc[ws:we].dropna().to_numpy()
        if q.size < 100:
            continue
        q = np.sort(q)[::-1]
        pct = np.arange(1, q.size + 1) / q.size * 100
        if rec.complete:
            ax2.plot(pct, q / 1000, color="0.75", lw=0.6, alpha=0.6)
        else:
            ax2.plot(pct, q / 1000, color=CURRENT_COLOR, lw=2,
                     label=f"WY{rec.wy} (partial)")
    ax2.set_yscale("log")
    ax2.set_xlabel("Exceedance (%)")
    ax2.set_ylabel("Discharge (kcfs)")
    ax2.set_title("Flow duration curves")
    ax2.legend(fontsize=8)

    # winter rain vs seasonal melt
    comp = df[df.complete]
    s = ax3.scatter(comp["v_oct_mar_kaf"], comp["v_seasonal_kaf"], s=40,
                    c=comp["wy"], cmap="viridis")
    plt.colorbar(s, ax=ax3, label="Water year")
    if ana.current_wy in df.index:
        cur = df.loc[ana.current_wy]
        ax3.scatter([cur["v_oct_mar_kaf"]], [cur["v_seasonal_kaf"]], s=160,
                    marker="*", color=CURRENT_COLOR, edgecolor="k", zorder=5,
                    label=f"WY{ana.current_wy} (partial)")
        ax3.legend(fontsize=8)
    ax3.set_xlabel("Oct-Mar volume (kaf)  -- winter rain")
    ax3.set_ylabel(f"Seasonal volume (kaf)  -- {ana.window_label}")
    ax3.set_title("Winter rain against spring melt")

    # seasonal volume bar chart with the current year flagged
    colors = [CURRENT_COLOR if not c else "#4C72B0" for c in df["complete"]]
    ax4.bar(df["wy"], df["v_seasonal_kaf"], color=colors)
    ax4.axhline(comp["v_seasonal_kaf"].median(), color="0.3", ls="--", lw=1.2,
                label=f"median {comp['v_seasonal_kaf'].median():,.0f} kaf")
    ax4.set_xlabel("Water year")
    ax4.set_ylabel("Seasonal volume (kaf)")
    ax4.set_title(f"Seasonal runoff by year ({ana.window_label})\n"
                  f"red = WY{ana.current_wy}, partial")
    ax4.legend(fontsize=8)

    fig.suptitle("Data inventory and hydrologic context", fontweight="bold")
    fig.tight_layout()
    fs.save(fig, "09_data_inventory", "coverage and context")


# ==========================================================================
def make_all(cfg: Config, ana: Analysis, fc, th, report, lead,
             season=None, season_skill=None, season_current=None
             ) -> FigureSet:
    fs = FigureSet(cfg)
    print("\n  Writing figures:")
    forecast_summary(fs, ana, fc)
    hindcast_verification(fs, ana, report, lead)
    snowpack_regression(fs, ana, fc)
    analog_detail(fs, ana, fc)
    kayaker_outlook(fs, ana, fc)
    if season is not None:
        season_end_validation(fs, ana, season, season_skill,
                              season_current or {})
    snowpack_state(fs, ana, fc)
    flow_regime(fs, ana)
    thermal(fs, ana, th)
    data_inventory(fs, ana)
    return fs


# ==========================================================================
# 10. Season-end validation: predicted vs actual last boatable day
# ==========================================================================
def season_end_validation(fs: FigureSet, ana: Analysis, validation,
                          skill_curve: pd.DataFrame, current: dict) -> None:
    """Predicted against actual last day of the recession above the threshold."""
    from . import season_end as SE

    if validation is None:
        return
    cfg = ana.cfg
    method = validation.best_method()
    tbl = validation.table(method).sort_values("wy")
    thr = cfg.runnable_cfs

    fig = plt.figure(figsize=(13, 9.5))
    gs = fig.add_gridspec(3, 2, height_ratios=[1.25, 1.5, 1.0], hspace=0.42,
                          wspace=0.22)
    ax_sc = fig.add_subplot(gs[0, 0])
    ax_sk = fig.add_subplot(gs[0, 1])
    ax_ts = fig.add_subplot(gs[1, :])
    ax_er = fig.add_subplot(gs[2, :])

    good = tbl[~tbl.censored & ~tbl.already_over]

    # -- predicted vs actual -------------------------------------------
    lo = float(min(good.actual_doy.min(), good.predicted_doy.min())) - 6
    hi = float(max(good.actual_doy.max(), good.predicted_doy.max())) + 6
    ax_sc.plot([lo, hi], [lo, hi], "k--", lw=1, zorder=1, label="perfect")
    ax_sc.fill_between([lo, hi], [lo - 14, hi - 14], [lo + 14, hi + 14],
                       color="#4C72B0", alpha=0.10, zorder=0,
                       label="within 2 weeks")
    ax_sc.scatter(good.actual_doy, good.predicted_doy, s=38, color="#4C72B0",
                  zorder=3)
    cens = tbl[tbl.censored]
    if len(cens):
        ax_sc.scatter(cens.actual_doy, cens.predicted_doy, s=60,
                      facecolors="none", edgecolors="0.4", zorder=3,
                      label="censored (never dropped)")
    cur_row = tbl[tbl.wy == ana.current_wy]
    if len(cur_row):
        ax_sc.scatter(cur_row.actual_doy, cur_row.predicted_doy, s=170,
                      marker="*", color=CURRENT_COLOR, edgecolor="k", zorder=5,
                      label=f"WY{ana.current_wy}")
    ticks = [t for t in MONTH_START_DOY if lo <= t <= hi]
    lab = [MONTH_LABELS[MONTH_START_DOY.index(t)] for t in ticks]
    ax_sc.set_xticks(ticks); ax_sc.set_xticklabels(lab)
    ax_sc.set_yticks(ticks); ax_sc.set_yticklabels(lab)
    ax_sc.set_xlim(lo, hi); ax_sc.set_ylim(lo, hi)
    ax_sc.set_xlabel("Actual last boatable day")
    ax_sc.set_ylabel("Predicted")
    sc = validation.scores()
    row = sc[sc.method == method].iloc[0] if len(sc) else None
    ax_sc.set_title(
        f"Issued {validation.label}, predictor: {method}\n"
        + (f"MAE {row['MAE_days']:.1f} days, "
           f"{row['within_2wk']:.0%} within 2 weeks (n={int(row['n'])})"
           if row is not None else ""))
    ax_sc.legend(fontsize=7, loc="upper left")

    # -- skill vs issue date -------------------------------------------
    if skill_curve is not None and not skill_curve.empty:
        piv = skill_curve.pivot_table(index="issue", columns="method",
                                      values="MAE_days", sort=False)
        order = [d for d in ["Mar 01", "Apr 01", "May 01", "May 15", "Jun 01",
                             "Jun 15", "Jul 01"] if d in piv.index]
        piv = piv.reindex(order)
        styles = {"climatology": ("#999999", "--"), "snowpack": ("#2CA02C", "-"),
                  "flow": ("#1F77B4", "-"), "swe_remaining": ("#9A19CC", "-"),
                  "snow+flow": ("#E68019", "-")}
        for col in piv.columns:
            c, ls = styles.get(col, (None, "-"))
            ax_sk.plot(range(len(piv)), piv[col], ls, marker="o", ms=4,
                       color=c, lw=1.8, label=col)
        ax_sk.set_xticks(range(len(piv)))
        ax_sk.set_xticklabels(piv.index, rotation=45, fontsize=8)
        ax_sk.set_ylabel("Mean absolute error (days)")
        ax_sk.set_xlabel("Forecast issue date")
        ax_sk.set_title("The answer sharpens through spring\n"
                        "(snow on the ground beats peak snowpack; "
                        "by July, current flow wins)")
        ax_sk.legend(fontsize=7)
        ax_sk.set_ylim(bottom=0)

    # -- year by year ---------------------------------------------------
    x = np.arange(len(tbl))
    ax_ts.vlines(x, tbl.lo_doy, tbl.hi_doy, color="#4C72B0", alpha=0.30, lw=5,
                 label=f"{cfg.prediction_interval:.0%} interval")
    ax_ts.plot(x, tbl.predicted_doy, "o", ms=5, color="#4C72B0",
               label="predicted")
    ax_ts.plot(x, tbl.actual_doy, "D", ms=5, color="#111111", label="actual")
    for i, r in enumerate(tbl.itertuples()):
        if r.censored:
            ax_ts.annotate("censored", (i, r.actual_doy),
                           textcoords="offset points", xytext=(9, -4),
                           ha="left", fontsize=6, color="0.35", rotation=90)
    cur_i = np.flatnonzero(tbl.wy.to_numpy() == ana.current_wy)
    if cur_i.size:
        ax_ts.plot(cur_i, tbl.actual_doy.to_numpy()[cur_i], "D", ms=8,
                   color=CURRENT_COLOR, zorder=5,
                   label=f"WY{ana.current_wy} actual")
    ax_ts.set_xticks(x)
    ax_ts.set_xticklabels(tbl.wy, rotation=60, fontsize=7)
    ticks = [t for t in MONTH_START_DOY if 260 <= t <= 375]
    ax_ts.set_yticks(ticks)
    ax_ts.set_yticklabels([MONTH_LABELS[MONTH_START_DOY.index(t)] for t in ticks])
    ax_ts.set_ylabel("Last day above 1,000 cfs")
    ax_ts.set_title(f"Predicted against actual end of the boating season, "
                    f"every year -- each forecast made without using that year")
    ax_ts.legend(fontsize=8, ncol=4, loc="lower left", framealpha=0.95)
    ax_ts.margins(y=0.16)

    # -- error distribution ---------------------------------------------
    err = good.error_days.dropna().to_numpy()
    ax_er.bar(x, tbl.error_days, color=["#999999" if c else "#4C72B0"
                                        for c in tbl.censored])
    if cur_i.size:
        for i in cur_i:
            ax_er.bar([i], [tbl.error_days.to_numpy()[i]], color=CURRENT_COLOR)
    for d, style in ((7, ":"), (14, "--")):
        for sign in (1, -1):
            ax_er.axhline(sign * d, color="0.5", ls=style, lw=0.9)
    ax_er.axhline(0, color="k", lw=1)
    ax_er.set_xticks(x)
    ax_er.set_xticklabels(tbl.wy, rotation=60, fontsize=7)
    ax_er.set_ylabel("Error (days)\nlate  <->  early")
    ax_er.set_title(f"Forecast error. Dotted +/-1 week, dashed +/-2 weeks. "
                    f"Median absolute error {np.median(np.abs(err)):.0f} days.")

    title = (f"When does the boating season end? Last day of the summer "
             f"recession at or above {thr:,.0f} cfs")
    if current.get("status") == "observed" and current.get("actual") is not None:
        title += (f"\nWY{ana.current_wy} actual: "
                  f"{current['actual']:%B %d}")
        if current.get("predicted") is not None:
            title += (f"   |   predicted {current['predicted']:%B %d}"
                      f"   ({current.get('error_days', 0):+d} days)")
    fig.suptitle(title, fontweight="bold", y=0.995)
    fs.save(fig, "10_season_end_validation",
            "predicted vs actual end of boating season")
