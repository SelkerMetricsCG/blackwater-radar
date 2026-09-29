"""
Public observations (citizen and professional field reports) from the National Avalanche Center's
observation API, the one the centers' own observation pages read. It answers only to requests whose
Origin header is on NAC's allow list (a bare 401 otherwise), so this runs only when NWAC/NAC has given
us an origin to use: environment variable NAC_OBS_ORIGIN (an Actions secret once granted). No origin,
nothing is fetched. Never send an origin that was not given to us.

Saved raw, one file per page, into the day's archive folder: obs/<kind>_p<N>.json, for the last
OBS_DAYS days (late submissions are common). The endpoint paths and query parameters below are from
NWAC's own site code (NWACus/web issues 1218 and 1337) and are unverified until access is granted;
check them then with:  NAC_OBS_ORIGIN=... python -m snow.observations
"""
import datetime as dt
import json
import os
import urllib.parse
import urllib.request

UA = "RadarTracker/1.0 (personal weather map; chris.gabrielli@gmail.com)"
BASE = "https://api.avalanche.org/obs/v1/public/"
KINDS = ("observation", "avalanche_observation")
OBS_DAYS = 3
PAGE_SIZE = 100
MAX_PAGES = 20


def origin():
    return os.environ.get("NAC_OBS_ORIGIN", "").strip()


def center():
    import region
    return region.cfg().get("avy") or "NWAC"


def fetch_page(kind, start, end, page, timeout=60):
    q = urllib.parse.urlencode({"center_id": center(), "start_date": start, "end_date": end, "page_size": PAGE_SIZE, "page": page})
    req = urllib.request.Request(BASE + "%s/list/?%s" % (kind, q), headers={"User-Agent": UA, "Accept": "application/json", "Origin": origin()})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def build(day_dir, log=print):
    if not origin():
        log("observations: skipped (no NAC_OBS_ORIGIN; access is by agreement with NWAC/NAC)")
        return 0
    today = dt.date.today()
    start, end = (today - dt.timedelta(days=OBS_DAYS)).isoformat(), today.isoformat()
    n = 0
    for kind in KINDS:
        for page in range(1, MAX_PAGES + 1):
            try:
                data = fetch_page(kind, start, end, page)
            except Exception as e:  # noqa: BLE001
                log("observations: %s page %d failed: %r" % (kind, page, e))
                break
            path = os.path.join(day_dir, "obs", "%s_p%d.json" % (kind, page))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path + ".tmp", "w", encoding="utf-8") as f:
                json.dump(data, f, separators=(",", ":"))
            os.replace(path + ".tmp", path)
            n += 1
            if not (isinstance(data, dict) and data.get("next_url")):
                break
    log("observations: %d pages for %s..%s" % (n, start, end))
    return n


if __name__ == "__main__":
    import region
    build(os.path.join(region.region_dir(), "snow", "archive", dt.date.today().isoformat()))
