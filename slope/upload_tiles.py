"""
Upload the slope-angle tiles (slope/work/tiles) to R2 for the map. Chris runs this.

  python slope/upload_tiles.py --dry-run    count the files and bytes, upload nothing
  python slope/upload_tiles.py              upload; resumable: tiles already sent are listed in work/uploaded.txt

Zooms, key prefix and cache header come from slope_config.yaml (upload:). Credentials come from r2.env through
r2sync, like the rest of the pipeline. Run from radar/ with the main (Anaconda) Python.
"""
import argparse
import concurrent.futures as cf
import os
import sys
import threading
import time

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import r2sync  # noqa: E402

with open(os.path.join(HERE, "slope_config.yaml"), encoding="utf-8") as _f:
    CFG = yaml.safe_load(_f)
U = CFG["upload"]
WORK = os.path.join(HERE, CFG["work"]["dir"])
TILES = os.path.join(WORK, "tiles")
DONE = os.path.join(WORK, "uploaded.txt")


def tiles():
    for z in range(U["zoom_min"], U["zoom_max"] + 1):
        zd = os.path.join(TILES, str(z))
        for x in sorted(os.listdir(zd), key=int):
            for fn in sorted(os.listdir(os.path.join(zd, x))):
                if fn.endswith(".png"):
                    yield "%d/%s/%s" % (z, x, fn)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    rel = list(tiles())
    done = set()
    if os.path.exists(DONE):
        with open(DONE, encoding="utf-8") as f:
            done = {line.strip() for line in f if line.strip()}
    todo = [r for r in rel if r not in done]
    size = sum(os.path.getsize(os.path.join(TILES, r)) for r in todo)
    print("zoom %d-%d: %d tiles, %d already uploaded, %d to go (%.2f GB) -> %s"
          % (U["zoom_min"], U["zoom_max"], len(rel), len(rel) - len(todo), len(todo), size / 1e9, U["prefix"]), flush=True)
    if a.dry_run or not todo:
        return
    env = r2sync.load_env()
    if env is None:
        raise SystemExit("r2.env not found")
    s3, bucket = r2sync.client(env), env["R2_BUCKET"]
    lock, t0, sent = threading.Lock(), time.time(), [0]
    log = open(DONE, "a", encoding="utf-8", buffering=1)

    def put(r):
        for k in range(3):
            try:
                with open(os.path.join(TILES, r), "rb") as fh:
                    s3.put_object(Bucket=bucket, Key=U["prefix"] + r, Body=fh, ContentType="image/png", CacheControl=U["cache_control"])
                break
            except Exception:  # noqa: BLE001
                if k == 2:
                    raise
                time.sleep(5 * (k + 1))
        with lock:
            log.write(r + "\n")
            sent[0] += 1
            if sent[0] % 5000 == 0:
                el = time.time() - t0
                print("  %d / %d  (%.0f/s, about %.0f min left)" % (sent[0], len(todo), sent[0] / el, (len(todo) - sent[0]) / (sent[0] / el) / 60), flush=True)

    with cf.ThreadPoolExecutor(U["workers"]) as ex:
        list(ex.map(put, todo))
    print("done: %d tiles in %.0f min; e.g. %s/%s%s" % (len(todo), (time.time() - t0) / 60, env.get("R2_PUBLIC_URL", ""), U["prefix"], todo[-1]))


if __name__ == "__main__":
    main()
