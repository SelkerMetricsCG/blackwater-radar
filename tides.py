"""
Tides and tidal currents for the Coastal group: NOAA CO-OPS (US) and the Canadian
Hydrographic Service IWLS API (BC), filtered to the map window.

Output: data/tides.js -> window.TIDES = {updated, updated_t, stations: [...], currents: [...]}
  stations: high/low predictions from 12 h ago to 36 h ahead (plus one extreme past each edge so the page can
            draw its curve to the edges), the last 12 h of observed water level at 30-min steps where the station
            is live, and the latest water level, water temperature and wind. Feet; MLLW (US) or chart datum (BC).
  currents: slack / max-flood / max-ebb events for today and tomorrow (local), knots, at the named passages.

State: data/tides_cache.json = {"meta": {"fetched", "stations": [...], "currents": [...]},
                                "pred": {id: {"day", "fetched", "hilo"}}, "cur": {id: {"day", "fetched", "events", ...}}}
  Metadata is refreshed every 7 days; predictions once a UTC day per station, at most PRED_LIMIT stations per run,
  oldest first, so the daily refresh is spread over the half-hour runs. buoys.py reads meta["stations"]
  (CO-OPS records carry `sensors`, a subset of "wl", "wind", "wtemp").

Times are requested in GMT and converted once to epoch seconds (never re-parsed as local).

Run standalone:  python tides.py
"""
import calendar
import datetime as dt
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

import region

DATA = region.data_dir()
OUT = os.path.join(DATA, "tides.js")
CACHE = os.path.join(DATA, "tides_cache.json")
UA = "RadarTracker/1.0 (personal weather map)"
TIMEOUT = 20
META_TIMEOUT = 60          # the CO-OPS station lists are 1-4 MB and slow (tidepredictions took 21 s in research)
TRIES = 2
SLEEP_S = 0.2              # between CO-OPS / CHS calls (CO-OPS asks for sleeps between requests)
META_MAX_AGE_S = 7 * 86400
PRED_LIMIT = 60
DEADLINE_S = 300           # stop refreshing predictions after this long; the next run continues
FT_PER_M = 3.28084
KT_PER_CMS = 0.019438
MPH_PER_KT = 1.15078

MDAPI = "https://api.tidesandcurrents.noaa.gov/mdapi/prod/webapi/stations.json"
DATAGETTER = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"
CHS = "https://api-iwls.dfo-mpo.gc.ca/api/v1"

# CO-OPS tidal-current prediction stations shown: the named passages (coastal_research/tides_currents_sst.md 1.5)
NAMED_CURRENTS = {
    "PUG1616", "PUG1617",                         # Admiralty Inlet (Bush Point)
    "PUG1623", "PUG1624", "PUG1625",              # Point Wilson
    "PUG1619", "PUG1620",                         # Marrowstone
    "PUG1701", "PUG1629",                         # Deception Pass (Narrows), Yokeko Point
    "PUG1524", "PUG1525", "PUG1526", "PUG1527", "PUG1528",   # Tacoma Narrows
    "PUG1513", "PUG1514", "ks0101",               # Rich Passage
    "PUG1501",                                    # Agate Passage
    "PUG1703",                                    # San Juan Channel
    "PUG1742", "PUG1743",                         # Cattle Point
    "PUG1718", "PUG1724",                         # Haro Strait
    "PUG1702",                                    # Rosario Strait
    "PUG1642", "PUG1640",                         # Strait of Juan de Fuca entrance, Race Rocks
    "PCT1121", "PCT1151", "PCT1171",              # Columbia River entrance: Clatsop Spit, Hammond, Chinook Point
    "PCT1291",                                    # Grays Harbor entrance
    "PCT1076", "PCT1096", "PCT1061", "PCT1066", "PCT1056", "PCT1321",   # Yaquina, Tillamook, Coos, Umpqua, Coquille, Quillayute
}

_down = set()              # hosts that timed out or refused this run


class HostDown(Exception):
    pass


# ---------- fetching ----------
def fetch(url, timeout=TIMEOUT):
    """-> bytes. Two tries; a host that times out or refuses is skipped for the rest of the run. HTTP errors
    (the host answered) are raised at once."""
    host = urllib.parse.urlsplit(url).netloc
    if host in _down:
        raise HostDown(url)
    last = None
    for _ in range(TRIES):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError:
            raise
        except OSError as e:               # URLError, timeouts, refused connections
            last = e
    _down.add(host)
    raise HostDown(url) from last


