"""Tides and tidal currents (tides.py): CO-OPS and CHS parsing, refresh planning, output (no network)."""
import calendar
import json
import os
import time
import urllib.error

import pytest

import tides

FX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "coastal")
BBOX = (43.07, 52.48, -126.56, -112.5)
NOW = calendar.timegm((2026, 10, 13, 20, 30, 0))          # 2026-10-13 20:30 UTC (13:30 PDT)


def fx(name):
    with open(os.path.join(FX, name), "rb") as f:
        return f.read()


def utc(s):
    return calendar.timegm(time.strptime(s, "%Y-%m-%d %H:%M"))


# ---------- metadata ----------
def test_coops_meta_window_and_sensors():
    wl = tides.parse_coops_stations(fx("coops_stations_waterlevels.json"), "waterlevels", BBOX)
    by = {s["id"]: s for s in wl}
    assert set(by) == {"9441102", "9447130"}                  # San Francisco is outside the window
    w = by["9441102"]
    assert (w["name"], w["src"]) == ("Westport", "COOPS")
    assert w["lat"] == pytest.approx(46.90431) and w["lon"] == pytest.approx(-124.10508)
    assert set(w["sensors"]) == {"wl", "wind", "wtemp"}
    assert by["9447130"]["sensors"] == ["wl"]                  # Seattle: water level only
    for s in wl:
        assert {"id", "name", "lat", "lon", "src", "sensors"} <= set(s)

    tp = {s["id"]: s for s in tides.parse_coops_stations(fx("coops_stations_tidepredictions.json"),
                                                            "tidepredictions", BBOX)}
    assert set(tp) == {"9439040", "9449211"}
    assert tp["9439040"]["kind"] == "harmonic" and tp["9449211"]["kind"] == "subordinate"

    cp = tides.parse_coops_stations(fx("coops_stations_currentpredictions.json"), "currentpredictions", BBOX)
    assert [c["id"] for c in cp] == ["PUG1701"]                # PCT1371 is "weak and variable", SFB1203 outside
    assert cp[0]["bin"] == 33 and cp[0]["bin_depth_ft"] == 18.0  # the shallowest bin


def test_chs_stations_split_tides_and_currents():
    tide, cur = tides.parse_chs_stations(fx("chs_stations.json"), BBOX)
    assert [s["id"] for s in tide] == ["08615"]                # Prince Rupert is north of the window
    t = tide[0]
    assert t["name"] == "Tofino" and t["src"] == "CHS" and t["datum"] == "CD"
    assert t["chs_id"] == "5cebf1e23d0f4a073c4bc07c" and t["live"] is True
    assert [c["id"] for c in cur] == ["07090"] and cur[0]["chs_id"] == "63aeee896a2b9417c034d337"


# ---------- predictions and observations ----------
def test_hilo_times_are_utc_epoch():
    h = tides.parse_hilo(fx("coops_hilo_9439040.json"))
    assert len(h) == 12
    assert h[4] == [1791866100, -0.78, "L"]                    # "2026-10-13 04:35" gmt, ft as given (units=english)
    assert h[4][0] == utc("2026-10-13 04:35")
    assert h[1] == [utc("2026-10-12 10:10"), 7.55, "H"]
    assert all(a[0] < b[0] for a, b in zip(h, h[1:]))


def test_hilo_error_raises():
    with pytest.raises(ValueError):
        tides.parse_hilo(b'{"error": {"message": "No Predictions data was found."}}')


def test_wl_last_12h_30min():
    obs = tides.parse_wl(fx("coops_wl_9447130.json"))
    ts = [t for t, _ in obs]
    assert ts[-1] == utc("2026-10-13 20:00")
    assert ts[0] >= utc("2026-10-13 20:24") - 12 * 3600
    assert all(t % 1800 == 0 for t in ts)
    assert all(b - a == 1800 for a, b in zip(ts, ts[1:]))
    assert dict(obs)[utc("2026-10-13 09:00")] == 0.55
    assert tides.latest_wl(fx("coops_wl_9447130.json")) == (utc("2026-10-13 20:24"), 6.45)


