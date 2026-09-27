# SNOTEL Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace "Snowpack by basin" with a SNOTEL layer that works like NRCS iMap's Station/Basin Conditions view (stations, basins or both; SWE, snow depth, new snow 12–72 h, water-year precip, soil moisture, soil temperature), with new snow computed as a storm total that Chris approves from real data first.

**Architecture:** A small pure module `newsnow.py` computes the storm total and is shared by everything that reports new snow. A new hourly job module `snotel.py` makes the one NRCS AWDB pull per run, writes `data/snotel.js`, and hands `stations.py` SNOTEL records in its old 1–24 h format so the Rain / snow totals interpolation keeps SNOTEL. `map.html` gains a SNOTEL layer (stations/basins/both) and loses SNOTEL from Weather stations. A method check (`snotel_check/`) runs first and gates everything after it.

**Tech Stack:** Python 3.12 on GitHub Actions (3.13 locally, Anaconda), PyYAML, pytest; Leaflet 1.x in a single `map.html`; NRCS AWDB REST API; matplotlib (MATLAB style) for the check figure.

**Spec:** `docs/superpowers/specs/2026-09-27-snotel-layer-design.md` (commit `cea8cb8`). Read it before starting; its decisions table is binding.

## Global Constraints

- Work in `C:\Users\16035\Desktop\BlackwaterLabs\radar` (its own git repo, branch `main`). Main Python: `C:\Users\16035\anaconda3\python.exe` (`python` in Git Bash). Tests: `python -m pytest tests/ -v` from `radar/`.
- **Another Claude session edits files in `radar/` at the same time.** Stage and commit only your own paths: `git add <paths>` then `git commit -m "..." -- <paths>`. Never `git add -A`, `git add .`, `git stash` or `git checkout -- .`.
- Chris runs `git push`, `npx wrangler deploy` and `gh` logins himself. Never push or deploy; ask before anything that publishes.
- Never run `capture.capture_all()` or `cloud.py` locally: with `r2.env` present they upload to the live bucket. Call module `build()` functions directly.
- Never print or commit `r2.env` or `nps.env`; leave `*.env` out of any grep whose output is shown.
- New code sends no personal data: User-Agent strings are `BlackwaterRadar/1.0 (...)` with no email address.
- `web/` is gitignored and holds the only copies of the icons, `manifest.webmanifest` and `vendor/leaflet*`. Never delete or regenerate it; `build_web.py` only rewrites `web/index.html` and `web/stf.js`.
- `stations.py WINDOWS` stays `[1, 3, 6, 12, 24]`. SNOTEL layer windows are `[12, 24, 36, 48, 60, 72]`; soil depth buttons are 2, 8 and 20 in.
- Basin outlines appear only for SWE and water-year precipitation; for depth, new snow and soil they are removed, not greyed (spec decision 4).
- Raw units: snow depth and new snow in inches, soil moisture in % water by volume, soil temperature in °F (spec decision 5).
- Figures for Chris: `plt.style.use('matlab')`, muted colours.
- Verification protocol (`~/.claude/verification-protocol.md`): never write "verified" or "checked" without saying what was checked and how; flag every judgment call and library default when it is made.
- Task 3 is a hard gate: nothing from Task 4 on starts until Chris has approved the check figure and the values in `snotel_config.yaml`.

## Review Focus

1. **Station clock vs runner clock.** AWDB stamps hourly values in the station's standard time (`dataTimeZone`, e.g. −8) all year; the runner's clock follows daylight saving. A reading must land in the right window in both seasons. Pinned by `test_station_time_is_converted_to_utc` (Task 4).
2. **Gaps and stale sensors.** A window with missing hours inside must still report; a window whose start the record doesn't reach, or whose last reading is hours old, must report nothing rather than a wrong number. Pinned by `test_a_gap_inside_the_window_does_not_break_it`, `test_window_needs_a_reading_near_its_start`, `test_window_needs_a_recent_reading` (Task 1).
3. **Early season (now, late September).** Most SWE medians are 0, so % of median is undefined: sites show ⊗ with "no snow normally on this date", never 0 % or a crash. Pinned by `test_zero_median_gives_no_percent` (Task 4) and the browser check in Task 9.
4. **A region with no SNOTEL (`ne`).** `snotel.py` writes an empty file with a note, `stations.py` still runs, and the page hides the layer. Pinned by `test_region_without_snotel_writes_a_note` (Task 4) and the `ne` browser check (Task 9).
5. **Readers' saved defaults.** Someone whose saved map had "Snowpack by basin" or a SNOTEL mode in Weather stations must open to the equivalent SNOTEL view. Pinned by the four tests in `tests/test_map_defaults.py` (Task 8).

---

## File map

| File | Status | Responsibility |
|---|---|---|
| `newsnow.py` | create | storm total, window cutting, config loading (pure, no network) |
| `snotel_config.yaml` | create | every new-snow parameter with provenance and `approved:` |
| `tests/test_newsnow.py` | create | known-answer tests on synthetic depth traces |
| `snotel_check/check_newsnow.py` | create | method check at the five test sites; figure + summary |
| `snotel_check/METHOD.md` | create | one-page method card |
| `snotel.py` | create | AWDB pull, `data/snotel.js`, SNOTEL records for `stations.py` |
| `tests/test_snotel.py` | create | record builder on AWDB-shaped synthetic responses |
| `stations.py` | modify | take SNOTEL from `snotel.py`; HADS depth uses the storm total |
| `capture.py` | modify | run `snotel.build()` before `stations.build()` |
| `cloud.py` | modify | keep `snotel_meta_cache.json` between runs |
| `requirements.txt`, `.github/workflows/tests.yml` | modify | add `pyyaml` to the hourly runner and the tests job |
| `.gitignore` | modify | ignore `snotel_check/out/` |
| `map.html` | modify | panel order, SNOTEL layer, Weather stations without SNOTEL, defaults migration |
| `build_web.py` | modify | `snotel` flag per region |
| `tests/test_map_defaults.py` | create | saved-default migration run under node |
| `CLAUDE.md`, `HANDOFF.md` | modify | docs at the end |

---

### Task 1: Storm-total module and its config

**Files:**
- Create: `newsnow.py`, `snotel_config.yaml`, `tests/test_newsnow.py`
- Modify: `requirements.txt` (add `pyyaml`), `.github/workflows/tests.yml` (install PyYAML: the tests job installs only pytest)

**Interfaces:**
- Produces:
  - `newsnow.storm_total(values: list[float], floor: float, despike_width: int = 1) -> float | None` (None when fewer than 2 values)
  - `newsnow.window_values(series: list[tuple[datetime, float]], t_end: datetime, hours: int, start_slack_h: float = 1, end_slack_h: float = 3) -> list[float] | None`
  - `newsnow.new_snow(series, t_end, windows: list[int], cfg: dict) -> dict[int, float | None]`
  - `newsnow.load_config(path=newsnow.CONFIG) -> dict` with keys `noise_floor_in, despike_width, start_slack_h, end_slack_h, max_new_base_in, max_new_per_h_in`

- [ ] **Step 1: Write the failing tests**

