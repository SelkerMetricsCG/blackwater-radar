"""
Active NWS watches, warnings and advisories for WA, OR, ID, MT as map polygons.

Most alerts reference forecast zones rather than carrying their own shape, so
zone outlines are fetched once from api.weather.gov and cached in
data/zone_cache.json. Output: data/alerts.js -> window.ALERTS = {updated, features:[...]}

Run standalone:  python alerts.py
"""
import datetime as dt
import json
import os
import time
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data")
OUT = os.path.join(DATA, "alerts.js")
ZONES = os.path.join(DATA, "zone_cache.json")
UA = "RadarTracker/1.0 (personal weather map; chris.gabrielli@gmail.com)"
URL = "https://api.weather.gov/alerts/active?area=WA,OR,ID,MT&status=actual&message_type=alert,update"


def fetch(url, timeout=30, tries=2):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/geo+json"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(2 + 2 * i)
    raise last


def _round(coords):
    if isinstance(coords[0], (int, float)):
        return [round(coords[0], 4), round(coords[1], 4)]
    return [_round(c) for c in coords]


def build(log=print):
    try:
        with open(ZONES, encoding="utf-8") as f:
            zones = json.load(f)
    except (OSError, ValueError):
        zones = {}
    alerts = json.loads(fetch(URL))
    feats = []
    fetched = 0
    keep = ("id", "event", "severity", "urgency", "certainty", "headline", "description", "instruction",
            "senderName", "areaDesc", "onset", "ends", "expires", "effective")
    for f in alerts.get("features", []):
        p = f["properties"]
        props = {k: p.get(k) for k in keep}
        if props.get("description"):
            props["description"] = props["description"][:2500]
        geoms = []
        if f.get("geometry"):
            geoms.append(f["geometry"])
        else:
            for zurl in p.get("affectedZones", []):
                if zurl not in zones:
                    try:
                        z = json.loads(fetch(zurl))
                        zones[zurl] = z.get("geometry")
                        fetched += 1
                    except Exception as e:  # noqa: BLE001
                        log("zone %s failed: %r" % (zurl, e))
                        zones[zurl] = None
                if zones.get(zurl):
                    geoms.append(zones[zurl])
        for g in geoms:
            feats.append({"type": "Feature", "properties": props,
                          "geometry": {"type": g["type"], "coordinates": _round(g["coordinates"])}})
    if fetched:
        with open(ZONES + ".tmp", "w", encoding="utf-8") as f:
            json.dump(zones, f)
        os.replace(ZONES + ".tmp", ZONES)
    data = {"updated": dt.datetime.now().strftime("%a %b %d %I:%M %p"), "updated_t": int(time.time()),
            "count": len(alerts.get("features", [])), "features": feats}
    os.makedirs(DATA, exist_ok=True)
    with open(OUT + ".tmp", "w", encoding="utf-8") as f:
        f.write("window.ALERTS = %s;\n" % json.dumps(data, separators=(",", ":")))
    os.replace(OUT + ".tmp", OUT)
    log("alerts: %d active, %d shapes (%d new zones fetched)" % (data["count"], len(feats), fetched))
    return data["count"]


if __name__ == "__main__":
    build()
