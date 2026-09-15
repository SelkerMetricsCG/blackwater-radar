"""Hindcast verification: does the forecast actually work?

The MATLAB analysis reported calibration r-squared and stopped there. That
says how well a line fits points it was drawn through, not whether the tool
would have told you the truth on a given day in a given year.

This module re-runs the whole forecast for a past date in each historical
water year, using only data available on that date, and compares the answer
to what the river actually did. It is the one figure that says whether to
trust the rest of the output.

Every year's forecast is fitted on the *other* years only, so the year being
forecast never contributes to its own model.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np
import pandas as pd

from .config import Config
from .core import Analysis, equivalent_date, volume_af, wy_bounds
from .fetch import RawData
from .stats import fit_ols, mae, rmse, skill_score


@dataclass
class HindcastResult:
    wy: int
    ref_date: pd.Timestamp
    observed_af: float
    predictions: dict[str, float]        # method -> predicted remaining volume
    intervals: dict[str, tuple[float, float]]
    q_at_ref_cfs: float
    snow_index: float


@dataclass
class BacktestReport:
    month: int
    day: int
    results: list[HindcastResult]
    methods: tuple[str, ...]

    def frame(self) -> pd.DataFrame:
        rows = []
        for r in self.results:
            row = {"wy": r.wy, "observed_kaf": r.observed_af / 1000.0,
                   "q_at_ref_cfs": r.q_at_ref_cfs, "snow_index": r.snow_index}
            for m in self.methods:
                row[f"{m}_kaf"] = r.predictions.get(m, np.nan) / 1000.0
                lo, hi = r.intervals.get(m, (np.nan, np.nan))
                row[f"{m}_in_pi"] = (lo <= r.observed_af <= hi
                                     if np.isfinite(lo) and np.isfinite(hi) else np.nan)
            rows.append(row)
        return pd.DataFrame(rows)

    def scores(self) -> pd.DataFrame:
        obs = np.array([r.observed_af for r in self.results], dtype=float)
        rows = []
        for m in self.methods:
            pred = np.array([r.predictions.get(m, np.nan) for r in self.results],
                            dtype=float)
            ok = np.isfinite(obs) & np.isfinite(pred)
            if ok.sum() < 3:
                continue
            cover = [r.intervals.get(m, (np.nan, np.nan)) for r in self.results]
            hits = [lo <= o <= hi for (lo, hi), o in zip(cover, obs)
                    if np.isfinite(lo) and np.isfinite(hi)]
            bias = float(np.mean(pred[ok] - obs[ok]))
            rows.append({
                "method": m,
                "n": int(ok.sum()),
                "skill": skill_score(obs[ok], pred[ok]),
                "RMSE_kaf": rmse(obs[ok], pred[ok]) / 1000.0,
                "MAE_kaf": mae(obs[ok], pred[ok]) / 1000.0,
                "bias_kaf": bias / 1000.0,
                "PI_coverage": float(np.mean(hits)) if hits else np.nan,
            })
        return pd.DataFrame(rows).sort_values("RMSE_kaf")

    @property
    def label(self) -> str:
        return pd.Timestamp(2001, self.month, self.day).strftime("%b %d")


def _snow_to_date(ana: Analysis, rec, ref: pd.Timestamp, index_key: str) -> float:
    """The snowpack index as it would have read on ``ref``.

    Peak SWE is a hindsight quantity: on March 1 nobody knows whether the
    peak has happened. An honest forecast issued on a date uses the largest
    SWE observed *so far*, which converges to the true peak as the season
    advances. This is what makes the lead-time skill curve meaningful rather
    than flattering.
    """
    ws, _ = wy_bounds(rec.wy)
    vals: list[float] = []
    for sid, sy in rec.stations.items():
        if not sy.usable:
            continue
        df = ana.raw.snotel.get(sid)
        if df is None or "swe_in" not in df.columns:
            continue
        swe = df.loc[ws:ref, "swe_in"].dropna()
        if swe.empty:
            continue
        smooth = swe.rolling(7, center=True, min_periods=4).mean().dropna()
        series = smooth if not smooth.empty else swe
        if index_key.startswith("apr1"):
            vals.append(float(series.iloc[-1]))
        else:
            vals.append(float(series.max()))
    return float(np.mean(vals)) if vals else np.nan


def _leave_one_out_predict(x: np.ndarray, y: np.ndarray, hold: int,
                           x0: float, level: float
                           ) -> tuple[float, float, float]:
    """Fit on every year but ``hold``, then predict the held-out year."""
    mask = np.ones(len(x), dtype=bool)
    mask[hold] = False
    fit = fit_ols(x[mask], y[mask], log_x=True, log_y=True)
    if fit is None or not np.isfinite(x0) or x0 <= 0:
        return np.nan, np.nan, np.nan
    p = fit.predict(x0, level)
    return p.value, p.lo, p.hi


def run_backtest(cfg: Config, raw: RawData, month: int, day: int
                 ) -> BacktestReport | None:
    """Hindcast remaining-season volume as of ``month``/``day`` in every year.

    Two methods are verified head to head:

    * ``recession``  - from the flow the river was running that day
    * ``snowpack``   - the seasonal-volume regression, minus volume already past

    Both are fitted leave-one-out, so no year informs its own forecast.
    """
    ana = Analysis(cfg, raw)
    comp = [r for r in ana.records if r.complete]
    if len(comp) < 12:
        return None

    wys, obs, q_at, snow, to_date = [], [], [], [], []
    for rec in comp:
        ws, we = wy_bounds(rec.wy)
        ref = pd.Timestamp(rec.wy, month, day)
        if not (ws < ref < we):
            continue
        q_wy = ana.q.loc[ws:we]
        window = q_wy.loc[ref - pd.Timedelta(days=6):ref].dropna()
        after = q_wy.loc[ref + pd.Timedelta(days=1):we].dropna()
        if len(window) < 5 or len(after) < 20:
            continue

        start = pd.Timestamp(rec.wy, 4, 1) if cfg.volume_window == "apr1" \
            else rec.composite_peak_date
        # Volume already past inside the accounting window. If the issue date
        # falls before the window opens, nothing has passed yet -- zero, not
        # missing.
        if start is None:
            v_past = np.nan
        elif ref <= start:
            v_past = 0.0
        else:
            v_past = volume_af(q_wy.loc[start:ref])

        # Snowpack known *on the issue date*, not the full-season peak. Peak
        # SWE is only knowable in hindsight, so using it for a January
        # forecast would be cheating and would overstate early-season skill.
        snow_val = _snow_to_date(ana, rec, ref, cfg.snow_index)

        wys.append(rec.wy)
        obs.append(volume_af(after))
        q_at.append(float(np.exp(np.log(window.clip(lower=1.0)).mean())))
        snow.append(snow_val)
        to_date.append(v_past)

    if len(wys) < 12:
        return None

    obs_a = np.asarray(obs, float)
    q_a = np.asarray(q_at, float)
    snow_a = np.asarray(snow, float)
    to_date_a = np.asarray(to_date, float)
    seasonal_a = obs_a + to_date_a          # the seasonal total, by construction

    level = cfg.prediction_interval
    results: list[HindcastResult] = []
    for i, wy in enumerate(wys):
        preds: dict[str, float] = {}
        ints: dict[str, tuple[float, float]] = {}

        v, lo, hi = _leave_one_out_predict(q_a, obs_a, i, q_a[i], level)
        preds["recession"] = v
        ints["recession"] = (lo, hi)

        v, lo, hi = _leave_one_out_predict(snow_a, seasonal_a, i, snow_a[i], level)
        preds["snowpack"] = v - to_date_a[i]
        ints["snowpack"] = (lo - to_date_a[i], hi - to_date_a[i])

        # Climatology: the median remaining volume across the other years.
        others = np.delete(obs_a, i)
        preds["climatology"] = float(np.median(others))
        ints["climatology"] = (float(np.percentile(others, 10, method="hazen")),
                               float(np.percentile(others, 90, method="hazen")))

        results.append(HindcastResult(
            wy=wy, ref_date=pd.Timestamp(wy, month, day), observed_af=obs_a[i],
            predictions=preds, intervals=ints,
            q_at_ref_cfs=q_a[i], snow_index=snow_a[i]))

    return BacktestReport(month=month, day=day, results=results,
                          methods=("recession", "snowpack", "climatology"))


def run_lead_time_curve(cfg: Config, raw: RawData,
                        dates: tuple[tuple[int, int], ...] = (
                            (1, 1), (2, 1), (3, 1), (4, 1), (5, 1),
                            (6, 1), (7, 1), (8, 1))
                        ) -> pd.DataFrame:
    """Forecast skill as a function of issue date.

    This is what an operational forecast centre publishes: skill is not one
    number, it is a curve that improves as the season reveals itself. A tool
    that reports a single r-squared hides the fact that its February answer
    and its July answer are not the same product.
    """
    rows = []
    for month, day in dates:
        rep = run_backtest(cfg, raw, month, day)
        if rep is None:
            continue
        sc = rep.scores()
        for _, r in sc.iterrows():
            rows.append({"issue_date": rep.label, "month": month,
                         **r.to_dict()})
    return pd.DataFrame(rows)
