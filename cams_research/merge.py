"""
Merge the research agents' camera lists into combined.json, dedupe, flag the ones that need
Chris's decision, and re-fetch every image once (browser UA, radar Referer, cache-buster).

Run from this folder:  python merge.py [--no-check]
Inputs: feeds/towns/towns2/ski_north/ski_south/wind_water.json here, plus the Roundshot
positions list (rs_na_positions.json) if present.
"""
import concurrent.futures as cf
import datetime as dt
import json
import math
import os
import re
import sys

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
FILES = ["feeds", "towns", "towns2", "ski_north", "ski_south", "wind_water"]
H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128 Safari/537.36",
     "Referer": "https://radar.blackwaterlabs.org/"}

# host or URL fragment -> flag. Flags mark cams that wait on a decision; they are not verdicts.
FLAG_RULES = [
    ("ipcamlive.com", "consent"), ("webcam.io", "consent"),
    ("ytimg.com", "youtube"), ("seejh", "seejh"), ("nest.com", "nest"), ("dropcam", "nest"),
    ("ambientweather", "ambient"), ("niknas.net", "hobby"), ("sauviewind.net", "hobby"),
    ("tripcheck.com", "tripcheck"), ("coloradowebcam.net", "coloradowebcam"),
    ("phenocam.nau.edu", "robots"),
]


def roundshot_id(url):
    m = re.search(r"backend\.roundshot\.com/cams/([0-9a-f]+)", url or "")
    return m.group(1) if m else None


def key(c):
    rid = roundshot_id(c["img"])
    if rid:
        return "roundshot:" + rid
    return re.sub(r"[?&]t=\d+$", "", c["img"].strip()).lower()


def roundshot_cams():
    path = os.path.join(HERE, "rs_na_positions.json")
    if not os.path.exists(path):
        return []
    out = []
    for r in json.load(open(path, encoding="utf-8")):
        rid = roundshot_id(r.get("picture"))
        if not r.get("boxes") or not rid or not rid.isdigit() or r.get("status") == "broken":
            continue
        out.append({"name": r["name"], "category": "ski" if "Ski" in (r.get("category") or "") else "town",
                    "lat": round(r["lat"], 5), "lon": round(r["lon"], 5), "coord_source": "provider",
                    "region": r["boxes"][0], "img": "https://backend.roundshot.com/cams/%s/centerprev" % rid,
                    "page": r["link"], "owner": r["name"].split(" - ")[0], "provider": "Roundshot",
                    "terms": "Roundshot Livecam Service Conditions 2026-01-28: third-party preview display allowed; credit owner + Roundshot",
                    "notes": "from Roundshot's public references list; status %s" % r.get("status")})
    return out


def km(a, b):
    dy = (a["lat"] - b["lat"]) * 111.2
    dx = (a["lon"] - b["lon"]) * 111.2 * math.cos(math.radians(a["lat"]))
    return math.hypot(dx, dy)


def check(c):
    if "robots" in c["flags"]:
        return {"skipped": "robots.txt disallows server fetches"}
    url = c["img"] + ("&" if "?" in c["img"] else "?") + "t=%d" % int(dt.datetime.now().timestamp())
    try:
        r = requests.get(url, headers=H, timeout=20)
        body = r.content
        ctype = r.headers.get("content-type", "")
        is_img = ctype.startswith("image/") or body[:2] == b"\xff\xd8" or body[:4] == b"\x89PNG"
        res = {"http": r.status_code, "content_type": ctype, "bytes": len(body),
               "last_modified": r.headers.get("last-modified"), "ok": r.status_code == 200 and is_img and len(body) > 5000}
        if "brownrice" in c["img"] and body[:4] == b"\x89PNG":
            res["ok"], res["note"] = False, "Brownrice offline card (PNG)"
        return res
    except Exception as e:
        return {"ok": False, "error": type(e).__name__}


def main():
    cams, http_only, video = [], [], []
    for f in FILES:
        d = json.load(open(os.path.join(HERE, f + ".json"), encoding="utf-8"))
        for c in d["cams"]:
            c["from"] = [f]
            cams.append(c)
        for c in d.get("http_only", []):
            c["from"] = [f]
            http_only.append(c)
        for c in d.get("video_only", []):
            c["from"] = f
            video.append(c)
    for c in roundshot_cams():
        c["from"] = ["providers"]
        cams.append(c)

    merged = {}
    for c in cams:
        k = key(c)
        if k in merged:
            m = merged[k]
            m["from"] = sorted(set(m["from"]) | set(c["from"]))
            if m.get("coord_source") == "estimated" and c.get("coord_source") == "provider":
                m["lat"], m["lon"], m["coord_source"] = c["lat"], c["lon"], "provider"
        else:
            merged[k] = c
    cams = list(merged.values())

    for c in cams:
        u = c["img"].lower()
        fl = {flag for frag, flag in FLAG_RULES if frag in u}
        if c.get("consent_needed"):
            fl.add("consent")
        if c.get("robots_disallows_img"):
            fl.add("robots")
        if "nest" in (c.get("provider") or "").lower():
            fl.add("nest")
        c["flags"] = sorted(fl)

    # pairs of distinct cams within 150 m: possible duplicates to eyeball (e.g. USGS re-hosting a ski cam)
    near = []
    for i, a in enumerate(cams):
        for b in cams[i + 1:]:
            if abs(a["lat"] - b["lat"]) < 0.002 and km(a, b) < 0.15:
                near.append([a["name"], b["name"], round(km(a, b) * 1000)])

    if "--no-check" not in sys.argv:
        with cf.ThreadPoolExecutor(12) as ex:
            for c, res in zip(cams, ex.map(check, cams)):
                c["recheck"] = res

    out = {"built_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M"),
           "cams": cams, "http_only": http_only, "video_only": video, "near_pairs": near}
    with open(os.path.join(HERE, "combined.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1, ensure_ascii=False)

    from collections import Counter
    ok = [c for c in cams if c.get("recheck", {}).get("ok")]
    skipped = [c for c in cams if "skipped" in c.get("recheck", {})]
    print("cams %d (after dedupe), recheck ok %d, failed %d, skipped %d; http_only %d; video_only %d; near pairs %d"
          % (len(cams), len(ok), len(cams) - len(ok) - len(skipped), len(skipped), len(http_only), len(video), len(near)))
    print("by category:", dict(Counter(c["category"] for c in cams).most_common()))
    print("by region:", dict(Counter(c["region"] for c in cams).most_common()))
    print("flags:", dict(Counter(f for c in cams for f in c["flags"]).most_common()))
    print("clean (no flags) and ok:", sum(1 for c in ok if not c["flags"]))


if __name__ == "__main__":
    main()
