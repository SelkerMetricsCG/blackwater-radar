"""Sea surface temperature layer (sst.py): ERDDAP CSV to a north-up grid, window raster, colours, skip logic (no network)."""
import math
import os

import numpy as np
import pytest

import region
import sst

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "coastal", "sst_excerpt.csv")


def fixture_text():
    with open(FIX, encoding="utf-8") as f:
        return f.read()


def reversed_lat_order(text):
    """the same CSV with the latitude rows north-to-south (ERDDAP order for a descending-latitude dataset)"""
    lines = text.splitlines()
    head, rows = lines[:2], lines[2:]
    by_lat = {}
    for r in rows:
        by_lat.setdefault(r.split(",")[1], []).append(r)
    order = sorted(by_lat, key=float, reverse=True)
    return "\n".join(head + [r for lat in order for r in by_lat[lat]]) + "\n"


def pixel(lat, lon):
    """(row, col) of a lat/lon in the full window pixel space"""
    z, x0, x1, y0, y1 = region.window()
    n = 2 ** z
    x = (lon + 180.0) / 360.0 * n
    y = (1 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi) / 2 * n
    return int((y - y0) * 256), int((x - x0) * 256)


def test_parse_csv_values_and_nan():
    lats, lons, g = sst.parse_csv(fixture_text())
    assert g.shape == (6, 8) and g.dtype == np.float32
    assert lats[0] > lats[-1]                                   # north-up
    assert np.all(np.diff(lons) > 0)
    # 47.275 N, -124.525: 285.31 K -> 12.16 C (bottom-left of a north-up grid)
    assert lats[-1] == pytest.approx(47.275) and lons[0] == pytest.approx(-124.525)
    assert g[-1, 0] == pytest.approx(285.31 - 273.15, abs=1e-3)
    assert np.isnan(g[-1, -1])                                  # land
    assert np.isnan(g[0, 4]) and not np.isnan(g[0, 3])          # 47.525 N: water to -124.375, land from -124.325
    assert int(np.isnan(g).sum()) == 18


def test_grid_orientation():
    a = sst.parse_csv(fixture_text())
    b = sst.parse_csv(reversed_lat_order(fixture_text()))
    np.testing.assert_array_equal(a[0], b[0])
    np.testing.assert_array_equal(a[2], b[2])
    wa, wb = sst.to_window(*a), sst.to_window(*b)
    z, x0, x1, y0, y1 = region.window()
    assert wa.shape == ((y1 - y0 + 1) * 256, (x1 - x0 + 1) * 256)
    np.testing.assert_array_equal(wa, wb)
    # north-up in the window: the south-west cell's value lands at its own position, in F
    r, c = pixel(47.275, -124.525)
    assert wa[r, c] == pytest.approx((285.31 - 273.15) * 9 / 5 + 32, abs=1e-3)
    r, c = pixel(47.525, -124.525)
    assert wa[r, c] == pytest.approx((284.36 - 273.15) * 9 / 5 + 32, abs=1e-3)
    assert np.isnan(wa[0, 0])                                   # outside the excerpt


def test_colorize_nodata_transparent():
    arr = np.array([[np.nan, 50.0], [35.0, 75.0]], np.float32)
    img = sst.colorize(arr)
    assert img.mode == "RGBA" and img.size == (2, 2)
    px = np.asarray(img)
    assert px[0, 0, 3] == 0                                     # nodata
    assert px[0, 1, 3] > 0 and px[1, 0, 3] > 0 and px[1, 1, 3] > 0
    assert tuple(px[1, 0, :3]) == sst.SST_BINS[0][1]            # below the ramp: clamped to the first colour
    assert tuple(px[1, 1, :3]) == sst.SST_BINS[-1][1]           # above the ramp: the last colour


def test_legend_bins_match_colors():
    mins = [lo for lo, _ in sst.SST_BINS]
    assert mins[0] == 40 and mins[-1] == 68 and all(b - a == 2 for a, b in zip(mins, mins[1:]))
    blues, reds = sst.SST_BINS[0][1], sst.SST_BINS[-1][1]
    assert blues[2] > blues[0] and reds[0] > reds[2]           # blue to red
    arr = np.array([[lo + 1.0 for lo, _ in sst.SST_BINS]], np.float32)
    px = np.asarray(sst.colorize(arr))
    for i, (lo, color) in enumerate(sst.SST_BINS):
        assert tuple(px[0, i, :3]) == color
    leg = sst.legend()
    assert [d["min"] for d in leg] == mins
    assert [d["color"] for d in leg] == ["#%02x%02x%02x" % c for _, c in sst.SST_BINS]


def test_skips_when_date_unchanged(tmp_path, monkeypatch):
    out = tmp_path / "sst.js"
    out.write_text('window.SST = {"date":"2026-10-12","file":"frames/sst/sst.webp"};\n', encoding="utf-8")
    monkeypatch.setattr(sst, "OUT", str(out))
    monkeypatch.setattr(sst, "latest_date", lambda: "2026-10-12")

    def boom(url):
        raise AssertionError("fetched %s" % url)

    monkeypatch.setattr(sst, "fetch", boom)
    logs = []
    assert sst.build(log=logs.append) is None
    assert logs == ["sst: unchanged 2026-10-12"]
