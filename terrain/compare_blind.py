"""
Check 3: the page's walk (work/check/js_results.json from check_js.py) against an independent program written from
METHOD.md alone (its blind_results.json). Prints per place and date: hours of direct sun from each, the first and last
minute, and the share of patch points (41 x 41 at 50 m, three times of day) on which they agree; draws the
disagreements in work/diag/3_blind_vs_page.png and appends one accounting line.

  python terrain/compare_blind.py BLIND_RESULTS.json
"""
import datetime as dt
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    blind = json.load(open(sys.argv[1], encoding="utf-8"))
    page = json.load(open(os.path.join(HERE, "work", "check", "js_results.json"), encoding="utf-8"))
    cases = json.load(open(os.path.join(HERE, "check_cases.json"), encoding="utf-8"))
    n = cases["patch"]["n"]
    tot = agree = 0
    hours_d, edge_d, worst = [], [], []
    print("%-24s %-10s %13s %13s %11s %11s  patch agreement" % ("place", "date", "page h", "blind h", "page 1st", "blind 1st"))
    for pl in cases["places"]:
        for date in cases["dates"]:
            p, b = page[pl["name"]][date], blind[pl["name"]][date]
            hours_d.append(p["hours"] - b["hours"])
            f = lambda w, k: w[0][0] if k == 0 and w else (w[-1][1] if w else None)   # noqa: E731
            for k in (0, 1):
                if f(p["windows"], k) is not None and f(b["windows"], k) is not None:
                    edge_d.append(f(p["windows"], k) - f(b["windows"], k))
            ags = []
            for t in map(str, cases["patch_times_min"]):
                ps, bs = p["patch"][t], b["patch"][t]
                both = [(x, y) for x, y in zip(ps, bs) if x != "-" and y != "-"]
                a = sum(x == y for x, y in both)
                tot += len(both)
                agree += a
                ags.append(100 * a / max(len(both), 1))
                worst.append((100 * a / max(len(both), 1), pl["name"], date, t, ps, bs))
            print("%-24s %-10s %8.1f (%2d) %8.1f (%2d) %11s %11s  %s" % (
                pl["name"], date, p["hours"], len(p["windows"]), b["hours"], len(b["windows"]),
                "%d:%02d" % divmod(p["windows"][0][0], 60) if p["windows"] else "-",
                "%d:%02d" % divmod(b["windows"][0][0], 60) if b["windows"] else "-", " ".join("%.1f%%" % x for x in ags)))
    hours_d, edge_d = np.array(hours_d), np.array(edge_d)
    line = ("page vs blind (%d place-days): patch points agree %.2f%% of %d; hours differ by median %+.2f, max |%.2f| h; "
            "first/last sun minute differ by median %+.0f, max |%.0f| min" % (
                len(hours_d), 100 * agree / tot, tot, np.median(hours_d), np.abs(hours_d).max(),
                np.median(edge_d) if len(edge_d) else 0, np.abs(edge_d).max() if len(edge_d) else 0))
    print(line)
    with open(os.path.join(HERE, "work", "accounting.log"), "a", encoding="utf-8") as fh:
        fh.write("%s  %-9s %s\n" % (dt.datetime.now().strftime("%Y-%m-%d %H:%M"), "blind", line))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    try:
        plt.style.use("matlab")
    except OSError:
        pass
    worst.sort(key=lambda w: w[0])
    fig, axs = plt.subplots(1, 4, figsize=(15, 4.4))
    code = {"1": 2, "0": 0, "-": np.nan}
    for ax, (ag, name, date, t, ps, bs) in zip(axs, worst[:4]):
        pa = np.array([code[c] for c in ps], float).reshape(n, n)
        ba = np.array([code[c] for c in bs], float).reshape(n, n)
        ax.imshow(pa, cmap="gray", vmin=-1, vmax=3, extent=(-1, 1, -1, 1))
        dis = np.where((pa != ba) & np.isfinite(pa) & np.isfinite(ba), 1.0, np.nan)
        ax.imshow(dis, cmap="autumn", vmin=0, vmax=1, extent=(-1, 1, -1, 1))
        ax.set_title("%s\n%s %s:%02d  agree %.1f%%" % (name, date, int(t) // 60, int(t) % 60, ag), fontsize=9)
        ax.set_xlabel("east (km)")
    axs[0].set_ylabel("north (km)")
    fig.suptitle("Page walk (grey: light = sun) with points where the blind program disagrees (orange): the four worst patches")
    os.makedirs(os.path.join(HERE, "work", "diag"), exist_ok=True)
    fig.savefig(os.path.join(HERE, "work", "diag", "3_blind_vs_page.png"), dpi=120, bbox_inches="tight")


if __name__ == "__main__":
    main()
