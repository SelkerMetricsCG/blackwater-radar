"""
The fit: move the model's parameters, within their bounds and by at most their max_step, to reduce the mismatch
between what the model replays and what people reported. Runs on demand (snow_fit.yml, or from a PC), never
inside the daily run; every change it applies is a `param` ledger record with the residuals that drove it.

Residuals come from the ledger (snow/score.py): each names a lattice cell (coordinates or a gazetteer place) or
only a zone group; only the ones with a cell take part. For each, the loss is confidence x (1 - frac), where frac
is the share of the cells within its radius (kept to its band and aspects) that the replay classifies as the
observed class on that day. The search is coordinate descent: for each fittable parameter try +max_step and
-max_step, keep a move when the total loss drops by more than `tol`, repeat until a round changes nothing.

  python -m snow.fit                    proposal only: fit/<date>.json (and R2), nothing changed
  python -m snow.fit --apply            also write the new values into snow_config.yaml and the ledger
"""
import argparse
import datetime as dt
import json
import os
import time

import numpy as np

from snow import forcing, ledger, replay, score, state, store
from snow.state import CID

ROOT = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(ROOT, "snow_config.yaml")
MIN_RESIDUALS = 30
MAX_ROUNDS = 4
TOL = 0.5
WINDOW_K = 20          # cells each way around a residual (2 km)


def fittable(cfg_state):
    return {k: v for k, v in cfg_state.items() if isinstance(v, dict) and "bounds" in v and "max_step" in v
            and isinstance(v.get("value"), (int, float))}


def residual_items(recs, meta, log=print):
    """the residuals that name a cell, joined to their observation: [(date, r, c, observed id, conf, radius_cells, band, aspects)]"""
    obs = {r["id"]: r for r in recs if r.get("kind") in ("obs", "trip")}
    table = score.places()
    bands = {"below": 0, "near": 1, "above": 2}
    cell_m = float(meta.get("cell_m") or 100)
    items = []
    for r in recs:
        if r.get("kind") != "residual" or r.get("observed") not in CID:
            continue
        o = obs.get(r.get("obs_id"), {})
        if r.get("how") == "near" and r.get("cell"):
            rr, cc = r["cell"]
        else:
            hit = table.get(r.get("place") or "")
            if not hit:
                continue
            rw, cw = forcing.cell_of(meta, [hit[0]], [hit[1]])
            if rw[0] < 0:
                continue
            rr, cc = int(rw[0]), int(cw[0])
        radius = float(r.get("radius_m") or 300) / cell_m
        conf = float(o.get("confidence") if o.get("confidence") is not None else 0.6)
        items.append({"id": r["id"], "date": r["date"], "r": int(rr), "c": int(cc), "obs": CID[r["observed"]], "conf": conf,
                      "radius": radius, "band": bands.get(o.get("band") or ""), "aspects": o.get("aspects") or []})
    return items


def loss_of(cls_by_day, items, subset):
    total = 0.0
    for it in items:
        cls = cls_by_day.get(it["date"])
        if cls is None:
            continue
        m = subset.near(it["r"], it["c"], it["radius"]) & (cls != 255)
        filt = m.copy()
        if it["band"] is not None:
            filt &= subset.lat["band"] == it["band"]
        if it["aspects"] and "all" not in it["aspects"]:
            oi = state.octants(subset.lat["aspect"])
            filt &= np.isin(oi, [score.OCT.index(a) for a in it["aspects"] if a in score.OCT])
        use = filt if filt.any() else m
        if not use.any():
            continue
        frac = float((cls[use] == it["obs"]).mean())
        total += it["conf"] * (1 - frac)
    return total


