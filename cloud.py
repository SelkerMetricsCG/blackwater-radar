"""
One capture cycle on a fresh machine (GitHub Actions), with all state in R2.

  1. list what R2 already has; drop anything older than RETAIN_H hours (radar, satellite,
     reflectivity scans) so the archive always holds a rolling day
  2. recreate the local layout: empty placeholders for radar/satellite frames (so the
     manifest lists them and nothing is re-downloaded), real copies of the reflectivity
     scans (the accumulation math needs them), and the cache files under state/
  3. run one capture cycle (capture.capture_all); "hourly" mode adds the slow jobs
  4. push changed caches back to state/

Credentials come from environment variables (R2_ACCOUNT_ID, R2_ACCESS_KEY_ID,
R2_SECRET_ACCESS_KEY, R2_BUCKET, R2_PUBLIC_URL) or from r2.env locally.
Set TZ=America/Los_Angeles so file names and labels stay in Pacific time.

Usage:  python cloud.py [radar|hourly]
"""
import datetime as dt
import json
import os
import re
import sys
import time

import r2sync

ROOT = os.path.dirname(os.path.abspath(__file__))
FRAMES = os.path.join(ROOT, "frames")
DATA = os.path.join(ROOT, "data")
RETAIN_H = 30                      # rolling archive: keep this many hours of scans
STATE_PREFIX = "state/"
STATE_FILES = ["dem_z7.npy", "huc6.geojson", "station_meta_cache.json", "usgs_median_cache.json", "nwps_cache.json",
               "usgs_lid_cache.json", "nws_stations_cache.json", "zone_cache.json", "snodas.js"]
STAMP = re.compile(r"[rs](\d{8}_\d{4})\.")


def log(msg):
    print("%s  %s" % (dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg), flush=True)


def stamp_of(key):
    m = STAMP.search(os.path.basename(key))
    if not m:
        return None
    try:
        return dt.datetime.strptime(m.group(1), "%Y%m%d_%H%M")
    except ValueError:
        return None


def touch(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not os.path.exists(path):
        open(path, "wb").close()


def main():
    t0 = time.time()
    env = r2sync.load_env()
    if not env:
        raise SystemExit("no R2 credentials")
    s3, bucket = r2sync.client(env), env["R2_BUCKET"]
    now = dt.datetime.now()
    cutoff = now - dt.timedelta(hours=RETAIN_H)

    # ---- 1. inventory and prune ----
    keys = r2sync.list_keys(s3, bucket, "frames/")
    old = [k for k in keys if k.split("/")[1] in ("radar", "sat", "dbz") and (stamp_of(k) or now) < cutoff]
    if old:
        r2sync.delete_keys(s3, bucket, old)
        log("pruned %d objects older than %d h" % (len(old), RETAIN_H))
        keys = [k for k in keys if k not in set(old)]

    # ---- 2. rebuild local layout ----
    n_ph = n_dl = 0
    for k in keys:
        parts = k.split("/")
        if len(parts) != 3:
            continue
        sub, fn = parts[1], parts[2]
        if sub in ("radar", "sat"):
            touch(os.path.join(FRAMES, sub, fn))
            n_ph += 1
        elif sub == "dbz":
            dest = os.path.join(FRAMES, "dbz", fn)
            if not os.path.exists(dest) or os.path.getsize(dest) == 0:
                r2sync.download(s3, bucket, k, dest)
                n_dl += 1
    os.makedirs(DATA, exist_ok=True)
    for fn in STATE_FILES:
        dest = os.path.join(DATA, fn)
        if not os.path.exists(dest):
            try:
                r2sync.download(s3, bucket, STATE_PREFIX + fn, dest)
            except Exception:  # noqa: BLE001
                pass
    # the uploader must know these already exist so it never overwrites a real frame with a placeholder
    with open(r2sync.STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(keys), f)
    log("layout: %d placeholders, %d reflectivity scans fetched" % (n_ph, n_dl))

    # ---- 3. one cycle: "radar" mode is the quick 15-minute pass (radar, satellite, accumulation,
    #         alerts); "hourly" mode also runs stations, rivers, forecast, MRMS, freezing level,
    #         SNODAS, webcams, avalanche and basins ----
    import capture
    mode = (sys.argv[1] if len(sys.argv) > 1 else "radar").lower()
    due = mode == "hourly"
    capture.FORCE_HOURLY = due
    capture.FORCE_HALF = due
    before = time.time()
    capture.capture_all()

    # ---- 4. push changed caches ----
    n_up = 0
    for fn in STATE_FILES:
        p = os.path.join(DATA, fn)
        if os.path.exists(p) and os.path.getmtime(p) >= before - 1:
            r2sync.put(s3, bucket, STATE_PREFIX + fn, p, "private, max-age=0")
            n_up += 1
    log("done in %.0fs (%d caches pushed, hourly jobs %s)" % (time.time() - t0, n_up, "ran" if due else "skipped"))


if __name__ == "__main__":
    main()
