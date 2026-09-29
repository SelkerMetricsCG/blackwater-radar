"""
Data check for the fires layer (spec: "Data check (gate before any map code)").

Runs fires.build() for one region WITHOUT uploading (it never calls r2sync), then prints:
  1. accounting: WFIGS rows by type, children and out dropped, inside the window; CWFIF rows, BCWS matched and unmatched;
     perimeters with and without an incident; FIRMS rows per file, duplicates removed, inside; NGFS features, distinct
     tracked features, known vs possible; hotspots linked to a fire
  2. independent checks: (a) VIIRS 24 h detections within 2 km of a fire or inside a perimeter, and active fires with
     >= 1 hotspot; big fires without hotspots and dense clusters without a fire; (b) polygon acres vs reported acres;
     (c) every NGFS known_incident_id exists in FIRES
  3. a MATLAB-style figure: the window with perimeters, fires and hotspots; the ten largest active fires as bars

Usage (from the repo root):  python smoke_research/fires_check.py [region]   figure -> smoke_research/checks/fires_check_<region>.png
"""
import json
import math
import os
import sys
import urllib.parse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ["REGION"] = (sys.argv[1] if len(sys.argv) > 1 else "pnw")
sys.path.insert(0, ROOT)

import fires  # noqa: E402
import region  # noqa: E402


def gj(url, params):
    return json.loads(fires.fetch(url + "?" + urllib.parse.urlencode(params))[0])


