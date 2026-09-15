"""Command-line entry point.

    python -m wenatchee                 run today's analysis
    python -m wenatchee --as-of 2026-05-02   hindcast an earlier date
    python -m wenatchee --offline       use the cached downloads only
"""

from __future__ import annotations

import argparse
import sys
import traceback
from dataclasses import replace

import pandas as pd

from .config import CORE_STATIONS, EXTENDED_STATIONS, Config


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="wenatchee",
        description="Snowpack-to-runoff analysis and seasonal forecast for the "
                    "Wenatchee River.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  python -m wenatchee
  python -m wenatchee --as-of 2026-05-02     forecast as of an earlier date
  python -m wenatchee --site 12459000        Peshastin: above the big diversions
  python -m wenatchee --window peak          use the original peak-SWE window
  python -m wenatchee --stations extended    also test in-basin SNOTEL sites
  python -m wenatchee --offline --no-figures fast text-only re-run
""")
    p.add_argument("--as-of", metavar="YYYY-MM-DD",
                   help="run the forecast as if today were this date; later "
                        "data is withheld, which turns the run into a hindcast")
    p.add_argument("--site", default=None,
                   help="USGS gauge id (default 12462500, Monitor). "
                        "12459000 is Peshastin, above the Dryden diversions.")
    p.add_argument("--start-wy", type=int, default=None,
                   help="first water year of the record (default 1990)")
    p.add_argument("--window", choices=("apr1", "peak"), default=None,
                   help="seasonal volume window: apr1 (fixed, default) or peak "
                        "(from each year's composite peak-SWE date)")
    p.add_argument("--index", default=None,
                   choices=("peak_swe_in", "peak_swe_pct", "apr1_swe_in",
                            "apr1_swe_pct"),
                   help="snowpack index used by every model (default peak_swe_in)")
    p.add_argument("--stations", choices=("core", "extended"), default="core",
                   help="core = the original four; extended also tests nearby "
                        "in-basin sites")
    p.add_argument("--offline", action="store_true",
                   help="use cached downloads only, never hit the network")
    p.add_argument("--refresh", action="store_true",
                   help="force a fresh download even if the cache is warm")
    p.add_argument("--no-figures", action="store_true", help="skip plotting")
    p.add_argument("--no-web", action="store_true",
                   help="skip the web export (output/web.js, web.json)")
    p.add_argument("--no-track", action="store_true",
                   help="skip re-issuing the season-end forecast day by day "
                        "through the spring (the web export's track)")
    p.add_argument("--show", action="store_true",
                   help="open the figures as well as saving them")
    p.add_argument("--pi", type=float, default=None, metavar="P",
                   help="prediction-interval width, e.g. 0.9 (default 0.8)")
    p.add_argument("--quiet", action="store_true",
                   help="write the report to file without printing it")
    return p


def config_from_args(args) -> Config:
    cfg = Config()
    if args.site:
        cfg = replace(cfg, usgs_site=args.site,
                      usgs_site_name=f"USGS {args.site}")
    if args.start_wy:
        cfg = replace(cfg, start_wy=args.start_wy)
    if args.window:
        cfg = replace(cfg, volume_window=args.window)
    if args.index:
        cfg = replace(cfg, snow_index=args.index)
    if args.stations == "extended":
        cfg = replace(cfg, stations=CORE_STATIONS + EXTENDED_STATIONS)
    if args.as_of:
        cfg = replace(cfg, as_of=pd.Timestamp(args.as_of))
    if args.pi:
        cfg = replace(cfg, prediction_interval=float(args.pi))
    if args.offline:
        cfg = replace(cfg, offline=True)
    if args.refresh:
        cfg = replace(cfg, cache_max_age_hours=0.0)
    if args.no_figures:
        cfg = replace(cfg, make_figures=False)
    if args.no_web:
        cfg = replace(cfg, make_web=False)
    if args.no_track:
        cfg = replace(cfg, make_track=False)
    if args.show:
        cfg = replace(cfg, show_figures=True)
    return cfg


def run(cfg: Config, quiet: bool = False) -> int:
    from . import (backtest, core, derived, export, fetch, figures, models,
                   report, season_end)

    raw = fetch.fetch_all(cfg)
    ana = core.Analysis(cfg, raw)

    print("\n  Verifying the forecast against history (leave-one-out)...")
    bt = backtest.run_backtest(cfg, raw, ana.ref_date.month, ana.ref_date.day)
    lead = backtest.run_lead_time_curve(cfg, raw)

    fc = models.build_forecast(ana, bt.scores() if bt is not None else None)
    th = derived.build_thermal(ana, raw.water_temp_max_c)
    melt = derived.build_melt(ana)

    # Season end: validated at a spring issue date, because spring is when
    # the question actually gets asked.
    season = season_end.validate(ana, cfg.season_issue_month, cfg.season_issue_day)
    season_skill = season_end.skill_by_issue_date(ana)
    season_current = (season_end.forecast_current(ana, season)
                      if season is not None else {})
    track = None
    if cfg.make_web and cfg.make_track and season is not None:
        print("  Re-issuing the season-end forecast through the spring "
              f"({cfg.track_start[0]}/{cfg.track_start[1]} to "
              f"{cfg.track_end[0]}/{cfg.track_end[1]})...")
        track = season_end.track_by_issue_date(
            ana, cfg.track_start, cfg.track_end, cfg.track_step_days)

    if cfg.make_figures:
        figures.make_all(cfg, ana, fc, th, bt, lead,
                         season, season_skill, season_current)

    print()
    rep = report.build_report(cfg, ana, fc, th, melt, bt, lead,
                              season, season_skill, season_current)

    out = cfg.output_dir
    stamp = "" if cfg.as_of is None else f"_asof_{cfg.as_of:%Y%m%d}"
    rep.write(out / f"report{stamp}.txt")
    report.write_json(out / f"results{stamp}.json", cfg, ana, fc, th, bt)
    ana.frame().to_csv(out / f"annual_summary{stamp}.csv", index=False)
    if season is not None:
        season.table().to_csv(out / f"season_end_validation{stamp}.csv",
                              index=False)
    if cfg.make_web:
        web = export.build_web(cfg, ana, fc, th, melt, bt, lead, season,
                               season_skill, season_current, track,
                               report_text=rep.text())
        export.write_web(out, web, stem=f"web{stamp}")

    print()
    print(f"  Wrote {out / f'report{stamp}.txt'}")
    print(f"        {out / f'results{stamp}.json'}")
    print(f"        {out / f'annual_summary{stamp}.csv'}")
    if season is not None:
        print(f"        {out / f'season_end_validation{stamp}.csv'}")
    if cfg.make_web:
        print(f"        {out / f'web{stamp}.js'}  (+ .json)")
    if cfg.make_figures:
        print(f"        {cfg.figure_dir}  ({len(list(cfg.figure_dir.glob('*.png')))} figures)")

    if cfg.show_figures:
        import matplotlib.pyplot as plt
        plt.show()
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cfg = config_from_args(args)
    try:
        return run(cfg, quiet=args.quiet)
    except KeyboardInterrupt:
        print("\nInterrupted.")
        return 130
    except Exception as exc:                      # noqa: BLE001
        print("\n" + "=" * 72)
        print("  THE ANALYSIS FAILED")
        print("=" * 72)
        print(f"  {type(exc).__name__}: {exc}")
        print()
        from .fetch import FetchError
        network = isinstance(exc, FetchError) or any(
            n in type(exc).__name__ for n in
            ("ConnectionError", "Timeout", "HTTPError", "SSLError", "RequestException"))
        if network:
            print("  This looks like a data-download problem. Things to try:")
            print("    * check your internet connection")
            print("    * re-run with --offline to use the last cached download")
            print("    * the USGS or NRCS server may be down; try again later")
        else:
            print("  Full traceback:")
            traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
