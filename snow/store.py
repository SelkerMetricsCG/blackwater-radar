"""
R2 access for the snow model's daily run: the lattice, the archive days and the model state live in the bucket;
the runner is a fresh machine. Keys are under <region>/snow/. Without R2 credentials everything is read from and
written to the local regions/<r>/snow/ tree only (tests, a PC without r2.env).
"""
import gzip
import json
import os

import r2sync
import region

SNOW_DIR = os.path.join(region.region_dir(), "snow")
_ENV = None
_S3 = None


def _client():
    global _ENV, _S3
    if _ENV is None:
        _ENV = r2sync.load_env() or {}
        if _ENV:
            _S3 = r2sync.client(_ENV)
    return _S3, _ENV.get("R2_BUCKET")


def local(rel):
    """local path of <region>/snow/<rel>"""
    return os.path.join(SNOW_DIR, rel.replace("/", os.sep))


def fetch(rel, log=print):
    """make sure <region>/snow/<rel> is on disk (from R2 when possible); returns the path or None"""
    path = local(rel)
    if os.path.exists(path):
        return path
    s3, bucket = _client()
    if s3 is None:
        return None
    try:
        r2sync.download(s3, bucket, region.prefix() + "snow/" + rel, path)
        return path
    except Exception as e:  # noqa: BLE001
        log("store: %s not fetched: %r" % (rel, e))
        return None


def listing(rel_prefix):
    """names under <region>/snow/<rel_prefix> (R2 when possible, else local)"""
    s3, bucket = _client()
    if s3 is not None:
        pre = region.prefix() + "snow/" + rel_prefix
        return [k[len(pre):] for k in r2sync.list_objects(s3, bucket, pre)]
    base = local(rel_prefix)
    if not os.path.isdir(base):
        return []
    return sorted(os.path.relpath(os.path.join(r, f), base).replace(os.sep, "/") for r, _, fs in os.walk(base) for f in fs)


def put(rel, cache="public, max-age=300", log=print):
    """upload <region>/snow/<rel> (no-op without R2)"""
    s3, bucket = _client()
    if s3 is None:
        return False
    r2sync.put(s3, bucket, region.prefix() + "snow/" + rel, local(rel), cache)
    return True


def read_json(rel, log=print):
    path = fetch(rel, log)
    if not path:
        return None
    try:
        if path.endswith(".gz"):
            with gzip.open(path, "rt", encoding="utf-8") as f:
                return json.load(f)
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError) as e:
        log("store: %s unreadable: %r" % (rel, e))
        return None
