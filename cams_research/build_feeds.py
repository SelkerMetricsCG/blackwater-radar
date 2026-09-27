"""
Build a conditions-camera list for radar.blackwaterlabs.org from keyless public feeds.

Sources (all US federal, public domain unless a camera is re-hosted from a third party):
  usgs_hivis  USGS HIVIS / NIMS streamgage cameras   api.waterdata.usgs.gov/nims/cameras   (keyless JSON)
  usgs_ashcam USGS volcano webcams (Ashcam)          volcview.wr.usgs.gov/ashcam-api       (keyless JSON)
  ndbc        NOAA NDBC BuoyCAMs                     www.ndbc.noaa.gov/buoycams.php        (keyless JSON)
  nps         National Park Service webcams          developer.nps.gov/api/v1/webcams      (api.data.gov key;
              the live-image URL is not in the API, it is read once from each camera's nps.gov view page
              and cached, so the hourly job only needs the cache)

Usage:
  python build_feeds.py                 # all sources, checks every image, writes cams_built.json
  python build_feeds.py usgs_hivis ndbc # just these
  NPS_API_KEY=... python build_feeds.py nps   (DEMO_KEY is used if unset: fine for a one-off, 10 req/h)

Checks per image (the map hotlinks with ?t=<ms>): GET IMAGE?t=..., browser UA, Referer radar.blackwaterlabs.org;
ok = HTTP 200 and image/* and > 2 kB. Stale = newest image older than 24 h (listing timestamp, else Last-Modified).
"""
import datetime as dt
import email.utils
import html
import json
import os
import re
import sys
import time

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "cams_built.json")
NPS_CACHE = os.path.join(HERE, "nps_img_cache.json")

BOT_UA = "BlackwaterLabs-radar-webcams/0.1 (+https://radar.blackwaterlabs.org)"
BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/128 Safari/537.36")
REFERER = "https://radar.blackwaterlabs.org/"

# Region boxes: lat0, lat1, lon0, lon1 (same as the map's regions)
BOXES = {
    "pnw": (43.06, 52.4, -126.6, -112.5),
    "sierra": (31.9, 43.06, -126.6, -112.5),
    "utco": (31.9, 43.06, -115.3, -101.25),
    "imw": (43.06, 50.7, -118.1, -104.1),
}
NOW = dt.datetime.now(dt.timezone.utc)
STALE_H = 24
DROP_AFTER_DAYS = 30  # cameras whose newest image is older than this are left out entirely

S = requests.Session()


def regions(lat, lon):
    return [r for r, (a, b, x, y) in BOXES.items() if a <= lat <= b and x <= lon <= y]


def get_json(url, **kw):
    r = S.get(url, headers={"User-Agent": BOT_UA, "Accept": "application/json"}, timeout=90, **kw)
    r.raise_for_status()
    return r.json()


def age_h(t):
    return None if t is None else (NOW - t).total_seconds() / 3600.0


def check_image(url):
    """Fetch url?t=... the way a viewer's browser would. Returns the per-camera check fields."""
    sep = "&" if "?" in url else "?"
    rec = {"http": None, "content_type": None, "bytes": None, "last_modified": None, "referer_ok": False}
    try:
        r = S.get(url + sep + "t=%d" % int(time.time() * 1000), timeout=45, allow_redirects=True,
                  headers={"User-Agent": BROWSER_UA, "Referer": REFERER, "Accept": "image/avif,image/webp,image/*,*/*"})
        rec["http"] = r.status_code
        rec["content_type"] = r.headers.get("Content-Type", "").split(";")[0]
        rec["bytes"] = len(r.content)
        lm = r.headers.get("Last-Modified")
        if lm:
            rec["last_modified"] = email.utils.parsedate_to_datetime(lm).astimezone(dt.timezone.utc).isoformat()
        rec["referer_ok"] = bool(r.status_code == 200 and rec["content_type"].startswith("image/") and rec["bytes"] > 2000)
        if r.url.startswith("http://"):
            rec["referer_ok"] = False
            rec["note"] = "redirected to http"
    except requests.RequestException as e:
        rec["error"] = str(e)[:200]
    return rec


def base(name, category, lat, lon, img, page, owner, provider, terms, source_id, coord_source, refresh_min, notes=""):
    rs = regions(lat, lon)
    return {"name": name, "category": category, "lat": round(lat, 5), "lon": round(lon, 5),
            "coord_source": coord_source, "region": rs[0], "regions": rs, "img": img, "page": page,
            "owner": owner, "provider": provider, "http": None, "content_type": None, "bytes": None,
            "last_modified": None, "referer_ok": None, "stale": None, "newest_utc": None,
            "refresh_min": refresh_min, "terms": terms, "notes": notes, "source_id": source_id}


