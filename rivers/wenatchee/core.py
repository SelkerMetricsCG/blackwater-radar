"""Water-year bookkeeping and per-year hydrologic accounting.

This is the layer that turns raw daily series into one record per water year.
Everything downstream (regressions, forecasts, figures) reads these records
and never touches the raw series again.

Three things here are deliberately different from the MATLAB original, and
each fixes a defect that silently changed reported numbers:

1. **Leap years.** MATLAB compared years by ``date - wy_start + 1``. A water
   year containing Feb 29 has 366 days, so from March onward every leap year
   was offset one day against every non-leap year. Here, "the same day in a
   different year" is defined by *calendar month and day*
   (:func:`equivalent_date`), and the day-of-water-year used for plotting is
   normalised to a common 365-day axis (:func:`doy_of_wy`), so month
   boundaries line up exactly.

2. **"Complete" means the water year has ended.** A day count alone marks the
   current year complete once it passes the threshold in late summer, which
   would let a partial year into the regressions it is supposed to be
   excluded from.

3. **The composite snowpack index is scale-free.** Lyman Lake peaks at 35-98
   inches and Blewett Pass at 3-26, so an unweighted mean of raw inches is
   roughly half Lyman by construction, and it shifts level whenever a station
   is missing. The normalised composite averages each station's
   percent-of-its-own-median instead, which is what NRCS does operationally
   and is robust to a dropped station.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .config import AF_PER_CFS_DAY, Config, Station
from .fetch import RawData


# --------------------------------------------------------------------------
# Water-year calendar helpers
# --------------------------------------------------------------------------
def water_year(ts: pd.Timestamp | pd.DatetimeIndex):
    """Water year (Oct 1 - Sep 30) containing ``ts``."""
    if isinstance(ts, pd.DatetimeIndex):
        return ts.year + (ts.month >= 10).astype(int)
    return ts.year + (1 if ts.month >= 10 else 0)


def wy_bounds(wy: int) -> tuple[pd.Timestamp, pd.Timestamp]:
    """First and last day of water year ``wy``."""
    return pd.Timestamp(wy - 1, 10, 1), pd.Timestamp(wy, 9, 30)


def is_leap_wy(wy: int) -> bool:
    """True if water year ``wy`` contains Feb 29."""
    return bool(pd.Timestamp(wy, 1, 1).is_leap_year)


# Day-of-water-year of Mar 1 on the common axis. Everything from here on is
# shifted back by a day in leap water years so the axis stays 365 days long.
MAR1_DOY = 152


def doy_of_wy(dates: pd.DatetimeIndex | pd.Timestamp, wy: int):
    """Day of water year on a common 365-day axis.

    In a leap water year, Feb 29 collapses onto Feb 28's day number so that
    March onward lines up across leap and non-leap years and the month tick
    positions in ``MONTH_START_DOY`` are exact in every year.

    :func:`date_from_doy` is the inverse and must stay consistent with this;
    both are pinned by the self-tests.
    """
    start = pd.Timestamp(wy - 1, 10, 1)
    if isinstance(dates, pd.DatetimeIndex):
        doy = np.asarray((dates - start).days, dtype=float) + 1.0
        if is_leap_wy(wy):
            doy[np.asarray(dates >= pd.Timestamp(wy, 2, 29))] -= 1.0
        return doy
    doy = float((dates - start).days) + 1.0
    if is_leap_wy(wy) and dates >= pd.Timestamp(wy, 2, 29):
        doy -= 1.0
    return doy


def date_from_doy(doy: float, wy: int) -> pd.Timestamp | None:
    """Calendar date for a day of water year -- the inverse of :func:`doy_of_wy`.

    Without the leap-year term here, every date displayed for a leap water
    year comes out one day early. That is nine of the thirty-seven years in
    this record.
    """
    if doy is None or not np.isfinite(doy):
        return None
    d = int(round(float(doy)))
    if is_leap_wy(wy) and d >= MAR1_DOY:
        d += 1                      # step back over Feb 29
    return pd.Timestamp(wy - 1, 10, 1) + pd.Timedelta(days=d - 1)


def equivalent_date(ref: pd.Timestamp, target_wy: int) -> pd.Timestamp:
    """The same calendar month/day as ``ref``, inside water year ``target_wy``.

    Leap-safe: Feb 29 maps to Feb 28 in a non-leap year.
    """
    cal_year = target_wy - 1 if ref.month >= 10 else target_wy
    month, day = ref.month, ref.day
    if month == 2 and day == 29 and not pd.Timestamp(cal_year, 1, 1).is_leap_year:
        day = 28
    return pd.Timestamp(cal_year, month, day)


def basin_inches(volume_af: float, drainage_mi2: float) -> float:
    """Convert a runoff volume to inches over the drainage area.

    The single most useful sanity check in the whole analysis: one inch over
    the Wenatchee's 1,301 sq mi is 69,387 acre-feet, so a predicted seasonal
    volume and a measured snowpack depth can finally be compared directly.
    The MATLAB version defined the drainage area and then never used it.
    """
    return volume_af / (drainage_mi2 * 640.0 / 12.0)


def af_per_basin_inch(drainage_mi2: float) -> float:
    return drainage_mi2 * 640.0 / 12.0


def volume_af(q_cfs: pd.Series) -> float:
    """Total volume in acre-feet from a series of daily mean discharge."""
    if q_cfs.empty:
        return float("nan")
    return float(q_cfs.sum() * AF_PER_CFS_DAY)


# --------------------------------------------------------------------------
# Per-station, per-year snowpack summary
# --------------------------------------------------------------------------
@dataclass
class StationYear:
    site_id: int
    name: str
    elev_ft: int
    peak_swe_in: float = float("nan")
    peak_date: pd.Timestamp | None = None
    apr1_swe_in: float = float("nan")
    swe_at_ref_in: float = float("nan")      # SWE on the reference date
    precip_to_apr1_in: float = float("nan")  # Oct 1 -> Apr 1 accumulation
    n_days: int = 0
    usable: bool = False                     # passed the coverage screen


@dataclass
class YearRecord:
    """One water year of hydrology."""

    wy: int
    complete: bool                     # the water year has ended, with full data
    n_days_q: int

    # Snowpack
    stations: dict[int, StationYear] = field(default_factory=dict)
    composite_peak_swe_in: float = float("nan")     # raw mean of station peaks
    composite_peak_swe_pct: float = float("nan")    # scale-free index (% of median)
    composite_apr1_swe_in: float = float("nan")
    composite_apr1_swe_pct: float = float("nan")
    composite_peak_date: pd.Timestamp | None = None
    composite_precip_in: float = float("nan")
    n_stations_used: int = 0

    # Volumes (acre-feet)
    v_total_af: float = float("nan")        # Oct 1 - Sep 30
    v_apr_sep_af: float = float("nan")      # Apr 1 - Sep 30  (fixed window)
    v_post_peak_af: float = float("nan")    # composite peak date - Sep 30
    v_oct_mar_af: float = float("nan")      # Oct 1 - Mar 31
    v_to_ref_af: float = float("nan")       # window start -> reference date
    v_after_ref_af: float = float("nan")    # reference date+1 -> Sep 30
    v_prev_oct_dec_af: float = float("nan")  # antecedent wetness proxy
    q_mean_at_ref_cfs: float = float("nan")  # 7-day mean flow at the reference date

    # Flow statistics
    peak_q_cfs: float = float("nan")
    peak_q_date: pd.Timestamp | None = None
    centroid_doy: float = float("nan")
    last_runnable_date: pd.Timestamp | None = None
    sustained_below_date: pd.Timestamp | None = None
    days_in_bin: np.ndarray | None = None          # full WY
    days_in_bin_after_ref: np.ndarray | None = None

    # Snowpack state at the reference date
    swe_frac_at_ref: float = float("nan")   # basin sum(now)/sum(peak)
    swe_at_ref_in: float = float("nan")     # mean station SWE still on the ground

    @property
    def label(self) -> str:
        return f"WY{self.wy}" + ("" if self.complete else " (partial)")


# --------------------------------------------------------------------------
# Builder
# --------------------------------------------------------------------------
class Analysis:
    """Per-year records plus the shared context every model needs."""

    def __init__(self, cfg: Config, raw: RawData):
        self.cfg = cfg
        self.raw = raw
        # Reindex onto a gap-free daily axis. USGS omits rows for ice-affected
        # and missing days, so without this a "7 consecutive days below 1000
        # cfs" test counts 7 consecutive *samples*, which a gap can satisfy
        # spuriously, and a "3-day mean" can silently span a week.
        self.q = raw.q_cfs.reindex(
            pd.date_range(raw.q_cfs.index.min(), raw.q_cfs.index.max(), freq="D"))
        self.n_missing_days = int(self.q.isna().sum())
        self.stations = raw.stations

        # The reference date drives every "as of" number. Normally it is the
        # most recent day with observed flow; --as-of pins it to a past date
        # so the forecast can be hindcast against what actually happened.
        self.ref_date: pd.Timestamp = raw.last_flow_date
        self.is_hindcast = False
        if cfg.as_of is not None:
            as_of = pd.Timestamp(cfg.as_of).normalize()
            if as_of > raw.last_flow_date:
                raise ValueError(
                    f"--as-of {as_of:%Y-%m-%d} is after the last observed flow "
                    f"({raw.last_flow_date:%Y-%m-%d})")
            self.ref_date = as_of
            self.is_hindcast = as_of < raw.last_flow_date
            # A hindcast must not see the future: truncate every input series.
            self.q = self.q.loc[:as_of]
            raw = RawData(
                q_cfs=self.q,
                water_temp_c=raw.water_temp_c.loc[:as_of],
                water_temp_max_c=raw.water_temp_max_c.loc[:as_of],
                snotel={k: v.loc[:as_of] for k, v in raw.snotel.items()},
                stations=raw.stations,
                fetched_at=raw.fetched_at,
            )
            self.raw = raw

        self.current_wy: int = cfg.end_wy or int(water_year(self.ref_date))
        self.today = pd.Timestamp.today().normalize()

        self.records: list[YearRecord] = []
        self._build()

    # -- construction ----------------------------------------------------
    def _station_year(self, st: Station, wy: int) -> StationYear:
        cfg = self.cfg
        ws, we = wy_bounds(wy)
        sy = StationYear(st.site_id, st.name, st.elev_ft)

        df = self.raw.snotel.get(st.site_id)
        if df is None:
            return sy
        swe = df.loc[ws:we, "swe_in"].dropna() if "swe_in" in df else pd.Series(dtype=float)
        sy.n_days = len(swe)
        if swe.empty:
            return sy

        # Peak SWE from a 7-day smoothed series inside a plausible window.
        # A raw daily max over a snow pillow is an extreme-value statistic:
        # a single-day sensor spike, or a December rain-on-snow bump at a
        # low station, becomes "peak SWE" and drags the peak date months
        # early. Smoothing and windowing removes both failure modes.
        search = swe.loc[pd.Timestamp(wy - 1, 12, 1):pd.Timestamp(wy, 6, 30)]
        smooth = (search.rolling(7, center=True, min_periods=4).mean()
                  if len(search) >= 10 else search)
        if smooth.dropna().empty:
            smooth = swe
        smooth = smooth.dropna()
        sy.peak_swe_in = float(smooth.max())
        # Use the midpoint of the plateau within 2% of the peak, so a flat
        # melting-out pack does not report its first day as the peak date.
        plateau = smooth.index[smooth >= smooth.max() * 0.98]
        sy.peak_date = pd.Timestamp(np.mean([d.value for d in plateau])).normalize()

        # Coverage screen: enough days, and still reporting past Apr 1, so a
        # station that dropped out in February cannot fake a low peak.
        last_doy = doy_of_wy(swe.index.max(), wy)
        # A station-year is usable only with enough real observations, a
        # record reaching past Apr 1, and a peak large enough to be a
        # snowpack rather than a sensor artefact. Without the last test a
        # dead sensor reporting zeros contributes peak SWE = 0 on Oct 1,
        # which drags the composite peak date months early and inflates the
        # post-peak volume to the whole water year.
        sy.usable = (sy.n_days >= cfg.min_swe_days_per_wy
                     and last_doy >= cfg.swe_required_through_doy
                     and sy.peak_swe_in >= cfg.min_peak_swe_in)

        apr1 = pd.Timestamp(wy, 4, 1)
        if apr1 in swe.index:
            sy.apr1_swe_in = float(swe.loc[apr1])
        elif not swe.loc[:apr1].empty:
            sy.apr1_swe_in = float(swe.loc[:apr1].iloc[-1])

        ref = equivalent_date(self.ref_date, wy)
        window = swe.loc[ref - pd.Timedelta(days=3): ref + pd.Timedelta(days=3)]
        if not window.empty:
            nearest = window.index[np.argmin(np.abs((window.index - ref).days))]
            sy.swe_at_ref_in = float(window.loc[nearest])

        # SNOTEL precipitation is a running water-year accumulation, so the
        # Oct 1 -> Apr 1 total is the value on Apr 1 minus the value on Oct 1.
        if "prec_in" in df.columns:
            prec = df.loc[ws:we, "prec_in"].dropna()
            if not prec.empty:
                head = prec.loc[:apr1]
                if not head.empty:
                    sy.precip_to_apr1_in = float(head.iloc[-1] - head.iloc[0])
        return sy

    def _build(self) -> None:
        cfg = self.cfg
        wy_all = sorted(set(int(w) for w in water_year(self.q.index)))
        wy_all = [w for w in wy_all if cfg.start_wy <= w <= self.current_wy]

        bins = np.asarray(cfg.flow_bin_edges, dtype=float)

        for wy in wy_all:
            ws, we = wy_bounds(wy)
            q_wy = self.q.loc[ws:we].dropna()
            n_days = len(q_wy)

            # A water year is complete only once it has actually ended.
            ended = self.ref_date >= we
            complete = ended and n_days >= cfg.min_days_full_wy
            if not complete and int(q_wy.notna().sum()) < cfg.min_days_current_wy:
                continue

            rec = YearRecord(wy=wy, complete=complete,
                             n_days_q=int(q_wy.notna().sum()))

            # -- snowpack ------------------------------------------------
            for st in self.stations:
                rec.stations[st.site_id] = self._station_year(st, wy)
            usable = [sy for sy in rec.stations.values() if sy.usable]
            rec.n_stations_used = len(usable)
            if usable:
                rec.composite_peak_swe_in = float(np.mean([s.peak_swe_in for s in usable]))
                apr1_vals = [s.apr1_swe_in for s in usable if np.isfinite(s.apr1_swe_in)]
                if apr1_vals:
                    rec.composite_apr1_swe_in = float(np.mean(apr1_vals))
                peak_dates = [s.peak_date for s in usable if s.peak_date is not None]
                if peak_dates:
                    rec.composite_peak_date = pd.Timestamp(
                        np.mean([d.value for d in peak_dates])).normalize()
                prec_vals = [s.precip_to_apr1_in for s in usable
                             if np.isfinite(s.precip_to_apr1_in)]
                if prec_vals:
                    rec.composite_precip_in = float(np.mean(prec_vals))

                # Snowpack remaining, as a depth-weighted basin fraction:
                # sum(now) / sum(peak), NOT the mean of per-station ratios.
                # With Lyman at 50 in and Blewett at 6, mean-of-ratios weights
                # a station holding 6 inches of water equally with one holding
                # 50, and in late season the two definitions differ ~3x.
                pk = [s.peak_swe_in for s in usable
                      if np.isfinite(s.swe_at_ref_in) and s.peak_swe_in > 0]
                nw = [s.swe_at_ref_in for s in usable
                      if np.isfinite(s.swe_at_ref_in) and s.peak_swe_in > 0]
                if pk and sum(pk) > 0:
                    rec.swe_frac_at_ref = float(sum(nw) / sum(pk))
                    rec.swe_at_ref_in = float(np.mean(nw))

            # -- volumes -------------------------------------------------
            rec.v_total_af = volume_af(q_wy)
            apr1, mar31 = pd.Timestamp(wy, 4, 1), pd.Timestamp(wy, 3, 31)
            rec.v_apr_sep_af = volume_af(q_wy.loc[apr1:we])
            rec.v_oct_mar_af = volume_af(q_wy.loc[ws:mar31])
            if rec.composite_peak_date is not None:
                rec.v_post_peak_af = volume_af(q_wy.loc[rec.composite_peak_date:we])

            # -- flow statistics -----------------------------------------
            if not q_wy.empty:
                rec.peak_q_cfs = float(q_wy.max())
                rec.peak_q_date = q_wy.idxmax()
                doy = doy_of_wy(q_wy.index, wy)
                total = float(q_wy.sum())
                if total > 0:
                    rec.centroid_doy = float(np.sum(doy * q_wy.to_numpy()) / total)
                rec.days_in_bin = np.histogram(q_wy.to_numpy(), bins=bins)[0]

                season = q_wy.loc[pd.Timestamp(wy, 5, 1):we]
                rec.last_runnable_date, rec.sustained_below_date = \
                    self._season_end(season, wy)

            self.records.append(rec)

        self._normalise_composites()
        self._reference_window_volumes()

    def _season_end(self, season: pd.Series, wy: int
                    ) -> tuple[pd.Timestamp | None, pd.Timestamp | None]:
        """Last day above the runnable threshold, and the first sustained drop."""
        cfg = self.cfg
        if season.empty:
            return None, None
        above = season[season >= cfg.runnable_cfs]
        last_runnable = above.index.max() if not above.empty else None

        # First day beginning a full run of `sustained_below_days` under the
        # threshold. Requires the whole window to be observed.
        below = (season < cfg.runnable_cfs).to_numpy()
        n = cfg.sustained_below_days
        sustained = None
        if len(below) >= n:
            # rolling all-True over an n-day window
            run = np.convolve(below.astype(int), np.ones(n, dtype=int), mode="valid")
            hits = np.flatnonzero(run == n)
            if hits.size:
                sustained = season.index[hits[0]]
        return last_runnable, sustained

    def _normalise_composites(self) -> None:
        """Scale-free snowpack index: mean of each station's percent-of-median.

        Computed on complete years only, then rescaled so the index reads in
        inches on the same scale as the raw composite.
        """
        complete = [r for r in self.records if r.complete]
        if not complete:
            return

        medians: dict[int, float] = {}
        for st in self.stations:
            vals = [r.stations[st.site_id].peak_swe_in for r in complete
                    if r.stations[st.site_id].usable]
            vals = [v for v in vals if np.isfinite(v) and v > 0]
            if vals:
                medians[st.site_id] = float(np.median(vals))

        apr_medians: dict[int, float] = {}
        for st in self.stations:
            vals = [r.stations[st.site_id].apr1_swe_in for r in complete
                    if r.stations[st.site_id].usable]
            vals = [v for v in vals if np.isfinite(v) and v > 0]
            if vals:
                apr_medians[st.site_id] = float(np.median(vals))

        if not medians:
            return
        scale = float(np.mean(list(medians.values())))
        apr_scale = float(np.mean(list(apr_medians.values()))) if apr_medians else np.nan

        for rec in self.records:
            pcts, apr_pcts = [], []
            for sid, sy in rec.stations.items():
                if not sy.usable:
                    continue
                med = medians.get(sid)
                if med and np.isfinite(sy.peak_swe_in):
                    pcts.append(sy.peak_swe_in / med)
                amed = apr_medians.get(sid)
                if amed and np.isfinite(sy.apr1_swe_in):
                    apr_pcts.append(sy.apr1_swe_in / amed)
            if pcts:
                rec.composite_peak_swe_pct = float(np.mean(pcts) * scale)
            if apr_pcts and np.isfinite(apr_scale):
                rec.composite_apr1_swe_pct = float(np.mean(apr_pcts) * apr_scale)

    def _reference_window_volumes(self) -> None:
        """Volume already past, and still to come, relative to the reference date.

        For each year this splits the accounting window at the calendar
        equivalent of the reference date, so the current year's "how much is
        left" question has a matched historical answer.
        """
        cfg = self.cfg
        bins = np.asarray(cfg.flow_bin_edges, dtype=float)

        for rec in self.records:
            ws, we = wy_bounds(rec.wy)
            start = self.window_start(rec)
            if start is None:
                continue
            ref = equivalent_date(self.ref_date, rec.wy)
            q_wy = self.q.loc[ws:we]

            rec.v_to_ref_af = volume_af(q_wy.loc[start:ref])
            after = q_wy.loc[ref + pd.Timedelta(days=1):we]
            rec.v_after_ref_af = volume_af(after)
            if not after.empty:
                rec.days_in_bin_after_ref = np.histogram(after.to_numpy(), bins=bins)[0]

            # Antecedent wetness: Oct-Dec runoff of this water year, a proxy
            # for soil moisture and groundwater storage going into the melt
            # season. NRCS operational forecasts carry a predictor like this
            # and the MATLAB version had none.
            rec.v_prev_oct_dec_af = volume_af(
                self.q.loc[ws:pd.Timestamp(rec.wy - 1, 12, 31)])

            # Flow state at the reference date: a 7-day geometric-scale mean,
            # long enough to average out a synoptic melt pulse.
            recent = q_wy.loc[ref - pd.Timedelta(days=6):ref].dropna()
            if len(recent) >= 3:
                rec.q_mean_at_ref_cfs = float(np.exp(np.log(
                    recent.clip(lower=1.0)).mean()))

    # -- accessors -------------------------------------------------------
    def window_start(self, rec: YearRecord) -> pd.Timestamp | None:
        """Start of the seasonal volume accounting window for a year."""
        if self.cfg.volume_window == "peak":
            return rec.composite_peak_date
        return pd.Timestamp(rec.wy, 4, 1)

    def seasonal_volume(self, rec: YearRecord) -> float:
        """The predictand: seasonal runoff volume under the configured window."""
        if self.cfg.volume_window == "peak":
            return rec.v_post_peak_af
        return rec.v_apr_sep_af

    @property
    def window_label(self) -> str:
        return ("composite peak-SWE date -> Sep 30" if self.cfg.volume_window == "peak"
                else "Apr 1 -> Sep 30")

    @property
    def complete(self) -> list[YearRecord]:
        return [r for r in self.records if r.complete]

    @property
    def current(self) -> YearRecord | None:
        for r in self.records:
            if r.wy == self.current_wy:
                return r
        return None

    def by_wy(self, wy: int) -> YearRecord | None:
        for r in self.records:
            if r.wy == wy:
                return r
        return None

    def frame(self) -> pd.DataFrame:
        """Tidy one-row-per-year table. The unit of exchange with the models."""
        rows = []
        for r in self.records:
            row = {
                "wy": r.wy,
                "complete": r.complete,
                "n_days_q": r.n_days_q,
                "n_stations": r.n_stations_used,
                "peak_swe_in": r.composite_peak_swe_in,
                "peak_swe_pct": r.composite_peak_swe_pct,
                "apr1_swe_in": r.composite_apr1_swe_in,
                "apr1_swe_pct": r.composite_apr1_swe_pct,
                "precip_in": r.composite_precip_in,
                "peak_swe_doy": (doy_of_wy(r.composite_peak_date, r.wy)
                                 if r.composite_peak_date is not None else np.nan),
                "v_total_kaf": r.v_total_af / 1000.0,
                "v_apr_sep_kaf": r.v_apr_sep_af / 1000.0,
                "v_post_peak_kaf": r.v_post_peak_af / 1000.0,
                "v_oct_mar_kaf": r.v_oct_mar_af / 1000.0,
                "v_seasonal_kaf": self.seasonal_volume(r) / 1000.0,
                "v_to_ref_kaf": r.v_to_ref_af / 1000.0,
                "v_after_ref_kaf": r.v_after_ref_af / 1000.0,
                "swe_frac_at_ref": r.swe_frac_at_ref,
                "swe_at_ref_in": r.swe_at_ref_in,
                "v_prev_oct_dec_kaf": r.v_prev_oct_dec_af / 1000.0,
                "q_at_ref_cfs": r.q_mean_at_ref_cfs,
                "peak_q_cfs": r.peak_q_cfs,
                "peak_q_doy": (doy_of_wy(r.peak_q_date, r.wy)
                               if r.peak_q_date is not None else np.nan),
                "centroid_doy": r.centroid_doy,
                "last_runnable_doy": (doy_of_wy(r.last_runnable_date, r.wy)
                                      if r.last_runnable_date is not None else np.nan),
                "sustained_below_doy": (doy_of_wy(r.sustained_below_date, r.wy)
                                        if r.sustained_below_date is not None else np.nan),
            }
            for sid, sy in r.stations.items():
                row[f"swe_{sid}"] = sy.peak_swe_in if sy.usable else np.nan
            rows.append(row)
        return pd.DataFrame(rows).set_index("wy", drop=False)

    def daily_matrix(self, series: pd.Series, complete_only: bool = True
                     ) -> pd.DataFrame:
        """Daily values reshaped to a 365 x n_years matrix on the common DOY axis."""
        cols: dict[int, pd.Series] = {}
        for rec in self.records:
            if complete_only and not rec.complete:
                continue
            ws, we = wy_bounds(rec.wy)
            sub = series.loc[ws:we].dropna()
            if sub.empty:
                continue
            doy = doy_of_wy(sub.index, rec.wy)
            s = pd.Series(sub.to_numpy(), index=np.round(doy).astype(int))
            cols[rec.wy] = s[~s.index.duplicated(keep="first")]
        if not cols:
            return pd.DataFrame(index=range(1, 366))
        return pd.DataFrame(cols).reindex(range(1, 366))

    @property
    def ref_doy(self) -> float:
        return doy_of_wy(self.ref_date, self.current_wy)
