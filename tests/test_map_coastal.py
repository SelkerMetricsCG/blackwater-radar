"""Coastal helpers in map.html (coastalHelpers block), run under node; skipped where node is missing."""
import json
import os
import re
import shutil
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node not installed")

# a mixed semidiurnal day: low 0.5 ft, high 8.5 ft six hours later, low 4.5 ft, high 7.5 ft
HILO = [[0, 0.5, "L"], [21600, 8.5, "H"], [43200, 4.5, "L"], [64800, 7.5, "H"]]
EVENTS = [[0, "slack", 0.0], [10800, "flood", 2.0], [21600, "slack", 0.0], [32400, "ebb", 1.6], [43200, "slack", 0.0]]


def run(expr):
    with open(os.path.join(ROOT, "map.html"), encoding="utf-8") as f:
        html = f.read()
    block = re.search(r"// BEGIN coastalHelpers[^\n]*\n(.*?)// END coastalHelpers", html, re.S).group(1)
    js = block + "\nconst HILO = " + json.dumps(HILO) + ", EVENTS = " + json.dumps(EVENTS) + ";\n" \
        + "process.stdout.write(JSON.stringify(" + expr + "));"
    return json.loads(subprocess.run([NODE, "-e", js], capture_output=True, text=True, encoding="utf-8", check=True).stdout)


def test_tide_curve_passes_through_the_extremes():
    assert run("HILO.map(e => tideAt(HILO, e[0]))") == [0.5, 8.5, 4.5, 7.5]


def test_tide_curve_is_the_mean_halfway_between_extremes():
    assert run("tideAt(HILO, 10800)") == pytest.approx(4.5)
    assert run("tideAt(HILO, 32400)") == pytest.approx(6.5)


def test_tide_curve_rises_monotonically_from_low_to_high():
    v = run("[0, 3600, 7200, 10800, 14400, 18000, 21600].map(t => tideAt(HILO, t))")
    assert v == sorted(v)


def test_tide_curve_is_null_outside_the_predictions():
    assert run("[tideAt(HILO, -1), tideAt(HILO, 64801), tideAt([], 5), tideAt([[0, 1, 'H']], 0)]") == [None, None, None, None]


def test_stage_rising_with_minutes_to_the_next_high():
    assert run("tideStage(HILO, 7200)") == {"dir": "rising", "next": [21600, 8.5, "H"], "mins": 240, "at": None}


def test_stage_falling_toward_a_low():
    s = run("tideStage(HILO, 30000)")
    assert s["dir"] == "falling" and s["next"] == [43200, 4.5, "L"] and s["mins"] == 220


def test_stage_slack_within_20_minutes_of_an_extreme():
    before = run("tideStage(HILO, 21600 - 20 * 60)")
    assert before["dir"] == "slack" and before["at"] == [21600, 8.5, "H"] and before["next"] == [21600, 8.5, "H"]
    after = run("tideStage(HILO, 21600 + 20 * 60)")
    assert after["dir"] == "slack" and after["at"] == [21600, 8.5, "H"] and after["next"] == [43200, 4.5, "L"]
    assert run("tideStage(HILO, 21600 - 21 * 60).dir") == "rising"
    assert run("tideStage(HILO, 21600 + 21 * 60).dir") == "falling"


def test_stage_is_null_without_a_next_extreme():
    assert run("tideStage(HILO, 70000)") is None
    assert run("tideStage([], 0)") is None


def test_stage_sentence():
    assert run("tideSentence(tideStage(HILO, 7200))") == "Rising: high 8.5 ft in 4 h"
    assert run("tideSentence(tideStage(HILO, 30000))") == "Falling: low 4.5 ft in 3 h 40 min"
    assert run("tideSentence(tideStage(HILO, 21600 - 600))") == "Slack: high 8.5 ft in 10 min"
    assert run("tideSentence(tideStage(HILO, 21600 + 600))") == "Slack: high 8.5 ft 10 min ago; next low 4.5 ft in 5 h 50 min"
    assert run("tideSentence(null)") == ""


def test_observed_trend_for_stations_without_predictions():
    assert run("obsTrend([[0, 1.0], [1800, 1.3], [3600, 1.6]])") == "rising"
    assert run("obsTrend([[0, 5.0], [1800, 4.8], [3600, 4.5]])") == "falling"
    assert run("obsTrend([[0, 5.0], [1800, 5.05], [3600, 5.05]])") == "slack"
    assert run("[obsTrend(null), obsTrend([[0, 1]])]") == [None, None]


