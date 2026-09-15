"""Self-checks for the invariants this rewrite exists to protect.

Run with:  python -m wenatchee.selftest

These are the specific things the MATLAB version got wrong. Each test pins
one of them so a future edit cannot quietly reintroduce it. The tests that
need data use the on-disk cache and are skipped if it is empty.
"""

from __future__ import annotations

import sys
import traceback

import numpy as np
import pandas as pd

from .config import (AF_PER_CFS_DAY, MONTH_LABELS, MONTH_START_DOY, Config)
from .core import (af_per_basin_inch, basin_inches, date_from_doy,
                   doy_of_wy, equivalent_date, is_leap_wy, volume_af,
                   water_year, wy_bounds)
from .stats import envelope, fit_ols, skill_score, trend

_FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}" + (f"  --  {detail}" if detail else ""))
        _FAILURES.append(name)


# --------------------------------------------------------------------------
def test_units() -> None:
    print("\nUnits and conversions")
    # 1 cfs for 1 day = 1.98347 acre-feet
    check("acre-feet per cfs-day", abs(AF_PER_CFS_DAY - 1.983471) < 1e-5,
          f"got {AF_PER_CFS_DAY}")
    # 1 inch over 1301 sq mi = 1301 * 640 / 12 acre-feet
    check("acre-feet per basin inch",
          abs(af_per_basin_inch(1301.0) - 69386.667) < 0.1,
          f"got {af_per_basin_inch(1301.0)}")
    check("basin_inches round-trips",
          abs(basin_inches(af_per_basin_inch(1301.0), 1301.0) - 1.0) < 1e-9)
    q = pd.Series([1000.0] * 10, index=pd.date_range("2020-05-01", periods=10))
    check("volume_af of 1000 cfs for 10 days",
          abs(volume_af(q) - 19834.71) < 1.0, f"got {volume_af(q)}")


def test_water_year() -> None:
    print("\nWater-year calendar")
    check("Oct 1 starts the next water year",
          water_year(pd.Timestamp(2025, 10, 1)) == 2026)
    check("Sep 30 ends the same water year",
          water_year(pd.Timestamp(2026, 9, 30)) == 2026)
    check("wy_bounds", wy_bounds(2026) == (pd.Timestamp(2025, 10, 1),
                                           pd.Timestamp(2026, 9, 30)))
    check("WY2024 is a leap water year", is_leap_wy(2024))
    check("WY2026 is not", not is_leap_wy(2026))


def test_leap_alignment() -> None:
    """The bug that silently offset a quarter of the record by one day."""
    print("\nLeap-year alignment")
    # Aug 31 must be the same day-of-water-year in leap and non-leap years.
    a = doy_of_wy(pd.Timestamp(2026, 8, 31), 2026)   # non-leap WY
    b = doy_of_wy(pd.Timestamp(2024, 8, 31), 2024)   # leap WY
    check("Aug 31 has the same DOY in leap and non-leap water years",
          a == b, f"{a} vs {b}")
    # Month ticks must land on the first of each month, in every year.
    ok = True
    detail = ""
    for wy in (2024, 2025, 2026):
        for i, (tick, label) in enumerate(zip(MONTH_START_DOY, MONTH_LABELS)):
            month = [10, 11, 12, 1, 2, 3, 4, 5, 6, 7, 8, 9][i]
            year = wy - 1 if month >= 10 else wy
            got = doy_of_wy(pd.Timestamp(year, month, 1), wy)
            if got != tick:
                ok = False
                detail = f"WY{wy} {label} 1: tick {tick}, actual {got}"
    check("every month tick lands on the 1st, in every water year", ok, detail)
    # Sep 1 is day 336, not 335 -- the off-by-one in the MATLAB vector.
    check("Sep 1 is day 336", MONTH_START_DOY[11] == 336,
          f"got {MONTH_START_DOY[11]}")

    # date -> doy -> date must be the identity on every day of every water
    # year. Without the leap term in the inverse, every date reported for a
    # leap water year comes out one day early -- nine of thirty-seven years.
    bad, example = 0, ""
    for wy in range(1990, 2027):
        ws, we = wy_bounds(wy)
        for ts in pd.date_range(ws, we, freq="D"):
            if is_leap_wy(wy) and ts == pd.Timestamp(wy, 2, 29):
                continue                       # collapses onto Feb 28 by design
            back = date_from_doy(doy_of_wy(ts, wy), wy)
            if back != ts:
                bad += 1
                example = example or f"WY{wy} {ts.date()} -> {back.date()}"
    check("day-of-year round-trips to the same date, every day of every year",
          bad == 0, f"{bad} failures, e.g. {example}")
    check("Feb 29 collapses onto Feb 28's day number",
          doy_of_wy(pd.Timestamp(2024, 2, 29), 2024)
          == doy_of_wy(pd.Timestamp(2024, 2, 28), 2024))


