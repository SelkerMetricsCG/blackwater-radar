"""
NOAA MRMS composite reflectivity (MergedReflectivityQCComposite) as the radar source.

Files come from NOAA's open-data archive on Amazon S3 (noaa-mrms-pds), one CONUS
GRIB2 every two minutes on a 0.01-degree lat/lon grid (3500 x 7000). We keep one
scan every STEP_MIN minutes, decode the CONUS grid once (cached under cache/cref so
the other regions in the same run only crop it), and write the same two products the
old RainViewer capture wrote, so everything downstream is unchanged:

  frames/radar/r<YYYYMMDD_HHMM>.webp   colour overlay, NWS reflectivity palette (local-time tag)
  frames/dbz/r<YYYYMMDD_HHMM>.png      8-bit, value = dBZ + 32, 0 = no echo / no coverage

Usage:  python cref.py [--backfill HOURS]      (default backfill 3 h; capture.py calls capture())
"""
import argparse
import datetime as dt
import gzip
import os
import re
import time
import urllib.request

import numpy as np
from PIL import Image

import region

ROOT = os.path.dirname(os.path.abspath(__file__))
FRAMES = region.frames_dir()
RADAR_DIR = os.path.join(FRAMES, "radar")
DBZ_DIR = os.path.join(FRAMES, "dbz")
CACHE = os.path.join(ROOT, "cache", "cref")

S3 = "https://noaa-mrms-pds.s3.amazonaws.com"
PRODUCT = "CONUS/MergedReflectivityQCComposite_00.50"
STEP_MIN = 10          # keep one scan per 10 minutes (files arrive every 2)
BACKFILL_H = 3         # how far back a normal cycle looks for missing scans
MAX_NEW = 24           # cap per run so a cycle never balloons
CACHE_KEEP_H = 4       # decoded CONUS grids older than this are removed
DISPLAY_PX = 512       # per zoom-7 tile, matches the old frames (5 tiles -> 2560 px)
DBZ_PX = 256
UA = "RadarTracker/1.0 (personal radar archive; chris.gabrielli@gmail.com)"
KEY_RE = re.compile(r"MRMS_MergedReflectivityQCComposite_00\.50_(\d{8})-(\d{6})\.grib2\.gz$")

_Z, X0, X1, Y0, Y1 = region.window()
NT = X1 - X0 + 1


def fetch(url, timeout=60, tries=3):
    last = None
    for k in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(2 + 3 * k)
    raise last


def list_scans(hours):
    """-> sorted list of (utc datetime, s3 key) at STEP_MIN cadence within the last `hours`."""
    now = dt.datetime.now(dt.timezone.utc)
    start = now - dt.timedelta(hours=hours)
    out = []
    day = start.date()
    while day <= now.date():
        prefix = "%s/%s/" % (PRODUCT, day.strftime("%Y%m%d"))
        after = "%sMRMS_MergedReflectivityQCComposite_00.50_%s.grib2.gz" % (
            prefix, (start if day == start.date() else dt.datetime.combine(day, dt.time.min)).strftime("%Y%m%d-%H%M%S"))
        url = "%s/?list-type=2&prefix=%s&start-after=%s&max-keys=1000" % (S3, prefix, after)
        xml = fetch(url).decode("utf-8", "replace")
        for key in re.findall(r"<Key>([^<]+)</Key>", xml):
            m = KEY_RE.search(key)
            if not m:
                continue
            t = dt.datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S").replace(tzinfo=dt.timezone.utc)
            if t.minute % STEP_MIN == 0 and t >= start:
                out.append((t.replace(second=0), key))
        day += dt.timedelta(days=1)
    # one file per slot (the first of the two-minute files at that minute)
    seen = {}
    for t, key in sorted(out):
        seen.setdefault(t, key)
    return sorted(seen.items())


def decode_conus(key):
    """Download + decode one CONUS GRIB2 -> uint8 grid (dBZ+32, 0 = no echo) and grid geometry."""
    import eccodes
    raw = gzip.decompress(fetch("%s/%s" % (S3, key), timeout=120))
    gid = eccodes.codes_new_from_message(raw)
    try:
        nj = eccodes.codes_get(gid, "Nj")
        ni = eccodes.codes_get(gid, "Ni")
        lat0 = eccodes.codes_get(gid, "latitudeOfFirstGridPointInDegrees")
        lon0 = eccodes.codes_get(gid, "longitudeOfFirstGridPointInDegrees")
        dlat = eccodes.codes_get(gid, "jDirectionIncrementInDegrees")
        dlon = eccodes.codes_get(gid, "iDirectionIncrementInDegrees")
        vals = eccodes.codes_get_values(gid).reshape(nj, ni)
    finally:
        eccodes.codes_release(gid)
    del raw
    enc = np.zeros(vals.shape, np.uint8)
    ok = vals >= -30.0
    enc[ok] = np.clip(np.rint(vals[ok]) + 32, 1, 255).astype(np.uint8)
    geo = np.array([lat0, lon0 if lon0 <= 180 else lon0 - 360, dlat, dlon], np.float64)
    return enc, geo


