"""
Data check for the air quality layer (spec: "Data check (gate before any map code)").

Runs airquality.build() for one region WITHOUT uploading (it never calls r2sync), then:
  1. accounting: rows read, PM2.5 rows, inside the window, temporary monitors, skipped and why
  2. independent check: our AQI per permanent station vs USFS AirFire's NowCast for the same monitor and hour,
     converted with the 2024 breakpoints; grid value at each station vs its station AQI
  3. temporary monitors: our breakpoint conversion vs AirNow's own NowCast AQI in AirNowWildfire.csv
  4. a MATLAB-style figure: the grid with stations on top, and three stations' 72 h series

Usage (from radar/):  python smoke_research/aq_check.py [region]      figure -> smoke_research/checks/aq_check_<region>.png
"""
import csv
import io
import json
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ["REGION"] = (sys.argv[1] if len(sys.argv) > 1 else "pnw")
sys.path.insert(0, ROOT)

import airquality  # noqa: E402
import region  # noqa: E402


def text(url):
    return airquality.fetch(url)[0].decode("utf-8", "replace")


def main():
    bbox = region.bbox()
    n = airquality.build(log=print)
    with open(airquality.OUT, encoding="utf-8") as f:
        airq = json.loads(f.read()[len("window.AIRQ = "):].rstrip().rstrip(";"))
    hours = airq["hours"]

    # ---- 1. accounting (newest AirNow file) ----
    perm = [s for s in airq["stations"] if not s["temp"]]
    newest_perm = max((i for s in perm for i, v in enumerate(s["aqi"]) if v is not None), default=len(hours) - 1)
    t = hours[newest_perm]
    body = text(airquality.hourly_url(t))
    lines = body.strip().splitlines()
    recs = airquality.parse_hourly(body)
    inside = [r for r in recs if airquality.in_window(r["lat"], r["lon"], bbox)]
    print("\n== accounting, HourlyAQObs %s ==" % airquality.hourly_url(t).rsplit("_", 1)[1])
    print("rows %d; with a PM2.5 AQI %d; skipped (no PM2.5 AQI, bad or missing fields) %d; inside the %s window %d"
          % (len(lines) - 1, len(recs), len(lines) - 1 - len(recs), region.KEY, len(inside)))
    meta = list(csv.DictReader(io.StringIO(text(airquality.AIRFIRE + "airnow_PM2.5_latest_meta.csv"))))
    tmp = [m for m in meta if m.get("deploymentType") == "Temporary"]
    tmp_in = [m for m in tmp if airquality.in_window(float(m["latitude"]), float(m["longitude"]), bbox)]
    print("AirFire temporary monitors: %d nationally, %d inside the window, %d with a raw value in the last 72 h (on the map)"
          % (len(tmp), len(tmp_in), sum(1 for s in airq["stations"] if s["temp"])))
    print("AIRQ: %d stations written (%d permanent, %d temporary)" % (n, len(perm), n - len(perm)))

    # ---- 2. independent check: AirNow's AQI vs AirFire NowCast -> 2024 breakpoints, same monitor, same hour ----
    # (AirFire's hourly NowCast file, not its "latest" GeoJSON: AirFire's latest hour often runs one ahead of AirNow's newest file)
    nc_rows = list(csv.reader(io.StringIO(text(airquality.AIRFIRE + "airnow_PM2.5_nowcast_latest_data.csv"))))
    perm_dev = {m["deviceDeploymentID"]: m.get("AQSID") for m in meta if m.get("deploymentType") != "Temporary"}
    col = {}
    for i, d in enumerate(nc_rows[0]):
        if d in perm_dev and perm_dev[d] not in col:
            col[perm_dev[d]] = i
    byhour = {}
    for r in nc_rows[1:]:
        try:
            byhour[airquality._stamp(r[0])] = r
        except (ValueError, IndexError):
            pass
    same = within2 = compared = 0
    outliers = []
    for s in perm:
        last = max((i for i, v in enumerate(s["aqi"]) if v is not None), default=None)
        if last is None or s["id"] not in col or hours[last] not in byhour:
            continue
        nc = airquality._num(byhour[hours[last]][col[s["id"]]])
        if nc is None:
            continue
        ours, theirs = s["aqi"][last], airquality.aqi_from_pm25(nc)
        compared += 1
        same += ours == theirs
        within2 += abs(ours - theirs) <= 2
        if abs(ours - theirs) > 5:
            outliers.append((s["name"], ours, theirs, nc))
    print("\n== independent check: AirNow PM25_AQI vs AirFire NowCast (2024 breakpoints), same monitor and hour ==")
    print("compared %d stations: exact %d (%.0f%%), within 2 AQI %d (%.0f%%); research expectation ~93%% / ~97%%"
          % (compared, same, 100 * same / max(compared, 1), within2, 100 * within2 / max(compared, 1)))
    for o in outliers[:15]:
        print("  outlier: %s  AirNow %d  ours-from-AirFire %d  (NowCast %.1f)" % o)

    # grid value at each station vs station AQI (newest hour with both)
    vals_path = os.path.join(region.data_dir(), "values", "aqi.js")
    if airq["grid"] and os.path.exists(vals_path):
        with open(vals_path, encoding="utf-8") as f:
            vt = f.read()
        data = [int(v) for v in vt.split('.data="')[1].split('"')[0].split(",")]
        z, x0, x1, y0, y1 = region.window()
        nn = 2 ** z
        diffs = []
        for s in perm:
            v = s["aqi"][-1] if s["aqi"][-1] is not None else s["aqi"][-2]
            if v is None:
                continue
            mx = (s["lon"] + 180) / 360 * nn
            my = (1 - math.log(math.tan(math.radians(s["lat"])) + 1 / math.cos(math.radians(s["lat"]))) / math.pi) / 2 * nn
            px, py = int((mx - x0) / (x1 - x0 + 1) * 256), int((my - y0) / (y1 - y0 + 1) * 256)
            if 0 <= px < 256 and 0 <= py < 256 and data[py * 256 + px] >= 0:
                diffs.append(abs(data[py * 256 + px] - v))
        diffs.sort()
        if diffs:
            print("grid at %d stations: mean |grid - station| %.1f AQI, median %.0f, 90th pct %.0f (research: mean 1.0 at 713 sites;"
                  " the value grid is 256 x 256 block means, so expect more here)"
                  % (len(diffs), sum(diffs) / len(diffs), diffs[len(diffs) // 2], diffs[int(0.9 * (len(diffs) - 1))]))

    # ---- 3. temporary monitors: our conversion vs AirNow's own NowCast AQI ----
    wf = list(csv.DictReader(io.StringIO(text("https://files.airnowtech.org/airnow/today/AirNowWildfire.csv"))))
    agree = total = 0
    for r in wf:
        c, a = airquality._num(r.get("NowCast Concentration")), airquality._num(r.get("NowCast AQI"))
        if c is None or a is None:
            continue
        total += 1
        agree += airquality.aqi_from_pm25(c) == int(a)
    print("\n== temporary monitors: aqi_from_pm25(NowCast conc) vs AirNow's NowCast AQI (AirNowWildfire.csv, all rows) ==")
    print("%d of %d agree exactly" % (agree, total))

    # ---- 4. figure ----
    figure(airq)


def figure(airq):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from PIL import Image
    plt.style.use("matlab")
    z, x0, x1, y0, y1 = region.window()
    nn, W = 2 ** z, (x1 - x0 + 1) * 256

    def px(lat, lon):
        mx = (lon + 180) / 360 * nn
        my = (1 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi) / 2 * nn
        return (mx - x0) * 256, (my - y0) * 256

    fig = plt.figure(figsize=(13, 6.5))
    ax = fig.add_axes([0.03, 0.06, 0.5, 0.88])
    img = os.path.join(airquality.FRAME_DIR, "aqi.webp")
    if os.path.exists(img):
        ax.imshow(Image.open(img), extent=(0, W, W, 0), alpha=0.55)
    cols = ["#00e400", "#ffff00", "#ff7e00", "#ff0000", "#8f3f97", "#7e0023"]
    for s in airq["stations"]:
        v = next((x for x in reversed(s["aqi"]) if x is not None), None)
        if v is None:
            continue
        cat = sum(v >= e for e in airquality.AQ_EDGES)
        x, y = px(s["lat"], s["lon"])
        ax.scatter([x], [y], s=30, c=cols[cat], edgecolors="k", linewidths=0.5, marker="s" if s["temp"] else "o", zorder=3)
    ax.set_xlim(0, W)
    ax.set_ylim(W, 0)
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_title("%s: AirNow interpolated AQI with stations (squares = temporary)" % region.KEY, fontsize=10)

    def pick(pred):
        return next((s for s in airq["stations"] if pred(s) and sum(v is not None for v in s["aqi"]) > 12), None)
    picks = [("urban", pick(lambda s: not s["temp"] and any(k in s["name"] for k in ("Seattle", "Portland", "Boise", "Reno", "Salt Lake", "Denver", "Boston")))),
             ("mountain valley", pick(lambda s: not s["temp"] and any(k in s["name"] for k in ("Winthrop", "Twisp", "Leavenworth", "Wenatchee", "Cle Elum", "Ellensburg", "Truckee", "Mammoth", "Missoula", "Hamilton", "Aspen", "Steamboat")))),
             ("temporary", pick(lambda s: s["temp"]))]
    hrs = [(t - airq["hours"][-1]) / 3600 for t in airq["hours"]]
    for k, (label, s) in enumerate(picks):
        a = fig.add_axes([0.6, 0.72 - k * 0.31, 0.37, 0.22])
        if not s:
            a.set_title("%s: none in this region" % label, fontsize=9)
            continue
        a.bar(hrs, [v if v is not None else 0 for v in s["aqi"]], width=0.9, color="#8fa7c7", label="AQI")
        a2 = a.twinx()
        a2.plot(hrs, [v if v is not None else float("nan") for v in s["pm"]], color="#b5654a", lw=1.2, label="raw PM2.5")
        a.set_ylabel("AQI", fontsize=8)
        a2.set_ylabel("ug/m3", fontsize=8)
        a.set_title("%s: %s (%s)" % (label, s["name"], s["id"]), fontsize=9)
        a.set_xlim(-72, 1)
    fig.axes[-1].set_xlabel("hours before newest")
    out = os.path.join(ROOT, "smoke_research", "checks", "aq_check_%s.png" % region.KEY)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    fig.savefig(out, dpi=110)
    print("\nfigure:", out)


if __name__ == "__main__":
    main()
