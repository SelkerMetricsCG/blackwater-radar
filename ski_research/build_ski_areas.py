"""
Builds ski_areas.json (repo root), the list behind the map's ski-report layer: every operating,
lift-served downhill ski area inside the five map windows, from OpenSkiMap's daily ski_areas.geojson
(OpenStreetMap refined with Skimap.org; ODbL), merged with the hand-kept ski_research/overrides.json
(Ikon feed ids, snow-report links, renames, drops, additions).

Run from a PC (not by any job):
    python ski_research/build_ski_areas.py            # uses the cached download in ski_research/work/
    python ski_research/build_ski_areas.py --refetch  # downloads ski_areas.geojson again (~20 MB)
It writes ski_research/work/review.txt: operating downhill areas in the windows that OpenSkiMap has no
lifts for (unmapped lifts or a hike-only hill; add real ones through overrides "add"), and overrides
that no longer match an area.

"Lift-served" = at least one lift of a LIFT_TYPES type in OpenSkiMap's statistics; magic carpets alone
don't count, rope tows do (Chris, 2026-09-28: small local hills in).
Attribution the page must carry (openskidata.org): "Data from OpenSkiData / OpenSkiMap.org,
(c) OpenStreetMap contributors (ODbL), Skimap.org".
"""
import json
import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
import region  # noqa: E402

WORK = os.path.join(HERE, "work")
SRC = os.path.join(WORK, "ski_areas_world.geojson")
OVERRIDES = os.path.join(HERE, "overrides.json")
OUT = os.path.join(ROOT, "ski_areas.json")
URL = "https://tiles.openskimap.org/geojson/ski_areas.geojson"
UA = "BlackwaterRadar-ski-list/1.0 (+https://radar.blackwaterlabs.org)"
LIFT_TYPES = ("cable_car", "gondola", "mixed_lift", "chair_lift", "funicular", "drag_lift", "t-bar", "j-bar",
              "platter", "rope_tow")
M_TO_FT = 3.28084


def region_bbox(key):
    x0, x1, y0, y1 = region.REGIONS[key]["tiles"]
    return region.tile_lat(y1 + 1), region.tile_lat(y0), region.tile_lon(x0), region.tile_lon(x1 + 1)


def fetch(refetch):
    if os.path.exists(SRC) and not refetch:
        return
    os.makedirs(WORK, exist_ok=True)
    req = urllib.request.Request(URL, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=300) as r, open(SRC + ".tmp", "wb") as f:
        f.write(r.read())
    os.replace(SRC + ".tmp", SRC)


def point(f):
    """(lat, lon): OpenSkiMap's viewport centre for outlines, else the point / ring average."""
    hint = (f["properties"].get("viewportHint") or {}).get("center")
    if hint:
        return hint[1], hint[0]
    geom = f["geometry"]
    if geom["type"] == "Point":
        return geom["coordinates"][1], geom["coordinates"][0]
    ring = geom["coordinates"][0] if geom["type"] == "Polygon" else geom["coordinates"][0][0]
    return sum(p[1] for p in ring) / len(ring), sum(p[0] for p in ring) / len(ring)


def regions_of(lat, lon):
    return [k for k in region.REGIONS
            if region_bbox(k)[0] <= lat <= region_bbox(k)[1] and region_bbox(k)[2] <= lon <= region_bbox(k)[3]]


def lift_summary(p):
    """-> (lift count of the types that count, [base_ft, top_ft] or None)"""
    st = (p.get("statistics") or {}).get("lifts") or {}
    by = st.get("byType") or {}
    n = sum((by[t] or {}).get("count", 0) for t in LIFT_TYPES if t in by)
    elev = None
    if st.get("minElevation") is not None and st.get("maxElevation") is not None:
        elev = [int(round(st["minElevation"] * M_TO_FT, -1)), int(round(st["maxElevation"] * M_TO_FT, -1))]
    return n, elev


def main():
    fetch("--refetch" in sys.argv)
    with open(SRC, encoding="utf-8") as f:
        feats = json.load(f)["features"]
    with open(OVERRIDES, encoding="utf-8") as f:
        ov = json.load(f)
    review, out, seen = [], [], set()
    per_region = {k: 0 for k in region.REGIONS}
    for f in feats:
        p = f["properties"]
        if "downhill" not in (p.get("activities") or []) or p.get("status") not in ("operating", None):
            continue
        lat, lon = point(f)
        keys = regions_of(lat, lon)
        if not keys:
            continue
        o = ov.get("areas", {}).get(p["id"][:12], {})      # overrides are keyed by the short id
        n, elev = lift_summary(p)
        name = (o.get("name") or p.get("name") or "").strip()
        if o.get("drop"):
            continue
        if not n and not o.get("keep"):
            review.append("no lifts in OpenSkiMap: %s (%s) at %.4f,%.4f id %s" % (name or "?", "/".join(keys), lat, lon, p["id"]))
            continue
        if not name:
            review.append("unnamed lift-served area at %.4f,%.4f id %s (%d lifts)" % (lat, lon, p["id"], n))
            continue
        e = {"id": p["id"][:12], "name": name, "lat": round(o.get("lat", lat), 4), "lon": round(o.get("lon", lon), 4),
             "lifts": n}
        if elev:
            e["elev_ft"] = elev
        web = o.get("web", (p.get("websites") or [None])[0])
        if web:
            e["web"] = web
        for k in ("report", "mp"):
            if o.get(k) is not None:
                e[k] = o[k]
        if e["id"] in seen:
            raise SystemExit("short id clash: " + p["id"])
        seen.add(e["id"])
        out.append(e)
        for k in keys:
            per_region[k] += 1
    for extra in ov.get("add", []):
        out.append(dict(extra))
    known = {f["properties"]["id"][:12] for f in feats}
    for u in sorted(set(ov.get("areas", {})) - known):
        review.append("override for %s matches no OpenSkiMap area (id changed?)" % u)
    out.sort(key=lambda e: (-e["lat"], e["lon"]))
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        f.write("[\n" + ",\n".join(json.dumps(e, ensure_ascii=False) for e in out) + "\n]\n")
    os.makedirs(WORK, exist_ok=True)
    with open(os.path.join(WORK, "review.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(review) + "\n")
    print("per region:", ", ".join("%s %d" % kv for kv in per_region.items()))
    print("wrote %s: %d areas (%d with the Ikon feed, %d with a snow-report link); %d review lines"
          % (os.path.relpath(OUT, ROOT), len(out), sum(1 for e in out if "mp" in e),
             sum(1 for e in out if "report" in e), len(review)))


if __name__ == "__main__":
    main()
