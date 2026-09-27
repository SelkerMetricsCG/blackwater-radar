"""SNOTEL layer symbol choice in map.html (snMissingKind), run under node; skipped where node is missing."""
import json
import os
import re
import shutil
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node not installed")


def kind(site, el):
    with open(os.path.join(ROOT, "map.html"), encoding="utf-8") as f:
        html = f.read()
    block = re.search(r"// BEGIN snMissingKind[^\n]*\n(.*?)// END snMissingKind", html, re.S).group(1)
    js = block + "\nprocess.stdout.write(JSON.stringify(snMissingKind(" + json.dumps(site) + ", " + json.dumps(el) + ")));"
    return json.loads(subprocess.run([NODE, "-e", js], capture_output=True, text=True, check=True).stdout)


def test_percent_of_median_shows_even_without_a_current_hourly_reading():
    assert kind({"swe_day": 13.5, "swe_med": 15.0, "swe_pct": 90}, "swe") is None


def test_zero_median_is_median_missing_not_no_reading():
    assert kind({"swe_day": 0.0, "swe_med": 0.0}, "swe") == "med"


def test_a_reading_without_any_median_is_median_missing():
    assert kind({"swe": 4.2}, "swe") == "med"


def test_nothing_at_all_is_no_reading():
    assert kind({}, "swe") == "obs"
    assert kind({}, "depth") == "obs"


def test_precip_uses_the_same_rules():
    assert kind({"wy": 30.0, "wy_med": 25.0, "wy_pct": 120}, "prec") is None
    assert kind({"wy": 0.4, "wy_med": 0.0}, "prec") == "med"


def test_raw_elements_need_their_value():
    assert kind({"depth": 12}, "depth") is None
    assert kind({"soil": {"2": {"m": 20.0, "t": None}}}, "sto") == "obs"
