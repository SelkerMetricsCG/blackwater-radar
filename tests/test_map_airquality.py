"""Air quality helpers in map.html (aqHelpers block), run under node; skipped where node is missing."""
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
    block = re.search(r"// BEGIN aqHelpers[^\n]*\n(.*?)// END aqHelpers", html, re.S).group(1)
    js = block + "\nprocess.stdout.write(JSON.stringify(" + expr + "));"
    return json.loads(subprocess.run([NODE, "-e", js], capture_output=True, text=True, check=True).stdout)


def test_categories_at_every_edge():
    edges = [0, 50, 51, 100, 101, 150, 151, 200, 201, 300, 301, 500, 50.4, 50.5]
    assert run("[" + ",".join(map(str, edges)) + "].map(aqCat)") == [0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 0, 1]
    assert run("[null, NaN].map(aqCat)") == [-1, -1]


def test_colours_and_names_are_the_official_ones():
    assert run("AQ_BINS") == [[0, "#00e400"], [51, "#ffff00"], [101, "#ff7e00"], [151, "#ff0000"], [201, "#8f3f97"], [301, "#7e0023"]]
    assert run("AQ_NAMES") == ["Good", "Moderate", "Unhealthy for sensitive groups", "Unhealthy", "Very unhealthy", "Hazardous"]


def test_last_report_and_staleness():
    s = '{aqi: [40, 44, null, null], pm: [7, 8, null, null]}'
    hours = "[0, 3600, 7200, 10800]"
    assert run("aqLast(" + s + ")") == {"i": 1, "aqi": 44, "pm": 8}
    # last report is the hour 3600-7200; stale once more than 3 h have passed since 7200
    assert run("aqStale(" + s + ", " + hours + ", 7200 + 3 * 3600)") is False
    assert run("aqStale(" + s + ", " + hours + ", 7200 + 3 * 3600 + 1)") is True
    assert run("aqStale({aqi: [null], pm: [null]}, [0], 10)") is True


@pytest.mark.parametrize("pm,trend", [
    ([10, 10, 10, 16], "rising"),            # +6, and 6 >= 20 % of 10
    ([30, 30, 30, 35], "steady"),            # +5 but under 20 % of 30
    ([40, 40, 40, 30], "falling"),           # -10, and 10 >= 20 % of 40
    ([10, None, 10, 12], "steady"),
    ([None, 10, 10, 16], None),              # no value 3 h before the latest
    ([5, 5], None),
    ([10, 10, 10, 16, None], "rising"),      # trailing gap: the latest value is the one that counts
])
def test_trend(pm, trend):
    assert run("aqTrend(" + json.dumps(pm) + ")") == trend


def test_escape():
    assert run("aqEsc('<b>A & \"B\"</b>')") == "&lt;b&gt;A &amp; &quot;B&quot;&lt;/b&gt;"
    assert run("aqEsc(null)") == ""


def test_air_quality_data_reloads_after_15_minutes():
    # final review: click-anywhere and the layer switches reused AIRQ loaded hours earlier
    assert run("aqNeedsLoad(null, 0, 1000)") is True
    assert run("aqNeedsLoad({}, 1000, 1000 + 15 * 60 * 1000)") is False
    assert run("aqNeedsLoad({}, 1000, 1000 + 15 * 60 * 1000 + 1)") is True
