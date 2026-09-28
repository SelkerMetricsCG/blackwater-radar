"""
Build radar/webcams_extra.json (the curated conditions-camera list webcams.py reads) from combined.json,
applying Chris's decisions of 2026-09-27:
  - out: YouTube thumbnails, SeeJH, Ambient Weather, ipcamlive/webcam.io (owner consent) except the
    webcam.io cams the parks publish through the NPS API, cams that need a page scrape each run,
    cams that answered 401/403/404/410 at the last check
  - in: Nest public share links, robots.txt-disallowed images (browsers load them; the job never
    fetches them), ColoradoWebcam.net (credit + link), the Gorge hobby sites
  - USGS river, USGS volcano and NOAA buoy cams are left out here: webcams.py pulls them live each hour
  - USCG bar cams that TripCheck serves are dropped when AlertWest already has a camera within 300 m
YouTube-live cameras are not built here: they live in radar/webcams_youtube.json (kept by hand, read by
webcams.py through youtube.py and the YouTube Data API), which this script never touches, so a rebuild keeps them.

Run from this folder:  python make_extra.py <folder with AlertWest webcams.js copies>
"""
import glob
import json
import math
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), "webcams_extra.json")
LIVE_FEEDS = ("USGS HIVIS", "USGS Ashcam (VolcView)", "NOAA NDBC BuoyCAM")
WATER = {"surf", "wind", "bar", "harbor", "lake", "buoy"}


def kind(c):
    cat = c["category"]
    if cat == "ski":
        return "ski"
    if cat in WATER:
        return "water"
    if cat == "river":
        return "river"
    if cat in ("park", "volcano"):
        return "park"
    if cat == "other" and re.search(r"beach|lighthouse|marina|lake|bay|harbou?r", c["name"], re.I):
        return "water"
    return "town"


def km(a, b):
    dy = (a[0] - b[0]) * 111.2
    dx = (a[1] - b[1]) * 111.2 * math.cos(math.radians(a[0]))
    return math.hypot(dx, dy)


def alertwest_points(folder):
    pts = []
    for f in glob.glob(os.path.join(folder, "*.js")):
        t = open(f, encoding="utf-8").read()
        pts += [(c["lat"], c["lon"]) for c in json.loads(t[t.index("=") + 1:].strip().rstrip(";"))["cams"]]
    return pts


def main(aw_folder):
    d = json.load(open(os.path.join(HERE, "combined.json"), encoding="utf-8"))
    aw = alertwest_points(aw_folder)
    if not aw:
        raise SystemExit("no AlertWest webcams.js copies found in %s" % aw_folder)
    out, dropped = [], {}

    def drop(why):
        dropped[why] = dropped.get(why, 0) + 1

    for c in d["cams"]:
        fl = set(c["flags"])
        if c.get("provider") in LIVE_FEEDS:
            drop("live feed")
            continue
        if fl & {"youtube", "seejh", "ambient"}:
            drop("youtube/seejh/ambient")
            continue
        if "consent" in fl and "feeds" not in c["from"]:
            drop("owner consent")
            continue
        if c.get("resolver") or c.get("img_resolver"):
            drop("needs page scrape")
            continue
        if c.get("recheck", {}).get("http") in (401, 403, 404, 410):
            drop("refused at last check")
            continue
        if "tripcheck" in fl and any(km((c["lat"], c["lon"]), p) < 0.3 for p in aw):
            drop("already in AlertWest")
            continue
        rec = {"name": c["name"], "kind": kind(c), "lat": c["lat"], "lon": c["lon"], "img": c["img"],
               "page": c.get("page") or "", "owner": c.get("owner") or "", "provider": c.get("provider") or ""}
        if "robots" in fl:
            rec["robots"] = True  # hotlink only; the hourly job must not fetch it
        if c.get("snow_stake"):
            rec["stake"] = True
        out.append(rec)

    out.sort(key=lambda r: (r["kind"], r["name"]))
    with open(OUT, "w", encoding="utf-8") as f:
        f.write('{"note": "Curated conditions cameras for webcams.py; built by cams_research/make_extra.py '
                'from the 2026-09-26 research. Edit by hand or rebuild.",\n "cams": [\n')
        f.write(",\n".join(json.dumps(r, ensure_ascii=False) for r in out))
        f.write("\n]}\n")
    from collections import Counter
    print("wrote %d cams to %s" % (len(out), OUT))
    print("by kind:", dict(Counter(r["kind"] for r in out)))
    print("dropped:", dropped)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else ".")
