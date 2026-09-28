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
