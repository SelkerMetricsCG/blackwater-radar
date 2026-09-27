"""
Webcam layer, inside the map window:
- AlertWest: fire-detection PTZ cameras, plus the DOT road cameras and FAA / HPWREN / utility cameras it
  aggregates. Road vs fire comes from the agency (`src`), not the camera name.
- Pulled live each run: USGS river cameras (HIVIS), USGS volcano cameras (Ashcam), NOAA buoy cameras.
- webcams_extra.json: curated conditions cameras (ski areas, water, towns, national parks). Each is
  fetched once per run (except those marked robots) to log problems and take its Last-Modified time; only
  a Brownrice offline card drops one (see drops()). Prune dead ones from a PC: cams_research/prune_extra.py.

Road cameras are grouped by pole (cameras within SITE_M share one marker and every view is kept) and
thinned to one site per RURAL_KM, or per URBAN_KM inside the metro circles in URBAN.

Output: data/webcams.js -> window.WEBCAMS = {updated, updated_t, cams:[{id, name, lat, lon, img, ts, kind,
src, link, owner?, pan?, fov?, stake?, views?:[{name, img, ts}]}]}. kind: road, fire, ski, water, river,
town, park. Image URLs point at each camera's own host; the map adds a cache-buster when a popup opens.

Run standalone:  python webcams.py
"""
import concurrent.futures as cf
import datetime as dt
import email.utils
import hashlib
import json
import math
import os
import re
import time
import urllib.error
import urllib.request

import region

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = region.data_dir()
OUT = os.path.join(DATA, "webcams.js")
EXTRA = os.path.join(ROOT, "webcams_extra.json")
UA = "Mozilla/5.0 (RadarTracker personal weather map; chris.gabrielli@gmail.com)"
CHECK_UA = "BlackwaterLabs-radar-webcams/1.0 (+https://radar.blackwaterlabs.org)"
REFERER = "https://radar.blackwaterlabs.org/"
URL = "https://alertwest.live/api/getCameraDataByLoc"
LAT0, LAT1, LON0, LON1 = region.bbox()

DOT_SRC = {"WSDOT", "ODOT", "ITD", "MDT", "WYDOT", "CALTRANS", "NDOT", "UDOT", "CDOT", "ADOT", "NMDOT",
           "DRIVEBC", "NYSDOT", "MASSDOT", "VTRANS", "NHDOT", "MAINEDOT", "RIDOT", "CTDOT"}
SITE_M = 250        # cameras closer than this share one marker
RURAL_KM = 3        # road-camera spacing in the mountains and countryside
URBAN_KM = 10       # road-camera spacing inside the metro circles below
# (name, lat, lon, radius km). Hand-set; kept tight enough that canyon and pass roads stay rural.
URBAN = [
    ("Seattle", 47.61, -122.33, 25), ("Everett", 47.95, -122.20, 12), ("Tacoma", 47.23, -122.45, 18),
    ("Olympia", 47.04, -122.90, 10), ("Vancouver BC", 49.25, -123.05, 25), ("Bellingham", 48.76, -122.47, 8),
    ("Portland", 45.52, -122.65, 28), ("Salem", 44.94, -123.03, 10), ("Eugene", 44.06, -123.08, 12),
    ("Spokane", 47.66, -117.40, 16), ("Coeur d'Alene", 47.69, -116.78, 8), ("Tri-Cities", 46.24, -119.20, 14),
    ("Yakima", 46.60, -120.51, 8), ("Boise", 43.60, -116.30, 22), ("Idaho Falls", 43.49, -112.03, 8),
    ("Billings", 45.78, -108.54, 10), ("Missoula", 46.87, -114.00, 8), ("Great Falls", 47.50, -111.30, 7),
    ("Bay Area", 37.65, -122.18, 50), ("Santa Rosa", 38.44, -122.71, 9), ("Sacramento", 38.60, -121.40, 25),
    ("Stockton", 37.96, -121.29, 10), ("Modesto", 37.64, -120.99, 10), ("Fresno", 36.77, -119.78, 16),
    ("Bakersfield", 35.37, -119.02, 14), ("Santa Barbara", 34.42, -119.72, 10), ("Los Angeles", 34.05, -118.25, 45),
    ("Inland Empire", 34.03, -117.35, 30), ("Orange County", 33.70, -117.85, 22), ("San Diego", 32.80, -117.10, 28),
    ("Reno", 39.53, -119.80, 14), ("Las Vegas", 36.15, -115.15, 25), ("Salt Lake", 40.70, -111.93, 18),
    ("Ogden", 41.20, -111.98, 12), ("Provo", 40.26, -111.68, 14), ("St George", 37.10, -113.58, 10),
    ("Denver", 39.74, -104.97, 28), ("Boulder", 40.02, -105.26, 8), ("Fort Collins", 40.55, -105.07, 12),
    ("Colorado Springs", 38.86, -104.79, 18), ("Pueblo", 38.27, -104.61, 8), ("Phoenix", 33.45, -112.07, 45),
    ("Tucson", 32.22, -110.93, 20), ("Albuquerque", 35.10, -106.62, 20),
    ("New York", 40.75, -73.95, 45), ("Boston", 42.36, -71.08, 30), ("Providence", 41.82, -71.42, 15),
    ("Hartford", 41.76, -72.68, 15), ("New Haven", 41.31, -72.93, 10), ("Albany", 42.68, -73.80, 12),
    ("Buffalo", 42.90, -78.85, 15), ("Rochester", 43.16, -77.61, 12), ("Syracuse", 43.05, -76.15, 10),
    ("Worcester", 42.27, -71.80, 10), ("Springfield MA", 42.10, -72.59, 10), ("Portland ME", 43.66, -70.26, 8),
]
DROP_AFTER_H = 30 * 24   # live-feed cameras whose newest image is older than this are left out


