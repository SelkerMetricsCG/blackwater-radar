"""
Webcam layer: AlertWest camera network (fire-detection PTZ cameras plus the state
DOT road cameras they aggregate) inside the map window.

Output: data/webcams.js -> window.WEBCAMS = {updated, cams:[{id, name, lat, lon, pan, fov,
img, ts, kind, src, link}]}. Image URLs point at alertwest.live; the map refreshes
them with a cache-busting query when a popup opens.

Run standalone:  python webcams.py
"""
import datetime as dt
import json
import os
import re
import time
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data")
OUT = os.path.join(DATA, "webcams.js")
UA = "Mozilla/5.0 (RadarTracker personal weather map; chris.gabrielli@gmail.com)"
URL = "https://alertwest.live/api/getCameraDataByLoc"
LAT0, LAT1, LON0, LON1 = 43.1, 52.5, -126.6, -112.5
STATES = ("WA", "OR", "ID", "MT", "BC")


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def image_url(cam):
    img = cam.get("img") or ""
    m = re.search(r"_(\d{10})_", img)
    if not m:
        return None, None
    ts = int(m.group(1))
    day = dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y/%m/%d")
    return "https://alertwest.live/data/img/%s/%s/%s" % (cam["id"], day, img), ts


def build(log=print):
    d = json.loads(fetch(URL))["data"]
    locs = {l["id"]: l for l in d["locs"]["data"]}
    out = []
    for c in d["cams"]["data"]:
        loc = locs.get(c.get("lid"))
        if not loc or loc.get("st") not in STATES or c.get("off"):
            continue
        try:
            lat, lon = float(loc["lat"]), float(loc["lon"])
        except (TypeError, ValueError):
            continue
        if not (LAT0 <= lat <= LAT1 and LON0 <= lon <= LON1):
            continue
        url, ts = image_url(c)
        if not url:
            continue
        name = (c.get("cn") or "").replace("_", " ").strip()
        road = str(c.get("typ")) == "15" or name.split(" ")[0] in ("I-90", "US", "SR", "I-5", "I-82", "I-84", "OR", "ID", "US-2")
        rec = {"id": c["id"], "name": name, "lat": round(lat, 5), "lon": round(lon, 5),
               "img": url, "ts": ts, "kind": "road" if road else "fire",
               "src": (c.get("sp") or c.get("pr") or "AlertWest").strip() or "AlertWest",
               "link": "https://alertwest.live/"}
        if not road:
            try:
                rec["pan"] = round(float(c.get("p")), 1)
                rec["fov"] = round(float(c.get("fov")), 1)
            except (TypeError, ValueError):
                pass
        out.append(rec)
    data = {"updated": dt.datetime.now().strftime("%a %b %d %I:%M %p"), "updated_t": int(time.time()), "cams": out}
    os.makedirs(DATA, exist_ok=True)
    with open(OUT + ".tmp", "w", encoding="utf-8") as f:
        f.write("window.WEBCAMS = %s;\n" % json.dumps(data, separators=(",", ":")))
    os.replace(OUT + ".tmp", OUT)
    log("webcams: %d cameras (%d road, %d fire)" % (len(out), sum(1 for x in out if x["kind"] == "road"), sum(1 for x in out if x["kind"] == "fire")))
    return len(out)


if __name__ == "__main__":
    build()