def test_current_interpolates_between_slack_and_max():
    assert run("currentAt(EVENTS, 0)") == {"kind": "slack", "kt": 0}
    assert run("currentAt(EVENTS, 10800)") == {"kind": "flood", "kt": 2}
    assert run("currentAt(EVENTS, 5400)") == {"kind": "flood", "kt": 1}            # halfway: half the max
    assert run("currentAt(EVENTS, 27000)") == {"kind": "ebb", "kt": 0.8}
    v = run("[1800, 3600, 5400, 7200, 9000].map(t => currentAt(EVENTS, t).kt)")
    assert v == sorted(v) and 0 < v[0] < 1 < v[-1] < 2


def test_current_between_flood_and_ebb_without_a_slack_passes_through_zero():
    ev = '[[0, "flood", 2.0], [3600, "ebb", 2.0]]'
    assert run("currentAt(" + ev + ", 1800)") == {"kind": "slack", "kt": 0}
    assert run("currentAt(" + ev + ", 900).kind") == "flood"
    assert run("currentAt(" + ev + ", 2700).kind") == "ebb"


def test_current_is_null_outside_the_events():
    assert run("[currentAt(EVENTS, -5), currentAt(EVENTS, 43201), currentAt([], 0)]") == [None, None, None]


def test_wave_bins_at_every_edge():
    edges = [0, 1.9, 2, 3.9, 4, 6, 8, 10, 12.9, 13, 16, 19.9, 20, 35]
    assert run(json.dumps(edges) + ".map(waveBin)") == [0, 0, 1, 1, 2, 3, 4, 5, 5, 6, 7, 7, 8, 8]
    assert run("[waveBin(null), waveBin(NaN)]") == [-1, -1]
    assert [b[0] for b in run("WAVE_BINS")] == [0, 2, 4, 6, 8, 10, 13, 16, 20]


def test_temp_bins_at_every_edge():
    edges = [33, 40, 44.9, 45, 50, 55, 60, 64.9, 65, 70, 80]
    assert run(json.dumps(edges) + ".map(tempBin)") == [0, 0, 0, 1, 2, 3, 4, 4, 5, 6, 6]
    assert run("tempBin(null)") == -1
    assert [b[0] for b in run("WTEMP_BINS")] == [40, 45, 50, 55, 60, 65, 70]


def test_marine_zone_wind_bins_at_every_edge():
    edges = [0, 14, 15, 24, 25, 33, 34, 47, 48, 70]
    assert run(json.dumps(edges) + ".map(windBinKt)") == [0, 0, 1, 1, 2, 2, 3, 3, 4, 4]
    assert run("windBinKt(null)") == -1
    assert [b[0] for b in run("ZONE_BINS")] == [0, 15, 25, 34, 48]


def test_compass_points():
    assert run("compass(292.5)") == "WNW"
    assert run("[0, 11.24, 11.25, 90, 180, 270, 348.75, 359, 360, -22.5].map(compass)") == \
        ["N", "N", "NNE", "E", "S", "W", "N", "N", "N", "NNW"]
    assert run("compass(null)") == ""


def test_age_and_duration_formatting():
    assert run("[0, 59 * 60, 89 * 60, 90 * 60, 47 * 3600, 48 * 3600, 5 * 86400].map(fmtAge)") == \
        ["0 min", "59 min", "89 min", "2 h", "47 h", "2 days", "5 days"]
    assert run("[fmtAge(null), fmtAge(-30)]") == ["", "0 min"]
    assert run("[0, 10, 60, 130, 600].map(fmtMins)") == ["0 min", "10 min", "1 h", "2 h 10 min", "10 h"]


def test_buoy_stale_value_and_label():
    s = '{t: 1000, hs_ft: 6.24, dpd_s: 14.3, wspd_mph: 17.6, gust_mph: 24.2, wtmp_f: 51.6}'
    assert run("[buoyStale(" + s + ", 1000 + 6 * 3600), buoyStale(" + s + ", 1001 + 6 * 3600)]") == [False, True]
    assert run("[buoyStale({t: 1000, stale: true}, 1000), buoyStale({}, 1000)]") == [True, True]
    assert run("['waves', 'wind', 'wtemp'].map(m => buoyValue(" + s + ", m))") == [6.24, 24.2, 51.6]
    assert run("['waves', 'wind', 'wtemp'].map(m => buoyLabel(" + s + ", m))") == ["6.2 ft 14 s", "18g24", "52°"]
    assert run("[buoyValue({wspd_mph: 8}, 'wind'), buoyValue({}, 'waves'), buoyLabel({wspd_mph: 0}, 'wind')]") == [8, None, "calm"]


def test_surf_zone_text_starts_at_the_title_and_is_capped():
    text = "000\nFZUS56 KPQR\nSRFPQR\n\nSURF ZONE FORECAST\nNWS Portland"
    assert run("srfText(" + json.dumps(text) + ")") == "SURF ZONE FORECAST\nNWS Portland"
    assert run("srfText('x'.repeat(3000)).length") == 2501
