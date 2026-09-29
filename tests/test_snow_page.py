"""The snow-conditions page (snow.html) and its build (build_snow.py): data contract and build output, no network."""
import os
import re
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

from snow import state as snow_state   # noqa: E402  the page mirrors the model's class list and palette

CLASSES = list(snow_state.CLASSES)
DATA_FILES = ["state/index.js", "state/latest.js", "state/latest_cls.js", "brief/latest.js", "static/zones.js"]
TRIP_KEYS = ["source", "source_id", "obs_date", "location", "lat", "lon", "zone", "elevation_ft", "band", "aspects", "surface", "confidence", "quote"]


@pytest.fixture(scope="module")
def html():
    with open(os.path.join(ROOT, "snow.html"), encoding="utf-8") as f:
        return f.read()


def test_base_meta_tag_is_present_for_the_build(html):
    assert '<meta name="snow-base" content="">' in html


def test_every_data_file_is_referenced(html):
    for path in DATA_FILES:
        assert "'%s'" % path in html, path
    # the dated files: state/<date>.js, state/<date>_cls.js, brief/<date>.js
    assert re.search(r"'state/' \+ d \+ '\.js'", html)
    assert re.search(r"'state/' \+ d \+ '_cls\.js'", html)
    assert re.search(r"'brief/' \+ d \+ '\.js'", html)
    assert "?t=' + Date.now()" in html, "data scripts need the cache-buster"


def test_data_globals_are_read(html):
    for g in ("SNOW_INDEX", "SNOW_STATE", "SNOW_CLS", "SNOW_BRIEF", "SNOW_ZONES"):
        assert "window.%s" % g in html, g


def test_class_names_match_the_model_in_order(html):
    m = re.search(r"const CLASSES = \[([^\]]*)\]", html)
    assert m
    names = re.findall(r"'([a-z_]+)'", m.group(1))
    assert names == CLASSES
    assert names[:12] == ["no_snow", "fresh", "settled", "wind", "sun_crust", "rain_crust", "melt_freeze", "isothermal", "dust_on_crust", "old",
                          "wind_loaded", "wind_scoured"]


def test_fallback_palette_and_labels_cover_every_class(html):
    pal = re.search(r"const FALLBACK = \{(.*?)\};", html, re.S).group(1)
    lab = re.search(r"const LABEL = \{(.*?)\};", html, re.S).group(1)
    for c in CLASSES:
        assert re.search(r"\b%s: '%s'" % (c, snow_state.PALETTE[c]), pal), c   # same colours as the class PNG
        assert re.search(r"\b%s:" % c, lab), c
    assert "no_snow: 'transparent'" in pal
    assert "melt_freeze: 'melt-freeze (corn)'" in lab


def test_trip_record_has_the_ledger_shape(html):
    body = re.search(r"const rec = \{(.*?)\n\s*\};", html, re.S).group(1)
    keys = re.findall(r"^\s*([a-z_]+):", body, re.M)
    assert keys == TRIP_KEYS
    assert "source: 'trip'" in body
    assert "snow/trips.json" in html


def test_latest_class_png_is_cache_busted(html):
    # state.py serves latest_cls.png no-cache and the dated PNGs immutable
    assert "/latest/.test(CLS.file) ? '?t=' + Date.now() : ''" in html


def test_page_uses_the_vendored_leaflet_like_the_map(html):
    assert '<link rel="stylesheet" href="vendor/leaflet.css">' in html
    assert '<script src="vendor/leaflet.js"></script>' in html
    assert "unpkg.com" not in html and "cdnjs" not in html


def test_page_has_the_credit_and_terms_link(html):
    assert "avalanche.org public API and NWAC" in html and "USGS 3DEP, ESA WorldCover" in html
    assert 'href="terms.html"' in html


def test_build_bakes_the_base_into_an_output_dir(tmp_path):
    out = tmp_path / "web_snow"
    r = subprocess.run([sys.executable, os.path.join(ROOT, "build_snow.py"), "--base", "http://x/", "--out", str(out)],
                       capture_output=True, text=True, cwd=str(tmp_path))
    assert r.returncode == 0, r.stderr
    built = (out / "index.html").read_text(encoding="utf-8")
    assert 'content="http://x/"' in built
    assert '<meta name="snow-base" content="">' not in built
    assert (out / "terms.html").exists()


def test_build_adds_one_slash_to_a_base_without_one(tmp_path):
    out = tmp_path / "o"
    subprocess.run([sys.executable, os.path.join(ROOT, "build_snow.py"), "--base", "http://x", "--out", str(out)], check=True,
                   capture_output=True, cwd=str(tmp_path))
    assert 'content="http://x/"' in (out / "index.html").read_text(encoding="utf-8")


def test_build_without_env_or_base_fails_clearly(tmp_path, monkeypatch):
    for k in ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET", "R2_PUBLIC_URL"):
        monkeypatch.delenv(k, raising=False)
    if os.path.exists(os.path.join(ROOT, "r2.env")):
        pytest.skip("r2.env present on this machine")
    r = subprocess.run([sys.executable, os.path.join(ROOT, "build_snow.py"), "--out", str(tmp_path / "o")], capture_output=True, text=True, cwd=str(tmp_path))
    assert r.returncode != 0 and "R2_PUBLIC_URL" in r.stderr
    assert not (tmp_path / "o").exists()