def test_equivalent_date() -> None:
    print("\nEquivalent dates across years")
    ref = pd.Timestamp(2026, 5, 2)
    check("May 2 maps to May 2", equivalent_date(ref, 2015) == pd.Timestamp(2015, 5, 2))
    ref_oct = pd.Timestamp(2025, 11, 15)     # in WY2026, calendar year 2025
    check("Nov 15 maps into the prior calendar year",
          equivalent_date(ref_oct, 2015) == pd.Timestamp(2014, 11, 15))
    ref_feb = pd.Timestamp(2024, 2, 29)
    check("Feb 29 falls back to Feb 28 in a non-leap year",
          equivalent_date(ref_feb, 2025) == pd.Timestamp(2025, 2, 28))


def test_regression() -> None:
    print("\nRegression and intervals")
    rng = np.random.default_rng(7)
    x = rng.uniform(15, 50, 200)
    y = 40 * x + 300 + rng.normal(0, 120, 200)
    fit = fit_ols(x, y, "synthetic")
    check("recovers a known slope", abs(fit.slope - 40) < 4,
          f"got {fit.slope:.2f}")
    check("LOOCV skill is below in-sample r2", fit.loocv_r2 <= fit.r2 + 1e-9)
    check("prediction interval brackets the point estimate",
          fit.predict(30).lo < fit.predict(30).value < fit.predict(30).hi)
    check("a value outside the calibration range is flagged",
          fit.predict(5).extrapolated and not fit.predict(30).extrapolated)
    check("the fitted line is clipped to the data range",
          fit.line()[0].min() >= x.min() - 1e-6
          and fit.line()[0].max() <= x.max() + 1e-6)

    # Interval coverage: an honest 80% interval covers about 80%.
    hits = 0
    for _ in range(300):
        xs = rng.uniform(15, 50, 60)
        ys = 40 * xs + 300 + rng.normal(0, 120, 60)
        f = fit_ols(xs[:-1], ys[:-1], "cov")
        p = f.predict(xs[-1], 0.80)
        hits += int(p.lo <= ys[-1] <= p.hi)
    cov = hits / 300
    check("80% intervals cover close to 80% of new observations",
          0.72 <= cov <= 0.88, f"coverage {cov:.2f}")

    check("skill score is allowed to go negative",
          skill_score(np.array([1.0, 2, 3]), np.array([9.0, 9, 9])) < 0)


def test_log_space() -> None:
    print("\nLog-space fitting")
    rng = np.random.default_rng(11)
    x = rng.uniform(10, 60, 300)
    y = 25 * x ** 1.1 * np.exp(rng.normal(0, 0.15, 300))
    fit = fit_ols(x, y, "power", log_x=True, log_y=True)
    check("recovers a known exponent", abs(fit.slope - 1.1) < 0.08,
          f"got {fit.slope:.3f}")
    check("Duan smearing factor exceeds 1", fit.duan > 1.0,
          f"got {fit.duan:.4f}")
    check("predictions stay positive well below the data",
          fit.predict(1.0).value > 0)


def test_trend() -> None:
    print("\nTrend testing")
    rng = np.random.default_rng(3)
    yrs = np.arange(1990, 2026)
    flat = rng.normal(0, 1, len(yrs))
    check("pure noise is not called significant",
          not trend(yrs, flat, "noise").significant)
    strong = 0.6 * (yrs - 1990) + rng.normal(0, 1, len(yrs))
    t = trend(yrs, strong, "strong")
    check("a strong trend is detected", t.significant)
    check("the confidence interval brackets the slope", t.lo <= t.slope <= t.hi)
    outlier = flat.copy()
    outlier[0] = 40.0
    check("Theil-Sen resists a single wild outlier",
          abs(trend(yrs, outlier, "outlier").slope) < 0.3,
          f"slope {trend(yrs, outlier, 'outlier').slope:.3f}")


