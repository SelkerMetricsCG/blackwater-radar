"""SNOTEL layer records (snotel.py) from synthetic responses in the AWDB API's shape (no network)."""
import datetime as dt
import json
import time

import snotel

CFG = {"noise_floor_in": 1.0, "despike_width": 1, "start_slack_h": 1, "end_slack_h": 3,
       "max_new_base_in": 6.0, "max_new_per_h_in": 1.0}
NOW = dt.datetime(2026, 1, 10, 15, 30)       # naive UTC = 07:30 PST
SITE = {"id": "791:WA:SNTL", "name": "Stevens Pass", "net": "SNTL", "lat": 47.74, "lon": -121.09,
        "elev": 3940, "tz": -8.0, "huc": "170200"}
MED = {"791:WA:SNTL": {"swe": (13.5, 15.0), "wy": (31.0, 25.0)}}
# 74 hourly readings from 2026-01-07 06:00 PST to 2026-01-10 07:00 PST: flat 40 in, a 14 in storm
# ending at midnight, then 4 in of settling
DEPTH = [40] * 60 + [42, 44, 46, 48, 50, 52, 54] + [53, 52, 52, 51, 51, 50, 50]
PREC = [30.0] * 62 + [30.2, 30.5, 30.9, 31.3, 31.6, 31.8, 31.9] + [31.9] * 5
WTEQ = [12.0] * 60 + [12.3, 12.6, 12.9, 13.2, 13.4, 13.6, 13.7] + [13.7] * 7


def awdb(triplet, elements, start_local, daily=False):
    """elements: {"SNWD": [...], "SMS:-2": [...]}, one value per hour (or day) from start_local, station time"""
    step = dt.timedelta(days=1) if daily else dt.timedelta(hours=1)
    fmt = "%Y-%m-%d" if daily else "%Y-%m-%d %H:%M"
    data = []
    for key, vals in elements.items():
        code, _, depth = key.partition(":")
        se = {"elementCode": code}
        if depth:
            se["heightDepth"] = int(depth)
        data.append({"stationElement": se,
                     "values": [{"date": (start_local + i * step).strftime(fmt), "value": v} for i, v in enumerate(vals)]})
    return [{"stationTriplet": triplet, "data": data}]


def stevens():
    rows = awdb("791:WA:SNTL", {"SNWD": DEPTH, "PREC": PREC, "WTEQ": WTEQ, "TOBS": [25] * 74,
                                "SMS:-2": [22.5] * 74, "STO:-2": [33] * 74, "SMS:-8": [30.1] * 74},
                dt.datetime(2026, 1, 7, 6, 0))
    return snotel.parse(rows, {"791:WA:SNTL": -8.0}, False)["791:WA:SNTL"]


def test_station_time_is_converted_to_utc():
    # read as UTC, the last reading (07:00 PST) would be 8.5 h old and every window would be empty
    rec = snotel.site_record(SITE, stevens(), MED, NOW, CFG)
    assert rec["new"] == {"12": 10.0, "24": 14.0, "36": 14.0, "48": 14.0, "60": 14.0, "72": 14.0}


def test_site_record_carries_everything_the_popup_shows():
    rec = snotel.site_record(SITE, stevens(), MED, NOW, CFG)
    assert rec["depth"] == 50 and rec["swe"] == 13.7
    assert rec["swe_pct"] == 90 and rec["swe_med"] == 15.0
    assert rec["wy"] == 31.0 and rec["wy_pct"] == 124
    assert rec["p24"] == 1.9
    assert rec["temp"]["now"] == 25 and len(rec["temp"]["spark"]) == 25
    assert rec["soil"] == {"2": {"m": 22.5, "t": 33.0}, "8": {"m": 30.1, "t": None}}
    assert rec["t"] == int(dt.datetime(2026, 1, 10, 15, 0, tzinfo=dt.timezone.utc).timestamp())


def test_zero_median_gives_no_percent():
    rec = snotel.site_record(SITE, stevens(), {"791:WA:SNTL": {"swe": (0.0, 0.0), "wy": (0.4, 0.0)}}, NOW, CFG)
    assert rec["swe_med"] == 0.0 and "swe_pct" not in rec
    assert "wy_pct" not in rec


def test_bc_pillows_report_daily_windows_only():
    bc = dict(SITE, id="2A06P:BC:MSNT", net="BC")
    rows = awdb("2A06P:BC:MSNT", {"SNWD": [80, 80, 86, 92, 90]}, dt.datetime(2026, 1, 6), daily=True)
    ser = snotel.parse(rows, {"2A06P:BC:MSNT": -8.0}, True)["2A06P:BC:MSNT"]
    rec = snotel.site_record(bc, ser, {}, NOW, CFG)
    assert rec["new"] == {"24": 0.0, "48": 6.0, "72": 12.0}


def test_scan_sites_carry_soil_only():
    scan = dict(SITE, id="2069:WA:SCAN", net="SCAN")
    rows = awdb("2069:WA:SCAN", {"SMS:-2": [18.0] * 74, "STO:-2": [36] * 74, "PREC": PREC}, dt.datetime(2026, 1, 7, 6, 0))
    ser = snotel.parse(rows, {"2069:WA:SCAN": -8.0}, False)["2069:WA:SCAN"]
    rec = snotel.site_record(scan, ser, {}, NOW, CFG)
    assert rec["soil"]["2"] == {"m": 18.0, "t": 36.0}
    assert not {"swe", "depth", "new", "wy"} & set(rec)


def test_stations_records_keep_the_old_format():
    snotel._LAST.update(t=time.time(), sites=[SITE], series={"791:WA:SNTL": stevens()}, med=MED, now=NOW)
    (rec,) = snotel.stations_records([1, 3, 6, 12, 24], log=lambda *a: None, cfg=CFG)
    assert rec["src"] == "SNOTEL"
    assert rec["snow"][12] == 10.0 and rec["snow"][24] == 14.0
    assert rec["precip"][24] == 1.9
    assert rec["swe_pct"] == 90 and rec["wy_pct"] == 124 and rec["depth"] == 50


def test_region_without_snotel_writes_a_note(tmp_path, monkeypatch):
    out = tmp_path / "snotel.js"
    monkeypatch.setattr(snotel, "OUT", str(out))
    monkeypatch.setattr(snotel.region, "cfg", lambda: {"snotel_states": []})
    assert snotel.build(log=lambda *a: None) == 0
    text = out.read_text(encoding="utf-8")
    assert text.startswith("window.SNOTEL = ")
    data = json.loads(text[len("window.SNOTEL = "):].rstrip().rstrip(";"))
    assert data["sites"] == [] and data["note"]