# ---------------------------------------------------------------- USGS HIVIS (streamgage cameras)
def usgs_hivis(log=print):
    d = get_json("https://api.waterdata.usgs.gov/nims/cameras?enabled=true")
    out = []
    for c in d:
        try:
            lat, lon = float(c["lat"]), float(c["lng"])
        except (KeyError, TypeError, ValueError):
            continue
        if not regions(lat, lon) or c.get("hideCam"):
            continue
        newest = c.get("newestImageDT")
        t = dt.datetime.fromisoformat(newest.replace("Z", "+00:00")) if newest else None
        if t is None or age_h(t) > DROP_AFTER_DAYS * 24:
            continue
        cam = c["camId"]
        # a few NIMS cams are USGS coastal cams (e.g. Santa Cruz Dream Inn, Sunset State Beach), not gages
        if re.search(r"Test Site", c.get("camName") or ""):
            continue  # USGS field-office test cameras
        if c.get("nwisId") == "888888":
            c["nwisId"] = None  # placeholder id used on non-gage cameras
        coastal = re.search(r"\b(Beach|Inn|Coast|Pier)\b", c.get("camName") or "", re.I) and not c.get("nwisId")
        rec = base(c.get("camName") or cam, "other" if coastal else "river", lat, lon,
                   "%s%s_newest.jpg" % (c["smallDir"], cam),  # 720-px copy; overlayDir has full size
                   "https://apps.usgs.gov/hivis/camera/%s" % cam,
                   "U.S. Geological Survey", "USGS HIVIS",
                   "USGS public domain; credit U.S. Geological Survey", c.get("nwisId") or cam,
                   "USGS NIMS camera listing (lat/lng)", (c.get("ingest") or {}).get("intr"),
                   (c.get("camDesc") or "").strip())
        rec["newest_utc"] = t.isoformat()
        rec["stale"] = age_h(t) > STALE_H
        rec["cam_id"] = cam
        out.append(rec)
    log("usgs_hivis: %d cameras in boxes (visible, image within %d d)" % (len(out), DROP_AFTER_DAYS))
    return out


# ---------------------------------------------------------------- USGS volcano webcams (Ashcam)
SKIP_EXTERNAL = ("wsdot.wa.gov", "faa.gov")  # DOT / FAA views are already in AlertWest


def usgs_ashcam(log=print):
    d = get_json("https://volcview.wr.usgs.gov/ashcam-api/webcamApi/webcams")["webcams"]
    ext_n = {}
    for c in d:
        if c.get("externalUrl"):
            ext_n[c["externalUrl"]] = ext_n.get(c["externalUrl"], 0) + 1
    out = []
    for c in d:
        lat, lon = c.get("latitude"), c.get("longitude")
        if lat is None or lon is None or not regions(lat, lon):
            continue
        ext = c.get("externalUrl") or ""
        if c.get("hasImages") != "Y" or not c.get("lastImageTimestamp") or c.get("faaInd") == "Y":
            continue
        if any(s in ext for s in SKIP_EXTERNAL):
            continue
        t = dt.datetime.fromtimestamp(int(c["lastImageTimestamp"]), dt.timezone.utc)
        if age_h(t) > DROP_AFTER_DAYS * 24:
            continue
        notes = ""
        if ext and ext_n.get(ext, 0) > 1 and re.search(r"-(PR\d+|DIVE)$", c["webcamCode"]):
            # Puyallup lahar-station cams carry a copied externalUrl (NPS Sunrise); PR04's image has no NPS stamp
            notes = "Ashcam externalUrl points at the NPS Sunrise cam but this is a USGS lahar-station view; "
            ext = ""
        host = re.sub(r"^https?://([^/]+).*$", r"\1", ext) if ext else ""
        usgs_own = (not host) or host.endswith("usgs.gov") or host.endswith("unavco.org")
        owner = "U.S. Geological Survey" if usgs_own else "third party (%s), re-hosted by USGS" % host
        if not usgs_own:
            notes += "image is USGS's copy of %s; credit the original owner" % ext
        elif re.search(r"Meadows|Crystal|Bachelor|Timberline|Snowcrest", c["webcamName"]):
            notes += "name suggests a ski-area view re-hosted by USGS (no externalUrl given); owner unconfirmed"
        rec = base(c["webcamName"], "volcano", float(lat), float(lon),
                   c["currentMediumImageUrl"],  # full size: currentImageUrl
                   "https://volcview.wr.usgs.gov/ashcam-gui/webcam.html?webcam=%s" % c["webcamCode"],
                   owner, "USGS Ashcam (VolcView)",
                   "USGS public domain for USGS cameras; re-hosted third-party views keep their owners' rights",
                   c["webcamCode"], "USGS Ashcam listing (camera position, not the volcano)", None, notes)
        rec["newest_utc"] = t.isoformat()
        rec["stale"] = age_h(t) > STALE_H
        rec["volcano"] = c.get("vName")
        rec["bearing_deg"] = c.get("bearingDeg")
        out.append(rec)
    log("usgs_ashcam: %d cameras in boxes" % len(out))
    return out


