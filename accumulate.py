"""
Estimated rainfall accumulation from the saved reflectivity scans, rendered as
transparent map overlays for the web map.

Reads  frames/dbz/r<YYYYMMDD_HHMM>.png   (8-bit: value = dBZ + 32, 0 = no echo)
Writes frames/accum/<window>.webp        RGBA overlay, same bounds as the radar
       frames/accum/meta.json            per-window label, span, scan count, peak

dBZ -> rain rate uses Marshall-Palmer (Z = 200 R^1.6). Each scan counts until the
next scan (capped at 20 min). This is a radar estimate, not a gauge.

Run standalone:  python accumulate.py
"""
import datetime as dt
import json
import os

import numpy as np
from PIL import Image

import region

ROOT = os.path.dirname(os.path.abspath(__file__))
FRAMES = region.frames_dir()
DBZ_DIR = os.path.join(FRAMES, "dbz")
OUT_DIR = os.path.join(FRAMES, "accum")

WINDOWS = [("1h", 1, "Last 1 hour"), ("3h", 3, "Last 3 hours"), ("6h", 6, "Last 6 hours"),
           ("12h", 12, "Last 12 hours"), ("24h", 24, "Last 24 hours"), ("all", None, "Everything recorded")]

MIN_DBZ, MAX_DBZ = 5.0, 53.0
MAX_GAP_MIN, LAST_SCAN_MIN = 20.0, 10.0

# accumulation bins in inches -> RGB; also written to meta.json for the map legend
BINS = [
    (0.01, (185, 240, 185)), (0.10, (80, 200, 80)),  (0.25, (255, 240, 0)),
    (0.50, (255, 170, 0)),   (0.75, (255, 90, 0)),   (1.00, (220, 0, 0)),
    (1.50, (200, 0, 200)),   (2.00, (120, 0, 180)),  (3.00, (70, 0, 110)),
]


def load_scans():
    if not os.path.isdir(DBZ_DIR):
        return []
    out = []
    for fn in os.listdir(DBZ_DIR):
        if fn.startswith("r") and fn.endswith(".png"):
            try:
                out.append((dt.datetime.strptime(fn[1:14], "%Y%m%d_%H%M"), os.path.join(DBZ_DIR, fn)))
            except ValueError:
                pass
    return sorted(out)


def rain_rate_mm_h(dbz_img):
    a = np.asarray(dbz_img, dtype=np.float32)
    dbz = a - 32.0
    dbz[a == 0] = -99.0
    dbz = np.clip(dbz, None, MAX_DBZ)
    r = (10.0 ** (dbz / 10.0) / 200.0) ** (1.0 / 1.6)
    r[dbz < MIN_DBZ] = 0.0
    return r


def accumulate(scans, hours):
    if not scans:
        return None, []
    end = scans[-1][0]
    used = scans if hours is None else [s for s in scans if s[0] > end - dt.timedelta(hours=hours)]
    total = None
    for k, (t, path) in enumerate(used):
        nxt = used[k + 1][0] if k + 1 < len(used) else None
        gap_min = (nxt - t).total_seconds() / 60.0 if nxt else LAST_SCAN_MIN
        gap_min = min(max(gap_min, 1.0), MAX_GAP_MIN)
        mm = rain_rate_mm_h(Image.open(path).convert("L")) * (gap_min / 60.0)
        total = mm if total is None else total + mm
    return total / 25.4, used


def colorize(inches):
    h, w = inches.shape
    rgb = np.zeros((h, w, 3), np.uint8)
    alpha = np.zeros((h, w), np.uint8)
    for lo, color in BINS:
        m = inches >= lo
        rgb[m] = color
        alpha[m] = 190
    return Image.fromarray(np.dstack([rgb, alpha]), "RGBA")


def build_all():
    scans = load_scans()
    if not scans:
        return {}
    os.makedirs(OUT_DIR, exist_ok=True)
    meta = {}
    for key, hours, title in WINDOWS:
        inches, used = accumulate(scans, hours)
        if inches is None:
            continue
        img = colorize(inches)
        img = img.resize((img.width * 2, img.height * 2), Image.BILINEAR)
        try:
            import values
            values.write_grid("accum_%s" % key, inches)
        except Exception as e:  # noqa: BLE001
            print("accum values %s failed: %r" % (key, e))
        tmp = os.path.join(OUT_DIR, key + ".tmp.webp")
        img.save(tmp, "WEBP", quality=80, method=4)
        os.replace(tmp, os.path.join(OUT_DIR, key + ".webp"))
        meta[key] = {
            "title": title,
            "start": used[0][0].strftime("%a %I:%M %p"), "end": used[-1][0].strftime("%a %I:%M %p"),
            "scans": len(used), "peak_in": round(float(inches.max()), 2),
        }
    meta["_legend"] = [{"min": lo, "color": "#%02x%02x%02x" % c} for lo, c in BINS]
    with open(os.path.join(OUT_DIR, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=1)
    return meta


if __name__ == "__main__":
    m = build_all()
    for k, v in m.items():
        if not k.startswith("_"):
            print(k, "->", v)
    if not m:
        print("no dBZ scans found in", DBZ_DIR)
