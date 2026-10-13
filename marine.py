"""
NWS marine forecasts for the Coastal group: coastal-waters zones with their period text, and Surf Zone Forecasts.

Zones come from api.weather.gov /zones?type=coastal (one request per run), kept when their `cwa` is one of the
region's offices (region.cfg()["marine_cwa"]). Zone outlines share data/zone_cache.json with alerts.py, keyed by the
zone URL; the forecast text is fetched every run. Each period's max wind (gusts count) and max seas are parsed from
the text; when nothing parses they are null and the page draws the zone grey. Surf Zone Forecasts (SRF) are the
latest product per office; an office that issues none (SEW) is simply absent.
Output: data/marine.js -> window.MARINE = {updated, updated_t, zones: [...], srf: {cwa: {text, issued, link}}}

Run standalone:  python marine.py
"""
import datetime as dt
import json
import os
import re
import time
import urllib.error

import alerts
import region

API = "https://api.weather.gov"
ZONES_URL = API + "/zones?type=coastal"
DATA = region.data_dir()
OUT = os.path.join(DATA, "marine.js")
ZONES = os.path.join(DATA, "zone_cache.json")       # shared with alerts.py: {zone URL: GeoJSON geometry | None}
CWAS = ["SEW", "PQR", "MFR", "EKA"]
PERIODS = 6
SRF_CHARS = 2500
TIMEOUT = 20

_down = False


class HostDown(Exception):
    """api.weather.gov timed out or refused earlier in this run; don't wait on it again"""


def fetch(url):
    """alerts.fetch (the site's api.weather.gov User-Agent), 20 s, 2 tries; after a timeout or refused connection
    every later call in this run fails at once. HTTP errors (the host answered) don't count."""
    global _down
    if _down:
        raise HostDown(url)
    try:
        return alerts.fetch(url, timeout=TIMEOUT, tries=2)
    except urllib.error.HTTPError:
        raise
    except OSError:
        _down = True
        raise HostDown(url)


def cwas():
    return list(region.cfg().get("marine_cwa") or CWAS)


# ---------- period text ----------
_KT = re.compile(r"(less than\s+|current of\s+)?(?<![\d.])(\d+)(?:\s+to\s+(\d+))?\s*(?:kt|knots)\b", re.I)
_FT = re.compile(r"(\d+)(?:\s+to\s+(\d+))?\s*(?:ft|feet)\b", re.I)
_SEAS = re.compile(r"\b(?:seas|waves)\b([^.]*)", re.I)


def parse_period(text):
    """'W wind 15 to 25 kt. Seas 6 to 8 ft.' -> (25, 8). Wind is the largest kt figure, gusts included, ignoring
    'less than N kt' (variable or light winds give None) and bar ebb currents ('current of 5.61 kt'); seas is the
    largest ft figure in a 'Seas' or 'Waves' sentence, stopping at a swell clause. The 'Wave Detail:' heights are wave trains, not seas, and are skipped."""
    if not text:
        return None, None
    text = re.sub(r"Wave Detail:[^.]*\.?", " ", text, flags=re.I)
    wind = [int(n) for m in _KT.finditer(text) if not m.group(1) for n in m.groups()[1:] if n]
    seas = []
    for m in _SEAS.finditer(text):
        clause = re.split(r"\bswell", m.group(1), maxsplit=1, flags=re.I)[0]
        seas += [int(n) for f in _FT.finditer(clause) for n in f.groups() if n]
    return (max(wind) if wind else None), (max(seas) if seas else None)


# ---------- zones ----------
def _json(x):
    return json.loads(x) if isinstance(x, (str, bytes)) else x


def zones_for(cwas, zones_json):
    """-> [{id, name, cwa, url}] for the coastal zones whose office is in cwas, in listing order."""
    want = set(cwas)
    out = []
    for f in _json(zones_json).get("features", []):
        p = f.get("properties") or {}
        cwa = p.get("cwa") or []
        cwa = [cwa] if isinstance(cwa, str) else cwa
        hit = [c for c in cwa if c in want]
        if not hit or not p.get("id"):
            continue
        out.append({"id": p["id"], "name": p.get("name") or p["id"], "cwa": hit[0],
                    "url": p.get("@id") or f.get("id") or "%s/zones/forecast/%s" % (API, p["id"])})
    return out


def _epoch(iso):
    try:
        return int(dt.datetime.fromisoformat(iso).timestamp())
    except (TypeError, ValueError):
        return None


def _periods(forecast_json):
    p = _json(forecast_json).get("properties") or {}
    periods = []
    for x in (p.get("periods") or [])[:PERIODS]:
        text = x.get("detailedForecast") or ""
        name = x.get("name") or ""
        # bar zones (PZZ210) put the seas in a period named "General Seas" whose text has no "Seas" label
        wind, seas = parse_period("Seas " + text if re.search(r"\bseas\b", name, re.I) else text)
        periods.append({"name": name, "text": text, "wind_kt_max": wind, "seas_ft_max": seas})
    return periods, _epoch(p.get("updated"))


