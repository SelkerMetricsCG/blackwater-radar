# Fires Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A new "Smoke & fires" panel section on radar.blackwaterlabs.org with agency fire incidents (US WFIGS, Canada CWFIF + BC Wildfire Service), mapped perimeters and satellite hotspots (NASA FIRMS, NOAA NGFS).

**Architecture:** One new job module, `fires.py`, runs in the 15-minute radar job for each region after `airquality`. It writes `data/fires.js` (`window.FIRES`, incidents + hotspots) every run, `data/perimeters.js` (`window.PERIMS`, GeoJSON) from a private state file that is refreshed only when the ArcGIS layers' edit stamps change, and keeps `data/fires_cache.json` in R2 state. `map.html` gets a new panel group with two layers, cards, in-view labels and a click-anywhere block, following the air-quality patterns.

**Tech Stack:** Python 3 standard library only at module level (csv, json, math, urllib, datetime), reusing `airquality.fetch` / `_open` / `CACHE_DIR`; matplotlib for the check figure; Leaflet 1.x in `map.html`; pytest; node for the `// BEGIN…END` block tests.

**Spec:** `docs/superpowers/specs/2026-09-28-fires-layer-design.md` (read it first; decisions 1–7 and the parameter ledger are binding). Sources and endpoints: `smoke_research/sources_notes.md`; the 2026-09-28 re-check figures are in the spec.

## Global Constraints

- Work in the worktree `C:\Users\16035\Desktop\BlackwaterLabs\radar-fires` (branch `fires`, from `a3735af`). Tests: `python -m pytest tests/ -v` from that folder with `C:\Users\16035\anaconda3\python.exe`; set `PYTHONIOENCODING=utf-8`. Stage only the files a task names (never `git add -A`).
- The worktree has no `web/` (gitignored; the icons and Leaflet live only in `..\radar\web`). Before Task 5's preview and Task 8's local check, copy it: `Copy-Item ..\radar\web .\web -Recurse` (gitignored, so it never commits).
- Every web request uses the plain Chrome User-Agent (`airquality.UA`) and a 30 s timeout (`airquality.TIMEOUT`). Never put Chris's email, name or other personal data in any request. Free tier, no keys, no sign-ups.
- Endpoints (only these): `services3.arcgis.com/T4QMspbfLg3qTGWY` (WFIGS), `geoserver.cwfif.nrcan.gc.ca`, `services6.arcgis.com/ubm4tcTYICKBpist` (BCWS), `firms.modaps.eosdis.nasa.gov`, `fire.data.nesdis.noaa.gov`, `inciweb.wildfire.gov`.
- CI installs only `pytest` and `pyyaml`. `fires.py` imports only the standard library, `region` and `airquality` at module level.
- Never print, open or grep `*.env`. Never run `capture.capture_all()` or `cloud.py` locally (they upload to the live bucket). Call `fires.build()` directly.
- Units: acres everywhere in output (hectares × 2.4711 in the job). Times in output are epoch seconds UTC; ages in hours with one decimal.
- Ledger values (spec): active = updated ≤ 72 h or ≥ 1 linked hotspot ≤ 24 h or Canadian stage OC/BH, and a 100 %-contained fire is quiet unless it has hotspots; FIRMS 48 h, NGFS 24 h, NGFS cache 1 h; hotspot link 2 km then containing perimeter; age chips < 6 / 6–24 / 24–48 h; marker size steps < 100 / 100–9,999 / ≥ 10,000 acres; quiet style 45 % opacity; labels from zoom 8; colours wildfire `#d1462f`, prescribed `#8a8f98`, perimeter `#c0392b` fill 0.12; click-anywhere fire ≤ 50 km, hotspots ≤ 10 km in 24 h; budget 150 s.
- Card footers: "Source: NIFC (WFIGS)" for US fires; "Source: CWFIF (Natural Resources Canada)" plus ", BC Wildfire Service" when BCWS data was joined.
- Commit messages end with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`. Chris runs `git push` and `npx --yes wrangler deploy` himself from Run-button blocks (root `CLAUDE.md`, "Commands for Chris to run").
- **Task 5 is a gate:** stop after it and show Chris the accounting line, the figure and the independent checks. Map work (Tasks 6–8) starts only after he says go.

## Review Focus

1. **A WFIGS record without geometry or with a null size** (new starts are often entered before a point is placed; `IncidentSize` is null for hours) must be kept when it has a point and shown with "size not reported", never crash or be silently dropped for a null number. Pinned in Task 1 (`test_wfigs_null_size_and_missing_geometry`).
2. **CWFIF and BCWS disagreeing on the same fire** (BCWS says Out, CWFIF still lists it; or sizes differ) must yield one record, BCWS status and size winning where present, and the fire dropped when BCWS says Out. Pinned in Task 1 (`test_join_canada_bcws_wins_and_out_drops`).
3. **NGFS returning a tracked feature whose newest detection is older than 24 h** (the feature list covers the query range, but a feature's last detection can precede it when the API pads) must not appear with a negative or > 24 h age. Pinned in Task 2 (`test_ngfs_ages_clamped_to_window`).
4. **A perimeter whose incident is not in the window or not in WFIGS** (a fire just outside the box with a polygon reaching in; an orphan polygon) must still draw when its bounding box touches the window, with the polygon's own name, and `perim` on a fire must be true only when a polygon carries that fire's id. Pinned in Task 3 (`test_orphan_perimeter_kept_by_bbox`).
5. **Fire names and descriptions containing HTML** (`<`, `&`, quotes; agency descriptions are free text) must show as text in cards, labels and the click panel. Pinned in Task 6 (`test_fire_escape`).

---

### Task 1: Incident parsing and the Canada join

**Files:**
- Create: `fires.py`
- Test: `tests/test_fires.py`

**Interfaces:**
- Produces:
  - `fires.parse_wfigs(g: dict) -> list[dict]`: one record per WF/CX/RX incident with a point, complex children and out fires dropped. Record keys: `id` (IRWIN id, braces stripped, upper), `name`, `type` ("WF"/"CX"/"RX"), `src` ("wfigs"), `lat`, `lon`, `acres` (float or None), `contained` (int or None), `discovered`, `modified` (epoch s or None), `behaviour`, `personnel`, `desc`, `county`, `state` ("OR" from "US-OR"), `cause`, `org` (`IncidentManagementOrganization`, e.g. "Type 4 IC"), `stage` (None), `response` (None), `url` (None), `note` (False), `bcws` (False).
  - `fires.parse_cwfif(g: dict) -> list[dict]`: same keys; `id` = `national_fire_id`, `src` "cwfif", `name` = `agency_fire_id`, `state` = `agency_code` (BC, AB, …), `stage` = `stage_of_control_status`, `response`, `type` "RX" when `fire_was_prescribed == 1` else "WF", `acres` from hectares, `contained` when ≥ 0, `modified` from `status_date`, plus `bcnum` (the BCWS fire number, `agency_fire_id` after the last `-`, for BC only).
  - `fires.parse_bcws(g: dict) -> dict[str, dict]`: keyed by `FIRE_NUMBER`: `{name, status, acres, url, discovered, cause, note, lat, lon, out}`.
  - `fires.join_canada(cw: list, bc: dict) -> list[dict]`: CWFIF records enriched from BCWS by `bcnum`; BCWS-only fires appended with `id` `"BC_" + number`, `src` "bcws"; fires BCWS marks Out dropped; every BC record gets `bcws: True` when joined.
  - `fires.HA_TO_ACRES = 2.4711`, `fires.ms(v) -> int | None` (ArcGIS epoch ms → s), `fires.iso(s) -> int | None` (`2026-09-28T08:25:00Z` → s), `fires.irwin(s) -> str | None`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_fires.py`:

```python
"""Fires layer (fires.py): WFIGS, CWFIF, BCWS incidents; hotspots; perimeters; activity; FIRES (no network)."""
import datetime as dt
import json
import urllib.parse

import pytest

import fires

BBOX = (43.0, 52.5, -126.6, -112.5)          # the pnw window, rounded
NOW = int(dt.datetime(2026, 9, 28, 13, tzinfo=dt.timezone.utc).timestamp())
H = 3600


def wf(name, lat, lon, irwin="{B8431C26-6A9B-4EF0-88D8-F7EA9A3F56C3}", typ="WF", size=373927, cont=99, cpx=0, out=None,
       modified=NOW - 2 * H, discovered=NOW - 30 * 24 * H, geom=True):
    p = {"IncidentName": name, "IrwinID": irwin, "IncidentTypeCategory": typ, "IncidentSize": size, "PercentContained": cont,
         "IsCpxChild": cpx, "FireOutDateTime": None if out is None else out * 1000, "ModifiedOnDateTime_dt": modified * 1000,
         "FireDiscoveryDateTime": discovered * 1000, "ContainmentDateTime": None, "FireBehaviorGeneral": "Minimal",
         "TotalIncidentPersonnel": 120, "IncidentShortDescription": "Rowe Creek <b>Complex</b> & others", "POOCounty": "Wheeler",
         "POOState": "US-OR", "IncidentManagementOrganization": "Type 4 IC", "FireCause": "Natural"}
    return {"type": "Feature", "properties": p, "geometry": {"type": "Point", "coordinates": [lon, lat]} if geom else None}


def fc(feats):
    return {"type": "FeatureCollection", "features": feats}


def cw(nid="2026_BC_2026-V12186", agency="BC", afid="2026-V12186", ha=8.4, soc="UC", resp="FUL", pc=-1, rx=0,
       status="2026-09-28T08:25:00Z", lat=49.1, lon=-121.8):
    p = {"national_fire_id": nid, "agency_code": agency, "agency_fire_id": afid, "fire_size": ha, "stage_of_control_status": soc,
         "response_type": resp, "percent_contained": pc, "fire_was_prescribed": rx, "status_date": status, "national_fire_cause": "U"}
    return {"type": "Feature", "properties": p, "geometry": {"type": "Point", "coordinates": [lon, lat]}}


def bc(num="V12186", status="Under Control", ha=12.0, desc="Chilliwack River", name=None, note="N", ign=NOW - 20 * 24 * H, lat=49.1, lon=-121.8):
    p = {"FIRE_NUMBER": num, "FIRE_STATUS": status, "CURRENT_SIZE": ha, "GEOGRAPHIC_DESCRIPTION": desc, "INCIDENT_NAME": name or num,
         "FIRE_URL": "https://wildfiresituation.nrs.gov.bc.ca/incidents?fireYear=2026&incidentNumber=" + num,
         "IGNITION_DATE": ign * 1000, "FIRE_CAUSE": "Person", "FIRE_OF_NOTE_IND": note, "FIRE_TYPE": "Fire"}
    return {"type": "Feature", "properties": p, "geometry": {"type": "Point", "coordinates": [lon, lat]}}


# ---------- helpers ----------
def test_time_and_id_helpers():
    assert fires.ms(1790601765537) == 1790601765 and fires.ms(None) is None and fires.ms("x") is None
    assert fires.iso("2026-09-28T08:25:00Z") == NOW - 4 * H - 35 * 60 and fires.iso(None) is None and fires.iso("bad") is None
    assert fires.irwin("{b8431c26-6a9b-4ef0-88d8-f7ea9a3f56c3}") == "B8431C26-6A9B-4EF0-88D8-F7EA9A3F56C3"
    assert fires.irwin("") is None and fires.irwin(None) is None


# ---------- WFIGS ----------
def test_parse_wfigs_keeps_wf_cx_rx_drops_children_and_out():
    g = fc([wf("ROWE CREEK COMPLEX", 44.9, -120.1, typ="CX"),
            wf("CHILD", 44.9, -120.2, irwin="{1}", cpx=1),
            wf("OUT", 44.8, -120.3, irwin="{2}", out=NOW - H),
            wf("GALENA RX", 46.1, -115.0, irwin="{3}", typ="RX", size=40, cont=None),
            wf("NOT A FIRE", 44.7, -120.4, irwin="{4}", typ="OT")])
    recs = fires.parse_wfigs(g)
    assert [r["name"] for r in recs] == ["ROWE CREEK COMPLEX", "GALENA RX"]
    r = recs[0]
    assert (r["id"], r["type"], r["src"], r["lat"], r["lon"]) == ("B8431C26-6A9B-4EF0-88D8-F7EA9A3F56C3", "CX", "wfigs", 44.9, -120.1)
    assert (r["acres"], r["contained"], r["state"], r["county"], r["personnel"]) == (373927.0, 99, "OR", "Wheeler", 120)
    assert r["modified"] == NOW - 2 * H and r["discovered"] == NOW - 30 * 24 * H and r["behaviour"] == "Minimal"
    assert r["desc"].startswith("Rowe Creek") and r["cause"] == "Natural" and r["org"] == "Type 4 IC"
    assert recs[1]["type"] == "RX" and recs[1]["contained"] is None and recs[1]["url"] is None


def test_wfigs_null_size_and_missing_geometry():
    g = fc([wf("NEW START", 47.0, -120.0, irwin="{5}", size=None, cont=None),
            wf("NO POINT", 47.0, -120.0, irwin="{6}", geom=False),
            wf("NO IRWIN", 47.1, -120.0, irwin=None)])
    recs = fires.parse_wfigs(g)
    assert [r["name"] for r in recs] == ["NEW START"]      # no point or no id: dropped; null size: kept
    assert recs[0]["acres"] is None and recs[0]["contained"] is None


# ---------- CWFIF and BCWS ----------
def test_parse_cwfif_units_stage_and_prescribed():
    recs = fires.parse_cwfif(fc([cw(), cw(nid="2026_QC_1", agency="QC", afid="1", ha=0, pc=60, rx=1, soc="OC", lat=48, lon=-71)]))
    a, b = recs
    assert (a["id"], a["src"], a["name"], a["state"], a["bcnum"], a["stage"], a["response"]) == ("2026_BC_2026-V12186", "cwfif", "2026-V12186", "BC", "V12186", "UC", "FUL")
    assert a["acres"] == pytest.approx(8.4 * 2.4711) and a["contained"] is None and a["modified"] == fires.iso("2026-09-28T08:25:00Z")
    assert (b["type"], b["acres"], b["contained"], b["bcnum"]) == ("RX", None, 60, None)


def test_parse_bcws_keyed_by_number():
    d = fires.parse_bcws(fc([bc(), bc(num="K42287", status="Out", desc=None, name="Big Bar")]))
    assert d["V12186"]["name"] == "Chilliwack River" and d["V12186"]["acres"] == pytest.approx(12 * 2.4711)
    assert d["V12186"]["url"].endswith("V12186") and d["V12186"]["out"] is False and d["V12186"]["discovered"] == NOW - 20 * 24 * H
    assert d["K42287"]["name"] == "Big Bar" and d["K42287"]["out"] is True


def test_join_canada_bcws_wins_and_out_drops():
    cwl = fires.parse_cwfif(fc([cw(), cw(nid="2026_BC_2026-K42287", afid="2026-K42287", lat=51, lon=-122), cw(nid="2026_QC_1", agency="QC", afid="1", lat=48, lon=-71)]))
    bcd = fires.parse_bcws(fc([bc(), bc(num="K42287", status="Out"), bc(num="G12290", status="Being Held", desc="Fraser Canyon", note="Y", lat=50, lon=-121.5)]))
    out = fires.join_canada(cwl, bcd)
    ids = [r["id"] for r in out]
    assert ids == ["2026_BC_2026-V12186", "2026_QC_1", "BC_G12290"]       # K42287 dropped: BCWS says Out
    v = out[0]
    assert v["name"] == "Chilliwack River" and v["acres"] == pytest.approx(12 * 2.4711) and v["url"].endswith("V12186")
    assert v["bcws"] is True and v["stage"] == "UC" and v["discovered"] == NOW - 20 * 24 * H and v["cause"] == "Person"
    assert out[1]["bcws"] is False and out[1]["url"] is None
    g = out[2]
    assert (g["src"], g["name"], g["note"], g["stage"], g["lat"], g["state"]) == ("bcws", "Fraser Canyon", True, "Being Held", 50, "BC")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_fires.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'fires'`.

