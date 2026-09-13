"""
NWAC avalanche forecast zones (via the avalanche.org public API).

Writes data/avalanche.js -> window.AVALANCHE = GeoJSON FeatureCollection with
danger level, color, travel advice, dates and a link per zone. Off season the
zones carry 'no rating'.

Run standalone:  python avalanche.py
"""
import datetime as dt
import json
import os
import time
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data")
OUT = os.path.join(DATA, "avalanche.js")
UA = "RadarTracker/1.0 (personal weather map; chris.gabrielli@gmail.com)"
URL = "https://api.avalanche.org/v2/public/products/map-layer/NWAC"
KEEP = ("name", "danger", "danger_level", "travel_advice", "start_date", "end_date", "link", "color",
        "fillOpacity", "off_season", "center", "warning")


def build(log=print):
    req = urllib.request.Request(URL, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        g = json.load(r)
    feats = []
    for f in g.get("features", []):
        p = f.get("properties", {})
        props = {k: p.get(k) for k in KEEP}
        w = props.get("warning") or {}
        props["warning"] = (w.get("product") or {}).get("title") if isinstance(w, dict) else None
        feats.append({"type": "Feature", "properties": props, "geometry": f.get("geometry")})
    data = {"type": "FeatureCollection", "features": feats,
            "updated": dt.datetime.now().strftime("%a %b %d %I:%M %p"), "updated_t": int(time.time())}
    os.makedirs(DATA, exist_ok=True)
    with open(OUT + ".tmp", "w", encoding="utf-8") as f:
        f.write("window.AVALANCHE = %s;\n" % json.dumps(data, separators=(",", ":")))
    os.replace(OUT + ".tmp", OUT)
    log("avalanche: %d zones, %s" % (len(feats), ", ".join(sorted(set(x["properties"]["danger"] or "?" for x in feats)))))
    return len(feats)


if __name__ == "__main__":
    build()