def fit(recs, lat, meta, log=print, max_rounds=MAX_ROUNDS, tol=TOL, cache_dir=replay.CACHE, use_cache=True, min_residuals=MIN_RESIDUALS):
    import yaml
    with open(CONFIG, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    fit_params = fittable(cfg["state"])
    p, scfg = state.load_params()
    items = residual_items(recs, meta, log)
    if len(items) < min_residuals:
        log("fit: %d usable residuals, need %d; nothing proposed" % (len(items), min_residuals))
        return {"n_residuals": len(items), "changes": [], "skipped": "too few residuals"}
    dates = sorted(set(it["date"] for it in items))
    start = dt.date.fromisoformat(dates[0]) - dt.timedelta(days=replay.SPINUP)
    end = dt.date.fromisoformat(dates[-1])
    subset = replay.Subset(lat, meta, [(it["r"], it["c"]) for it in items], WINDOW_K)
    log("fit: %d residuals on %d days, %d cells in the replay subset, %s..%s" % (len(items), len(dates), len(subset.flat), start, end))

    def evaluate(params):
        cls = replay.run(start, end, params, subset, scfg, log=lambda *a: None, cache_dir=cache_dir, use_cache=use_cache)
        return loss_of(cls, items, subset)

    best = evaluate(p)
    base = best
    changes = []
    t0 = time.time()
    for rnd in range(max_rounds):
        moved = False
        for k, spec in fit_params.items():
            lo, hi = spec["bounds"]
            for sign in (1, -1):
                trial = dict(p)
                trial[k] = float(np.clip(p[k] + sign * spec["max_step"], lo, hi))
                if trial[k] == p[k]:
                    continue
                L = evaluate(trial)
                if L < best - tol:
                    changes.append({"param": k, "from": p[k], "to": trial[k], "loss_before": round(best, 3), "loss_after": round(L, 3), "round": rnd})
                    p, best, moved = trial, L, True
                    log("fit: %s %g -> %g (loss %.2f -> %.2f)" % (k, changes[-1]["from"], trial[k], changes[-1]["loss_before"], L))
                    break
        if not moved:
            break
    log("fit: loss %.2f -> %.2f, %d changes, %.0f s" % (base, best, len(changes), time.time() - t0))
    return {"n_residuals": len(items), "dates": [dates[0], dates[-1]], "loss_before": round(base, 3), "loss_after": round(best, 3),
            "changes": changes, "params": {k: p[k] for k in fit_params}, "residual_ids": [it["id"] for it in items]}


def apply(proposal, recs, day, log=print):
    """write the fitted values into snow_config.yaml (values only, comments kept) and param records into the ledger"""
    if not proposal.get("changes"):
        return 0
    final = {}
    for ch in proposal["changes"]:
        final[ch["param"]] = ch["to"]
    with open(CONFIG, encoding="utf-8") as f:
        lines = f.read().split("\n")
    out = []
    in_state = False
    for line in lines:
        if line.startswith("state:"):
            in_state = True
        elif line and not line.startswith(" ") and not line.startswith("#"):
            in_state = False
        if in_state:
            for k, v in final.items():
                key = "  %s: {value: " % k
                if line.startswith(key):
                    rest = line[len(key):]
                    end = rest.index(",")
                    line = key + ("%g" % v) + rest[end:]
        out.append(line)
    with open(CONFIG, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(out))
    firsts = {}
    for ch in proposal["changes"]:
        firsts.setdefault(ch["param"], ch["from"])
    recs_new = [{"param": k, "from": firsts[k], "to": v, "loss_before": proposal["loss_before"], "loss_after": proposal["loss_after"],
                 "n_residuals": proposal["n_residuals"], "residual_ids": proposal["residual_ids"][:200]} for k, v in final.items()]
    ledger.append(recs, recs_new, day, "param")
    log("fit: applied %d parameter changes to snow_config.yaml" % len(final))
    return len(final)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--no-upload", action="store_true")
    a = ap.parse_args()
    day = dt.date.today().isoformat()
    recs = ledger.load()
    lat, meta = replay.load_lattice()
    proposal = fit(recs, lat, meta)
    proposal["date"] = day
    os.makedirs(store.local("fit"), exist_ok=True)
    with open(store.local("fit/%s.json" % day), "w", encoding="utf-8") as f:
        json.dump(proposal, f, indent=1)
    if not a.no_upload:
        store.put("fit/%s.json" % day, "public, max-age=3600")
    if a.apply and proposal.get("changes"):
        apply(proposal, recs, day)
        ledger.save(recs, upload=not a.no_upload)
    print(json.dumps({k: v for k, v in proposal.items() if k != "residual_ids"}, indent=1))


if __name__ == "__main__":
    main()
