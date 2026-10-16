"""Swell-forecast helpers in map.html (swellHelpers block, after coastalHelpers for compass), run under node;
skipped where node is missing."""
import json
import os
import re
import shutil
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node not installed")

# a 2 x 2 grid with 3 stacked bands as RGBA bytes (row 0 north; band b in rows 2b, 2b + 1). Band 0: heights 1.0, 2.0,
# 3.0, 4.0 m, period 10 s, from 270; band 1: one crafted cell (R 92, G 24, B 146) at i 1, j 0, the rest nodata;
# band 2: all nodata except i 0, j 1 (0.5 m, 8 s, from 180).
PX = ("[10,20,135,255, 20,20,135,255, 30,20,135,255, 40,20,135,255,"
      " 0,0,255,255, 92,24,146,255, 0,0,255,255, 0,0,255,255,"
      " 0,0,255,255, 0,0,255,255, 5,16,90,255, 0,0,255,255]")


def run(expr):
    with open(os.path.join(ROOT, "map.html"), encoding="utf-8") as f:
        html = f.read()
    blocks = [re.search(r"// BEGIN " + n + r"[^\n]*\n(.*?)// END " + n, html, re.S).group(1)
              for n in ("coastalHelpers", "swellHelpers")]
    js = "\n".join(blocks) + "\nconst PX = " + PX + ";\n" + "process.stdout.write(JSON.stringify(" + expr + "));"
    out = subprocess.run([NODE, "-e", js], capture_output=True, text=True, encoding="utf-8", check=True).stdout
    return json.loads(out)


def test_decode_crafted_pixel():
    assert run("decodeSwell([92, 24, 146, 255], 1, 1, 0, 0, 0)") == {"h_m": 9.2, "per_s": 12, "dir": 292}


def test_decode_nodata_is_null():
    assert run("decodeSwell([92, 24, 255, 255], 1, 1, 0, 0, 0)") is None


def test_decode_band_offset_is_band_times_ny():
    assert run("decodeSwell(PX, 2, 2, 1, 1, 0)") == {"h_m": 9.2, "per_s": 12, "dir": 292}
    assert run("decodeSwell(PX, 2, 2, 2, 0, 1)") == {"h_m": 0.5, "per_s": 8, "dir": 180}
    assert run("decodeSwell(PX, 2, 2, 2, 0, 0)") is None
    assert run("[decodeSwell(PX, 2, 2, 0, 2, 0), decodeSwell(PX, 2, 2, 0, 0, -1)]") == [None, None]


def test_sample_is_bilinear_over_valid_cells():
    v = run("sampleSwell(PX, 2, 2, 0, 0.5, 0.5)")
    assert v["h_m"] == pytest.approx(2.5) and v["per_s"] == 10 and v["dir"] == 270
    assert run("sampleSwell(PX, 2, 2, 1, 0.5, 0.5)")["h_m"] == pytest.approx(9.2)   # only the one valid corner
    assert run("sampleSwell(PX, 2, 2, 1, 0, 1)") is None                            # its weight there is 0
    assert run("heightAt(PX, 2, 2, 0, 0.5, 0.5)") == pytest.approx(2.5)
    assert run("[heightAt(PX, 2, 2, 1, 0, 1), heightAt(PX, 2, 2, 0, -0.6, 0)]") == [-1, -1]


def test_swell_bin_edges():
    edges = [0, 1, 2, 3, 4, 6, 8, 10, 13, 16, 20]
    got = run("[" + ",".join("swellBin(%s)" % e for e in edges) + "]")
    assert got == list(range(11))
    below = run("[" + ",".join("swellBin(%s)" % (e - 0.01) for e in edges[1:]) + "]")
    assert below == list(range(10))
    assert run("[swellBin(-1), swellBin(45), swellBin(null), swellBin(NaN)]") == [0, 10, -1, -1]


def test_arrow_length_by_period():
    assert run("arrowLen(6)") == 8
    assert run("arrowLen(20)") == 24
    assert run("arrowLen(13)") == pytest.approx(16)
    assert run("[arrowLen(3), arrowLen(25), arrowLen(null)]") == [8, 24, 8]


def test_streak_speed_by_period_and_zoom():
    assert run("streakSpeed(6, 9)") == pytest.approx(1.12)                  # 0.4 + 6 * 0.12 px per frame at zoom 9
    assert run("streakSpeed(15, 9)") == pytest.approx(2.2)
    assert run("streakSpeed(6, 10)") == pytest.approx(2.24)                 # doubles per zoom level
    assert run("streakSpeed(6, 13)") == pytest.approx(1.12 * 3)             # 2^4 clamped to 3
    assert run("streakSpeed(6, 5)") == pytest.approx(1.12 * 0.5)            # 2^-4 clamped to 0.5
    assert run("[streakSpeed(null, 9), streakSpeed(NaN, 9)]") == pytest.approx([0.4, 0.4])


