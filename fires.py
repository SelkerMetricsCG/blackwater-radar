"""
Fires: agency incidents, mapped perimeters and satellite hotspots (the map's "Smoke & fires" section, phase 2).

Every 15-minute radar run, for the region in REGION:
  data/fires.js          window.FIRES = {updated, updated_t, ngfs, fires:[...], hotspots:[[lat, lon, age_h, src, frp, fire_id, unconfirmed]]}
  data/perimeters.js     window.PERIMS = GeoJSON FeatureCollection (id, name, acres, age_h per polygon)
  data/fires_cache.json  private (cloud.py STATE_FILES): ArcGIS edit stamps, the last perimeter set, the last NGFS detections

Incidents: NIFC WFIGS (US), CWFIF (Canada) joined with BC Wildfire Service by fire number. Perimeters: WFIGS and BCWS,
refetched only when the layer's edit stamp changes. Hotspots: NASA FIRMS keyless 48 h CSVs (VIIRS x3, MODIS) and NOAA
NGFS (GOES, beta; newest detection per tracked feature, 24 h). Requests reuse airquality's fetch, cache and hung-host rule.
Design: docs/superpowers/specs/2026-09-28-fires-layer-design.md; sources: smoke_research/sources_notes.md.

Run standalone (writes local files, uploads nothing):  python fires.py
"""
import csv
import datetime as dt
import io
import json
import math
import os
import re
import time
import urllib.parse

import region
from airquality import CACHE_DIR, HostDown, NotPosted, TIMEOUT, UA, _open, fetch  # noqa: F401  (shared request helpers)

WFIGS = "https://services3.arcgis.com/T4QMspbfLg3qTGWY/arcgis/rest/services/"
WFIGS_INC = WFIGS + "WFIGS_Incident_Locations_Current/FeatureServer/0"
WFIGS_PERIM = WFIGS + "WFIGS_Interagency_Perimeters_Current/FeatureServer/0"
BCWS = "https://services6.arcgis.com/ubm4tcTYICKBpist/arcgis/rest/services/"
BCWS_FIRES = BCWS + "BCWS_ActiveFires_PublicView/FeatureServer/0"
BCWS_PERIM = BCWS + "BCWS_FirePerimeters_PublicView/FeatureServer/0"
CWFIF = "https://geoserver.cwfif.nrcan.gc.ca/geoserver/wfs"
FIRMS = "https://firms.modaps.eosdis.nasa.gov/data/active_fire/"
NGFS = "https://fire.data.nesdis.noaa.gov/api/ogc/detections/collections/ngfs_schema.ngfs_features_scene_%s_conus/items"
INCIWEB = "https://inciweb.wildfire.gov/incidents/rss.xml"

HA_TO_ACRES = 2.4711
ACTIVE_H = 72               # updated within this many hours = active (judgment call, spec ledger)
HOT_H = 24                  # hotspots within this many hours count for a fire (ledger)
FIRMS_H = 48                # FIRMS files used (ledger)
NGFS_CACHE_S = 3600         # reuse cached NGFS detections this long after a failed call (ledger)
LINK_KM = 2.0               # hotspot -> nearest fire link distance (ledger)
DEADLINE_S = 150            # per region step (airquality.DEADLINE_S)
WFIGS_FIELDS = ("IncidentName,IrwinID,IncidentTypeCategory,IncidentSize,PercentContained,FireDiscoveryDateTime,"
                "ModifiedOnDateTime_dt,ContainmentDateTime,FireOutDateTime,FireBehaviorGeneral,TotalIncidentPersonnel,"
                "IncidentShortDescription,POOCounty,POOState,IncidentManagementOrganization,FireCause,IsCpxChild")
PERIM_FIELDS = "poly_IncidentName,poly_GISAcres,poly_DateCurrent,attr_IrwinID,attr_IncidentSize"
BCWS_FIELDS = ("FIRE_NUMBER,FIRE_STATUS,CURRENT_SIZE,GEOGRAPHIC_DESCRIPTION,INCIDENT_NAME,FIRE_URL,IGNITION_DATE,"
               "FIRE_CAUSE,FIRE_OF_NOTE_IND,FIRE_TYPE")
