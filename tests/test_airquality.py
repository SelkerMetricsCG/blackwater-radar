"""Air quality layer (airquality.py): AirNow HourlyAQObs, AirFire temporary monitors, store, AIRQ (no network)."""
import datetime as dt
import json

import pytest

import airquality

BBOX = (43.0, 52.5, -126.6, -112.5)          # the pnw window, rounded
T00 = int(dt.datetime(2026, 9, 28, 0, tzinfo=dt.timezone.utc).timestamp())
HDR = ('"AQSID","SiteName","Status","EPARegion","Latitude","Longitude","Elevation","GMTOffset","CountryCode","StateName",'
       '"ValidDate","ValidTime","DataSource","ReportingArea_PipeDelimited","OZONE_AQI","PM10_AQI","PM25_AQI","NO2_AQI",'
       '"OZONE_Measured","PM10_Measured","PM25_Measured","NO2_Measured","PM25","PM25_Unit","OZONE","OZONE_Unit","NO2",'
       '"NO2_Unit","CO","CO_Unit","SO2","SO2_Unit","PM10","PM10_Unit"')


def row(aqsid, name, lat, lon, when, aqi, pm, agency="Washington Dept. of Ecology", elev="30.0"):
    return ('"%s","%s","Active","R10","%s","%s","%s","-8","US","WA","%s","%s","%s","","","","%s","","0","0","1","0",'
            '"%s","UG/M3","","","","","","","","","",""' % (aqsid, name, lat, lon, elev, when.strftime("%m/%d/%Y"),
                                                           when.strftime("%H:%M"), agency, aqi, pm))


def hourly(t, rows):
    return "\n".join([HDR] + rows) + "\n"


def when(t):
    return dt.datetime.fromtimestamp(t, dt.timezone.utc)


def airfire(hours, temp_vals, perm_vals=None):
    """AirFire wide files: one temporary monitor inside the window, one outside, one permanent (ignored)."""
    meta = ("deviceDeploymentID,deviceID,locationName,longitude,latitude,elevation,address,airnow_agencyName,deploymentType\n"
            "d_tmp,840MMWA1,MMWA1,-120.66,47.60,350,\"Leavenworth Fish Hatchery, Icicle Road, Chelan County, WA\",USFS,Temporary\n"
            "d_far,840MMCA9,MMCA9,-119.6,37.7,2200,NA,California Air Resources Board,Temporary\n"
            "d_perm,530330080,Seattle,-122.3,47.6,30,NA,Washington Dept. of Ecology,Permanent\n")
    stamps = [when(t).strftime("%Y-%m-%dT%H:%M:%SZ") for t in hours]
    raw = ["datetime,d_tmp,d_far,d_perm"] + ["%s,%s,5,7" % (s, r) for s, (r, _) in zip(stamps, temp_vals)]
    nc = ["datetime,d_tmp,d_far,d_perm"] + ["%s,%s,5,7" % (s, n) for s, (_, n) in zip(stamps, temp_vals)]
    return meta, "\n".join(raw) + "\n", "\n".join(nc) + "\n"


# ---------- AQI conversion (EPA AQI TAD, May 2024) ----------
@pytest.mark.parametrize("c,aqi", [(0.0, 0), (4.6, 26), (6.6, 37), (9.0, 50), (9.1, 51), (12.0, 56), (35.4, 100),
                                   (35.5, 101), (55.4, 150), (125.4, 200), (225.4, 300), (325.4, 500), (9.05, 50)])
def test_aqi_from_pm25_breakpoints(c, aqi):
    # 4.6 -> 26 and 6.6 -> 37 are AirNow's own values for two temporary monitors (AirNowWildfire.csv, 2026-09-28)
    assert airquality.aqi_from_pm25(c) == aqi


def test_aqi_above_the_top_breakpoint_extends_the_last_segment():
    assert airquality.aqi_from_pm25(425.3) == 699
    assert airquality.aqi_from_pm25(None) is None and airquality.aqi_from_pm25(-1) is None


