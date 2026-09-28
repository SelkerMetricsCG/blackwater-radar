"""
Full avalanche forecast products (danger by elevation, problems with their aspect/elevation rose, bottom
line, discussions) for every zone in the window, from the avalanche.org public API that avalanche.py
already uses for the map layer, saved raw into the day's archive folder as
  products/<center>_<zone>_<product id>_<hash>.json
once per version per day: the hash covers the fields that change when a forecaster edits a product, so
a re-issued product is a new file and an unchanged one is not fetched again into the same day.

The product endpoint (`/v2/public/product?type=forecast&center_id=..&zone_id=..`) is the one the
centers' own sites call; only the map layer is in NAC's public docs. Its shape is stored as received,
so nothing downstream depends on this module's guesses about it. Off season the endpoint returns an
empty or summary product; those are kept too (they say the season has not started).
"""
import hashlib
import json
import os
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UA = "RadarTracker/1.0 (personal weather map; chris.gabrielli@gmail.com)"
URL = "https://api.avalanche.org/v2/public/product?type=forecast&center_id=%s&zone_id=%s"
STABLE = ("id", "product_type", "published_time", "updated_at", "expires_time", "bottom_line", "hazard_discussion",
          "danger", "forecast_avalanche_problems")
MAX_PER_ZONE_DAY = 4      # a runaway hash (some field that changes each fetch) can never fill the archive


def fetch(center, zone, timeout=60):
    req = urllib.request.Request(URL % (center, zone), headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read()
    return json.loads(body) if body.strip() else None


def zones(log=print):
    """[(center_id, zone_id, name)] from the avalanche layer built earlier this run (or its file)"""
    import avalanche
    feats = (avalanche._LAST.get("features") if avalanche._LAST.get("features") is not None else None)
    if feats is None:
        from snow.archive import read_js
        g = read_js(avalanche.OUT)
        feats = (g or {}).get("features") or []
    out = []
    for f in feats:
        p = f.get("properties") or {}
        if p.get("center_id") and p.get("zone_id") is not None:
            out.append((p["center_id"], p["zone_id"], p.get("name")))
    return out


def product_key(p):
    """'<id>_<hash8>': the id plus a hash of the fields a forecaster edits (all of it when none of those exist)"""
    if not isinstance(p, dict):
        p = {"_": p}
    sub = {k: p.get(k) for k in STABLE if k in p} or p
    h = hashlib.sha1(json.dumps(sub, sort_keys=True, default=str).encode()).hexdigest()[:8]
    return "%s_%s" % (p.get("id") if p.get("id") is not None else "na", h)


def build(day_dir, have, log=print):
    """fetch every zone's current product; write the ones not yet in `have` (names relative to day_dir)"""
    n_new, n_fail = 0, 0
    for center, zone, name in zones(log):
        prefix = "products/%s_%s_" % (center, zone)
        if sum(1 for k in have if k.startswith(prefix)) >= MAX_PER_ZONE_DAY:
            continue
        try:
            p = fetch(center, zone)
        except Exception as e:  # noqa: BLE001
            n_fail += 1
            log("products: %s %s (%s) failed: %r" % (center, zone, name, e))
            continue
        if p is None:
            continue
        fn = prefix + product_key(p) + ".json"
        if fn in have:
            continue
        path = os.path.join(day_dir, fn)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path + ".tmp", "w", encoding="utf-8") as f:
            json.dump(p, f, separators=(",", ":"))
        os.replace(path + ".tmp", path)
        have.add(fn)
        n_new += 1
    if n_fail:
        log("products: %d zones failed" % n_fail)
    return n_new
