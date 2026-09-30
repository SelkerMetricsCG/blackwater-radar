"""
Check 4: the layer's click readout against the snow model's terrain horizons (snow/sunhours.py: 100 m cells, 16
directions to 10 km, true sun without refraction, no self-shade test) at the places in check_cases.json.
Different grid, different method (horizon angles vs a walk), same USGS terrain family, so close but not equal answers
are expected; large gaps go to ANOMALY_LOG.md.

  python terrain/check_snow.py LATTICE.npz LATTICE.json      (after check_js.py; reads work/check/js_results.json)
"""
import datetime as dt
import json
import os
import sys
from zoneinfo import ZoneInfo

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from snow import forcing, sunhours  # noqa: E402


def main():
    npz, meta_path = sys.argv[1], sys.argv[2]
    lat = np.load(npz)
    hz_all, elev = lat["horizon"], lat["elev"]
    meta = json.load(open(meta_path, encoding="utf-8"))
    cases = json.load(open(os.path.join(HERE, "check_cases.json"), encoding="utf-8"))
    js = json.load(open(os.path.join(HERE, "work", "check", "js_results.json"), encoding="utf-8"))
    rows, lines = [], []
    for pl in cases["places"]:
        r, c = forcing.cell_of(meta, [pl["lat"]], [pl["lon"]])
        hz = hz_all[:, r[0], c[0]]
        for date in cases["dates"]:
            d = dt.date.fromisoformat(date)
            tz = ZoneInfo("America/Los_Angeles").utcoffset(dt.datetime(d.year, d.month, d.day, 12)).total_seconds() / 3600
            first, last, hours = sunhours.sun_on_terrain(hz, pl["lat"], pl["lon"], d, tz, step_min=2)
            j = js[pl["name"]][date]
            jf = j["windows"][0][0] if j["windows"] else None
            jl = j["windows"][-1][1] if j["windows"] else None
            fmt = lambda t: t.strftime("%H:%M") if t else "-"          # noqa: E731
            hm = lambda m: "%d:%02d" % divmod(m, 60) if m is not None else "-"  # noqa: E731
            rows.append({"place": pl["name"], "date": date, "snow_hours": hours, "layer_hours": j["hours"],
                         "snow_first": fmt(first), "layer_first": hm(jf), "snow_last": fmt(last), "layer_last": hm(jl),
                         "snow_cell_elev_m": int(elev[r[0], c[0]]), "horizon_deg": hz.tolist()})
            lines.append("%-24s %s  snow %4.1f h %s-%s   layer %4.1f h %s-%s  (%d windows)" % (
                pl["name"], date, hours, fmt(first), fmt(last), j["hours"], hm(jf), hm(jl), len(j["windows"])))
    out = os.path.join(HERE, "work", "check", "snow_compare.json")
    json.dump(rows, open(out, "w", encoding="utf-8"), indent=1)
    print("\n".join(lines))
    d = np.array([x["layer_hours"] - x["snow_hours"] for x in rows])
    print("layer - snow model hours: median %+.2f, mean |%.2f|, max |%.2f| over %d place-days" % (np.median(d), np.abs(d).mean(), np.abs(d).max(), len(d)))


if __name__ == "__main__":
    main()
