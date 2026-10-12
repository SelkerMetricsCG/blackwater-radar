"""
Fill gaps in the season archive from the agencies' own archives; every file is new (nothing is ever rewritten).

  <date>/snodas.json.gz   SNODAS depth and SWE for the date (NSIDC G02158 masked daily tar), the same 128 px grids the
                          hourly job files from 2026-10-11 on (snow/archive.py); the daily files' copies were empty
  <date>/mrms1h.json.gz   MRMS 1 h QPE for every hour of the day's 24 h window that the hourly files lack (each valid
                          hour counts once: a stalled NOAA feed repeats its last hour), from NOAA's archive on AWS
                          (noaa-mrms-pds), Pass 2 where it exists, else Pass 1. NOAA's Pass 2 feed stopped 2026-10-09
                          19Z to 2026-10-10 15Z, the evening of the season's first snow

  python -m snow.backfill --start 2026-09-28 --end 2026-10-11              local files only (regions/<r>/snow/archive/)
  python -m snow.backfill --start 2026-09-28 --end 2026-10-11 --upload     and to R2 (immutable), skipping files there
"""
import argparse
import datetime as dt
import io
import os
import shutil
import tarfile
import tempfile
import urllib.request

import region
import values
from snow import archive, state, store

UA = "BlackwaterSnowArchive/1.0"
NSIDC = "https://noaadata.apps.nsidc.org/NOAA/G02158/masked/%s/SNODAS_%s.tar"
AWS = "https://noaa-mrms-pds.s3.amazonaws.com/CONUS/MultiSensor_QPE_01H_%s_00.00/%s/MRMS_MultiSensor_QPE_01H_%s_00.00_%s.grib2.gz"


def fetch(url, timeout=300):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def pack(name, arr, n_out, tmp, unit, scale):
    """an array on the map window -> the archive's grid form, through the same value-grid path the hourly job uses"""
    values.write_grid(name, arr, unit=unit, scale=scale, out_dir=tmp)
    return archive.grid(name, n_out, tmp)


def snodas_day(day, tmp, log=print):
    """{date, grids, source} for one SNODAS date, or None when NSIDC has no file"""
    import snodas
    url = NSIDC % (day.strftime("%Y/%m_%b"), day.strftime("%Y%m%d"))
    try:
        tar = tarfile.open(fileobj=io.BytesIO(fetch(url)))
    except Exception as e:  # noqa: BLE001
        log("backfill: SNODAS %s not available (%r)" % (day, e))
        return None
    mask_mm = 3000 if 7 <= day.month <= 11 else 10000                  # as snodas.build
    grids = {}
    for key, code in (("depth", "1036"), ("swe", "1034")):
        a, geo = snodas.read_product(tar, code, mask_mm)
        grids[key] = pack("snodas_" + key, snodas.window_grid(a, geo), archive.SNODAS_N, tmp, "in", 0.1)
    return {"date": day.isoformat(), "grids": grids, "source": "NSIDC G02158 masked, backfilled %s" % dt.date.today()}


def window_end(day, tz_offset_h, log=print):
    """the end of the day's 24 h precipitation window: the next day's MRMS 24 h valid time, else local midnight"""
    dn = store.read_json("archive/%s/daily.json.gz" % (day + dt.timedelta(days=1)).isoformat(), log) or {}
    return state._iso_utc((dn.get("mrms24") or {}).get("valid_utc")) or \
        dt.datetime.combine(day + dt.timedelta(days=1), dt.time()) - dt.timedelta(hours=tz_offset_h)


def mrms_gaps(day, names, end_utc, log=print):
    """valid hours (UTC) of the day's window that no hourly file holds"""
    hourlies = [store.read_json("archive/%s/%s" % (day.isoformat(), n), log) for n in names if n[:2].isdigit() and n.endswith(".json.gz")]
    have = {v for v, _ in state.precip_hours([h for h in hourlies if h], None, end_utc)}
    want = [end_utc - dt.timedelta(hours=k) for k in range(23, -1, -1)]
    return [v for v in want if v not in have]


def mrms_hour(v, tmp, lat_w, lon_w, log=print):
    """(grid, product) for the hour ending at v from NOAA's AWS archive, or None"""
    import mrms
    for product in ("Pass2", "Pass1"):
        url = AWS % (product, v.strftime("%Y%m%d"), product, v.strftime("%Y%m%d-%H%M%S"))
        gz = os.path.join(tmp, "q_%s_%s.grib2.gz" % (product, v.strftime("%Y%m%d%H")))
        try:
            with open(gz, "wb") as f:
                f.write(fetch(url, 120))
        except Exception:  # noqa: BLE001
            continue
        grid, valid = mrms.gunzip_read(gz, lat_w, lon_w)
        if valid != v:
            log("backfill: %s %s says valid %s; skipped" % (product, v, valid))
            continue
        return pack("mrms_bf", grid, 256, tmp, "in", 0.01), product
    log("backfill: no MRMS 1 h for %s on AWS" % v)
    return None


def put_new(rel, log):
    store.put(rel, "public, max-age=31536000, immutable", log)


def run(start, end, upload=False, log=print):
    import mrms
    tz = region.cfg().get("tz_offset_h", -8)
    lat_w, lon_w = mrms.window_latlon()
    tmp = tempfile.mkdtemp(prefix="snow_backfill_")
    try:
        day = start
        while day <= end:
            d = day.isoformat()
            names = set(store.listing("archive/%s/" % d))
            done = []
            if "snodas.json.gz" not in names:
                snap = snodas_day(day, tmp, log)
                if snap:
                    n = archive.write_gz(store.local("archive/%s/snodas.json.gz" % d), snap)
                    done.append("snodas %dK" % (n // 1024))
                    if upload:
                        put_new("archive/%s/snodas.json.gz" % d, log)
            if "mrms1h.json.gz" not in names:
                end_utc = window_end(day, tz, log)
                gaps = mrms_gaps(day, sorted(names), end_utc, log)
                hours, products = {}, {}
                for v in gaps:
                    got = mrms_hour(v, tmp, lat_w, lon_w, log)
                    if got:
                        hours[v.strftime("%Y-%m-%dT%H:%M")] = dict(got[0], product=got[1])
                        products[got[1]] = products.get(got[1], 0) + 1
                if hours:
                    obj = {"source": "noaa-mrms-pds (AWS), backfilled %s" % dt.date.today(), "window_end_utc": end_utc.strftime("%Y-%m-%dT%H:%M"),
                           "hours": hours}
                    n = archive.write_gz(store.local("archive/%s/mrms1h.json.gz" % d), obj)
                    done.append("mrms %d of %d missing hours (%s) %dK" % (len(hours), len(gaps),
                                                                        ", ".join("%s %d" % kv for kv in sorted(products.items())), n // 1024))
                    if upload:
                        put_new("archive/%s/mrms1h.json.gz" % d, log)
                else:
                    done.append("mrms complete" if not gaps else "mrms %d missing, none on AWS" % len(gaps))
            log("backfill %s: %s" % (d, ", ".join(done) or "nothing to do"))
            day += dt.timedelta(days=1)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--upload", action="store_true")
    a = ap.parse_args()
    run(dt.date.fromisoformat(a.start), dt.date.fromisoformat(a.end), a.upload)
