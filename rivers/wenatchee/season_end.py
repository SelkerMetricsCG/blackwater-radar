"""When does the boating season end?

The question this answers is "what is the last day of the summer recession on
which the Wenatchee is still running 1,000 cfs or more" -- the date after
which the river is out for the year.

**The definition matters more than the model.** There are three candidate
definitions and they disagree by up to two months:

``last_any``
    The last day anywhere in May-Sep at or above the threshold. This is what
    the MATLAB version regressed on. It is wrong for this question: an
    isolated September rain bump counts as boating season. In WY1992 the
    recession ended on Jul 25 and this definition returns Sep 27, a 64-day
    error; WY2004 is off by 61 days and WY2020 by 52. Eight of 37 years are
    affected, and they are not a random eight -- they are the years with wet
    autumns, which is a systematic bias, not noise.

``sustained_start``
    The first day of a run of ``sustained_below_days`` consecutive days under
    the threshold.

``recession_end``  (what this module predicts)
    The last day at or above the threshold *before* that sustained drop. This
    is the last day you could actually have gone boating on the recession
    limb. It is ``sustained_start`` minus the length of the final dip, which
    is normally one day.

A handful of years never drop below the threshold before Sep 30. Those are
right-censored: the true season end is "Sep 30 or later" and is flagged, not
quietly treated as though the season ended on Sep 30.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .config import Config
from .core import Analysis, date_from_doy, doy_of_wy, wy_bounds
from .stats import Fit, fit_ols, mae, rmse, skill_score


# --------------------------------------------------------------------------
# The target
# --------------------------------------------------------------------------
@dataclass
class SeasonEnd:
    wy: int
    recession_end: pd.Timestamp | None    # last day >= threshold on the recession
    sustained_start: pd.Timestamp | None  # first day of the sustained drop
    last_any: pd.Timestamp | None         # last day >= threshold anywhere
    censored: bool                        # never dropped before Sep 30
    rain_bump_days: int                   # how far last_any overstates the end

    @property
    def doy(self) -> float:
        if self.recession_end is None:
            return np.nan
        return doy_of_wy(self.recession_end, self.wy)


def find_season_end(q: pd.Series, wy: int, threshold: float,
                    sustained_days: int, season_start_month: int = 5
                    ) -> SeasonEnd:
    """Locate the end of the summer recession in one water year."""
    ws, we = wy_bounds(wy)
    season = q.loc[pd.Timestamp(wy, season_start_month, 1):we].dropna()
    if season.empty:
        return SeasonEnd(wy, None, None, None, False, 0)

    above = season[season >= threshold]
    last_any = above.index.max() if len(above) else None

    below = (season < threshold).to_numpy()
    sustained = None
    if len(below) >= sustained_days:
        run = np.convolve(below.astype(int), np.ones(sustained_days, int), "valid")
        hits = np.flatnonzero(run == sustained_days)
        if hits.size:
            sustained = season.index[hits[0]]

    if sustained is None:
        # Never dropped for a sustained stretch before Sep 30: censored.
        return SeasonEnd(wy, last_any, None, last_any, censored=True,
                         rain_bump_days=0)

    pre = season.loc[:sustained]
    pre = pre[pre >= threshold]
    recession_end = pre.index.max() if len(pre) else None
    bump = ((last_any - recession_end).days
            if (last_any is not None and recession_end is not None) else 0)
    return SeasonEnd(wy, recession_end, sustained, last_any, False, bump)


def all_season_ends(ana: Analysis) -> dict[int, SeasonEnd]:
    cfg = ana.cfg
    return {r.wy: find_season_end(ana.q, r.wy, cfg.runnable_cfs,
                                  cfg.sustained_below_days)
            for r in ana.records}


# --------------------------------------------------------------------------
# Predictors available on an issue date
# --------------------------------------------------------------------------
def _snow_index_to_date(ana: Analysis, wy: int, issue: pd.Timestamp) -> float:
    """Snowpack index as it read on the issue date (largest SWE observed so far).

    Peak SWE is hindsight. On May 1 nobody is certain the peak has happened,
    so a forecast issued then may only use the maximum observed up to then.
    """
    ws, _ = wy_bounds(wy)
    rec = ana.by_wy(wy)
    if rec is None:
        return np.nan
    vals: list[float] = []
    for sid, sy in rec.stations.items():
        if not sy.usable:
            continue
        df = ana.raw.snotel.get(sid)
        if df is None or "swe_in" not in df.columns:
            continue
        swe = df.loc[ws:issue, "swe_in"].dropna()
        if swe.empty:
            continue
        smooth = swe.rolling(7, center=True, min_periods=4).mean().dropna()
        vals.append(float((smooth if not smooth.empty else swe).max()))
    return float(np.mean(vals)) if vals else np.nan


def _flow_at(ana: Analysis, wy: int, issue: pd.Timestamp, window: int = 7) -> float:
    """Geometric-mean discharge over the ``window`` days ending on the issue date."""
    sub = ana.q.loc[issue - pd.Timedelta(days=window - 1):issue].dropna()
    if len(sub) < max(3, window - 3):
        return np.nan
    return float(np.exp(np.log(sub.clip(lower=1.0)).mean()))


def _swe_remaining_at(ana: Analysis, wy: int, issue: pd.Timestamp) -> float:
    """Mean station SWE still on the ground on the issue date."""
    rec = ana.by_wy(wy)
    if rec is None:
        return np.nan
    vals: list[float] = []
    for sid, sy in rec.stations.items():
        if not sy.usable:
            continue
        df = ana.raw.snotel.get(sid)
        if df is None or "swe_in" not in df.columns:
            continue
        win = df.loc[issue - pd.Timedelta(days=3):issue + pd.Timedelta(days=3),
                     "swe_in"].dropna()
        if not win.empty:
            vals.append(float(win.iloc[len(win) // 2]))
    return float(np.mean(vals)) if vals else np.nan


# --------------------------------------------------------------------------
# Model
# --------------------------------------------------------------------------
PREDICTORS = ("climatology", "snowpack", "flow", "swe_remaining", "snow+flow")


@dataclass
class YearForecast:
    wy: int
    actual: pd.Timestamp | None
    actual_doy: float
    censored: bool
    already_over: bool                    # the season had ended by the issue date
    predictions: dict[str, float] = field(default_factory=dict)   # method -> DOY
    intervals: dict[str, tuple[float, float]] = field(default_factory=dict)
    snow_index: float = np.nan
    flow_cfs: float = np.nan
    swe_remaining: float = np.nan

    def error_days(self, method: str) -> float:
        p = self.predictions.get(method, np.nan)
        if not np.isfinite(p) or not np.isfinite(self.actual_doy):
            return np.nan
        return p - self.actual_doy


@dataclass
class SeasonEndValidation:
    """Leave-one-out validation of the season-end forecast at one issue date."""

    issue_month: int
    issue_day: int
    threshold: float
    years: list[YearForecast]
    fits: dict[str, Fit | None]
    n_censored: int
    n_already_over: int

    @property
    def label(self) -> str:
        return pd.Timestamp(2001, self.issue_month, self.issue_day).strftime("%b %d")

    def usable(self) -> list[YearForecast]:
        """Years that were a genuine forecast: not censored, not already over."""
        return [y for y in self.years
                if not y.censored and not y.already_over
                and np.isfinite(y.actual_doy)]

    def scores(self) -> pd.DataFrame:
        rows = []
        use = self.usable()
        actual = np.array([y.actual_doy for y in use], dtype=float)
        for m in PREDICTORS:
            pred = np.array([y.predictions.get(m, np.nan) for y in use], dtype=float)
            ok = np.isfinite(pred) & np.isfinite(actual)
            if ok.sum() < 5:
                continue
            hits, within7, within14 = [], 0, 0
            for y in use:
                p = y.predictions.get(m, np.nan)
                lo, hi = y.intervals.get(m, (np.nan, np.nan))
                if np.isfinite(lo) and np.isfinite(hi):
                    hits.append(lo <= y.actual_doy <= hi)
                e = abs(y.error_days(m))
                if np.isfinite(e):
                    within7 += int(e <= 7)
                    within14 += int(e <= 14)
            rows.append({
                "method": m,
                "n": int(ok.sum()),
                "skill": skill_score(actual[ok], pred[ok]),
                "RMSE_days": rmse(actual[ok], pred[ok]),
                "MAE_days": mae(actual[ok], pred[ok]),
                "bias_days": float(np.mean(pred[ok] - actual[ok])),
                "within_1wk": within7 / max(1, ok.sum()),
                "within_2wk": within14 / max(1, ok.sum()),
                "PI_coverage": float(np.mean(hits)) if hits else np.nan,
            })
        return pd.DataFrame(rows).sort_values("MAE_days")

    def best_method(self) -> str:
        sc = self.scores()
        if sc.empty:
            return "climatology"
        return str(sc.iloc[0]["method"])

    def table(self, method: str | None = None) -> pd.DataFrame:
        m = method or self.best_method()
        rows = []
        for y in self.years:
            p = y.predictions.get(m, np.nan)
            lo, hi = y.intervals.get(m, (np.nan, np.nan))
            rows.append({
                "wy": y.wy,
                "snow_index_in": y.snow_index,
                "swe_remaining_in": y.swe_remaining,
                "flow_at_issue_cfs": y.flow_cfs,
                "predicted_doy": p,
                "actual_doy": y.actual_doy,
                "error_days": y.error_days(m),
                "lo_doy": lo, "hi_doy": hi,
                "censored": y.censored,
                "already_over": y.already_over,
            })
        return pd.DataFrame(rows)


def _doy_to_date(doy: float, wy: int) -> pd.Timestamp | None:
    return date_from_doy(doy, wy)


def date_label(doy: float, wy: int = 2001) -> str:
    d = _doy_to_date(doy, wy)
    return d.strftime("%b %d") if d is not None else "n/a"


def validate(ana: Analysis, issue_month: int = 5, issue_day: int = 1
             ) -> SeasonEndValidation | None:
    """Hindcast the season-end date for every year, from one issue date.

    Each year is predicted by a model fitted on the *other* years only, using
    predictors as they read on the issue date. Years whose season had already
    ended by the issue date are excluded from the skill scores: on those the
    answer was observed, not forecast.
    """
    cfg = ana.cfg
    ends = all_season_ends(ana)

    wys, actual, snow, flow, swe_rem = [], [], [], [], []
    censored, already = [], []
    for rec in ana.records:
        se = ends.get(rec.wy)
        if se is None:
            continue
        issue = pd.Timestamp(rec.wy, issue_month, issue_day)
        # The current (partial) year is included only if the record reaches
        # the issue date; its actual may not exist yet.
        if issue > ana.ref_date and rec.wy == ana.current_wy:
            continue
        wys.append(rec.wy)
        actual.append(se.doy)
        censored.append(se.censored)
        already.append(bool(se.recession_end is not None
                            and se.recession_end <= issue))
        snow.append(_snow_index_to_date(ana, rec.wy, issue))
        flow.append(_flow_at(ana, rec.wy, issue))
        swe_rem.append(_swe_remaining_at(ana, rec.wy, issue))

    if len(wys) < 12:
        return None

    y = np.asarray(actual, float)
    x_snow = np.asarray(snow, float)
    x_flow = np.asarray(flow, float)
    x_swe = np.asarray(swe_rem, float)
    cens = np.asarray(censored, bool)
    over = np.asarray(already, bool)

    # Only clean years -- uncensored, and not already finished on the issue
    # date -- may inform the fit.
    trainable = np.isfinite(y) & ~cens & ~over

    level = cfg.prediction_interval
    fits: dict[str, Fit | None] = {}
    fits["snowpack"] = fit_ols(x_snow[trainable], y[trainable], "snowpack",
                               y_units=" days")
    fits["flow"] = fit_ols(x_flow[trainable], y[trainable], "flow at issue",
                           log_x=True, y_units=" days")
    fits["swe_remaining"] = fit_ols(x_swe[trainable], y[trainable], "SWE remaining",
                                    y_units=" days")

    out: list[YearForecast] = []
    for i, wy in enumerate(wys):
        yf = YearForecast(
            wy=wy, actual=_doy_to_date(y[i], wy), actual_doy=float(y[i]),
            censored=bool(cens[i]), already_over=bool(over[i]),
            snow_index=float(x_snow[i]), flow_cfs=float(x_flow[i]),
            swe_remaining=float(x_swe[i]))

        hold = trainable.copy()
        hold[i] = False        # leave this year out of its own model

        # Climatology: the median season end of the other years.
        others = y[hold]
        if others.size >= 5:
            yf.predictions["climatology"] = float(np.median(others))
            yf.intervals["climatology"] = (
                float(np.percentile(others, 10, method="hazen")),
                float(np.percentile(others, 90, method="hazen")))

        for name, xv in (("snowpack", x_snow), ("flow", x_flow),
                         ("swe_remaining", x_swe)):
            f = fit_ols(xv[hold], y[hold], name,
                        log_x=(name == "flow"))
            if f is None or not np.isfinite(xv[i]):
                continue
            p = f.predict(xv[i], level)
            yf.predictions[name] = p.value
            yf.intervals[name] = (p.lo, p.hi)

        # Two predictors together.
        both = hold & np.isfinite(x_snow) & np.isfinite(x_flow)
        if both.sum() >= 12 and np.isfinite(x_snow[i]) and np.isfinite(x_flow[i]):
            A = np.column_stack([np.ones(both.sum()), x_snow[both],
                                 np.log(np.clip(x_flow[both], 1, None))])
            coef, *_ = np.linalg.lstsq(A, y[both], rcond=None)
            resid = y[both] - A @ coef
            s = float(np.std(resid, ddof=3)) if both.sum() > 3 else np.nan
            pred = float(coef[0] + coef[1] * x_snow[i]
                         + coef[2] * np.log(max(x_flow[i], 1.0)))
            from scipy import stats as _st
            t = _st.t.ppf(0.5 + level / 2, max(1, both.sum() - 3))
            yf.predictions["snow+flow"] = pred
            yf.intervals["snow+flow"] = (pred - t * s, pred + t * s)

        out.append(yf)

    return SeasonEndValidation(
        issue_month=issue_month, issue_day=issue_day,
        threshold=cfg.runnable_cfs, years=out, fits=fits,
        n_censored=int(cens.sum()), n_already_over=int(over.sum()))


def skill_by_issue_date(ana: Analysis,
                        dates: tuple[tuple[int, int], ...] = (
                            (3, 1), (4, 1), (5, 1), (5, 15), (6, 1),
                            (6, 15), (7, 1))
                        ) -> pd.DataFrame:
    """How the season-end forecast sharpens as spring turns into summer."""
    rows = []
    for m, d in dates:
        v = validate(ana, m, d)
        if v is None:
            continue
        sc = v.scores()
        for _, r in sc.iterrows():
            rows.append({"issue": v.label, "month": m, "day": d,
                         "n_forecast": len(v.usable()),
                         "n_already_over": v.n_already_over, **r.to_dict()})
    return pd.DataFrame(rows)


def forecast_current(ana: Analysis, validation: SeasonEndValidation,
                     method: str | None = None) -> dict:
    """The season-end call for the current water year, as of the reference date."""
    cfg = ana.cfg
    wy = ana.current_wy
    ends = all_season_ends(ana)
    se = ends.get(wy)
    m = method or validation.best_method()

    result: dict = {"wy": wy, "method": m, "threshold": cfg.runnable_cfs}

    if se is not None and se.recession_end is not None and se.sustained_start is not None:
        result["status"] = "observed"
        result["actual"] = se.recession_end
        result["sustained_start"] = se.sustained_start
        result["rain_bump_days"] = se.rain_bump_days
        result["last_any"] = se.last_any

    yf = next((y for y in validation.years if y.wy == wy), None)
    if yf is not None and m in yf.predictions:
        lo, hi = yf.intervals.get(m, (np.nan, np.nan))
        result["predicted"] = _doy_to_date(yf.predictions[m], wy)
        result["predicted_lo"] = _doy_to_date(lo, wy)
        result["predicted_hi"] = _doy_to_date(hi, wy)
        result["snow_index"] = yf.snow_index
        result["flow_at_issue"] = yf.flow_cfs
        if "actual" in result and result["predicted"] is not None:
            result["error_days"] = (result["predicted"] - result["actual"]).days
        result.setdefault("status", "forecast")
    return result


# --------------------------------------------------------------------------
# How the call moved through the spring
# --------------------------------------------------------------------------
@dataclass
class SeasonEndTrack:
    """The season-end forecast re-issued on every date from ``start`` to ``end``.

    One :func:`validate` per issue date, so every entry is a genuine
    leave-one-out hindcast: the year being forecast never informs its own
    model, and each issue date sees only the data available on that date.
    ``best_method`` is the predictor with the lowest leave-one-out MAE on
    that date; ``years[wy]`` follows that predictor day by day, which is
    what the tool would actually have said had it been run on that date.
    """

    issue_dates: list[tuple[int, int]]           # (month, day)
    best_method: list[str]
    # wy -> {"pred": [doy...], "lo": [...], "hi": [...], "method": [...]}
    years: dict[int, dict[str, list]]
    # wy -> every predictor's track: {method: {"pred": [...], "lo": [...], "hi": [...]}}
    detail: dict[int, dict[str, dict[str, list]]]
    actual_doy: dict[int, float]
    censored: dict[int, bool]
    threshold: float


def track_by_issue_date(ana: Analysis, start: tuple[int, int] = (3, 1),
                        end: tuple[int, int] = (6, 15), step_days: int = 1,
                        detail_years: tuple[int, ...] | None = None
                        ) -> SeasonEndTrack | None:
    """Re-issue the season-end forecast on each date from ``start`` to ``end``.

    ``detail_years`` lists the water years for which every predictor's
    track is kept (default: the current year only); every year keeps the
    best-method track.
    """
    cfg = ana.cfg
    if detail_years is None:
        detail_years = (ana.current_wy,)
    d0 = pd.Timestamp(2001, *start)
    d1 = pd.Timestamp(2001, *end)
    if d1 < d0:
        return None
    dates = [(d.month, d.day) for d in pd.date_range(d0, d1, freq=f"{step_days}D")]

    ends = all_season_ends(ana)
    years: dict[int, dict[str, list]] = {}
    detail: dict[int, dict[str, dict[str, list]]] = {}
    best: list[str] = []
    n_valid = 0
    for m, d in dates:
        v = validate(ana, m, d)
        if v is None:
            best.append("")
            for wy in years:
                for k in ("pred", "lo", "hi"):
                    years[wy][k].append(np.nan)
                years[wy]["method"].append("")
            continue
        n_valid += 1
        bm = v.best_method()
        best.append(bm)
        seen: set[int] = set()
        for yf in v.years:
            wy = yf.wy
            seen.add(wy)
            y = years.setdefault(wy, {"pred": [], "lo": [], "hi": [], "method": []})
            # pad a year that first appears now (the current year once the
            # record reaches the issue date) so every list stays aligned
            while len(y["pred"]) < len(best) - 1:
                y["pred"].append(np.nan); y["lo"].append(np.nan)
                y["hi"].append(np.nan); y["method"].append("")
            p = yf.predictions.get(bm, np.nan)
            lo, hi = yf.intervals.get(bm, (np.nan, np.nan))
            y["pred"].append(p); y["lo"].append(lo); y["hi"].append(hi)
            y["method"].append(bm)
            if wy in detail_years:
                dd = detail.setdefault(wy, {})
                for meth in PREDICTORS:
                    t = dd.setdefault(meth, {"pred": [], "lo": [], "hi": []})
                    while len(t["pred"]) < len(best) - 1:
                        t["pred"].append(np.nan); t["lo"].append(np.nan); t["hi"].append(np.nan)
                    pp = yf.predictions.get(meth, np.nan)
                    l2, h2 = yf.intervals.get(meth, (np.nan, np.nan))
                    t["pred"].append(pp); t["lo"].append(l2); t["hi"].append(h2)
        # years that dropped out on this date (none in practice, but keep aligned)
        for wy, y in years.items():
            if wy not in seen:
                y["pred"].append(np.nan); y["lo"].append(np.nan)
                y["hi"].append(np.nan); y["method"].append("")
        for wy, dd in detail.items():
            if wy not in seen:
                for t in dd.values():
                    t["pred"].append(np.nan); t["lo"].append(np.nan); t["hi"].append(np.nan)

    if n_valid == 0:
        return None
    return SeasonEndTrack(
        issue_dates=dates, best_method=best, years=years, detail=detail,
        actual_doy={wy: (se.doy if se is not None else np.nan) for wy, se in ends.items()},
        censored={wy: bool(se.censored) for wy, se in ends.items()},
        threshold=cfg.runnable_cfs,
    )
