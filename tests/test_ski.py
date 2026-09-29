"""ski.py: the resort feed's snow report, the window filter and the file the page loads."""
import datetime as dt
import json
import os

import pytest

import ski

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _area(name, base, h24, h48, h72, d7, closed):
    return {"Name": name, "BaseIn": base, "Last24HoursIn": h24, "Last48HoursIn": h48, "Last72HoursIn": h72,
            "Last7DaysIn": d7, "SinceLiftsClosedIn": closed, "BaseCm": "--", "Last24HoursCm": "--"}


# Crystal Mountain's answer of 2026-05-18, trimmed to the snow report (the base area had no since-close figure)
CRYSTAL = {"Name": "Crystal Mountain", "OperatingStatus": "Closed", "LastUpdate": "2026-09-28T19:00:00-0700",
           "SnowReport": {"LastUpdate": "2026-05-18T12:41:48-0700", "StormTotalIn": "0", "SeasonTotalIn": "281",
                          "SnowBaseRangeIn": "37 - 70", "SnowBaseRangeCM": "94 - 178",
                          "BaseArea": _area("Base", "37", "0", "0", "0", "--", "--"),
                          "MidMountainArea": _area("Mid-Mountain", "58", "0", "0", "0", "--", "0"),
                          "SummitArea": _area("Summit", "70", "0", "0", "0", "--", "0")}}


def test_numbers_and_dashes():
    assert ski.num("10") == 10 and isinstance(ski.num("10"), int)
    assert ski.num("0.5") == 0.5 and ski.num(5) == 5
    assert ski.num("--") is None and ski.num("") is None and ski.num(None) is None and ski.num("n/a") is None


def test_base_range():
    assert ski.base_range("37 - 70") == [37, 70]
    assert ski.base_range("55") == [55, 55]
    assert ski.base_range("--") is None and ski.base_range(None) is None


def test_report_time_is_the_resorts_own_stamp():
    want = int(dt.datetime(2026, 6, 7, 11, 1, 49, tzinfo=dt.timezone(dt.timedelta(hours=-7))).timestamp())
    assert ski.when("2026-06-07T11:01:49-0700") == want
    assert ski.when("yesterday") is None and ski.when(None) is None


def test_parse_report_keeps_points_and_drops_dashes():
    r = ski.parse_report(CRYSTAL)
    assert r["status"] == "Closed" and r["storm"] == 0 and r["season"] == 281 and r["base"] == [37, 70]
    assert r["t"] == ski.when("2026-05-18T12:41:48-0700")
    kinds = [p["kind"] for p in r["pts"]]
    assert kinds == ["base", "mid", "summit"]
    mid = r["pts"][1]
    assert mid["name"] == "Mid-Mountain" and mid["base"] == 58 and mid["h24"] == 0 and mid["closed"] == 0
    assert "d7" not in mid                       # '--' never becomes a number
    assert "closed" not in r["pts"][0]


def test_parse_report_skips_empty_points_and_feeds_without_a_report():
    feed = json.loads(json.dumps(CRYSTAL))
    feed["SnowReport"]["MidMountainArea"] = _area("--", "--", "--", "--", "--", "--", "--")     # Schweitzer's shape
    assert [p["kind"] for p in ski.parse_report(feed)["pts"]] == ["base", "summit"]
    assert ski.parse_report({"Name": "Revelstoke", "LastUpdate": "x", "Forecast": {}}) is None
    assert ski.parse_report({"SnowReport": {"StormTotalIn": "0"}}) is None
    assert ski.parse_report(None) is None


def test_build_writes_the_page_file_and_marks_feed_failures(tmp_path):
    areas = [{"id": "a", "name": "Crystal Mountain", "lat": 46.93, "lon": -121.49, "mp": 80},
             {"id": "b", "name": "Broken Feed", "lat": 47.0, "lon": -121.0, "mp": 999},
             {"id": "c", "name": "Stevens Pass Ski Area", "lat": 47.74, "lon": -121.09, "web": "https://www.stevenspass.com/"}]
    calls = []

    def fake_fetch(mp):
        calls.append(mp)
        if mp == 999:
            raise OSError("timed out")
        return CRYSTAL

    logs = []
    out = tmp_path / "ski.js"
    n = ski.build(logs.append, areas=areas, fetch_fn=fake_fetch, out=str(out))
    assert n == 3 and calls == [80, 999]
    txt = out.read_text(encoding="utf-8")
    assert txt.startswith("window.SKI = ") and txt.endswith(";\n")
    data = json.loads(txt[len("window.SKI = "):-2])
    by = {a["id"]: a for a in data["areas"]}
    assert by["a"]["rep"]["season"] == 281 and by["a"]["rep"]["pts"][1]["base"] == 58
    assert by["b"]["rep"] is None                 # on the feed, nothing usable this run
    assert "rep" not in by["c"]                   # link-out area: never fetched
    assert data["updated_t"] > 0 and any("1 failed" in m for m in logs)
    assert areas[0].get("rep") is None            # the caller's list is left alone


def test_window_filter_uses_the_regions_box(tmp_path):
    lst = tmp_path / "ski_areas.json"
    lst.write_text(json.dumps([{"id": "in", "name": "Alpental", "lat": 47.44, "lon": -121.44},
                               {"id": "out", "name": "Far away", "lat": 10.0, "lon": 10.0}]), encoding="utf-8")
    assert [a["id"] for a in ski.areas_in_window(str(lst))] == ["in"]


def test_shipped_list_is_sound():
    with open(os.path.join(ROOT, "ski_areas.json"), encoding="utf-8") as f:
        areas = json.load(f)
    ids = [a["id"] for a in areas]
    assert len(ids) == len(set(ids)) and len(areas) > 400
    for a in areas:
        assert a["name"] and -90 < a["lat"] < 90 and -180 < a["lon"] < 180
        if "mp" in a:
            assert isinstance(a["mp"], int)
    names = {a["name"] for a in areas}
    assert {"Stevens Pass Ski Area", "Mt Baker", "Crystal Mountain", "Alpental", "Mission Ridge"} <= names
    assert sum(1 for a in areas if "mp" in a) >= 45