def test_maxslack_events_kt():
    ev = tides.parse_maxslack(fx("coops_maxslack_PUG1701.json"))
    assert ev[0] == [utc("2026-10-13 00:23"), "slack", 0.0]
    assert ev[1] == [utc("2026-10-13 03:22"), "ebb", 6.47]
    assert ev[3] == [utc("2026-10-13 10:48"), "flood", 4.78]
    assert tides.current_dirs(fx("coops_maxslack_PUG1701.json")) == (108, 277)
    # the same table in metric units (cm/s) comes out in knots
    d = json.loads(fx("coops_maxslack_PUG1701.json"))
    d["current_predictions"]["units"] = "meters, cm/s"
    for r in d["current_predictions"]["cp"]:
        r["Velocity_Major"] = r["Velocity_Major"] * 51.444
    ev2 = tides.parse_maxslack(json.dumps(d).encode())
    assert ev2[1][2] == pytest.approx(6.47, abs=0.01)


def test_chs_metres_to_feet_and_datum():
    h = tides.parse_chs_hilo(fx("chs_wlp_hilo.json"))
    assert h[4] == [utc("2026-10-13 03:45"), round(0.52 * 3.28084, 2), "L"]
    assert h[5] == [utc("2026-10-13 10:05"), round(3.156 * 3.28084, 2), "H"]
    assert [x[2] for x in h[:4]] == ["L", "H", "L", "H"]
    obs = tides.parse_chs_wl(fx("chs_wlo.json"))
    assert obs[-1] == [utc("2026-10-13 20:00"), round(3.127 * 3.28084, 2)]
    assert all(t % 1800 == 0 for t, _ in obs)
    ev = tides.parse_chs_events(fx("chs_wcp1_events.json"))
    assert ev[0] == [utc("2026-10-13 00:28"), "slack", 0.0]
    assert ev[1] == [utc("2026-10-13 03:51"), "ebb", 4.96]     # CHS current speeds are knots (phenomenon "wcs": kn)
    assert ev[3][1] == "flood"


# ---------- refresh planning ----------
def test_refresh_plan_limits_and_prefers_stale():
    stations = [{"id": "S%03d" % i, "src": "COOPS", "kind": "harmonic"} for i in range(100)]
    pred = {"S%03d" % i: {"day": "2026-10-12", "fetched": NOW - 86400 - (1000 - i) * 60, "hilo": []}
            for i in range(100)}
    stations += [{"id": "FRESH", "src": "COOPS", "kind": "harmonic"}, {"id": "OBS", "src": "COOPS", "kind": "obs"}]
    pred["FRESH"] = {"day": "2026-10-13", "fetched": NOW - 600, "hilo": []}
    cache = {"meta": {"stations": stations, "currents": [{"id": "PUG1701", "src": "COOPS"}]}, "pred": pred, "cur": {}}
    plan = tides.refresh_plan(cache, NOW, limit=60)
    assert len(plan) == 60
    assert plan[0] == "PUG1701"                                # never fetched comes first
    assert plan[1:] == ["S%03d" % i for i in range(59)]        # then the oldest
    assert "FRESH" not in plan and "OBS" not in plan
    # first run: nothing cached; current stations are not starved behind hundreds of tide stations
    cache = {"meta": {"stations": stations, "currents": [{"id": "PUG1701", "src": "COOPS"}]}, "pred": {}, "cur": {}}
    plan = tides.refresh_plan(cache, NOW, limit=3)
    assert plan == ["PUG1701", "S000", "S001"]


# ---------- the whole run ----------
def serve(calls):
    def fetch(url, timeout=None):
        calls.append(url)
        if "mdapi" in url:
            kind = url.split("type=")[1].split("&")[0]
            return fx("coops_stations_%s.json" % kind)
        if url.endswith("/api/v1/stations"):
            return fx("chs_stations.json")
        if "datagetter" in url:
            if "product=predictions" in url:
                return fx("coops_hilo_9439040.json")
            if "product=water_level" in url:
                return fx("coops_wl_9447130.json")
            if "product=currents_predictions" in url:
                return fx("coops_maxslack_PUG1701.json")
            return b'{"error": {"message": "No data was found."}}'
        if "time-series-code=wlp-hilo" in url:
            return fx("chs_wlp_hilo.json")
        if "time-series-code=wlo" in url:
            return fx("chs_wlo.json")
        if "time-series-code=wcp1-events" in url:
            return fx("chs_wcp1_events.json")
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
    return fetch


@pytest.fixture
def job(tmp_path, monkeypatch):
    monkeypatch.setattr(tides, "OUT", str(tmp_path / "tides.js"))
    monkeypatch.setattr(tides, "CACHE", str(tmp_path / "tides_cache.json"))
    monkeypatch.setattr(tides, "SLEEP_S", 0)
    monkeypatch.setattr(tides.region, "bbox", lambda: BBOX)
    monkeypatch.setitem(tides.region.cfg(), "coastal", True)
    calls = []
    monkeypatch.setattr(tides, "fetch", serve(calls))
    return tmp_path, calls


