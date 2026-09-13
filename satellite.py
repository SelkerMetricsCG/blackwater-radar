"""
GOES-West GeoColor satellite frames for the map window, from NASA GIBS
(Web Mercator tiles, 10-minute imagery, roughly an hour behind real time).

Saves frames/sat/s<YYYYMMDD_HHMM>.jpg (local time in the name, 1280x1280) for
every available time step in the last ~2 hours not yet on disk, at 20-minute
spacing. capture.py lists them in the manifest.
"""
import datetime as dt
import io
import os
import re
import time
import urllib.request

from PIL import Image

import region

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(region.frames_dir(), "sat")
UA = "RadarTracker/1.0 (personal weather map; chris.gabrielli@gmail.com)"
LAYER = "GOES-West_ABI_GeoColor"
Z, X0, X1, Y0, Y1 = region.window()
T = 256
STEP_MIN = 20
LOOKBACK_H = 2.5


def fetch(url, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def latest_time():
    """latest GeoColor time GIBS advertises (UTC datetime)"""
    xml = fetch("https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/1.0.0/WMTSCapabilities.xml", 120).decode("utf-8", "ignore")
    i = xml.find("<ows:Identifier>%s</ows:Identifier>" % LAYER)
    m = re.search(r"<Default>([^<]+)</Default>", xml[i:i + 20000])
    return dt.datetime.strptime(m.group(1), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)


def stitch(t_utc):
    ts = t_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    img = Image.new("RGB", ((X1 - X0 + 1) * T, (Y1 - Y0 + 1) * T), (0, 0, 0))
    for x in range(X0, X1 + 1):
        for y in range(Y0, Y1 + 1):
            url = "https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/%s/default/%s/GoogleMapsCompatible_Level7/%d/%d/%d.png" % (LAYER, ts, Z, y, x)
            tile = Image.open(io.BytesIO(fetch(url))).convert("RGB")
            img.paste(tile, ((x - X0) * T, (y - Y0) * T))
    return img


def build(log=print):
    os.makedirs(OUT_DIR, exist_ok=True)
    try:
        latest = latest_time()
    except Exception as e:  # noqa: BLE001
        log("satellite: capabilities failed: %r" % e)
        return 0
    # candidate times: every STEP_MIN back from the latest, within the lookback
    times = []
    t = latest.replace(minute=(latest.minute // 10) * 10, second=0, microsecond=0)
    while t > latest - dt.timedelta(hours=LOOKBACK_H):
        times.append(t)
        t -= dt.timedelta(minutes=STEP_MIN)
    new = 0
    for t_utc in sorted(times):
        local = t_utc.astimezone()
        dest = os.path.join(OUT_DIR, "s" + local.strftime("%Y%m%d_%H%M") + ".jpg")
        if os.path.exists(dest):
            continue
        try:
            img = stitch(t_utc)
        except Exception as e:  # noqa: BLE001
            log("satellite: %s failed: %r" % (t_utc.strftime("%H:%MZ"), e))
            continue
        img.save(dest + ".tmp.jpg", "JPEG", quality=80, optimize=True)
        os.replace(dest + ".tmp.jpg", dest)
        new += 1
    log("satellite: +%d frames (latest %s)" % (new, latest.astimezone().strftime("%I:%M %p")))
    return new


if __name__ == "__main__":
    t0 = time.time()
    build()
    print("done in %.0fs" % (time.time() - t0))