# ---------------------------------------------------------------- NOAA NDBC BuoyCAMs
def ndbc(log=print):
    d = get_json("https://www.ndbc.noaa.gov/buoycams.php")
    out = []
    for c in d:
        lat, lon = c.get("lat"), c.get("lng")
        if lat is None or not regions(lat, lon) or not c.get("img"):
            continue
        m = re.search(r"_(\d{4})_(\d\d)_(\d\d)_(\d\d)(\d\d)\.jpg$", c["img"])
        t = dt.datetime(*map(int, m.groups()), tzinfo=dt.timezone.utc) if m else None
        rec = base(c["name"].strip(), "buoy", lat, lon,
                   "https://www.ndbc.noaa.gov/images/buoycam/%s" % c["img"],
                   "https://www.ndbc.noaa.gov/station_page.php?station=%s" % c["id"],
                   "NOAA National Data Buoy Center", "NOAA NDBC BuoyCAM",
                   "NOAA public domain; credit NOAA/NDBC", c["id"], "NDBC buoycams.php listing", 60,
                   "6-frame panorama %sx%s, daylight only. File name changes each hour: take it from the hourly "
                   "listing. Stable alternative https://www.ndbc.noaa.gov/buoycam.php?station=%s serves the latest "
                   "image but needs '&t=' (the map currently appends '?t=', which breaks it)."
                   % (c.get("width"), c.get("height"), c["id"]))
        if t:
            rec["newest_utc"] = t.isoformat()
            rec["stale"] = age_h(t) > STALE_H
        out.append(rec)
    log("ndbc: %d buoys with a current image in boxes" % len(out))
    return out


# ---------------------------------------------------------------- National Park Service
def nps_image_from_page(url, cache):
    """Live-image URL for one NPS webcam page (cached: the URLs are stable file names on nps.gov)."""
    m = re.search(r"[?&]site=([a-z0-9]+)", url)
    key = ("air3:" + m.group(1)) if ("/subjects/air/webcams.htm" in url and m) else url
    if key in cache:
        return cache[key]
    img = None
    if key.startswith("air3:"):
        # Air-quality visibility cams: the page's script reads json/<site>json.txt and shows images/<imagefile>
        time.sleep(1.0)
        r = S.get("https://www.nps.gov/featurecontent/ard/webcams/json/%sjson.txt" % m.group(1),
                  headers={"User-Agent": BOT_UA}, timeout=60)
        if r.ok and r.text.lstrip().startswith("{"):
            try:
                j = json.loads(r.text)
                f = j.get("imagefile") or j.get("imagefilelarge")  # ~150 kB; *large.jpg is 1-2.5 MB
                if f:
                    img = "https://www.nps.gov/featurecontent/ard/webcams/images/%s" % f
            except ValueError:
                pass
    elif "/media/webcam/view.htm" in url:
        time.sleep(1.0)
        r = S.get(url, headers={"User-Agent": BOT_UA}, timeout=60)
        if r.ok:
            mm = re.search(r'id="webcamRefreshImage"\s+src="([^"]+)"', r.text) or \
                 re.search(r'<img[^>]+class="Multimedia__Webcam"[^>]*src="([^"]+)"', r.text, re.S)
            if mm:
                img = html.unescape(mm.group(1)).strip()
                if img.startswith("//"):
                    img = "https:" + img
                elif img.startswith("/"):
                    img = "https://www.nps.gov" + img
    cache[key] = img
    return img


# NPS entries to leave out: placeholders, test/quiz records, DOT cams (AlertWest has them), USGS (HIVIS has them)
NPS_BAD_IMG = re.compile(r"inactive_webcam|/media/webcam/view\.htm|az511\.com|udottraffic|wsdot|usgs-nims-images|"
                         r"^https?://\d+\.\d+")