BCWS_PERIM_FIELDS = "FIRE_NUMBER,FIRE_SIZE_HECTARES,LOAD_DATE"

DATA = region.data_dir()
OUT = os.path.join(DATA, "fires.js")
OUT_PERIMS = os.path.join(DATA, "perimeters.js")
STORE = os.path.join(DATA, "fires_cache.json")


# ---------- small helpers ----------
def ms(v):
    """ArcGIS epoch milliseconds -> epoch seconds, or None"""
    try:
        return int(float(v) // 1000)
    except (TypeError, ValueError):
        return None


def iso(s):
    """'2026-09-28T08:25:00Z' (fractional seconds allowed) -> epoch seconds, or None"""
    if not s:
        return None
    try:
        return int(dt.datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=dt.timezone.utc).timestamp())
    except (TypeError, ValueError):
        return None


def irwin(s):
    """IRWIN id -> upper-case without braces, or None"""
    if not s:
        return None
    s = str(s).strip().strip("{}").upper()
    return s or None


def num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def point(f):
    g = f.get("geometry") or {}
    if g.get("type") != "Point":
        return None
    c = g.get("coordinates") or []
    if len(c) < 2 or num(c[0]) is None or num(c[1]) is None:
        return None
    return float(c[1]), float(c[0])


def _rec(**kw):
    base = dict(id=None, name="", type="WF", src="wfigs", lat=None, lon=None, acres=None, contained=None, discovered=None,
                modified=None, behaviour=None, personnel=None, desc=None, county=None, state=None, cause=None, org=None,
                stage=None, response=None, url=None, note=False, bcws=False)
    base.update(kw)
    return base


# ---------- incidents ----------
def parse_wfigs(g):
    """WFIGS Incident Locations GeoJSON -> records for WF, CX and RX incidents with a point and an IRWIN id;
    complex children (their complex carries them) and fires with FireOutDateTime are dropped."""
    out = []
    for f in g.get("features", []):
        p = f.get("properties") or {}
        pt = point(f)
        iid = irwin(p.get("IrwinID"))
        if pt is None or iid is None or p.get("IncidentTypeCategory") not in ("WF", "CX", "RX"):
            continue
        if p.get("IsCpxChild") in (1, True, "1") or p.get("FireOutDateTime"):
            continue
        cont = num(p.get("PercentContained"))
        pers = num(p.get("TotalIncidentPersonnel"))
        state = (p.get("POOState") or "").split("-")[-1] or None
        out.append(_rec(id=iid, name=(p.get("IncidentName") or "").strip(), type=p["IncidentTypeCategory"], src="wfigs",
                        lat=pt[0], lon=pt[1], acres=num(p.get("IncidentSize")), contained=None if cont is None else int(cont),
                        discovered=ms(p.get("FireDiscoveryDateTime")), modified=ms(p.get("ModifiedOnDateTime_dt")),
                        behaviour=p.get("FireBehaviorGeneral") or None, personnel=None if pers is None else int(pers),
                        desc=(p.get("IncidentShortDescription") or "").strip() or None, county=p.get("POOCounty") or None,
                        state=state, cause=p.get("FireCause") or None, org=p.get("IncidentManagementOrganization") or None))
    return out


def parse_cwfif(g):
    """CWFIF national active fires (WFS GeoJSON) -> records; hectares -> acres; bcnum for BC fires"""
    out = []
    for f in g.get("features", []):
        p = f.get("properties") or {}
        pt = point(f)
        nid = p.get("national_fire_id")
        if pt is None or not nid:
            continue
        ha = num(p.get("fire_size"))
        pc = num(p.get("percent_contained"))
        afid = str(p.get("agency_fire_id") or "")
        agency = p.get("agency_code") or None
        r = _rec(id=str(nid), name=afid, type="RX" if p.get("fire_was_prescribed") == 1 else "WF", src="cwfif",
                 lat=pt[0], lon=pt[1], acres=ha * HA_TO_ACRES if ha and ha > 0 else None,
                 contained=int(pc) if pc is not None and pc >= 0 else None, modified=iso(p.get("status_date")),
                 state=agency, stage=p.get("stage_of_control_status") or None, response=p.get("response_type") or None,
                 cause=p.get("national_fire_cause") or None)
        r["bcnum"] = afid.rsplit("-", 1)[-1] if agency == "BC" and afid else None
        out.append(r)
    return out


