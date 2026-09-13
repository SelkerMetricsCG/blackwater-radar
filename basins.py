"""
Snowpack and precipitation by basin, NRCS style: for each HUC6 basin, the sum of
SNOTEL snow water equivalent divided by the sum of the sites' 1991-2020 medians
(and the same for water-year precipitation), from the NRCS AWDB API.

Basin outlines come from the USGS Watershed Boundary Dataset (region 17,
Columbia) and are cached in data/huc6.geojson.
Output: data/basins.js -> window.BASINS = FeatureCollection with per-basin stats.

Run standalone:  python basins.py
"""
import datetime as dt
import json
import os
import time
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data")
OUT = os.path.join(DATA, "basins.js")
HUC_FILE = os.path.join(DATA, "huc6.geojson")
UA = "RadarTracker/1.0 (personal weather map; chris.gabrielli@gmail.com)"
LAT0, LAT1, LON0, LON1 = 43.1, 52.5, -126.6, -112.5


def fetch(url, timeout=120):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _round(coords):
    if isinstance(coords[0], (int, float)):
        return [round(coords[0], 4), round(coords[1], 4)]
    return [_round(c) for c in coords]


def simplify(g, tol=0.01):
    """Douglas-Peucker simplify every polygon (tol in degrees, ~1 km) to keep the file small."""
    try:
        from shapely.geometry import shape, mapping
    except ImportError:
        return g
    out = []
    for f in g["features"]:
        geom = shape(f["geometry"]).simplify(tol, preserve_topology=True)
        out.append({"type": "Feature", "properties": f["properties"], "geometry": mapping(geom)})
    return {"type": "FeatureCollection", "features": out}


def huc6_polygons(log):
    if os.path.exists(HUC_FILE):
        with open(HUC_FILE, encoding="utf-8") as f:
            g = json.load(f)
        if os.path.getsize(HUC_FILE) > 600000:          # first-run raw file: simplify once and rewrite
            g = simplify(g)
            g["features"] = [dict(f, geometry={"type": f["geometry"]["type"], "coordinates": _round(f["geometry"]["coordinates"])}) for f in g["features"]]
            with open(HUC_FILE, "w", encoding="utf-8") as f:
                json.dump(g, f, separators=(",", ":"))
            log("basins: simplified outlines to %d KB" % (os.path.getsize(HUC_FILE) // 1024))
        return g
    q = urllib.parse.urlencode({"where": "huc6 LIKE '17%' OR huc6 LIKE '16%'", "outFields": "huc6,name", "returnGeometry": "true",
                                "f": "geojson", "outSR": "4326", "geometryPrecision": "4"})
    g = json.loads(fetch("https://hydro.nationalmap.gov/arcgis/rest/services/wbd/MapServer/3/query?" + q, 300))
    feats = []
    for f in g.get("features", []):
        f["geometry"]["coordinates"] = _round(f["geometry"]["coordinates"])
        feats.append(f)
    g = simplify({"type": "FeatureCollection", "features": feats})
    with open(HUC_FILE, "w", encoding="utf-8") as f:
        json.dump(g, f, separators=(",", ":"))
    log("basins: cached %d HUC6 outlines" % len(feats))
    return g


def build(log=print):
    g = huc6_polygons(log)
    # stations with HUC codes (from the station cache written by stations.py, or fresh)
    url = ("https://wcc.sc.egov.usda.gov/awdbRestApi/services/v1/stations?"
           "stationTriplets=*:WA:SNTL,*:OR:SNTL,*:ID:SNTL,*:MT:SNTL&activeOnly=true")
    st = [s for s in json.loads(fetch(url)) if LAT0 <= s["latitude"] <= LAT1 and LON0 <= s["longitude"] <= LON1 and s.get("huc")]
    huc_of = {s["stationTriplet"]: s["huc"][:6] for s in st}
    day = (dt.datetime.now() - dt.timedelta(days=1)).strftime("%Y-%m-%d")
    sums = {}
    trips = list(huc_of)
    for i in range(0, len(trips), 60):
        q = urllib.parse.urlencode({"stationTriplets": ",".join(trips[i:i + 60]), "elements": "WTEQ,PREC", "duration": "DAILY",
                                    "beginDate": day, "endDate": day, "centralTendencyType": "MEDIAN"})
        for s in json.loads(fetch("https://wcc.sc.egov.usda.gov/awdbRestApi/services/v1/data?" + q)):
            h = huc_of.get(s["stationTriplet"])
            if not h:
                continue
            b = sums.setdefault(h, {"swe": 0.0, "swe_med": 0.0, "swe_n": 0, "prec": 0.0, "prec_med": 0.0, "prec_n": 0})
            for e in s["data"]:
                code = e["stationElement"]["elementCode"]
                for v in e["values"]:
                    val, med = v.get("value"), v.get("median")
                    if val is None or med is None:
                        continue
                    k = "swe" if code == "WTEQ" else "prec"
                    b[k] += val
                    b[k + "_med"] += med
                    b[k + "_n"] += 1
    feats = []
    for f in g["features"]:
        h = f["properties"]["huc6"]
        b = sums.get(h)
        p = {"huc6": h, "name": f["properties"]["name"]}
        if b:
            p["swe_n"] = b["swe_n"]
            p["swe_pct"] = round(100.0 * b["swe"] / b["swe_med"]) if b["swe_med"] > 0 else None
            p["swe_in"] = round(b["swe"] / b["swe_n"], 1) if b["swe_n"] else None
            p["prec_n"] = b["prec_n"]
            p["prec_pct"] = round(100.0 * b["prec"] / b["prec_med"]) if b["prec_med"] > 0 else None
        feats.append({"type": "Feature", "properties": p, "geometry": f["geometry"]})
    data = {"type": "FeatureCollection", "features": feats, "date": day,
            "updated": dt.datetime.now().strftime("%a %b %d %I:%M %p"), "updated_t": int(time.time())}
    with open(OUT + ".tmp", "w", encoding="utf-8") as f:
        f.write("window.BASINS = %s;\n" % json.dumps(data, separators=(",", ":")))
    os.replace(OUT + ".tmp", OUT)
    with_swe = sum(1 for x in feats if x["properties"].get("swe_pct") is not None)
    log("basins: %d basins, %d with snowpack values, %d with precip values" % (len(feats), with_swe, sum(1 for x in feats if x["properties"].get("prec_pct") is not None)))
    return len(feats)


if __name__ == "__main__":
    t0 = time.time()
    build()
    print("done in %.0fs" % (time.time() - t0))