- [ ] **Step 3: Write `fires.py` with the helpers and parsers**

Create `fires.py`:

```python
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
                 lat=pt[0], lon=pt[1], acres=round(ha * HA_TO_ACRES, 1) if ha and ha > 0 else None,
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
        out[n] = {"name": name, "status": p.get("FIRE_STATUS") or None, "acres": round(ha * HA_TO_ACRES, 1) if ha and ha > 0 else None,
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_fires.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add fires.py tests/test_fires.py
git commit -m "fires: WFIGS, CWFIF and BCWS incident parsing; Canada join by fire number

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: Hotspots: FIRMS CSVs, NGFS tracked features, linking to fires

**Files:**
- Modify: `fires.py` (append)
- Test: `tests/test_fires.py` (append)

**Interfaces:**
- Consumes: fire records from Task 1 (`id`, `lat`, `lon`).
- Produces:
  - `fires.parse_firms(text: str, src: str, seen: set) -> list[dict]`: hotspot dicts `{lat, lon, t, src, frp, fire, unc, since}` (`t` epoch s; `src` "V" or "M"; `fire` None; `unc` False; `since` None), duplicates (same lat, lon, date, time, satellite) skipped via `seen`.
  - `fires.parse_ngfs(g: dict, now: int) -> list[dict]`: newest detection per `feature_tracking_id`, `src` "G", `fire` = known-incident IRWIN id or None, `unc` True unless `type_description == "Known Wildland Fire Incident"`, `since` = the id's embedded time; detections older than `HOT_H` or in the future dropped.
  - `fires.dist_km(lat1, lon1, lat2, lon2) -> float` (equirectangular).
  - `fires.link_hotspots(hs: list, fire_list: list, perims: list, now: int) -> None`: sets `fire` on each hotspot (known id if in `fire_list`, else nearest fire ≤ `LINK_KM`, else containing perimeter id) and `hot24` on each fire.
  - `fires.point_in_geom(lat, lon, geom: dict) -> bool` (Polygon / MultiPolygon, holes respected).
  - `fires.hotspot_rows(hs, now) -> list[list]`: `[lat, lon, age_h, src, frp, fire, unc]` rows for `FIRES.hotspots`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_fires.py`:

```python
# ---------- hotspots ----------
FIRMS_HDR = "latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,satellite,confidence,version,bright_ti5,frp,daynight"


def firms_row(lat, lon, t, sat="N20", frp="5.3"):
    d = dt.datetime.fromtimestamp(t, dt.timezone.utc)
    return "%s,%s,330.1,0.4,0.4,%s,%s,%s,nominal,2.0NRT,290.0,%s,N" % (lat, lon, d.strftime("%Y-%m-%d"), d.strftime("%H%M"), sat, frp)


def test_parse_firms_dedupes_across_files():
    seen = set()
    us = "\n".join([FIRMS_HDR, firms_row(47.5, -120.5, NOW - 2 * H), firms_row(49.5, -121.0, NOW - 3 * H)]) + "\n"
    ca = "\n".join([FIRMS_HDR, firms_row(49.5, -121.0, NOW - 3 * H), firms_row(50.5, -121.5, NOW - 3 * H, sat="N21")]) + "\n"
    a = fires.parse_firms(us, "V", seen)
    b = fires.parse_firms(ca, "V", seen)
    assert [(h["lat"], h["t"]) for h in a] == [(47.5, NOW - 2 * H), (49.5, NOW - 3 * H)]
    assert [(h["lat"], h["src"], h["frp"], h["fire"], h["unc"]) for h in b] == [(50.5, "V", 5.3, None, False)]
    assert fires.parse_firms("latitude,longitude\n47,-120\n", "M", set()) == []          # short rows skipped


def ngfs_feat(tid, t, lat=47.5, lon=-120.5, known=None, typ="Known Wildland Fire Incident", frp=7.6):
    p = {"feature_tracking_id": tid, "acq_date_time": dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000000Z"),
         "known_incident_id": known, "known_incident_name": "GALENA RX" if known else None, "type_description": typ,
         "total_frp": frp, "satellite": "GOES-18", "confidence": "nominal"}
    return {"type": "Feature", "properties": p, "geometry": {"type": "Point", "coordinates": [lon, lat]}}


def test_parse_ngfs_newest_per_feature_with_link_and_first_seen():
    tid = "ID-2026-09-28T03:31:19.000Z_0003"
    g = fc([ngfs_feat(tid, NOW - 4 * H, known="{4BE3544A-2980-49D2-BB63-10B7E731F7BA}"),
            ngfs_feat(tid, NOW - 10 * 60, known="{4BE3544A-2980-49D2-BB63-10B7E731F7BA}", lat=47.51),
            ngfs_feat("ID-2026-09-28T08:26:19.000Z_0001", NOW - 5 * H, lat=49.2, lon=-118.8, typ="Possible Wildland Fire")])
    hs = fires.parse_ngfs(g, NOW)
    assert len(hs) == 2
    a = next(h for h in hs if h["fire"])
    assert (a["lat"], a["t"], a["src"], a["fire"], a["unc"], a["frp"]) == (47.51, NOW - 10 * 60, "G", "4BE3544A-2980-49D2-BB63-10B7E731F7BA", False, 7.6)
    assert a["since"] == fires.iso("2026-09-28T03:31:19Z")
    b = next(h for h in hs if not h["fire"])
    assert b["unc"] is True and b["since"] == fires.iso("2026-09-28T08:26:19Z")


def test_ngfs_ages_clamped_to_window():
    g = fc([ngfs_feat("ID-2026-09-26T01:00:00.000Z_0001", NOW - 30 * H), ngfs_feat("ID-2026-09-28T12:00:00.000Z_0002", NOW + 600),
            ngfs_feat("ID-2026-09-28T12:00:00.000Z_0003", NOW - H)])
    assert [h["t"] for h in fires.parse_ngfs(g, NOW)] == [NOW - H]


def test_point_in_geom_with_hole_and_multipolygon():
    sq = [[[-121, 47], [-120, 47], [-120, 48], [-121, 48], [-121, 47]]]
    hole = [[[-120.7, 47.3], [-120.3, 47.3], [-120.3, 47.7], [-120.7, 47.7], [-120.7, 47.3]]]
    assert fires.point_in_geom(47.1, -120.9, {"type": "Polygon", "coordinates": sq})
    assert not fires.point_in_geom(47.5, -120.5, {"type": "Polygon", "coordinates": sq + hole})
    assert fires.point_in_geom(47.5, -120.5, {"type": "MultiPolygon", "coordinates": [sq, [[[-119, 45], [-118, 45], [-118, 46], [-119, 46], [-119, 45]]]]})
    assert not fires.point_in_geom(50, -120.5, {"type": "Polygon", "coordinates": sq})


def test_link_hotspots_by_id_distance_then_perimeter_and_hot24():
    fl = [dict(id="A", lat=47.5, lon=-120.5), dict(id="B", lat=49.0, lon=-119.0)]
    perims = [{"type": "Feature", "properties": {"id": "B", "name": "B", "acres": 100, "t": NOW},
               "geometry": {"type": "Polygon", "coordinates": [[[-119.2, 48.8], [-118.8, 48.8], [-118.8, 49.2], [-119.2, 49.2], [-119.2, 48.8]]]}}]
    hs = [dict(lat=46.0, lon=-118.0, t=NOW - H, src="G", frp=1, fire="A", unc=False, since=None),        # known id wins over distance
          dict(lat=47.51, lon=-120.51, t=NOW - 30 * H, src="V", frp=1, fire=None, unc=False, since=None),   # 1.3 km from A, but 30 h old
          dict(lat=47.51, lon=-120.51, t=NOW - 2 * H, src="V", frp=1, fire=None, unc=False, since=None),    # 1.3 km from A
          dict(lat=49.15, lon=-119.15, t=NOW - 2 * H, src="V", frp=1, fire=None, unc=False, since=None),    # 18 km from B, inside its perimeter
          dict(lat=44.0, lon=-122.0, t=NOW - 2 * H, src="M", frp=1, fire=None, unc=False, since=None),      # nothing near
          dict(lat=46.0, lon=-118.0, t=NOW - H, src="G", frp=1, fire="ZZZ", unc=False, since=None)]         # id not in the list -> unlinked
    fires.link_hotspots(hs, fl, perims, NOW)
    assert [h["fire"] for h in hs] == ["A", "A", "A", "B", None, None]
    assert [f["hot24"] for f in fl] == [2, 1]
    assert fires.dist_km(47.5, -120.5, 47.51, -120.51) == pytest.approx(1.34, abs=0.05)


def test_hotspot_rows():
    hs = [dict(lat=47.5, lon=-120.51234, t=NOW - 90 * 60, src="V", frp=5.34, fire="A", unc=False, since=None),
          dict(lat=49.2, lon=-118.8, t=NOW - 300, src="G", frp=None, fire=None, unc=True, since=NOW - 3 * H)]
    assert fires.hotspot_rows(hs, NOW) == [[47.5, -120.5123, 1.5, "V", 5.3, "A", 0, None], [49.2, -118.8, 0.1, "G", None, None, 1, NOW - 3 * H]]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_fires.py -v -k "firms or ngfs or geom or link or rows"`
