"""Buoys and shore stations (buoys.py): NDBC, CDIP, ECCC SWOB-ML, NANOOS / Backyard Buoys ERDDAP, CO-OPS (no network)."""
import calendar
import json
import os
import urllib.error

import pytest

import buoys

FX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "coastal")
BBOX = (43.07, 52.48, -126.56, -112.5)          # region.bbox() for pnw: lat0, lat1, lon0, lon1


def fx(name):
    with open(os.path.join(FX, name), "rb") as f:
        return f.read()


def txt(name):
    return fx(name).decode("utf-8")


def utc(y, mo, d, h, mi=0):
    return calendar.timegm((y, mo, d, h, mi, 0))


NOW = utc(2026, 10, 13, 21, 0)
T46041 = utc(2026, 10, 13, 20, 30)


def by_id(stations):
    return {s["id"]: s for s in stations}


def test_latest_obs_window_filter_and_units():
    recs = buoys.parse_latest_obs(txt("latest_obs_excerpt.txt"), BBOX)
    assert "46041" in recs and "46026" not in recs          # 46026 San Francisco is outside the window
    r = recs["46041"]
    assert r["t"] == T46041
    assert (r["lat"], r["lon"]) == (47.351, -124.741)
    assert r["wspd_mph"] == 8.9 and r["gust_mph"] == 11.2 and r["wdir_deg"] == 150    # 4.0 / 5.0 m/s
    assert r["wtmp_f"] == 53.8 and r["atmp_f"] == 54.3                                # 12.1 / 12.4 C
    assert r["pres_mb"] == 1023.1
    assert r.get("hs_ft") is None                                                     # WVHT MM
    w = recs["46050"]
    assert w["hs_ft"] == 4.3 and w["dpd_s"] == 15 and w["apd_s"] == 8.3 and w["mwd_deg"] == 280   # 1.3 m
    assert w.get("wdir_deg") is None and w["wspd_mph"] == 0.0


def test_latest_obs_mm_waves_filled_from_history():
    latest = buoys.parse_latest_obs(txt("latest_obs_excerpt.txt"), BBOX)
    rows = buoys.parse_realtime(txt("46041.txt"))
    s = by_id(buoys.merge(latest, realtime={"46041": rows}, now=NOW))["46041"]
    # latest_obs has MM in every wave column; the newest wave row of the history (20:20, 1.3 m) fills them
    assert s["hs_ft"] == 4.3 and s["dpd_s"] == 11 and s["apd_s"] == 7.3 and s["mwd_deg"] == 288
    assert s["wspd_mph"] == 8.9 and s["wtmp_f"] == 53.8        # wind and water temperature still there
    assert s["t"] == T46041 and s["src"] == "NDBC"


def test_realtime_rows_newest_first_and_trace_24h():
    rows = buoys.parse_realtime(txt("46041.txt"))
    assert len(rows) == 30
    assert rows[0]["t"] == T46041 and all(a["t"] > b["t"] for a, b in zip(rows, rows[1:]))
    assert rows[0]["hs_ft"] is None and rows[1]["hs_ft"] == 4.3 and rows[1]["dpd_s"] == 11
    assert rows[0]["wspd_mph"] == 8.9 and rows[0]["pres_mb"] == 1023.1 and rows[0]["wtmp_f"] == 53.8
    trace, t0 = buoys.hourly_trace(rows)
    assert len(trace) == 24
    assert t0 == utc(2026, 10, 13, 20) - 23 * 3600              # ends at the hour of the newest wave row
    assert trace[23] == 4.3                                    # 20:20 row
    assert trace[22] == 5.2                                    # 19:50 row (newest in its hour)
    assert trace[18] == 4.6                                    # 15:50 row
    assert trace[0] is None and trace[17] is None              # hours not in the excerpt


def test_spec_swell_split():
    s = buoys.parse_spec(txt("46041.spec"))
    assert s["t"] == utc(2026, 10, 13, 20, 10)
    assert s["swh_ft"] == 3.9 and s["swp_s"] == 11.4 and s["swd_deg"] == 293     # 1.2 m, WNW
    assert s["wwh_ft"] == 1.3 and s["wwp_s"] == 3.2 and s["wwd_deg"] == 180      # 0.4 m, S
    assert s["steep"] == "SWELL"
    head = "\n".join(txt("46041.spec").splitlines()[:2])
    mm = buoys.parse_spec(head + "\n2026 10 13 20 10  1.3   MM   MM  0.4  3.2  MM   S        N/A  7.3 288\n")
    assert mm["swh_ft"] is None and mm["swp_s"] is None and mm["swd_deg"] is None and mm["steep"] is None
    assert mm["wwh_ft"] == 1.3


