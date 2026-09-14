"""
Upload radar frames to Cloudflare R2 so the public viewer can play them.

Reads credentials from r2.env (next to this file):
  R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET, R2_PUBLIC_URL

What gets uploaded, mirroring the local layout:
  frames/rainviewer/*.jpg, frames/nws_pnw/*.gif, frames/nws_conus/*.gif   (once each)
  frames/accum/*.jpg                                                     (every cycle)
  frames.js                                                              (every cycle)
The dBZ scans and basemap stay local; the site does not need them.

Run standalone to push everything not yet uploaded:  python r2sync.py
"""
import json
import os
import sys

import region

ROOT = os.path.dirname(os.path.abspath(__file__))
ENV_FILE = os.path.join(ROOT, "r2.env")
STATE_FILE = os.path.join(region.region_dir(), "r2_uploaded.json")
PREFIX = region.prefix()
SKIP_FRAMES = False       # hourly cloud job: never upload frames or the manifest (the radar job owns them)
FRAME_DIRS = ("radar", "sat", "dbz", "rainviewer", "nws_pnw", "nws_conus")
CONTENT_TYPES = {".jpg": "image/jpeg", ".gif": "image/gif", ".png": "image/png", ".webp": "image/webp", ".npy": "application/octet-stream",
                 ".js": "application/javascript", ".json": "application/json", ".geojson": "application/geo+json"}


def load_env():
    if not os.path.exists(ENV_FILE):
        env = {k: os.environ.get(k, "") for k in ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET", "R2_PUBLIC_URL")}
        return env if env["R2_ACCOUNT_ID"] and env["R2_ACCESS_KEY_ID"] else None
    env = {}
    with open(ENV_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    need = ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET")
    missing = [k for k in need if not env.get(k)]
    if missing:
        raise RuntimeError("r2.env is missing: " + ", ".join(missing))
    return env


def client(env):
    import boto3
    from botocore.config import Config
    return boto3.client(
        "s3",
        endpoint_url="https://%s.r2.cloudflarestorage.com" % env["R2_ACCOUNT_ID"],
        aws_access_key_id=env["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=env["R2_SECRET_ACCESS_KEY"],
        region_name="auto",
        config=Config(retries={"max_attempts": 3}, connect_timeout=15, read_timeout=60),
    )


def list_keys(s3, bucket, prefix):
    keys, token = [], None
    while True:
        kw = {"Bucket": bucket, "Prefix": prefix}
        if token:
            kw["ContinuationToken"] = token
        r = s3.list_objects_v2(**kw)
        keys += [o["Key"] for o in r.get("Contents", [])]
        if not r.get("IsTruncated"):
            return keys
        token = r.get("NextContinuationToken")


def delete_keys(s3, bucket, keys):
    for i in range(0, len(keys), 1000):
        s3.delete_objects(Bucket=bucket, Delete={"Objects": [{"Key": k} for k in keys[i:i + 1000]], "Quiet": True})


def download(s3, bucket, key, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    s3.download_file(bucket, key, path)


def _load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return set(json.load(f))
    except (OSError, ValueError):
        return set()


def _save_state(done):
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(sorted(done), f)
    os.replace(tmp, STATE_FILE)


def put(s3, bucket, key, path, cache):
    ext = os.path.splitext(path)[1].lower()
    with open(path, "rb") as f:
        s3.put_object(Bucket=bucket, Key=key, Body=f,
                      ContentType=CONTENT_TYPES.get(ext, "application/octet-stream"),
                      CacheControl=cache)


def sync(log=print):
    """Upload anything new. Returns a short status string, or None if R2 is not configured."""
    env = load_env()
    if env is None:
        return None
    s3, bucket = client(env), env["R2_BUCKET"]
    done, n_new = _load_state(), 0

    # immutable frames: upload once
    for d in ([] if SKIP_FRAMES else FRAME_DIRS):
        full = os.path.join(region.frames_dir(), d)
        if not os.path.isdir(full):
            continue
        for fn in sorted(os.listdir(full)):
            key = PREFIX + "frames/%s/%s" % (d, fn)
            if key in done or fn.endswith(".tmp") or os.path.getsize(os.path.join(full, fn)) == 0:
                continue
            put(s3, bucket, key, os.path.join(full, fn), "public, max-age=31536000, immutable")
            done.add(key)
            n_new += 1
            if n_new % 10 == 0:
                _save_state(done)

    # accumulation maps: overwritten each cycle, short cache
    for sub in ("accum", "interp", "forecast", "mrms", "freezing", "snodas"):
        acc = os.path.join(region.frames_dir(), sub)
        if os.path.isdir(acc):
            for fn in os.listdir(acc):
                if fn.endswith((".jpg", ".webp")) and ".tmp" not in fn:
                    put(s3, bucket, PREFIX + "frames/%s/%s" % (sub, fn), os.path.join(acc, fn), "public, max-age=60")

    # click-anywhere value grids: rewritten hourly
    vdir = os.path.join(region.data_dir(), "values")
    if os.path.isdir(vdir):
        for fn in os.listdir(vdir):
            if fn.endswith(".js"):
                put(s3, bucket, PREFIX + "data/values/" + fn, os.path.join(vdir, fn), "public, max-age=300")

    # data files for the map layers
    data_dir = region.data_dir()
    if os.path.isdir(data_dir):
        for fn in os.listdir(data_dir):
            if fn.endswith((".tmp", "_cache.json", ".npy", ".geojson")) or os.path.isdir(os.path.join(data_dir, fn)):
                continue      # caches, terrain and basin outlines are private state, not site data
            if fn.endswith(".js"):     # data files are rewritten often: always push, never cache
                put(s3, bucket, PREFIX + "data/" + fn, os.path.join(data_dir, fn), "no-cache")
                continue
            key = PREFIX + "data/%s@%d" % (fn, int(os.path.getmtime(os.path.join(data_dir, fn))))
            if key not in done:
                put(s3, bucket, PREFIX + "data/" + fn, os.path.join(data_dir, fn), "public, max-age=3600")
                done.add(key)

    # manifest last, so the site never lists a frame that is not there yet
    manifest = os.path.join(region.region_dir(), "frames.js")
    if os.path.exists(manifest) and not SKIP_FRAMES:
        put(s3, bucket, PREFIX + "frames.js", manifest, "no-cache")

    _save_state(done)
    return "r2 +%d new, %d total" % (n_new, len(done))


if __name__ == "__main__":
    try:
        r = sync()
        print(r or "r2.env not found; nothing uploaded")
    except Exception as e:  # noqa: BLE001
        print("upload failed:", repr(e))
        sys.exit(1)
