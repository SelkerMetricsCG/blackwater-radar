"""
Method check for the SNOTEL layer's new-snow number (storm total), following
~/.claude/verification-protocol.md. Nothing here feeds the live map.

For the five test sites (spec decision 10) it pulls hourly snow depth, SWE and precipitation for
winter 2025-26 (2025-10-01 to 2026-05-31) and summer 2026 (2026-07-01 to 2026-08-31), then for every
24 h window ending 07:00 station time reports:
  A = end minus start, B = storm total (floor 0, no despike), B3 = storm total after a 3-sample
  running median over the whole record (what the map uses), C = end minus the window's lowest reading,
  dSWE and dP = pillow and gauge rise.
Noise-floor evidence: B and B3 in summer bare-ground windows and in Dec-Mar dry spells (dSWE <= 0 and dP <= 0).
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
MUTED = {"depth": "#5a6f8c", "A": "#9aa3ad", "B": "#9db4c6", "B3": "#4f7a9a", "C": "#b0907a", "storm": "#d9c9a3"}


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
    snwd3 = newsnow.despike_series(snwd, 3)        # smoothed over the whole record, as newsnow.new_snow does
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
                         "B3": newsnow.storm_total(newsnow.window_values(snwd3, t_end, 24), 0.0), "C": round(v[-1] - min(v), 1),
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
    names = {"A": "A: end minus start", "B": "B: storm total, raw", "B3": "B3: storm total after 3-sample median (the map)",
             "C": "C: end minus window low"}
    for key, off in (("A", -0.3), ("B", -0.1), ("B3", 0.1), ("C", 0.3)):
        ax2.bar([i + off for i in x], [r[key] for r in storms], width=0.19, color=MUTED[key], label=names[key])
    for i, r in enumerate(storms):
        if r["dSWE"] is not None and r["B3"] > 0:
            ax2.annotate("%.0f%%" % (100 * r["dSWE"] / r["B3"]), (i + 0.1, r["B3"]), xytext=(0, 3),
                         textcoords="offset points", ha="center", fontsize=8)
    ax2.set_xticks(x)
    ax2.set_xticklabels([r["end"][5:10] for r in storms])
    ax2.set_ylabel("new snow, 24 h to 07:00 (in)")
    ax2.legend(loc="upper right", fontsize=8)
    ax2.set_title("label over each B3 bar: implied new-snow density = pillow SWE gain / B3", fontsize=9)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "fig_%s.png" % trip.split(":")[0]), dpi=130)
    plt.close(fig)


def main():
    os.makedirs(OUT, exist_ok=True)
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.style.use("matlab")
    lines, dry_all, dry3_all = [], [], []
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
        dry_rows = [r for r in rows if dt.datetime.fromisoformat(r["end"]).month in DRY_MONTHS
                    and r["dSWE"] is not None and r["dP"] is not None and r["dSWE"] <= 0 and r["dP"] <= 0]
        dry, dry3 = [r["B"] for r in dry_rows], [r["B3"] for r in dry_rows]
        bare_rows = [r for r in srows if r["median_depth"] <= 1]
        bare, bare3 = [r["B"] for r in bare_rows], [r["B3"] for r in bare_rows]
        dry_all += dry
        dry3_all += dry3
        sp = spikes([p for p in win.get("SNWD", []) if p[1] >= 0])
        storms = sorted((r for r in rows if r["B"] >= STORM_IN), key=lambda r: -r["B"])
        log("%s: %d winter windows, %d dry-spell, %d summer bare-ground, %d spikes, %d storm days"
            % (name, len(rows), len(dry), len(bare), len(sp), len(storms)))
        lines.append("\n== %s (%s)" % (name, trip))
        for label, xs in (("dry-spell B", dry), ("dry-spell B3", dry3), ("summer bare-ground B", bare), ("summer bare-ground B3", bare3)):
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
    for label, xs in (("B3 (3-sample median first)", dry3_all), ("B (raw)", dry_all)):
        lines.insert(0, "Pooled dry-spell %s, all five sites: n=%d  p90 %s  p95 %s  p99 %s  max %s"
                     % (label, len(xs), pct(xs, 90), pct(xs, 95), pct(xs, 99), max(xs) if xs else None))
    with open(os.path.join(OUT, "summary.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