def test_cdip_overwrites_relay_direction():
    latest = buoys.parse_latest_obs(txt("latest_obs_excerpt.txt"), BBOX)
    csv_text = txt("cdip_wave_agg.csv").replace("263.90625", "291.0")      # make CDIP's Dp differ from the relay's 264
    cdip = buoys.parse_cdip(csv_text)
    assert cdip["036"]["t"] == utc(2026, 10, 13, 20) and cdip["036"]["dpd_s"] == 15.4 and cdip["036"]["apd_s"] == 7.7
    s = by_id(buoys.merge(latest, cdip=cdip, now=NOW))["46211"]
    assert s["mwd_deg"] == 291 and s["hs_ft"] == 3.5 and s["dpd_s"] == 15.4       # 1.08 m; relay said 1.1 m, 15 s, 264
    assert s["src"] == "CDIP" and s["credit"] == "Data courtesy of CDIP"
    assert "036p1" in s["link"]
    # a CDIP row much older than the relay row does not overwrite it (CDIP's ERDDAP lagged the relay on 2026-10-13)
    old = {"036": dict(cdip["036"], t=utc(2026, 10, 13, 16, 30), mwd_deg=200)}
    s = by_id(buoys.merge(latest, cdip=old, now=NOW))["46211"]
    assert s["mwd_deg"] == 264 and s["hs_ft"] == 3.6 and s["credit"] == "Data courtesy of CDIP"


def test_eccc_swob_period_and_direction():
    e = buoys.parse_swob(txt("eccc_4600206.xml"))
    assert e["id"] == "4600206" and e["t"] == utc(2026, 10, 13, 20, 5)
    assert e["hs_ft"] == 5.6 and e["dpd_s"] == 13.3 and e["mwd_deg"] == 273 and e["apd_s"] == 5.0
    assert e["wspd_mph"] == 24.2 and e["gust_mph"] == 28.6 and e["wdir_deg"] == 121          # km/h
    assert e["wtmp_f"] == 52.9 and e["pres_mb"] == 1020.5
    latest = buoys.parse_latest_obs(txt("latest_obs_excerpt.txt"), BBOX)
    assert latest["46206"]["dpd_s"] == 6 and latest["46206"].get("mwd_deg") is None   # NDBC relay: wrong period, no direction
    s = by_id(buoys.merge(latest, eccc={"4600206": e}, now=NOW))["46206"]
    assert s["dpd_s"] == 13.3 and s["mwd_deg"] == 273
    assert s["src"] == "ECCC" and s["credit"] == "Data Source: Environment and Climate Change Canada"


def test_nanoos_and_byb_records():
    cfg = {st["id"]: st for st in buoys.NANOOS_STATIONS}
    chaba = cfg["46119"]
    met = buoys.parse_erddap(txt("nanoos_chaba_met.json"), chaba["datasets"][0][2])
    hydro = buoys.parse_erddap(txt("nanoos_chaba_hydro.json"), chaba["datasets"][1][2])
    assert met["wspd_mph"] == 17.3 and met["gust_mph"] == 20.5 and met["wdir_deg"] == 296    # 7.7486 / 9.158 m/s
    assert met["t"] == utc(2026, 10, 13, 19, 50) + 42
    assert hydro["wtmp_f"] == 55.3                                                           # 12.9419 C
    rec = buoys.nanoos_record(chaba, [met, hydro])
    latest = buoys.parse_latest_obs(txt("latest_obs_excerpt.txt"), BBOX)
    s = by_id(buoys.merge(latest, others=[rec], now=NOW))["46119"]
    assert s["name"] == "Cha'ba (La Push)" and s["src"] == "NANOOS"
    assert s["credit"] == "NANOOS / UW Applied Physics Laboratory"
    assert s["wspd_mph"] == 17.3 and s["wtmp_f"] == 55.3
    byb = cfg["byb_quileute_center"]
    w = buoys.parse_erddap(txt("nanoos_byb_quileute.json"), byb["datasets"][0][2])
    assert w["hs_ft"] == 4.0 and w["dpd_s"] == 11.4 and w["apd_s"] == 9.1 and w["mwd_deg"] == 281   # 1.22 m
    assert w["wtmp_f"] == 51.8                                                                      # 11.02 C
    r = buoys.nanoos_record(byb, [w])
    assert r["src"] == "BYB" and r["lat"] == 47.8412
    assert r["credit"] == "Quileute Tribe / Quinault Indian Nation (Backyard Buoys, CC BY-NC 4.0)"


def test_coops_wind_and_wtemp_station():
    wind = buoys.parse_coops(txt("coops_wind_9441102.json"))
    wt = buoys.parse_coops(txt("coops_wtemp_9441102.json"))
    assert wind["wspd_mph"] == 9.0 and wind["gust_mph"] == 11.2 and wind["wdir_deg"] == 198      # 7.78 / 9.72 kt
    assert wind["t"] == utc(2026, 10, 13, 20, 48) and wt["wtmp_f"] == 53.1
    assert buoys.parse_coops('{"error": {"message": "No data was found."}}') == {}
    meta = buoys.coops_sensor_stations(txt("coops_stations_waterlevels.json"), BBOX)
    assert [m["id"] for m in meta] == ["9441102"]          # San Francisco outside; Seattle has neither sensor
    assert set(meta[0]["sensors"]) >= {"wind", "wtemp"}
    table = buoys.parse_station_table(txt("station_table_excerpt.txt"))
    rec = buoys.coops_record(meta[0], [wind, wt], table)
    assert rec["ndbc"] == "WPTW1"
    latest = buoys.parse_latest_obs(txt("latest_obs_excerpt.txt"), BBOX)
    st = by_id(buoys.merge(latest, others=[rec], table=table, now=NOW))
    assert "WPTW1" not in st                                # the NDBC relay of the same gauge is folded in
    s = st["9441102"]
    assert s["src"] == "COOPS" and s["wspd_mph"] == 9.0 and s["wtmp_f"] == 53.1
    assert s["atmp_f"] == 55.8                              # air temperature only in the relay row
    assert s["credit"] is None and "9441102" in s["link"]


