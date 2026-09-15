"""Run the river analysis for every configured river and publish it to R2.

    python rivers/run_rivers.py                 all rivers, figures, upload
    python rivers/run_rivers.py --no-upload     local only (writes rivers/out/<key>/)
    python rivers/run_rivers.py --only wenatchee-monitor --no-figures

Runs daily on GitHub Actions (.github/workflows/rivers.yml). For each river
in rivers_config.RIVERS it builds a Config for the analysis package
(rivers/wenatchee/), runs the same pipeline as ``python -m wenatchee``, and
uploads output/ to the public R2 bucket under ``rivers/<key>/``:

    rivers/<key>/web.js               everything the dashboard draws (window.RIVER_DATA)
    rivers/<key>/web.json             the same, as JSON
    rivers/<key>/report.txt           the written report
    rivers/<key>/results.json, annual_summary.csv, season_end_validation.csv
    rivers/<key>/figures/*.png        the ten figures
    rivers/<key>/season_<cfs>.js      the season-end block at each preset threshold
    rivers/index.js                   the river list the site's picker reads (window.RIVERS_INDEX)

R2 credentials come from the environment (R2_ACCOUNT_ID, R2_ACCESS_KEY_ID,
R2_SECRET_ACCESS_KEY) or from ../r2.env locally, through r2sync.load_env().
One river failing does not stop the others; its index entry records the error.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from dataclasses import replace
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))            # the wenatchee package
sys.path.insert(0, str(HERE.parent))     # r2sync (radar repo root)

from rivers_config import RIVERS, STATIONS  # noqa: E402
from wenatchee import cli  # noqa: E402
from wenatchee.config import Config, Station  # noqa: E402

BUCKET_PREFIX = "rivers/"
UPLOAD_FILES = ("web.js", "web.json", "report.txt", "results.json",
                "annual_summary.csv", "season_end_validation.csv")
CONTENT_TYPES = {".js": "application/javascript", ".json": "application/json",
                 ".txt": "text/plain", ".csv": "text/csv", ".png": "image/png"}


def log(msg: str) -> None:
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {msg}", flush=True)


def config_for(r: dict, out_root: Path, make_figures: bool) -> Config:
    ib = r.get("in_basin", {})
    stations = tuple(Station(**{**STATIONS[s], "in_basin": ib.get(s, STATIONS[s]["in_basin"])})
                     for s in r["stations"])
    bins = r.get("bins") or {}
    cfg = Config(
        usgs_site=r["usgs"], usgs_site_name=r["name"],
        drainage_mi2=float(r["drainage_mi2"]), stations=stations,
        temp_station_ids=tuple(r.get("temp_stations", ())),
        start_wy=int(r.get("start_wy", 1990)),
        runnable_cfs=float(r.get("runnable_cfs", 1000.0)),
        root=out_root / r["key"], make_figures=make_figures,
        cache_max_age_hours=float(r.get("cache_max_age_hours", 12.0)),
    )
    if r.get("thresholds"):
        cfg = replace(cfg, season_thresholds=tuple(float(t) for t in r["thresholds"]))
    if bins:
        cfg = replace(cfg, flow_bin_edges=tuple(bins["edges"]),
                      flow_bin_labels=tuple(bins["labels"]),
                      flow_bin_desc=tuple(bins["desc"]))
    return cfg


def run_one(r: dict, out_root: Path, make_figures: bool) -> dict:
    t0 = time.time()
    cfg = config_for(r, out_root, make_figures)
    entry = {k: r.get(k) for k in ("key", "name", "short", "river", "usgs", "drainage_mi2",
                                   "lat", "lon", "region", "runnable_cfs", "blurb")}
    entry["stations"] = [STATIONS[s]["site_id"] for s in r["stations"]]
    entry["thresholds"] = list(r.get("thresholds", ()))
    try:
        rc = cli.run(cfg, quiet=True)
        if rc != 0:
            raise RuntimeError(f"analysis returned {rc}")
        res = json.loads((cfg.output_dir / "results.json").read_text(encoding="utf-8"))
        entry.update(status="ok", generated=res.get("generated"),
                     reference_date=res.get("reference_date"), water_year=res.get("water_year"))
    except Exception as exc:  # noqa: BLE001 - one river must not sink the rest
        traceback.print_exc()
        entry.update(status="failed", error=f"{type(exc).__name__}: {exc}")
    entry["seconds"] = round(time.time() - t0)
    log(f"{r['key']}: {entry['status']} in {entry['seconds']} s")
    return entry


def merge_previous(entries: list[dict], s3, bucket: str) -> list[dict]:
    """A river that failed today keeps yesterday's index entry, marked stale.

    The site keeps drawing the last good web.js (it is still in the bucket), so
    the picker must not call the river "no data"; it just notes the last run.
    """
    try:
        body = s3.get_object(Bucket=bucket, Key=f"{BUCKET_PREFIX}index.json")["Body"].read()
        prev = {e["key"]: e for e in json.loads(body).get("rivers", [])}
    except Exception:  # noqa: BLE001 - first run, or bucket unreachable
        return entries
    out = []
    for e in entries:
        p = prev.get(e["key"])
        if e.get("status") == "failed" and p and p.get("generated"):
            keep = {k: p.get(k) for k in ("generated", "reference_date", "water_year")}
            e = {**e, **keep, "status": "stale", "failed_at": pd.Timestamp.now(tz="UTC").isoformat(timespec="seconds"),
                 "last_good_status": p.get("status")}
        out.append(e)
    return out


def upload(entries: list[dict], out_root: Path, fig_cache: str = "public, max-age=3600") -> int:
    import r2sync
    env = r2sync.load_env()
    if not env:
        log("no R2 credentials; nothing uploaded")
        return 0
    s3, bucket = r2sync.client(env), env.get("R2_BUCKET") or "radar"
    entries = merge_previous(entries, s3, bucket)
    n = 0

    def put(key: str, path: Path, cache: str) -> None:
        nonlocal n
        with open(path, "rb") as f:
            s3.put_object(Bucket=bucket, Key=key, Body=f,
                          ContentType=CONTENT_TYPES.get(path.suffix.lower(), "application/octet-stream"),
                          CacheControl=cache)
        n += 1

    for e in entries:
        if e["status"] != "ok":
            continue
        out = out_root / e["key"] / "output"
        for fn in UPLOAD_FILES:
            p = out / fn
            if p.exists():
                put(f"{BUCKET_PREFIX}{e['key']}/{fn}", p, "no-cache")
        # the season-end block at each preset threshold (season_1000.js ...)
        for p in sorted(out.glob("season_*.js")) + sorted(out.glob("season_*.json")):
            put(f"{BUCKET_PREFIX}{e['key']}/{p.name}", p, "no-cache")
        figs = out / "figures"
        if figs.is_dir():
            for p in sorted(figs.glob("*.png")):
                put(f"{BUCKET_PREFIX}{e['key']}/figures/{p.name}", p, fig_cache)
    index = out_root / "index.js"
    write_index(index, entries)
    put(f"{BUCKET_PREFIX}index.js", index, "no-cache")
    put(f"{BUCKET_PREFIX}index.json", out_root / "index.json", "no-cache")
    log(f"uploaded {n} objects to {bucket}/{BUCKET_PREFIX}")
    return n


def write_index(path: Path, entries: list[dict]) -> None:
    doc = {"updated": pd.Timestamp.now(tz="UTC").isoformat(timespec="seconds"),
           "rivers": entries}
    text = json.dumps(doc, indent=1)
    path.write_text("window.RIVERS_INDEX = " + text + ";\n", encoding="utf-8")
    path.with_suffix(".json").write_text(text, encoding="utf-8")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", action="append", help="river key(s) to run; default all")
    ap.add_argument("--no-figures", action="store_true")
    ap.add_argument("--no-upload", action="store_true")
    ap.add_argument("--out", default=str(HERE / "out"), help="local output root")
    ap.add_argument("--upload-only", action="store_true",
                    help="skip the analysis; upload whatever is already in out/ (index rebuilt from it)")
    args = ap.parse_args(argv)

    out_root = Path(args.out)
    out_root.mkdir(parents=True, exist_ok=True)
    rivers = [r for r in RIVERS if not args.only or r["key"] in args.only]
    if not rivers:
        print("no rivers matched", file=sys.stderr)
        return 2

    if args.upload_only:
        ran = {}
        for r in rivers:
            res_p = out_root / r["key"] / "output" / "results.json"
            if not res_p.exists():
                continue
            res = json.loads(res_p.read_text(encoding="utf-8"))
            e = {k: r.get(k) for k in ("key", "name", "short", "river", "usgs", "drainage_mi2",
                                       "lat", "lon", "region", "runnable_cfs", "blurb")}
            e.update(stations=list(r["stations"]), status="ok", generated=res.get("generated"),
                     reference_date=res.get("reference_date"), water_year=res.get("water_year"), seconds=0)
            ran[r["key"]] = e
    else:
        ran = {r["key"]: run_one(r, out_root, not args.no_figures) for r in rivers}
    # keep every configured river in the index even when only some were run
    entries = []
    for r in RIVERS:
        if r["key"] in ran:
            entries.append(ran[r["key"]])
        else:
            e = {k: r.get(k) for k in ("key", "name", "short", "river", "usgs", "drainage_mi2",
                                       "lat", "lon", "region", "runnable_cfs", "blurb")}
            e.update(stations=list(r["stations"]), status="not run")
            entries.append(e)
    write_index(out_root / "index.js", entries)
    if not args.no_upload:
        upload(entries, out_root)
    failed = [e["key"] for e in entries if e["status"] == "failed"]
    if failed:
        log("FAILED: " + ", ".join(failed))
    return 1 if len(failed) == len(ran) else 0


if __name__ == "__main__":
    sys.exit(main())
