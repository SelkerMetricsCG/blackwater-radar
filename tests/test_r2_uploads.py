"""
R2 Class A budget (2026-09-28): the jobs upload only what changed.

- r2sync skips a rewritten file (map, value grid, data .js, frames.js) whose MD5 equals the ETag R2 listed for it.
- cloud.py pushes a state cache only when its content differs from the copy it downloaded (it used to push any cache
  touched within 1 s of the run start, so the hourly job wrote its start-of-run aq_cache.json back over newer ones).
- a second hourly run in the same UTC hour does nothing, unless forced.

The S3 client is a small in-memory fake: R2 is an external service and these tests never touch the network.
"""
import datetime as dt
import hashlib
import os
import sys
import types

import pytest

import cloud
import r2sync
import region

UTC = dt.timezone.utc
P = r2sync.PREFIX


def md5(b):
    return hashlib.md5(b).hexdigest()


class FakeS3:
    """Just the S3 calls r2sync and cloud.py make. objects: key -> (bytes, LastModified)."""

    def __init__(self, objects=None, page=2):
        old = dt.datetime(2026, 9, 1, tzinfo=UTC)
        self.objects = {k: (v, old) if isinstance(v, bytes) else v for k, v in (objects or {}).items()}
        self.page, self.puts, self.downloads, self.lists = page, [], [], 0

    def put_object(self, Bucket, Key, Body, **kw):
        self.objects[Key] = (Body.read(), dt.datetime.now(UTC))
        self.puts.append(Key)

    def download_file(self, Bucket, Key, Filename):
        if Key not in self.objects:
            raise RuntimeError("404 " + Key)
        with open(Filename, "wb") as f:
            f.write(self.objects[Key][0])
        self.downloads.append(Key)

    def list_objects_v2(self, Bucket, Prefix, ContinuationToken=None):
        self.lists += 1
        keys = sorted(k for k in self.objects if k.startswith(Prefix))
        start = int(ContinuationToken or 0)
        chunk = keys[start:start + self.page]
        r = {"Contents": [{"Key": k, "ETag": '"%s"' % md5(self.objects[k][0]), "LastModified": self.objects[k][1]} for k in chunk]}
        if start + self.page < len(keys):
            r.update(IsTruncated=True, NextContinuationToken=str(start + self.page))
        return r

    def delete_objects(self, Bucket, Delete):
        for o in Delete["Objects"]:
            self.objects.pop(o["Key"], None)


@pytest.fixture
def local(tmp_path, monkeypatch):
    """Region folders under tmp_path; R2 credentials and client replaced by the fake."""
    monkeypatch.setattr(region, "region_dir", lambda: str(tmp_path))
    monkeypatch.setattr(r2sync, "STATE_FILE", str(tmp_path / "r2_uploaded.json"))
    monkeypatch.setattr(r2sync, "SKIP_FRAMES", False)
    monkeypatch.setattr(r2sync, "REMOTE", {}, raising=False)
    monkeypatch.setattr(r2sync, "load_env", lambda: {"R2_BUCKET": "radar", "R2_ACCOUNT_ID": "x", "R2_ACCESS_KEY_ID": "x"})
    monkeypatch.setattr(cloud, "FRAMES", str(tmp_path / "frames"))
    monkeypatch.setattr(cloud, "DATA", str(tmp_path / "data"))
    return tmp_path