def read_out(path):
    text = open(path, encoding="utf-8").read()
    assert text.startswith("window.TIDES = ") and text.rstrip().endswith(";")
    return json.loads(text[len("window.TIDES = "):].rstrip().rstrip(";"))


def test_hilo_only_station_has_no_obs(job):
    tmp, calls = job
    tides.build(log=lambda *a: None, now=NOW)
    out = read_out(tmp / "tides.js")
    by = {s["id"]: s for s in out["stations"]}
    b = by["9449211"]                                          # Bellingham, subordinate: hi/lo only
    assert b["kind"] == "subordinate" and b["obs"] is None and b["hilo"]
    assert not any("9449211" in u and "water_level" in u for u in calls)
    assert all("interval=hilo" in u for u in calls if "product=predictions" in u)


def test_output_shape(job):
    tmp, calls = job
    n = tides.build(log=lambda *a: None, now=NOW)
    out = read_out(tmp / "tides.js")
    assert n == len(out["stations"]) > 0
    assert isinstance(out["updated"], str) and out["updated_t"] > 0
    by = {s["id"]: s for s in out["stations"]}
    a = by["9439040"]
    assert a["src"] == "COOPS" and a["datum"] == "MLLW" and a["kind"] == "harmonic"
    assert a["link"].startswith("https://tidesandcurrents.noaa.gov/")
    hs = [h[0] for h in a["hilo"]]
    inside = [t for t in hs if NOW - 12 * 3600 <= t <= NOW + 36 * 3600]
    assert inside and hs[0] <= NOW - 12 * 3600 and len(hs) - len(inside) <= 2   # one extreme past each edge
    s = by["9447130"]                                          # Seattle: live, no predictions in this fixture
    assert s["kind"] == "obs" and s["obs"] and s["wl_ft"] == 6.45 and s["wl_t"] == utc("2026-10-13 20:24")
    t = by["08615"]
    assert t["src"] == "CHS" and t["datum"] == "CD" and t["hilo"] and t["obs"]
    cur = {c["id"]: c for c in out["currents"]}
    d = cur["PUG1701"]
    assert d["bin_depth_ft"] == 18.0 and (d["flood_dir"], d["ebb_dir"]) == (108, 277)
    assert d["events"] and all(e[1] in ("slack", "flood", "ebb") for e in d["events"])
    assert cur["07090"]["src"] == "CHS" and cur["07090"]["events"]
    # the cache carries what buoys.py needs and today's predictions
    cache = json.load(open(tmp / "tides_cache.json", encoding="utf-8"))
    assert cache["meta"]["fetched"] == NOW
    w = [m for m in cache["meta"]["stations"] if m["id"] == "9441102"][0]
    assert set(w["sensors"]) == {"wl", "wind", "wtemp"}
    assert cache["pred"]["9439040"]["day"] == "2026-10-13"
    assert cache["cur"]["PUG1701"]["events"]
    # a second run the same day reuses the cache: no metadata or prediction requests
    calls.clear()
    tides.build(log=lambda *a: None, now=NOW + 1800)
    assert not any("mdapi" in u or "product=predictions" in u or "wlp-hilo" in u for u in calls)


def test_not_coastal_returns_zero(job, monkeypatch):
    tmp, calls = job
    monkeypatch.setitem(tides.region.cfg(), "coastal", False)
    assert tides.build(log=lambda *a: None, now=NOW) == 0
    assert calls == [] and not os.path.exists(tmp / "tides.js")


def test_code_that_is_tide_and_current_station_gets_both(job, monkeypatch):
    tmp, calls = job
    st = {"id": "07724", "chs_id": "x", "name": "Both", "lat": 49.0, "lon": -123.0, "src": "CHS", "kind": "harmonic",
          "datum": "CD", "live": False}
    cache = {"meta": {"fetched": NOW, "stations": [st], "currents": [dict(st)]}, "pred": {}, "cur": {}}
    tides.save_cache(cache)
    got = []

    def fake(rec, is_current, now):
        got.append(is_current)
        return {"events": [[NOW + 3600, "slack", 0.0]]} if is_current else {"hilo": [[NOW + 3600, 3.0, "H"]]}
    monkeypatch.setattr(tides, "fetch_pred", fake)
    tides.build(log=lambda *a: None, now=NOW)
    assert sorted(got) == [False, True]
    out = read_out(tmp / "tides.js")
    assert out["stations"][0]["hilo"] and out["currents"][0]["events"]