def parse_bcws(g):
    """BCWS active fires -> {FIRE_NUMBER: {name, status, acres, url, discovered, cause, note, lat, lon, out}}"""
    out = {}
    for f in g.get("features", []):
        p = f.get("properties") or {}
        n = p.get("FIRE_NUMBER")
        if not n:
            continue
        ha = num(p.get("CURRENT_SIZE"))
        name = (p.get("GEOGRAPHIC_DESCRIPTION") or "").strip() or ((p.get("INCIDENT_NAME") or "").strip() if p.get("INCIDENT_NAME") != n else "") or n
        pt = point(f)
        out[n] = {"name": name, "status": p.get("FIRE_STATUS") or None, "acres": ha * HA_TO_ACRES if ha and ha > 0 else None,
                  "url": p.get("FIRE_URL") or None, "discovered": ms(p.get("IGNITION_DATE")), "cause": p.get("FIRE_CAUSE") or None,
                  "note": p.get("FIRE_OF_NOTE_IND") == "Y", "lat": pt[0] if pt else None, "lon": pt[1] if pt else None,
                  "out": (p.get("FIRE_STATUS") or "") == "Out"}
    return out


def join_canada(cw, bc):
    """CWFIF records enriched from BCWS by fire number (BCWS status, size, name, link win); BCWS-only fires appended;
    fires BCWS marks Out dropped"""
    out, seen = [], set()
    for r in cw:
        b = bc.get(r.get("bcnum")) if r.get("bcnum") else None
        if b:
            seen.add(r["bcnum"])
            if b["out"]:
                continue
            r.update(name=b["name"], url=b["url"], note=b["note"], bcws=True)
            for k in ("acres", "discovered", "cause"):
                if b.get(k) is not None:
                    r[k] = b[k]
            r["status"] = b["status"]
        out.append(r)
    for n, b in bc.items():
        if n in seen or b["out"] or b["lat"] is None:
            continue
        out.append(_rec(id="BC_" + n, name=b["name"], src="bcws", lat=b["lat"], lon=b["lon"], acres=b["acres"],
                        discovered=b["discovered"], cause=b["cause"], state="BC", stage=b["status"], url=b["url"],
                        note=b["note"], bcws=True))
    return out


# ---------- hotspots ----------
def parse_firms(text, src, seen):
    """FIRMS active-fire CSV -> hotspots; rows already in `seen` (lat, lon, date, time, satellite) are skipped:
    the Canada files repeat ~90 % of their rows from the US files"""
    out = []
    for r in csv.DictReader(io.StringIO(text)):
        lat, lon, frp = num(r.get("latitude")), num(r.get("longitude")), num(r.get("frp"))
        d, tm = r.get("acq_date"), (r.get("acq_time") or "").zfill(4)
        if lat is None or lon is None or not d or len(tm) != 4:
            continue
        key = (r["latitude"], r["longitude"], d, tm, r.get("satellite"))
        if key in seen:
            continue
        seen.add(key)
        try:
            t = int(dt.datetime.strptime(d + tm, "%Y-%m-%d%H%M").replace(tzinfo=dt.timezone.utc).timestamp())
        except ValueError:
            continue
        out.append({"lat": lat, "lon": lon, "t": t, "src": src, "frp": frp, "fire": None, "unc": False, "since": None})
    return out


def parse_ngfs(g, now):
    """NGFS features -> the newest detection per feature_tracking_id within the last HOT_H hours (a feature is
    re-reported every ~5 min). fire = the known-incident IRWIN id; unc = not tied to a known incident;
    since = the first-seen time embedded in the tracking id ('ID-2026-09-28T03:31:19.000Z_0003')."""
    best = {}
    for f in g.get("features", []):
        p = f.get("properties") or {}
        pt = point(f)
        t = iso(p.get("acq_date_time"))
        tid = p.get("feature_tracking_id")
        if pt is None or t is None or not tid or t > now or now - t > HOT_H * 3600:
            continue
        if tid in best and best[tid]["t"] >= t:
            continue
        m = re.match(r"ID-(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})", tid)
        best[tid] = {"lat": pt[0], "lon": pt[1], "t": t, "src": "G", "frp": num(p.get("total_frp")),
                     "fire": irwin(p.get("known_incident_id")),
                     "unc": p.get("type_description") != "Known Wildland Fire Incident",
                     "since": iso(m.group(1) + "Z") if m else None}
    return list(best.values())