def test_stale_and_drop():
    latest = buoys.parse_latest_obs(txt("latest_obs_excerpt.txt"), BBOX)
    assert "stale" not in by_id(buoys.merge(latest, now=NOW))["46041"]
    assert by_id(buoys.merge(latest, now=T46041 + 7 * 3600))["46041"]["stale"] is True
    assert "46041" not in by_id(buoys.merge(latest, now=T46041 + 25 * 3600))
    assert buoys.STALE_H == 6 and buoys.DROP_H == 24


def test_output_shape(tmp_path, monkeypatch):
    monkeypatch.setattr(buoys, "DATA", str(tmp_path))
    monkeypatch.setattr(buoys, "OUT", str(tmp_path / "buoys.js"))
    monkeypatch.setattr(buoys.time, "sleep", lambda s: None)
    cache = {"meta": {"fetched": NOW, "stations": [
        {"id": "9441102", "name": "Westport", "lat": 46.9043, "lon": -124.1051, "src": "COOPS",
         "sensors": ["wl", "wind", "wtemp"]}]}}
    (tmp_path / "tides_cache.json").write_text(json.dumps(cache), encoding="utf-8")
    eccc_dir = buoys.ECCC_DIR.format(day="20261013", wmo="4600206")
    files = {
        buoys.STATION_TABLE: fx("station_table_excerpt.txt"),
        buoys.LATEST_OBS: fx("latest_obs_excerpt.txt"),
        buoys.REALTIME.format(id="46041", ext="txt"): fx("46041.txt"),
        buoys.REALTIME.format(id="46041", ext="spec"): fx("46041.spec"),
        buoys.CDIP_URL: fx("cdip_wave_agg.csv"),
        eccc_dir: b'<a href="2026-10-13-1905-4600206-AUTO-swob.xml">x</a> <a href="2026-10-13-2005-4600206-AUTO-swob.xml">',
        eccc_dir + "2026-10-13-2005-4600206-AUTO-swob.xml": fx("eccc_4600206.xml"),
        buoys.coops_url("wind", "9441102"): fx("coops_wind_9441102.json"),
        buoys.coops_url("water_temperature", "9441102"): fx("coops_wtemp_9441102.json"),
    }
    cfg = {st["id"]: st for st in buoys.NANOOS_STATIONS}
    for (host, ds, mapping, qc), name in zip(cfg["46119"]["datasets"], ("nanoos_chaba_met.json", "nanoos_chaba_hydro.json")):
        files[buoys.erddap_url(host, ds, mapping, qc)] = fx(name)
    host, ds, mapping, qc = cfg["byb_quileute_center"]["datasets"][0]
    files[buoys.erddap_url(host, ds, mapping, qc)] = fx("nanoos_byb_quileute.json")
    calls = []

    def fetch(url, headers=None):
        calls.append(url)
        if url not in files:
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
        return files[url]

    monkeypatch.setattr(buoys, "fetch", fetch)
    logs = []
    n = buoys.build(log=logs.append, now=NOW)
    text = (tmp_path / "buoys.js").read_text(encoding="utf-8")
    assert text.startswith("window.BUOYS = ") and text.rstrip().endswith(";")
    data = json.loads(text[len("window.BUOYS = "):].rstrip().rstrip(";"))
    assert set(data) == {"updated", "updated_t", "stations"} and n == len(data["stations"])
    st = by_id(data["stations"])
    assert {"46041", "46211", "46206", "46119", "9441102", "byb_quileute_center"} <= set(st)
    assert "46026" not in st and "WPTW1" not in st
    s = st["46041"]
    assert len(s["trace"]) == 24 and s["trace_t0"] == utc(2026, 10, 13, 20) - 23 * 3600
    assert s["hs_ft"] == 4.3 and s["swh_ft"] == 3.9 and s["credit"] is None
    assert st["46206"]["dpd_s"] == 13.3 and st["46211"]["src"] == "CDIP"
    assert all(isinstance(x["t"], int) for x in data["stations"])
    assert logs[-1].startswith("buoys: %d stations, " % n) and "with waves" in logs[-1]
    assert not any("@" in u for u in calls)


def test_not_coastal_region_does_nothing(monkeypatch):
    monkeypatch.setattr(buoys.region, "cfg", lambda: {"name": "x"})
    monkeypatch.setattr(buoys, "fetch", lambda *a, **k: pytest.fail("fetched"))
    assert buoys.build(log=lambda s: None) == 0
