"""
Data check for the smoke forecast layer (spec: "Data check").

Runs smoke.build() for one region WITHOUT uploading (it never calls r2sync; the local state file is removed first so the
newest run is always rebuilt), then prints:
  1. accounting: run, hours, MB, grid, window coverage, share of pixels >= 2 and >= 9.1 ug/m3, peak with hour and place,
     R2 writes if published
  2. check A (geometry): the drawn value at 2,000 random window pixels against the model's grid points found with
     ecCodes' own latitude/longitude arrays and a k-d tree (no shared code with the Lambert formula); the saved WebP's
     colours against the categories of the field
  3. check B (measurements): HRRR at AirNow monitors and AirFire temporary monitors against their measured PM2.5 for the
     run's analysis hour (model = mean of f00 and f01 at the nearest grid point; also the page's 10 km cell at f01);
     Spearman correlation, median measured - model, sites >= 35.5 either way, and the same correlation with the model
     shifted 25 and 50 km in eight directions (a georeferencing error would make a shift win)
  4. a MATLAB-style figure: the window at f01 with the monitors, measured vs modelled, peak and area by forecast hour

Usage (from the repo root):  python smoke_research/smoke_check.py [region]   figure -> smoke_research/checks/smoke_check_<region>.png
"""
import json
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ["REGION"] = (sys.argv[1] if len(sys.argv) > 1 else "pnw")
sys.path.insert(0, ROOT)

import numpy as np  # noqa: E402

import airquality  # noqa: E402
import region  # noqa: E402
import smoke  # noqa: E402

CAT_NAMES = ["light", "Moderate", "USG", "Unhealthy", "Very unh.", "Hazardous"]


def fields(run):
    """(hour -> window field) for f00..f48 and (hour -> (ug, grid)) for f00 and f01, from the runner cache"""
    out, raw = {}, {}
    for fh in (0,) + smoke.HOURS:
        url = smoke.url_for(run, fh)
        rng = smoke.idx_range(smoke.fetch(url + ".idx")[0].decode(), smoke.RECORD)
        ug, grid = smoke.decode(smoke.fetch_range(url, *rng))
        out[fh] = smoke.resample(ug, grid, smoke.SIZE)
        if fh <= 1:
            raw[fh] = (ug, grid, smoke.fetch_range(url, *rng))
    return out, raw


def monitors(t):
    """measured hourly PM2.5 for the hour starting at t (epoch s): AirNow permanent + AirFire temporary, in the window"""
    bbox = region.bbox()
    recs = []
    try:
        recs += [dict(r, temp=False) for r in airquality.parse_hourly(airquality.fetch(airquality.hourly_url(t))[0].decode("utf-8", "replace"))]
    except Exception as e:  # noqa: BLE001
        print("AirNow hourly file failed:", repr(e))
    try:
        texts = [airquality.fetch(airquality.AIRFIRE + fn)[0].decode("utf-8", "replace") for fn in
                 ("airnow_PM2.5_latest_meta.csv", "airnow_PM2.5_latest_data.csv", "airnow_PM2.5_nowcast_latest_data.csv")]
        recs += [dict(r, temp=True) for r in airquality.parse_airfire(*texts)]
    except Exception as e:  # noqa: BLE001
        print("AirFire files failed:", repr(e))
    lat0, lat1, lon0, lon1 = bbox
    return [r for r in recs if r["t"] == t and r["pm"] is not None and lat0 <= r["lat"] <= lat1 and lon0 <= r["lon"] <= lon1]


def pixel_of(lat, lon, size):
    """window pixel (row, col) of a point, the page's Web Mercator arithmetic"""
    z, x0, x1, y0, y1 = region.window()
    n = 2 ** z
    mx = (lon + 180) / 360 * n
    my = (1 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi) / 2 * n
    return int((my - y0) / (y1 - y0 + 1) * size), int((mx - x0) / (x1 - x0 + 1) * size)


def spearman(a, b):
    from scipy.stats import spearmanr
    a, b = np.asarray(a, float), np.asarray(b, float)
    ok = ~(np.isnan(a) | np.isnan(b))
    return float(spearmanr(a[ok], b[ok])[0]) if ok.sum() >= 5 else float("nan")