def _get(url, timeout=TIMEOUT):
    if SLEEP_S:
        time.sleep(SLEEP_S)
    return fetch(url, timeout=timeout)


def coops_url(station, product, **kw):
    q = {"station": station, "product": product, "units": "english", "time_zone": "gmt", "format": "json",
         "application": "RadarTracker"}
    if product in ("predictions", "water_level"):
        q["datum"] = "MLLW"
    q.update(kw)
    return DATAGETTER + "?" + urllib.parse.urlencode(q)


def chs_url(chs_id, code, t0, t1, **kw):
    q = {"time-series-code": code, "from": _iso(t0), "to": _iso(t1)}
    q.update(kw)
    return "%s/stations/%s/data?%s" % (CHS, chs_id, urllib.parse.urlencode(q))


def _iso(t):
    return dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------- parsing ----------
def _gmt(s):
    """CO-OPS "YYYY-MM-DD HH:MM" in time_zone=gmt -> epoch seconds"""
    return calendar.timegm(time.strptime(s.strip(), "%Y-%m-%d %H:%M"))


def _isoz(s):
    """CHS "2026-10-13T03:45:00Z" -> epoch seconds"""
    return calendar.timegm(time.strptime(s.strip().rstrip("Z")[:19], "%Y-%m-%dT%H:%M:%S"))


def _json(text):
    return json.loads(text.decode("utf-8", "replace") if isinstance(text, bytes) else text)


def _coops(text, key):
    d = _json(text)
    if isinstance(d, dict) and "error" in d:
        raise ValueError((d["error"] or {}).get("message", "CO-OPS error"))
    return d[key]