# ---------- parsing ----------
def test_parse_hourly_keeps_pm25_rows_with_utc_hour_start():
    text = hourly(T00, [row("530330080", "Seattle-10th & Weller", "47.5965", "-122.3197", when(T00), "44", "8.0"),
                        row("000010601", "Goose Bay", "53.3047", "-60.3644", when(T00), "", "")])
    recs = airquality.parse_hourly(text)
    assert [r["id"] for r in recs] == ["530330080"]
    r = recs[0]
    assert (r["t"], r["aqi"], r["pm"], r["agency"], r["elev"]) == (T00, 44, 8.0, "Washington Dept. of Ecology", 30.0)


def test_aqi_without_raw_value_is_kept_with_pm_none():
    # AirNow sometimes has PM25_AQI but a blank PM25 (seen at an Oakland site, 2026-09-28)
    recs = airquality.parse_hourly(hourly(T00, [row("060010011", "Oakland", "37.74", "-122.17", when(T00), "44", "")]))
    assert recs[0]["aqi"] == 44 and recs[0]["pm"] is None


def test_malformed_rows_are_skipped():
    good = row("530330080", "Seattle", "47.59", "-122.31", when(T00), "44", "8.0")
    bad_lat = row("530330081", "Bad lat", "x", "-122.31", when(T00), "44", "8.0")
    no_id = row("", "No id", "47.59", "-122.31", when(T00), "44", "8.0")
    truncated = good[:40]
    recs = airquality.parse_hourly(hourly(T00, [bad_lat, no_id, good, truncated]))
    assert [r["id"] for r in recs] == ["530330080"]


def test_parse_airfire_takes_temporary_monitors_hours_with_a_raw_value():
    hours = [T00 - 3600, T00, T00 + 3600]
    # the last row is the hour in progress: raw NA, NowCast carried forward
    meta, raw, nc = airfire(hours, [("15", "7.8"), ("9", "8.4"), ("NA", "8.4")])
    recs = airquality.parse_airfire(meta, raw, nc)
    tmp = [r for r in recs if r["id"] == "d_tmp"]
    assert [r["t"] for r in tmp] == [T00 - 3600, T00]
    assert [(r["pm"], r["aqi"]) for r in tmp] == [(15.0, 43), (9.0, 47)]
    assert tmp[0]["name"] == "Leavenworth Fish Hatchery" and tmp[0]["agency"] == "USFS" and tmp[0]["elev"] == 350.0
    assert {r["id"] for r in recs} == {"d_tmp", "d_far"}        # the permanent column is ignored


def test_parse_airfire_falls_back_to_location_name():
    meta, raw, nc = airfire([T00], [("9", "8.4")])
    far = [r for r in airquality.parse_airfire(meta, raw, nc) if r["id"] == "d_far"][0]
    assert far["name"] == "MMCA9"


# ---------- store ----------
def recs_at(t, aqi, pm=8.0, sid="530330080", lat=47.59, lon=-122.31):
    return [{"id": sid, "name": "Seattle", "agency": "Ecology", "lat": lat, "lon": lon, "elev": 30.0, "t": t,
             "aqi": aqi, "pm": pm}]


def test_merge_clips_to_the_region_window():
    store = airquality.merge({"v": 1}, recs_at(T00, 40) + recs_at(T00, 60, sid="080310026", lat=39.7, lon=-105.0),
                             False, BBOX)
    assert list(store["st"]) == ["530330080"]


def test_a_revised_hour_overwrites_the_older_value():
    store = airquality.merge({"v": 1}, recs_at(T00, 40, 7.9), False, BBOX)
    airquality.merge(store, recs_at(T00, 45, 9.2), False, BBOX)
    assert store["st"]["530330080"]["h"][str(T00)] == [45, 9.2]


def test_prune_drops_hours_older_than_72_and_empty_stations():
    store = airquality.merge({"v": 1, "have": [T00 - 72 * 3600, T00]}, recs_at(T00 - 72 * 3600, 30), False, BBOX)
    airquality.merge(store, recs_at(T00 - 71 * 3600, 31, sid="530330081"), False, BBOX)
    airquality.prune(store, T00)
    assert list(store["st"]) == ["530330081"] and store["have"] == [T00]