def main():
    bbox = region.bbox()
    n = fires.build(log=print)
    with open(fires.OUT, encoding="utf-8") as f:
        d = json.loads(f.read()[len("window.FIRES = "):].rstrip().rstrip(";"))
    with open(fires.OUT_PERIMS, encoding="utf-8") as f:
        perims = json.loads(f.read()[len("window.PERIMS = "):].rstrip().rstrip(";"))["features"]
    now = d["updated_t"]
    fl, hs = d["fires"], d["hotspots"]

    # ---- 1. accounting ----
    g = gj(fires.WFIGS_INC + "/query", {"where": "1=1", "outFields": fires.WFIGS_FIELDS, "f": "geojson", "returnGeometry": "true", "outSR": "4326"})
    feats = g["features"]
    by = {}
    for f in feats:
        p = f["properties"]
        by[p.get("IncidentTypeCategory")] = by.get(p.get("IncidentTypeCategory"), 0) + 1
    kept = fires.parse_wfigs(g)
    inside = [r for r in kept if fires.in_window(r["lat"], r["lon"], bbox)]
    print("\n== accounting (%s window) ==" % region.KEY)
    print("WFIGS: %d rows %s; kept %d (WF/CX/RX with a point and IRWIN id, not complex children, not out); inside the window %d"
          % (len(feats), by, len(kept), len(inside)))
    cw = fires.parse_cwfif(gj(fires.CWFIF, {"service": "WFS", "version": "2.0.1", "request": "GetFeature", "outputFormat": "application/json",
                                           "typeName": "public:cwfif_national_activefires", "CQL_FILTER": "now()>=record_start AND now()<=record_end", "srsName": "EPSG:4326"}))
    bc = fires.parse_bcws(gj(fires.BCWS_FIRES + "/query", {"where": "FIRE_STATUS<>'Out'", "outFields": fires.BCWS_FIELDS, "f": "geojson", "returnGeometry": "true", "outSR": "4326"}))
    cw_in = [r for r in cw if fires.in_window(r["lat"], r["lon"], bbox)]
    matched = [r for r in cw_in if r.get("bcnum") in bc]
    bc_only = [k for k, v in bc.items() if v["lat"] is not None and fires.in_window(v["lat"], v["lon"], bbox) and k not in {r.get("bcnum") for r in cw}]
    print("CWFIF: %d national, %d inside; BCWS: %d not out, %d matched to CWFIF inside the window, %d BCWS-only inside"
          % (len(cw), len(cw_in), len(bc), len(matched), len(bc_only)))
    ids = {f["id"] for f in fl}
    print("perimeters: %d in the window, %d with an incident in FIRES, %d without" % (len(perims), sum(p["properties"]["id"] in ids for p in perims),
                                                                                       sum(p["properties"]["id"] not in ids for p in perims)))
    srcs = {}
    for h in hs:
        srcs[h[3]] = srcs.get(h[3], 0) + 1
    print("hotspots: %s; linked to a fire %d of %d; NGFS unconfirmed %d" % (srcs, sum(1 for h in hs if h[5]), len(hs), sum(1 for h in hs if h[6])))
    print("FIRES: %d fires (%d active, %d prescribed, %d Canada, %d with a link)" % (n, sum(f["active"] for f in fl), sum(f["type"] == "RX" for f in fl),
                                                                                    sum(f["src"] != "wfigs" for f in fl), sum(1 for f in fl if f.get("url"))))

    # ---- 2. independent checks ----
    print("\n== check (a): VIIRS detections (24 h) against fires and perimeters ==")
    v24 = [h for h in hs if h[3] == "V" and h[2] <= 24]
    near = sum(1 for h in v24 if h[5])
    print("%d VIIRS detections in 24 h: %d (%.0f%%) within 2 km of a fire or inside a perimeter" % (len(v24), near, 100 * near / max(len(v24), 1)))
    act = [f for f in fl if f["active"]]
    print("%d active fires: %d with >= 1 hotspot in 24 h" % (len(act), sum(1 for f in act if f["hot24"])))
    big_quiet = sorted([f for f in fl if (f["acres"] or 0) >= 1000 and f["hot24"] == 0 and f["active"]], key=lambda f: -(f["acres"] or 0))[:8]
    for f in big_quiet:
        print("  big active fire without hotspots: %s %s ac, %s%% contained, updated %.0f h ago" % (f["name"], f["acres"], f["contained"], (now - (f["modified"] or now)) / 3600))
    cells = {}
    for h in v24:
        if not h[5]:
            k = (round(h[0] / 0.05), round(h[1] / 0.05))
            cells[k] = cells.get(k, 0) + 1
    for k, c in sorted(cells.items(), key=lambda kv: -kv[1])[:5]:
        print("  cluster without a fire: %d detections near %.2f, %.2f" % (c, k[0] * 0.05, k[1] * 0.05))
    print("\n== check (b): polygon acres vs reported acres ==")
    byid = {f["id"]: f for f in fl}
    area = {}
    for p in perims:
        pp = p["properties"]
        if pp["id"] in byid and pp["acres"]:
            area[pp["id"]] = area.get(pp["id"], 0) + pp["acres"]
    diffs, outl = [], []
    for i, a in area.items():
        f = byid[i]
        if not f["acres"]:
            continue
        r = a / f["acres"]
        diffs.append(r)
        if abs(r - 1) > 0.25:
            outl.append((f["name"], a, f["acres"], r))
    diffs.sort()
    outl.sort(key=lambda o: -abs(math.log(max(o[3], 1e-6))))
    if diffs:
        print("%d fires with perimeters: summed polygon acres / reported acres median %.2f, 10th %.2f, 90th %.2f; %d more than 25%% apart" % (
            len(diffs), diffs[len(diffs) // 2], diffs[int(0.1 * (len(diffs) - 1))], diffs[int(0.9 * (len(diffs) - 1))], len(outl)))
    for o in outl[:10]:
        print("  %s: polygons %.0f ac vs reported %.0f ac (x%.2f)" % o)
    print("\n== check (c): NGFS known incidents exist in FIRES ==")
    known = [h for h in hs if h[3] == "G" and not h[6]]
    print("%d NGFS known-incident detections: %d whose fire id is in FIRES" % (len(known), sum(1 for h in known if h[5] in ids)))

    figure(d, perims, now)


def figure(d, perims, now):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.style.use("matlab")
    z, x0, x1, y0, y1 = region.window()
    nn, W = 2 ** z, (x1 - x0 + 1) * 256

    def px(lat, lon):
        mx = (lon + 180) / 360 * nn
        my = (1 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi) / 2 * nn
        return (mx - x0) * 256, (my - y0) * 256

    fig = plt.figure(figsize=(13, 6.5))
    ax = fig.add_axes([0.03, 0.06, 0.5, 0.88])
    for p in perims:
        g = p["geometry"]
        for poly in (g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]):
            xy = [px(c[1], c[0]) for c in poly[0]]
            ax.fill([a for a, _ in xy], [b for _, b in xy], color="#c0392b", alpha=0.25, lw=0.6, ec="#c0392b")
    age_c = {0: "#ff2d00", 1: "#ff9a3c", 2: "#c9a76b"}
    for h in d["hotspots"]:
        x, y = px(h[0], h[1])
        ax.plot(x, y, ".", ms=3 if h[3] == "G" else 2, color=age_c[0 if h[2] < 6 else 1 if h[2] < 24 else 2], mfc="none" if h[6] else None, zorder=2)
    for f in d["fires"]:
        x, y = px(f["lat"], f["lon"])
        s = 20 if (f["acres"] or 0) < 100 else 50 if f["acres"] < 10000 else 110
        ax.scatter([x], [y], s=s, c="#8a8f98" if f["type"] == "RX" else "#d1462f", alpha=1 if f["active"] else 0.4, edgecolors="k", linewidths=0.4, zorder=3)
    ax.set_xlim(0, W)
    ax.set_ylim(W, 0)
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_title("%s: fires (size by acres, grey = prescribed, faded = quiet), perimeters, hotspots by age" % region.KEY, fontsize=10)
    a = fig.add_axes([0.62, 0.1, 0.35, 0.8])
    top = sorted([f for f in d["fires"] if f["active"] and f["acres"]], key=lambda f: -f["acres"])[:10][::-1]
    names = [f["name"][:28] for f in top]
    a.barh(names, [f["acres"] for f in top], color="#d9b8ad", label="reported acres")
    a.barh(names, [f["acres"] * (f["contained"] or 0) / 100 for f in top], color="#b5654a", label="contained share")
    a.set_xlabel("acres")
    a.set_title("ten largest active fires", fontsize=10)
    a.legend(fontsize=8, loc="lower right")
    out = os.path.join(ROOT, "smoke_research", "checks", "fires_check_%s.png" % region.KEY)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    fig.savefig(out, dpi=110)
    print("\nfigure:", out)


if __name__ == "__main__":
    main()
