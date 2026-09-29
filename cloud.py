"""
One capture cycle on a fresh machine (GitHub Actions), with all state in R2.

  1. list what R2 already has (frames/ and data/, with ETags, so r2sync skips files whose bytes are unchanged);
     drop anything older than RETAIN_H hours (radar, satellite, reflectivity scans) so the archive always holds
     a rolling day. An hourly run stops here if this region's stations.js already went up this UTC hour, under
     SKIP_WITHIN_MIN ago (GitHub's schedule sometimes starts a second run beside radar-cron's); HOURLY_FORCE=true
     overrides.
  2. recreate the local layout: empty placeholders for radar/satellite frames (so the
     manifest lists them and nothing is re-downloaded), real copies of the reflectivity
     scans (the accumulation math needs them), and the cache files under state/
  3. run one capture cycle (capture.capture_all); "hourly" mode adds the slow jobs
  4. push the caches whose content the run changed back to state/ (never an untouched copy: the two
     modes run at once, and a stale copy would overwrite the other job's update)

Credentials come from environment variables (R2_ACCOUNT_ID, R2_ACCESS_KEY_ID,
R2_SECRET_ACCESS_KEY, R2_BUCKET, R2_PUBLIC_URL) or from r2.env locally.
Set TZ=America/Los_Angeles so file names and labels stay in Pacific time.

Usage:  python cloud.py [radar|hourly]

The two modes write disjoint sets of files (radar: frames, accumulation, manifest, alerts, air quality;
hourly: stations, rivers, forecast, MRMS QPE, freezing level, SNODAS, webcams, avalanche,
basins), so they run at the same time without sharing a lock.
"""
import datetime as dt
import json
import os
import re
import sys
import time

import r2sync

import region

ROOT = os.path.dirname(os.path.abspath(__file__))
FRAMES = region.frames_dir()
DATA = region.data_dir()
RETAIN_H = 30                      # rolling archive: keep this many hours of scans
SKIP_WITHIN_MIN = 30               # judgment call (2026-09-28): a queued second hourly run starts within minutes of the first
                                   # one's end; the next hour's run starts >= 41 min after it (runs measured 7-19 min)
STATE_PREFIX = region.prefix() + "state/"
STATE_FILES = ["dem_z7.npy", "huc6.geojson", "station_meta_cache.json", "snotel_meta_cache.json", "usgs_median_cache.json", "nwps_cache.json",
               "usgs_lid_cache.json", "nws_stations_cache.json", "zone_cache.json", "snodas.js", "youtube_cache.json", "aq_cache.json",
               "fires_cache.json"]
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


def utcnow():
    return dt.datetime.now(dt.timezone.utc)


def ran_this_hour(remote, now, force=False):
    """When this region's stations.js went up in the current UTC hour and under SKIP_WITHIN_MIN ago, that time (the
    hourly layers are done); None if not, or if forced. remote: r2sync.list_objects() output; now: aware UTC.
    stations.js goes up at the end of a run, so the age limit keeps a run that started late in the previous hour
    from cancelling this hour's."""
    t = remote.get(region.prefix() + "data/stations.js", (None, None))[1]
    if force or t is None or t < now.replace(minute=0, second=0, microsecond=0) or now - t > dt.timedelta(minutes=SKIP_WITHIN_MIN):
        return None
    return t


def pull_state(s3, bucket):
    """Fetch the caches this machine lacks from state/; return {name: MD5} of every local cache for push_state()."""
    os.makedirs(DATA, exist_ok=True)
    pulled = {}
    for fn in STATE_FILES:
        dest = os.path.join(DATA, fn)
        if not os.path.exists(dest):
            try:
                r2sync.download(s3, bucket, STATE_PREFIX + fn, dest)
            except Exception:  # noqa: BLE001
                pass
        if os.path.exists(dest):
            pulled[fn] = r2sync.file_md5(dest)
    return pulled


def push_state(s3, bucket, pulled):
    """Upload the caches whose content differs from what pull_state() found. Returns how many went up."""
    n = 0
    for fn in STATE_FILES:
        p = os.path.join(DATA, fn)
        if os.path.exists(p) and r2sync.file_md5(p) != pulled.get(fn):
            r2sync.put(s3, bucket, STATE_PREFIX + fn, p, "private, max-age=0")
            n += 1
    return n


def main():
    t0 = time.time()
    env = r2sync.load_env()
    if not env:
        raise SystemExit("no R2 credentials")
    s3, bucket = r2sync.client(env), env["R2_BUCKET"]
    now = dt.datetime.now()
    cutoff = now - dt.timedelta(hours=RETAIN_H)

    mode = (sys.argv[1] if len(sys.argv) > 1 else "radar").lower()
    hourly = mode == "hourly"

    # ---- 1. inventory (ETags let r2sync skip unchanged files; the hourly job's maps are under frames/ too)
    #         and prune (radar mode only: the hourly job never touches the scans) ----
    remote = r2sync.list_objects(s3, bucket, region.prefix() + "frames")     # frames/ and frames.js
    keys = [k for k in remote if k.startswith(region.prefix() + "frames/")]
    remote.update(r2sync.list_objects(s3, bucket, region.prefix() + "data/"))
    if hourly:
        done_at = ran_this_hour(remote, utcnow(), os.environ.get("HOURLY_FORCE", "").lower() in ("1", "true"))
        if done_at:
            log("%s: hourly layers already went up at %s UTC this hour; nothing to do (HOURLY_FORCE=true runs anyway)"
                % (region.KEY, done_at.strftime("%H:%M")))
            return
    r2sync.REMOTE = remote
    old = [] if hourly else [k for k in keys if k.split("/")[2] in ("radar", "sat", "dbz") and (stamp_of(k) or now) < cutoff]
    if old:
        r2sync.delete_keys(s3, bucket, old)
        log("pruned %d objects older than %d h" % (len(old), RETAIN_H))
        keys = [k for k in keys if k not in set(old)]

    # ---- 2. rebuild local layout ----
    n_ph = n_dl = 0
    for k in ([] if hourly else keys):
        parts = k.split("/")
        if len(parts) != 4:
            continue
        sub, fn = parts[2], parts[3]
        if sub in ("radar", "sat"):
            touch(os.path.join(FRAMES, sub, fn))
            n_ph += 1
        elif sub == "dbz":
            dest = os.path.join(FRAMES, "dbz", fn)
            if not os.path.exists(dest) or os.path.getsize(dest) == 0:
                r2sync.download(s3, bucket, k, dest)
                n_dl += 1
    pulled = pull_state(s3, bucket)
    # the uploader must know these already exist so it never overwrites a real frame with a placeholder
    with open(r2sync.STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(keys), f)
    log("layout: %d placeholders, %d reflectivity scans fetched" % (n_ph, n_dl))

    # ---- 3. one cycle: "radar" mode is the quick 15-minute pass (radar, satellite, accumulation,
    #         alerts, air quality); "hourly" mode also runs stations, rivers, forecast, MRMS, freezing level,
    #         SNODAS, webcams, avalanche and basins ----
    import capture
    due = hourly
    capture.FORCE_HOURLY = due
    capture.FORCE_HALF = due
    capture.HOURLY_ONLY = due
    r2sync.SKIP_FRAMES = due          # the radar job owns frames and the manifest
    capture.capture_all()

    # ---- 4. push changed caches ----
    n_up = push_state(s3, bucket, pulled)
    log("%s: done in %.0fs (%d caches pushed, hourly jobs %s)" % (region.KEY, time.time() - t0, n_up, "ran" if due else "skipped"))


if __name__ == "__main__":
    main()
