"""
Ski areas and the snow totals the resorts themselves report.
Every operating, lift-served downhill area inside the window comes from ski_areas.json (built from
OpenSkiMap by ski_research/build_ski_areas.py; ODbL, credited on the page). Areas with an `mp` id are
on the Ikon/Alterra resort feed (mtnpowder.com/feed?resortId=N, the JSON the resort websites load):
one request each per hourly run gives new snow 24/48/72 h and 7 days at base, mid-mountain and
summit, storm and season totals and the base depth, as inches, with the resort's own report time.
Everything else gets a marker that links to the resort's report or website.
Writes data/ski.js -> window.SKI = {areas: [...], updated, updated_t}.
Run standalone:  python ski.py   (or REGION=utco python ski.py)
"""
import datetime as dt
import json
import os
import re
import time
import urllib.request

import region

ROOT = os.path.dirname(os.path.abspath(__file__))
LIST = os.path.join(ROOT, "ski_areas.json")
DATA = region.data_dir()
OUT = os.path.join(DATA, "ski.js")
FEED = "https://mtnpowder.com/feed?resortId=%d"
UA = "BlackwaterRadar/1.0 (+https://radar.blackwaterlabs.org)"
TIMEOUT = 20
PAUSE = 0.3          # between resorts: about a dozen per region, once an hour
POINTS = (("BaseArea", "base"), ("MidMountainArea", "mid"), ("SummitArea", "summit"))
FIELDS = (("BaseIn", "base"), ("Last24HoursIn", "h24"), ("Last48HoursIn", "h48"), ("Last72HoursIn", "h72"),
          ("Last7DaysIn", "d7"), ("SinceLiftsClosedIn", "closed"))


def num(s):
    """'10' -> 10, '0.5' -> 0.5, '--' / '' / None -> None"""
    if s is None or isinstance(s, bool):
        return None
    if isinstance(s, (int, float)):
        v = float(s)
    else:
        s = str(s).strip().replace('"', "")
        if not s or s == "--":
            return None
        try:
            v = float(s)
        except ValueError:
            return None
    return int(v) if v == int(v) else round(v, 1)


def base_range(s):
    """'37 - 70' -> [37, 70]; '55' -> [55, 55]; '--' -> None"""
    if not s or s == "--":
        return None
    parts = re.findall(r"\d+(?:\.\d+)?", str(s))
    if not parts:
        return None
    lo, hi = num(parts[0]), num(parts[-1])
    return [lo, hi]


def when(s):
    """'2026-06-07T11:01:49-0700' -> epoch seconds, or None"""
    try:
        return int(dt.datetime.strptime(s, "%Y-%m-%dT%H:%M:%S%z").timestamp())
    except (TypeError, ValueError):
        return None


def parse_report(feed):
    """The resort's snow report from one feed answer, or None when it carries none."""
    s = (feed or {}).get("SnowReport")
    if not isinstance(s, dict) or not s.get("LastUpdate"):
        return None
    pts = []
    for key, kind in POINTS:
        a = s.get(key)
        if not isinstance(a, dict):
            continue
        name = (a.get("Name") or "").strip()
        vals = {short: num(a.get(k)) for k, short in FIELDS}
        if name in ("", "--") and all(v is None for v in vals.values()):
            continue
        pt = {"kind": kind, "name": name if name not in ("", "--") else kind.title()}
        pt.update({k: v for k, v in vals.items() if v is not None})
        pts.append(pt)
    rep = {"t": when(s["LastUpdate"]), "status": feed.get("OperatingStatus") or None,
           "storm": num(s.get("StormTotalIn")), "season": num(s.get("SeasonTotalIn")),
           "base": base_range(s.get("SnowBaseRangeIn")), "pts": pts}
    return {k: v for k, v in rep.items() if v is not None}


def fetch(mp):
    req = urllib.request.Request(FEED % mp, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.load(r)


def areas_in_window(path=LIST):
    lat0, lat1, lon0, lon1 = region.bbox()
    with open(path, encoding="utf-8") as f:
        return [a for a in json.load(f) if lat0 <= a["lat"] <= lat1 and lon0 <= a["lon"] <= lon1]


def build(log=print, areas=None, fetch_fn=fetch, out=OUT):
    areas = [dict(a) for a in (areas if areas is not None else areas_in_window())]
    n_feed = n_rep = n_fail = 0
    for a in areas:
        if a.get("mp") is None:
            continue
        n_feed += 1
        try:
            rep = parse_report(fetch_fn(a["mp"]))
        except Exception as e:  # noqa: BLE001
            n_fail += 1
            log("ski: %s (feed %s) failed: %r" % (a["name"], a["mp"], e))
            rep = None
        if rep:
            a["rep"] = rep
            n_rep += 1
        else:
            a["rep"] = None                # on the feed, but no report right now
        if fetch_fn is fetch:
            time.sleep(PAUSE)
    data = {"areas": areas, "updated": dt.datetime.now().strftime("%a %b %d %I:%M %p"), "updated_t": int(time.time())}
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out + ".tmp", "w", encoding="utf-8") as f:
        f.write("window.SKI = %s;\n" % json.dumps(data, separators=(",", ":"), ensure_ascii=False))
    os.replace(out + ".tmp", out)
    log("ski: %d areas, %d on the resort feed, %d with a report, %d failed" % (len(areas), n_feed, n_rep, n_fail))
    return len(areas)


if __name__ == "__main__":
    build()