Expected: FAIL with `AttributeError: module 'fires' has no attribute 'parse_firms'` (and the others).

- [ ] **Step 3: Implement the hotspot functions**

Append to `fires.py`:

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_fires.py -v`
Expected: 14 passed.

- [ ] **Step 5: Commit**

```bash
git add fires.py tests/test_fires.py
git commit -m "fires: FIRMS and NGFS hotspots, de-duplication, linking to fires by id, distance and perimeter

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: Perimeters, ArcGIS helpers, edit stamps, InciWeb links, the state file

**Files:**
- Modify: `fires.py` (append)
- Test: `tests/test_fires.py` (append)

**Interfaces:**
- Consumes: `point_in_geom`, `geom_bbox` (Task 2); `irwin`, `ms` (Task 1).
- Produces:
  - `fires.arcgis_query(layer: str, params: dict, log) -> dict`: GeoJSON with paging (`resultOffset`) while `exceededTransferLimit`; raises on failure.
  - `fires.layer_stamp(layer: str) -> int | None`: `editingInfo.dataLastEditDate` from `<layer>?f=pjson`.
  - `fires.parse_perims(wfigs_g: dict, bcws_g: dict, bc_ids: dict, bbox) -> list[dict]`: GeoJSON Features `{properties: {id, name, acres, t}, geometry}` whose bounding box touches `bbox`; id from `attr_IrwinID` or `bc_ids[FIRE_NUMBER]` (BCWS-only fires use `"BC_" + number`); `t` from `poly_DateCurrent` / `LOAD_DATE`.
  - `fires.inciweb_links(rss_text: str) -> dict[tuple[str, str], str]`: `{(norm_name, state_name_lower): url}`.
  - `fires.norm_name(s) -> str`, `fires.STATE_NAMES` (abbreviation → name).
  - `fires.load_store() -> dict` (`{"v": 1}` when missing or wrong version), `fires.save_store(store)`.
  - `fires.bbox_touches(b, bbox) -> bool`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_fires.py`:

```python
# ---------- perimeters, stamps, links, store ----------
def perim(irwin_id, name, x0, y0, acres=1000, t=NOW - 3 * H):
    p = {"attr_IrwinID": irwin_id, "poly_IncidentName": name, "poly_GISAcres": acres, "poly_DateCurrent": t * 1000, "attr_IncidentSize": acres}
    ring = [[x0, y0], [x0 + 0.2, y0], [x0 + 0.2, y0 + 0.2], [x0, y0 + 0.2], [x0, y0]]
    return {"type": "Feature", "properties": p, "geometry": {"type": "Polygon", "coordinates": [ring]}}


def bc_perim(num, x0, y0, ha=100, t=NOW - 5 * H):
    p = {"FIRE_NUMBER": num, "FIRE_SIZE_HECTARES": ha, "LOAD_DATE": t * 1000}
    ring = [[x0, y0], [x0 + 0.1, y0], [x0 + 0.1, y0 + 0.1], [x0, y0 + 0.1], [x0, y0]]
    return {"type": "Feature", "properties": p, "geometry": {"type": "MultiPolygon", "coordinates": [[ring]]}}


def test_parse_perims_joins_ids_converts_and_clips():
    wg = fc([perim("{B8431C26-6A9B-4EF0-88D8-F7EA9A3F56C3}", "Rowe Creek", -120.2, 44.8),
             perim("{7}", "Far away", -100.0, 30.0)])
    bg = fc([bc_perim("V12186", -121.9, 49.0), bc_perim("G12290", -121.6, 50.0), bc_perim("K42287", -122.1, 51.0)])
    out = fires.parse_perims(wg, bg, {"V12186": "2026_BC_2026-V12186", "G12290": "BC_G12290"}, BBOX)
    assert [f["properties"]["id"] for f in out] == ["B8431C26-6A9B-4EF0-88D8-F7EA9A3F56C3", "2026_BC_2026-V12186", "BC_G12290", "BC_K42287"]
    assert out[0]["properties"] == {"id": "B8431C26-6A9B-4EF0-88D8-F7EA9A3F56C3", "name": "Rowe Creek", "acres": 1000.0, "t": NOW - 3 * H}
    assert out[1]["properties"]["acres"] == pytest.approx(100 * 2.4711) and out[1]["properties"]["name"] == "V12186"
    assert out[1]["geometry"]["type"] == "MultiPolygon"


def test_orphan_perimeter_kept_by_bbox():
    # a polygon reaching into the window from outside, and one with no IRWIN id: both kept, named from the polygon
    wg = fc([perim("{8}", "Edge fire", -112.6, 45.0), perim(None, "Orphan", -120.0, 46.0), perim("{9}", "Outside", -112.3, 45.0)])
    out = fires.parse_perims(wg, fc([]), {}, BBOX)
    assert [f["properties"]["name"] for f in out] == ["Edge fire", "Orphan"]
    assert out[1]["properties"]["id"] is None


def test_bbox_touches():
    assert fires.bbox_touches((44.8, 45.0, -120.2, -120.0), BBOX)
    assert fires.bbox_touches((45.0, 45.2, -112.6, -112.4), BBOX)          # straddles the east edge
    assert not fires.bbox_touches((30.0, 30.2, -100.0, -99.8), BBOX)


RSS = """<?xml version="1.0"?><rss><channel>
<item><title>CAYNP Dome Fire</title><link>http://inciweb.wildfire.gov/incident-information/caynp-dome-fire</link>
<description>Last updated: 2026-09-28 --- The type of incident is Wildfire and involves the following unit(s) Yosemite National Park. --- State: California --- Coordinates: Latitude: 37 33 58</description></item>
<item><title>ORPRD Rowe Creek Complex</title><link>http://inciweb.wildfire.gov/incident-information/orprd-rowe-creek-complex</link>
<description>Last updated: 2026-09-27 --- The type of incident is Wildfire --- State: Oregon --- Coordinates: x</description></item>
<item><title>Bad item</title></item>
</channel></rss>"""


def test_inciweb_links_by_normalised_name_and_state():
    links = fires.inciweb_links(RSS)
    assert links == {("dome", "california"): "https://inciweb.wildfire.gov/incident-information/caynp-dome-fire",
                     ("rowecreek", "oregon"): "https://inciweb.wildfire.gov/incident-information/orprd-rowe-creek-complex"}
    assert fires.norm_name("ROWE CREEK COMPLEX") == "rowecreek" and fires.norm_name("Dome Fire") == "dome" and fires.norm_name("GALENA RX") == "galena"
    assert fires.STATE_NAMES["OR"] == "Oregon" and len(fires.STATE_NAMES) == 51


def test_store_roundtrip_and_bad_store(tmp_path, monkeypatch):
    monkeypatch.setattr(fires, "DATA", str(tmp_path))
    monkeypatch.setattr(fires, "STORE", str(tmp_path / "fires_cache.json"))
    assert fires.load_store() == {"v": 1}
    fires.save_store({"v": 1, "stamps": {"wfigs": 5}})
    assert fires.load_store()["stamps"] == {"wfigs": 5}
    (tmp_path / "fires_cache.json").write_text("{bad json", encoding="utf-8")
    assert fires.load_store() == {"v": 1}
    (tmp_path / "fires_cache.json").write_text('{"v": 0}', encoding="utf-8")
    assert fires.load_store() == {"v": 1}


