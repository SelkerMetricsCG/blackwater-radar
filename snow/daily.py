"""
The daily run after the state model (snow.yml, second step): read the day's forecast products and observations from
the archive, extract records with the LLM, score them against the model, write the brief, save the ledger.

  python -m snow.daily --date 2026-01-15      (yesterday by default; --no-upload for a dry run)
Without ANTHROPIC_API_KEY the LLM passes are skipped and only Chris's trips (snow/trips.json) are scored.
"""
import argparse
import datetime as dt
import json
import os
import time

import numpy as np

from snow import ledger, llm, score, store

LEDGER_DAYS = 21


def day_products(date, log=print):
    import region
    center = region.cfg().get("avy")
    names = [n for n in store.listing("archive/%s/products/" % date) if n.endswith(".json") and (not center or n.startswith(center + "_"))]
    out = []
    for n in names:
        p = store.read_json("archive/%s/products/%s" % (date, n), log)
        if isinstance(p, dict):
            out.append(dict(p, _file=n))
    return out


def day_obs(date, log=print):
    out = []
    for n in store.listing("archive/%s/obs/" % date):
        if n.endswith(".json"):
            o = store.read_json("archive/%s/obs/%s" % (date, n), log)
            if o:
                out.append({"_file": n, "data": o})
    return out


def bottom_lines(products):
    keep = ("id", "product_type", "published_time", "expires_time", "bottom_line", "danger", "forecast_zone")
    return [{k: p.get(k) for k in keep if k in p} for p in products]


def run(day, log=print, upload=True):
    t0 = time.time()
    d = day.isoformat()
    recs = ledger.load(log)
    summ = store.read_json("state/%s.json" % d, log)
    meta = store.read_json("static/lattice.json", log) or {}
    products = day_products(d, log)
    obs = day_obs(d, log)
    log("daily %s: ledger %d records, %d products, %d obs files, state %s" % (d, len(recs), len(products), len(obs), "yes" if summ else "none"))
    # trips: Chris's own records for the day (their tier is known by construction; older trips.json entries lack it)
    trips_today = [dict({"source_tier": "trip"}, **t) for t in ledger.trips(log) if t.get("obs_date") == d]
    new_obs = ledger.append(recs, trips_today, d, "trip") if trips_today else []
    # pass 1: extraction
    known = ledger.layers(recs, today=d)
    if products or obs:
        ex = llm.extract(d, products, obs, list(known.values()), log)
        if ex:
            new_obs += ledger.append(recs, ex.get("observations", []), d, "obs")
            ledger.append(recs, ex.get("layers", []), d, "layer")
            ledger.append(recs, ex.get("notes", []), d, "note")
            log("daily: +%d obs, +%d layer snapshots, +%d notes" % (len(ex.get("observations", [])), len(ex.get("layers", [])), len(ex.get("notes", []))))
    # scoring against the day's classes
    if new_obs:
        cls_path = store.fetch("state/%s_cls.npz" % d, log)
        lat_path = store.fetch("static/lattice.npz", log)
        st_path = store.fetch("state/latest.npz", log)
        if cls_path and lat_path:
            cls = np.load(cls_path)["cls"]
            lat = dict(np.load(lat_path))
            state = dict(np.load(st_path)) if st_path else {}
            residuals = ledger.append(recs, score.score(new_obs, cls, state, lat, meta, log), d, "residual")
            if residuals and state and str(state.get("day", "")) == d:
                from snow import assimilate, state as st_mod
                p, _ = st_mod.load_params()
                nudged = assimilate.apply(state, residuals, {o["id"]: o for o in new_obs}, lat, meta, p, log)
                if nudged:
                    ledger.append(recs, nudged, d, "assim")
                    st_mod.rewrite_outputs(state, lat, meta, day, log, upload)
    # pass 2: the brief
    out = {"date": d, "generated_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M"), "model": llm.MODEL}
    if summ:
        b = llm.brief(d, summ, ledger.recent(recs, d, LEDGER_DAYS), bottom_lines(products), log)
        if b:
            out.update(b)
            ledger.append(recs, b.get("notes", []), d, "note")
    out["layers"] = list(ledger.layers(recs, today=d).values())
    from snow.state import write_js
    write_js("brief/%s" % d, "SNOW_BRIEF", out)
    write_js("brief/latest", "SNOW_BRIEF", out)
    ledger.save(recs, upload, log)
    if upload:
        for ext in (".json", ".js"):
            store.put("brief/%s%s" % (d, ext), "public, max-age=31536000, immutable", log)
            store.put("brief/latest" + ext, "no-cache", log)
    log("daily %s: done in %.0f s, ledger %d records, brief %s" % (d, time.time() - t0, len(recs), "written" if "overview" in out else "none"))
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None)
    ap.add_argument("--no-upload", action="store_true")
    a = ap.parse_args()
    dd = dt.date.fromisoformat(a.date) if a.date else dt.date.today() - dt.timedelta(days=1)
    run(dd, upload=not a.no_upload)