def test_envelope() -> None:
    print("\nPercentile envelopes")
    m = np.full((10, 30), 5.0)
    m[5, 5:] = np.nan          # only 5 years back row 5
    env, counts = envelope(m, (0.5,), min_count=20)
    check("a thinly-supported row is masked out", np.isnan(env[0.5][5]))
    check("a fully-supported row is kept", np.isfinite(env[0.5][0]))
    check("counts are reported", counts[5] == 5 and counts[0] == 30)


def test_no_future_leakage() -> None:
    """A hindcast must not see data after its reference date."""
    print("\nHindcast isolation (uses the cache; skipped if empty)")
    from dataclasses import replace
    from .core import Analysis
    from .fetch import fetch_all
    cfg = replace(Config(), offline=True, as_of=pd.Timestamp("2026-05-02"))
    try:
        raw = fetch_all(cfg)
    except Exception as exc:                    # noqa: BLE001
        print(f"  SKIP  no cached data available ({type(exc).__name__})")
        return
    ana = Analysis(cfg, raw)
    cutoff = pd.Timestamp("2026-05-02")
    check("discharge is truncated at the reference date",
          ana.q.index.max() <= cutoff, f"max {ana.q.index.max()}")
    check("water temperature is truncated",
          ana.raw.water_temp_c.empty or ana.raw.water_temp_c.index.max() <= cutoff)
    check("every SNOTEL series is truncated",
          all(df.index.max() <= cutoff for df in ana.raw.snotel.values()))
    check("the reference date is honoured", ana.ref_date == cutoff)
    check("the run is marked as a hindcast", ana.is_hindcast)
    cur = ana.current
    check("the current water year is not treated as complete",
          cur is not None and not cur.complete)
    check("no complete year is the current year",
          all(r.wy != ana.current_wy for r in ana.complete))


def test_season_end_definition() -> None:
    """The definition that separates the recession end from a fall rain bump."""
    print("\nSeason-end definition")
    from .season_end import find_season_end

    idx = pd.date_range("2020-05-01", "2020-09-30", freq="D")
    # A clean recession: above 1000 until Jul 20, below thereafter.
    q = pd.Series(2000.0, index=idx)
    q.loc["2020-07-21":] = 500.0
    se = find_season_end(q, 2020, 1000.0, 7)
    check("clean recession: end is the last day above the threshold",
          se.recession_end == pd.Timestamp("2020-07-20"),
          f"got {se.recession_end}")
    check("clean recession: sustained drop starts the next day",
          se.sustained_start == pd.Timestamp("2020-07-21"))
    check("clean recession: not censored", not se.censored)

    # Same recession, plus a 3-day September rain bump over the threshold.
    q2 = q.copy()
    q2.loc["2020-09-10":"2020-09-12"] = 1800.0
    se2 = find_season_end(q2, 2020, 1000.0, 7)
    check("a September rain bump does not extend the season",
          se2.recession_end == pd.Timestamp("2020-07-20"),
          f"got {se2.recession_end}")
    check("the naive 'last day above' definition IS fooled by it",
          se2.last_any == pd.Timestamp("2020-09-12"))
    check("the size of that error is reported",
          se2.rain_bump_days == 54, f"got {se2.rain_bump_days}")

    # Never drops: right-censored.
    q3 = pd.Series(2000.0, index=idx)
    se3 = find_season_end(q3, 2020, 1000.0, 7)
    check("a season that never drops is flagged censored", se3.censored)

    # A dip shorter than the sustained window must not end the season.
    q4 = q.copy()
    q4.loc["2020-06-10":"2020-06-14"] = 500.0     # 5 days, under the 7-day rule
    se4 = find_season_end(q4, 2020, 1000.0, 7)
    check("a 5-day dip does not end the season under a 7-day rule",
          se4.recession_end == pd.Timestamp("2020-07-20"),
          f"got {se4.recession_end}")

    # Ordering invariants must hold in every real year.
    from dataclasses import replace
    from .core import Analysis
    from .fetch import fetch_all
    try:
        raw = fetch_all(replace(Config(), offline=True))
    except Exception:                           # noqa: BLE001
        print("  SKIP  ordering checks need cached data")
        return
    ana = Analysis(replace(Config(), offline=True), raw)
    ok_order = ok_bump = True
    for rec in ana.records:
        e = find_season_end(ana.q, rec.wy, 1000.0, 7)
        if e.recession_end is None:
            continue
        if e.last_any is not None and e.recession_end > e.last_any:
            ok_order = False
        if e.sustained_start is not None and e.recession_end >= e.sustained_start:
            ok_order = False
        if e.rain_bump_days < 0:
            ok_bump = False
    check("recession end never exceeds the last day above threshold", ok_order)
    check("the rain-bump offset is never negative", ok_bump)


