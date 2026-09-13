"""
Radar capture, version 2: georeferenced layers for the web map.

Every cycle (aligned to the 15-minute mark) this:
  * asks RainViewer for its list of recent radar scans (10-minute cadence, ~2 h of history)
  * for every scan not yet saved, stitches 25 tiles into
      frames/radar/r<YYYYMMDD_HHMM>.webp   transparent color radar for display
      frames/dbz/r<YYYYMMDD_HHMM>.png      reflectivity (dBZ + 32) for the math
  * rebuilds the rainfall accumulation overlays (accumulate.py)
  * writes frames.js, the manifest the map reads
  * uploads new files to Cloudflare R2 (r2sync.py) when r2.env exists

Window: zoom-7 tiles x 19..23, y 42..46 -> lon -126.6..-112.5, lat 43.1..52.5
(southern Oregon to central BC, coast to the Rockies).

Usage:  python capture.py [--until HH:MM] [--interval MIN] [--once]
Stops at --until (default 10:00, next occurrence) or when a STOP file appears.
"""
import argparse
import ctypes
import datetime as dt
import io
import json
import math
import os
import time
import traceback
import urllib.request

from PIL import Image

ROOT = os.path.dirname(os.path.abspath(__file__))
FRAMES = os.path.join(ROOT, "frames")
RADAR_DIR = os.path.join(FRAMES, "radar")
DBZ_DIR = os.path.join(FRAMES, "dbz")
LOG = os.path.join(ROOT, "capture.log")
STOPFILE = os.path.join(ROOT, "STOP")
UA = "RadarTracker/1.0 (personal radar archive; chris.gabrielli@gmail.com)"

# --- map window ----------------------------------------------------------------
Z, X0, X1, Y0, Y1 = 7, 19, 23, 42, 46
TILE = 512          # display tiles (RainViewer serves 256 or 512)
DBZ_TILE = 256      # reflectivity tiles
RV_COLOR, RV_OPTS = 4, "1_1"   # color scheme, smooth=1 snow=1


def tile_lon(x):
    return x / 2 ** Z * 360.0 - 180.0


def tile_lat(y):
    n = math.pi - 2.0 * math.pi * y / 2 ** Z
    return math.degrees(math.atan(math.sinh(n)))


BOUNDS = [[tile_lat(Y1 + 1), tile_lon(X0)], [tile_lat(Y0), tile_lon(X1 + 1)]]   # [[S, W], [N, E]]

PALETTE_FILE = os.path.join(ROOT, "rv_palette.json")
_palette = None


def log(msg):
    line = "%s  %s" % (dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg)
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def fetch(url, timeout=30, tries=3):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(2 + 3 * i)
    raise last


def keep_awake(on):
    if os.name == "nt":
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | (0x00000001 if on else 0))


def palette():
    global _palette
    if _palette is None:
        with open(PALETTE_FILE, encoding="utf-8") as f:
            _palette = {tuple(k): v for k, v in json.load(f)}
    return _palette


def decode_dbz(tile_rgba):
    """RGBA tile -> 'L' image, value = dBZ + 32, 0 where no echo."""
    import numpy as np
    a = np.asarray(tile_rgba, dtype=np.uint32)
    key = (a[..., 0] << 24) | (a[..., 1] << 16) | (a[..., 2] << 8) | a[..., 3]
    lut = {(r << 24) | (g << 16) | (b << 8) | al: dbz + 32 for (r, g, b, al), dbz in palette().items()}
    out = np.zeros(key.shape, np.uint8)
    for k in np.unique(key[a[..., 3] > 0]):
        v = lut.get(int(k))
        if v is not None:
            out[key == k] = v
    return Image.fromarray(out, "L")


def stitch(host, path, size, color, opts, mode):
    n = X1 - X0 + 1
    img = Image.new(mode, (n * size, (Y1 - Y0 + 1) * size), 0 if mode == "L" else (0, 0, 0, 0))
    for x in range(X0, X1 + 1):
        for y in range(Y0, Y1 + 1):
            url = "%s%s/%d/%d/%d/%d/%d/%s.png" % (host, path, size, Z, x, y, color, opts)
            t = Image.open(io.BytesIO(fetch(url))).convert("RGBA")
            if mode == "L":
                t = decode_dbz(t)
            img.paste(t, ((x - X0) * size, (y - Y0) * size))
    return img


