"""
The station network's temperature field for one day: every station with a full day of hourly readings (the
archive's compact records: SNOTEL, HADS, NWS) gives a daily max and min; per avalanche zone a linear fit of
temperature against elevation (the day's own lapse rate, which is what it is: inverted on a cold-pool night),
pooled over all stations where a zone has too few; the residuals from the fit interpolated by inverse distance
squared. A cell's temperature is the zone fit at its own elevation plus the interpolated residual.

The residual of the minimum is the cold-pool diagnostic: a strongly negative residual at a valley-floor station
says the night's air pooled there, and the interpolation carries that to the cells around it. Per-zone lapse
slopes go to the log (positive = inversion).

Kriging with a fitted variogram is the upgrade when the season shows the residual field's structure; this is
regression plus inverse distance, which is what the station density supports today.
"""
import numpy as np

from snow import forcing

MIN_HOURS = 12
FT_SOURCES = ("SNOTEL", "SCAN", "BC")


def station_extremes(hourlies, daily_next=None, day=None, tz_offset_h=-8):
    """{id: {lat, lon, elev_m, tmax_c, tmin_c, n}} from the day's hourly compact records"""
    acc = {}
    for h in hourlies or []:
        for r in h.get("stations") or []:
            t = r.get("temp")
            if t is None or r.get("lat") is None or r.get("lon") is None or r.get("elev") is None:
                continue
            e = float(r["elev"])
            src = r.get("src") or ""
            if src in FT_SOURCES or (src != "NWS" and e > 4500):
                e *= 0.3048
            a = acc.setdefault(r["id"], {"lat": r["lat"], "lon": r["lon"], "elev_m": e, "temps": []})
            a["temps"].append(float(t))
    out = {}
    for sid, a in acc.items():
        if len(a["temps"]) >= MIN_HOURS:
            out[sid] = {"lat": a["lat"], "lon": a["lon"], "elev_m": a["elev_m"], "n": len(a["temps"]),
                        "tmax_c": (max(a["temps"]) - 32) * 5 / 9, "tmin_c": (min(a["temps"]) - 32) * 5 / 9}
    return out


def _fit(elev, t):
    """(a, b) of t = a + b * elev_km by least squares"""
    x = np.asarray(elev, float) / 1000.0
    y = np.asarray(t, float)
    if len(x) < 2 or np.ptp(x) < 0.05:
        return float(y.mean()), 0.0
    b, a = np.polyfit(x, y, 1)
    return float(a), float(b)


def _idw(sx, sy, sv, qx, qy, reach_m, power=2.0):
    """inverse-distance interpolation of station values sv at query points; 0 beyond reach of every station"""
    out = np.zeros(qx.shape, np.float32)
    wsum = np.zeros(qx.shape, np.float32)
    for x, y, v in zip(sx, sy, sv):
        d2 = (qx - x) ** 2 + (qy - y) ** 2
        w = np.where(d2 <= reach_m * reach_m, 1.0 / np.maximum(d2, 100.0 ** 2) ** (power / 2), 0.0).astype(np.float32)
        out += w * v
        wsum += w
    return np.where(wsum > 0, out / np.maximum(wsum, 1e-12), 0.0).astype(np.float32)