def test_streak_count_bounds():
    assert run("[streakCount(7), streakCount(9), streakCount(11)]") == [1200, 2100, 3000]
    assert run("[streakCount(3), streakCount(6.5), streakCount(11.5), streakCount(18)]") == [1200, 1200, 3000, 3000]


def test_crest_length_by_period():
    assert run("crestLen(10)") == pytest.approx(12)
    assert run("crestLen(20)") == pytest.approx(19)
    assert run("[crestLen(0), crestLen(null)]") == [5, 5]


def test_travel_direction():
    assert run("travelDir(292)") == 112
    assert run("[travelDir(0), travelDir(180), travelDir(90), travelDir(359)]") == [180, 0, 270, 179]


def test_nearest_hour_window():
    hours = "[{t: 0}, {t: 10800}, {t: 21600}]"
    assert run("nearestHour(" + hours + ", 11000, 5400)") == 1
    assert run("nearestHour(" + hours + ", 10800 + 5400, 5400)") == 1        # a tie keeps the earlier
    assert run("nearestHour(" + hours + ", 21600 + 5401, 5400)") == -1       # beyond the window
    assert run("nearestHour(" + hours + ", -99999)") == 0                    # no window: always the nearest
    assert run("nearestHour([], 0, 5400)") == -1


def test_series_at():
    s = "{t0: 1000, dt: 10800, p: [[1, 10, 270], null, [3, 12, 250]]}"
    assert run("seriesAt(" + s + ", 1000 + 21600 + 3000)") == [3, 12, 250]
    assert run("[seriesAt(" + s + ", 1000 + 10800), seriesAt(" + s + ", 1000 + 32400), seriesAt(null, 0)]") == [None, None, None]


def test_fmt_swell():
    assert run("fmtSwell(6.21, 15.2, 292)") == "6.2 ft at 15 s from WNW"
    assert run("fmtSwell(6.2, null, null)") == "6.2 ft"
    assert run("fmtSwell(null, 15, 292)") == ""


def test_partitions_text_leaves_absent_ones_out():
    assert run("swPartsText([[8.2, 15, 292], null, [1.3, 16, 180]])") == \
        "primary 8.2 ft at 15 s from WNW · third 1.3 ft at 16 s from S"
    assert run("swPartsText([null, null, null])") == ""


def test_labels_and_run_text():
    assert run("beachLabel([6.2, 14.6, 270])") == "6 ft 15 s"
    assert run("beachLabel([0.4, 9, 270])") == "0.4 ft 9 s"
    assert run("gfsRunText('gfswave_t18z_20261015')") == "GFS-Wave 18Z 10/15"
    runs = "{sew: {run: 1792065600, label: '12Z 2026-10-15'}, pqr: {run: 1792087200, label: '18Z 2026-10-15'}, mfr: {run: 1792065600}}"
    assert run("nwpsRunText(" + runs + ")") == "NWPS Seattle 12Z / Portland 18Z / Medford 12Z"
    assert run("nwpsRunText({})") == ""


def test_worker_url_from_index_file():
    assert run("swUrl('pnw', 'frames/swell/gfswave_t18z_20261015/s03.png')") == "/pnw/swell/gfswave_t18z_20261015/s03.png"
    assert run("swUrl('pnw', 'frames/nwps/nwps_sew_t12z_20261015-pqr_t18z_20261015/h00.png')") == \
        "/pnw/nwps/nwps_sew_t12z_20261015-pqr_t18z_20261015/h00.png"
    assert run("swUrl('pnw', 'frames/currents/x/h00.png')") is None


def test_layers_are_wired_into_the_page():
    with open(os.path.join(ROOT, "map.html"), encoding="utf-8") as f:
        html = f.read()
    for ident in ("lySwell", "swLook", "swSlider", "swPlay", "swPrev", "swNext", "swOpacity", "swLabel", "swInfo", "lyBeaches", "beachInfo"):
        assert 'id="' + ident + '"' in html
    assert html.index('id="lyCurrents"') < html.index('id="lySwell"') < html.index('id="lyBeaches"')
    assert "data-swfc" in html and "swReadout(ll)" in html
    for look in ("streaks", "crests", "arrows"):
        assert 'data-look="' + look + '"' in html
    assert 'class="chip on" data-look="streaks"' in html and "let swLook = 'streaks'" in html
