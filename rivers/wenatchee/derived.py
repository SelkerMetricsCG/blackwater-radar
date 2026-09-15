"""Water temperature and melt dynamics.

Two analyses that the MATLAB version got mechanically wrong:

**Thermal stress.** Washington's standard for salmonid spawning, rearing and
migration (WAC 173-201A-200) is 17.5 C as a *7-day average of the daily
maximum* -- 7-DADMax. The MATLAB version compared the daily *mean* to 17.5,
which runs 1.5-3 C cooler in a river this size in summer, so it systematically
undercounted exceedances of a criterion it was not actually evaluating. Here
the daily maximum is fetched separately, the true 7-DADMax is computed, and
both statistics are reported side by side and labelled.

**Melt energy.** Degree-days here are computed from the daily mean of Tmax and
Tmin rather than Tmax alone (which roughly doubles shoulder-season degree-day
totals), missing days stay missing instead of silently counting as zero melt,
and the multi-station composite is a proper column-wise mean on a shared date
index with the contributing station count recorded, rather than a series that
switches between one-station and two-station values partway through.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .config import Config
from .core import Analysis, doy_of_wy, water_year, wy_bounds
from .stats import Fit, MultiFit, fit_multi, fit_ols


# --------------------------------------------------------------------------
# Water temperature
# --------------------------------------------------------------------------
@dataclass
class ThermalYear:
    wy: int
    n_days_observed: int
    coverage: float                    # fraction of Jun 15 - Sep 30 observed
    days_over_mean: int                # daily mean above threshold
    days_over_7dadmax: int             # 7-DADMax above threshold (the standard)
    frac_over_7dadmax: float           # normalised by coverage
    summer_max_c: float
    summer_mean_c: float
    first_exceedance_doy: float


@dataclass
class ThermalAnalysis:
    years: list[ThermalYear]
    daily: pd.DataFrame                # date-indexed: q, t_mean, t_max, dadmax
    have_daily_max: bool
    threshold_c: float
    by_flow_bin: pd.DataFrame          # exceedance risk vs discharge
    air_water_fit: MultiFit | None     # T = f(air T, log Q)
    swe_marginal: MultiFit | None      # ...plus snowpack, to test if it adds
    n_complete: int
    note: str = ""

    @property
    def usable(self) -> bool:
        return self.n_complete >= 5

    def frame(self) -> pd.DataFrame:
        return pd.DataFrame([vars(y) for y in self.years])


def build_thermal(ana: Analysis, water_temp_max: pd.Series | None = None
                  ) -> ThermalAnalysis | None:
    cfg = ana.cfg
    t_mean = ana.raw.water_temp_c
    if t_mean.empty:
        return None

    t_max = water_temp_max if (water_temp_max is not None
                               and not water_temp_max.empty) else None
    have_max = t_max is not None

    idx = pd.date_range(t_mean.index.min(), t_mean.index.max(), freq="D")
    daily = pd.DataFrame(index=idx)
    daily["q_cfs"] = ana.q.reindex(idx)
    daily["t_mean"] = t_mean.reindex(idx)
    daily["t_max"] = t_max.reindex(idx) if have_max else np.nan

    # 7-DADMax: rolling 7-day mean of the daily maximum. Requires at least 5
    # of the 7 days present so a gap cannot fabricate a low value.
    basis = daily["t_max"] if have_max else daily["t_mean"]
    daily["dadmax7"] = basis.rolling(7, min_periods=5).mean()

    thr = cfg.salmon_thresh_c
    years: list[ThermalYear] = []
    for rec in ana.records:
        ws, we = wy_bounds(rec.wy)
        sub = daily.loc[ws:we]
        summer = sub.loc[pd.Timestamp(rec.wy, 6, 15):pd.Timestamp(rec.wy, 9, 30)]
        n_obs = int(summer["t_mean"].notna().sum())
        span = max(1, len(summer))
        coverage = n_obs / span
        # A year observed for only part of the summer scores a low exceedance
        # count purely from missing data, so counts are reported alongside the
        # coverage that produced them and normalised where used.
        if n_obs < 20:
            continue
        d_mean = int((summer["t_mean"] > thr).sum())
        d_dad = int((summer["dadmax7"] > thr).sum())
        exceed = summer.index[summer["dadmax7"] > thr]
        years.append(ThermalYear(
            wy=rec.wy, n_days_observed=n_obs, coverage=float(coverage),
            days_over_mean=d_mean, days_over_7dadmax=d_dad,
            frac_over_7dadmax=float(d_dad / max(n_obs, 1)),
            summer_max_c=float(summer["t_mean"].max()),
            summer_mean_c=float(summer["t_mean"].mean()),
            first_exceedance_doy=(float(doy_of_wy(exceed[0], rec.wy))
                                  if len(exceed) else np.nan),
        ))

    # Exceedance risk by flow band, with the sample size behind each bar.
    rows = []
    edges = [0, 500, 1000, 2000, 3000, 5000, np.inf]
    labels = ["<500", "500-1k", "1-2k", "2-3k", "3-5k", ">5k"]
    both = daily.dropna(subset=["q_cfs", "dadmax7"])
    for lo, hi, lab in zip(edges[:-1], edges[1:], labels):
        m = (both["q_cfs"] >= lo) & (both["q_cfs"] < hi)
        n = int(m.sum())
        rows.append({
            "band": lab, "n_days": n,
            "pct_over": (float((both.loc[m, "dadmax7"] > thr).mean() * 100)
                         if n >= 30 else np.nan),
            "median_t": float(both.loc[m, "dadmax7"].median()) if n >= 30 else np.nan,
        })
    by_bin = pd.DataFrame(rows)

    # Is summer water temperature a hydrologic variable or a meteorological
    # one? Fit air temperature and discharge first, then test whether the
    # snowpack index adds anything once those are in the model. The MATLAB
    # version regressed water temperature on snowpack alone -- a textbook
    # omitted-variable setup that attributed a weather signal to snow.
    air = _composite_air_temp(ana)
    air_fit = swe_fit = None
    if air is not None:
        jj = daily.loc[daily.index.month.isin([7, 8, 9])].copy()
        jj["air"] = air.reindex(jj.index)
        jj["wy"] = water_year(jj.index)
        idxmap = ana.frame()[cfg.snow_index]
        jj["snow"] = jj["wy"].map(idxmap)
        jj = jj.dropna(subset=["dadmax7", "air", "q_cfs"])
        if len(jj) >= 200:
            X2 = np.column_stack([jj["air"].to_numpy(),
                                  np.log(jj["q_cfs"].clip(lower=1).to_numpy())])
            air_fit = fit_multi(X2, jj["dadmax7"].to_numpy(),
                                ("air temp (F)", "log Q"), "air + flow")
            jj3 = jj.dropna(subset=["snow"])
            if len(jj3) >= 200:
                X3 = np.column_stack([jj3["air"].to_numpy(),
                                      np.log(jj3["q_cfs"].clip(lower=1).to_numpy()),
                                      jj3["snow"].to_numpy()])
                swe_fit = fit_multi(X3, jj3["dadmax7"].to_numpy(),
                                    ("air temp (F)", "log Q", "snow index"),
                                    "air + flow + snow")

    note = ("" if have_max else
            "daily-maximum water temperature is unavailable at this gauge; "
            "7-DADMax is approximated from daily means and UNDERSTATES the "
            "true value by roughly 1.5-3 C")
    n_complete = sum(1 for y in years if y.coverage > 0.8)
    return ThermalAnalysis(years=years, daily=daily, have_daily_max=have_max,
                           threshold_c=thr, by_flow_bin=by_bin,
                           air_water_fit=air_fit, swe_marginal=swe_fit,
                           n_complete=n_complete, note=note)


def _composite_air_temp(ana: Analysis) -> pd.Series | None:
    """Mean daily air temperature across the temperature stations.

    Built by reindexing every station onto one shared daily axis and taking a
    column-wise mean, so the composite has a single, stable definition. The
    MATLAB version averaged only the dates two stations had in common and left
    single-station dates as raw values, so the series silently changed meaning
    partway through each year.
    """
    cfg = ana.cfg
    frames = []
    for sid in cfg.temp_station_ids:
        df = ana.raw.snotel.get(sid)
        if df is None or "tmax_f" not in df.columns:
            continue
        tmax, tmin = df["tmax_f"], df.get("tmin_f")
        # Daily mean of max and min, not max alone: using Tmax roughly doubles
        # shoulder-season degree-days.
        mean = (tmax + tmin) / 2.0 if tmin is not None else tmax
        frames.append(mean.rename(sid))
    if not frames:
        return None
    wide = pd.concat(frames, axis=1)
    return wide.mean(axis=1, skipna=True)


def station_count(ana: Analysis) -> pd.Series:
    frames = []
    for sid in ana.cfg.temp_station_ids:
        df = ana.raw.snotel.get(sid)
        if df is not None and "tmax_f" in df.columns:
            frames.append(df["tmax_f"].notna().rename(sid))
    if not frames:
        return pd.Series(dtype=float)
    return pd.concat(frames, axis=1).sum(axis=1)


# --------------------------------------------------------------------------
# Melt dynamics
# --------------------------------------------------------------------------
@dataclass
class MeltAnalysis:
    degree_days: pd.Series             # daily degree-days, NaN where unobserved
    n_stations: pd.Series
    cumulative: dict[int, pd.Series]   # wy -> cumulative degree-days from Apr 1
    depletion: pd.DataFrame            # wy x doy basin-mean SWE
    melt_out_estimate: dict            # observed-depletion projection
    note: str = ""


def build_melt(ana: Analysis) -> MeltAnalysis | None:
    cfg = ana.cfg
    air = _composite_air_temp(ana)
    if air is None:
        return None
    counts = station_count(ana)

    # Missing temperature stays missing. Treating a gap as zero degree-days
    # silently understates cumulative melt energy for the rest of the season.
    dd = (air - cfg.base_temp_f).clip(lower=0.0)
    dd[air.isna()] = np.nan

    cumulative: dict[int, pd.Series] = {}
    for rec in ana.records:
        apr1 = pd.Timestamp(rec.wy, 4, 1)
        _, we = wy_bounds(rec.wy)
        sub = dd.loc[apr1:we]
        if sub.notna().sum() < 30:
            continue
        # Gaps interpolated only if short; longer gaps break the accumulation.
        filled = sub.interpolate(limit=3, limit_area="inside")
        cumulative[rec.wy] = filled.cumsum()

    # Basin-mean SWE by day of water year, for depletion-based melt-out.
    swe_cols = {}
    for rec in ana.records:
        ws, we = wy_bounds(rec.wy)
        vals = []
        for sid, sy in rec.stations.items():
            if not sy.usable:
                continue
            df = ana.raw.snotel.get(sid)
            if df is None or "swe_in" not in df.columns:
                continue
            s = df.loc[ws:we, "swe_in"]
            s.index = np.round(doy_of_wy(s.index, rec.wy)).astype(int)
            vals.append(s[~s.index.duplicated(keep="first")])
        if vals:
            swe_cols[rec.wy] = pd.concat(vals, axis=1).mean(axis=1, skipna=True)
    depletion = pd.DataFrame(swe_cols).reindex(range(1, 366))

    # Melt-out from the observed depletion rate, not from extrapolating a
    # heatwave's degree-day rate through September. The MATLAB version took a
    # 7-day degree-day rate and projected it forward for months, when the
    # rate falls sharply as the season ends.
    est: dict = {}
    cur = ana.current
    if cur is not None and cur.wy in depletion.columns:
        s = depletion[cur.wy].dropna()
        if not s.empty:
            now = float(s.iloc[-1])
            recent = s.loc[max(s.index.min(), s.index.max() - 20):]
            rate = float(-np.polyfit(recent.index, recent.to_numpy(), 1)[0]) \
                if len(recent) >= 10 else np.nan
            est = {"swe_now_in": now, "depletion_in_per_day": rate,
                   "days_to_melt_out": (now / rate if rate and rate > 0.01
                                        else np.nan)}

    return MeltAnalysis(degree_days=dd, n_stations=counts, cumulative=cumulative,
                        depletion=depletion, melt_out_estimate=est)