def test_season_end_validation() -> None:
    """A year must never contribute to its own forecast."""
    print("\nSeason-end validation")
    from dataclasses import replace
    from .core import Analysis
    from .fetch import fetch_all
    from .season_end import validate
    try:
        cfg = replace(Config(), offline=True)
        raw = fetch_all(cfg)
    except Exception:                           # noqa: BLE001
        print("  SKIP  needs cached data")
        return
    ana = Analysis(cfg, raw)
    v = validate(ana, 5, 1)
    if v is None:
        print("  SKIP  not enough years")
        return

    use = v.usable()
    check("censored years are excluded from the scores",
          all(not y.censored for y in use))
    check("years already over at the issue date are excluded",
          all(not y.already_over for y in use))
    check("the best predictor beats climatology",
          v.scores().iloc[0]["MAE_days"] <
          float(v.scores().set_index("method").loc["climatology", "MAE_days"]))

    # Leave-one-out: dropping a year must change nothing about the others'
    # forecasts, and a year's own value must not pin its own prediction.
    exact = sum(1 for y in use if abs(y.error_days(v.best_method())) < 0.5)
    check("forecasts are not trivially reproducing the answer",
          exact < len(use) * 0.5, f"{exact}/{len(use)} exact")
    check("prediction intervals cover close to the nominal rate",
          0.65 <= float(v.scores().iloc[0]["PI_coverage"]) <= 0.95,
          f"coverage {v.scores().iloc[0]['PI_coverage']:.2f}")

    tbl = v.table()
    check("every year appears in the table once",
          len(tbl) == len(v.years) and tbl.wy.is_unique)


def test_parsers() -> None:
    print("\nParsers")
    from .fetch import parse_nwis_rdb, parse_snotel_csv
    rdb = ("# comment\n"
           "agency_cd\tsite_no\tdatetime\t149854_00060_00003\t149854_00060_00003_cd\n"
           "5s\t15s\t20d\t14n\t10s\n"
           "USGS\t12462500\t2024-10-01\t352\tA\n"
           "USGS\t12462500\t2024-10-02\tIce\tA\n"
           "USGS\t12462500\t2024-10-03\t330\tP\n")
    s = parse_nwis_rdb(rdb, "00060")
    check("RDB: the type-definition row is skipped", len(s) == 2, f"got {len(s)}")
    check("RDB: a non-numeric qualifier becomes missing, not zero",
          pd.Timestamp("2024-10-02") not in s.index)
    check("RDB: values parse correctly", s.iloc[0] == 352 and s.iloc[1] == 330)

    csv = ("# comment\n"
           "Date,Snow Water Equivalent (in) Start of Day Values,"
           "Air Temperature Maximum (degF)\n"
           "2025-10-01,0.0,50.2\n"
           "2025-10-02,,\n"
           "2025-10-03,1.5,44.0\n")
    df = parse_snotel_csv(csv)
    check("SNOTEL: the header row is not parsed as data", len(df) == 3,
          f"got {len(df)}")
    check("SNOTEL: a blank value becomes NaN, not a row that vanishes",
          bool(np.isnan(df["swe_in"].iloc[1])))
    check("SNOTEL: columns are renamed", list(df.columns) == ["swe_in", "tmax_f"])


# --------------------------------------------------------------------------
def main() -> int:
    print("=" * 70)
    print("  WENATCHEE ANALYSIS - SELF TEST")
    print("=" * 70)
    for fn in (test_units, test_water_year, test_leap_alignment,
               test_equivalent_date, test_regression, test_log_space,
               test_trend, test_envelope, test_parsers,
               test_season_end_definition, test_season_end_validation,
               test_no_future_leakage):
        try:
            fn()
        except Exception:                       # noqa: BLE001
            print(f"  ERROR in {fn.__name__}:")
            traceback.print_exc()
            _FAILURES.append(fn.__name__)
    print("\n" + "=" * 70)
    if _FAILURES:
        print(f"  {len(_FAILURES)} FAILED: {', '.join(_FAILURES)}")
        print("=" * 70)
        return 1
    print("  All checks passed.")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
