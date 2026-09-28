"""Fires helpers in map.html (fireHelpers block), run under node; skipped where node is missing."""
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
    block = re.search(r"// BEGIN fireHelpers[^\n]*\n(.*?)// END fireHelpers", html, re.S).group(1)
    js = block + "\nprocess.stdout.write(JSON.stringify(" + expr + "));"
    return json.loads(subprocess.run([NODE, "-e", js], capture_output=True, text=True, check=True).stdout)


def test_size_steps_and_age_chips():
    assert run("[null, 0, 99, 100, 9999, 10000, 5e6].map(fireSize)") == [0, 0, 0, 1, 1, 2, 2]
    assert run("[0, 5.9, 6, 23.9, 24, 48, 48.1, null, NaN].map(hotAge)") == [0, 0, 1, 1, 2, 2, -1, -1, -1]
    assert run("HOT_BINS") == [[0, "#ff2d00"], [6, "#ff9a3c"], [24, "#c9a76b"]]
    assert run("[FIRE_COL.WF, FIRE_COL.CX, FIRE_COL.RX, PERIM_COL]") == ["#d1462f", "#d1462f", "#8a8f98", "#c0392b"]


def test_fire_escape():
    assert run("fireEsc('<b>Rowe & \"Creek\"</b>')") == "&lt;b&gt;Rowe &amp; &quot;Creek&quot;&lt;/b&gt;"
    assert run("fireEsc(null)") == ""


def test_ago_and_type_names():
    assert run("[fireAgo(1000, 1000 + 50), fireAgo(1000, 1000 + 3 * 3600), fireAgo(1000, 1000 + 40 * 3600), fireAgo(null, 5), fireAgo(1000, 1000 + 90 * 60)]") == ["just now", "3 h ago", "2 d ago", "", "90 min ago"]
    assert run("['WF', 'CX', 'RX', 'zz'].map(fireTypeName)") == ["wildfire", "complex", "prescribed burn", "fire"]


def test_nearest_and_hotspots_near():
    fl = "[{id:'A', lat:47.5, lon:-120.5, active:true}, {id:'B', lat:47.6, lon:-120.5, active:false}]"
    assert run("fireNearest(" + fl + ", 47.61, -120.5, 50, f => f.active).f.id") == "A"
    assert run("fireNearest(" + fl + ", 47.61, -120.5, 50).f.id") == "B"
    assert run("fireNearest(" + fl + ", 40, -120.5, 50)") is None
    assert run("Math.round(fireDist(47.5, -120.5, 47.51, -120.51) * 100) / 100") == pytest.approx(1.34, abs=0.05)
    rows = "[[47.5, -120.5, 1.0, 'V', 3, 'A', 0, null], [47.5, -120.5, 30, 'V', 3, 'A', 0, null], [48.5, -120.5, 1.0, 'G', 3, null, 1, null]]"
    assert run("hotsNear(" + rows + ", 47.51, -120.51, 10, 24)") == 1


def test_fires_data_reloads_after_15_minutes():
    assert run("fireNeedsLoad(null, 0, 1000)") is True
    assert run("fireNeedsLoad({}, 1000, 1000 + 15 * 60 * 1000)") is False
    assert run("fireNeedsLoad({}, 1000, 1000 + 15 * 60 * 1000 + 1)") is True


def test_panel_controls_are_saved_as_defaults():
    with open(os.path.join(ROOT, "map.html"), encoding="utf-8") as f:
        html = f.read()
    defs = re.search(r"const DEF_CHECKS = \[(.*?)\];", html).group(1)
    for k in ("lyFires", "fireQuiet", "lyHot"):
        assert "'%s'" % k in defs and 'id="%s"' % k in html
    assert html.index('data-grp="air"') < html.index('data-grp="fire"') < html.index('data-grp="hazards"')
