"""Storm-total new snow (newsnow.py): known answers on synthetic depth traces (no network)."""
import datetime as dt

import newsnow

T0 = dt.datetime(2026, 1, 10, 0, 0)
CFG = {"noise_floor_in": 1.0, "despike_width": 1, "start_slack_h": 1, "end_slack_h": 3,
       "max_new_base_in": 6.0, "max_new_per_h_in": 1.0}


def hourly(depths, start=T0):
    return [(start + dt.timedelta(hours=i), float(v)) for i, v in enumerate(depths)]


def test_clean_storm_is_the_full_rise():
    assert newsnow.storm_total([40, 40, 44, 50, 54, 54], floor=1.0) == 14.0


def test_settling_after_the_peak_does_not_erase_it():
    # 14 in fell, then settled 4 in: the storm total stays 14 (end minus start would say 10)
    assert newsnow.storm_total([40, 47, 54, 52, 50], floor=1.0) == 14.0


def test_rise_is_measured_from_the_low_before_it():
    # settling first (60 -> 50), then 8 in of new snow: 8, not 58 - 60
    assert newsnow.storm_total([60, 55, 50, 54, 58], floor=1.0) == 8.0


def test_noise_below_the_floor_is_zero():
    assert newsnow.storm_total([40, 40.5, 40, 40.8, 40.2], floor=1.0) == 0.0


def test_melt_only_is_zero_never_negative():
    assert newsnow.storm_total([50, 48, 45, 41], floor=1.0) == 0.0


def test_too_few_values_is_none():
    assert newsnow.storm_total([40], floor=1.0) is None


def test_one_hour_spike_counts_without_despike_and_not_with_it():
    trace = [40, 40, 52, 40, 40]            # one 12 in spike, e.g. falling snow or an animal in the beam
    assert newsnow.storm_total(trace, floor=1.0, despike_width=1) == 12.0
    assert newsnow.storm_total(trace, floor=1.0, despike_width=3) == 0.0


def test_despike_keeps_a_real_step():
    assert newsnow.storm_total([40, 40, 46, 46, 46], floor=1.0, despike_width=3) == 6.0


def test_despike_does_not_lift_the_start_of_a_steady_rise():
    # 4 in an hour from the first reading: smoothing must not raise the starting depth
    assert newsnow.storm_total([40, 44, 48, 52], floor=1.0, despike_width=3) == 12.0


def test_a_dip_on_the_window_start_reading_is_smoothed_away():
    # a one-hour dip exactly at the window's first reading must not become a 10 in "rise"
    s = hourly([50] * 5 + [40] + [50] * 14)       # dip at T0 + 5 h; flat otherwise
    cfg = dict(CFG, despike_width=3)
    assert newsnow.new_snow(s, T0 + dt.timedelta(hours=17), [12], cfg) == {12: 0.0}


def test_window_needs_a_reading_near_its_start():
    s = hourly([40] * 5 + [44] * 20)          # T0 .. T0+24 h
    t_end = T0 + dt.timedelta(hours=24)
    assert newsnow.window_values(s, t_end, 24) is not None
    assert newsnow.window_values(s, t_end, 36) is None            # the record doesn't reach back 36 h


def test_window_needs_a_recent_reading():
    s = hourly([40] * 10)                     # last reading at T0 + 9 h
    assert newsnow.window_values(s, T0 + dt.timedelta(hours=11), 6) is not None     # 2 h old
    assert newsnow.window_values(s, T0 + dt.timedelta(hours=13), 6) is None         # 4 h old


def test_a_gap_inside_the_window_does_not_break_it():
    s = hourly([40] * 6) + hourly([48] * 6, start=T0 + dt.timedelta(hours=12))     # 6 h gap, then 8 in more
    assert newsnow.new_snow(s, T0 + dt.timedelta(hours=17), [12], CFG) == {12: 8.0}


def test_implausible_totals_are_dropped():
    s = hourly([40] * 18 + [140] * 7)         # +100 in within hours is a sensor fault, not snow
    assert newsnow.new_snow(s, T0 + dt.timedelta(hours=24), [12, 24], CFG) == {12: None, 24: None}


def test_config_file_has_every_parameter():
    assert set(CFG) <= set(newsnow.load_config())
