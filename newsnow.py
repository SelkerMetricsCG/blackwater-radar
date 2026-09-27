"""
New snow from a snow-depth sensor, as a storm total: the largest rise from a reading to a later,
higher reading inside a window. Settling after the peak doesn't erase it, and it is never negative.
Rises below the noise floor count as 0.

Used by snotel.py (SNOTEL layer, 12-72 h), stations.py (SNOTEL and HADS depth sensors, 1-24 h) and
snotel_check/ (the method check). Parameters are in snotel_config.yaml; see snotel_check/METHOD.md.
"""
import datetime as dt
import os

ROOT = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(ROOT, "snotel_config.yaml")


def load_config(path=CONFIG):
    """{parameter: value} from snotel_config.yaml"""
    import yaml
    with open(path, encoding="utf-8") as f:
        c = yaml.safe_load(f)
    return {k: v["value"] for k, v in c["parameters"].items()}


def despike(values, width):
    """Centred running median over `width` samples (odd; 1 = off). Near the ends the window shrinks
    symmetrically, so the first and last values are kept as they are (a one-sided window would lift a
    rising record's first value and understate the rise)."""
    if width <= 1 or len(values) < 3:
        return list(values)
    h, n, out = width // 2, len(values), []
    for i in range(n):
        k = min(h, i, n - 1 - i)
        out.append(sorted(values[i - k: i + k + 1])[k])
    return out


def storm_total(values, floor, despike_width=1):
    """values: depths in time order (in). Largest rise from a low to a later high, 0 below `floor`."""
    vals = [v for v in values if v is not None]
    if len(vals) < 2:
        return None
    vals = despike(vals, despike_width)
    low, best = vals[0], 0.0
    for v in vals[1:]:
        low = min(low, v)
        best = max(best, v - low)
    return round(best, 1) if best >= floor else 0.0


def window_values(series, t_end, hours, start_slack_h=1, end_slack_h=3):
    """series: sorted [(datetime, value)]. The reading at or just before the window start plus every
    reading inside it; None when no reading falls inside the window, the record doesn't reach the start
    (within start_slack_h), or its latest reading is more than end_slack_h old."""
    t0 = t_end - dt.timedelta(hours=hours)
    lead = [p for p in series if p[0] <= t0]
    body = [p for p in series if t0 < p[0] <= t_end]
    if not body:
        return None
    pts = ([lead[-1]] if lead else []) + body
    if not pts or abs((pts[0][0] - t0).total_seconds()) > start_slack_h * 3600:
        return None
    if (t_end - pts[-1][0]).total_seconds() > end_slack_h * 3600:
        return None
    return [v for _, v in pts]


def despike_series(series, width):
    """despike() over a whole [(time, value)] record, so a window's first reading is smoothed with its
    real neighbours rather than treated as an end"""
    return list(zip([t for t, _ in series], despike([v for _, v in series], width)))


def new_snow(series, t_end, windows, cfg):
    """{window hours: storm total (in), or None without coverage or above the plausibility cap}"""
    smooth = despike_series(series, cfg["despike_width"])
    out = {}
    for w in windows:
        vals = window_values(smooth, t_end, w, cfg["start_slack_h"], cfg["end_slack_h"])
        v = None if vals is None else storm_total(vals, cfg["noise_floor_in"])
        out[w] = None if v is None or v > cfg["max_new_base_in"] + cfg["max_new_per_h_in"] * w else v
    return out