def main():
    if os.path.exists(smoke.STORE):
        os.remove(smoke.STORE)
    status = smoke.build(log=print)
    if not status.endswith("new"):
        raise SystemExit("build did not produce a run: " + status)
    with open(smoke.OUT, encoding="utf-8") as f:
        d = json.loads(f.read()[len("window.SMOKE = "):].rstrip().rstrip(";"))
    import datetime as dt
    run = dt.datetime.fromtimestamp(d["run_t"], dt.timezone.utc)
    F, raw = fields(run)
    lat, lon = smoke.window_latlon(smoke.SIZE)

    # ---- 1. accounting ----
    stack = np.stack([F[h] for h in smoke.HOURS])
    inside = ~np.isnan(stack[0])
    pk = np.unravel_index(np.nanargmax(stack), stack.shape)
    mb = sum(len(raw[h][2]) for h in raw) / 1e6
    print("\n== accounting (%s window) ==" % region.KEY)
    print("run %s: %d/48 hours built (f01-f48), grid %dx%d Lambert %.0f m, window %.1f%% inside the model"
          % (d["run_utc"], len(d["hours"]), raw[1][1]["ni"], raw[1][1]["nj"], raw[1][1]["dx"], 100 * inside.mean()))
    print("pixels (all 48 h, inside the model): >= 2 ug/m3 %.2f%%, >= 9.1 %.2f%%, >= 35.5 %.3f%%; peak %.0f ug/m3 at f%02d, %.2fN %.2fE"
          % tuple([100 * np.nanmean(stack >= v) for v in (2, 9.1, 35.5)] + [stack[pk], pk[0] + 1, lat[pk[1]], lon[pk[2]]]))
    print("R2 writes if published: 48 frames + 1 value file + smoke.js + smoke_cache.json = 51 PUTs "
          "(f00/f01 messages here %.1f MB)" % mb)

    # ---- 2. check A: geometry, independent of the Lambert formula ----
    import eccodes
    from PIL import Image
    from scipy.spatial import cKDTree
    hpk = int(pk[0]) + 1
    ug_pk, grid = smoke.decode(smoke.fetch_range(smoke.url_for(run, hpk), *smoke.idx_range(
        smoke.fetch(smoke.url_for(run, hpk) + ".idx")[0].decode(), smoke.RECORD)))
    g = eccodes.codes_new_from_message(raw[1][2])
    glat = eccodes.codes_get_array(g, "latitudes")
    glon = (eccodes.codes_get_array(g, "longitudes") + 180) % 360 - 180
    eccodes.codes_release(g)
    k = math.cos(math.radians(np.mean(lat)))
    sel = (glat > lat.min() - 1) & (glat < lat.max() + 1) & (glon > lon.min() - 1) & (glon < lon.max() + 1)
    tree = cKDTree(np.column_stack([glat[sel], glon[sel] * k]))
    vals = ug_pk.ravel()[sel]
    rng = np.random.default_rng(1)
    rows, cols = np.nonzero(~np.isnan(F[hpk]))
    pick = rng.choice(len(rows), size=min(2000, len(rows)), replace=False)
    # bias the sample toward smoke so the comparison has signal: half the points from pixels >= 2 ug/m3
    smoky = np.nonzero(F[hpk][rows, cols] >= 2)[0]
    if len(smoky):
        pick = np.concatenate([pick[:1000], rng.choice(smoky, size=min(1000, len(smoky)), replace=False)])
    r, c = rows[pick], cols[pick]
    dist, idx = tree.query(np.column_stack([lat[r], lon[c] * k]), k=4)
    drawn = F[hpk][r, c]
    near = vals[idx]
    within = (drawn >= near.min(axis=1) - 1e-3) & (drawn <= near.max(axis=1) + 1e-3)
    diff = np.abs(drawn - near[:, 0])
    print("\n== check A: geometry (f%02d, %d pixels, half of them >= 2 ug/m3) ==" % (hpk, len(pick)))
    print("drawn value within the range of the 4 nearest model points (ecCodes lat/lon + k-d tree): %.1f%%" % (100 * within.mean()))
    print("|drawn - nearest point|: median %.2f, 95th pct %.2f ug/m3; nearest point median %.2f km away"
          % (np.median(diff), np.percentile(diff, 95), np.median(dist[:, 0]) * 111.2))
    frame = np.asarray(Image.open(os.path.join(smoke.FRAME_DIR, "%s%02d.webp" % (d["slot"], hpk))).convert("RGBA"))
    table = smoke.frame_rgba(np.array([np.nan, 3.0, 20, 40, 100, 200, 300]))
    cats = smoke.category(F[hpk])
    got = np.full(cats.shape, -9)
    for ci, px in zip(range(-1, 6), table):
        got[(frame == px).all(axis=2)] = ci
    fine = got == cats
    print("saved frame colours = categories of the field: %.3f%% of %d pixels" % (100 * fine.mean(), fine.size))
    print("value file: series cell (block mean) vs its pixels, checked by the unit tests")

    # ---- 3. check B: monitors ----
    t = d["run_t"]
    obs = monitors(t)
    ug0, grid0, _ = raw[0]
    ug1 = raw[1][0]
    mean01 = (ug0 + ug1) / 2
    ptree = cKDTree(np.column_stack([glat, glon * k]))

    def model_at(la, lo):
        _, i = ptree.query(np.column_stack([la, lo * k]))
        return mean01.ravel()[i]
    olat = np.array([o["lat"] for o in obs])
    olon = np.array([o["lon"] for o in obs])
    opm = np.array([o["pm"] for o in obs], float)
    oin = np.array([smoke.lcc_ij(grid0, a, b)[1] <= grid0["nj"] - 1 for a, b in zip(olat, olon)])
    olat, olon, opm = olat[oin], olon[oin], opm[oin]
    obs = [o for o, keep in zip(obs, oin) if keep]
    mod = model_at(olat, olon)
    with open(os.path.join(smoke.VALUES_DIR, d["series"] + ".js"), encoding="utf-8") as f:
        js = f.read()
    head = json.loads(js.split("]=", 1)[1].split(";", 1)[0])
    cells = np.array(js.split('.data="')[1].split('"')[0].split(","), dtype=np.int64).reshape(head["n"], head["h"], head["w"])
    page = []
    for a, b in zip(olat, olon):
        py, px = pixel_of(a, b, head["w"])
        page.append(cells[0, py, px] * head["scale"] if 0 <= py < head["h"] and 0 <= px < head["w"] and cells[0, py, px] >= 0 else np.nan)
    page = np.array(page, float)
    ntemp = sum(1 for o in obs if o["temp"])
    print("\n== check B: measured PM2.5, hour %s UTC (%d monitors in the window and the model: %d permanent, %d temporary) =="
          % (run.strftime("%Y-%m-%d %H:00"), len(obs), len(obs) - ntemp, ntemp))
    if len(obs) >= 5:
        smoky = (opm >= 20) | (mod >= 10)
        print("Spearman measured vs model (nearest point, mean f00/f01): all %.2f; smoke-affected sites (measured >= 20 or model >= 10, n=%d) %.2f"
              % (spearman(opm, mod), smoky.sum(), spearman(opm[smoky], mod[smoky]) if smoky.sum() >= 5 else float("nan")))
        print("Spearman measured vs the page's 10 km cell at f01: %.2f" % spearman(opm, page))
        print("median measured - model: %.1f ug/m3 (all), %.1f (model < 2: the background the model does not carry)"
              % (np.median(opm - mod), np.median((opm - mod)[mod < 2]) if (mod < 2).any() else float("nan")))
        print("sites measured >= 35.5:", ", ".join("%s %.0f/%.0f" % (o["name"][:22], p, m) for o, p, m in zip(obs, opm, mod) if p >= 35.5) or "none",
              "(measured/model)")
        print("sites modelled >= 35.5:", ", ".join("%s %.0f/%.0f" % (o["name"][:22], m, p) for o, p, m in zip(obs, opm, mod) if m >= 35.5) or "none",
              "(model/measured)")
        base = spearman(opm, mod)
        shifts = []
        for km in (25, 50):
            for ang in range(0, 360, 45):
                dy, dx = km * math.cos(math.radians(ang)) / 111.2, km * math.sin(math.radians(ang)) / (111.2 * k)
                shifts.append((spearman(opm, model_at(olat + dy, olon + dx)), km, ang))
        best = max(shifts)
        print("shift test: unshifted %.2f; best shifted %.2f (%d km toward %d deg); shifted median %.2f"
              % (base, best[0], best[1], best[2], np.median([s[0] for s in shifts])))
    else:
        print("too few monitors for statistics")

    # ---- 4. figure ----
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import ListedColormap, BoundaryNorm
    plt.style.use("matlab")
    fig, ax = plt.subplots(1, 3, figsize=(17, 5.6), gridspec_kw={"width_ratios": [1.25, 1, 1.1]})
    cols = [(0.59, 0.55, 0.50, 0.45)] + [tuple(v / 255 for v in c) + (0.85,) for c in smoke.AQ_COLORS[1:]]
    cmap, norm = ListedColormap(cols), BoundaryNorm([0, 1, 2, 3, 4, 5, 6], 6)
    cat = smoke.category(F[1]).astype(float)
    cat[cat < 0] = np.nan
    LO, LA = np.meshgrid(lon, lat)
    ax[0].pcolormesh(LO, LA, cat, cmap=cmap, norm=norm, shading="auto")
    ax[0].contour(LO, LA, np.isnan(F[1]).astype(float), levels=[0.5], colors="k", linewidths=1, linestyles="--")
    if len(obs):
        oc = np.clip(smoke.category(opm), 0, 5)
        ax[0].scatter(olon, olat, c=[cols[i][:3] if i > 0 else (0.35, 0.6, 0.35) for i in np.where(opm < 9.1, 0, oc)],
                      s=[22 if not o["temp"] else 30 for o in obs], marker="o", edgecolors="k", linewidths=0.4, zorder=3)
    ax[0].set_xlim(lon.min(), lon.max()); ax[0].set_ylim(lat.min(), lat.max())
    ax[0].set_title("HRRR smoke f01 (%s) and measured PM2.5 (dots)" % (run + dt.timedelta(hours=1)).strftime("%d %b %H:00Z"), fontsize=10)
    ax[0].set_xlabel("longitude"); ax[0].set_ylabel("latitude")
    ax[0].set_aspect(1 / math.cos(math.radians(np.mean(lat))))
    if len(obs):
        ax[1].scatter(opm + 0.5, mod + 0.5, s=14, c=["#b0703c" if o["temp"] else "#4f6d8a" for o in obs], alpha=0.8)
        top = max(opm.max(), mod.max(), 50) * 2
        ax[1].plot([0.5, top], [0.5, top], "k--", lw=0.8)
        ax[1].set_xscale("log"); ax[1].set_yscale("log")
        ax[1].set_xlim(0.5, top); ax[1].set_ylim(0.5, top)
    ax[1].set_xlabel("measured PM2.5 + 0.5 (ug/m3)"); ax[1].set_ylabel("HRRR smoke + 0.5 (ug/m3), mean f00/f01")
    ax[1].set_title("monitors, hour from %s (blue AirNow, brown temporary)" % run.strftime("%d %b %H:00Z"), fontsize=10)
    hrs = np.array(smoke.HOURS)
    ax[2].plot(hrs, [np.nanmax(F[h]) for h in hrs], color="#8a5a44", lw=1.5, label="window peak")
    ax[2].set_yscale("log"); ax[2].set_ylabel("window peak (ug/m3)"); ax[2].set_xlabel("forecast hour")
    a2 = ax[2].twinx()
    a2.plot(hrs, [100 * np.nanmean(F[h] >= 9.1) for h in hrs], color="#5f7f6a", lw=1.5, label="area >= 9.1")
    a2.set_ylabel("share of window >= 9.1 ug/m3 (%)")
    ax[2].set_title("run %s: peak and Moderate-or-worse area" % run.strftime("%d %b %HZ"), fontsize=10)
    ax[2].legend(loc="upper left", fontsize=8); a2.legend(loc="upper right", fontsize=8)
    fig.tight_layout()
    out = os.path.join(ROOT, "smoke_research", "checks", "smoke_check_%s.png" % region.KEY)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    fig.savefig(out, dpi=110)
    print("\nfigure:", out)


if __name__ == "__main__":
    main()
