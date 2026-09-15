"""Forecast models for the remaining season.

Four independent estimates of "how much water is left", plus the diagnostics
needed to decide which to believe:

* :class:`SeasonalVolumeModel` - snowpack index -> seasonal runoff volume.
  Answers "how big is this water year". Fitted in log space so volumes stay
  positive and the variance stops scaling with the mean.
* :class:`RecessionModel` - current flow -> volume still to come. By midsummer
  this is far and away the strongest predictor, because the snowpack signal
  has already passed through the basin and what is left is recession. The
  MATLAB version computed current flow and used it only for a subtraction.
* :class:`SnowpackFractionModel` - snow still on the ground -> fraction of the
  season's volume still to come. Constrained so that a full snowpack implies
  the full season, which the unconstrained MATLAB version violated by 17
  percentage points.
* :class:`AnalogEnsemble` - similar years, rescaled and replayed. Gives the
  shape of the coming hydrograph and an empirical season-end distribution.

The estimates are reported side by side and are *not* averaged. The MATLAB
version averaged two of them, but both were affine functions of the same
fitted value, so the average shrank the estimate toward an arbitrary point
while presenting itself as agreement between independent methods.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .config import AF_PER_CFS_DAY, Config
from .core import (Analysis, YearRecord, af_per_basin_inch, basin_inches,
                   doy_of_wy, equivalent_date, volume_af, wy_bounds)
from .stats import Fit, MultiFit, Prediction, fit_multi, fit_ols, skill_score


# --------------------------------------------------------------------------
# Candidate snowpack indices
# --------------------------------------------------------------------------
@dataclass
class IndexCandidate:
    key: str
    label: str
    values: np.ndarray
    loocv_r2: float = np.nan
    r2: float = np.nan
    rmse: float = np.nan
    n: int = 0


@dataclass
class IndexComparison:
    """Candidate snowpack indices scored honestly, with the winner not chosen.

    The MATLAB version fitted six weighting schemes and reported the highest
    in-sample r-squared as if it had been specified in advance. The schemes
    are near-identical by construction -- all means over the same four
    stations -- so the differences between them are noise, and every
    downstream analysis inherited whichever one happened to win.

    Here the index is fixed in configuration (``cfg.snow_index``) rather than
    picked per run, the candidates are scored by leave-one-out skill rather
    than in-sample fit, and their correlation matrix is printed so the reader
    can see how much - or how little - separates them.
    """

    candidates: list[IndexCandidate]
    correlation: pd.DataFrame
    chosen_key: str
    chosen_label: str

    def table(self) -> pd.DataFrame:
        return pd.DataFrame([
            {"index": c.label, "n": c.n, "r2": c.r2,
             "LOOCV_r2": c.loocv_r2, "RMSE_kaf": c.rmse / 1000.0,
             "chosen": c.key == self.chosen_key}
            for c in self.candidates
        ]).sort_values("LOOCV_r2", ascending=False)

    @property
    def spread(self) -> float:
        vals = [c.loocv_r2 for c in self.candidates if np.isfinite(c.loocv_r2)]
        return (max(vals) - min(vals)) if len(vals) > 1 else np.nan


def build_index_candidates(ana: Analysis) -> IndexComparison:
    df = ana.frame()
    complete = df[df.complete]
    y = complete["v_seasonal_kaf"].to_numpy() * 1000.0

    stations = ana.stations
    by_id = {s.site_id: s for s in stations}
    high = [s.site_id for s in stations if s.elev_ft >= 4800]

    def col(sid: int) -> np.ndarray:
        return complete[f"swe_{sid}"].to_numpy()

    raw = {f"swe_{s.site_id}": col(s.site_id) for s in stations}
    cands: list[IndexCandidate] = [
        IndexCandidate("composite_pct", "Scale-free composite (% of median)",
                       complete["peak_swe_pct"].to_numpy()),
        IndexCandidate("composite_raw", "Raw mean of station peaks (inches)",
                       complete["peak_swe_in"].to_numpy()),
        IndexCandidate("apr1_pct", "Scale-free Apr-1 SWE",
                       complete["apr1_swe_pct"].to_numpy()),
        IndexCandidate("apr1_raw", "Raw mean Apr-1 SWE",
                       complete["apr1_swe_in"].to_numpy()),
    ]
    if high:
        cands.append(IndexCandidate(
            "high_only", "High stations only (>=4800 ft)",
            np.nanmean(np.column_stack([col(s) for s in high]), axis=1)))
    for s in stations:
        cands.append(IndexCandidate(
            f"only_{s.site_id}", f"{s.name} only ({s.elev_ft} ft)", col(s.site_id)))

    for c in cands:
        fit = fit_ols(c.values, y, c.label, log_x=True, log_y=True)
        if fit is not None:
            c.r2, c.loocv_r2, c.rmse, c.n = fit.r2, fit.loocv_r2, fit.rmse, fit.n

    corr = pd.DataFrame({c.label: c.values for c in cands}).corr()

    key_map = {"peak_swe_in": ("composite_raw", "Raw mean of station peaks (inches)"),
               "peak_swe_pct": ("composite_pct", "Scale-free composite (% of median)"),
               "apr1_swe_in": ("apr1_raw", "Raw mean Apr-1 SWE"),
               "apr1_swe_pct": ("apr1_pct", "Scale-free Apr-1 SWE")}
    key, label = key_map.get(ana.cfg.snow_index, key_map["peak_swe_in"])
    return IndexComparison(cands, corr, key, label)


# --------------------------------------------------------------------------
# 1. Seasonal volume from snowpack
# --------------------------------------------------------------------------
@dataclass
class SeasonalVolumeModel:
    """Snowpack index -> total seasonal runoff volume."""

    fit: Fit
    fit_with_precip: MultiFit | None
    fit_with_antecedent: MultiFit | None
    fit_swe_only_multi: MultiFit | None
    window_label: str
    prediction: Prediction | None
    index_label: str
    intercept_af: float                 # volume implied at the low end of the data
    intercept_basin_in: float
    years: np.ndarray = field(default_factory=lambda: np.array([]))
    observed: np.ndarray = field(default_factory=lambda: np.array([]))

    @property
    def added_value_precip(self) -> float:
        """LOOCV gain from adding winter precipitation to the snowpack index."""
        if self.fit_with_precip is None or self.fit_swe_only_multi is None:
            return np.nan
        return self.fit_with_precip.loocv_r2 - self.fit_swe_only_multi.loocv_r2


def fit_seasonal_volume(ana: Analysis, index_key: str | None = None
                        ) -> SeasonalVolumeModel | None:
    cfg = ana.cfg
    index_key = index_key or cfg.snow_index
    df = ana.frame()
    comp = df[df.complete]
    x = comp[index_key].to_numpy()
    y = comp["v_seasonal_kaf"].to_numpy() * 1000.0

    fit = fit_ols(x, y, "seasonal volume", log_x=True, log_y=True, y_units=" af")
    if fit is None:
        return None

    cur = ana.current
    x_now = (float(df.loc[cur.wy, index_key])
             if cur is not None and cur.wy in df.index else np.nan)
    pred = fit.predict(x_now, cfg.prediction_interval) if cur is not None else None

    # Does winter precipitation or antecedent wetness add real skill?
    # A pure-noise column raises in-sample r2 by about 1/(n-2), so the
    # comparison is made on leave-one-out skill, not r2.
    base = fit_multi(x.reshape(-1, 1), y, ("snow index",), "snow only", log_y=True)
    with_p = fit_multi(np.column_stack([x, comp["precip_in"].to_numpy()]), y,
                       ("snow index", "Oct-Mar precip"), "snow + precip", log_y=True)
    with_a = fit_multi(np.column_stack([x, comp["v_prev_oct_dec_kaf"].to_numpy()]), y,
                       ("snow index", "Oct-Dec runoff"), "snow + antecedent",
                       log_y=True)

    # The implied volume at the driest year on record, in basin inches.
    # A physically sensible model cannot send seasonal runoff to zero as
    # snowpack goes to zero: summer baseflow alone is a few hundred kaf.
    lo = fit.predict(float(np.nanmin(x)), cfg.prediction_interval)
    return SeasonalVolumeModel(
        fit=fit, fit_with_precip=with_p, fit_with_antecedent=with_a,
        fit_swe_only_multi=base, window_label=ana.window_label,
        prediction=pred, index_label=index_key,
        intercept_af=lo.value,
        intercept_basin_in=basin_inches(lo.value, cfg.drainage_mi2),
        years=comp["wy"].to_numpy(), observed=y,
    )


# --------------------------------------------------------------------------
# 2. Recession: current flow -> volume still to come
# --------------------------------------------------------------------------
@dataclass
class RecessionModel:
    """Volume remaining predicted from the flow the river is running now.

    Fitted across complete years at the *same calendar date*, so it answers
    exactly the question asked: given that the Wenatchee is running Q today,
    how much water has historically come down between today and Sep 30?

    Late in the season this dominates every snowpack-based estimate, because
    daily flow is strongly autocorrelated and the snowpack signal has already
    left the basin.
    """

    fit: Fit
    prediction: Prediction | None
    q_now_cfs: float
    ref_date: pd.Timestamp
    days_remaining: int


def fit_recession(ana: Analysis) -> RecessionModel | None:
    cfg = ana.cfg
    df = ana.frame()
    comp = df[df.complete]
    x = comp["q_at_ref_cfs"].to_numpy()
    y = comp["v_after_ref_kaf"].to_numpy() * 1000.0

    fit = fit_ols(x, y, "recession", log_x=True, log_y=True, y_units=" af")
    if fit is None:
        return None

    cur = ana.current
    q_now = getattr(cur, "q_mean_at_ref_cfs", np.nan) if cur is not None else np.nan
    pred = fit.predict(q_now, cfg.prediction_interval) if np.isfinite(q_now) else None
    sep30 = pd.Timestamp(ana.current_wy, 9, 30)
    return RecessionModel(fit=fit, prediction=pred, q_now_cfs=float(q_now),
                          ref_date=ana.ref_date,
                          days_remaining=max(0, (sep30 - ana.ref_date).days))


# --------------------------------------------------------------------------
# 3. Snowpack fraction -> volume fraction
# --------------------------------------------------------------------------
@dataclass
class SnowpackFractionModel:
    """Constrained model: vol_frac = b + (1 - b) * swe_frac.

    One parameter. ``b`` is the fraction of the season's volume that arrives
    without snowmelt -- baseflow and summer rain -- and the form guarantees
    that a full snowpack implies the full season's volume remaining.

    The MATLAB version fitted an unconstrained line whose coefficients summed
    to 0.83, meaning it claimed that at peak snowpack only 83% of the
    post-peak volume was still to come, when by definition it is 100%.
    """

    b: float                    # snow-independent fraction
    n: int
    r2: float
    rmse: float
    swe_frac_now: float
    vol_frac_pred: float
    volume_af: float
    lo_af: float
    hi_af: float
    degenerate: bool            # no usable spread in snowpack fraction
    note: str = ""
    swe_fracs: np.ndarray = field(default_factory=lambda: np.array([]))
    vol_fracs: np.ndarray = field(default_factory=lambda: np.array([]))


def fit_snowpack_fraction(ana: Analysis, seasonal_af: float
                          ) -> SnowpackFractionModel | None:
    cfg = ana.cfg
    df = ana.frame()
    comp = df[df.complete]

    sf = comp["swe_frac_at_ref"].to_numpy()
    vf = (comp["v_after_ref_kaf"].to_numpy() * 1000.0
          / np.where(comp["v_seasonal_kaf"].to_numpy() > 0,
                     comp["v_seasonal_kaf"].to_numpy() * 1000.0, np.nan))
    ok = np.isfinite(sf) & np.isfinite(vf)
    if ok.sum() < cfg.min_n_for_regression:
        return None
    sf, vf = sf[ok], vf[ok]

    cur = ana.current
    sf_now = getattr(cur, "swe_frac_at_ref", np.nan) if cur is not None else np.nan

    # Least squares on the constrained form:
    #   vol_frac - swe_frac = b * (1 - swe_frac)
    denom = float(np.sum((1.0 - sf) ** 2))
    b = float(np.sum((vf - sf) * (1.0 - sf)) / denom) if denom > 0 else np.nan
    b = float(np.clip(b, 0.0, 1.0))
    pred = b + (1.0 - b) * sf
    resid = vf - pred
    s = float(np.std(resid, ddof=1))

    # When the snowpack is gone in every year at this date, the predictor has
    # no variance left and the model degenerates to "the historical mean
    # remaining fraction". Say so rather than presenting a fitted slope.
    degenerate = bool(np.nanmax(sf) - np.nanmin(sf) < 0.05)
    note = ("snowpack is gone in every year at this date - this reduces to the "
            "historical mean remaining fraction, not a snowpack model"
            if degenerate else "")

    vf_now = b + (1.0 - b) * sf_now if np.isfinite(sf_now) else np.nan
    return SnowpackFractionModel(
        b=b, n=int(ok.sum()), r2=skill_score(vf, pred),
        rmse=float(np.sqrt(np.mean(resid ** 2))),
        swe_frac_now=float(sf_now), vol_frac_pred=float(vf_now),
        volume_af=float(vf_now * seasonal_af),
        lo_af=float(max(0.0, (vf_now - 1.28 * s) * seasonal_af)),
        hi_af=float((vf_now + 1.28 * s) * seasonal_af),
        degenerate=degenerate, note=note, swe_fracs=sf, vol_fracs=vf,
    )


# --------------------------------------------------------------------------
# 4. Analog ensemble
# --------------------------------------------------------------------------
@dataclass
class AnalogYear:
    wy: int
    scale: float
    scale_clipped: bool
    distance: float
    swe_index: float
    q_at_ref: float
    trace: pd.Series          # scaled daily flow, indexed by day-of-water-year
    volume_af: float          # remaining volume implied by this analog
    last_runnable_doy: float
    sustained_below_doy: float


@dataclass
class AnalogEnsemble:
    """Similar years, rescaled to today's flow and replayed forward.

    Differences from the MATLAB version, each of which changed the answer:

    * Analogs are chosen by nearest neighbour on *both* snowpack and current
      flow, not by a fixed +/-8 inch snowpack window. A fixed window at the
      edge of the record selects only wetter years, biasing the forecast high.
    * The scale factor is the ratio of matched multi-day geometric means, not
      of a single day to a 3-day mean. A single quiet or stormy day in the
      analog year previously rescaled its entire remaining hydrograph.
    * Quantiles are taken over the analogs' *volumes*, not over daily flows
      that are then summed. The sum of pointwise medians is a trace no year
      ever followed and its total is not the median total.
    * Season end comes from the analogs' actual dates as an empirical
      distribution, replacing a regression whose response was censored at
      both ends.
    """

    analogs: list[AnalogYear]
    n_candidates: int
    tolerance_used: float
    volume_median_af: float
    volume_lo_af: float
    volume_hi_af: float
    q_median: pd.Series             # DOY-indexed median forecast trace
    q_lo: pd.Series
    q_hi: pd.Series
    q_now_cfs: float
    ref_doy: float
    biased_note: str = ""

    @property
    def wys(self) -> list[int]:
        return [a.wy for a in self.analogs]

    def threshold_crossing(self, cfs: float) -> tuple[float, int] | None:
        """First forecast DOY below ``cfs``, and how many analogs agree."""
        below = self.q_median[self.q_median < cfs]
        if below.empty:
            return None
        doy = float(below.index[0])
        agree = sum(1 for a in self.analogs
                    if (a.trace < cfs).any() and float(a.trace[a.trace < cfs].index[0]) <= doy + 14)
        return doy, agree

    def season_end_quantiles(self, field_name: str = "last_runnable_doy"):
        vals = np.array([getattr(a, field_name) for a in self.analogs], dtype=float)
        vals = vals[np.isfinite(vals)]
        if vals.size < 3:
            return None
        return {
            "n": int(vals.size),
            "min": float(np.min(vals)),
            "p10": float(np.percentile(vals, 10, method="hazen")),
            "median": float(np.median(vals)),
            "p90": float(np.percentile(vals, 90, method="hazen")),
            "max": float(np.max(vals)),
            "values": vals,
        }


def build_analogs(ana: Analysis) -> AnalogEnsemble | None:
    cfg = ana.cfg
    cur = ana.current
    if cur is None:
        return None

    df = ana.frame()
    comp = df[df.complete]
    if comp.empty:
        return None

    idx = cfg.snow_index
    swe_now = float(df.loc[cur.wy, idx]) if cur.wy in df.index else np.nan
    q_now = cur.q_mean_at_ref_cfs
    if not np.isfinite(swe_now):
        return None

    swe_hist = comp[idx].to_numpy()
    q_hist = comp["q_at_ref_cfs"].to_numpy()

    # Standardise both matching variables so neither dominates by unit scale.
    sd_swe = float(np.nanstd(swe_hist)) or 1.0
    log_q_hist = np.log(np.clip(q_hist, 1.0, None))
    sd_q = float(np.nanstd(log_q_hist)) or 1.0

    z_swe = (swe_hist - swe_now) / sd_swe
    if np.isfinite(q_now) and q_now > 0:
        z_q = (log_q_hist - np.log(q_now)) / sd_q
        dist = np.sqrt(z_swe ** 2 + z_q ** 2)
    else:
        dist = np.abs(z_swe)

    k = int(np.clip(cfg.analog_max_count, cfg.analog_min_count, len(comp)))
    order = np.argsort(np.where(np.isfinite(dist), dist, np.inf))[:k]

    ref_doy = ana.ref_doy
    sep30_doy = doy_of_wy(pd.Timestamp(ana.current_wy, 9, 30), ana.current_wy)
    horizon = np.arange(ref_doy + 1, sep30_doy + 1)
    if horizon.size == 0:
        return None

    w = cfg.analog_scale_window_days
    lo_clip, hi_clip = cfg.analog_scale_clip

    analogs: list[AnalogYear] = []
    for pos in order:
        wy = int(comp["wy"].to_numpy()[pos])
        rec = ana.by_wy(wy)
        if rec is None:
            continue
        ws, we = wy_bounds(wy)
        ref_h = equivalent_date(ana.ref_date, wy)
        q_wy = ana.q.loc[ws:we]

        # Matched-window geometric means on both sides of the ratio.
        hist_win = q_wy.loc[ref_h - pd.Timedelta(days=w - 1):ref_h].dropna()
        if len(hist_win) < max(3, w - 3) or not np.isfinite(q_now) or q_now <= 0:
            continue
        hist_mean = float(np.exp(np.log(hist_win.clip(lower=1.0)).mean()))
        scale = q_now / hist_mean
        clipped = not (lo_clip <= scale <= hi_clip)
        scale = float(np.clip(scale, lo_clip, hi_clip))

        fwd = q_wy.loc[ref_h + pd.Timedelta(days=1):we].dropna()
        if len(fwd) < 15:
            continue
        trace = pd.Series(fwd.to_numpy() * scale,
                          index=np.round(doy_of_wy(fwd.index, wy)).astype(int))
        trace = trace[~trace.index.duplicated(keep="first")]

        analogs.append(AnalogYear(
            wy=wy, scale=scale, scale_clipped=clipped, distance=float(dist[pos]),
            swe_index=float(swe_hist[pos]), q_at_ref=float(q_hist[pos]),
            trace=trace, volume_af=float(trace.sum() * AF_PER_CFS_DAY),
            last_runnable_doy=float(comp["last_runnable_doy"].to_numpy()[pos]),
            sustained_below_doy=float(comp["sustained_below_doy"].to_numpy()[pos]),
        ))

    if len(analogs) < 3:
        return None

    # Quantiles over analog VOLUMES, not over daily flows that are then summed.
    vols = np.array([a.volume_af for a in analogs])
    v_med = float(np.median(vols))
    v_lo = float(np.percentile(vols, 10, method="hazen"))
    v_hi = float(np.percentile(vols, 90, method="hazen"))

    grid = np.arange(int(ref_doy) + 1, int(sep30_doy) + 1)
    mat = pd.DataFrame({a.wy: a.trace for a in analogs}).reindex(grid)
    with np.errstate(all="ignore"):
        q_med = pd.Series(np.nanmedian(mat.to_numpy(), axis=1), index=grid)
        q_lo = pd.Series(np.nanpercentile(mat.to_numpy(), 10, axis=1, method="hazen"),
                         index=grid)
        q_hi = pd.Series(np.nanpercentile(mat.to_numpy(), 90, axis=1, method="hazen"),
                         index=grid)

    # If the neighbours are systematically snowier than this year, say so
    # rather than letting the bias pass as an unqualified forecast.
    note = ""
    med_swe = float(np.median([a.swe_index for a in analogs]))
    if med_swe > swe_now * 1.10:
        note = (f"analog years average {med_swe / swe_now - 1:+.0%} more snowpack "
                f"than {ana.current_wy}; the analog volume is likely biased high")
    elif med_swe < swe_now * 0.90:
        note = (f"analog years average {med_swe / swe_now - 1:+.0%} less snowpack "
                f"than {ana.current_wy}; the analog volume is likely biased low")

    return AnalogEnsemble(
        analogs=analogs, n_candidates=len(comp),
        tolerance_used=float(np.max([a.distance for a in analogs])),
        volume_median_af=v_med, volume_lo_af=v_lo, volume_hi_af=v_hi,
        q_median=q_med, q_lo=q_lo, q_hi=q_hi, q_now_cfs=float(q_now),
        ref_doy=ref_doy, biased_note=note,
    )


# --------------------------------------------------------------------------
# 5. Physical bounds
# --------------------------------------------------------------------------
@dataclass
class MassBalance:
    """A physical sanity check on the remaining-volume forecasts.

    Runoff is expressed in inches over the 1,301 sq mi drainage, so it can be
    compared directly with the snowpack that has to supply it. One basin inch
    is 69,387 acre-feet. The MATLAB version declared the drainage area and
    then never used it, which is why a forecast of 798 kaf remaining could
    stand alongside a snowpack that could not deliver it.
    """

    af_per_inch: float
    swe_remaining_in: float          # mean station SWE still on the ground
    historical_min_af: float         # smallest remaining volume on record
    historical_median_af: float
    historical_max_af: float
    forecasts: dict[str, float]

    def verdict(self, name: str) -> str:
        v = self.forecasts.get(name)
        if v is None or not np.isfinite(v):
            return "no estimate"
        if v > self.historical_max_af * 1.15:
            return "ABOVE anything in the record"
        if v < self.historical_min_af * 0.85:
            return "BELOW anything in the record"
        return "within the historical range"

    def as_basin_inches(self, af: float) -> float:
        return af / self.af_per_inch


def mass_balance(ana: Analysis, forecasts: dict[str, float]) -> MassBalance:
    cfg = ana.cfg
    df = ana.frame()
    comp = df[df.complete]
    rem = comp["v_after_ref_kaf"].to_numpy() * 1000.0
    rem = rem[np.isfinite(rem)]
    cur = ana.current
    return MassBalance(
        af_per_inch=af_per_basin_inch(cfg.drainage_mi2),
        swe_remaining_in=getattr(cur, "swe_at_ref_in", np.nan),
        historical_min_af=float(np.min(rem)) if rem.size else np.nan,
        historical_median_af=float(np.median(rem)) if rem.size else np.nan,
        historical_max_af=float(np.max(rem)) if rem.size else np.nan,
        forecasts=forecasts,
    )


# --------------------------------------------------------------------------
# Assembled forecast
# --------------------------------------------------------------------------
@dataclass
class Forecast:
    ana: Analysis
    index: IndexComparison
    seasonal: SeasonalVolumeModel | None
    recession: RecessionModel | None
    snowfrac: SnowpackFractionModel | None
    analogs: AnalogEnsemble | None
    balance: MassBalance | None
    v_observed_to_date_af: float
    skill_at_issue: "pd.DataFrame | None"
    primary_name: str
    primary_af: float
    primary_lo_af: float
    primary_hi_af: float
    primary_basis: str = ""
    consistency_warning: str = ""

    def _hindcast_skill(self, key: str) -> float:
        """Verified skill for this estimand, not the parent model's fit skill.

        The snowpack regression can fit seasonal totals with a leave-one-out
        skill of 0.90 while its *remaining-volume* estimate is worse than
        useless in late summer. Reporting the fit skill beside the remaining
        volume would advertise the wrong number, so the hindcast score for the
        actual quantity is used whenever it exists.
        """
        if self.skill_at_issue is None or self.skill_at_issue.empty:
            return np.nan
        row = self.skill_at_issue[self.skill_at_issue["method"] == key]
        return float(row.iloc[0]["skill"]) if len(row) else np.nan

    def estimates(self) -> list[dict]:
        """Every remaining-volume estimate, side by side and never averaged."""
        out: list[dict] = []
        if self.recession is not None and self.recession.prediction is not None:
            p = self.recession.prediction
            out.append({"method": "Recession (current flow)", "af": p.value,
                        "lo": p.lo, "hi": p.hi,
                        "skill": self._hindcast_skill("recession"),
                        "note": "predicts remaining volume directly"})
        if self.analogs is not None:
            out.append({"method": f"Analog years (n={len(self.analogs.analogs)})",
                        "af": self.analogs.volume_median_af,
                        "lo": self.analogs.volume_lo_af,
                        "hi": self.analogs.volume_hi_af,
                        "skill": np.nan, "note": self.analogs.biased_note})
        if self.seasonal is not None and self.seasonal.prediction is not None:
            p = self.seasonal.prediction
            v = p.value - self.v_observed_to_date_af
            out.append({"method": "Snowpack regression (total minus observed)",
                        "af": v,
                        "lo": p.lo - self.v_observed_to_date_af,
                        "hi": p.hi - self.v_observed_to_date_af,
                        "skill": self._hindcast_skill("snowpack"),
                        "note": (f"the seasonal-total fit has LOOCV skill "
                                 f"{self.seasonal.fit.loocv_r2:.2f}, but that is "
                                 f"skill at predicting the whole season, not "
                                 f"what is left of it")})
        if self.snowfrac is not None and np.isfinite(self.snowfrac.volume_af):
            out.append({"method": "Snowpack fraction remaining",
                        "af": self.snowfrac.volume_af,
                        "lo": self.snowfrac.lo_af, "hi": self.snowfrac.hi_af,
                        "skill": self.snowfrac.r2,
                        "note": self.snowfrac.note})
        return out


def build_forecast(ana: Analysis,
                   skill_at_issue: pd.DataFrame | None = None) -> Forecast:
    cfg = ana.cfg
    index = build_index_candidates(ana)
    seasonal = fit_seasonal_volume(ana)
    recession = fit_recession(ana)

    cur = ana.current
    v_to_date = getattr(cur, "v_to_ref_af", np.nan) if cur is not None else np.nan

    seasonal_af = (seasonal.prediction.value
                   if seasonal is not None and seasonal.prediction is not None
                   else np.nan)
    snowfrac = (fit_snowpack_fraction(ana, seasonal_af)
                if np.isfinite(seasonal_af) else None)
    analogs = build_analogs(ana)

    # Which method leads is decided by hindcast skill at THIS issue date, not
    # by a fixed preference. The two models cross over: the snowpack
    # regression is far better in spring, when the snow is on the ground and
    # has not yet run off, and the recession model is far better by midsummer,
    # when the snow is gone and what remains is baseflow. A tool that always
    # trusted one of them would be wrong for half the year.
    options: dict[str, tuple[float, float, float]] = {}
    if recession is not None and recession.prediction is not None:
        p = recession.prediction
        options["recession"] = (p.value, p.lo, p.hi)
    if seasonal is not None and seasonal.prediction is not None:
        p = seasonal.prediction
        options["snowpack"] = (p.value - v_to_date, p.lo - v_to_date,
                               p.hi - v_to_date)
    if analogs is not None:
        options["analog"] = (analogs.volume_median_af, analogs.volume_lo_af,
                             analogs.volume_hi_af)

    pretty = {"recession": "Recession (current flow)",
              "snowpack": "Snowpack regression",
              "analog": "Analog years"}

    primary_name, primary, lo, hi = "none", np.nan, np.nan, np.nan
    basis = ""
    ranked: list[str] = []
    if skill_at_issue is not None and not skill_at_issue.empty:
        ranked = [m for m in skill_at_issue.sort_values("RMSE_kaf")["method"]
                  if m in options]
    for m in ranked + ["recession", "snowpack", "analog"]:
        if m in options and np.isfinite(options[m][0]):
            primary_name = pretty.get(m, m)
            primary, lo, hi = options[m]
            if ranked and m == ranked[0] and skill_at_issue is not None:
                row = skill_at_issue[skill_at_issue["method"] == m].iloc[0]
                basis = (f"lowest hindcast error at this issue date "
                         f"(RMSE {row['RMSE_kaf']:.0f} kaf, skill {row['skill']:.2f} "
                         f"over {int(row['n'])} past years)")
            break

    # Do not clamp a negative remainder to zero. If the snowpack model says
    # the season's water has already passed the gauge, that is a diagnosis
    # that the model has failed for this year, and it should be reported.
    warning = ""
    if (seasonal is not None and seasonal.prediction is not None
            and np.isfinite(v_to_date) and seasonal.prediction.value > 0):
        frac = v_to_date / seasonal.prediction.value
        if frac > 1.0:
            warning = (
                f"observed volume to date is {frac:.0%} of the snowpack model's "
                f"predicted seasonal total - the snowpack model is inconsistent "
                f"with this year's observed flow and its remaining-volume "
                f"estimate is not usable")

    fc_map: dict[str, float] = {}
    if recession is not None and recession.prediction is not None:
        fc_map["recession"] = recession.prediction.value
    if analogs is not None:
        fc_map["analog"] = analogs.volume_median_af
    if seasonal is not None and seasonal.prediction is not None:
        fc_map["snowpack"] = seasonal.prediction.value - v_to_date

    return Forecast(
        ana=ana, index=index, seasonal=seasonal, recession=recession,
        snowfrac=snowfrac, analogs=analogs,
        balance=mass_balance(ana, fc_map),
        v_observed_to_date_af=float(v_to_date),
        skill_at_issue=skill_at_issue,
        primary_name=primary_name, primary_af=float(primary),
        primary_lo_af=float(lo), primary_hi_af=float(hi),
        primary_basis=basis, consistency_warning=warning,
    )