def test_to_airq_aligns_72_hours_ending_at_newest():
    store = airquality.merge({"v": 1}, recs_at(T00, 44, 8.0) + recs_at(T00 - 2 * 3600, 41, 7.0), False, BBOX)
    store["grid"] = {"lm": "x", "t": T00 + 3600, "file": "frames/aq/aqi.webp?v=1"}
    a = airquality.to_airq(store, T00, T00 + 5400)
    assert len(a["hours"]) == 72 and a["hours"][-1] == T00 and a["hours"][0] == T00 - 71 * 3600
    s = a["stations"][0]
    assert s["aqi"][-3:] == [41, None, 44] and s["pm"][-3:] == [7.0, None, 8.0] and s["temp"] is False
    assert a["grid"] == {"t": T00 + 3600, "file": "frames/aq/aqi.webp?v=1"}
    json.dumps(a)                                    # must serialise


def test_to_airq_of_an_empty_store_is_valid():
    a = airquality.to_airq({"v": 1}, T00, T00 + 5400)
    assert a["stations"] == [] and a["grid"] is None and len(a["hours"]) == 72


# ---------- build(): fetch, backfill, keep last good ----------
import urllib.error          # noqa: E402

NOW = T00 + 2 * 3600 + 1800          # 02:30 UTC: 01 UTC may not be posted yet, 00 and 23 are
LM = "Mon, 28 Sep 2026 01:44:48 GMT"


def serve(files, calls=None):
    """fake airquality.fetch: url -> text (or an Exception to raise); anything else is not posted"""
    def fetch(url):
        if calls is not None:
            calls.append(url)
        v = files.get(url)
        if v is None:
            raise airquality.NotPosted(url)
        if isinstance(v, Exception):
            raise v
        return v.encode(), LM
    return fetch


def af_urls(meta, raw, nc):
    return {airquality.AIRFIRE + "airnow_PM2.5_latest_meta.csv": meta,
            airquality.AIRFIRE + "airnow_PM2.5_latest_data.csv": raw,
            airquality.AIRFIRE + "airnow_PM2.5_nowcast_latest_data.csv": nc}


def seattle(t, aqi, pm="8.0"):
    return hourly(t, [row("530330080", "Seattle-10th & Weller", "47.5965", "-122.3197", when(t), str(aqi), pm)])


@pytest.fixture
def job(tmp_path, monkeypatch):
    monkeypatch.setattr(airquality, "OUT", str(tmp_path / "airquality.js"))
    monkeypatch.setattr(airquality, "STORE", str(tmp_path / "aq_cache.json"))
    monkeypatch.setattr(airquality.region, "bbox", lambda: BBOX)
    monkeypatch.setattr(airquality, "build_grid", lambda store, log=print: False)
    return tmp_path


def read_airq(path):
    text = path.read_text(encoding="utf-8")
    assert text.startswith("window.AIRQ = ")
    return json.loads(text[len("window.AIRQ = "):].rstrip().rstrip(";"))


def test_first_run_writes_permanent_and_temporary_monitors(job, monkeypatch):
    files = {airquality.hourly_url(T00): seattle(T00, 44), airquality.hourly_url(T00 - 3600): seattle(T00 - 3600, 40)}
    files.update(af_urls(*airfire([T00, T00 + 3600, T00 + 7200], [("9", "8.4"), ("2", "4.3"), ("NA", "4.3")])))
    monkeypatch.setattr(airquality, "fetch", serve(files))
    assert airquality.build(log=lambda *a: None, now=NOW) == 2
    a = read_airq(job / "airquality.js")
    assert a["hours"][-1] == T00 + 3600                     # newest: the temporary monitor's 01 UTC hour
    by = {s["id"]: s for s in a["stations"]}
    assert by["530330080"]["aqi"][-3:] == [40, 44, None]
    assert by["d_tmp"]["aqi"][-2:] == [47, 24] and by["d_tmp"]["temp"] is True   # NowCast 8.4 and 4.3 ug/m3
    assert "d_far" not in by                               # outside the window