NPS_BAD_TITLE = re.compile(r"^(Test|Question \d+)$", re.I)


def nps(log=print):
    key = os.environ.get("NPS_API_KEY", "DEMO_KEY")
    d = get_json("https://developer.nps.gov/api/v1/webcams?limit=1000&api_key=%s" % key)["data"]
    cache = json.load(open(NPS_CACHE, encoding="utf-8")) if os.path.exists(NPS_CACHE) else {}
    out, skipped = [], {"streaming": 0, "inactive": 0, "no_image": 0}
    for c in d:
        try:
            lat, lon = float(c["latitude"]), float(c["longitude"])
        except (KeyError, TypeError, ValueError):
            continue
        if not regions(lat, lon):
            continue
        if c.get("status") != "Active":
            skipped["inactive"] += 1
            continue
        if c.get("isStreaming"):
            skipped["streaming"] += 1
            continue
        if NPS_BAD_TITLE.match(c["title"].strip()):
            skipped["junk"] = skipped.get("junk", 0) + 1
            continue
        img = nps_image_from_page(c["url"], cache)
        if not img:
            skipped["no_image"] += 1
            continue
        if NPS_BAD_IMG.search(img):
            skipped["dot_usgs_placeholder"] = skipped.get("dot_usgs_placeholder", 0) + 1
            continue
        park = (c.get("relatedParks") or [{}])[0]
        title = c["title"].strip()
        pname = park.get("name") or ""
        name = title if (not pname or pname.lower() in title.lower()) else "%s: %s" % (pname, title)
        host = re.sub(r"^https?://([^/]+).*$", r"\1", img)
        on_nps = host.endswith("nps.gov")
        owner = ("National Park Service" if on_nps else "NPS-listed partner camera hosted on %s" % host) + \
                (" (credit: %s)" % c["credit"] if c.get("credit") else "")
        terms = ("NPS web content is generally public domain; honour any credit line on the image" if on_nps else
                 "listed by NPS but hosted by a partner (%s); partner's terms apply" % host)
        rec = base(name, "park", lat, lon, img, c["url"], owner, "NPS webcams", terms,
                   c["id"], "NPS Data API webcams (latitude/longitude)", None,
                   "" if on_nps else "image host %s" % host)
        rec["park_code"] = park.get("parkCode")
        out.append(rec)
    json.dump(cache, open(NPS_CACHE, "w", encoding="utf-8"), indent=1)
    log("nps: %d cameras in boxes with a still image (skipped %s)" % (len(out), skipped))
    return out


SOURCES = {"usgs_hivis": usgs_hivis, "usgs_ashcam": usgs_ashcam, "ndbc": ndbc, "nps": nps}


def main(names):
    prev = json.load(open(OUT, encoding="utf-8")) if os.path.exists(OUT) else {"cams": []}
    keep = [c for c in prev.get("cams", []) if c.get("_src") not in names]
    cams = []
    for n in names:
        rows = SOURCES[n]()
        for i, c in enumerate(rows):
            c["_src"] = n
            chk = check_image(c["img"])
            c.update({k: chk.get(k) for k in ("http", "content_type", "bytes", "last_modified", "referer_ok")})
            if chk.get("error") or chk.get("note"):
                c["notes"] = (c["notes"] + "; " if c["notes"] else "") + (chk.get("error") or chk.get("note"))
            if c["stale"] is None and c["last_modified"]:
                c["newest_utc"] = c["last_modified"]
                c["stale"] = age_h(dt.datetime.fromisoformat(c["last_modified"])) > STALE_H
            c["notes"] = (c["notes"] + "; " if c["notes"] else "") + "image fetched and checked %s" % NOW.strftime("%Y-%m-%d %H:%M UTC")
            time.sleep(0.25)
        ok = sum(1 for c in rows if c["referer_ok"])
        fresh = sum(1 for c in rows if c["referer_ok"] and c["stale"] is False)
        print("  %s: %d checked, %d load OK, %d OK and fresh (<%d h)" % (n, len(rows), ok, fresh, STALE_H))
        cams += rows
    allcams = keep + cams
    json.dump({"built_utc": NOW.isoformat(), "cams": allcams}, open(OUT, "w", encoding="utf-8"), indent=1)
    print("wrote %s (%d cameras)" % (OUT, len(allcams)))


if __name__ == "__main__":
    main(sys.argv[1:] or list(SOURCES))