def dist_km(lat1, lon1, lat2, lon2):
    x = (lon2 - lon1) * math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot(x, lat2 - lat1) * 111.2


def _rings(geom):
    if geom.get("type") == "Polygon":
        return [geom["coordinates"]]
    if geom.get("type") == "MultiPolygon":
        return geom["coordinates"]
    return []


def _in_ring(lat, lon, ring):
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi, xj, yj = ring[i][0], ring[i][1], ring[j][0], ring[j][1]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def point_in_geom(lat, lon, geom):
    """point in a GeoJSON Polygon or MultiPolygon, holes respected"""
    return any(_in_ring(lat, lon, poly[0]) and not any(_in_ring(lat, lon, h) for h in poly[1:]) for poly in _rings(geom))


def geom_bbox(geom):
    xs = [c[0] for poly in _rings(geom) for c in poly[0]]
    ys = [c[1] for poly in _rings(geom) for c in poly[0]]
    return (min(ys), max(ys), min(xs), max(xs)) if xs else None


def link_hotspots(hs, fire_list, perims, now):
    """set hotspot['fire']: the known-incident id when it is in fire_list, else the nearest fire within LINK_KM, else the
    perimeter containing the point; then fire['hot24'] = linked hotspots in the last HOT_H hours"""
    ids = {f["id"] for f in fire_list}
    boxes = [(geom_bbox(p["geometry"]), p) for p in perims if p.get("geometry")]
    for h in hs:
        if h.get("fire") and h["fire"] in ids:
            continue
        h["fire"] = None
        best, bd = None, LINK_KM
        for f in fire_list:
            d = dist_km(h["lat"], h["lon"], f["lat"], f["lon"])
            if d <= bd:
                best, bd = f["id"], d
        if best is None:
            for b, p in boxes:
                if b and b[0] <= h["lat"] <= b[1] and b[2] <= h["lon"] <= b[3] and point_in_geom(h["lat"], h["lon"], p["geometry"]):
                    best = p["properties"]["id"]
                    break
        h["fire"] = best
    counts = {}
    for h in hs:
        if h["fire"] and now - h["t"] <= HOT_H * 3600:
            counts[h["fire"]] = counts.get(h["fire"], 0) + 1
    for f in fire_list:
        f["hot24"] = counts.get(f["id"], 0)


def hotspot_rows(hs, now):
    """FIRES.hotspots rows: [lat, lon, age_h, src, frp, fire_id, unconfirmed, since]"""
    return [[round(h["lat"], 4), round(h["lon"], 4), round(max(0, now - h["t"]) / 3600, 1), h["src"],
             None if h["frp"] is None else round(h["frp"], 1), h["fire"], 1 if h["unc"] else 0, h["since"]] for h in hs]


# ---------- ArcGIS, perimeters, links, store ----------
def arcgis_query(layer, params, log=print):
    """<layer>/query as GeoJSON, paged with resultOffset while exceededTransferLimit is set (WFIGS caps at 2000)"""
    p = dict(params)
    p.setdefault("f", "geojson")
    p.setdefault("returnGeometry", "true")
    p.setdefault("outSR", "4326")
    feats, off = [], 0
    while True:
        if off:
            p["resultOffset"] = off
        body, _ = fetch(layer + "/query?" + urllib.parse.urlencode(p))
        g = json.loads(body)
        if "error" in g:
            raise RuntimeError("ArcGIS error %s" % g["error"])
        feats.extend(g.get("features", []))
        if not g.get("exceededTransferLimit") or not g.get("features"):
            break
        off += len(g["features"])
        if off > 20000:
            log("fires: %s: stopped paging at %d" % (layer.rsplit("/", 3)[1], off))
            break
    return {"type": "FeatureCollection", "features": feats}