def test_arcgis_query_pages_and_layer_stamp(monkeypatch):
    calls = []

    def fake_fetch(url):
        calls.append(url)
        q = dict(urllib.parse.parse_qsl(url.split("?", 1)[1]))
        if url.endswith("f=pjson"):
            return json.dumps({"editingInfo": {"dataLastEditDate": 1790601765537}}).encode(), ""
        off = int(q.get("resultOffset", 0))
        feats = [wf("F%d" % (off + i), 45, -120, irwin="{%d}" % (off + i)) for i in range(2)]
        return json.dumps({"type": "FeatureCollection", "features": feats, "exceededTransferLimit": off < 2}).encode(), ""

    monkeypatch.setattr(fires, "fetch", fake_fetch)
    g = fires.arcgis_query(fires.WFIGS_INC, {"where": "1=1", "outFields": "IncidentName"}, log=lambda m: None)
    assert [f["properties"]["IncidentName"] for f in g["features"]] == ["F0", "F1", "F2", "F3"] and len(calls) == 2
    assert calls[0].startswith(fires.WFIGS_INC + "/query?") and "f=geojson" in calls[0] and "resultOffset=2" in calls[1]
    assert fires.layer_stamp(fires.WFIGS_INC) == 1790601765537
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_fires.py -v -k "perim or bbox or inciweb or store or arcgis"`
Expected: FAIL with `AttributeError` for each missing function.

- [ ] **Step 3: Implement**

Append to `fires.py`:

```python
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
        out.append({"type": "Feature", "properties": {"id": bc_ids.get(n, "BC_" + n), "name": n, "acres": round(ha * HA_TO_ACRES, 1) if ha else None,
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_fires.py -v`
Expected: 21 passed.

- [ ] **Step 5: Commit**

```bash
git add fires.py tests/test_fires.py
git commit -m "fires: perimeters joined by id and clipped to the window; ArcGIS paging and edit stamps; InciWeb links; state file

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: Activity rule, FIRES output, `build()`, job wiring

**Files:**
- Modify: `fires.py` (append)
- Modify: `capture.py:225-229` (add the fires call after airquality)
- Modify: `cloud.py:38-39` (add `fires_cache.json` to `STATE_FILES`)
- Test: `tests/test_fires.py` (append)

**Interfaces:**
- Consumes: everything above.
- Produces:
  - `fires.is_active(f: dict, now: int) -> bool`.
  - `fires.to_fires(fire_list, hs, perims, now, ngfs_ok: bool) -> dict` (the `window.FIRES` object; fire records lose `bcnum`/`status` and gain `active`, `perim`, `hot24`; `src` stays).
  - `fires.write_perims(feats, now)`: writes `perimeters.js` with `age_h` per polygon.
  - `fires.build(log=print, now=None) -> int` (fires written); writes `fires.js`, `perimeters.js`, the store; raises when no incident source answered (capture logs "fires FAILED" and the last good files stay).
  - `fires.ngfs_scene() -> str` ("west" / "east" from `region.cfg().get("goes", "West")`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_fires.py`:

```python
# ---------- activity, output, build ----------
def rec(**kw):
    r = fires._rec(id="X", name="X", lat=47, lon=-120)
    r.update(kw)
    r.setdefault("hot24", 0)
    return r


@pytest.mark.parametrize("kw,active", [
    (dict(modified=NOW - 72 * H), True), (dict(modified=NOW - 72 * H - 1), False),
    (dict(modified=NOW - 10 * 24 * H, hot24=1), True),
    (dict(modified=NOW - H, contained=100), False), (dict(modified=NOW - 10 * 24 * H, contained=100, hot24=2), True),
    (dict(modified=None, stage="OC"), True), (dict(modified=None, stage="BH"), True), (dict(modified=None, stage="UC"), False),
    (dict(modified=None), False),
])
def test_is_active(kw, active):
    assert fires.is_active(rec(**kw), NOW) is active


def test_to_fires_shape():
    fl = [rec(id="A", modified=NOW - H, bcnum=None, status=None, acres=12.34, desc="d", src="wfigs"),
          rec(id="B", name="Chilliwack River", src="cwfif", bcws=True, bcnum="V1", status="Under Control", stage="UC", url="u", note=True)]
    hs = [dict(lat=47.001, lon=-120.001, t=NOW - H, src="V", frp=3, fire="A", unc=False, since=None)]
    perims = [{"type": "Feature", "properties": {"id": "B", "name": "V1", "acres": 1, "t": NOW}, "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]}}]
    fires.link_hotspots(hs, fl, perims, NOW)
    d = fires.to_fires(fl, hs, perims, NOW, ngfs_ok=False)
    assert set(d) == {"updated", "updated_t", "ngfs", "fires", "hotspots"} and d["ngfs"] is False and d["updated_t"] == NOW
    a, b = d["fires"]
    assert a["active"] is True and a["perim"] is False and a["hot24"] == 1 and "bcnum" not in a and "status" not in a
    assert b["active"] is False and b["perim"] is True and b["stage"] == "UC" and b["bcws"] is True
    assert d["hotspots"] == [[47.001, -120.001, 1.0, "V", 3.0, "A", 0, None]]


def test_perims_js_ages(monkeypatch, tmp_path):
    monkeypatch.setattr(fires, "OUT_PERIMS", str(tmp_path / "perimeters.js"))
    feats = [{"type": "Feature", "properties": {"id": "B", "name": "V1", "acres": 1, "t": NOW - 5 * H}, "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]}}]
    fires.write_perims(feats, NOW)
    txt = (tmp_path / "perimeters.js").read_text(encoding="utf-8")
    assert txt.startswith("window.PERIMS = ") and json.loads(txt[len("window.PERIMS = "):].rstrip().rstrip(";"))["features"][0]["properties"]["age_h"] == 5.0


def test_ngfs_scene(monkeypatch):
    monkeypatch.setattr(fires.region, "cfg", lambda: {"goes": "East"})
    assert fires.ngfs_scene() == "east"
    monkeypatch.setattr(fires.region, "cfg", lambda: {})
    assert fires.ngfs_scene() == "west"


class FakeNet:
    """answers fires' fetch/arcgis calls from a dict of url-substring -> (body, raises)"""
    def __init__(self, answers):
        self.answers, self.calls = answers, []

    def __call__(self, url):
        self.calls.append(url)
        for k, v in self.answers.items():
            if k in url:
                if isinstance(v, Exception):
                    raise v
                return (v if isinstance(v, bytes) else json.dumps(v).encode()), "Mon, 28 Sep 2026 13:00:00 GMT"
        raise fires.NotPosted(url)


def build_env(monkeypatch, tmp_path, answers, store=None):
    monkeypatch.setattr(fires, "DATA", str(tmp_path))
    monkeypatch.setattr(fires, "OUT", str(tmp_path / "fires.js"))
    monkeypatch.setattr(fires, "OUT_PERIMS", str(tmp_path / "perimeters.js"))
    monkeypatch.setattr(fires, "STORE", str(tmp_path / "fires_cache.json"))
    monkeypatch.setattr(fires.region, "bbox", lambda: BBOX)
    monkeypatch.setattr(fires.region, "cfg", lambda: {})
    if store:
        (tmp_path / "fires_cache.json").write_text(json.dumps(store), encoding="utf-8")
    net = FakeNet(answers)
    monkeypatch.setattr(fires, "fetch", net)
    return net


def read_js(path, prefix):
    return json.loads(path.read_text(encoding="utf-8")[len(prefix):].rstrip().rstrip(";"))


def full_answers():
    return {"WFIGS_Incident_Locations_Current/FeatureServer/0?f=pjson": {"editingInfo": {"dataLastEditDate": 1}},
            "WFIGS_Incident_Locations_Current/FeatureServer/0/query": fc([wf("ROWE CREEK COMPLEX", 44.9, -120.1, typ="CX"), wf("FAR", 30, -100, irwin="{2}")]),
            "WFIGS_Interagency_Perimeters_Current/FeatureServer/0?f=pjson": {"editingInfo": {"dataLastEditDate": 10}},
            "WFIGS_Interagency_Perimeters_Current/FeatureServer/0/query": fc([perim("{B8431C26-6A9B-4EF0-88D8-F7EA9A3F56C3}", "Rowe Creek", -120.2, 44.8)]),
            "BCWS_FirePerimeters_PublicView/FeatureServer/0?f=pjson": {"editingInfo": {"dataLastEditDate": 20}},
            "BCWS_FirePerimeters_PublicView/FeatureServer/0/query": fc([bc_perim("V12186", -121.9, 49.0)]),
            "BCWS_ActiveFires_PublicView": fc([bc()]),
            "geoserver.cwfif": fc([cw()]),
            "firms.modaps": ("\n".join([FIRMS_HDR, firms_row(44.85, -120.15, NOW - 2 * H)]) + "\n").encode(),
            "fire.data.nesdis": fc([ngfs_feat("ID-2026-09-28T03:31:19.000Z_0003", NOW - 600, lat=49.05, lon=-121.85, typ="Possible Wildland Fire")]),
            "inciweb": RSS.encode()}


def test_build_writes_files_store_and_log(monkeypatch, tmp_path):
    net = build_env(monkeypatch, tmp_path, full_answers())
    lines = []
    n = fires.build(log=lines.append, now=NOW)
    d = read_js(tmp_path / "fires.js", "window.FIRES = ")
    assert n == 2 and [f["name"] for f in d["fires"]] == ["ROWE CREEK COMPLEX", "Chilliwack River"]     # FAR is outside the window
    rowe = d["fires"][0]
    assert rowe["url"] == "https://inciweb.wildfire.gov/incident-information/orprd-rowe-creek-complex" and rowe["perim"] is True and rowe["hot24"] == 1
    assert d["ngfs"] is True and [h[3] for h in d["hotspots"]] == ["V", "G"] and d["hotspots"][1][6] == 1
    p = read_js(tmp_path / "perimeters.js", "window.PERIMS = ")
    assert [f["properties"]["id"] for f in p["features"]] == ["B8431C26-6A9B-4EF0-88D8-F7EA9A3F56C3", "2026_BC_2026-V12186"]
    store = json.loads((tmp_path / "fires_cache.json").read_text(encoding="utf-8"))
    assert store["stamps"] == {"wfigs": 10, "bcws": 20} and len(store["perims"]) == 2 and store["ngfs"]["t"] == NOW and len(store["ngfs"]["hs"]) == 1
    assert lines[-1] == "fires: 2 fires (2 active, 0 prescribed, 1 Canada), 2 perimeters (new), hotspots 1 FIRMS + 1 NGFS"
    assert sum(1 for u in net.calls if "firms.modaps" in u) == 8


def test_build_unchanged_stamps_reuse_perimeters_and_ngfs_cache_on_failure(monkeypatch, tmp_path):
    a = full_answers()
    a["fire.data.nesdis"] = OSError("timeout")
    store = {"v": 1, "stamps": {"wfigs": 10, "bcws": 20}, "perims": [{"type": "Feature", "properties": {"id": "OLD", "name": "Old", "acres": 1, "t": NOW - 30 * H}, "geometry": {"type": "Polygon", "coordinates": [[[-120.2, 44.8], [-120.0, 44.8], [-120.0, 45.0], [-120.2, 44.8]]]}}],
             "ngfs": {"t": NOW - 1800, "hs": [dict(lat=49.05, lon=-121.85, t=NOW - 2000, src="G", frp=1, fire=None, unc=True, since=None)]}}
    net = build_env(monkeypatch, tmp_path, a, store)
    lines = []
    fires.build(log=lines.append, now=NOW)
    assert not any("Perimeters_Current/FeatureServer/0/query" in u or "FirePerimeters_PublicView/FeatureServer/0/query" in u for u in net.calls)
    p = read_js(tmp_path / "perimeters.js", "window.PERIMS = ")
    assert [f["properties"]["id"] for f in p["features"]] == ["OLD"] and p["features"][0]["properties"]["age_h"] == 30.0
    d = read_js(tmp_path / "fires.js", "window.FIRES = ")
    assert d["ngfs"] is True and [h[3] for h in d["hotspots"]] == ["V", "G"]          # cached NGFS reused (30 min old)
    assert any("NGFS" in l and "cached" in l for l in lines) and "2 perimeters (unchanged)" not in lines[-1] and "1 perimeters (unchanged)" in lines[-1]


def test_build_ngfs_cache_expires_and_incident_failure_keeps_last_good(monkeypatch, tmp_path):
    a = full_answers()
    a["fire.data.nesdis"] = OSError("timeout")
    store = {"v": 1, "ngfs": {"t": NOW - 3601, "hs": [dict(lat=49.05, lon=-121.85, t=NOW - 4000, src="G", frp=1, fire=None, unc=True, since=None)]}}
    build_env(monkeypatch, tmp_path, a, store)
    fires.build(log=lambda m: None, now=NOW)
    d = read_js(tmp_path / "fires.js", "window.FIRES = ")
    assert d["ngfs"] is False and [h[3] for h in d["hotspots"]] == ["V"]
    # now every incident source fails: build raises and the files above are untouched
    a["WFIGS_Incident_Locations_Current/FeatureServer/0/query"] = OSError("down")
    a["geoserver.cwfif"] = OSError("down")
    a["BCWS_ActiveFires_PublicView"] = OSError("down")
    before = (tmp_path / "fires.js").read_text(encoding="utf-8")
    with pytest.raises(RuntimeError):
        fires.build(log=lambda m: None, now=NOW + 900)
    assert (tmp_path / "fires.js").read_text(encoding="utf-8") == before


def test_build_one_incident_source_down_still_writes(monkeypatch, tmp_path):
    a = full_answers()
    a["geoserver.cwfif"] = OSError("down")
    a["BCWS_ActiveFires_PublicView"] = OSError("down")
    build_env(monkeypatch, tmp_path, a)
    lines = []
    fires.build(log=lines.append, now=NOW)
    d = read_js(tmp_path / "fires.js", "window.FIRES = ")
    assert [f["name"] for f in d["fires"]] == ["ROWE CREEK COMPLEX"] and any("CWFIF" in l and "failed" in l for l in lines)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_fires.py -v -k "active or to_fires or perims_js or scene or build"`
Expected: FAIL with `AttributeError` (`is_active`, `to_fires`, `write_perims`, `ngfs_scene`, `build`).

- [ ] **Step 3: Implement the activity rule, output and `build()`**

Append to `fires.py`:

```python
# ---------- activity, output, build ----------
def is_active(f, now):
    """spec ledger: updated within ACTIVE_H, or hotspots within HOT_H, or Canadian stage OC / BH;
    100 % contained is quiet unless it has hotspots"""
    if f.get("hot24", 0) > 0:
        return True
    if f.get("contained") is not None and f["contained"] >= 100:
        return False
    if f.get("stage") in ("OC", "BH"):
        return True
    m = f.get("modified")
    return m is not None and 0 <= now - m <= ACTIVE_H * 3600


def to_fires(fire_list, hs, perims, now, ngfs_ok):
    """the window.FIRES object"""
    with_perim = {p["properties"]["id"] for p in perims if p["properties"].get("id")}
    out = []
    for f in fire_list:
        r = {k: v for k, v in f.items() if k not in ("bcnum", "status")}
        r["acres"] = None if f.get("acres") is None else round(f["acres"], 1)
        r["lat"], r["lon"] = round(f["lat"], 4), round(f["lon"], 4)
        r["hot24"] = f.get("hot24", 0)
        r["perim"] = f["id"] in with_perim
        r["active"] = is_active(r, now)
        out.append(r)
    return {"updated": dt.datetime.fromtimestamp(now).strftime("%a %b %d %I:%M %p"), "updated_t": int(now), "ngfs": bool(ngfs_ok),
            "fires": out, "hotspots": hotspot_rows(hs, now)}


def write_perims(feats, now):
    fc = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": dict(p["properties"], age_h=None if p["properties"].get("t") is None else round(max(0, now - p["properties"]["t"]) / 3600, 1)),
         "geometry": p["geometry"]} for p in feats]}
    os.makedirs(os.path.dirname(OUT_PERIMS), exist_ok=True)
    _write(OUT_PERIMS, "window.PERIMS = %s;\n" % json.dumps(fc, separators=(",", ":")))


def ngfs_scene():
    return "east" if str(region.cfg().get("goes", "West")).lower().startswith("e") else "west"


def in_window(lat, lon, bbox):
    return bbox[0] <= lat <= bbox[1] and bbox[2] <= lon <= bbox[3]


def _try(log, what, fn, *a):
    """run fn; on any failure log 'fires: <what> failed: ...' and return None"""
    try:
        return fn(*a)
    except Exception as e:  # noqa: BLE001
        log("fires: %s failed: %r" % (what, e))
        return None


def build(log=print, now=None):
    t_start = time.time()
    now = int(now or time.time())
    bbox = region.bbox()
    store = load_store()

    # 1. incidents
    fire_list, ok = [], []
    g = _try(log, "WFIGS incidents", arcgis_query, WFIGS_INC, {"where": "1=1", "outFields": WFIGS_FIELDS}, log)
    if g is not None:
        fire_list += parse_wfigs(g)
        ok.append("wfigs")
    cwg = _try(log, "CWFIF", lambda: json.loads(fetch(CWFIF + "?" + urllib.parse.urlencode({
        "service": "WFS", "version": "2.0.1", "request": "GetFeature", "outputFormat": "application/json",
        "typeName": "public:cwfif_national_activefires", "CQL_FILTER": "now()>=record_start AND now()<=record_end", "srsName": "EPSG:4326"}))[0]))
    bcg = _try(log, "BCWS fires", arcgis_query, BCWS_FIRES, {"where": "FIRE_STATUS<>'Out'", "outFields": BCWS_FIELDS}, log)
    if cwg is not None or bcg is not None:
        fire_list += join_canada(parse_cwfif(cwg) if cwg is not None else [], parse_bcws(bcg) if bcg is not None else {})
        ok.append("canada")
    if not ok:
        raise RuntimeError("no incident source answered; keeping the last good fires.js")
    fire_list = [f for f in fire_list if in_window(f["lat"], f["lon"], bbox)]
    bc_ids = {f["bcnum"]: f["id"] for f in fire_list if f.get("bcnum")}
    bc_ids.update({f["id"][3:]: f["id"] for f in fire_list if f["src"] == "bcws"})

    links = _try(log, "InciWeb links", lambda: inciweb_links(fetch(INCIWEB)[0].decode("utf-8", "replace"))) or {}
    for f in fire_list:
        if f["src"] == "wfigs" and not f.get("url"):
            f["url"] = links.get((norm_name(f["name"]), STATE_NAMES.get(f.get("state") or "", "").lower()))

    # 2. perimeters: refetch only when a layer's edit stamp changed
    stamps = {"wfigs": _try(log, "WFIGS perimeter stamp", layer_stamp, WFIGS_PERIM), "bcws": _try(log, "BCWS perimeter stamp", layer_stamp, BCWS_PERIM)}
    old = store.get("stamps") or {}
    perims, pstate = store.get("perims"), "unchanged"
    if perims is None or stamps["wfigs"] is None or stamps["bcws"] is None or stamps != old:
        wg = _try(log, "WFIGS perimeters", arcgis_query, WFIGS_PERIM, {"where": "1=1", "outFields": PERIM_FIELDS, "maxAllowableOffset": "0.001", "geometryPrecision": "4"}, log)
        bg = _try(log, "BCWS perimeters", arcgis_query, BCWS_PERIM, {"where": "FIRE_STATUS<>'Out'", "outFields": BCWS_PERIM_FIELDS, "maxAllowableOffset": "0.001", "geometryPrecision": "4"}, log)
        if wg is not None and bg is not None:
            perims = parse_perims(wg, bg, bc_ids, bbox)
            store["perims"], store["stamps"], pstate = perims, stamps, "new"
        elif perims is None:
            perims, pstate = [], "FAILED"
        else:
            pstate = "kept after a failed fetch"
    write_perims(perims, now)

    # 3. hotspots
    hs, seen, n_firms = [], set(), 0
    for sat, path in (("V", "noaa-20-viirs-c2/csv/J1_VIIRS_C2"), ("V", "noaa-21-viirs-c2/csv/J2_VIIRS_C2"),
                      ("V", "suomi-npp-viirs-c2/csv/SUOMI_VIIRS_C2"), ("M", "modis-c6.1/csv/MODIS_C6_1")):
        for area in ("USA_contiguous_and_Hawaii", "Canada"):
            if time.time() - t_start > DEADLINE_S:
                log("fires: FIRMS: out of time before %s %s" % (path.rsplit("/", 1)[-1], area))
                break
            body = _try(log, "FIRMS %s %s" % (path.rsplit("/", 1)[-1], area), fetch, "%s%s_%s_%dh.csv" % (FIRMS, path, area, FIRMS_H))
            if body is None:
                continue
            got = [h for h in parse_firms(body[0].decode("utf-8", "replace"), sat, seen) if in_window(h["lat"], h["lon"], bbox) and now - h["t"] <= FIRMS_H * 3600]
            hs += got
            n_firms += len(got)
    t1 = dt.datetime.fromtimestamp(now, dt.timezone.utc)
    t0 = t1 - dt.timedelta(hours=HOT_H)
    q = urllib.parse.urlencode({"f": "json", "datetime": "%s/%s" % (t0.strftime("%Y-%m-%dT%H:%M:%SZ"), t1.strftime("%Y-%m-%dT%H:%M:%SZ")),
                                "datetime-column": "acq_date_time", "limit": 5000, "bbox": "%.3f,%.3f,%.3f,%.3f" % (bbox[2], bbox[0], bbox[3], bbox[1])})
    ng = _try(log, "NGFS", lambda: json.loads(fetch((NGFS % ngfs_scene()) + "?" + q)[0]))
    ngfs_ok = ng is not None
    if ng is not None:
        if ng.get("numberMatched") and ng.get("numberReturned") and ng["numberMatched"] > ng["numberReturned"]:
            log("fires: NGFS returned %d of %d (cap); consider paging" % (ng["numberReturned"], ng["numberMatched"]))
        ngs = [h for h in parse_ngfs(ng, now) if in_window(h["lat"], h["lon"], bbox)]
        store["ngfs"] = {"t": now, "hs": ngs}
    else:
        c = store.get("ngfs") or {}
        if c.get("t") and now - c["t"] <= NGFS_CACHE_S:
            ngs = [h for h in c.get("hs", []) if now - h["t"] <= HOT_H * 3600]
            ngfs_ok = True
            log("fires: NGFS failed; %d cached detections reused (%d min old)" % (len(ngs), (now - c["t"]) // 60))
        else:
            ngs = []
    hs += ngs
    link_hotspots(hs, fire_list, perims, now)

    # 4. write
    data = to_fires(fire_list, hs, perims, now, ngfs_ok)
    os.makedirs(DATA, exist_ok=True)
    _write(OUT, "window.FIRES = %s;\n" % json.dumps(data, separators=(",", ":")))
    save_store(store)
    fl = data["fires"]
    log("fires: %d fires (%d active, %d prescribed, %d Canada), %d perimeters (%s), hotspots %d FIRMS + %d NGFS" % (
        len(fl), sum(f["active"] for f in fl), sum(f["type"] == "RX" for f in fl), sum(f["src"] != "wfigs" for f in fl),
        len(perims), pstate, n_firms, len(ngs)))
    return len(fl)


if __name__ == "__main__":
    t0 = time.time()
    build()
    print("done in %.0fs" % (time.time() - t0))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_fires.py -v`
Expected: 35 passed. If `test_build_writes_files_store_and_log` fails on the log line, print `lines` and match the format exactly; do not loosen the assertion.

- [ ] **Step 5: Wire the job**

In `capture.py`, after the `airquality` block (line 229), add:

```python
        try:
            import fires
            ok.append("fires %d" % fires.build(log))
        except Exception as e:  # noqa: BLE001
            log("fires FAILED: %r" % e)
```

In `cloud.py` line 39, append `"fires_cache.json"` to `STATE_FILES`.

- [ ] **Step 6: Run the whole suite and commit**

Run: `python -m pytest tests/ -q`
Expected: all pass (134 + 35).

```bash
git add fires.py tests/test_fires.py capture.py cloud.py
git commit -m "fires: activity rule, FIRES and PERIMS output, build() with stamp-gated perimeters and NGFS fallback; job wiring

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: Data-check gate: `fires_check.py`, `fires_serve.py`, run for pnw, STOP

**Files:**
- Create: `smoke_research/fires_check.py`
- Create: `smoke_research/fires_serve.py`

**Interfaces:**
- Consumes: `fires.build`, `fires.OUT`, `fires.OUT_PERIMS`, `fires.fetch`, `fires.parse_*`, `fires.dist_km`, `fires.point_in_geom`, `region.window()`.
- Produces: `smoke_research/checks/fires_check_<region>.png`; console output for Chris.

- [ ] **Step 1: Write `fires_check.py`**

```python
"""
Data check for the fires layer (spec: "Data check (gate before any map code)").

Runs fires.build() for one region WITHOUT uploading (it never calls r2sync), then prints:
  1. accounting: WFIGS rows by type, children and out dropped, inside the window; CWFIF rows, BCWS matched and unmatched;
     perimeters with and without an incident; FIRMS rows per file, duplicates removed, inside; NGFS features, distinct
     tracked features, known vs possible; hotspots linked to a fire
  2. independent checks: (a) VIIRS 24 h detections within 2 km of a fire or inside a perimeter, and active fires with
     >= 1 hotspot; big fires without hotspots and dense clusters without a fire; (b) polygon acres vs reported acres;
     (c) every NGFS known_incident_id exists in WFIGS
  3. a MATLAB-style figure: the window with perimeters, fires and hotspots; the ten largest active fires as bars

Usage (from the repo root):  python smoke_research/fires_check.py [region]   figure -> smoke_research/checks/fires_check_<region>.png
"""
import json
import math
import os
import sys
import urllib.parse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ["REGION"] = (sys.argv[1] if len(sys.argv) > 1 else "pnw")
sys.path.insert(0, ROOT)

import fires  # noqa: E402
import region  # noqa: E402


def gj(url, params):
    return json.loads(fires.fetch(url + "?" + urllib.parse.urlencode(params))[0])


def main():
    bbox = region.bbox()
    n = fires.build(log=print)
    with open(fires.OUT, encoding="utf-8") as f:
        d = json.loads(f.read()[len("window.FIRES = "):].rstrip().rstrip(";"))
    with open(fires.OUT_PERIMS, encoding="utf-8") as f:
        perims = json.loads(f.read()[len("window.PERIMS = "):].rstrip().rstrip(";"))["features"]
    now = d["updated_t"]
    fl, hs = d["fires"], d["hotspots"]

    # ---- 1. accounting ----
    g = gj(fires.WFIGS_INC + "/query", {"where": "1=1", "outFields": fires.WFIGS_FIELDS, "f": "geojson", "returnGeometry": "true", "outSR": "4326"})
    feats = g["features"]
    by = {}
    for f in feats:
        p = f["properties"]
        by[p.get("IncidentTypeCategory")] = by.get(p.get("IncidentTypeCategory"), 0) + 1
    kept = fires.parse_wfigs(g)
    inside = [r for r in kept if fires.in_window(r["lat"], r["lon"], bbox)]
    print("\n== accounting (%s window) ==" % region.KEY)
    print("WFIGS: %d rows %s; kept %d (WF/CX/RX with a point and IRWIN id, not complex children, not out); inside the window %d"
          % (len(feats), by, len(kept), len(inside)))
    cw = fires.parse_cwfif(gj(fires.CWFIF, {"service": "WFS", "version": "2.0.1", "request": "GetFeature", "outputFormat": "application/json",
                                           "typeName": "public:cwfif_national_activefires", "CQL_FILTER": "now()>=record_start AND now()<=record_end", "srsName": "EPSG:4326"}))
    bc = fires.parse_bcws(gj(fires.BCWS_FIRES + "/query", {"where": "FIRE_STATUS<>'Out'", "outFields": fires.BCWS_FIELDS, "f": "geojson", "returnGeometry": "true", "outSR": "4326"}))
    cw_in = [r for r in cw if fires.in_window(r["lat"], r["lon"], bbox)]
    matched = [r for r in cw_in if r.get("bcnum") in bc]
    bc_only = [k for k, v in bc.items() if v["lat"] is not None and fires.in_window(v["lat"], v["lon"], bbox) and k not in {r.get("bcnum") for r in cw}]
    print("CWFIF: %d national, %d inside; BCWS: %d not out, %d matched to CWFIF inside the window, %d BCWS-only inside"
          % (len(cw), len(cw_in), len(bc), len(matched), len(bc_only)))
    ids = {f["id"] for f in fl}
    print("perimeters: %d in the window, %d with an incident in FIRES, %d without" % (len(perims), sum(p["properties"]["id"] in ids for p in perims),
                                                                                       sum(p["properties"]["id"] not in ids for p in perims)))
    srcs = {}
    for h in hs:
        srcs[h[3]] = srcs.get(h[3], 0) + 1
    print("hotspots: %s; linked to a fire %d of %d; NGFS unconfirmed %d" % (srcs, sum(1 for h in hs if h[5]), len(hs), sum(1 for h in hs if h[6])))
    print("FIRES: %d fires (%d active, %d prescribed, %d Canada, %d with a link)" % (n, sum(f["active"] for f in fl), sum(f["type"] == "RX" for f in fl),
                                                                                    sum(f["src"] != "wfigs" for f in fl), sum(1 for f in fl if f.get("url"))))

    # ---- 2. independent checks ----
    print("\n== check (a): VIIRS detections (24 h) against fires and perimeters ==")
    v24 = [h for h in hs if h[3] == "V" and h[2] <= 24]
    near = sum(1 for h in v24 if h[5])
    print("%d VIIRS detections in 24 h: %d (%.0f%%) within 2 km of a fire or inside a perimeter" % (len(v24), near, 100 * near / max(len(v24), 1)))
    act = [f for f in fl if f["active"]]
    print("%d active fires: %d with >= 1 hotspot in 24 h" % (len(act), sum(1 for f in act if f["hot24"])))
    big_quiet = sorted([f for f in fl if (f["acres"] or 0) >= 1000 and f["hot24"] == 0 and f["active"]], key=lambda f: -(f["acres"] or 0))[:8]
    for f in big_quiet:
        print("  big active fire without hotspots: %s %s ac, %s%% contained, updated %.0f h ago" % (f["name"], f["acres"], f["contained"], (now - (f["modified"] or now)) / 3600))
    cells = {}
    for h in v24:
        if not h[5]:
            k = (round(h[0] / 0.05), round(h[1] / 0.05))
            cells[k] = cells.get(k, 0) + 1
    for k, c in sorted(cells.items(), key=lambda kv: -kv[1])[:5]:
        print("  cluster without a fire: %d detections near %.2f, %.2f" % (c, k[0] * 0.05, k[1] * 0.05))
    print("\n== check (b): polygon acres vs reported acres ==")
    byid = {f["id"]: f for f in fl}
    diffs, outl = [], []
    for p in perims:
        pp = p["properties"]
        f = byid.get(pp["id"])
        if not f or not f["acres"] or not pp["acres"]:
            continue
        r = pp["acres"] / f["acres"]
        diffs.append(r)
        if abs(r - 1) > 0.25:
            outl.append((pp["name"], pp["acres"], f["acres"], r))
    diffs.sort()
    if diffs:
        print("%d joined perimeters: polygon/reported median %.2f, 10th %.2f, 90th %.2f; %d more than 25%% apart" % (
            len(diffs), diffs[len(diffs) // 2], diffs[int(0.1 * (len(diffs) - 1))], diffs[int(0.9 * (len(diffs) - 1))], len(outl)))
    for o in outl[:10]:
        print("  %s: polygon %.0f ac vs reported %.0f ac (x%.2f)" % o)
    print("\n== check (c): NGFS known incidents exist in WFIGS ==")
    known = [h for h in hs if h[3] == "G" and not h[6]]
    print("%d NGFS known-incident detections: %d whose fire id is in FIRES" % (len(known), sum(1 for h in known if h[5] in ids)))

    figure(d, perims, now)


def figure(d, perims, now):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.style.use("matlab")
    z, x0, x1, y0, y1 = region.window()
    nn, W = 2 ** z, (x1 - x0 + 1) * 256

    def px(lat, lon):
        mx = (lon + 180) / 360 * nn
        my = (1 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi) / 2 * nn
        return (mx - x0) * 256, (my - y0) * 256

    fig = plt.figure(figsize=(13, 6.5))
    ax = fig.add_axes([0.03, 0.06, 0.5, 0.88])
    for p in perims:
        g = p["geometry"]
        for poly in (g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]):
            xy = [px(c[1], c[0]) for c in poly[0]]
            ax.fill([a for a, _ in xy], [b for _, b in xy], color="#c0392b", alpha=0.25, lw=0.6, ec="#c0392b")
    age_c = {0: "#ff2d00", 1: "#ff9a3c", 2: "#c9a76b"}
    for h in d["hotspots"]:
        x, y = px(h[0], h[1])
        ax.plot(x, y, ".", ms=3 if h[3] == "G" else 2, color=age_c[0 if h[2] < 6 else 1 if h[2] < 24 else 2], mfc="none" if h[6] else None, zorder=2)
    for f in d["fires"]:
        x, y = px(f["lat"], f["lon"])
        s = 20 if (f["acres"] or 0) < 100 else 50 if f["acres"] < 10000 else 110
        ax.scatter([x], [y], s=s, c="#8a8f98" if f["type"] == "RX" else "#d1462f", alpha=1 if f["active"] else 0.4, edgecolors="k", linewidths=0.4, zorder=3)
    ax.set_xlim(0, W)
    ax.set_ylim(W, 0)
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_title("%s: fires (size by acres, grey = prescribed, faded = quiet), perimeters, hotspots by age" % region.KEY, fontsize=10)
    a = fig.add_axes([0.62, 0.1, 0.35, 0.8])
    top = sorted([f for f in d["fires"] if f["active"] and f["acres"]], key=lambda f: -f["acres"])[:10][::-1]
    names = [f["name"][:28] for f in top]
    a.barh(names, [f["acres"] for f in top], color="#d9b8ad", label="reported acres")
    a.barh(names, [f["acres"] * (f["contained"] or 0) / 100 for f in top], color="#b5654a", label="contained share")
    a.set_xlabel("acres")
    a.set_title("ten largest active fires", fontsize=10)
    a.legend(fontsize=8, loc="lower right")
    out = os.path.join(ROOT, "smoke_research", "checks", "fires_check_%s.png" % region.KEY)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    fig.savefig(out, dpi=110)
    print("\nfigure:", out)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Write `fires_serve.py`**

Copy `smoke_research/aq_serve.py` to `smoke_research/fires_serve.py`, change the docstring's first line to "Preview the built page with this PC's air quality and fires files before anything is published.", set

```python
PORT = 8796          # 8795 is aq_serve
LOCAL = ("data/airquality.js", "frames/aq/", "data/values/aqi.js", "data/fires.js", "data/perimeters.js")
```

and the final print to `"serving on http://127.0.0.1:%d/?r=pnw (air quality and fires files local, the rest from %s)"`.

- [ ] **Step 3: Run the check for pnw**

Run from the worktree: `$env:PYTHONIOENCODING = "utf-8"; python smoke_research/fires_check.py pnw`
Expected: the `fires:` log line, the accounting block, checks (a)–(c), and the figure path. Open the PNG (Read tool) and look at it before showing it. If a source fails, read the log line, fix, re-run.

- [ ] **Step 4: Commit the check scripts (the PNG is gitignored: `*.png`)**

```bash
git add smoke_research/fires_check.py smoke_research/fires_serve.py
git commit -m "fires: data-check script (accounting, hotspot/perimeter/NGFS checks, figure) and local preview server

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

- [ ] **Step 5: STOP. Show Chris** the log line, the accounting block, the three checks and the figure (SendUserFile), and the ledger's judgment calls (activity rule, 2 km link, hotspot windows, colours). Wait for his go before Task 6.

---

### Task 6: Panel section and the `fireHelpers` block (node tests)

**Files:**
- Modify: `map.html:275-282` (panel HTML between Air quality and Hazards)
- Modify: `map.html:1454` (`DEF_CHECKS`)
- Modify: `map.html` (new `// BEGIN fireHelpers … // END fireHelpers` block after `// END aqHelpers`)
- Test: `tests/test_map_fires.py`

**Interfaces:**
- Produces (JS, inside the block, self-contained for node):
  - `FIRE_COL = {WF: '#d1462f', CX: '#d1462f', RX: '#8a8f98'}`, `PERIM_COL = '#c0392b'`, `HOT_BINS = [[0, '#ff2d00'], [6, '#ff9a3c'], [24, '#c9a76b']]`, `HOT_NAMES = ['< 6 h', '6–24 h', '24–48 h']`
  - `fireSize(acres) -> 0|1|2`, `hotAge(h) -> 0|1|2|-1`, `fireEsc(s)`, `fireAgo(t, nowS) -> '3 h ago' | '2 d ago' | 'just now' | ''`
  - `fireDist(lat1, lon1, lat2, lon2) -> km`, `fireNearest(list, lat, lon, maxKm, pred) -> {f, km} | null`, `hotsNear(rows, lat, lon, km, maxAgeH) -> n`
  - `fireTypeName(t) -> 'wildfire' | 'complex' | 'prescribed burn'`, `fireNeedsLoad(d, loadedAtMs, nowMs)` (15 min, like `aqNeedsLoad`)
  - Panel ids: `lyFires`, `fireQuiet`, `lyHot`, info divs `fireInfo`, `hotInfo`.

- [ ] **Step 1: Write the failing node tests**

Create `tests/test_map_fires.py`:

```python
"""Fires helpers in map.html (fireHelpers block), run under node; skipped where node is missing."""
import json
import os
import re
import shutil
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node not installed")


def run(expr):
    with open(os.path.join(ROOT, "map.html"), encoding="utf-8") as f:
        html = f.read()
    block = re.search(r"// BEGIN fireHelpers[^\n]*\n(.*?)// END fireHelpers", html, re.S).group(1)
    js = block + "\nprocess.stdout.write(JSON.stringify(" + expr + "));"
    return json.loads(subprocess.run([NODE, "-e", js], capture_output=True, text=True, check=True).stdout)


def test_size_steps_and_age_chips():
    assert run("[null, 0, 99, 100, 9999, 10000, 5e6].map(fireSize)") == [0, 0, 0, 1, 1, 2, 2]
    assert run("[0, 5.9, 6, 23.9, 24, 48, 48.1, null, NaN].map(hotAge)") == [0, 0, 1, 1, 2, 2, -1, -1, -1]
    assert run("HOT_BINS") == [[0, "#ff2d00"], [6, "#ff9a3c"], [24, "#c9a76b"]]
    assert run("[FIRE_COL.WF, FIRE_COL.CX, FIRE_COL.RX, PERIM_COL]") == ["#d1462f", "#d1462f", "#8a8f98", "#c0392b"]


def test_fire_escape():
    assert run("fireEsc('<b>Rowe & \"Creek\"</b>')") == "&lt;b&gt;Rowe &amp; &quot;Creek&quot;&lt;/b&gt;"
    assert run("fireEsc(null)") == ""


def test_ago_and_type_names():
    assert run("[fireAgo(1000, 1000 + 50), fireAgo(1000, 1000 + 3 * 3600), fireAgo(1000, 1000 + 40 * 3600), fireAgo(null, 5), fireAgo(1000, 1000 + 90 * 60)]") == ["just now", "3 h ago", "2 d ago", "", "90 min ago"]
    assert run("['WF', 'CX', 'RX', 'zz'].map(fireTypeName)") == ["wildfire", "complex", "prescribed burn", "fire"]


def test_nearest_and_hotspots_near():
    fl = "[{id:'A', lat:47.5, lon:-120.5, active:true}, {id:'B', lat:47.6, lon:-120.5, active:false}]"
    assert run("fireNearest(" + fl + ", 47.61, -120.5, 50, f => f.active).f.id") == "A"
    assert run("fireNearest(" + fl + ", 47.61, -120.5, 50).f.id") == "B"
    assert run("fireNearest(" + fl + ", 40, -120.5, 50)") is None
    assert run("Math.round(fireDist(47.5, -120.5, 47.51, -120.51) * 100) / 100") == pytest.approx(1.34, abs=0.05)
    rows = "[[47.5, -120.5, 1.0, 'V', 3, 'A', 0, null], [47.5, -120.5, 30, 'V', 3, 'A', 0, null], [48.5, -120.5, 1.0, 'G', 3, null, 1, null]]"
    assert run("hotsNear(" + rows + ", 47.51, -120.51, 10, 24)") == 1


def test_fires_data_reloads_after_15_minutes():
    assert run("fireNeedsLoad(null, 0, 1000)") is True
    assert run("fireNeedsLoad({}, 1000, 1000 + 15 * 60 * 1000)") is False
    assert run("fireNeedsLoad({}, 1000, 1000 + 15 * 60 * 1000 + 1)") is True


def test_panel_controls_are_saved_as_defaults():
    with open(os.path.join(ROOT, "map.html"), encoding="utf-8") as f:
        html = f.read()
    defs = re.search(r"const DEF_CHECKS = \[(.*?)\];", html).group(1)
    for k in ("lyFires", "fireQuiet", "lyHot"):
        assert "'%s'" % k in defs and 'id="%s"' % k in html
    assert html.index('data-grp="air"') < html.index('data-grp="fire"') < html.index('data-grp="hazards"')
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_map_fires.py -v`
Expected: FAIL (`AttributeError: 'NoneType' object has no attribute 'group'`: no block yet).

- [ ] **Step 3: Add the panel HTML**

In `map.html`, between the Air quality group's closing `</div>` (line 275) and `<div class="sec grp" data-grp="hazards">`, insert:

```html
  <div class="sec grp" data-grp="fire">
    <h2 class="grph"><span class="chev"></span>Smoke &amp; fires <span class="n"></span></h2>
    <div class="body">
    <label class="opt"><input type="checkbox" id="lyFires"> Fires
      <button type="button" class="help" aria-label="About the fires layer" aria-expanded="false">?</button>
      <span class="helptip" role="tooltip">Fires reported by US and Canadian agencies (NIFC, CWFIF, BC Wildfire Service). A fire is active when its agency updated it in the last 3 days, satellites saw heat on it in the last 24 h, or Canada lists it as out of control or being held; quiet fires are still listed by the agency, not out. Sizes and containment are the agencies' latest reports; perimeters come from mapping flights and can be days old. Grey: prescribed burns.</span></label>
    <div class="subwrap" data-for="lyFires">
      <div class="sub"><label class="opt" style="padding:0"><input type="checkbox" id="fireQuiet" checked> hide quiet fires</label></div>
      <div class="sub" id="fireInfo" style="display:block"></div>
    </div>

    <label class="opt"><input type="checkbox" id="lyHot"> Satellite hotspots
      <button type="button" class="help" aria-label="About satellite hotspots" aria-expanded="false">?</button>
      <span class="helptip" role="tooltip">Heat seen from satellites: NOAA GOES every few minutes (a pixel is about 2 km), NASA VIIRS and MODIS a few hours old (375 m to 1 km). A hotspot is heat, not a mapped fire edge. Includes prescribed burns and industrial or farm heat sources. Hollow: a GOES detection not yet tied to a known fire.</span></label>
    <div class="subwrap" data-for="lyHot">
      <div class="sub" id="hotInfo" style="display:block"></div>
    </div>
    </div>
  </div>
```

Add `'lyFires', 'fireQuiet', 'lyHot'` to `DEF_CHECKS` after `'lyAqGrid'`.

- [ ] **Step 4: Add the helpers block**

After `// END aqHelpers`, insert:

```js
  // ---------- Smoke & fires: helpers ----------
  // BEGIN fireHelpers (tests/test_map_fires.py runs this block under node)
  // colours and steps are judgment calls (spec ledger, 2026-09-28)
  const FIRE_COL = { WF: '#d1462f', CX: '#d1462f', RX: '#8a8f98' }, PERIM_COL = '#c0392b';
  const HOT_BINS = [[0, '#ff2d00'], [6, '#ff9a3c'], [24, '#c9a76b']], HOT_NAMES = ['< 6 h', '6–24 h', '24–48 h'];
  function fireSize(acres) { return acres == null || acres < 100 ? 0 : acres < 10000 ? 1 : 2; }   // marker size step
  function hotAge(h) { if (h == null || isNaN(h) || h > 48) return -1; return h < 6 ? 0 : h < 24 ? 1 : 2; }
  function fireEsc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])); }
  function fireAgo(t, nowS) {
    if (t == null) return '';
    const s = nowS - t;
    if (s < 60) return 'just now';
    const m = Math.round(s / 60);
    if (m < 120) return m + ' min ago';
    if (m < 36 * 60) return Math.round(m / 60) + ' h ago';
    return Math.round(m / 1440) + ' d ago';
  }
  function fireTypeName(t) { return t === 'WF' ? 'wildfire' : t === 'CX' ? 'complex' : t === 'RX' ? 'prescribed burn' : 'fire'; }
  function fireDist(lat1, lon1, lat2, lon2) { const r = Math.PI / 180, x = (lon2 - lon1) * Math.cos((lat1 + lat2) / 2 * r); return Math.sqrt(x * x + (lat2 - lat1) ** 2) * 111.2; }
  function fireNearest(list, lat, lon, maxKm, pred) {
    let best = null, bd = maxKm;
    for (const f of list || []) { if (pred && !pred(f)) continue; const d = fireDist(lat, lon, f.lat, f.lon); if (d <= bd) { bd = d; best = f; } }
    return best ? { f: best, km: bd } : null;
  }
  function hotsNear(rows, lat, lon, km, maxAgeH) { let n = 0; for (const h of rows || []) if (h[2] <= maxAgeH && fireDist(lat, lon, h[0], h[1]) <= km) n++; return n; }
  function fireNeedsLoad(d, loadedAtMs, nowMs) { return !d || nowMs - loadedAtMs > 15 * 60 * 1000; }
  // END fireHelpers
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_map_fires.py -v`
Expected: 6 passed.

- [ ] **Step 6: Commit**

```bash
git add map.html tests/test_map_fires.py
git commit -m "map: Smoke & fires panel section (Fires, hide quiet fires, Satellite hotspots) and fireHelpers block

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 7: Layers, labels, cards, hotspots, click-anywhere, terms

**Files:**
- Modify: `map.html` (after the fireHelpers block; the point panel near line 1384; `applyData` if the other layers refresh there)
- Modify: `terms.html:31-33` (add a fires credit bullet after the air-quality one)

**Interfaces:**
- Consumes: `FIRES` and `PERIMS` globals (Task 4 shapes), the Task 6 helpers and ids, `loadScript`, `legendHtml`, `$`, `map`, `bounds()`, `BASE`.
- Produces: `fireLayer`, `perimLayer`, `hotLayer` (Leaflet layer groups), `loadFires()`, `renderFires()`, `renderHot()`, `fireCard(f)`; a "Fires" block in the point panel.

- [ ] **Step 1: Add the layers**

After `// END fireHelpers`, insert:

```js
  // ---------- Smoke & fires: fires (markers, in-view labels, perimeters, cards) ----------
  const fireLayer = L.layerGroup(), fireLabelLayer = L.layerGroup(), perimLayer = L.layerGroup(), hotLayer = L.layerGroup();
  let fireData = null, fireLoadedAt = 0, fireLabels = [], perimData = null, perimLoadedAt = 0;
  function fireIcon(f) {
    const s = [14, 20, 28][fireSize(f.acres)] - (f.active ? 0 : 4), c = FIRE_COL[f.type] || FIRE_COL.WF;
    const svg = '<svg viewBox="0 0 24 24" width="' + s + '" height="' + s + '" style="opacity:' + (f.active ? 1 : .45) + '"><path d="M12 2c1 4 5 6 5 11a5 5 0 0 1-10 0c0-2 1-3 2-4 0 2 1 3 2 3 0-3-1-6 1-10z" fill="' + c + '" stroke="#222" stroke-width="1"/></svg>';
    return L.divIcon({ className: '', html: svg, iconSize: [s, s], iconAnchor: [s / 2, s], popupAnchor: [0, -s] });
  }
  function labelFires() {
    const show = map.hasLayer(fireLayer) && map.getZoom() >= 8, b = map.getBounds().pad(.1);
    for (const l of fireLabels) {
      const on = show && b.contains(l[0]);
      if (on && !l[2]) fireLabelLayer.addLayer(l[2] = L.marker(l[0], { interactive: false, keyboard: false, pane: 'tooltipPane', icon: L.divIcon({ className: '', html: '<div class="stlabel stlab">' + fireEsc(l[1]) + '</div>', iconSize: null }) }));
      else if (!on && l[2]) { fireLabelLayer.removeLayer(l[2]); l[2] = null; }
    }
  }
  map.on('moveend', labelFires);
  function fireCard(f) {
    const nowS = Date.now() / 1000, c = FIRE_COL[f.type] || FIRE_COL.WF;
    let h = '<div style="font:13px system-ui;min-width:240px;max-width:320px"><b>' + fireEsc(f.name) + '</b> <span style="background:' + c + ';color:#fff;padding:1px 6px;border-radius:3px;font-size:11px">' + fireTypeName(f.type) + '</span>' + (f.active ? '' : ' <span style="color:#666;font-size:11px">quiet</span>') +
      '<div style="color:#666">' + fireEsc([f.county, f.state].filter(Boolean).join(', ')) + (f.note ? ' · fire of note' : '') + '</div>';
    if (f.acres != null) {
      h += '<div style="margin:6px 0"><span style="font-size:20px;font-weight:700">' + Math.round(f.acres).toLocaleString() + '</span> acres' + (f.contained != null ? ', <b>' + f.contained + '%</b> contained' : '') + '</div>';
      if (f.contained != null) h += '<div style="height:5px;background:#eee;border-radius:3px"><div style="width:' + Math.min(100, f.contained) + '%;height:5px;background:#3f7d58;border-radius:3px"></div></div>';
    } else h += '<div style="margin:6px 0;color:#666">size not reported</div>';
    const rows = [];
    if (f.discovered) rows.push('discovered ' + new Date(f.discovered * 1000).toLocaleDateString([], { month: 'short', day: 'numeric' }));
    if (f.modified) rows.push('last update ' + fireAgo(f.modified, nowS));
    if (f.stage) rows.push(fireEsc(f.stage === 'OC' ? 'out of control' : f.stage === 'BH' ? 'being held' : f.stage === 'UC' ? 'under control' : f.stage));
    if (f.org) rows.push(fireEsc(f.org));
    if (f.behaviour) rows.push('behaviour ' + fireEsc(f.behaviour.toLowerCase()));
    if (f.personnel) rows.push(f.personnel.toLocaleString() + ' personnel');
    if (f.hot24) rows.push('<b>' + f.hot24 + '</b> hotspot' + (f.hot24 > 1 ? 's' : '') + ' in the last 24 h');
    if (f.perim && perimData) { const p = perimData.features.find(x => x.properties.id === f.id); if (p && p.properties.age_h != null) rows.push('perimeter mapped ' + fireAgo(nowS - p.properties.age_h * 3600, nowS)); }
    h += '<div style="margin-top:4px">' + rows.join(' · ') + '</div>';
    if (f.desc) h += '<div style="margin-top:4px;font-size:12px;max-height:80px;overflow:auto">' + fireEsc(f.desc) + '</div>';
    if (f.url) h += '<div style="margin-top:4px;font-size:12px"><a href="' + fireEsc(f.url) + '" target="_blank" rel="noopener">agency page</a></div>';
    h += '<div style="font-size:11px;color:#666;margin-top:4px">Source: ' + (f.src === 'wfigs' ? 'NIFC (WFIGS)' : 'CWFIF (Natural Resources Canada)' + (f.bcws ? ', BC Wildfire Service' : '')) + '.</div></div>';
    return h;
  }
  function renderPerims() {
    perimLayer.clearLayers();
    if (!perimData || !map.hasLayer(fireLayer)) return;
    L.geoJSON(perimData, { style: () => ({ color: PERIM_COL, weight: 1.5, fillOpacity: .12 }), interactive: true,
      onEachFeature: (ft, l) => { const p = ft.properties; l.bindTooltip(fireEsc(p.name) + (p.acres ? ' · ' + Math.round(p.acres).toLocaleString() + ' ac' : '') + (p.age_h != null ? ' · mapped ' + fireAgo(Date.now() / 1000 - p.age_h * 3600, Date.now() / 1000) : ''), { sticky: true }); } }).addTo(perimLayer);
  }
  function renderFires() {
    fireLayer.clearLayers(); fireLabelLayer.clearLayers(); fireLayer.addLayer(perimLayer); fireLayer.addLayer(fireLabelLayer); fireLabels = [];
    if (!fireData) return;
    const hideQuiet = $('fireQuiet').checked; let n = 0, na = 0, nrx = 0;
    for (const f of fireData.fires) {
      if (f.active) na++; if (f.type === 'RX') nrx++;
      if (hideQuiet && !f.active) continue;
      n++;
      const m = L.marker([f.lat, f.lon], { icon: fireIcon(f), zIndexOffset: f.active ? 200 : 0 });
      m.bindPopup(() => fireCard(f), { maxWidth: 340 });
      m.on('mouseover', () => { if (!m.isPopupOpen()) m.openPopup(); });
      fireLayer.addLayer(m);
      if (f.active) fireLabels.push([m.getLatLng(), f.name, null]);
    }
    renderPerims(); labelFires();
    $('fireInfo').innerHTML = '<div class="muted">' + na + ' active of ' + fireData.fires.length + ' · ' + nrx + ' prescribed' + (hideQuiet ? '' : ' · showing ' + n) + ' · updated ' + fireData.updated + '</div>' +
      '<div class="note">Fires reported by US and Canadian agencies (NIFC, CWFIF, BC Wildfire Service). Sizes and containment are the agencies\' latest reports; perimeters come from mapping flights and can be days old. Grey: prescribed burns; faded: quiet.</div>';
  }
  function loadPerims() { loadScript('data/perimeters.js', () => { perimData = window.PERIMS || perimData; perimLoadedAt = Date.now(); renderPerims(); }, () => {}); }
  function loadFires() {
    loadScript('data/fires.js', () => {
      fireData = window.FIRES || fireData; fireLoadedAt = Date.now();
      if (map.hasLayer(fireLayer)) { renderFires(); if (fireNeedsLoad(perimData, perimLoadedAt, Date.now())) loadPerims(); }
      if (map.hasLayer(hotLayer)) renderHot();
    }, () => { $('fireInfo').innerHTML = $('hotInfo').innerHTML = '<div class="muted">fire data not available yet</div>'; });
  }
  $('lyFires').onchange = e => { if (e.target.checked) { fireLayer.addTo(map); if (fireNeedsLoad(fireData, fireLoadedAt, Date.now())) loadFires(); else { renderFires(); if (fireNeedsLoad(perimData, perimLoadedAt, Date.now())) loadPerims(); } } else map.removeLayer(fireLayer); };
  $('fireQuiet').onchange = () => { if (map.hasLayer(fireLayer)) renderFires(); };
  // ---------- Smoke & fires: satellite hotspots ----------
  function renderHot() {
    hotLayer.clearLayers();
    if (!fireData) return;
    const byId = {}; for (const f of fireData.fires) byId[f.id] = f;
    let n = 0, ng = 0;
    for (const h of fireData.hotspots) {
      const a = hotAge(h[2]); if (a < 0) continue;
      n++; if (h[3] === 'G') ng++;
      const m = L.circleMarker([h[0], h[1]], { radius: h[3] === 'G' ? 4 : 3, color: HOT_BINS[a][1], weight: 1.2, fillColor: HOT_BINS[a][1], fillOpacity: h[6] ? 0 : .8 });
      const f = h[5] && byId[h[5]];
      m.bindTooltip((h[3] === 'G' ? 'GOES' : h[3] === 'V' ? 'VIIRS' : 'MODIS') + ' · ' + (h[2] < 1 ? Math.round(h[2] * 60) + ' min' : h[2].toFixed(1) + ' h') + ' ago' + (h[4] != null ? ' · ' + h[4] + ' MW' : '') +
        (h[7] ? ' · seen since ' + new Date(h[7] * 1000).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }) : '') + (f ? ' · ' + fireEsc(f.name) : h[6] ? ' · not yet tied to a known fire' : ''), { sticky: true });
      hotLayer.addLayer(m);
    }
    $('hotInfo').innerHTML = '<div class="muted">' + n + ' hotspots (' + ng + ' GOES) · updated ' + fireData.updated + '</div>' + legendHtml(HOT_BINS, x => HOT_NAMES[HOT_BINS.findIndex(b => b[0] === x)]) +
      '<div class="note">' + (fireData.ngfs ? 'NOAA GOES (NGFS, every few minutes; beta) and ' : 'NOAA GOES unavailable; ') + 'NASA VIIRS and MODIS (FIRMS, a few hours old). Heat, not a fire edge; includes prescribed burns and industrial or farm sources. Hollow: GOES detection not yet tied to a known fire.</div>';
  }
  $('lyHot').onchange = e => { if (e.target.checked) { hotLayer.addTo(map); if (fireNeedsLoad(fireData, fireLoadedAt, Date.now())) loadFires(); else renderHot(); } else map.removeLayer(hotLayer); };
  setInterval(() => { if (map.hasLayer(fireLayer) || map.hasLayer(hotLayer)) loadFires(); }, 15 * 60 * 1000);
```

- [ ] **Step 2: Add the click-anywhere block**

In the point panel, after the air-quality block (`if (rows.length) sec.push('<div style="margin-top:6px;color:#666">Air quality</div>' + rows.join('')); }`), insert:

```js
    // fires: nearest active fire within 50 km and hotspots within 10 km in 24 h (judgment calls, spec ledger)
    await new Promise(res => !fireNeedsLoad(fireData, fireLoadedAt, Date.now()) ? res() : loadScript('data/fires.js', () => { fireData = window.FIRES || fireData; fireLoadedAt = Date.now(); res(); }, res));
    if (fireData) {
      const rows = [], nf = fireNearest(fireData.fires, ll.lat, ll.lng, 50, f => f.active);
      if (nf) rows.push('<div>' + fireEsc(nf.f.name) + ' <span style="color:#666">(' + nf.km.toFixed(0) + ' km, ' + fireTypeName(nf.f.type) + ')</span>: ' + (nf.f.acres != null ? '<b>' + Math.round(nf.f.acres).toLocaleString() + ' ac</b>' : 'size not reported') + (nf.f.contained != null ? ', ' + nf.f.contained + '% contained' : '') + '</div>');
      const nh = hotsNear(fireData.hotspots, ll.lat, ll.lng, 10, 24);
      if (nh) rows.push('<div><b>' + nh + '</b> satellite hotspot' + (nh > 1 ? 's' : '') + ' within 10 km in the last 24 h</div>');
      if (rows.length) sec.push('<div style="margin-top:6px;color:#666">Fires</div>' + rows.join(''));
    }
```

- [ ] **Step 3: Terms**

In `terms.html`, after the air-quality bullet, add:

```html
  <li>Fire locations, sizes and perimeters come from the National Interagency Fire Center (WFIGS), Natural Resources
    Canada's Canadian Wildland Fire Information System (Open Government Licence – Canada) and the BC Wildfire Service
    (Open Government Licence – British Columbia). Satellite hotspots: we acknowledge the use of data from NASA's Fire
    Information for Resource Management System (FIRMS), part of EOSDIS, and NOAA's Next Generation Fire System (beta,
    provided as is). Hotspots are heat detections, not verified fires.</li>
```

- [ ] **Step 4: Run every test**

Run: `python -m pytest tests/ -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add map.html terms.html
git commit -m "map: fire markers, in-view labels, perimeters, cards; satellite hotspots by age; nearest fire in the point panel; terms credits

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 8: Local browser check, docs, handoff, release

**Files:**
- Modify: `CLAUDE.md` (radar): the "What lives here" layer list, the `capture.yml` row, globals, a "Fires" rule paragraph after the Air quality one, the timeline.
- Modify: `../radar/HANDOFF.md` item 7 (untracked; lives in the main checkout).

- [ ] **Step 1: Build and preview locally**

From the worktree (PowerShell): `Copy-Item ..\radar\web .\web -Recurse -Force` (if not done), then `python build_web.py`, then start `python smoke_research/fires_serve.py` in the background and open `http://127.0.0.1:8796/?r=pnw` in the in-app browser. Turn on Fires: markers, labels at zoom 8, a card with a link, perimeters and their tooltips, "hide quiet fires" off then on. Turn on Satellite hotspots: colours by age, hollow GOES points, tooltips. Click anywhere near a fire: the Fires block. Phone width (`resize_window` mobile): the panel section reads. `read_console_messages` must show no errors. Fix and re-check anything wrong. Screenshot for Chris.

- [ ] **Step 2: Docs**

`CLAUDE.md` (radar), keep each change to one or two lines:
- "What lives here": add "fires (WFIGS, CWFIF, BCWS incidents and perimeters), satellite hotspots (FIRMS, NGFS)" to the layer list.
- `capture.yml` row: add "fires (`fires.py`)".
- Globals: add `FIRES`, `PERIMS`.
- After the Air quality rule: "Fires (`fires.py`, 15-minute job): every current agency fire, styled by activity (spec ledger); perimeters refetched only when the ArcGIS edit stamp changes; hotspots from FIRMS 48 h + NGFS 24 h (newest detection per tracked feature; unconfirmed shown hollow). State `fires_cache.json`. Check: `python smoke_research/fires_check.py <region>`; preview `smoke_research/fires_serve.py` (port 8796). Spec: `docs/superpowers/specs/2026-09-28-fires-layer-design.md`."
- Timeline: "2026-09-28: Smoke & fires section, phase 2 (fires, perimeters, hotspots); spec `docs/superpowers/specs/2026-09-28-fires-layer-design.md`."

`git diff CLAUDE.md` first is unnecessary in the worktree (it starts clean), but the merge in Step 4 must keep the other sessions' hunks in `../radar/CLAUDE.md`: merge before they commit, or rebase after; ask Chris which.

```bash
git add CLAUDE.md
git commit -m "CLAUDE.md: fires layer (job, globals, rules, timeline)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

- [ ] **Step 3: Whole-branch review**

Invoke `superpowers:requesting-code-review` on `fires` vs `main` (Chris's execution choice decides whether reviewers ran per task). Fix findings, re-run `python -m pytest tests/ -q`, commit.

- [ ] **Step 4: Merge and release (Chris)**

Invoke `superpowers:finishing-a-development-branch`. Expected path: merge `fires` into `main` in `../radar` (`git merge --no-ff fires`), which leaves other sessions' uncommitted edits alone unless they touch `CLAUDE.md` or `capture.py`; if `git merge` reports a conflict, resolve it keeping both sides' lines. Then in `../radar`: `python build_web.py`, hand Chris `git push origin main` and `npx --yes wrangler deploy` from `C:/Users/16035/Desktop/BlackwaterLabs/radar` as Run-button blocks, curl `https://radar.blackwaterlabs.org/` and diff against `web/index.html`, and read the next two capture runs' `fires:` lines for all five regions (Actions log). Update `HANDOFF.md` item 7 with the commit, deploy version and first-run counts; remove the worktree (`git worktree remove ../radar-fires`) once merged.