def _num(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x else None


def _in(lat, lon, bbox):
    lat0, lat1, lon0, lon1 = bbox
    return lat is not None and lon is not None and lat0 <= lat <= lat1 and lon0 <= lon <= lon1


def _sensors(rec):
    out = set()
    for s in ((rec.get("sensors") or {}).get("sensors") or []):
        if s.get("status") != 1:
            continue
        name = s.get("name") or ""
        if name.endswith("WL"):
            out.add("wl")
        elif name == "Wind":
            out.add("wind")
        elif name == "Water Temperature":
            out.add("wtemp")
    return [k for k in ("wl", "wind", "wtemp") if k in out]


def parse_coops_stations(json_text, kind, bbox):
    """CO-OPS mdapi station list (kind: waterlevels | tidepredictions | currentpredictions) -> meta records in bbox"""
    rows = _json(json_text).get("stations") or []
    out = []
    if kind == "currentpredictions":
        by = {}
        for r in rows:
            lat, lon = _num(r.get("lat")), _num(r.get("lng"))
            if r.get("type") == "W" or not _in(lat, lon, bbox):      # W: weak and variable, no predictions
                continue
            by.setdefault(r["id"], []).append(r)
        for sid, bins in by.items():
            with_depth = [b for b in bins if _num(b.get("depth")) is not None]
            b = min(with_depth, key=lambda x: _num(x["depth"])) if with_depth else bins[0]   # shallowest bin
            out.append({"id": sid, "name": b.get("name") or sid, "lat": _num(b["lat"]), "lon": _num(b["lng"]),
                        "src": "COOPS", "type": b.get("type"), "bin": b.get("currbin"),
                        "bin_depth_ft": _num(b.get("depth")),
                        "link": "https://tidesandcurrents.noaa.gov/noaacurrents/predictions?id=%s_%s" % (
                            sid, b.get("currbin"))})
        return out
    for r in rows:
        lat, lon = _num(r.get("lat")), _num(r.get("lng"))
        if not _in(lat, lon, bbox):
            continue
        rec = {"id": r["id"], "name": r.get("name") or r["id"], "lat": lat, "lon": lon, "src": "COOPS"}
        if kind == "waterlevels":
            if r.get("tidal") is False:
                continue
            rec["sensors"] = _sensors(r)
        else:
            rec["kind"] = "subordinate" if r.get("type") == "S" else "harmonic"
            if r.get("reference_id"):
                rec["reference"] = r["reference_id"]
        out.append(rec)
    return out


def parse_chs_stations(json_text, bbox):
    """CHS /stations -> (tide stations with wlp-hilo or wlo, current stations with wcp1-events), in bbox"""
    tide, cur = [], []
    for r in _json(json_text):
        lat, lon = _num(r.get("latitude")), _num(r.get("longitude"))
        if not _in(lat, lon, bbox):
            continue
        codes = {t.get("code") for t in r.get("timeSeries") or []}
        base = {"id": r.get("code") or r["id"], "chs_id": r["id"], "name": r.get("officialName") or r.get("code"),
                "lat": lat, "lon": lon, "src": "CHS",
                "link": "https://www.tides.gc.ca/en/stations/%s" % (r.get("code") or r["id"])}
        if "wcp1-events" in codes:
            cur.append(dict(base))
        if "wlp-hilo" in codes or "wlo" in codes:
            rec = dict(base, datum="CD", kind="harmonic" if "wlp-hilo" in codes else "obs",
                       live=bool(r.get("operating")) and "wlo" in codes)
            tide.append(rec)
    return tide, cur


def parse_hilo(json_text):
    """CO-OPS predictions&interval=hilo (units=english, time_zone=gmt) -> [[epoch, ft, "H"|"L"], ...]"""
    out = []
    for r in _coops(json_text, "predictions"):
        v = _num(r.get("v"))
        if v is None or r.get("type") not in ("H", "L"):
            continue
        out.append([_gmt(r["t"]), round(v, 2), r["type"]])
    return sorted(out)


def _thin(rows, hours=12, step=1800):
    """[(epoch, ft)] -> one sample per `step` mark (the first within 6 min after it) over the last `hours`"""
    if not rows:
        return []
    newest = max(t for t, _ in rows)
    best = {}
    for t, v in rows:
        if t < newest - hours * 3600:
            continue
        mark = t // step * step
        if t - mark >= 360:                # no sample within 6 min after the mark (a gap): skip this mark
            continue
        if mark not in best or t - mark < best[mark][0] - mark:
            best[mark] = (t, v)
    return [[t, round(v, 2)] for t, v in sorted(best.values())]


def _wl_rows(json_text):
    rows = []
    for r in _coops(json_text, "data"):
        v = _num(r.get("v"))
        if v is not None and r.get("t"):
            rows.append((_gmt(r["t"]), v))
    return sorted(rows)


def parse_wl(json_text):
    """CO-OPS water_level (6-min, english, gmt) -> last 12 h thinned to 30 min: [[epoch, ft], ...]"""
    return _thin(_wl_rows(json_text))


def latest_wl(json_text):
    """-> (epoch, ft) of the newest water-level row, or None"""
    rows = _wl_rows(json_text)
    return (rows[-1][0], round(rows[-1][1], 2)) if rows else None


def parse_maxslack(json_text):
    """CO-OPS currents_predictions&interval=MAX_SLACK -> [[epoch, "slack"|"flood"|"ebb", kt], ...] (speed >= 0)"""
    d = _coops(json_text, "current_predictions")
    k = KT_PER_CMS if "cm/s" in (d.get("units") or "") else 1.0
    out = []
    for r in d.get("cp") or []:
        typ = (r.get("Type") or "").lower()
        v = _num(r.get("Velocity_Major"))
        if typ not in ("slack", "flood", "ebb") or v is None:
            continue
        out.append([_gmt(r["Time"]), typ, 0.0 if typ == "slack" else round(abs(v) * k, 2)])
    return sorted(out)


def current_dirs(json_text):
    """-> (mean flood direction, mean ebb direction) in degrees true, from a MAX_SLACK table"""
    for r in _coops(json_text, "current_predictions").get("cp") or []:
        return _num(r.get("meanFloodDir")), _num(r.get("meanEbbDir"))
    return None, None


def parse_chs_hilo(json_text):
    """CHS wlp-hilo (metres above chart datum) -> [[epoch, ft, "H"|"L"], ...]; H/L from the neighbouring extremes"""
    rows = sorted((_isoz(r["eventDate"]), _num(r.get("value"))) for r in _json(json_text)
                  if r.get("eventDate") and _num(r.get("value")) is not None)
    out = []
    for i, (t, v) in enumerate(rows):
        nb = [rows[j][1] for j in (i - 1, i + 1) if 0 <= j < len(rows)]
        typ = "H" if nb and all(v > x for x in nb) else "L"
        out.append([t, round(v * FT_PER_M, 2), typ])
    return out


def parse_chs_wl(json_text):
    """CHS wlo (metres above chart datum) -> last 12 h thinned to 30 min: [[epoch, ft], ...]"""
    rows = [(_isoz(r["eventDate"]), _num(r.get("value")) * FT_PER_M) for r in _json(json_text)
            if r.get("eventDate") and _num(r.get("value")) is not None]
    return _thin(rows)


def parse_chs_events(json_text):
    """CHS wcp1-events (knots: phenomenon "wcs", unit "kn") -> [[epoch, "slack"|"flood"|"ebb", kt], ...]"""
    kinds = {"SLACK": "slack", "EXTREMA_FLOOD": "flood", "EXTREMA_EBB": "ebb"}
    out = []
    for r in _json(json_text):
        typ = kinds.get(r.get("qualifier"))
        v = _num(r.get("value"))
        if typ is None or v is None or not r.get("eventDate"):
            continue
        out.append([_isoz(r["eventDate"]), typ, 0.0 if typ == "slack" else round(abs(v), 2)])
    return sorted(out)


# ---------- cache ----------
def load_cache():
    try:
        with open(CACHE, encoding="utf-8") as f:
            c = json.load(f)
        if isinstance(c, dict):
            c.setdefault("meta", {})
            c.setdefault("pred", {})
            c.setdefault("cur", {})
            return c
    except (OSError, ValueError):
        pass
    return {"meta": {}, "pred": {}, "cur": {}}


def save_cache(cache):
    _write(CACHE, json.dumps(cache, separators=(",", ":")))


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(path + ".tmp", path)


def _day(t):
    return dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%Y-%m-%d")


def refresh_plan(cache, now, limit=PRED_LIMIT):
    """-> ids of stations whose predictions are not from today's UTC day: never-fetched first, then oldest, <= limit.
    Current stations come before tide stations of the same age."""
    today = _day(now)
    cand = []
    meta = cache.get("meta") or {}
    for i, s in enumerate(meta.get("stations") or []):
        if s.get("kind") in ("harmonic", "subordinate"):
            e = (cache.get("pred") or {}).get(s["id"])
            if not e or e.get("day") != today:
                cand.append(((e or {}).get("fetched", 0), 1, i, s["id"]))
    for i, s in enumerate(meta.get("currents") or []):
        e = (cache.get("cur") or {}).get(s["id"])
        if not e or e.get("day") != today:
            cand.append(((e or {}).get("fetched", 0), 0, i, s["id"]))
    cand.sort()                            # oldest first; on a tie the current stations (few, and asked about) first
    return [c[3] for c in cand[:limit]]


# ---------- the run ----------
def refresh_meta(cache, bbox, now, log):
    """Fetch the CO-OPS and CHS station lists; keep the cached ones if any list fails."""
    wl = parse_coops_stations(fetch(MDAPI + "?type=waterlevels&expand=sensors&units=english", META_TIMEOUT),
                              "waterlevels", bbox)
    tp = parse_coops_stations(fetch(MDAPI + "?type=tidepredictions&units=english", META_TIMEOUT),
                              "tidepredictions", bbox)
    cp = parse_coops_stations(fetch(MDAPI + "?type=currentpredictions&units=english", META_TIMEOUT),
                              "currentpredictions", bbox)
    chs_t, chs_c = parse_chs_stations(fetch(CHS + "/stations", META_TIMEOUT), bbox)
    by = {}
    for p in tp:
        by[p["id"]] = dict(p, datum="MLLW", sensors=[], live=False,
                           link="https://tidesandcurrents.noaa.gov/noaatidepredictions.html?id=%s" % p["id"])
    for w in wl:
        rec = by.setdefault(w["id"], {"kind": "obs", "datum": "MLLW"})
        rec.update(w, live="wl" in w["sensors"],
                   link="https://tidesandcurrents.noaa.gov/stationhome.html?id=%s" % w["id"])
    stations = sorted(by.values(), key=lambda s: -s["lat"]) + chs_t
    currents = [c for c in cp if c["id"] in NAMED_CURRENTS] + chs_c
    cache["meta"] = {"fetched": int(now), "stations": stations, "currents": currents}
    log("tides: metadata refreshed: %d CO-OPS (%d live), %d CHS tide, %d current stations" % (
        len(by), sum(1 for s in by.values() if s.get("live")), len(chs_t), len(currents)))


def _local_tz():
    if region.KEY == "pnw":
        try:
            import zoneinfo
            return zoneinfo.ZoneInfo("America/Los_Angeles")
        except Exception:  # noqa: BLE001  (no tz database on this machine)
            pass
    return dt.timezone(dt.timedelta(hours=region.cfg().get("tz_offset_h", 0)))


def _today_tomorrow(now):
    tz = _local_tz()
    d0 = dt.datetime.fromtimestamp(now, tz).replace(hour=0, minute=0, second=0, microsecond=0)
    d2 = (d0 + dt.timedelta(days=2, hours=3)).replace(hour=0)       # robust to a DST day of 23 or 25 h
    return d0.timestamp(), d2.timestamp()


def _clip(hilo, t0, t1):
    """extremes in [t0, t1] plus the one just before and just after, so a curve reaches both edges"""
    idx = [i for i, h in enumerate(hilo) if t0 <= h[0] <= t1]
    if not idx:
        before = [h for h in hilo if h[0] < t0][-1:]
        after = [h for h in hilo if h[0] > t1][:1]
        return before + after if before and after else []
    return hilo[max(idx[0] - 1, 0):idx[-1] + 2]


def _pred_window(now):
    """prediction request span: yesterday 00:00 UTC for 96 h, so a cache from yesterday still reaches now + 36 h"""
    t0 = int(now) // 86400 * 86400 - 86400
    return t0, t0 + 96 * 3600


def fetch_pred(rec, is_current, now):
    t0, t1 = _pred_window(now)
    begin = dt.datetime.fromtimestamp(t0, dt.timezone.utc).strftime("%Y%m%d")
    if rec["src"] == "COOPS" and not is_current:
        return {"hilo": parse_hilo(_get(coops_url(rec["id"], "predictions", interval="hilo",
                                                  begin_date=begin, range=96)))}
    if rec["src"] == "COOPS":
        text = _get(coops_url(rec["id"], "currents_predictions", interval="MAX_SLACK", bin=rec.get("bin"),
                              begin_date=begin, range=96))
        fd, ed = current_dirs(text)
        return {"events": parse_maxslack(text), "flood_dir": fd, "ebb_dir": ed}
    if is_current:
        return {"events": parse_chs_events(_get(chs_url(rec["chs_id"], "wcp1-events", t0, t1)))}
    return {"hilo": parse_chs_hilo(_get(chs_url(rec["chs_id"], "wlp-hilo", t0, t1)))}


def fetch_obs(rec, now, log, fails):
    """latest observations for a live station -> dict of the TIDES fields"""
    o = {}
    if rec["src"] == "CHS":
        try:
            o["obs"] = parse_chs_wl(_get(chs_url(rec["chs_id"], "wlo", now - 12 * 3600, now,
                                                 resolution="FIFTEEN_MINUTES"))) or None
            if o["obs"]:
                o["wl_t"], o["wl_ft"] = o["obs"][-1]
        except Exception as e:  # noqa: BLE001
            fails.append(rec["id"])
            log("tides: %s %s wlo failed: %r" % (rec["id"], rec["name"], e))
        return o
    sensors = rec.get("sensors") or []
    if "wl" in sensors:
        try:
            text = _get(coops_url(rec["id"], "water_level", range=12))
            o["obs"] = parse_wl(text) or None
            last = latest_wl(text)
            if last:
                o["wl_t"], o["wl_ft"] = last
        except Exception as e:  # noqa: BLE001
            fails.append(rec["id"])
            log("tides: %s %s water_level failed: %r" % (rec["id"], rec["name"], e))
    if "wtemp" in sensors:
        try:
            rows = _coops(_get(coops_url(rec["id"], "water_temperature", date="latest")), "data")
            v = _num(rows[-1].get("v")) if rows else None
            if v is not None and _gmt(rows[-1]["t"]) > now - 6 * 3600:
                o["wtmp_f"] = round(v, 1)
        except Exception:  # noqa: BLE001  (a sensor that is down is common; not counted as a failure)
            pass
    if "wind" in sensors:
        try:
            rows = _coops(_get(coops_url(rec["id"], "wind", date="latest")), "data")
            r = rows[-1] if rows else {}
            s, g, d = _num(r.get("s")), _num(r.get("g")), _num(r.get("d"))
            if s is not None and _gmt(r["t"]) > now - 6 * 3600:      # units=english: knots
                o["wspd_mph"] = round(s * MPH_PER_KT, 1)
                o["gust_mph"] = round(g * MPH_PER_KT, 1) if g is not None else None
                o["wdir_deg"] = d
        except Exception:  # noqa: BLE001
            pass
    return o


def build(log=print, now=None):
    if not region.cfg().get("coastal"):
        return 0
    t_start = time.time()
    now = now or time.time()
    _down.clear()
    bbox = region.bbox()
    cache = load_cache()
    meta = cache["meta"]
    if not meta.get("stations") or now - meta.get("fetched", 0) > META_MAX_AGE_S:
        try:
            refresh_meta(cache, bbox, now, log)
        except Exception as e:  # noqa: BLE001
            log("tides: metadata refresh failed (keeping the cached lists): %r" % e)
        meta = cache["meta"]
    if not meta.get("stations"):
        raise RuntimeError("no tide station metadata; keeping the last good file")

    today = _day(now)
    tide_by = {s["id"]: s for s in meta["stations"]}
    cur_by = {c["id"]: c for c in meta.get("currents") or []}
    n_ref, fails = 0, []
    jobs = []                              # (record, is_current); a CHS code can be both a tide and a current station
    for sid in dict.fromkeys(refresh_plan(cache, now, PRED_LIMIT)):
        t = tide_by.get(sid)
        if t and t.get("kind") in ("harmonic", "subordinate") and (cache["pred"].get(sid) or {}).get("day") != today:
            jobs.append((t, False))
        if sid in cur_by and (cache["cur"].get(sid) or {}).get("day") != today:
            jobs.append((cur_by[sid], True))
    for rec, is_cur in jobs:
        if time.time() - t_start > DEADLINE_S:
            break
        sid = rec["id"]
        store = cache["cur"] if is_cur else cache["pred"]
        try:
            got = fetch_pred(rec, is_cur, now)
        except HostDown as e:
            fails.append(sid)
            log("tides: %s skipped, host down: %s" % (sid, e))
            continue
        except Exception as e:  # noqa: BLE001  (an API error answer: don't ask again until tomorrow)
            fails.append(sid)
            log("tides: %s %s predictions failed: %r" % (sid, rec["name"], e))
            old = store.get(sid) or {}
            store[sid] = dict(old, day=today, fetched=int(now), err=str(e)[:200])
            continue
        store[sid] = dict(got, day=today, fetched=int(now))
        n_ref += 1

    lo, hi = now - 12 * 3600, now + 36 * 3600
    stations = []
    for s in meta["stations"]:
        p = cache["pred"].get(s["id"]) or {}
        hilo = _clip(p.get("hilo") or [], lo, hi) if s.get("kind") != "obs" else []
        o = fetch_obs(s, now, log, fails) if s.get("live") else {}
        if not hilo and not o.get("obs"):
            continue
        rec = {"id": s["id"], "name": s["name"], "lat": round(s["lat"], 4), "lon": round(s["lon"], 4),
               "src": s["src"], "kind": s.get("kind", "obs"), "datum": s.get("datum", "MLLW"), "link": s.get("link"),
               "hilo": hilo, "obs": o.get("obs")}
        for k in ("wl_ft", "wl_t", "wtmp_f", "wspd_mph", "gust_mph", "wdir_deg"):
            if o.get(k) is not None:
                rec[k] = o[k]
        stations.append(rec)

    d0, d2 = _today_tomorrow(now)
    currents = []
    for c in meta.get("currents") or []:
        e = cache["cur"].get(c["id"]) or {}
        events = [x for x in e.get("events") or [] if d0 <= x[0] < d2]
        if not events:
            continue
        currents.append({"id": c["id"], "name": c["name"], "lat": round(c["lat"], 4), "lon": round(c["lon"], 4),
                         "src": c["src"], "bin_depth_ft": c.get("bin_depth_ft"), "flood_dir": e.get("flood_dir"),
                         "ebb_dir": e.get("ebb_dir"), "link": c.get("link"), "events": events})

    out = {"updated": dt.datetime.fromtimestamp(now).strftime("%a %b %d %I:%M %p"), "updated_t": int(now),
           "stations": stations, "currents": currents}
    _write(OUT, "window.TIDES = %s;\n" % json.dumps(out, separators=(",", ":")))
    save_cache(cache)
    n_live = sum(1 for s in stations if s["obs"])
    log("tides: %d stations (%d live), %d current stations, %d predictions refreshed, %d failed" % (
        len(stations), n_live, len(currents), n_ref, len(fails)))
    return len(stations)


def missing_predictions(cache):
    """-> ids of prediction stations (tide and current) with nothing cached yet"""
    meta = cache.get("meta") or {}
    miss = [s["id"] for s in meta.get("stations") or [] if s.get("kind") in ("harmonic", "subordinate")
            and not (cache["pred"].get(s["id"]) or {}).get("hilo")]
    miss += [c["id"] for c in meta.get("currents") or [] if not (cache["cur"].get(c["id"]) or {}).get("events")]
    return miss


if __name__ == "__main__":
    t0 = time.time()
    build()
    print("tides: %d prediction stations still without predictions" % len(missing_predictions(load_cache())))
    print("done in %.0fs" % (time.time() - t0))