def layer_stamp(layer):
    """the layer's data edit stamp (epoch ms), from its 8 KB metadata; None when absent"""
    body, _ = fetch(layer + "?f=pjson")
    return (json.loads(body).get("editingInfo") or {}).get("dataLastEditDate")


def bbox_touches(b, bbox):
    """b and bbox are (lat0, lat1, lon0, lon1)"""
    return b is not None and b[1] >= bbox[0] and b[0] <= bbox[1] and b[3] >= bbox[2] and b[2] <= bbox[3]


def _round_coords(c):
    if isinstance(c[0], (int, float)):
        return [round(c[0], 4), round(c[1], 4)]
    return [_round_coords(x) for x in c]


def parse_perims(wfigs_g, bcws_g, bc_ids, bbox):
    """WFIGS + BCWS perimeter GeoJSON -> Features {id, name, acres, t} whose bounding box touches the window.
    A polygon without a matching incident keeps its own name (and id None when it has no IRWIN id)."""
    out = []
    for f in wfigs_g.get("features", []):
        p, g = f.get("properties") or {}, f.get("geometry")
        if not g or not bbox_touches(geom_bbox(g), bbox):
            continue
        acres = num(p.get("poly_GISAcres"))
        out.append({"type": "Feature", "properties": {"id": irwin(p.get("attr_IrwinID")), "name": (p.get("poly_IncidentName") or "").strip(),
                    "acres": acres, "t": ms(p.get("poly_DateCurrent"))}, "geometry": {"type": g["type"], "coordinates": _round_coords(g["coordinates"])}})
    for f in bcws_g.get("features", []):
        p, g = f.get("properties") or {}, f.get("geometry")
        n = p.get("FIRE_NUMBER")
        if not g or not n or not bbox_touches(geom_bbox(g), bbox):
            continue
        ha = num(p.get("FIRE_SIZE_HECTARES"))
        out.append({"type": "Feature", "properties": {"id": bc_ids.get(n, "BC_" + n), "name": n, "acres": ha * HA_TO_ACRES if ha else None,
                    "t": ms(p.get("LOAD_DATE"))}, "geometry": {"type": g["type"], "coordinates": _round_coords(g["coordinates"])}})
    return out


STATE_NAMES = {"AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California", "CO": "Colorado", "CT": "Connecticut",
               "DE": "Delaware", "DC": "District of Columbia", "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois",
               "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
               "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri", "MT": "Montana",
               "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
               "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania",
               "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah",
               "VT": "Vermont", "VA": "Virginia", "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming"}


def norm_name(s):
    """lower-case letters only, with the words fire, complex and rx removed (judgment call, spec ledger)"""
    words = [w for w in re.findall(r"[a-z]+", (s or "").lower()) if w not in ("fire", "complex", "rx")]
    return "".join(words)


def inciweb_links(rss_text):
    """InciWeb RSS -> {(norm_name, state name lower): https link}; the title's leading unit code (e.g. CAYNP) is dropped"""
    out = {}
    for item in re.findall(r"<item>(.*?)</item>", rss_text, re.S):
        t = re.search(r"<title>(.*?)</title>", item, re.S)
        l = re.search(r"<link>(.*?)</link>", item, re.S)
        s = re.search(r"State:\s*([A-Za-z ]+?)\s*---", item)
        if not (t and l and s):
            continue
        title = t.group(1).strip()
        parts = title.split(None, 1)
        if len(parts) == 2 and re.fullmatch(r"[A-Z0-9]{4,}", parts[0]):
            title = parts[1]
        out[(norm_name(title), s.group(1).strip().lower())] = l.group(1).strip().replace("http://", "https://", 1)
    return out


def load_store():
    try:
        with open(STORE, encoding="utf-8") as f:
            s = json.load(f)
        if isinstance(s, dict) and s.get("v") == 1:
            return s
    except (OSError, ValueError):
        pass
    return {"v": 1}


def _write(path, text):
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(path + ".tmp", path)


def save_store(store):
    os.makedirs(DATA, exist_ok=True)
    _write(STORE, json.dumps(store, separators=(",", ":")))
