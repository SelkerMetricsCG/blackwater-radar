"""map.html wiring for the ski-report layer: panel control, saved default, data file, credit."""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
with open(os.path.join(ROOT, "map.html"), encoding="utf-8") as f:
    HTML = f.read()


def test_layer_control_sits_in_the_snow_group_with_its_subwrap():
    snow = re.search(r'data-grp="snow">(.*?)<div class="sec grp"', HTML, re.S).group(1)
    assert 'id="lySki"' in snow and 'data-for="lySki"' in snow
    assert 'id="skiWins"' in snow and 'id="skiInfo"' in snow


def test_layer_is_saved_with_the_defaults():
    checks = re.search(r"const DEF_CHECKS = \[(.*?)\];", HTML).group(1)
    assert "'lySki'" in checks
    assert "d.skiWin = skiWin" in HTML and "skiWin = String(d.skiWin)" in HTML


def test_page_loads_the_hourly_file_and_credits_the_sources():
    assert "loadScript('data/ski.js'" in HTML
    assert "Data from OpenSkiData / OpenSkiMap.org, © OpenStreetMap contributors (ODbL), Skimap.org" in HTML
    assert "as each resort reports them" in HTML
