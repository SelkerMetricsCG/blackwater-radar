"""Smoke forecast helpers in map.html (smokeHelpers block), run under node; skipped where node is missing."""
import json
import os
import re
import shutil
import subprocess

import pytest

import region

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node not installed")

# six hours of a run, t = 4600, 8200, 11800, 15400, 19000, 22600
H = "[0,1,2,3,4,5].map(k => ({h: k + 1, t: 1000 + 3600 * (k + 1)}))"
# the PNW window (tiles 19..23, 42..46): west longitude and north latitude, as the page's bounds() gives them
B = "{w: %r, n: %r}" % (region.tile_lon(19), region.tile_lat(42))
G = "{w: 2, h: 2, n: 2, nodata: -1, scale: 0.1, arr: [10, 20, -1, 40, 50, 60, 70, 80]}"


def run(expr):
    with open(os.path.join(ROOT, "map.html"), encoding="utf-8") as f:
        html = f.read()
    block = re.search(r"// BEGIN smokeHelpers[^\n]*\n(.*?)// END smokeHelpers", html, re.S).group(1)
    js = block + "\nprocess.stdout.write(JSON.stringify(" + expr + "));"
    return json.loads(subprocess.run([NODE, "-e", js], capture_output=True, text=True, check=True).stdout)


def test_category_edges_match_the_job():
    assert run("[1.99, 2, 9.0, 9.09, 9.1, 35.4, 35.5, 55.5, 125.5, 225.5, 300, null, NaN, -1].map(smokeCat)") == [-1, 0, 0, 0, 1, 1, 2, 3, 4, 5, 5, -1, -1, -1]
    assert run("[SMOKE_EDGES, SMOKE_COLS.length, SMOKE_NAMES.length, SMOKE_SHORT.length]") == [[2, 9.1, 35.5, 55.5, 125.5, 225.5], 6, 6, 6]


def test_hours_shown_from_now_and_the_kept_hour():
    assert run("smokeHours({hours: " + H + "}, 1000 + 3 * 3600 + 1000).map(h => h.h)") == [3, 4, 5, 6]     # past hours drop out
    assert run("smokeHours({hours: " + H + "}, 6040).map(h => h.h)") == [1, 2, 3, 4, 5, 6]                  # 24 min before f01: shown
    assert run("smokeHours({hours: " + H + "}, 6400).map(h => h.h)") == [2, 3, 4, 5, 6]                     # exactly 30 min past f01: gone
    assert run("smokeHours({hours: " + H + "}, 1e9)") == []
    assert run("[smokeHours(null, 5), smokeHours({}, 5)]") == [[], []]
    assert run("smokeIndex(" + H + ", 15500)") == 3
    assert run("smokeIndex(" + H + ", 1)") == 0
    assert run("[smokeIndex(" + H + ", null), smokeIndex([], 5)]") == [0, 0]


def test_when_label():
    assert run("[smokeWhen(1000, 1000), smokeWhen(1000 + 14 * 3600, 1000), smokeWhen(400, 1000), smokeWhen(2700, 1000), smokeWhen(2900, 1000)]") == \
        ["now", "in 14 h", "now", "now", "in 1 h"]


def test_cell_and_values_at_a_point():
    assert run("smokeCell(" + G + ", 50, -115, " + B + ")") == 1
    assert run("smokeAt(" + G + ", 50, -115, " + B + ")") == [2, 6]
    assert run("smokeAt(" + G + ", 44.5, -120, " + B + ")") == [None, 7]           # nodata at hour 0: outside the model
    assert run("[smokeAt(" + G + ", 30, -120, " + B + "), smokeAt(null, 50, -115, " + B + "), smokeCell(" + G + ", 50, -100, " + B + ")]") == [None, None, -1]


def test_reload_after_30_minutes():
    assert run("smokeNeedsLoad(null, 0, 1000)") is True
    assert run("smokeNeedsLoad({}, 0, 29 * 60 * 1000)") is False
    assert run("smokeNeedsLoad({}, 0, 31 * 60 * 1000)") is True
