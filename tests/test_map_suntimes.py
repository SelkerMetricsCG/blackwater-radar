"""Point-panel sunrise and sunset in map.html (sunTimes), run under node; skipped where node is missing.

Expected times are NOAA's (gml.noaa.gov/grad/solcalc, its calcSunriseSetUTC with one refinement pass,
read 2026-09-28); the page itself shows Seattle 07:05 / 18:54 PDT.
"""
import json
import os
import re
import shutil
import subprocess
from datetime import datetime

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node not installed")
TOL_S = 180   # the map's simplified sunrise equation vs NOAA's full algorithm


def sun(lat, lon, y, m, d):
    with open(os.path.join(ROOT, "map.html"), encoding="utf-8") as f:
        html = f.read()
    block = re.search(r"// BEGIN sunTimes[^\n]*\n(.*?)// END sunTimes", html, re.S).group(1)
    # local noon keeps the calendar day whatever the zone; the viewer is in Pacific time, like Chris
    js = block + "\nconst r = sunTimes(%r, %r, new Date(%d, %d, %d, 12));" % (lat, lon, y, m - 1, d) + \
        "\nprocess.stdout.write(JSON.stringify(r && { rise: r.rise.toISOString(), set: r.set.toISOString() }));"
    env = dict(os.environ, TZ="America/Los_Angeles")
    return json.loads(subprocess.run([NODE, "-e", js], capture_output=True, text=True, check=True, env=env).stdout)


def near(got, want):
    diff = abs((datetime.fromisoformat(got) - datetime.fromisoformat(want)).total_seconds())
    return diff <= TOL_S


def test_seattle_rises_in_the_morning_and_sets_in_the_evening():
    r = sun(47.61, -122.33, 2026, 9, 28)
    assert near(r["rise"], "2026-09-28T14:04:32Z"), r
    assert near(r["set"], "2026-09-29T01:54:22Z"), r


def test_the_central_oregon_click_that_showed_them_swapped():
    # the map said "sunrise 6:56 PM · sunset 6:48 AM" here on 2026-09-28
    r = sun(43.7493, -120.5804, 2026, 9, 28)
    assert near(r["rise"], "2026-09-28T13:56:39Z"), r
    assert near(r["set"], "2026-09-29T01:48:21Z"), r


def test_east_longitude_in_the_southern_hemisphere():
    r = sun(-33.87, 151.21, 2026, 9, 28)   # Sydney
    assert near(r["rise"], "2026-09-27T19:37:00Z"), r
    assert near(r["set"], "2026-09-28T07:55:28Z"), r


def test_polar_night_has_no_sunrise():
    assert sun(69.65, 18.96, 2026, 12, 15) is None   # Tromso