def save_atomic(img, dest, **kw):
    tmp = dest + ".tmp"
    img.save(tmp, **kw)
    os.replace(tmp, dest)


def capture_scans(meta):
    """Save every RainViewer scan not yet on disk. Returns list of new scan tags."""
    os.makedirs(RADAR_DIR, exist_ok=True)
    os.makedirs(DBZ_DIR, exist_ok=True)
    new = []
    for frame in meta["radar"]["past"]:
        tag = "r" + dt.datetime.fromtimestamp(frame["time"]).strftime("%Y%m%d_%H%M")
        radar_dest = os.path.join(RADAR_DIR, tag + ".webp")
        dbz_dest = os.path.join(DBZ_DIR, tag + ".png")
        if not os.path.exists(dbz_dest):
            save_atomic(stitch(meta["host"], frame["path"], DBZ_TILE, 0, "0_0", "L"), dbz_dest, format="PNG")
        if not os.path.exists(radar_dest):
            img = stitch(meta["host"], frame["path"], TILE, RV_COLOR, RV_OPTS, "RGBA")
            save_atomic(img, radar_dest, format="WEBP", quality=80, method=4)
            new.append(tag)
    return new


def write_manifest(accum_meta):
    radar = []
    if os.path.isdir(RADAR_DIR):
        for fn in sorted(os.listdir(RADAR_DIR)):
            if fn.startswith("r") and fn.endswith(".webp"):
                t = dt.datetime.strptime(fn[1:14], "%Y%m%d_%H%M")
                radar.append({"file": "frames/radar/" + fn, "t": int(t.timestamp()),
                              "label": t.strftime("%a %b %d, %I:%M %p")})
    sat = []
    sat_dir = os.path.join(FRAMES, "sat")
    if os.path.isdir(sat_dir):
        for fn in sorted(os.listdir(sat_dir)):
            if fn.startswith("s") and fn.endswith(".jpg"):
                t = dt.datetime.strptime(fn[1:14], "%Y%m%d_%H%M")
                sat.append({"file": "frames/sat/" + fn, "t": int(t.timestamp()), "label": t.strftime("%a %b %d, %I:%M %p")})
    accum = []
    for key in ("1h", "3h", "6h", "12h", "24h", "all"):
        p = os.path.join(FRAMES, "accum", key + ".webp")
        if key in accum_meta and os.path.exists(p):
            accum.append(dict(accum_meta[key], key=key,
                              file="frames/accum/%s.webp?v=%d" % (key, int(os.path.getmtime(p)))))
    data = {"bounds": BOUNDS, "radar": radar, "sat": sat, "accum": accum, "legend": accum_meta.get("_legend", []),
            "updated": dt.datetime.now().strftime("%a %b %d %I:%M %p"), "updated_t": int(time.time())}
    tmp = os.path.join(ROOT, "frames.js.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("window.RADAR_DATA = %s;\n" % json.dumps(data))
    os.replace(tmp, os.path.join(ROOT, "frames.js"))
    return len(radar)


def capture_all():
    tag = dt.datetime.now().strftime("%Y%m%d_%H%M")
    ok = []
    accum_meta = {}
    try:
        meta = json.loads(fetch("https://api.rainviewer.com/public/weather-maps.json"))
        new = capture_scans(meta)
        ok.append("scans +%d%s" % (len(new), (" (latest " + new[-1][10:12] + ":" + new[-1][12:14] + ")") if new else ""))
    except Exception as e:  # noqa: BLE001
        log("radar FAILED: %r" % e)
    try:
        import satellite
        n = satellite.build(log)
        if n:
            ok.append("sat +%d" % n)
    except Exception as e:  # noqa: BLE001
        log("satellite FAILED: %r" % e)
    try:
        import accumulate
        accum_meta = accumulate.build_all()
        if "24h" in accum_meta:
            ok.append("accum 24h peak %.2f in" % accum_meta["24h"]["peak_in"])
    except Exception as e:  # noqa: BLE001
        log("accumulation FAILED: %r" % e)
    try:
        n = write_manifest(accum_meta)
        ok.append("%d frames" % n)
    except Exception as e:  # noqa: BLE001
        log("manifest FAILED: %r" % e)
    try:
        import alerts
        ok.append("alerts %d" % alerts.build(log))
    except Exception as e:  # noqa: BLE001
        log("alerts FAILED: %r" % e)
    # river gauges and webcams: every half hour, or if missing
    rv_file = os.path.join(ROOT, "data", "rivers.js")
    half_due = FORCE_HALF if FORCE_HALF is not None else (dt.datetime.now().minute % 30 < 15)
    if half_due or not os.path.exists(rv_file):
        try:
            import rivers
            ok.append("rivers %d" % rivers.build(log))
        except Exception as e:  # noqa: BLE001
            log("rivers FAILED: %r" % e)
    # station totals: once an hour (first cycle after the top of the hour), or if missing
    st_file = os.path.join(ROOT, "data", "stations.js")
    hourly_due = FORCE_HOURLY if FORCE_HOURLY is not None else (dt.datetime.now().minute < 15)
    if hourly_due or not os.path.exists(st_file):
        try:
            import stations
            ok.append("stations %d" % stations.build(log))
        except Exception as e:  # noqa: BLE001
            log("stations FAILED: %r" % e)
        try:
            import forecast
            forecast.build(log)
            ok.append("forecast")
        except Exception as e:  # noqa: BLE001
            log("forecast FAILED: %r" % e)
        try:
            import mrms
            mrms.build(log)
            ok.append("mrms")
        except Exception as e:  # noqa: BLE001
            log("mrms FAILED: %r" % e)
        try:
            import freezing
            freezing.elevation_grid(log)
            freezing.build(log)
            ok.append("freezing")
        except Exception as e:  # noqa: BLE001
            log("freezing FAILED: %r" % e)
        try:
            import snodas
            ok.append("snodas %s" % snodas.build(log))
        except Exception as e:  # noqa: BLE001
            log("snodas FAILED: %r" % e)
        try:
            import webcams
            ok.append("webcams %d" % webcams.build(log))
        except Exception as e:  # noqa: BLE001
            log("webcams FAILED: %r" % e)
        try:
            import avalanche
            ok.append("avalanche %d" % avalanche.build(log))
        except Exception as e:  # noqa: BLE001
            log("avalanche FAILED: %r" % e)
        try:
            import basins
            ok.append("basins %d" % basins.build(log))
        except Exception as e:  # noqa: BLE001
            log("basins FAILED: %r" % e)
    try:
        import r2sync
        r = r2sync.sync(log)
        if r:
            ok.append(r)
    except Exception as e:  # noqa: BLE001
        log("r2 upload FAILED: %r" % e)
    log("cycle %s -> %s" % (tag, ", ".join(ok) or "nothing"))


def next_boundary(now, interval):
    minute = (now.minute // interval + 1) * interval
    return now.replace(second=0, microsecond=0) + dt.timedelta(minutes=minute - now.minute)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--until", default=None, help="optional local stop time HH:MM (default: run until stopped)")
    ap.add_argument("--interval", type=int, default=15, help="minutes between cycles")
    ap.add_argument("--once", action="store_true", help="run one cycle and exit")
    a = ap.parse_args()

    os.makedirs(FRAMES, exist_ok=True)
    if os.path.exists(STOPFILE):
        os.remove(STOPFILE)
    if a.once:
        capture_all()
        return

    until = None
    if a.until:
        hh, mm = map(int, a.until.split(":"))
        now = dt.datetime.now()
        until = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if until <= now:
            until += dt.timedelta(days=1)
    log("=== starting: every %d min %s (or until a STOP file appears). Ctrl+C to quit ==="
        % (a.interval, ("until " + until.strftime("%a %I:%M %p")) if until else "continuously"))
    keep_awake(True)
    try:
        capture_all()
        while True:
            nxt = next_boundary(dt.datetime.now(), a.interval)
            if until and nxt >= until:
                log("reached stop time; done.")
                break
            while dt.datetime.now() < nxt:
                if os.path.exists(STOPFILE):
                    log("STOP file found; done.")
                    return
                time.sleep(min(20, max(1, (nxt - dt.datetime.now()).total_seconds())))
            try:
                capture_all()
            except Exception:  # noqa: BLE001
                log("unexpected error:\n" + traceback.format_exc())
    except KeyboardInterrupt:
        log("interrupted; done.")
    finally:
        keep_awake(False)


if __name__ == "__main__":
    main()