def write(root, rel, data):
    path = os.path.join(str(root), *rel.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    return path


# ---- listing ----

def test_list_objects_returns_etag_without_quotes_and_time_across_pages():
    t = dt.datetime(2026, 9, 28, 22, 19, tzinfo=UTC)
    s3 = FakeS3({P + "data/a.js": b"a", P + "data/b.js": (b"b", t), P + "data/values/c.js": b"c", P + "frames/x.webp": b"x"})
    got = r2sync.list_objects(s3, "radar", P + "data/")
    assert set(got) == {P + "data/a.js", P + "data/b.js", P + "data/values/c.js"}
    assert got[P + "data/b.js"] == (md5(b"b"), t)
    assert s3.lists == 2                      # 3 keys, pages of 2


# ---- fix 2: rewritten files are uploaded only when their bytes changed ----

REWRITTEN = ["frames/accum/1h.webp", "frames/forecast/maxt.webp", "data/values/elev.js", "data/snodas.js", "frames.js"]


@pytest.mark.parametrize("rel", REWRITTEN)
def test_sync_skips_rewritten_file_identical_to_r2(local, monkeypatch, rel):
    write(local, rel, b"same bytes")
    s3 = FakeS3()
    monkeypatch.setattr(r2sync, "client", lambda env: s3)
    r2sync.REMOTE[P + rel] = (md5(b"same bytes"), dt.datetime.now(UTC))
    r2sync.sync(log=lambda *a: None)
    assert s3.puts == []


@pytest.mark.parametrize("rel", REWRITTEN)
def test_sync_uploads_rewritten_file_that_changed(local, monkeypatch, rel):
    write(local, rel, b"new bytes")
    s3 = FakeS3()
    monkeypatch.setattr(r2sync, "client", lambda env: s3)
    r2sync.REMOTE[P + rel] = (md5(b"old bytes"), dt.datetime.now(UTC))
    r2sync.sync(log=lambda *a: None)
    assert s3.puts == [P + rel]


@pytest.mark.parametrize("rel", REWRITTEN)
def test_sync_uploads_rewritten_file_r2_does_not_have(local, monkeypatch, rel):
    write(local, rel, b"new bytes")
    s3 = FakeS3()
    monkeypatch.setattr(r2sync, "client", lambda env: s3)
    r2sync.sync(log=lambda *a: None)
    assert s3.puts == [P + rel]


def test_sync_reports_skipped_count(local, monkeypatch):
    write(local, "data/alerts.js", b"A")
    write(local, "data/airquality.js", b"Q2")
    s3 = FakeS3()
    monkeypatch.setattr(r2sync, "client", lambda env: s3)
    r2sync.REMOTE.update({P + "data/alerts.js": (md5(b"A"), None), P + "data/airquality.js": (md5(b"Q1"), None)})
    status = r2sync.sync(log=lambda *a: None)
    assert "1 updated" in status and "1 unchanged" in status


# ---- fix 1: state caches go back only when their content changed ----

def test_push_state_skips_cache_unchanged_since_download(local):
    s3 = FakeS3({P + "state/zone_cache.json": b"z", P + "state/aq_cache.json": b"q"})
    pulled = cloud.pull_state(s3, "radar")
    assert cloud.push_state(s3, "radar", pulled) == 0
    assert s3.puts == []


def test_push_state_uploads_cache_changed_during_run(local):
    s3 = FakeS3({P + "state/zone_cache.json": b"z", P + "state/aq_cache.json": b"q"})
    pulled = cloud.pull_state(s3, "radar")
    write(local, "data/aq_cache.json", b"q + one more hour")
    assert cloud.push_state(s3, "radar", pulled) == 1
    assert s3.puts == [P + "state/aq_cache.json"]


def test_push_state_uploads_cache_created_during_run(local):
    s3 = FakeS3()
    pulled = cloud.pull_state(s3, "radar")
    write(local, "data/youtube_cache.json", b"{}")
    assert cloud.push_state(s3, "radar", pulled) == 1
    assert s3.puts == [P + "state/youtube_cache.json"]


def test_pull_state_keeps_a_local_copy_and_does_not_push_it_back(local):
    """A PC run keeps its own caches (no download); an untouched one is not uploaded."""
    write(local, "data/zone_cache.json", b"local")
    s3 = FakeS3({P + "state/zone_cache.json": b"remote"})
    pulled = cloud.pull_state(s3, "radar")
    assert P + "state/zone_cache.json" not in s3.downloads
    assert cloud.push_state(s3, "radar", pulled) == 0


# ---- fix 3: one hourly run per UTC hour ----

NOW = dt.datetime(2026, 9, 28, 22, 25, tzinfo=UTC)


def at(h, m):
    return dt.datetime(2026, 9, 28, h, m, tzinfo=UTC)


def test_hourly_skips_when_stations_written_this_utc_hour():
    remote = {P + "data/stations.js": ("e", at(22, 19))}
    assert cloud.ran_this_hour(remote, NOW) == at(22, 19)


def test_hourly_runs_when_this_hours_upload_is_old():
    """A run that finished at 22:05 (it started late in the 21:00 hour) does not make the 22:50 run skip."""
    remote = {P + "data/stations.js": ("e", at(22, 5))}
    assert cloud.ran_this_hour(remote, at(22, 50)) is None


def test_hourly_runs_when_stations_written_last_hour():
    remote = {P + "data/stations.js": ("e", dt.datetime(2026, 9, 28, 21, 58, tzinfo=UTC))}
    assert cloud.ran_this_hour(remote, NOW) is None


def test_hourly_runs_when_stations_missing():
    assert cloud.ran_this_hour({}, NOW) is None


def test_hourly_runs_when_forced():
    remote = {P + "data/stations.js": ("e", dt.datetime(2026, 9, 28, 22, 19, tzinfo=UTC))}
    assert cloud.ran_this_hour(remote, NOW, force=True) is None


# ---- whole run (cloud.main with a stand-in capture module) ----

def fake_capture(monkeypatch, work):
    """capture.capture_all stand-in: runs work(), then r2sync.sync() as the real one does."""
    calls = []

    def capture_all():
        calls.append(1)
        work()
        r2sync.sync(lambda *a: None)
    monkeypatch.setitem(sys.modules, "capture", types.SimpleNamespace(capture_all=capture_all))
    return calls


def test_capture_run_uploads_only_what_changed(local, monkeypatch):
    s3 = FakeS3({P + "frames/accum/1h.webp": b"old map", P + "data/alerts.js": b"A", P + "data/snodas.js": b"S",
                 P + "state/zone_cache.json": b"Z", P + "state/snodas.js": b"S", P + "state/youtube_cache.json": b"Y",
                 P + "state/aq_cache.json": b"Q"})
    monkeypatch.setattr(r2sync, "client", lambda env: s3)
    monkeypatch.setattr(sys, "argv", ["cloud.py", "radar"])

    def work():
        write(local, "frames/accum/1h.webp", b"new map")      # changed
        write(local, "data/alerts.js", b"A")                   # rewritten, same bytes
        write(local, "data/aq_cache.json", b"Q + new hour")    # cache the run changed
    fake_capture(monkeypatch, work)
    cloud.main()
    assert sorted(s3.puts) == [P + "frames/accum/1h.webp", P + "state/aq_cache.json"]


def test_capture_run_skips_unchanged_manifest(local, monkeypatch):
    """frames.js sits beside frames/, not under it: the listing must still cover it."""
    s3 = FakeS3({P + "frames.js": b"M", P + "frames/radar/r20260928_2200.webp": b"R"})
    monkeypatch.setattr(r2sync, "client", lambda env: s3)
    monkeypatch.setattr(sys, "argv", ["cloud.py", "radar"])
    fake_capture(monkeypatch, lambda: write(local, "frames.js", b"M"))
    cloud.main()
    assert s3.puts == []


def hourly_run(local, monkeypatch, objects, work, force=None):
    """cloud.main() in hourly mode at NOW (22:25 UTC) against a fake bucket; returns (capture calls, fake S3)."""
    s3 = FakeS3(objects)
    monkeypatch.setattr(r2sync, "client", lambda env: s3)
    monkeypatch.setattr(sys, "argv", ["cloud.py", "hourly"])
    monkeypatch.setattr(cloud, "utcnow", lambda: NOW)
    if force is None:
        monkeypatch.delenv("HOURLY_FORCE", raising=False)
    else:
        monkeypatch.setenv("HOURLY_FORCE", force)
    calls = fake_capture(monkeypatch, work)
    cloud.main()
    return calls, s3


def test_second_hourly_run_in_same_hour_does_nothing(local, monkeypatch):
    calls, s3 = hourly_run(local, monkeypatch, {P + "data/stations.js": (b"S", at(22, 19)), P + "state/nwps_cache.json": b"N"},
                           lambda: None)
    assert calls == [] and s3.puts == [] and s3.downloads == []


@pytest.mark.parametrize("force", ["true", "1"])
def test_forced_hourly_run_proceeds(local, monkeypatch, force):
    calls, s3 = hourly_run(local, monkeypatch, {P + "data/stations.js": (b"S", at(22, 19))},
                           lambda: write(local, "data/stations.js", b"S2"), force=force)
    assert calls == [1] and s3.puts == [P + "data/stations.js"]


def test_hourly_run_proceeds_when_last_one_was_last_hour(local, monkeypatch):
    calls, s3 = hourly_run(local, monkeypatch, {P + "data/stations.js": (b"S", at(21, 20))},
                           lambda: write(local, "data/stations.js", b"S2"))
    assert calls == [1] and s3.puts == [P + "data/stations.js"]


def test_hourly_run_skips_its_own_unchanged_maps(local, monkeypatch):
    """The hourly job's maps live under frames/ (forecast, freezing, interp, mrms, snodas): it must list frames/ too."""
    def work():
        write(local, "frames/forecast/maxt.webp", b"F")        # same forecast as last hour
        write(local, "frames/interp/precip_1h.webp", b"I2")    # new stations, new map
        write(local, "data/stations.js", b"S2")
    calls, s3 = hourly_run(local, monkeypatch, {P + "data/stations.js": (b"S", at(21, 20)),
                                                P + "frames/forecast/maxt.webp": b"F", P + "frames/interp/precip_1h.webp": b"I1"}, work)
    assert sorted(s3.puts) == [P + "data/stations.js", P + "frames/interp/precip_1h.webp"]