# ---------- surf zone forecast ----------
def latest_product(listing_json):
    """the newest product URL in a /products/types/<code>/locations/<cwa> listing, or None when it is empty"""
    graph = sorted(_json(listing_json).get("@graph") or [], key=lambda g: g.get("issuanceTime") or "", reverse=True)
    if not graph:
        return None
    g = graph[0]
    return g.get("@id") or "%s/products/%s" % (API, g["id"])


def srf_text(product_json):
    """-> (productText cut to 2,500 characters, issued epoch s)"""
    p = _json(product_json)
    text = (p.get("productText") or "").strip()
    return text[:SRF_CHARS], _epoch(p.get("issuanceTime"))


# ---------- job ----------
def _load_cache():
    try:
        with open(ZONES, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save_cache(new):
    """merge the newly fetched outlines into whatever is on disk now (alerts.py writes the same file)"""
    zones = _load_cache()
    zones.update(new)
    os.makedirs(os.path.dirname(ZONES), exist_ok=True)
    with open(ZONES + ".tmp", "w", encoding="utf-8") as f:
        json.dump(zones, f)
    os.replace(ZONES + ".tmp", ZONES)

SIMPLIFY_DEG = 0.002     # judgment call: ~200 m, below what the page can show at the zone layer's zoom; the raw outlines are 800 KB


def simplify(geom):
    """A lighter copy of a zone outline for the page (Douglas-Peucker, topology kept); the raw one stays in the cache."""
    try:
        from shapely.geometry import shape, mapping
        g = shape(geom).simplify(SIMPLIFY_DEG, preserve_topology=True)
        out = mapping(g)
        return {"type": out["type"], "coordinates": alerts._round(json.loads(json.dumps(out["coordinates"])))}
    except Exception:  # noqa: BLE001  (shapely missing or an odd shape: send the full outline)
        return {"type": geom["type"], "coordinates": alerts._round(geom["coordinates"])}


def build(log=print):
    if not region.cfg().get("coastal"):
        return 0
    offices = cwas()
    try:
        listing = fetch(ZONES_URL)
    except Exception as e:  # noqa: BLE001
        log("marine: zone list failed: %r" % e)
        return 0
    cache = _load_cache()
    new = {}
    bbox = region.bbox()
    zones, failed = [], 0
    for z in zones_for(offices, listing):
        try:
            geom = cache.get(z["url"])
            if not geom:
                geom = json.loads(fetch(z["url"])).get("geometry")
                if not geom:
                    raise ValueError("no geometry")
                new[z["url"]] = geom
            if not alerts.in_window(geom, bbox):
                continue
            periods, issued = _periods(fetch(z["url"] + "/forecast"))   # [] for PZZ110: drawn grey, linked
        except Exception as e:  # noqa: BLE001
            log("marine: %s failed: %r" % (z["id"], e))
            failed += 1
            continue
        zones.append({"id": z["id"], "name": z["name"], "cwa": z["cwa"],
                      "geometry": simplify(geom),
                      "periods": periods, "issued": issued,
                      "link": "https://forecast.weather.gov/shmrn.php?mz=%s" % z["id"].lower()})
    if new:
        _save_cache(new)
    srf = {}
    for cwa in offices:
        try:
            url = latest_product(fetch("%s/products/types/SRF/locations/%s" % (API, cwa)))
            if not url:
                continue                                   # the office issues no SRF
            text, issued = srf_text(fetch(url))
        except urllib.error.HTTPError as e:
            if e.code != 404:
                log("marine: SRF %s failed: %r" % (cwa, e))
                failed += 1
            continue
        except Exception as e:  # noqa: BLE001
            log("marine: SRF %s failed: %r" % (cwa, e))
            failed += 1
            continue
        if text:
            srf[cwa] = {"text": text, "issued": issued,
                        "link": "https://forecast.weather.gov/product.php?site=%s&issuedby=%s&product=SRF" % (cwa, cwa)}
    data = {"updated": dt.datetime.now().strftime("%a %b %d %I:%M %p"), "updated_t": int(time.time()),
            "zones": zones, "srf": srf}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT + ".tmp", "w", encoding="utf-8") as f:
        f.write("window.MARINE = %s;\n" % json.dumps(data, separators=(",", ":")))
    os.replace(OUT + ".tmp", OUT)
    log("marine: %d zones, %d surf-zone forecasts, %d failed" % (len(zones), len(srf), failed))
    return len(zones)


if __name__ == "__main__":
    build()
