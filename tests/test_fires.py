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
