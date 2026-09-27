"""Saved-default migration in map.html (migrateDefault), run under node; skipped where node is missing."""
import json
import os
import re
import shutil
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node not installed")


def migrate(d):
    with open(os.path.join(ROOT, "map.html"), encoding="utf-8") as f:
        html = f.read()
    block = re.search(r"// BEGIN migrateDefault[^\n]*\n(.*?)// END migrateDefault", html, re.S).group(1)
    js = block + "\nprocess.stdout.write(JSON.stringify(migrateDefault(" + json.dumps(d) + ")));"
    return json.loads(subprocess.run([NODE, "-e", js], capture_output=True, text=True, check=True).stdout)


def test_basin_layer_becomes_snotel_basins():
    d = migrate({"checks": {"lyBasins": True}, "selects": {"basinSel": "prec"}})
    assert d["checks"]["lySnotel"] is True and d["snMode"] == "basins" and d["snEl"] == "prec"
    assert "lyBasins" not in d["checks"] and "basinSel" not in d["selects"]


def test_weather_stations_snotel_mode_becomes_snotel_stations():
    d = migrate({"checks": {"lyStations": True}, "selects": {}, "stMode": "swe_pct"})
    assert d["checks"]["lySnotel"] is True and d["snMode"] == "stations" and d["snEl"] == "swe"
    assert d["checks"]["lyStations"] is False and d["stMode"] == "precip"


def test_new_snow_water_mode_falls_back_to_new_snow():
    d = migrate({"checks": {"lyStations": True}, "selects": {}, "stMode": "swe"})
    assert d["stMode"] == "snow" and not d["checks"].get("lySnotel")


def test_new_saves_are_left_alone():
    d = {"checks": {"lySnotel": True, "lyStations": False}, "selects": {}, "snMode": "both", "snEl": "new",
         "snWin": "48", "stMode": "wind"}
    assert migrate(dict(d, checks=dict(d["checks"]), selects={})) == d
