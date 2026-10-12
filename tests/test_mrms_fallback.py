"""mrms.py: Pass 2 is used while it is fresh; when NOAA stops posting it, Pass 1, then radar-only, take over."""
import datetime as dt

import pytest

pytest.importorskip("numpy")
import mrms  # noqa: E402

NOW = dt.datetime(2026, 10, 10, 3, 4)


def _reader(valid, calls):
    def read(name):
        calls.append(name)
        if valid.get(name) is None:
            raise OSError("404")
        return "grid of " + name, valid[name]
    return read


def test_fresh_pass2_is_used_and_nothing_else_is_fetched():
    calls = []
    label, grid, v = mrms.choose(1, NOW, _reader({"MultiSensor_QPE_01H_Pass2": dt.datetime(2026, 10, 10, 2, 0)}, calls), lambda *a: None)
    assert label == "Pass2" and grid == "grid of MultiSensor_QPE_01H_Pass2" and calls == ["MultiSensor_QPE_01H_Pass2"]


def test_stale_pass2_falls_back_to_pass1():
    # 2026-10-09: Pass 2 stopped at 18Z for 21 hours; Pass 1 and radar-only kept coming
    calls = []
    valid = {"MultiSensor_QPE_24H_Pass2": dt.datetime(2026, 10, 9, 18, 0), "MultiSensor_QPE_24H_Pass1": dt.datetime(2026, 10, 10, 2, 0),
             "RadarOnly_QPE_24H": dt.datetime(2026, 10, 10, 3, 0)}
    label, grid, v = mrms.choose(24, NOW, _reader(valid, calls), lambda *a: None)
    assert label == "Pass1" and v == dt.datetime(2026, 10, 10, 2, 0) and len(calls) == 2


def test_missing_or_stale_everywhere_takes_the_newest():
    calls = []
    valid = {"MultiSensor_QPE_01H_Pass2": None, "MultiSensor_QPE_01H_Pass1": dt.datetime(2026, 10, 9, 20, 0),
             "RadarOnly_QPE_01H": dt.datetime(2026, 10, 9, 22, 0)}
    label, grid, v = mrms.choose(1, NOW, _reader(valid, calls), lambda *a: None)
    assert label == "RadarOnly" and len(calls) == 3


def test_nothing_readable_raises():
    with pytest.raises(RuntimeError):
        mrms.choose(1, NOW, _reader({}, []), lambda *a: None)