`tests/test_newsnow.py`:
```python
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
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `python -m pytest tests/test_newsnow.py -v`
Expected: collection error, `ModuleNotFoundError: No module named 'newsnow'`.

- [ ] **Step 3: Write `newsnow.py`**

```python
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
    """Centred running median over `width` samples (odd; 1 = off); the ends use the samples they have."""
    if width <= 1 or len(values) < 3:
        return list(values)
    h = width // 2
    out = []
    for i in range(len(values)):
        win = sorted(values[max(0, i - h): i + h + 1])
        out.append(win[len(win) // 2])
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
    reading inside it; None when the record doesn't reach the start (within start_slack_h) or its
    latest reading is more than end_slack_h old."""
    t0 = t_end - dt.timedelta(hours=hours)
    lead = [p for p in series if p[0] <= t0]
    body = [p for p in series if t0 < p[0] <= t_end]
    pts = ([lead[-1]] if lead else []) + body
    if not pts or abs((pts[0][0] - t0).total_seconds()) > start_slack_h * 3600:
        return None
    if (t_end - pts[-1][0]).total_seconds() > end_slack_h * 3600:
        return None
    return [v for _, v in pts]


def new_snow(series, t_end, windows, cfg):
    """{window hours: storm total (in), or None without coverage or above the plausibility cap}"""
    out = {}
    for w in windows:
        vals = window_values(series, t_end, w, cfg["start_slack_h"], cfg["end_slack_h"])
        v = None if vals is None else storm_total(vals, cfg["noise_floor_in"], cfg["despike_width"])
        out[w] = None if v is None or v > cfg["max_new_base_in"] + cfg["max_new_per_h_in"] * w else v
    return out
```

- [ ] **Step 4: Write `snotel_config.yaml`**

```yaml
# New-snow (storm total) parameters for the SNOTEL layer, Weather stations and the "New snow"
# interpolation. Read by newsnow.load_config(); the file is the configuration that actually runs.
# Source categories (verification protocol): measured / fitted from data / literature / library default /
# judgment call. "provisional" values are placeholders until Chris approves the snotel_check/ results.
approved:            # date Chris approved the values below; empty = not yet approved
parameters:
  noise_floor_in:
    value: 1.0
    units: in
    source: judgment call (provisional)
    derived: placeholder; to be fitted from dry-spell storm totals at the five test sites (snotel_check/)
    used_in: newsnow.new_snow, snotel.py BC windows
  despike_width:
    value: 1
    units: hourly samples, odd (1 = off)
    source: judgment call (provisional)
    derived: off until snotel_check/ shows whether one-hour spikes change storm totals
    used_in: newsnow.new_snow
  start_slack_h:
    value: 1
    units: h
    source: judgment call
    derived: the reading used as the window's start may be up to 1 h from it (one missed hourly report)
    used_in: newsnow.window_values
  end_slack_h:
    value: 3
    units: h
    source: judgment call
    derived: the latest reading may be up to 3 h old; report latency to be measured in the Task 5 local run
    used_in: newsnow.window_values, snotel.py freshness of latest values
  max_new_base_in:
    value: 6.0
    units: in
    source: judgment call (carried over from stations.py build(), in use since 2026-09-13)
    derived: new snow above base + per_h x window hours is treated as a sensor fault
    used_in: newsnow.new_snow
  max_new_per_h_in:
    value: 1.0
    units: in per window hour
    source: judgment call (carried over from stations.py build(), in use since 2026-09-13)
    derived: see max_new_base_in
    used_in: newsnow.new_snow
```

Add `pyyaml` as a new last line of `requirements.txt` (the hourly runner installs from it; locally PyYAML 6.0.2 is already present). The tests workflow installs only pytest, so in `.github/workflows/tests.yml` change `- run: pip install pytest` to `- run: pip install pytest pyyaml` and the header comment's `stdlib + pytest` to `stdlib + pytest + PyYAML`.

- [ ] **Step 5: Run the tests to see them pass**

Run: `python -m pytest tests/test_newsnow.py -v`
Expected: 14 passed.

- [ ] **Step 6: Commit**

```bash
git add newsnow.py snotel_config.yaml tests/test_newsnow.py requirements.txt .github/workflows/tests.yml
git commit -m "newsnow: storm-total new snow from depth sensors, provisional config" -- newsnow.py snotel_config.yaml tests/test_newsnow.py requirements.txt .github/workflows/tests.yml
```
(End the message with the Co-Authored-By line from the session's attribution reminder.)

---

### Task 2: New-snow method check at the five test sites

**Files:**
- Create: `snotel_check/check_newsnow.py`, `snotel_check/METHOD.md`
- Modify: `.gitignore` (add a line `snotel_check/out/`)

**Interfaces:**
- Consumes: `newsnow.storm_total`, `newsnow.window_values` (Task 1).
- Produces: `snotel_check/out/summary.txt`, `snotel_check/out/fig_<id>.png`, `snotel_check/out/windows_<id>.csv`, `snotel_check/out/accounting.log` for Chris (Task 3).

- [ ] **Step 1: Write `snotel_check/check_newsnow.py`**

```python
"""
Method check for the SNOTEL layer's new-snow number (storm total), following
~/.claude/verification-protocol.md. Nothing here feeds the live map.

For the five test sites (spec decision 10) it pulls hourly snow depth, SWE and precipitation for
winter 2025-26 (2025-10-01 to 2026-05-31) and summer 2026 (2026-07-01 to 2026-08-31), then for every
24 h window ending 07:00 station time reports:
  A = end minus start, B = storm total (floor 0, no despike), B3 = storm total after a 3-sample
  running median, C = end minus the window's lowest reading, dSWE and dP = pillow and gauge rise.
Noise-floor evidence: B in summer bare-ground windows and in Dec-Mar dry spells (dSWE <= 0 and dP <= 0).
Spikes: hourly readings SPIKE_IN or more from the median of themselves and their two neighbours.
Storm days (B >= STORM_IN): implied new-snow density = dSWE / B, a check from a different sensor.

Outputs (snotel_check/out/, gitignored): raw_*.json (cached pulls), windows_<id>.csv, summary.txt,
fig_<id>.png, accounting.log.
Run from radar/:  python snotel_check/check_newsnow.py
"""
import csv
import datetime as dt
import json
import math
import os
import statistics
import sys
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import newsnow  # noqa: E402

OUT = os.path.join(HERE, "out")
UA = "BlackwaterRadar/1.0 (snow-depth method check)"
SITES = {"791:WA:SNTL": "Stevens Pass", "679:WA:SNTL": "Paradise", "908:WA:SNTL": "Alpine Meadows",
         "352:WA:SNTL": "Blewett Pass", "651:OR:SNTL": "Mt Hood Test Site"}
WINTER = ("2025-10-01", "2026-05-31")
SUMMER = ("2026-07-01", "2026-08-31")
DRY_MONTHS = (12, 1, 2, 3)
STORM_IN = 4.0      # judgment call: a "storm day" for the density table
SPIKE_IN = 2.0      # judgment call: a reading this far from its 3-sample median counts as a spike
END_HOUR = 7        # windows end 07:00 station time, like a morning snow report
MUTED = {"depth": "#5a6f8c", "A": "#9aa3ad", "B": "#4f7a9a", "C": "#b0907a", "storm": "#d9c9a3"}


def log(msg):
    print(msg)
    with open(os.path.join(OUT, "accounting.log"), "a", encoding="utf-8") as f:
        f.write(dt.datetime.now().strftime("%Y-%m-%d %H:%M ") + msg + "\n")


def months(begin, end):
    d, stop = dt.date.fromisoformat(begin), dt.date.fromisoformat(end)
    while d <= stop:
        nxt = (d.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
        yield d.isoformat(), min(nxt - dt.timedelta(days=1), stop).isoformat()
        d = nxt


def fetch(triplet, begin, end):
    q = urllib.parse.urlencode({"stationTriplets": triplet, "elements": "SNWD,WTEQ,PREC", "duration": "HOURLY",
                                "beginDate": begin + " 00:00", "endDate": end + " 23:00"})
    req = urllib.request.Request("https://wcc.sc.egov.usda.gov/awdbRestApi/services/v1/data?" + q,
                                 headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read())


def series(triplet, begin, end):
    """{code: sorted [(station-time datetime, value)]}; the raw pull is cached in out/"""
    path = os.path.join(OUT, "raw_%s_%s.json" % (triplet.split(":")[0], begin))
    if not os.path.exists(path):
        raw = {}
        for b, e in months(begin, end):
            for s in fetch(triplet, b, e):
                for el in s.get("data", []):
                    raw.setdefault(el["stationElement"]["elementCode"], []).extend(
                        [v["date"], v["value"]] for v in el.get("values", []) if v.get("value") is not None)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(raw, f)
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    return {code: sorted((dt.datetime.strptime(d, "%Y-%m-%d %H:%M"), float(v)) for d, v in rows)
            for code, rows in raw.items()}


def pct(xs, p):
    """nearest-rank percentile; None for an empty list"""
    if not xs:
        return None
    s = sorted(xs)
    return s[max(0, math.ceil(p / 100.0 * len(s)) - 1)]


def spikes(snwd):
    """(time, excursion) for hourly readings SPIKE_IN or more from the median of themselves and both
    neighbours; only where the three readings are consecutive hours"""
    out = []
    for i in range(1, len(snwd) - 1):
        (t0, a), (t1, b), (t2, c) = snwd[i - 1], snwd[i], snwd[i + 1]
        if t2 - t0 != dt.timedelta(hours=2):
            continue
        m = statistics.median([a, b, c])
        if abs(b - m) >= SPIKE_IN:
            out.append((t1, b - m))
    return out


def windows(ser, begin, end):
    """one row per 24 h window ending END_HOUR station time"""
    snwd = [p for p in ser.get("SNWD", []) if p[1] >= 0]
    rows = []
    day = dt.date.fromisoformat(begin) + dt.timedelta(days=1)
    while day <= dt.date.fromisoformat(end):
        t_end = dt.datetime.combine(day, dt.time(END_HOUR))
        v = newsnow.window_values(snwd, t_end, 24)
        if v is not None:
            w = newsnow.window_values(ser.get("WTEQ", []), t_end, 24)
            p = newsnow.window_values(ser.get("PREC", []), t_end, 24)
            rows.append({"end": t_end.isoformat(sep=" "), "depth_end": v[-1], "median_depth": statistics.median(v),
                         "A": round(v[-1] - v[0], 1), "B": newsnow.storm_total(v, 0.0, 1),
                         "B3": newsnow.storm_total(v, 0.0, 3), "C": round(v[-1] - min(v), 1),
                         "dSWE": None if w is None else round(w[-1] - w[0], 2),
                         "dP": None if p is None else round(p[-1] - p[0], 2)})
        day += dt.timedelta(days=1)
    return rows


def figure(plt, trip, name, win, storms):
    snwd = [p for p in win.get("SNWD", []) if p[1] >= 0]
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 7), gridspec_kw={"height_ratios": [3, 2]})
    ax1.plot([t for t, _ in snwd], [v for _, v in snwd], color=MUTED["depth"], lw=0.8)
    for r in storms:
        e = dt.datetime.fromisoformat(r["end"])
        ax1.axvspan(e - dt.timedelta(hours=24), e, color=MUTED["storm"], alpha=0.6, lw=0)
        top = max(v for t, v in snwd if e - dt.timedelta(hours=24) <= t <= e)
        ax1.annotate("%.0f" % r["B"], (e, top), fontsize=8, ha="right", va="bottom")
    ax1.set_ylabel("snow depth (in), hourly")
    ax1.set_title("%s (%s): winter 2025-26; the six largest 24 h storm totals shaded" % (name, trip))
    x = list(range(len(storms)))
    names = {"A": "A: end minus start", "B": "B: storm total", "C": "C: end minus window low"}
    for key, off in (("A", -0.27), ("B", 0.0), ("C", 0.27)):
        ax2.bar([i + off for i in x], [r[key] for r in storms], width=0.25, color=MUTED[key], label=names[key])
    for i, r in enumerate(storms):
        if r["dSWE"] is not None and r["B"] > 0:
            ax2.annotate("%.0f%%" % (100 * r["dSWE"] / r["B"]), (i, r["B"]), xytext=(0, 3),
                         textcoords="offset points", ha="center", fontsize=8)
    ax2.set_xticks(x)
    ax2.set_xticklabels([r["end"][5:10] for r in storms])
    ax2.set_ylabel("new snow, 24 h to 07:00 (in)")
    ax2.legend(loc="upper right", fontsize=8)
    ax2.set_title("label over each B bar: implied new-snow density = pillow SWE gain / B", fontsize=9)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "fig_%s.png" % trip.split(":")[0]), dpi=130)
    plt.close(fig)


def main():
    os.makedirs(OUT, exist_ok=True)
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.style.use("matlab")
    lines, dry_all = [], []
    for trip, name in SITES.items():
        win, summ = series(trip, *WINTER), series(trip, *SUMMER)
        hours = ((dt.date.fromisoformat(WINTER[1]) - dt.date.fromisoformat(WINTER[0])).days + 1) * 24
        neg = sum(1 for _, v in win.get("SNWD", []) if v < 0)
        log("%s %s: winter hours expected %d per element, returned %s, SNWD < 0 dropped %d"
            % (trip, name, hours, {k: len(v) for k, v in win.items()}, neg))
        rows, srows = windows(win, *WINTER), windows(summ, *SUMMER)
        with open(os.path.join(OUT, "windows_%s.csv" % trip.split(":")[0]), "w", newline="", encoding="utf-8") as f:
            wr = csv.DictWriter(f, fieldnames=list(rows[0]))
            wr.writeheader()
            wr.writerows(rows)
        dry = [r["B"] for r in rows if dt.datetime.fromisoformat(r["end"]).month in DRY_MONTHS
               and r["dSWE"] is not None and r["dP"] is not None and r["dSWE"] <= 0 and r["dP"] <= 0]
        bare = [r["B"] for r in srows if r["median_depth"] <= 1]
        dry_all += dry
        sp = spikes([p for p in win.get("SNWD", []) if p[1] >= 0])
        storms = sorted((r for r in rows if r["B"] >= STORM_IN), key=lambda r: -r["B"])
        log("%s: %d winter windows, %d dry-spell, %d summer bare-ground, %d spikes, %d storm days"
            % (name, len(rows), len(dry), len(bare), len(sp), len(storms)))
        lines.append("\n== %s (%s)" % (name, trip))
        for label, xs in (("dry-spell B", dry), ("summer bare-ground B", bare)):
            lines.append("%-22s n=%4d  p50 %s  p90 %s  p95 %s  p99 %s  max %s"
                         % (label, len(xs), pct(xs, 50), pct(xs, 90), pct(xs, 95), pct(xs, 99), max(xs) if xs else None))
        biggest = sorted(sp, key=lambda x: -abs(x[1]))[:5]
        lines.append("spikes >= %.0f in: %d; largest: %s" % (SPIKE_IN, len(sp), ", ".join("%s %+.1f" % (t.strftime("%m-%d %H:%M"), d) for t, d in biggest)))
        lines.append("storm days (B >= %.0f in): %d; B and B3 differ on %d" % (STORM_IN, len(storms), sum(1 for r in storms if r["B"] != r["B3"])))
        lines.append("  window end            A      B     B3      C   dSWE  density")
        for r in storms[:6]:
            dens = "%5.1f%%" % (100 * r["dSWE"] / r["B"]) if r["dSWE"] is not None else "    -"
            dswe = "%6.2f" % r["dSWE"] if r["dSWE"] is not None else "     -"
            lines.append("  %s %6.1f %6.1f %6.1f %6.1f %s  %s" % (r["end"][:16], r["A"], r["B"], r["B3"], r["C"], dswe, dens))
        figure(plt, trip, name, win, storms[:6])
    lines.insert(0, "Pooled dry-spell B, all five sites: n=%d  p90 %s  p95 %s  p99 %s  max %s"
                 % (len(dry_all), pct(dry_all, 90), pct(dry_all, 95), pct(dry_all, 99), max(dry_all) if dry_all else None))
    with open(os.path.join(OUT, "summary.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
```

Add `snotel_check/out/` as a new line in `.gitignore` (after `rivers/out/`).

- [ ] **Step 2: Run it**

Run: `python snotel_check/check_newsnow.py` (from `radar/`; first run pulls ~16 months × 5 sites, allow 10 min: `timeout: 600000`).
Expected: five `fig_*.png`, five `windows_*.csv`, `summary.txt` and `accounting.log` in `snotel_check/out/`; the printed summary starts with the pooled dry-spell line. If a site returns no SNWD or `rows` is empty (the CSV writer fails on `rows[0]`), stop and report the site to Chris; don't swap sites silently.

- [ ] **Step 3: Sanity checks before showing anything**

1. One window by hand: open `out/windows_791.csv`, take the row with the largest `B`; in `out/raw_791_2025-10-01.json` list the 25 SNWD readings from 24 h before its `end` to `end`; confirm the largest low-to-later-high rise equals `B` and `end` minus `start` equals `A`. Write the row, the readings and the result into the report for Chris.
2. Accounting: in `accounting.log`, expected hours per element are 5,832 for the winter; flag any site/element returning under 90 % of that.
3. Look at every figure (Read the PNGs). Anything physically odd (depth jumping 20 in and back, a flat line for weeks mid-winter, densities under 3 % or over 30 %) goes to Chris with rival explanations (at least one instrument artefact, one real), what each predicts, and the evidence that would tell them apart. Log each in `radar/ANOMALY_LOG.md` (create it: title `# Anomaly log (radar)`, one `##` entry per anomaly with seen / figure / hypotheses / tests / Chris's input / status / decision). Do not change any parameter to absorb one.

- [ ] **Step 4: Write `snotel_check/METHOD.md`**

Find a published evaluation of ultrasonic snow-depth sensors and read it. Candidate: Ryan, Doesken and Fassnacht (2008), "Evaluation of ultrasonic snow depth sensors for U.S. snow measurements", *Journal of Atmospheric and Oceanic Technology* 25, 667–684. Confirm the citation and open the paper (use the in-app browser; AMS journals). Quote, with the page number, what it says about (a) the sensor's accuracy or noise and (b) its behaviour during snowfall or settling. If it can't be opened, find another peer-reviewed evaluation and tell Chris which one you used and why. Never paraphrase a number you haven't read.

Then write the card:
```markdown
# Method card: new snow as a storm total

**What it does.** For a window (12–72 h on the SNOTEL layer, 1–24 h for Weather stations and the "New snow"
interpolation) it takes the station's hourly snow-depth readings and reports the largest rise from any reading
to a later, higher reading in that window. Rises below the noise floor count as 0. Code: `newsnow.py`.

**Intuition.** New snow shows up as the depth climbing. Once snowfall stops, the new layer settles, so the depth
at the end of the window understates what fell. Measuring from the low point before the rise to the peak after it
gives the snowfall before settling eats into it: what "we got 14 inches last night" means.

**Assumptions.**
- The sensor's patch of ground gets the same snow as its surroundings (no drifting or scouring under it).
- One storm dominates the window. With two storms and settling between them, the larger rise is reported, not the sum.
- Hourly readings; the window's first reading is within 1 h of its start and the latest within 3 h of now.

**Failure modes.**
- One-hour spikes (falling snow or an animal in the beam) inflate the total: the despike filter handles them if the
  check shows they matter.
- Wind drifting under the sensor reads as new snow; scouring hides it.
- Two storms in one window: understated (conservative). Summing every rise instead would add up sensor noise.
- Rain on snow: depth falls, the total is 0 although precipitation fell (the precipitation gauge covers that).

**Parameters.** `snotel_config.yaml` (value, source category, derivation, where used).

**Simpler methods shown beside it in the check.** A = end minus start (what the map showed before), C = end minus
the window's lowest reading.

**Independent check.** Implied new-snow density = pillow SWE gain ÷ storm total, from a different sensor (the
pillow, not the ultrasonic). Fresh snow is typically about 5–20 % water; a storm far outside that is investigated.

**Reference.** <author, year, title, journal, volume, pages>; p. <n>: "<quote on accuracy/noise>"; p. <n>: "<quote on
snowfall or settling>".
```
Replace the last paragraph's angle brackets with what you read; nothing else in the card is a placeholder.

- [ ] **Step 5: Commit the script, card and ignore rule (not the outputs)**

```bash
git add snotel_check/check_newsnow.py snotel_check/METHOD.md .gitignore
git commit -m "snotel_check: new-snow method check at five test sites, method card" -- snotel_check/check_newsnow.py snotel_check/METHOD.md .gitignore
```
If `ANOMALY_LOG.md` was created, add it to the same commit.

---

### Task 3: GATE: Chris approves the method and the values

**Files:**
- Modify: `snotel_config.yaml` (values, `derived`, `approved:`)

- [ ] **Step 1: Show Chris the results**

Send the five figures and `summary.txt` with SendUserFile. In chat, walk through: what each panel shows; the hand check from Task 2 Step 3; pooled and per-site dry-spell percentiles; summer bare-ground scatter; spike counts and whether B and B3 differ on storm days; the density column; anything in `ANOMALY_LOG.md`. Say where you are unsure.

- [ ] **Step 2: Propose values, one at a time, and wait**

1. `noise_floor_in`: propose the pooled dry-spell p95 rounded up to the next 0.5 in, with the p90/p99 alternatives and how many storm days each would zero out.
2. `despike_width`: 3 if spikes change any storm-day B (B ≠ B3), else 1; show the storm days affected.
3. `end_slack_h`: keep 3 unless the check shows otherwise (latency is measured again in Task 5).
Wait for Chris's answer on each. Do not continue on silence.

- [ ] **Step 3: Record his decisions**

Edit `snotel_config.yaml`: set each approved `value`, change `source` to `fitted from data` or `judgment call` as it now is (drop "provisional"), put the evidence in `derived` (e.g. "pooled dry-spell p95 = 1.3 in over n=412 windows, 5 sites, Dec–Mar 2025-26; rounded up"), and set `approved: 2026-MM-DD (Chris, in chat)`.

Run: `python -m pytest tests/test_newsnow.py -v`
Expected: 14 passed (the tests pass their own parameters; only `test_config_file_has_every_parameter` reads the file).

- [ ] **Step 4: Commit and update the handoff**

```bash
git add snotel_config.yaml
git commit -m "snotel_config: new-snow parameters approved by Chris" -- snotel_config.yaml
```
Update `HANDOFF.md` item 3: gate passed, values, next is Task 4.

**STOP here until Chris has approved. Everything below depends on it.**

---

### Task 4: `snotel.py`: the pull, the records, `data/snotel.js`

**Files:**
- Create: `snotel.py`, `tests/test_snotel.py`

**Interfaces:**
- Consumes: `newsnow.new_snow`, `newsnow.storm_total`, `newsnow.window_values`, `newsnow.load_config` (Task 1); `region.cfg()`, `region.bbox()`, `region.data_dir()`.
- Produces:
  - `snotel.build(log=print) -> int` (sites written); writes `data/snotel.js` as `window.SNOTEL = {...};`
  - `snotel.stations_records(windows: list[int], log=print, cfg: dict | None = None) -> list[dict]` in `stations.py`'s record format (`src: "SNOTEL"`, `precip/snow/swe` keyed by int hours, `depth`, `swe_total`, `swe_median`, `swe_pct`, `wy_total`, `wy_median`, `wy_pct`, `temp {now,max,min,spark,t}`, `last`)
  - `snotel.parse(rows, tz_of: dict, daily: bool) -> dict[triplet, dict[key, list[(utc datetime, float)]]]`, element keys `SNWD, WTEQ, PREC, TOBS, SMS2, SMS8, STO20, ...`
  - `snotel.site_record(site: dict, ser: dict, med: dict, now_utc: datetime, cfg: dict) -> dict | None`
  - `window.SNOTEL` = `{updated, updated_t, date, windows: [12..72], soil_depths: [2, 8, 20], sites: [{id, name, net: "SNTL"|"SCAN"|"BC", lat, lon, elev, t (epoch s of latest reading), swe, swe_med, swe_pct, depth, new: {"12": in, ...}, wy, wy_med, wy_pct, p24, temp: {now, max, min, spark}, soil: {"2": {m, t}, ...}}]}`, or `{note, sites: []}` for a region without SNOTEL.

- [ ] **Step 1: Write the failing tests**

`tests/test_snotel.py`:
```python
"""SNOTEL layer records (snotel.py) from synthetic responses in the AWDB API's shape (no network)."""
import datetime as dt
import json
import time

import snotel

CFG = {"noise_floor_in": 1.0, "despike_width": 1, "start_slack_h": 1, "end_slack_h": 3,
       "max_new_base_in": 6.0, "max_new_per_h_in": 1.0}
NOW = dt.datetime(2026, 1, 10, 15, 30)       # naive UTC = 07:30 PST
SITE = {"id": "791:WA:SNTL", "name": "Stevens Pass", "net": "SNTL", "lat": 47.74, "lon": -121.09,
        "elev": 3940, "tz": -8.0, "huc": "170200"}
MED = {"791:WA:SNTL": {"swe": (13.5, 15.0), "wy": (31.0, 25.0)}}
# 74 hourly readings from 2026-01-07 06:00 PST to 2026-01-10 07:00 PST: flat 40 in, a 14 in storm
# ending at midnight, then 4 in of settling
DEPTH = [40] * 60 + [42, 44, 46, 48, 50, 52, 54] + [53, 52, 52, 51, 51, 50, 50]
PREC = [30.0] * 62 + [30.2, 30.5, 30.9, 31.3, 31.6, 31.8, 31.9] + [31.9] * 5
WTEQ = [12.0] * 60 + [12.3, 12.6, 12.9, 13.2, 13.4, 13.6, 13.7] + [13.7] * 7


def awdb(triplet, elements, start_local, daily=False):
    """elements: {"SNWD": [...], "SMS:-2": [...]}, one value per hour (or day) from start_local, station time"""
    step = dt.timedelta(days=1) if daily else dt.timedelta(hours=1)
    fmt = "%Y-%m-%d" if daily else "%Y-%m-%d %H:%M"
    data = []
    for key, vals in elements.items():
        code, _, depth = key.partition(":")
        se = {"elementCode": code}
        if depth:
            se["heightDepth"] = int(depth)
        data.append({"stationElement": se,
                     "values": [{"date": (start_local + i * step).strftime(fmt), "value": v} for i, v in enumerate(vals)]})
    return [{"stationTriplet": triplet, "data": data}]


def stevens():
    rows = awdb("791:WA:SNTL", {"SNWD": DEPTH, "PREC": PREC, "WTEQ": WTEQ, "TOBS": [25] * 74,
                                "SMS:-2": [22.5] * 74, "STO:-2": [33] * 74, "SMS:-8": [30.1] * 74},
                dt.datetime(2026, 1, 7, 6, 0))
    return snotel.parse(rows, {"791:WA:SNTL": -8.0}, False)["791:WA:SNTL"]


def test_station_time_is_converted_to_utc():
    # read as UTC, the last reading (07:00 PST) would be 8.5 h old and every window would be empty
    rec = snotel.site_record(SITE, stevens(), MED, NOW, CFG)
    assert rec["new"] == {"12": 10.0, "24": 14.0, "36": 14.0, "48": 14.0, "60": 14.0, "72": 14.0}


def test_site_record_carries_everything_the_popup_shows():
    rec = snotel.site_record(SITE, stevens(), MED, NOW, CFG)
    assert rec["depth"] == 50 and rec["swe"] == 13.7
    assert rec["swe_pct"] == 90 and rec["swe_med"] == 15.0
    assert rec["wy"] == 31.0 and rec["wy_pct"] == 124
    assert rec["p24"] == 1.9
    assert rec["temp"]["now"] == 25 and len(rec["temp"]["spark"]) == 25
    assert rec["soil"] == {"2": {"m": 22.5, "t": 33.0}, "8": {"m": 30.1, "t": None}}
    assert rec["t"] == int(dt.datetime(2026, 1, 10, 15, 0, tzinfo=dt.timezone.utc).timestamp())


def test_zero_median_gives_no_percent():
    rec = snotel.site_record(SITE, stevens(), {"791:WA:SNTL": {"swe": (0.0, 0.0), "wy": (0.4, 0.0)}}, NOW, CFG)
    assert rec["swe_med"] == 0.0 and "swe_pct" not in rec
    assert "wy_pct" not in rec


def test_bc_pillows_report_daily_windows_only():
    bc = dict(SITE, id="2A06P:BC:MSNT", net="BC")
    rows = awdb("2A06P:BC:MSNT", {"SNWD": [80, 80, 86, 92, 90]}, dt.datetime(2026, 1, 6), daily=True)
    ser = snotel.parse(rows, {"2A06P:BC:MSNT": -8.0}, True)["2A06P:BC:MSNT"]
    rec = snotel.site_record(bc, ser, {}, NOW, CFG)
    assert rec["new"] == {"24": 0.0, "48": 6.0, "72": 12.0}


def test_scan_sites_carry_soil_only():
    scan = dict(SITE, id="2069:WA:SCAN", net="SCAN")
    rows = awdb("2069:WA:SCAN", {"SMS:-2": [18.0] * 74, "STO:-2": [36] * 74, "PREC": PREC}, dt.datetime(2026, 1, 7, 6, 0))
    ser = snotel.parse(rows, {"2069:WA:SCAN": -8.0}, False)["2069:WA:SCAN"]
    rec = snotel.site_record(scan, ser, {}, NOW, CFG)
    assert rec["soil"]["2"] == {"m": 18.0, "t": 36.0}
    assert not {"swe", "depth", "new", "wy"} & set(rec)


def test_stations_records_keep_the_old_format():
    snotel._LAST.update(t=time.time(), sites=[SITE], series={"791:WA:SNTL": stevens()}, med=MED, now=NOW)
    (rec,) = snotel.stations_records([1, 3, 6, 12, 24], log=lambda *a: None, cfg=CFG)
    assert rec["src"] == "SNOTEL"
    assert rec["snow"][12] == 10.0 and rec["snow"][24] == 14.0
    assert rec["precip"][24] == 1.9
    assert rec["swe_pct"] == 90 and rec["wy_pct"] == 124 and rec["depth"] == 50


def test_region_without_snotel_writes_a_note(tmp_path, monkeypatch):
    out = tmp_path / "snotel.js"
    monkeypatch.setattr(snotel, "OUT", str(out))
    monkeypatch.setattr(snotel.region, "cfg", lambda: {"snotel_states": []})
    assert snotel.build(log=lambda *a: None) == 0
    text = out.read_text(encoding="utf-8")
    assert text.startswith("window.SNOTEL = ")
    data = json.loads(text[len("window.SNOTEL = "):].rstrip().rstrip(";"))
    assert data["sites"] == [] and data["note"]
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `python -m pytest tests/test_snotel.py -v`
Expected: collection error, `ModuleNotFoundError: No module named 'snotel'`.

- [ ] **Step 3: Write `snotel.py`**

```python
"""
SNOTEL layer data from the NRCS AWDB API, rebuilt by the hourly job just before stations.py.

One pull per run:
  * US SNOTEL, hourly, the last 74 h: snow depth, SWE, precipitation, air temperature, and soil moisture
    and soil temperature at 2, 4, 8, 20 and 40 in
  * NRCS SCAN soil-climate sites, hourly, same window (the map shows them only for soil)
  * BC snow pillows, daily, the last 4 days
  * daily SWE and water-year precipitation medians (1991-2020) for yesterday
Writes data/snotel.js -> window.SNOTEL and keeps the pull in memory, so stations.py takes SNOTEL in its
own 1-24 h format (stations_records) without a second pull.

AWDB stamps hourly values in each station's standard time (dataTimeZone, e.g. -8) all year; everything
here is converted to naive UTC before windows are cut. New snow is newsnow.py's storm total.

Run standalone:  python snotel.py
"""
import collections
import datetime as dt
import json
import os
import time
import urllib.parse
import urllib.request

import newsnow
import region

DATA = region.data_dir()
OUT = os.path.join(DATA, "snotel.js")
META_CACHE = os.path.join(DATA, "snotel_meta_cache.json")
API = "https://wcc.sc.egov.usda.gov/awdbRestApi/services/v1/"
UA = "BlackwaterRadar/1.0 (weather map)"
WINDOWS = [12, 24, 36, 48, 60, 72]
BC_WINDOWS = [24, 48, 72]
SOIL_DEPTHS = [2, 4, 8, 20, 40]
PULL_H = 74
BC_FRESH_H = 36          # a BC daily value is current if it is at most this old
HOURLY = "SNWD,WTEQ,PREC,TOBS," + ",".join("%s:-%d" % (c, d) for c in ("SMS", "STO") for d in SOIL_DEPTHS)
CHUNK = 60
BASE_KEYS = {"id", "name", "net", "lat", "lon", "elev", "t"}
_LAST = {"t": 0, "sites": None, "series": None, "med": None, "now": None}


def fetch(url, timeout=120, tries=2):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())
        except Exception:  # noqa: BLE001
            if i == tries - 1:
                raise
            time.sleep(3)


def in_window(lat, lon):
    lat0, lat1, lon0, lon1 = region.bbox()
    return lat0 <= lat <= lat1 and lon0 <= lon <= lon1


def site_meta(log):
    """Active SNOTEL, SCAN and BC sites inside the map window; cached 7 days, only when every request worked."""
    try:
        with open(META_CACHE, encoding="utf-8") as f:
            c = json.load(f)
        if time.time() - c.get("_t", 0) < 7 * 86400:
            return c["sites"]
    except (OSError, ValueError, KeyError):
        pass
    sites, failed = [], False
    for st in region.cfg()["snotel_states"]:
        for net in (["*"] if st == "BC" else ["SNTL", "SCAN"]):
            try:
                rows = fetch(API + "stations?stationTriplets=*:%s:%s&activeOnly=true" % (st, net))
            except Exception as e:  # noqa: BLE001
                log("snotel meta %s:%s failed: %r" % (st, net, e))
                failed = True
                continue
            for s in rows:
                if in_window(s["latitude"], s["longitude"]):
                    sites.append({"id": s["stationTriplet"], "name": s["name"], "net": "BC" if st == "BC" else net,
                                  "lat": s["latitude"], "lon": s["longitude"], "elev": s.get("elevation"),
                                  "tz": s.get("dataTimeZone") or -8.0, "huc": (s.get("huc") or "")[:6]})
    if not failed:
        with open(META_CACHE, "w", encoding="utf-8") as f:
            json.dump({"_t": time.time(), "sites": sites}, f)
    return sites


def _key(se):
    """AWDB stationElement -> 'SNWD', 'SMS2', 'STO20', ..."""
    d = se.get("heightDepth")
    return se["elementCode"] + (str(abs(int(d))) if d not in (None, 0) else "")


def parse(rows, tz_of, daily):
    """AWDB data rows -> {triplet: {key: sorted [(naive UTC datetime, value)]}}"""
    out = {}
    for s in rows:
        tz = tz_of.get(s["stationTriplet"], -8.0)
        ser = out.setdefault(s["stationTriplet"], {})
        for e in s.get("data", []):
            vals = []
            for v in e.get("values", []):
                if v.get("value") is None:
                    continue
                t = dt.datetime.strptime(v["date"], "%Y-%m-%d" if daily else "%Y-%m-%d %H:%M")
                vals.append((t - dt.timedelta(hours=tz), float(v["value"])))
            if vals:
                ser[_key(e["stationElement"])] = sorted(vals)
    return out


def pull(sites, now_utc, log):
    tz_of = {s["id"]: s["tz"] for s in sites}
    us = [s["id"] for s in sites if s["net"] != "BC"]
    bc = [s["id"] for s in sites if s["net"] == "BC"]
    # dates are station time; ask ~10 h wider than needed, windows are cut later in UTC
    begin = (now_utc - dt.timedelta(hours=PULL_H + 10)).strftime("%Y-%m-%d %H:00")
    end = (now_utc + dt.timedelta(hours=2)).strftime("%Y-%m-%d %H:00")
    series = {}
    for i in range(0, len(us), CHUNK):
        q = urllib.parse.urlencode({"stationTriplets": ",".join(us[i:i + CHUNK]), "elements": HOURLY,
                                    "duration": "HOURLY", "beginDate": begin, "endDate": end})
        try:
            series.update(parse(fetch(API + "data?" + q, 180), tz_of, False))
        except Exception as e:  # noqa: BLE001
            log("snotel hourly chunk %d failed: %r" % (i // CHUNK, e))
    for i in range(0, len(bc), CHUNK):
        q = urllib.parse.urlencode({"stationTriplets": ",".join(bc[i:i + CHUNK]), "elements": "SNWD,WTEQ,PREC",
                                    "duration": "DAILY", "beginDate": (now_utc - dt.timedelta(days=4)).strftime("%Y-%m-%d"),
                                    "endDate": now_utc.strftime("%Y-%m-%d")})
        try:
            series.update(parse(fetch(API + "data?" + q), tz_of, True))
        except Exception as e:  # noqa: BLE001
            log("snotel BC chunk failed: %r" % e)
    return series


def medians(sites, day, log):
    """{triplet: {"swe": (value, median), "wy": (value, median)}} for `day` (yesterday)"""
    ids = [s["id"] for s in sites if s["net"] == "SNTL"]
    out = {}
    for i in range(0, len(ids), CHUNK):
        q = urllib.parse.urlencode({"stationTriplets": ",".join(ids[i:i + CHUNK]), "elements": "WTEQ,PREC",
                                    "duration": "DAILY", "beginDate": day, "endDate": day, "centralTendencyType": "MEDIAN"})
        try:
            rows = fetch(API + "data?" + q)
        except Exception as e:  # noqa: BLE001
            log("snotel medians chunk failed: %r" % e)
            continue
        for s in rows:
            for e in s.get("data", []):
                key = "swe" if e["stationElement"]["elementCode"] == "WTEQ" else "wy"
                for v in e.get("values", []):
                    if v.get("value") is not None:
                        out.setdefault(s["stationTriplet"], {})[key] = (v["value"], v.get("median"))
    return out


def pct(val, med):
    return round(100.0 * val / med) if val is not None and med else None


def latest(ser, now_utc, max_age_h):
    """last value if it is at most max_age_h old, else None"""
    if not ser or (now_utc - ser[-1][0]).total_seconds() > max_age_h * 3600:
        return None
    return ser[-1][1]


def accum_change(ser, t_end, hours, cfg):
    """rise of an accumulating element (PREC, WTEQ) over the window, never below 0; None without coverage"""
    vals = newsnow.window_values(ser or [], t_end, hours, cfg["start_slack_h"], cfg["end_slack_h"])
    return None if vals is None else round(max(0.0, vals[-1] - vals[0]), 2)


def _new_snow(site, ser, now_utc, cfg):
    snwd = [p for p in ser.get("SNWD", []) if p[1] >= 0]
    if site["net"] != "BC":
        out = newsnow.new_snow(snwd, now_utc, WINDOWS, cfg)
    else:       # daily pillows: the last w/24 + 1 daily readings
        vals = [v for _, v in snwd]
        fresh = bool(snwd) and (now_utc - snwd[-1][0]).total_seconds() <= BC_FRESH_H * 3600
        out = {}
        for w in BC_WINDOWS:
            n = w // 24 + 1
            v = newsnow.storm_total(vals[-n:], cfg["noise_floor_in"], 1) if fresh and len(vals) >= n else None
            out[w] = None if v is None or v > cfg["max_new_base_in"] + cfg["max_new_per_h_in"] * w else v
    return {str(w): v for w, v in out.items() if v is not None}


def site_record(site, ser, med, now_utc, cfg):
    """one entry of window.SNOTEL.sites, or None when the site returned nothing"""
    last_t = max((s[-1][0] for s in ser.values() if s), default=None)
    if last_t is None:
        return None
    fresh_h = BC_FRESH_H if site["net"] == "BC" else cfg["end_slack_h"]
    rec = {"id": site["id"], "name": site["name"], "net": site["net"], "lat": site["lat"], "lon": site["lon"],
           "elev": site["elev"], "t": int(last_t.replace(tzinfo=dt.timezone.utc).timestamp())}
    m = med.get(site["id"], {})
    if site["net"] != "SCAN":
        swe = latest(ser.get("WTEQ"), now_utc, fresh_h)
        depth = latest([p for p in ser.get("SNWD", []) if p[1] >= 0], now_utc, fresh_h)
        if swe is not None:
            rec["swe"] = swe
        if "swe" in m and m["swe"][1] is not None:
            rec["swe_med"] = m["swe"][1]
            if pct(*m["swe"]) is not None:
                rec["swe_pct"] = pct(*m["swe"])
        if depth is not None:
            rec["depth"] = depth
        new = _new_snow(site, ser, now_utc, cfg)
        if new:
            rec["new"] = new
        if "wy" in m:
            rec["wy"] = m["wy"][0]
            if m["wy"][1] is not None:
                rec["wy_med"] = m["wy"][1]
                if pct(*m["wy"]) is not None:
                    rec["wy_pct"] = pct(*m["wy"])
    if site["net"] != "BC":
        p24 = accum_change(ser.get("PREC"), now_utc, 24, cfg)
        if p24 is not None:
            rec["p24"] = p24
    tv = [(t, v) for t, v in ser.get("TOBS", []) if -60 < v < 130 and t > now_utc - dt.timedelta(hours=25)]
    if tv and (now_utc - tv[-1][0]).total_seconds() <= cfg["end_slack_h"] * 3600:
        rec["temp"] = {"now": round(tv[-1][1]), "max": round(max(v for _, v in tv)),
                       "min": round(min(v for _, v in tv)), "spark": [round(v) for _, v in tv[-25:]]}
    soil = {}
    for d in SOIL_DEPTHS:
        mv = latest([p for p in ser.get("SMS%d" % d, []) if 0 <= p[1] <= 100], now_utc, cfg["end_slack_h"])
        st = latest([p for p in ser.get("STO%d" % d, []) if -40 <= p[1] <= 130], now_utc, cfg["end_slack_h"])
        if mv is not None or st is not None:
            soil[str(d)] = {"m": mv, "t": st}
    if soil:
        rec["soil"] = soil
    return rec


def _write(obj):
    tmp = OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("window.SNOTEL = " + json.dumps(obj, separators=(",", ":")) + ";")
    os.replace(tmp, OUT)


def build(log=print):
    now_utc = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None, second=0, microsecond=0)
    if not region.cfg()["snotel_states"]:          # e.g. New England
        _write({"note": "No SNOTEL network in this region", "sites": []})
        _LAST.update(t=time.time(), sites=[], series={}, med={}, now=now_utc)
        log("snotel: no SNOTEL network in this region")
        return 0
    cfg = newsnow.load_config()
    t0 = time.time()
    sites = site_meta(log)
    series = pull(sites, now_utc, log)
    day = (dt.datetime.now() - dt.timedelta(days=1)).strftime("%Y-%m-%d")
    med = medians(sites, day, log)
    recs, why = [], collections.Counter()
    for s in sites:
        ser = series.get(s["id"])
        r = site_record(s, ser, med, now_utc, cfg) if ser else None
        if r is None:
            why["no data returned"] += 1
        elif not set(r) - BASE_KEYS:
            why["nothing current"] += 1
        else:
            recs.append(r)
    _write({"updated": dt.datetime.now().strftime("%a %b %d %I:%M %p"), "updated_t": int(time.time()), "date": day,
            "windows": WINDOWS, "soil_depths": [2, 8, 20], "sites": recs})
    _LAST.update(t=time.time(), sites=sites, series=series, med=med, now=now_utc)
    log("snotel: %d sites requested, %d written %s, dropped %s, %.0f s, %d KB"
        % (len(sites), len(recs), dict(collections.Counter(r["net"] for r in recs)), dict(why) or "none",
           time.time() - t0, os.path.getsize(OUT) // 1024))
    return len(recs)


def _label(t_utc):
    return t_utc.replace(tzinfo=dt.timezone.utc).astimezone().strftime("%I:%M %p").lstrip("0")


def stations_records(windows, log=print, cfg=None):
    """SNOTEL and BC sites in stations.py's record format for `windows` (hours). Reuses this process's
    pull when build() ran in the last 90 minutes; otherwise runs build() first."""
    if _LAST["series"] is None or time.time() - _LAST["t"] > 90 * 60:
        build(log)
    cfg = cfg or newsnow.load_config()
    now_utc, out = _LAST["now"], []
    for s in _LAST["sites"] or []:
        ser = (_LAST["series"] or {}).get(s["id"])
        if not ser or s["net"] == "SCAN":
            continue
        rec = {"id": s["id"], "name": s["name"], "src": "SNOTEL", "lat": s["lat"], "lon": s["lon"], "elev": s["elev"],
               "precip": {}, "snow": {}, "swe": {}}
        snwd = [p for p in ser.get("SNWD", []) if p[1] >= 0]
        if s["net"] == "BC":        # daily pillows: 24 h change only
            for key, code in (("precip", "PREC"), ("swe", "WTEQ")):
                v = ser.get(code, [])
                if len(v) >= 2:
                    rec[key] = {24: round(max(0.0, v[-1][1] - v[-2][1]), 2)}
            if len(snwd) >= 2:
                rec["snow"] = {24: newsnow.storm_total([snwd[-2][1], snwd[-1][1]], cfg["noise_floor_in"], 1)}
            if snwd:
                rec["last"] = snwd[-1][0].strftime("%m-%d")
        else:
            rec["precip"] = {w: accum_change(ser.get("PREC"), now_utc, w, cfg) for w in windows}
            rec["swe"] = {w: accum_change(ser.get("WTEQ"), now_utc, w, cfg) for w in windows}
            rec["snow"] = newsnow.new_snow(snwd, now_utc, windows, cfg)
            if ser.get("PREC"):
                rec["last"] = _label(ser["PREC"][-1][0])
            tv = [(t, v) for t, v in ser.get("TOBS", []) if -60 < v < 130 and t > now_utc - dt.timedelta(hours=25)]
            if tv:
                rec["temp"] = {"now": round(tv[-1][1]), "max": round(max(v for _, v in tv)),
                               "min": round(min(v for _, v in tv)), "spark": [round(v) for _, v in tv[-25:]],
                               "t": _label(tv[-1][0])}
        if snwd:
            rec["depth"] = snwd[-1][1]
        if ser.get("WTEQ"):
            rec["swe_total"] = ser["WTEQ"][-1][1]
        m = (_LAST["med"] or {}).get(s["id"], {})
        if "swe" in m:
            rec["swe_median"], rec["swe_pct"] = m["swe"][1], pct(*m["swe"])
        if "wy" in m:
            rec["wy_total"], rec["wy_median"], rec["wy_pct"] = m["wy"][0], m["wy"][1], pct(*m["wy"])
        out.append(rec)
    return out


if __name__ == "__main__":
    build()
```

- [ ] **Step 4: Run the tests to see them pass**

Run: `python -m pytest tests/test_snotel.py tests/test_newsnow.py -v`
Expected: all pass (7 + 14). If `test_bc_pillows_report_daily_windows_only` fails on the 24 h value, check the floor: `[92, 90]` has no rise, so 0.0 is right.

- [ ] **Step 5: Commit**

```bash
git add snotel.py tests/test_snotel.py
git commit -m "snotel.py: one AWDB pull per run for the SNOTEL layer, records for stations.py" -- snotel.py tests/test_snotel.py
```

---

### Task 5: Wire it into the hourly job; local run

**Files:**
- Modify: `stations.py` (docstring lines 1–14; `snotel()` lines 114–220; HADS `SD` block lines 279–282)
- Modify: `capture.py:235-242` (run `snotel` before `stations`)
- Modify: `cloud.py:38-39` (`STATE_FILES`)

**Interfaces:**
- Consumes: `snotel.build`, `snotel.stations_records(windows, log)` (Task 4); `newsnow.new_snow`, `newsnow.load_config` (Task 1).
- Produces: `stations.js` unchanged in shape; SNOTEL records now come from `snotel.py`, SNOTEL and HADS `snow` values are storm totals.

- [ ] **Step 1: Replace `stations.snotel()`**

Replace everything from `def snotel(now, log):` down to (not including) the `# ---------------------------------------------------------------- HADS` line with:
```python
def snotel(now, log):
    if not region.cfg()["snotel_states"]:          # e.g. New England: no SNOTEL network
        return []
    import snotel as sn                               # one NRCS pull per run, shared with the SNOTEL layer
    out = sn.stations_records(WINDOWS, log)
    log("snotel: %d stations" % len(out))
    return out


```
In the module docstring replace the line `  * NRCS SNOTEL (AWDB API): hourly precipitation, snow depth, snow water equivalent` with `  * NRCS SNOTEL, from snotel.py (one pull per run, shared with the SNOTEL layer)`, and add below the `with totals for ...` line: `New snow from depth sensors (SNOTEL, HADS SD) is newsnow.py's storm total.`

- [ ] **Step 2: HADS snow depth uses the storm total**

In `hads()`, replace
```python
            rec["snow"] = {w: (round(s[-1][1] - [v for t, v in s if t <= now - dt.timedelta(hours=w)][-1], 1)
                               if [v for t, v in s if t <= now - dt.timedelta(hours=w)] else None) for w in WINDOWS}
```
with
```python
            rec["snow"] = newsnow.new_snow([p for p in s if p[1] >= 0], now, WINDOWS, newsnow.load_config())
```
and add `import newsnow` after `import region` at the top.

- [ ] **Step 3: Run `snotel.build()` in the hourly job, before stations**

In `capture.py`, inside `if hourly_due:`, insert before the `import stations` try-block:
```python
        try:
            import snotel
            ok.append("snotel %d" % snotel.build(log))
        except Exception as e:  # noqa: BLE001
            log("snotel FAILED: %r" % e)
```
In `cloud.py`, add `"snotel_meta_cache.json"` to `STATE_FILES` (after `"station_meta_cache.json"`).

- [ ] **Step 4: Full test suite**

Run: `python -m pytest tests/ -v`
Expected: all pass (webcams, newsnow, snotel).

- [ ] **Step 5: Local run (no upload), with accounting**

Never call `capture_all()`. From `radar/`, in Git Bash:
```bash
REGION=pnw python -c "import snotel, time; t=time.time(); snotel.build(); import stations; stations.build(); print('total %.0f s' % (time.time()-t))"
```
Then:
```bash
REGION=pnw python -c "
import json, collections, datetime as dt
t = open('regions/pnw/data/snotel.js', encoding='utf-8').read(); d = json.loads(t[t.index('{'):t.rindex('}')+1])
s = d['sites']; now = dt.datetime.now(dt.timezone.utc).timestamp()
print('sites', collections.Counter(x['net'] for x in s))
print('with new', sum(1 for x in s if x.get('new')), '| with soil', sum(1 for x in s if x.get('soil')))
print('latest-reading age h: p50 %.1f max %.1f' % (sorted((now-x['t'])/3600 for x in s)[len(s)//2], max((now-x['t'])/3600 for x in s)))
print('soil moisture exactly 0:', [(x['name'], k) for x in s for k, v in (x.get('soil') or {}).items() if v['m'] == 0])
"
```
Record in the report: sites by network, run time, `snotel.js` size (from the build log line), stations.js SNOTEL count (from `stations.build` log), latest-reading age (evidence for `end_slack_h`), and the list of exactly-0 soil readings (spec judgment call: show Chris, no filter).

- [ ] **Step 6: The BC pillow question (spec open item)**

From the build log line, count `BC` sites written. If it is 0 while `site_meta` lists BC sites: request one BC triplet's daily data by hand (print only the element codes and the last 3 dates/values) and report the cause to Chris (e.g. no current data in September, a network code change, or a parsing miss). Fix only a parsing bug in `snotel.py`, with a test; anything else goes to Chris as a finding.

- [ ] **Step 7: Commit**

```bash
git add stations.py capture.py cloud.py
git commit -m "Hourly job: snotel.py feeds stations.py; SNOTEL and HADS new snow is the storm total" -- stations.py capture.py cloud.py
```

---

### Task 6: Panel: order, Weather stations without SNOTEL, text

**Files:**
- Modify: `map.html` (HTML lines 137–226; JS lines 481, 498–587, 1037; CSS after line 76)

**Interfaces:**
- Produces: element ids `lySnotel`, `snOpt`, `snModes`, `snEls`, `snWins`, `snInfo` and radio name `snEl` for Task 7; `lyBasins` and `basinSel` are gone.

- [ ] **Step 1: Reorder and replace the panel HTML**

1. Move the Weather stations block (`<label class="opt"><input type="checkbox" id="lyStations">` through its closing `</div>` of `.subwrap`) to sit directly after the Radar loop's `.subwrap`, before Rain / snow totals.
2. In Weather stations' `#stModes`, delete the three radios `value="swe"`, `value="swe_pct"`, `value="wy_pct"`. The list becomes Precipitation, New snow, Temperature, Wind.
3. Directly after Rain / snow totals' `.subwrap` (`data-for="lyAccum"`), insert:
```html
    <label class="opt" id="snOpt"><input type="checkbox" id="lySnotel"> SNOTEL
      <button type="button" class="help" aria-label="About the SNOTEL layer" aria-expanded="false">?</button>
      <span class="helptip" role="tooltip">NRCS SNOTEL mountain snow sites, as on the NRCS interactive map. Show the stations, the HUC6 basins or both. Basins exist only for snow water and water-year precipitation (percent of the 1991–2020 median); snow depth, new snow and soil are station readings. New snow is the storm total: the biggest rise in snow depth inside the window, so settling afterwards doesn't erase it.</span></label>
    <div class="subwrap" data-for="lySnotel">
      <div class="sub" id="snModes">
        <button type="button" class="chip on" data-mode="stations">Stations</button>
        <button type="button" class="chip" data-mode="basins">Basins</button>
        <button type="button" class="chip" data-mode="both">Stations &amp; basins</button>
      </div>
      <div class="sub radios" id="snEls">
        <label><input type="radio" name="snEl" value="swe" checked> Snow water equivalent</label>
        <label data-st-only><input type="radio" name="snEl" value="depth"> Snow depth</label>
        <label data-st-only><input type="radio" name="snEl" value="new"> New snow</label>
        <label><input type="radio" name="snEl" value="prec"> Precipitation (water year)</label>
        <label data-st-only><input type="radio" name="snEl" value="sms"> Soil moisture</label>
        <label data-st-only><input type="radio" name="snEl" value="sto"> Soil temperature</label>
      </div>
      <div class="sub" id="snWins"></div>
      <div class="sub" id="snInfo" style="display:block"></div>
    </div>
```
4. In the Snow group, delete the `lyBasins` label (with its `basinSel` select) and its `.subwrap`. Only SNODAS remains.

- [ ] **Step 2: CSS**

After the `.fzlabel` rule add:
```css
  .bslabel { background:rgba(255,255,255,.85); border:0; color:#111; font-weight:700; font-size:11px; padding:0 3px; border-radius:3px; box-shadow:none; }
  .bslabel::before { display:none; }
  .radios label.off { opacity:.4; pointer-events:none; }
```

- [ ] **Step 3: Help tips and texts that named SNOTEL under Weather stations**

1. Radar loop tip: replace `and Weather stations to check what individual gauges and SNOTEL sites measured.` with `Weather stations to check what individual gauges measured, and SNOTEL for the mountain snow sites.`
2. Rain / snow totals tip: replace `The map is smoothed, so turn on Weather stations to see what each gauge and SNOTEL site actually measured.` with `The map is smoothed, so turn on Weather stations (gauges) or SNOTEL (mountain snow sites) to see what each one actually measured.`
3. Line 481, the `snow:` source text: `'snow-depth change at SNOTEL and snow sites, elevation-aware; fades where sparse'` → `'new snow (storm total) at SNOTEL and snow-depth gauges, elevation-aware; fades where sparse'`.
4. Line 1037 (click readout, nearest SNOTEL): replace `', ' + (sn.s.snow['24'] >= 0 ? '+' : '') + fmt(sn.s.snow['24']) + ' in / 24 h'` with `', new snow ' + fmt(sn.s.snow['24']) + ' in / 24 h'`.

- [ ] **Step 4: Weather stations draws no SNOTEL**

In `renderStations()`:
1. Replace `const pctMode = stMode === 'swe_pct' || stMode === 'wy_pct', tempMode = stMode === 'temp', windMode = stMode === 'wind';` with `const tempMode = stMode === 'temp', windMode = stMode === 'wind';` and add below it `const list = stData.stations.filter(s => s.src !== 'SNOTEL');      // SNOTEL has its own layer`.
2. `const bins = ...` → `const bins = tempMode ? TEMP_BINS : windMode ? WIND_BINS : (stMode === 'snow' ? SNOW_BINS : RAIN_BINS);`
3. `for (const s of stData.stations) {` → `for (const s of list) {`
4. Delete the line `if (pctMode) v = s[stMode];` and change the next `else if (tempMode)` to `if (tempMode)`.
5. `const fill = pctMode ? basinColor(v) : (tempMode || windMode) ? ...` → `const fill = (tempMode || windMode) ? binColor(v, bins) : (v <= 0 ? '#8891a0' : binColor(mag, bins));`
6. `const lbl = pctMode ? v + '%' : tempMode ? ...` → `const lbl = tempMode ? v + '°' : windMode ? (!s.wind.spd && !s.wind.gust ? 'calm' : (s.wind.spd != null ? s.wind.spd : '') + (s.wind.gust ? 'g' + s.wind.gust : '')) : fmt(v);`
7. `if (!pctMode && !tempMode && !windMode) (stData.windows || [])...` → `if (!tempMode && !windMode) (stData.windows || [])...`
8. `const legFmt = pctMode ? ... : (tempMode || windMode) ? (x => String(x)) : fmt;` → `const legFmt = (tempMode || windMode) ? (x => String(x)) : fmt;`
9. `const note = pctMode ? 'SNOTEL only, ...' : tempMode ? ...` → `const note = tempMode ? '°F now' : windMode ? 'mph, gust if reported; arrows point downwind' : stMode === 'snow' ? 'inches · CoCoRaHS observers’ 24 h snowfall and storm totals from snow-depth gauges; mountain snow sites are in the SNOTEL layer' : 'inches';`
10. In the `$('stInfo').innerHTML` line, `stData.stations.length` → `list.length`.

In `stationCard()` delete the two lines starting `if (s.swe_total != null)` and `if (s.wy_pct != null)` (only SNOTEL had them). In `stationLink()` delete the `if (s.src === 'SNOTEL')` line.

- [ ] **Step 5: Temporary stub so the page runs until Task 7**

The old basin JS (the `// ---------- snowpack by basin (NRCS) ----------` section, down to and including the `$('lyBasins').onchange = ...` line) still references `lyBasins` and `basinSel`, which no longer exist. Replace that whole section with the Task 7 code now if doing Tasks 6 and 7 in one sitting; otherwise replace it with:
```js
  // ---------- SNOTEL layer: see Task 7 ----------
  const BASIN_BINS = [[150, '#1d2f9e'], [130, '#3d8bd6'], [110, '#7fd3f5'], [90, '#4caf50'], [70, '#f2d33a'], [50, '#f08c1e'], [0, '#d32f2f']];
  function basinColor(p) { if (p == null) return '#9e9e9e'; for (const [lo, c] of BASIN_BINS) if (p >= lo) return c; return '#d32f2f'; }
```
and in `DEF_CHECKS` replace `'lyBasins'` with `'lySnotel'`; in `DEF_SELECTS` delete `'basinSel'`.

- [ ] **Step 6: Check the page loads**

Run `python build_web.py`, then start the preview (Task 9 Step 1 sets it up; use the plain local server if the proxy isn't written yet: `python -m http.server 8796 --bind 127.0.0.1` from `web/`, in the background). In the in-app browser: `read_console_messages` with `onlyErrors: true` must be empty; `read_page` shows the Now & forecast order Radar loop, Weather stations, Rain / snow totals, SNOTEL, Webcams…; Weather stations' mode list has four entries; turning Weather stations on shows no SNOTEL site (`javascript_tool`: count markers whose tooltip text matches a known SNOTEL name, e.g. "Stevens Pass", expect 0 in Weather stations).

- [ ] **Step 7: Commit**

```bash
git add map.html
git commit -m "map: Weather stations above Rain / snow totals and without SNOTEL; SNOTEL panel markup" -- map.html
```

---

### Task 7: The SNOTEL layer

**Files:**
- Modify: `map.html` (replace the old basin section, or the Task 6 stub, with the code below)
- Modify: `build_web.py` (region flag)

**Interfaces:**
- Consumes: `window.SNOTEL` (Task 4 format), `window.BASINS` (`basins.py`, properties `huc6, name, swe_pct, swe_in, swe_n, prec_pct`), page helpers `$`, `loadScript`, `legendHtml`, `binColor`, `fmt`, `tempSpark`, `SNOW_BINS`, `TEMP_BINS`, `REG`, `map`.
- Produces: `snMode, snEl, snWin, snDepth` state and `setSnEl(v)`, `renderSnotel()` for Task 8.

- [ ] **Step 1: Replace the basin section with the SNOTEL layer**

```js
  // ---------- SNOTEL: stations, HUC6 basins or both, like the NRCS interactive map ----------
  const BASIN_BINS = [[150, '#1d2f9e'], [130, '#3d8bd6'], [110, '#7fd3f5'], [90, '#4caf50'], [70, '#f2d33a'], [50, '#f08c1e'], [0, '#d32f2f']];
  function basinColor(p) { if (p == null) return '#9e9e9e'; for (const [lo, c] of BASIN_BINS) if (p >= lo) return c; return '#d32f2f'; }
  // snow depth uses the SNODAS depth legend (snodas.py DEPTH_BINS)
  const DEPTH_BINS = [[1, '#deebf7'], [6, '#c6dbef'], [12, '#9ecae1'], [24, '#6baed6'], [36, '#4292c6'], [48, '#2171b5'], [72, '#08519c'], [96, '#08306b'], [120, '#4a1486'], [180, '#8c1478']];
  // soil moisture, % water by volume: judgment call (muted brown to teal), shown to Chris before release
  const SMS_BINS = [[0, '#8c6d46'], [10, '#b89a6a'], [20, '#d9c89e'], [30, '#9cc3b8'], [40, '#5f9e94'], [50, '#2f6f68']];
  const SN_WINS = ['12', '24', '36', '48', '60', '72'], SN_DEPTHS = ['2', '8', '20'];
  const SN_BASIN_EL = { swe: 'swe', prec: 'prec' };          // elements with an NRCS basin index
  map.createPane('snBasins'); map.getPane('snBasins').style.zIndex = 350;     // basins under every marker
  let snData = null, basinData = null, snMode = 'stations', snEl = 'swe', snWin = '24', snDepth = '2';
  const snLayer = L.layerGroup();
  const snBasinLayer = L.geoJSON(null, {
    pane: 'snBasins',
    style: f => { const v = f.properties[SN_BASIN_EL[snEl] + '_pct']; return { color: '#333', weight: 1, fillColor: basinColor(v), fillOpacity: v == null ? .12 : .45 }; },
    onEachFeature: (f, l) => {
      const p = f.properties, v = p[SN_BASIN_EL[snEl] + '_pct'];
      if (v != null) l.bindTooltip(v + '%', { permanent: true, direction: 'center', className: 'bslabel', interactive: false });
      l.bindPopup('<div style="font:13px system-ui;min-width:200px"><b>' + p.name + '</b> <span style="color:#666">basin ' + p.huc6 + '</span>' +
        '<div style="margin:4px 0">Snow water equivalent: ' + (p.swe_pct == null ? (p.swe_n ? 'no snow on this date normally' : 'no sites') : '<b>' + p.swe_pct + '% of median</b>' + (p.swe_in != null ? ' (' + p.swe_in + ' in avg)' : '')) + '</div>' +
        '<div>Water-year precipitation: ' + (p.prec_pct == null ? 'no value' : '<b>' + p.prec_pct + '% of median</b>') + '</div>' +
        '<div style="color:#666;font-size:12px;margin-top:4px">NRCS SNOTEL, ' + (basinData ? basinData.date : '') + ' · <a href="https://nwcc-apps.sc.egov.usda.gov/imap/" target="_blank" rel="noopener">NRCS map</a></div></div>');
    }
  });
  const snGroup = L.layerGroup([snBasinLayer, snLayer]);
  function snShows(s) {
    if (snEl === 'sms' || snEl === 'sto') return !!s.soil;
    if (s.net === 'SCAN') return false;
    if (snEl === 'new' && s.net === 'BC') return ['24', '48', '72'].includes(snWin);
    return true;
  }
  function snValue(s) {
    if (snEl === 'swe') return s.swe_pct;
    if (snEl === 'prec') return s.wy_pct;
    if (snEl === 'depth') return s.depth;
    if (snEl === 'new') return (s.new || {})[snWin];
    const d = (s.soil || {})[snDepth]; return d ? (snEl === 'sms' ? d.m : d.t) : null;
  }
  function snMissing(s) {       // NRCS iMap symbols: 'obs' observation missing, 'med' median missing
    if (snEl === 'swe') return s.swe == null ? 'obs' : s.swe_pct == null ? 'med' : null;
    if (snEl === 'prec') return s.wy == null ? 'obs' : s.wy_pct == null ? 'med' : null;
    return snValue(s) == null ? 'obs' : null;
  }
  function snColor(v) {
    if (snEl === 'swe' || snEl === 'prec') return basinColor(v);
    if (snEl === 'depth') return v < 1 ? '#8891a0' : binColor(v, DEPTH_BINS);
    if (snEl === 'new') return v <= 0 ? '#8891a0' : binColor(v, SNOW_BINS);
    return binColor(v, snEl === 'sms' ? SMS_BINS : TEMP_BINS);
  }
  function snLabel(v) { return (snEl === 'swe' || snEl === 'prec') ? v + '%' : snEl === 'sms' ? Math.round(v) + '%' : snEl === 'sto' ? Math.round(v) + '°' : snEl === 'depth' ? String(Math.round(v)) : fmt(v); }
  function snSymbol(kind) {    // ⊖ observation missing, ⊗ median missing
    const inner = kind === 'obs' ? '<path d="M3 8 H13" stroke="#333" stroke-width="1.5"/>' : '<path d="M4.5 4.5 L11.5 11.5 M11.5 4.5 L4.5 11.5" stroke="#333" stroke-width="1.5"/>';
    return L.divIcon({ className: '', iconSize: [16, 16], iconAnchor: [8, 8], popupAnchor: [0, -8],
      html: '<svg width="16" height="16" viewBox="0 0 16 16"><circle cx="8" cy="8" r="6" fill="#fff" fill-opacity=".85" stroke="#333" stroke-width="1.5"/>' + inner + '</svg>' });
  }
  function snLink(s) { const m = /^(\d+):/.exec(s.id); return s.net !== 'BC' && m ? 'https://wcc.sc.egov.usda.gov/nwcc/site?sitenum=' + m[1] : null; }
  function snCard(s) {
    const row = (k, v) => '<div>' + k + ': ' + v + '</div>';
    let h = '<div style="font:13px system-ui;min-width:230px"><b>' + s.name + '</b> <span style="color:#666">' + ({ SNTL: 'SNOTEL', SCAN: 'SCAN soil site', BC: 'BC snow pillow' }[s.net] || s.net) + (s.elev ? ' · ' + Math.round(s.elev).toLocaleString() + ' ft' : '') + '</span>';
    if (s.swe != null) h += row('Snow water equivalent', '<b>' + fmt(s.swe) + ' in</b>' + (s.swe_pct != null ? ', <b>' + s.swe_pct + '%</b> of median (' + fmt(s.swe_med) + ' in)' : s.swe_med === 0 ? ', no snow normally on this date' : ''));
    if (s.depth != null) h += row('Snow depth', '<b>' + Math.round(s.depth) + ' in</b>');
    const nw = SN_WINS.filter(w => (s.new || {})[w] != null);
    if (nw.length) h += '<table style="border-collapse:collapse;font-variant-numeric:tabular-nums;margin:6px 0 2px"><tr><td style="padding:1px 6px 1px 0;color:#666">New snow</td>' + nw.map(w => '<th style="padding:1px 6px;font-weight:600">' + w + 'h</th>').join('') + '</tr><tr><td></td>' + nw.map(w => '<td style="padding:1px 6px;text-align:right">' + fmt(s.new[w]) + '</td>').join('') + '</tr></table><div style="font-size:11px;color:#666">inches, storm total</div>';
    if (s.wy != null) h += row('Water-year precipitation', fmt(s.wy) + ' in' + (s.wy_pct != null ? ', <b>' + s.wy_pct + '%</b> of median' : ''));
    if (s.p24 != null) h += row('Precipitation, last 24 h', fmt(s.p24) + ' in');
    if (s.temp) h += row('Temperature', '<b>' + s.temp.now + '°F</b>' + (s.temp.max != null ? ' <span style="color:#666">(24 h ' + s.temp.min + '° to ' + s.temp.max + '°)</span>' : '')) + tempSpark(s.temp.spark);
    const ds = Object.keys(s.soil || {}).sort((a, b) => a - b);
    if (ds.length) h += '<table style="border-collapse:collapse;font-variant-numeric:tabular-nums;margin:6px 0 2px"><tr><th style="text-align:left;padding:1px 6px 1px 0;font-weight:600">Soil</th><th style="padding:1px 6px;font-weight:600">moisture</th><th style="padding:1px 6px;font-weight:600">temp</th></tr>' +
      ds.map(d => '<tr><td style="padding:1px 6px 1px 0;color:#666">' + d + ' in</td><td style="padding:1px 6px;text-align:right">' + (s.soil[d].m != null ? s.soil[d].m.toFixed(1) + '%' : '–') + '</td><td style="padding:1px 6px;text-align:right">' + (s.soil[d].t != null ? Math.round(s.soil[d].t) + '°F' : '–') + '</td></tr>').join('') + '</table>';
    const link = snLink(s), when = s.t ? (s.net === 'BC' ? new Date(s.t * 1000).toLocaleDateString() : new Date(s.t * 1000).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })) : '';
    h += '<div style="color:#666;margin-top:4px">' + (when ? 'last report ' + when : '') + (link ? (when ? ' · ' : '') + '<a href="' + link + '" target="_blank" rel="noopener">station page</a>' : '') + '</div></div>';
    return h;
  }
  function setSnEl(v) { const r = document.querySelector('input[name=snEl][value="' + v + '"]'); if (r) { r.checked = true; snEl = v; } }
  function renderSnotel() {
    snLayer.clearLayers(); snBasinLayer.clearLayers();
    const basinEl = SN_BASIN_EL[snEl], wantBasins = snMode !== 'stations' && !!basinEl, wantStations = snMode !== 'basins';
    document.querySelectorAll('#snEls label[data-st-only]').forEach(l => l.classList.toggle('off', snMode === 'basins'));
    document.querySelectorAll('#snModes .chip').forEach(c => c.classList.toggle('on', c.dataset.mode === snMode));
    if (wantBasins && basinData && !basinData.note) snBasinLayer.addData(basinData);
    let n = 0, shown = 0;
    if (wantStations && snData) {
      const showLabels = map.getZoom() >= 9;
      for (const s of snData.sites || []) {
        if (!snShows(s)) continue;
        shown++;
        const miss = snMissing(s), v = snValue(s);
        let m;
        if (miss) m = L.marker([s.lat, s.lon], { icon: snSymbol(miss) });
        else {
          n++;
          m = L.circleMarker([s.lat, s.lon], { radius: 5, color: '#111', weight: 1, fillColor: snColor(v), fillOpacity: .9 });
          m.bindTooltip(snLabel(v), { permanent: showLabels, direction: 'top', offset: [0, -10], className: 'stlabel', opacity: .95 });
        }
        m.bindPopup(() => snCard(s), { maxWidth: 320 });
        m.on('mouseover', () => { if (!m.isPopupOpen()) m.openPopup(); });
        snLayer.addLayer(m);
      }
    }
    const wEl = $('snWins'); wEl.innerHTML = '';
    const isSoil = snEl === 'sms' || snEl === 'sto';
    const chips = snEl === 'new' ? SN_WINS.map(w => [w, w + 'h']) : isSoil ? SN_DEPTHS.map(d => [d, d + ' in']) : [];
    chips.forEach(([k, t]) => {
      const b = document.createElement('button'); b.type = 'button'; b.className = 'chip' + (k === (snEl === 'new' ? snWin : snDepth) ? ' on' : ''); b.textContent = t;
      b.onclick = () => { if (snEl === 'new') snWin = k; else snDepth = k; renderSnotel(); }; wEl.appendChild(b);
    });
    const pctEl = snEl === 'swe' || snEl === 'prec';
    const bins = pctEl ? BASIN_BINS.slice().reverse() : snEl === 'depth' ? DEPTH_BINS : snEl === 'new' ? SNOW_BINS : snEl === 'sms' ? SMS_BINS : TEMP_BINS;
    const legFmt = pctEl ? (x => x === 0 ? '<50' : x + '%') : snEl === 'sms' ? (x => x + '%') : snEl === 'new' ? fmt : (x => String(x));
    const unit = { swe: 'percent of 1991–2020 median, yesterday', prec: 'water-year precipitation, percent of 1991–2020 median, yesterday', depth: 'inches, latest hourly reading',
      new: 'inches, storm total: the biggest rise in snow depth in the last ' + snWin + ' h', sms: 'percent water by volume, ' + snDepth + ' in deep', sto: '°F, ' + snDepth + ' in deep' }[snEl];
    let head;
    if (!snData) head = 'loading…';
    else if (snData.note) head = snData.note;
    else head = [wantStations ? n + ' of ' + shown + ' sites report this' : '', wantBasins && basinData && basinData.features ? basinData.features.filter(f => f.properties[basinEl + '_pct'] != null).length + ' basins with values' : '', 'as of ' + (snData.updated || '')].filter(Boolean).join(' · ');
    $('snInfo').innerHTML = '<div class="muted">' + head + (snMode === 'basins' ? ' · depth, new snow and soil are stations only' : '') + '</div>' + legendHtml(bins, legFmt) +
      '<div class="note" style="margin-top:18px">' + unit + ' · ⊖ no reading · ⊗ no median · <a href="https://nwcc-apps.sc.egov.usda.gov/imap/" target="_blank" rel="noopener">NRCS map</a></div>';
  }
  function loadSnotel() {
    let left = 2; const done = () => { if (--left === 0) renderSnotel(); };
    loadScript('data/snotel.js', () => { snData = window.SNOTEL || snData; done(); }, () => { snData = snData || { note: 'SNOTEL data not available yet', sites: [] }; done(); });
    loadScript('data/basins.js', () => { basinData = window.BASINS || basinData; done(); }, done);
  }
  $('lySnotel').onchange = e => { if (e.target.checked) { snGroup.addTo(map); if (!snData) loadSnotel(); else renderSnotel(); } else map.removeLayer(snGroup); };
  document.querySelectorAll('#snModes .chip').forEach(c => c.onclick = () => { snMode = c.dataset.mode; if (snMode === 'basins' && !SN_BASIN_EL[snEl]) setSnEl('swe'); renderSnotel(); });
  document.querySelectorAll('input[name=snEl]').forEach(r => r.addEventListener('change', () => { snEl = r.value; renderSnotel(); }));
  map.on('zoomend', () => { if (map.hasLayer(snGroup)) renderSnotel(); });
  setInterval(() => { if (map.hasLayer(snGroup)) loadSnotel(); }, 15 * 60 * 1000);
  if (REG.snotel === false) { $('snOpt').hidden = true; document.querySelector('.subwrap[data-for=lySnotel]').hidden = true; }
```

Also add `.opt[hidden], .subwrap[hidden] { display:none !important; }` to the CSS block from Task 6 Step 2 (`.subwrap.open` would otherwise show a hidden subwrap).

- [ ] **Step 2: Region flag in `build_web.py`**

In the `for key, c in region.REGIONS.items():` loop, after `regions[key] = {...}` add:
```python
    regions[key]["snotel"] = bool(c.get("snotel_states"))
```

- [ ] **Step 3: Load check**

`python build_web.py`, reload the preview. `read_console_messages` (`onlyErrors: true`) must be empty. Turn SNOTEL on: `javascript_tool` → `document.querySelectorAll('.leaflet-interactive').length` > 0 and `$('snInfo')` text is not "SNOTEL data not available yet" once the local `snotel.js` is served (Task 9 proxy). Full walkthrough is Task 9.

- [ ] **Step 4: Commit**

```bash
git add map.html build_web.py
git commit -m "map: SNOTEL layer (stations, basins or both; SWE, depth, new snow, precip, soil)" -- map.html build_web.py
```

---

### Task 8: Saved defaults

**Files:**
- Modify: `map.html` (defaults block, lines ~1095–1134)
- Create: `tests/test_map_defaults.py`

**Interfaces:**
- Consumes: `snMode, snEl, snWin, snDepth`, `setSnEl` (Task 7).
- Produces: `migrateDefault(d)` between the markers `// BEGIN migrateDefault` and `// END migrateDefault`, self-contained (no page globals), so node can run it.

- [ ] **Step 1: Write the failing tests**

`tests/test_map_defaults.py`:
```python
"""Saved-default migration in map.html (migrateDefault), run under node; skipped where node is missing."""
import json
import os
import re
import shutil
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node not installed")


def migrate(d):
    with open(os.path.join(ROOT, "map.html"), encoding="utf-8") as f:
        html = f.read()
    block = re.search(r"// BEGIN migrateDefault[^\n]*\n(.*?)// END migrateDefault", html, re.S).group(1)
    js = block + "\nprocess.stdout.write(JSON.stringify(migrateDefault(" + json.dumps(d) + ")));"
    return json.loads(subprocess.run([NODE, "-e", js], capture_output=True, text=True, check=True).stdout)


def test_basin_layer_becomes_snotel_basins():
    d = migrate({"checks": {"lyBasins": True}, "selects": {"basinSel": "prec"}})
    assert d["checks"]["lySnotel"] is True and d["snMode"] == "basins" and d["snEl"] == "prec"
    assert "lyBasins" not in d["checks"] and "basinSel" not in d["selects"]


def test_weather_stations_snotel_mode_becomes_snotel_stations():
    d = migrate({"checks": {"lyStations": True}, "selects": {}, "stMode": "swe_pct"})
    assert d["checks"]["lySnotel"] is True and d["snMode"] == "stations" and d["snEl"] == "swe"
    assert d["checks"]["lyStations"] is False and d["stMode"] == "precip"


def test_new_snow_water_mode_falls_back_to_new_snow():
    d = migrate({"checks": {"lyStations": True}, "selects": {}, "stMode": "swe"})
    assert d["stMode"] == "snow" and not d["checks"].get("lySnotel")


def test_new_saves_are_left_alone():
    d = {"checks": {"lySnotel": True, "lyStations": False}, "selects": {}, "snMode": "both", "snEl": "new",
         "snWin": "48", "stMode": "wind"}
    assert migrate(dict(d, checks=dict(d["checks"]), selects={})) == d
```

- [ ] **Step 2: Run them to see them fail**

Run: `python -m pytest tests/test_map_defaults.py -v`
Expected: 4 FAIL with `AttributeError: 'NoneType' object has no attribute 'group'` (no marker block yet).

- [ ] **Step 3: Add the migration and save/restore the SNOTEL state**

Directly above `const DEF_KEY = 'radar.default';` insert:
```js
  // BEGIN migrateDefault (tests/test_map_defaults.py runs this block under node)
  function migrateDefault(d) {
    // saves from before 2026-09-27 had "Snowpack by basin" (lyBasins, basinSel) and SNOTEL modes in Weather stations
    if (!d) return d;
    d.checks = d.checks || {}; d.selects = d.selects || {};
    const sm = d.stMode || d.selects.stModeSel;
    if (!('lySnotel' in d.checks)) {
      if (d.checks.lyBasins) { d.checks.lySnotel = true; d.snMode = 'basins'; d.snEl = d.selects.basinSel === 'prec' ? 'prec' : 'swe'; }
      else if (d.checks.lyStations && (sm === 'swe_pct' || sm === 'wy_pct')) { d.checks.lySnotel = true; d.checks.lyStations = false; d.snMode = 'stations'; d.snEl = sm === 'wy_pct' ? 'prec' : 'swe'; }
    }
    if (sm) d.stMode = { swe_pct: 'precip', wy_pct: 'precip', swe: 'snow' }[sm] || sm;
    delete d.checks.lyBasins; delete d.selects.basinSel; delete d.selects.stModeSel;
    return d;
  }
  // END migrateDefault
```
Then:
1. `DEF_CHECKS`: `'lyBasins'` → `'lySnotel'` (if Task 6 Step 5 didn't already). `DEF_SELECTS`: no `'basinSel'`.
2. In `$('saveDefault').onclick`, after `d.stWin = stWin; d.stMode = stMode;` add `d.snMode = snMode; d.snEl = snEl; d.snWin = snWin; d.snDepth = snDepth;`
3. In `applyDefault()`: `const d = readDefault(); if (!d) return;` → `const d = migrateDefault(readDefault()); if (!d) return;`, and before the `DEF_CHECKS.forEach(...)` line add:
```js
    if (d.snMode) snMode = d.snMode;
    if (d.snEl) setSnEl(d.snEl);
    if (d.snWin) snWin = String(d.snWin);
    if (d.snDepth) snDepth = String(d.snDepth);
```
4. In the `DEF_CHECKS.forEach` line of `applyDefault`, skip hidden layers: `const el = $(id);` → `const el = $(id); if (el && el.closest('.opt') && el.closest('.opt').hidden) return;`

- [ ] **Step 4: Run the tests**

Run: `python -m pytest tests/ -v`
Expected: all pass (4 new).

- [ ] **Step 5: Commit**

```bash
git add map.html tests/test_map_defaults.py
git commit -m "map: saved defaults carry over to the SNOTEL layer" -- map.html tests/test_map_defaults.py
```

---

### Task 9: Browser walkthrough on real data

**Files:**
- Create (scratch, not committed): `<session scratchpad>/snotel_preview.py`
- Modify: `C:\Users\16035\Desktop\BlackwaterLabs\.claude\launch.json` (add one configuration; keep the others)

- [ ] **Step 1: Preview proxy**

`<scratchpad>/snotel_preview.py`:
```python
"""Local preview of the map: web/index.html with its data base pointed here. /<region>/data/snotel.js comes from
the local regions/<region>/data/ copy (built in Task 5); files that exist in web/ are served; everything else
redirects to the live R2 bucket. Nothing is uploaded."""
import http.server
import os
import re
import urllib.parse

RADAR = r"C:\Users\16035\Desktop\BlackwaterLabs\radar"
PORT = 8795
WEB = os.path.join(RADAR, "web")
with open(os.path.join(WEB, "index.html"), encoding="utf-8") as f:
    HTML = f.read()
R2 = re.search(r'<meta name="radar-base" content="([^"]+)">', HTML).group(1)
HTML = HTML.replace('<meta name="radar-base" content="%s">' % R2, '<meta name="radar-base" content="http://127.0.0.1:%d/">' % PORT)
LOCAL = {"snotel.js"}


class H(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=WEB, **k)

    def send_bytes(self, body, ctype):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        p = u.path.lstrip("/")
        if p in ("", "index.html"):
            return self.send_bytes(HTML.encode("utf-8"), "text/html; charset=utf-8")
        parts = p.split("/")
        if len(parts) == 3 and parts[1] == "data" and parts[2] in LOCAL:
            f = os.path.join(RADAR, "regions", parts[0], "data", parts[2])
            if os.path.exists(f):
                with open(f, "rb") as fh:
                    return self.send_bytes(fh.read(), "application/javascript")
        if os.path.isfile(os.path.join(WEB, *parts)):
            return super().do_GET()
        self.send_response(302)
        self.send_header("Location", R2 + p + ("?" + u.query if u.query else ""))
        self.end_headers()


http.server.ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
```
Add to `BlackwaterLabs/.claude/launch.json` `configurations`:
```json
    { "name": "radar-snotel-preview", "runtimeExecutable": "C:\\Users\\16035\\anaconda3\\python.exe",
      "runtimeArgs": ["<absolute scratchpad path>\\snotel_preview.py"], "port": 8795 }
```
Run `python build_web.py`, then `preview_start` with `{name: "radar-snotel-preview"}`.

- [ ] **Step 2: Walk every state (pnw, `?r=pnw`)**

For each, check with `read_page`/`javascript_tool`, and screenshot the ones marked (S):
1. Panel order Radar loop → Weather stations → Rain / snow totals → SNOTEL → Webcams; Snow group has only SNODAS. (S)
2. SNOTEL on, Stations, SWE: dots and/or ⊗ symbols (late September: most medians are 0, so ⊗ with "no snow normally on this date" in the popup is correct; see Review Focus 3). (S)
3. Basins + SWE: basin fills, "NN%" labels where values exist; stations-only radios greyed; picking Basins while on Snow depth switches to SWE.
4. Stations & basins + Precipitation (water year): dots over fills, basins under dots (click a dot inside a basin: the dot's popup opens, not the basin's). (S)
5. Snow depth, New snow at each of 12/24/36/48/60/72 (BC sites appear only at 24/48/72), Soil moisture and Soil temperature at 2/8/20 in: basin outlines gone in each; legend and note text match the element. (S for soil moisture: this is the new colour scale Chris must see.)
6. A popup on a soil site (e.g. one with 4 and 40 in sensors) lists every depth.
7. Weather stations on: no SNOTEL names; New snow mode shows CoCoRaHS/HADS only; Rain / snow totals "New snow" still renders (SNOTEL feeds it).
8. Click-anywhere readout: nearest SNOTEL line says "new snow X in / 24 h".
9. Saved defaults: `javascript_tool` → `localStorage.setItem('radar.default', JSON.stringify({when:'test', checks:{lyBasins:true}, selects:{basinSel:'swe'}}))`, reload: SNOTEL on in Basins/SWE. Then remove the key (`localStorage.removeItem('radar.default')`).
10. Phone width: `resize_window` preset mobile, reload, open Layers: SNOTEL block fits, chips wrap. (S) Then `resize_window` preset desktop.
11. `read_console_messages` `onlyErrors: true` empty throughout.

- [ ] **Step 3: Other regions**

`?r=ne`: SNOTEL row absent; no console errors. `?r=utco` (no local `snotel.js` for it unless built: run `REGION=utco python -c "import snotel; snotel.build()"` first): stations and basins render.

- [ ] **Step 4: Show Chris**

SendUserFile the screenshots with one line each on what they show; ask him about the soil moisture colours (judgment call) and the exactly-0 soil readings from Task 5. Record his answers in `HANDOFF.md`; apply any change to `SMS_BINS` and re-check that state.

---

### Task 10: Docs, handoff, release notes for Chris

**Files:**
- Modify: `CLAUDE.md`, `HANDOFF.md`

- [ ] **Step 1: `CLAUDE.md`**

1. "What lives here": in the layer list replace `basin snowpack` with `SNOTEL (stations, basins or both, like NRCS iMap)`.
2. `hourly.yml` row: add `snotel` before `stations` in the list of what it runs.
3. "map.html conventions" globals: add `SNOTEL`.
4. Rules: replace `SNOTEL hourly data is pulled for the last 26 h only.` with `SNOTEL is pulled once per hourly run by snotel.py (74 h hourly, soil sensors, BC daily); stations.py takes its records from there. New snow from any depth sensor is newsnow.py's storm total; its parameters live in snotel_config.yaml (approved by Chris, see snotel_check/).`
5. Timeline: `- 2026-09-27: SNOTEL layer (spec docs/superpowers/specs/2026-09-27-snotel-layer-design.md); new snow as a storm total.`

- [ ] **Step 2: `HANDOFF.md` item 3**

Replace item 3 with: state (built, committed, not pushed/deployed), the release steps below, and anything Chris still owes (soil colours if undecided).

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "CLAUDE.md: SNOTEL layer, snotel.py and newsnow.py" -- CLAUDE.md
```
(`HANDOFF.md` is untracked on purpose; don't add it.)

- [ ] **Step 4: Release, told to Chris (he runs it)**

In chat, in this order, each command in its own `powershell` block:
1. Push: `git -C C:\Users\16035\Desktop\BlackwaterLabs\radar push`
2. Wait for the next hourly run (minute 4 of the hour), then confirm `https://radar-files.blackwaterlabs.org/pnw/data/snotel.js` exists and starts with `window.SNOTEL` (you can fetch it read-only with curl and print only the first 200 characters and the site count). Check the run's log for the `snotel:` accounting line via `gh run list --workflow hourly.yml` / `gh run view <id> --log` (Chris's gh login).
3. Deploy the page: `cd C:\Users\16035\Desktop\BlackwaterLabs\radar; python build_web.py; npx wrangler deploy`
4. After deploy: load `https://radar.blackwaterlabs.org` in the in-app browser and repeat Task 9 Step 2 items 1, 2 and 5 against production.

Then retire `HANDOFF.md` item 3 to one line naming the final commit.