def fetch(url, timeout=120):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def fetch_json(url, timeout=120):
    req = urllib.request.Request(url, headers={"User-Agent": CHECK_UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def inside(lat, lon):
    return LAT0 <= lat <= LAT1 and LON0 <= lon <= LON1


def km(lat1, lon1, lat2, lon2):
    dy = (lat1 - lat2) * 111.2
    dx = (lon1 - lon2) * 111.2 * math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot(dx, dy)


def is_road(src):
    return (src or "").strip().upper() in DOT_SRC


def urban(lat, lon):
    return any(km(lat, lon, a, b) <= r for _, a, b, r in URBAN)


# ---------------------------------------------------------------- AlertWest
def image_url(cam):
    img = cam.get("img") or ""
    m = re.search(r"_(\d{10})_", img)
    if not m:
        return None, None
    ts = int(m.group(1))
    day = dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y/%m/%d")
    return "https://alertwest.live/data/img/%s/%s/%s" % (cam["id"], day, img), ts


def alertwest():
    d = json.loads(fetch(URL))["data"]
    locs = {l["id"]: l for l in d["locs"]["data"]}
    out = []
    for c in d["cams"]["data"]:
        loc = locs.get(c.get("lid"))
        if not loc or c.get("off"):
            continue
        try:
            lat, lon = float(loc["lat"]), float(loc["lon"])
        except (TypeError, ValueError):
            continue
        if not inside(lat, lon):
            continue
        url, ts = image_url(c)
        if not url:
            continue
        src = (c.get("sp") or c.get("pr") or "AlertWest").strip() or "AlertWest"
        rec = {"id": c["id"], "name": (c.get("cn") or "").replace("_", " ").strip(), "lat": round(lat, 5),
               "lon": round(lon, 5), "img": url, "ts": ts, "kind": "road" if is_road(src) else "fire",
               "src": src, "link": "https://alertwest.live/"}
        if rec["kind"] == "fire":
            try:
                rec["pan"] = round(float(c.get("p")), 1)
                rec["fov"] = round(float(c.get("fov")), 1)
            except (TypeError, ValueError):
                pass
        out.append(rec)
    return out


# ---------------------------------------------------------------- live feeds (keyless, public domain)
def usgs_hivis():
    now = time.time()
    out = []
    for c in fetch_json("https://api.waterdata.usgs.gov/nims/cameras?enabled=true"):
        try:
            lat, lon = float(c["lat"]), float(c["lng"])
        except (KeyError, TypeError, ValueError):
            continue
        if not inside(lat, lon) or c.get("hideCam") or re.search(r"Test Site", c.get("camName") or ""):
            continue
        newest = c.get("newestImageDT")
        if not newest:
            continue
        ts = int(dt.datetime.fromisoformat(newest.replace("Z", "+00:00")).timestamp())
        if now - ts > DROP_AFTER_H * 3600:
            continue
        gage = c.get("nwisId") if c.get("nwisId") not in (None, "", "888888") else None
        coastal = not gage and re.search(r"\b(Beach|Inn|Coast|Pier)\b", c.get("camName") or "", re.I)
        out.append({"id": "usgs-" + c["camId"], "name": c.get("camName") or c["camId"], "lat": round(lat, 5),
                    "lon": round(lon, 5), "img": "%s%s_newest.jpg" % (c["smallDir"], c["camId"]), "ts": ts,
                    "kind": "water" if coastal else "river", "src": "USGS", "owner": "U.S. Geological Survey",
                    "link": "https://apps.usgs.gov/hivis/camera/%s" % c["camId"]})
    return out


def usgs_volcano():
    now = time.time()
    out = []
    for c in fetch_json("https://volcview.wr.usgs.gov/ashcam-api/webcamApi/webcams")["webcams"]:
        lat, lon = c.get("latitude"), c.get("longitude")
        if lat is None or lon is None or not inside(float(lat), float(lon)):
            continue
        if c.get("hasImages") != "Y" or not c.get("lastImageTimestamp") or c.get("faaInd") == "Y":
            continue
        # third-party views USGS re-hosts (DOT, FAA, NPS, ski areas) come from their own sources instead
        ext = c.get("externalUrl") or ""
        host = re.sub(r"^https?://([^/]+).*$", r"\1", ext) if ext else ""
        if host and not (host.endswith("usgs.gov") or host.endswith("unavco.org")):
            continue
        if re.search(r"Meadows|Crystal|Bachelor|Timberline|Snowcrest", c.get("webcamName") or ""):
            continue
        ts = int(c["lastImageTimestamp"])
        if now - ts > DROP_AFTER_H * 3600:
            continue
        out.append({"id": "ashcam-" + c["webcamCode"], "name": c["webcamName"], "lat": round(float(lat), 5),
                    "lon": round(float(lon), 5), "img": c["currentMediumImageUrl"], "ts": ts, "kind": "park",
                    "src": "USGS", "owner": "U.S. Geological Survey (volcano camera)",
                    "link": "https://volcview.wr.usgs.gov/ashcam-gui/webcam.html?webcam=%s" % c["webcamCode"]})
    return out


def ndbc():
    out = []
    for c in fetch_json("https://www.ndbc.noaa.gov/buoycams.php"):
        lat, lon = c.get("lat"), c.get("lng")
        if lat is None or lon is None or not c.get("img") or not inside(float(lat), float(lon)):
            continue
        m = re.search(r"_(\d{4})_(\d\d)_(\d\d)_(\d\d)(\d\d)\.jpg$", c["img"])
        ts = int(dt.datetime(*map(int, m.groups()), tzinfo=dt.timezone.utc).timestamp()) if m else None
        out.append({"id": "ndbc-" + c["id"], "name": c["name"].strip(), "lat": round(float(lat), 5),
                    "lon": round(float(lon), 5), "img": "https://www.ndbc.noaa.gov/images/buoycam/%s" % c["img"],
                    "ts": ts, "kind": "water", "src": "NOAA", "owner": "NOAA National Data Buoy Center (buoy camera)",
                    "link": "https://www.ndbc.noaa.gov/station_page.php?station=%s" % c["id"]})
    return out


# ---------------------------------------------------------------- curated extras
def check_image(url):
    """(state, last-modified epoch, reason) for one image URL. state is "ok"; "gone" when the host says so
    (404/410, not an image, Brownrice's offline card); or "unreachable" (refused, timed out, 5xx). From a
    cloud runner these can be wrong: see drops()."""
    sep = "&" if "?" in url else "?"
    req = urllib.request.Request(url + sep + "t=%d" % int(time.time()),
                                 headers={"User-Agent": CHECK_UA, "Referer": REFERER, "Accept": "image/*"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            head = r.read(16)
            ctype = r.headers.get("Content-Type", "")
            lm = r.headers.get("Last-Modified")
            is_img = ctype.startswith("image/") or head[:2] == b"\xff\xd8" or head[:4] == b"\x89PNG" or head[8:12] == b"WEBP"
            if "brownrice.com" in url and head[:4] == b"\x89PNG":
                return "gone", None, "offline card"
            if not is_img:
                return "gone", None, "not an image"
            ts = None
            if lm:
                try:
                    ts = int(email.utils.parsedate_to_datetime(lm).timestamp())
                except (TypeError, ValueError):
                    pass
            return "ok", ts, ""
    except urllib.error.HTTPError as e:
        return ("gone" if e.code in (404, 410) else "unreachable"), None, "HTTP %d" % e.code
    except Exception as e:
        return "unreachable", None, type(e).__name__


def drops(state, why):
    """Whether a curated camera is left out this run. From a cloud runner a dead camera and a refused one look
    the same (glacier.org and lakewenatcheeinfo.com answer GitHub's runners as if the image were gone, and
    Cloudflare sites refuse them, yet all load in a browser), so only Brownrice's offline card, which
    Brownrice serves to anyone, drops a camera. Dead cameras are pruned from a PC instead."""
    return state == "gone" and why == "offline card"


def extras(check=True, log=print):
    cams = [c for c in json.load(open(EXTRA, encoding="utf-8"))["cams"] if inside(c["lat"], c["lon"])]
    todo = [c for c in cams if check and not c.get("robots")]
    with cf.ThreadPoolExecutor(16) as ex:
        results = dict(zip((id(c) for c in todo), ex.map(lambda c: check_image(c["img"]), todo)))
    out, gone, unreachable = [], 0, {}
    for c in cams:
        state, ts, why = results.get(id(c), ("ok", None, ""))
        if drops(state, why):
            gone += 1
            continue
        if state != "ok":
            host = re.sub(r"^https?://([^/]+).*$", r"\1", c["img"])
            unreachable[host + " " + why] = unreachable.get(host + " " + why, 0) + 1
        rec = {"id": "x" + hashlib.md5(c["img"].encode()).hexdigest()[:10], "name": c["name"], "lat": c["lat"],
               "lon": c["lon"], "img": c["img"], "ts": ts, "kind": c["kind"], "src": c.get("provider") or "",
               "owner": c.get("owner") or c.get("provider") or "", "link": c.get("page") or ""}
        if c.get("stake"):
            rec["stake"] = True
        out.append(rec)
    if gone:
        log("webcams: %d curated cameras left out (Brownrice stream offline)" % gone)
    if unreachable:
        log("webcams: kept %d curated cameras this runner couldn't load: %s" % (
            sum(unreachable.values()), ", ".join("%s x%d" % kv for kv in sorted(unreachable.items()))))
    return out


# ---------------------------------------------------------------- grouping and thinning
def group(cams, site_m=SITE_M):
    """Merge cameras of the same kind within site_m metres into one site; every view is kept in `views`."""
    cell = site_m / 1000.0
    grid, sites = {}, []
    for c in sorted(cams, key=lambda c: (c["kind"], str(c["id"]))):
        y = c["lat"] * 111.2
        x = c["lon"] * 111.2 * math.cos(math.radians(c["lat"]))
        gy, gx = int(y // cell), int(x // cell)
        home = None
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                for s in grid.get((c["kind"], gy + dy, gx + dx), ()):
                    if km(s["lat"], s["lon"], c["lat"], c["lon"]) * 1000 <= site_m:
                        home = s
                        break
                if home:
                    break
            if home:
                break
        view = {"name": c["name"], "img": c["img"], "ts": c.get("ts")}
        if home:
            home.setdefault("views", [{"name": home["name"], "img": home["img"], "ts": home.get("ts")}]).append(view)
            if c.get("stake"):
                home["stake"] = True
        else:
            s = dict(c)
            grid.setdefault((c["kind"], gy, gx), []).append(s)
            sites.append(s)
    return sites


def thin(sites, rural_km=RURAL_KM, urban_km=URBAN_KM):
    """Keep one road site per rural_km (urban_km inside URBAN); sites with more views and pass/summit
    names win. Other kinds pass through untouched."""
    road = [s for s in sites if s["kind"] == "road"]
    rest = [s for s in sites if s["kind"] != "road"]
    pri = lambda s: (-len(s.get("views", ())), not re.search(r"pass|summit", s["name"], re.I), str(s["id"]))
    cell = float(urban_km)
    grid, kept = {}, []
    for s in sorted(road, key=pri):
        spacing = urban_km if urban(s["lat"], s["lon"]) else rural_km
        gy = int(s["lat"] * 111.2 // cell)
        gx = int(s["lon"] * 111.2 * math.cos(math.radians(s["lat"])) // cell)
        near = any(km(k["lat"], k["lon"], s["lat"], s["lon"]) < spacing
                   for dy in (-1, 0, 1) for dx in (-1, 0, 1) for k in grid.get((gy + dy, gx + dx), ()))
        if not near:
            grid.setdefault((gy, gx), []).append(s)
            kept.append(s)
    return kept + rest


def build(log=print, check=True):
    cams = alertwest()  # a failure here raises, so the last good webcams.js stays up
    n_aw = len(cams)
    for name, fn in (("usgs river", usgs_hivis), ("usgs volcano", usgs_volcano), ("noaa buoy", ndbc),
                     ("curated", lambda: extras(check, log))):
        try:
            got = fn()
            cams += got
        except Exception as e:  # one feed failing must not take the layer down
            log("webcams: %s feed failed: %s" % (name, e))
    n_road = sum(1 for c in cams if c["kind"] == "road")
    sites = thin(group([c for c in cams if c["kind"] != "fire"])) + [c for c in cams if c["kind"] == "fire"]
    data = {"updated": dt.datetime.now().strftime("%a %b %d %I:%M %p"), "updated_t": int(time.time()), "cams": sites}
    os.makedirs(DATA, exist_ok=True)
    with open(OUT + ".tmp", "w", encoding="utf-8") as f:
        f.write("window.WEBCAMS = %s;\n" % json.dumps(data, separators=(",", ":")))
    os.replace(OUT + ".tmp", OUT)
    by = {}
    for s in sites:
        by[s["kind"]] = by.get(s["kind"], 0) + 1
    log("webcams: %d markers from %d cameras (AlertWest %d; road cameras %d -> %d sites); %s"
        % (len(sites), len(cams), n_aw, n_road, by.get("road", 0),
           ", ".join("%s %d" % kv for kv in sorted(by.items()))))
    return len(sites)


if __name__ == "__main__":
    build()
