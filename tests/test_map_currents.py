"""Surface-currents helpers in map.html (currentsHelpers block), run under node; skipped where node is missing."""
import json
import os
import re
import shutil
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node not installed")

# a 2 x 2 grid as RGBA bytes, row 0 north: u = 0, 10, 20, 30 cm/s and v = -u (scale 2: byte = 128 + cm/s / 2)
GRID = "{nx: 2, ny: 2, scale: 2, px: [128,128,255,255, 133,123,255,255, 138,118,255,255, 143,113,255,255]}"
# the same with the south-east cell nodata (B = 0)
GRID_HOLE = "{nx: 2, ny: 2, scale: 2, px: [128,128,255,255, 133,123,255,255, 138,118,255,255, 143,113,0,255]}"


def run(expr):
    with open(os.path.join(ROOT, "map.html"), encoding="utf-8") as f:
        html = f.read()
    block = re.search(r"// BEGIN currentsHelpers[^\n]*\n(.*?)// END currentsHelpers", html, re.S).group(1)
    js = block + "\nconst GRID = " + GRID + ", GRID_HOLE = " + GRID_HOLE + ";\n" \
        + "process.stdout.write(JSON.stringify(" + expr + "));"
    return json.loads(subprocess.run([NODE, "-e", js], capture_output=True, text=True, encoding="utf-8", check=True).stdout)


def test_decode_mid_byte_is_still_water():
    assert run("decodeUV(128, 128, 255, 2)") == [0, 0]


def test_decode_saturation_is_plus_minus_254_cms():
    assert run("decodeUV(255, 1, 255, 2)") == [254, -254]


def test_decode_nodata_is_null():
    assert run("decodeUV(140, 120, 0, 2)") is None


def test_bilinear_centre_of_the_cell_is_the_mean_of_four():
    assert run("bilinearUV(GRID, 0.5, 0.5)") == pytest.approx([15, -15])


def test_bilinear_at_a_corner_is_that_cell():
    assert run("bilinearUV(GRID, 0, 0)") == pytest.approx([0, 0])
    assert run("bilinearUV(GRID, 1, 1)") == pytest.approx([30, -30])
    assert run("bilinearUV(GRID, 1, 0)") == pytest.approx([10, -10])


def test_bilinear_leaves_a_nodata_corner_out():
    assert run("bilinearUV(GRID_HOLE, 0.5, 0.5)") == pytest.approx([10, -10])   # mean of 0, 10, 20
    assert run("bilinearUV(GRID_HOLE, 1, 1)") is None                            # only the nodata cell has weight


def test_bilinear_outside_the_grid_is_null():
    assert run("[bilinearUV(GRID, -0.6, 0), bilinearUV(GRID, 0, 1.6), bilinearUV(GRID, -0.4, 0)]") == [None, None, [0, 0]]


def test_speed_bin_edges():
    assert run("CUR_BINS.map(b => b[0])") == [0, 0.5, 1, 1.5, 2, 3]
    assert run("[0, 0.49, 0.5, 0.99, 1, 1.49, 1.5, 1.99, 2, 2.99, 3, 9].map(speedBin)") == [0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5]
    assert run("[speedBin(null), speedBin(NaN)]") == [-1, -1]


def test_particle_count_bounds():
    assert run("particleCount(5)") >= 2000
    assert run("particleCount(14)") <= 6000
    assert run("[7, 12].map(particleCount)") == [2000, 6000]


def test_step_is_1_5_px_per_m_s():
    # 1.5 px at zoom 10 on the equator: 1.5 * 156543.034 / 1024 m; halves per zoom level; scales with cos(lat)
    assert run("stepPx(10, 0)") == pytest.approx(1.5 * 156543.03392 / 1024)
    assert run("stepPx(11, 0) / stepPx(10, 0)") == pytest.approx(0.5)
    assert run("stepPx(10, 60) / stepPx(10, 0)") == pytest.approx(0.5)


def test_speed_and_direction_toward():
    s = run("curSpeedDir(100, 0)")   # 1 m/s eastward
    assert s["kt"] == pytest.approx(1.9438) and s["deg"] == pytest.approx(90)
    assert run("curSpeedDir(0, -50).deg") == pytest.approx(180)
    assert run("curSpeedDir(-30, 30).deg") == pytest.approx(315)


def test_cycle_label_and_same_origin_url():
    assert run("curModels('sscofs t15z 2026-10-13 + wcofs t03z')") == "SSCOFS t15z + WCOFS t03z"
    assert run("curModels('sscofs_t15z_20261013-wcofs_t03z_20261013')") == "SSCOFS t15z + WCOFS t03z"   # the real cycle string
    assert run("curUrl('pnw', 'frames/currents/s2026101315_w2026101303/h07.png')") == "/pnw/currents/s2026101315_w2026101303/h07.png"