def test_unposted_top_hour_falls_back(job, monkeypatch):
    calls = []
    files = {airquality.hourly_url(T00): seattle(T00, 44), airquality.hourly_url(T00 - 3600): seattle(T00 - 3600, 40)}
    monkeypatch.setattr(airquality, "fetch", serve(files, calls))
    airquality.build(log=lambda *a: None, now=NOW)
    hourly_calls = [u for u in calls if "HourlyAQObs" in u]
    assert hourly_calls[:3] == [airquality.hourly_url(T00 + 3600), airquality.hourly_url(T00), airquality.hourly_url(T00 - 3600)]


def test_backfill_is_capped_per_run_and_remembered(job, monkeypatch):
    calls = []
    files = {airquality.hourly_url(T00): seattle(T00, 44), airquality.hourly_url(T00 - 3600): seattle(T00 - 3600, 40)}
    monkeypatch.setattr(airquality, "fetch", serve(files, calls))
    airquality.build(log=lambda *a: None, now=NOW)
    first = [u for u in calls if "HourlyAQObs" in u]
    assert len(first) == 3 + airquality.BACKFILL_PER_RUN      # 01 (not posted), 00, 23, then 24 older hours
    calls.clear()
    airquality.build(log=lambda *a: None, now=NOW + 900)
    second = [u for u in calls if "HourlyAQObs" in u]
    assert airquality.hourly_url(T00 - 3 * 3600) not in second   # asked last run: not again
    assert len(second) == 3 + airquality.BACKFILL_PER_RUN        # the next 24 missing hours


def test_second_run_takes_the_revised_hour(job, monkeypatch):
    files = {airquality.hourly_url(T00): seattle(T00, 44), airquality.hourly_url(T00 - 3600): seattle(T00 - 3600, 40)}
    monkeypatch.setattr(airquality, "fetch", serve(files))
    airquality.build(log=lambda *a: None, now=NOW)
    files[airquality.hourly_url(T00)] = seattle(T00, 47, "9.9")
    airquality.build(log=lambda *a: None, now=NOW + 900)
    s = read_airq(job / "airquality.js")["stations"][0]
    assert s["aqi"][-1] == 47 and s["pm"][-1] == 9.9


def test_everything_down_keeps_the_last_good_file(job, monkeypatch):
    out = job / "airquality.js"
    out.write_text('window.AIRQ = {"stations": [1]};\n', encoding="utf-8")
    monkeypatch.setattr(airquality, "fetch", serve({}))
    with pytest.raises(RuntimeError):
        airquality.build(log=lambda *a: None, now=NOW)
    assert out.read_text(encoding="utf-8") == 'window.AIRQ = {"stations": [1]};\n'


def test_airfire_down_still_writes_permanent_monitors(job, monkeypatch):
    logs = []
    files = {airquality.hourly_url(T00): seattle(T00, 44)}
    files.update({u: urllib.error.URLError("timed out") for u in af_urls("", "", "")})
    monkeypatch.setattr(airquality, "fetch", serve(files))
    assert airquality.build(log=logs.append, now=NOW) == 1
    assert any("AirFire" in m and "failed" in m for m in logs)


def test_grid_failure_still_writes_stations(job, monkeypatch):
    logs = []

    def broken(store, log=print):
        raise RuntimeError("cfgrib exploded")
    monkeypatch.setattr(airquality, "build_grid", broken)
    monkeypatch.setattr(airquality, "fetch", serve({airquality.hourly_url(T00): seattle(T00, 44)}))
    assert airquality.build(log=logs.append, now=NOW) == 1
    assert "grid FAILED" in logs[-1]


def test_corrupt_store_starts_fresh(job, monkeypatch):
    (job / "aq_cache.json").write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(airquality, "fetch", serve({airquality.hourly_url(T00): seattle(T00, 44)}))
    assert airquality.build(log=lambda *a: None, now=NOW) == 1
    assert json.loads((job / "aq_cache.json").read_text(encoding="utf-8"))["v"] == 1
