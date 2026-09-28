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