def fields(hourlies, daily_next, day, tz_offset_h, lat, meta, latg, long_, zone_full, band_full, p, log=print):
    """-> {tmax_c, tmin_c, tmin_resid_c} over the cells in `lat` (full lattice or a subset), or None when too few
    stations reported. Per-zone lapse fits (or the pooled fit), residuals interpolated on a coarse grid."""
    from pyproj import Transformer
    st = station_extremes(hourlies, daily_next, day, tz_offset_h)
    if len(st) < p["tfield_min_stations"]:
        log("tfield: %d stations with a full day, need %d; band means used" % (len(st), p["tfield_min_stations"]))
        return None
    ids = sorted(st)
    slat = np.array([st[i]["lat"] for i in ids], float)
    slon = np.array([st[i]["lon"] for i in ids], float)
    selev = np.array([st[i]["elev_m"] for i in ids], float)
    tmax = np.array([st[i]["tmax_c"] for i in ids], float)
    tmin = np.array([st[i]["tmin_c"] for i in ids], float)
    r, c = forcing.cell_of(meta, slat, slon)
    inside = r >= 0
    szone = np.where(inside, zone_full[np.clip(r, 0, zone_full.shape[0] - 1), np.clip(c, 0, zone_full.shape[1] - 1)], -1)
    fits = {}
    pooled = {"max": _fit(selev, tmax), "min": _fit(selev, tmin), "n": len(ids)}
    for z in np.unique(szone):
        if z < 0:
            continue
        m = szone == z
        if m.sum() >= p["tfield_min_per_zone"] and np.ptp(selev[m]) >= 500:
            fits[int(z)] = {"max": _fit(selev[m], tmax[m]), "min": _fit(selev[m], tmin[m]), "n": int(m.sum())}
    log("tfield: %d stations; night lapse (C/km, + = inversion): pooled %.1f, %s" % (
        len(ids), pooled["min"][1], ", ".join("%d: %.1f (n %d)" % (z, v["min"][1], v["n"]) for z, v in sorted(fits.items())) or "no zone fits"))

    def fit_for(zarr, which):
        a = np.full(zarr.shape, pooled[which][0], np.float32)
        b = np.full(zarr.shape, pooled[which][1], np.float32)
        for z, v in fits.items():
            m = zarr == z
            a[m], b[m] = v[which][0], v[which][1]
        return a, b
    # residuals at the stations from the fit that applies to each station's zone
    a_s, b_s = fit_for(szone, "max")
    res_max = tmax - (a_s + b_s * selev / 1000.0)
    a_s, b_s = fit_for(szone, "min")
    res_min = tmin - (a_s + b_s * selev / 1000.0)
    tr = Transformer.from_crs("EPSG:4326", meta["crs"], always_xy=True)
    sx, sy = tr.transform(slon, slat)
    cx, cy = tr.transform(np.asarray(long_, float).ravel(), np.asarray(latg, float).ravel())
    cx, cy = np.asarray(cx), np.asarray(cy)
    reach = p["tfield_idw_km"] * 1000.0
    n = cx.size
    if n > 300_000:
        # coarse grid over the cells' extent, then the nearest coarse node per cell
        step = 1000.0
        gx = np.arange(cx.min(), cx.max() + step, step)
        gy = np.arange(cy.min(), cy.max() + step, step)
        GX, GY = np.meshgrid(gx, gy)
        rmax = _idw(sx, sy, res_max, GX, GY, reach)
        rmin = _idw(sx, sy, res_min, GX, GY, reach)
        ix = np.clip(np.round((cx - gx[0]) / step).astype(int), 0, len(gx) - 1)
        iy = np.clip(np.round((cy - gy[0]) / step).astype(int), 0, len(gy) - 1)
        res_max_c, res_min_c = rmax[iy, ix], rmin[iy, ix]
    else:
        res_max_c = _idw(sx, sy, res_max, cx, cy, reach)
        res_min_c = _idw(sx, sy, res_min, cx, cy, reach)
    shape = np.shape(latg)
    zone_c = np.asarray(lat["zone"]).ravel()
    elev_km = np.asarray(lat["elev"], np.float32).ravel() / 1000.0
    a, b = fit_for(zone_c, "max")
    tmax_c = (a + b * elev_km + res_max_c).reshape(shape)
    a, b = fit_for(zone_c, "min")
    tmin_c = (a + b * elev_km + res_min_c).reshape(shape)
    return {"tmax_c": tmax_c.astype(np.float32), "tmin_c": tmin_c.astype(np.float32), "tmin_resid_c": res_min_c.reshape(shape).astype(np.float32),
            "lapse_min": {str(z): round(v["min"][1], 2) for z, v in fits.items()}, "pooled_lapse_min": round(pooled["min"][1], 2), "n": len(ids)}
