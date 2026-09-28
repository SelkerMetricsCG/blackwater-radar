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
