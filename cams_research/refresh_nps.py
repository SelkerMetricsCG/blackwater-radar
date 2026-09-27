"""
Refresh the National Park Service cameras in radar/webcams_extra.json from the NPS Data API.

The key is only needed for the camera list; the images themselves load without it. Put the key in
radar/nps.env (gitignored) as a single line  NPS_API_KEY=...  and run from radar/:

    python cams_research/refresh_nps.py

Replaces every entry whose provider is "NPS webcams" and keeps everything else as it is; each image is
fetched once from this PC and left out if it doesn't load. Covers every region in region.py (including ne). Takes a few minutes the first time: each camera's page is read once
to find its image, and the answers are cached in cams_research/nps_img_cache.json.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RADAR = os.path.dirname(HERE)
sys.path.insert(0, RADAR)
sys.path.insert(0, HERE)

import region  # noqa: E402

EXTRA = os.path.join(RADAR, "webcams_extra.json")
ENV = os.path.join(RADAR, "nps.env")


def main():
    if not os.environ.get("NPS_API_KEY") and os.path.exists(ENV):
        for line in open(ENV, encoding="utf-8"):
            k, _, v = line.strip().partition("=")
            if k == "NPS_API_KEY" and v:
                os.environ["NPS_API_KEY"] = v.strip()
    if not os.environ.get("NPS_API_KEY"):
        raise SystemExit("no key: put NPS_API_KEY=... in %s" % ENV)

    import build_feeds  # reads NPS_API_KEY from the environment
    boxes = {}
    for key, cfg in region.REGIONS.items():
        x0, x1, y0, y1 = cfg["tiles"]
        boxes[key] = (region.tile_lat(y1 + 1), region.tile_lat(y0), region.tile_lon(x0), region.tile_lon(x1 + 1))
    build_feeds.BOXES = boxes

    import concurrent.futures as cf
    import webcams
    listed = build_feeds.nps()
    # checked from this PC, not a cloud runner, so a failure here means the camera is really down
    with cf.ThreadPoolExecutor(12) as ex:
        states = list(ex.map(lambda c: webcams.check_image(c["img"])[0], listed))
    dead = [c["name"] for c, s in zip(listed, states) if s != "ok"]
    if dead:
        print("left out, no image now: %s" % "; ".join(dead))
    fresh = [{"name": c["name"], "kind": "park", "lat": c["lat"], "lon": c["lon"], "img": c["img"],
              "page": c["page"], "owner": c["owner"], "provider": "NPS webcams"}
             for c, s in zip(listed, states) if s == "ok"]
    d = json.load(open(EXTRA, encoding="utf-8"))
    kept = [c for c in d["cams"] if c.get("provider") != "NPS webcams"]
    old = len(d["cams"]) - len(kept)
    cams = sorted(kept + fresh, key=lambda r: (r["kind"], r["name"]))
    with open(EXTRA, "w", encoding="utf-8") as f:
        f.write('{"note": %s,\n "cams": [\n' % json.dumps(d.get("note", "")))
        f.write(",\n".join(json.dumps(r, ensure_ascii=False) for r in cams))
        f.write("\n]}\n")
    print("NPS cameras: %d before, %d now; webcams_extra.json has %d cameras" % (old, len(fresh), len(cams)))


if __name__ == "__main__":
    main()