def conus(t, key, log):
    """Decoded CONUS grid for one scan, cached on disk so the other regions reuse it."""
    os.makedirs(CACHE, exist_ok=True)
    stem = os.path.join(CACHE, t.strftime("%Y%m%d_%H%M"))
    if os.path.exists(stem + ".npy") and os.path.exists(stem + ".geo.npy"):
        return np.load(stem + ".npy", mmap_mode="r"), np.load(stem + ".geo.npy")
    t0 = time.time()
    enc, geo = decode_conus(key)
    np.save(stem + ".geo.npy", geo)
    np.save(stem + ".tmp.npy", enc)
    os.replace(stem + ".tmp.npy", stem + ".npy")
    log("cref: decoded %s UTC in %.0fs" % (t.strftime("%H:%M"), time.time() - t0))
    return enc, geo


def prune_cache():
    if not os.path.isdir(CACHE):
        return
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=CACHE_KEEP_H)
    for fn in os.listdir(CACHE):
        m = re.match(r"(\d{8}_\d{4})", fn)
        try:
            if fn.endswith(".tmp") or (m and dt.datetime.strptime(m.group(1), "%Y%m%d_%H%M").replace(tzinfo=dt.timezone.utc) < cutoff):
                os.remove(os.path.join(CACHE, fn))
        except OSError:
            pass


def crop(grid, geo, px):
    """Nearest-neighbour resample of the lat/lon grid onto this region's Web Mercator window."""
    lat0, lon0, dlat, dlon = geo
    h = w = NT * px
    ys = Y0 + (np.arange(h) + 0.5) / px
    lat = np.degrees(np.arctan(np.sinh(np.pi - 2.0 * np.pi * ys / 2 ** region.Z)))
    lon = (X0 + (np.arange(w) + 0.5) / px) / 2 ** region.Z * 360.0 - 180.0
    ri = np.rint((lat0 - lat) / dlat).astype(np.int64)
    ci = np.rint((lon - lon0) / dlon).astype(np.int64)
    rok = (ri >= 0) & (ri < grid.shape[0])
    cok = (ci >= 0) & (ci < grid.shape[1])
    out = np.zeros((h, w), np.uint8)
    sub = np.asarray(grid[ri[rok][:, None], ci[cok][None, :]])
    out[np.ix_(rok, cok)] = sub
    return out


# NWS reflectivity colour bands (dBZ threshold -> RGB); transparent below the first
BANDS = [(5, (4, 233, 231)), (10, (1, 159, 244)), (15, (3, 0, 244)), (20, (2, 253, 2)), (25, (1, 197, 1)),
         (30, (0, 142, 0)), (35, (253, 248, 2)), (40, (229, 188, 0)), (45, (253, 149, 0)), (50, (253, 0, 0)),
         (55, (212, 0, 0)), (60, (188, 0, 0)), (65, (248, 0, 253)), (70, (152, 84, 198)), (75, (253, 253, 253))]
ALPHA = 205


def lut():
    table = np.zeros((256, 4), np.uint8)
    for v in range(1, 256):
        dbz = v - 32
        for lo, rgb in BANDS:
            if dbz >= lo:
                table[v, :3] = rgb
                table[v, 3] = ALPHA
    return table


_LUT = None


def colorize(enc):
    global _LUT
    if _LUT is None:
        _LUT = lut()
    return Image.fromarray(_LUT[enc], "RGBA")


def save_atomic(img, dest, **kw):
    tmp = dest + ".tmp"
    img.save(tmp, **kw)
    os.replace(tmp, dest)


def local_tag(t):
    return "r" + dt.datetime.fromtimestamp(t.timestamp()).strftime("%Y%m%d_%H%M")


def capture(log, hours=BACKFILL_H):
    """Write every missing scan from the last `hours`. Returns the new local-time tags (oldest first)."""
    os.makedirs(RADAR_DIR, exist_ok=True)
    os.makedirs(DBZ_DIR, exist_ok=True)
    scans = list_scans(hours)
    if not scans:
        raise RuntimeError("no MRMS composite scans listed for the last %s h" % hours)
    todo = [(t, k) for t, k in scans if not os.path.exists(os.path.join(DBZ_DIR, local_tag(t) + ".png"))]
    todo = todo[-MAX_NEW:]
    new, failed = [], 0
    for t, key in todo:
        tag = local_tag(t)
        try:
            grid, geo = conus(t, key, log)
            save_atomic(Image.fromarray(crop(grid, geo, DBZ_PX), "L"), os.path.join(DBZ_DIR, tag + ".png"), format="PNG")
            save_atomic(colorize(crop(grid, geo, DISPLAY_PX)), os.path.join(RADAR_DIR, tag + ".webp"),
                        format="WEBP", quality=80, method=4)
            new.append(tag)
        except Exception as e:  # noqa: BLE001
            failed += 1
            log("cref: %s failed: %r" % (key.rsplit("/", 1)[-1], e))
    prune_cache()
    if todo and not new:
        raise RuntimeError("all %d MRMS scans failed" % failed)
    return new


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill", type=float, default=BACKFILL_H, help="hours to look back (default %s)" % BACKFILL_H)
    args = ap.parse_args()
    MAX_NEW = 10 ** 6
    t0 = time.time()
    tags = capture(print, args.backfill)
    print("%s: %d new scans in %.0fs%s" % (region.KEY, len(tags), time.time() - t0,
                                           (" (latest " + tags[-1][10:12] + ":" + tags[-1][12:14] + ")") if tags else ""))
