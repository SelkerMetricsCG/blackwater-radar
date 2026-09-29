"""
The ledger: dated, structured facts with sources, the snow model's memory across the season. Append-only records in
<region>/snow/ledger/ledger.json (a list; small enough to rewrite daily). Record kinds (see the spec):

  obs       an extracted field observation: date, source, location, zone, band, aspects, surface class seen, confidence
  residual  predicted class vs observed class for one obs (snow/score.py)
  layer     a persistent weak layer snapshot: name, status (active / dormant / healed), zones, bands, buried, first,
            last (a mention), evidence (product ids). The current table is the latest snapshot per name.
  note      an LLM model note with the evidence it cites
  param     a parameter change with the residuals that drove it (the fit, later)
  trip      Chris's own trip record (snow/trips.json, same fields as obs)
  assim     what a report nudged in the state (snow/assimilate.py): cells, weight

Never a brief: the brief is regenerated each day from the last weeks of this file.
"""
import datetime as dt
import json
import os

from snow import store

REL = "ledger/ledger.json"
KINDS = ("obs", "residual", "layer", "note", "param", "trip", "assim")


def load(log=print):
    recs = store.read_json(REL, log)
    return recs if isinstance(recs, list) else []


def save(recs, upload=True, log=print):
    path = store.local(REL)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        json.dump(recs, f, separators=(",", ":"))
    os.replace(path + ".tmp", path)
    if upload:
        store.put(REL, "no-cache", log)
    return len(recs)


def append(recs, new, date, kind):
    """add records of one kind for one date with ids kind_date_n; returns the records added"""
    assert kind in KINDS, kind
    n0 = sum(1 for r in recs if r.get("kind") == kind and r.get("date") == date)
    out = []
    for i, r in enumerate(new):
        rec = dict(r, kind=kind, date=date, id="%s_%s_%d" % (kind, date, n0 + i))
        recs.append(rec)
        out.append(rec)
    return out


def recent(recs, end_date, days, kinds=None):
    start = (dt.date.fromisoformat(end_date) - dt.timedelta(days=days)).isoformat()
    return [r for r in recs if start <= r.get("date", "") <= end_date and (kinds is None or r.get("kind") in kinds)]


def layers(recs, dormant_after_days=21, today=None):
    """the current weak-layer table: latest snapshot per name; active layers unmentioned for dormant_after_days
    are reported dormant (never deleted in season)"""
    table = {}
    for r in recs:
        if r.get("kind") == "layer" and r.get("name"):
            table[r["name"]] = r
    if today:
        cut = (dt.date.fromisoformat(today) - dt.timedelta(days=dormant_after_days)).isoformat()
        for name, r in table.items():
            if r.get("status") == "active" and (r.get("last") or r.get("date", "")) < cut:
                table[name] = dict(r, status="dormant")
    return table


def trips(log=print):
    """Chris's trip records from snow/trips.json in the repo (a list of obs-shaped dicts), or []"""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "trips.json")
    try:
        with open(path, encoding="utf-8") as f:
            t = json.load(f)
        return t if isinstance(t, list) else []
    except (OSError, ValueError):
        return []
