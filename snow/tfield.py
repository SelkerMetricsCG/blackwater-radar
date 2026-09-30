"""
The station network's temperature field for one day: every station with a full day of hourly readings (the
archive's compact records: SNOTEL, HADS, NWS) gives a daily max and min; per avalanche zone a linear fit of
temperature against elevation (the day's own lapse rate, which is what it is: inverted on a cold-pool night),
pooled over all stations where a zone has too few; the residuals from the fit interpolated by inverse distance
squared in an elevation-aware distance, d^2 = dh^2 + (k dz)^2 (tfield_vertical_k), so a valley residual reaches
the cells at the valley's own height and not the ridges above it. A cell's temperature is the zone fit at its
own elevation plus the interpolated residual. This is GIDS (Nalder & Wein 1998) with the non-Euclidean distance
of Frei (2014); kriging of the residuals is the upgrade once the season's leave-one-out errors say it is needed.

Nights: when the valley stations flatten or invert a zone's fit (slope above tfield_inversion_lapse), the lapse is
refitted on the stations above the inversion top (the warmest 200 m elevation bin), or falls back to the free-air
lapse (lapse_c_per_km) anchored there when too few remain (Pages & Miro 2010). The valley stations then carry
large negative residuals, which the elevation-aware interpolation keeps in the valley: that residual of the
minimum is the cold-pool diagnostic (`tmin_resid_c`). Per-zone night slopes go to the log (positive = inversion).

Every day the field is checked by leave-one-out: each station predicted from the others, mean absolute error for
the max and the min logged and returned (`loo_mae`). Good daily methods sit near 1.0-1.5 C in winter mountains
(Stahl et al. 2006; Frei 2014); a fixed lapse rate 1.5-2 C.
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


def _fit_night(elev, t, p, bin_m=200.0):
    """the night fit: (a, b, note). When the valley stations flatten or invert the fit, refit on the stations above
    the inversion top (the warmest elevation bin), else anchor the free-air lapse there; note says what happened"""
    a, b = _fit(elev, t)
    if len(elev) < 4 or b <= p["tfield_inversion_lapse"]:
        return a, b, None
    e = np.asarray(elev, float)
    y = np.asarray(t, float)
    bins = np.floor(e / bin_m).astype(int)
    ub = np.unique(bins)
    med = np.array([np.median(y[bins == k]) for k in ub])
    top_bin = ub[int(np.argmax(med))]
    if top_bin == ub[0]:
        return a, b, None                       # warmest at the bottom: no pool, just a weak lapse
    top = top_bin * bin_m
    above = e >= top
    if above.sum() >= 4 and np.ptp(e[above]) >= 300:
        a2, b2 = _fit(e[above], y[above])
        if b2 <= p["tfield_inversion_lapse"]:
            return a2, b2, "refit above %.0f m: %.1f (n %d)" % (top, b2, above.sum())
    b2 = -float(p["lapse_c_per_km"])
    a2 = float(y[above].mean() - b2 * e[above].mean() / 1000.0)
    return a2, b2, "free-air lapse anchored above %.0f m (n %d)" % (top, above.sum())


def _idw(sx, sy, sz, vals, qx, qy, qz, reach_m, k, power=2.0):
    """inverse-distance interpolation of the station value arrays `vals` at the query points, in the elevation-aware
    distance d^2 = dh^2 + (k dz)^2; 0 beyond the horizontal reach of every station. Query arrays 2-D on the regular
    lattice (x along columns, y down rows: each station touches only its reach window) or 1-D for point sets."""
    qx, qy, qz = (np.asarray(q, np.float64) for q in (qx, qy, qz))
    vals = [np.asarray(v, np.float64) for v in vals]
    out = [np.zeros(qx.shape, np.float64) for _ in vals]
    wsum = np.zeros(qx.shape, np.float64)
    regular = qx.ndim == 2
    if regular:
        xs, ys = qx[0, :], qy[:, 0]
        ydesc = len(ys) > 1 and ys[1] < ys[0]
        ykey = -ys if ydesc else ys
    for i, (x, y, z) in enumerate(zip(sx, sy, sz)):
        if regular:
            c0, c1 = np.searchsorted(xs, [x - reach_m, x + reach_m])
            r0, r1 = np.searchsorted(ykey, [(-y if ydesc else y) - reach_m, (-y if ydesc else y) + reach_m])
            win = (slice(r0, r1), slice(c0, c1))
            if r1 <= r0 or c1 <= c0:
                continue
        else:
            win = slice(None)
        dx, dy, dz = qx[win] - x, qy[win] - y, qz[win] - z
        d2 = dx * dx + dy * dy
        w = np.where(d2 <= reach_m * reach_m, 1.0 / np.maximum(d2 + (k * dz) ** 2, 100.0 ** 2) ** (power / 2), 0.0)
        for o, v in zip(out, vals):
            o[win] += w * v[i]
        wsum[win] += w
    return [np.where(wsum > 0, o / np.maximum(wsum, 1e-12), 0.0).astype(np.float32) for o in out]


def _loo(sx, sy, sz, a_s, b_s_max, a_min, b_min, selev, tmax, tmin, res_max, res_min, reach_m, k, power=2.0):
    """leave-one-out: each station predicted from the others' residuals (same distance rule), MAE of max and min"""
    n = len(sx)
    if n < 3:
        return None
    dx = sx[:, None] - sx[None, :]
    dy = sy[:, None] - sy[None, :]
    dz = sz[:, None] - sz[None, :]
    d2 = dx * dx + dy * dy
    w = np.where(d2 <= reach_m * reach_m, 1.0 / np.maximum(d2 + (k * dz) ** 2, 100.0 ** 2) ** (power / 2), 0.0)
    np.fill_diagonal(w, 0.0)
    ws = w.sum(axis=1)
    pr_max = np.where(ws > 0, (w @ res_max) / np.maximum(ws, 1e-12), 0.0)
    pr_min = np.where(ws > 0, (w @ res_min) / np.maximum(ws, 1e-12), 0.0)
    e_max = np.abs((a_s + b_s_max * selev / 1000.0 + pr_max) - tmax)
    e_min = np.abs((a_min + b_min * selev / 1000.0 + pr_min) - tmin)
    return {"tmax": round(float(e_max.mean()), 2), "tmin": round(float(e_min.mean()), 2), "n": int(n)}


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
    notes = {}
    a_n, b_n, note = _fit_night(selev, tmin, p)
    pooled = {"max": _fit(selev, tmax), "min": (a_n, b_n), "n": len(ids)}
    if note:
        notes["pooled"] = note
    for z in np.unique(szone):
        if z < 0:
            continue
        m = szone == z
        if m.sum() >= p["tfield_min_per_zone"] and np.ptp(selev[m]) >= 500:
            a_n, b_n, note = _fit_night(selev[m], tmin[m], p)
            fits[int(z)] = {"max": _fit(selev[m], tmax[m]), "min": (a_n, b_n), "n": int(m.sum())}
            if note:
                notes[int(z)] = note
    log("tfield: %d stations; night lapse (C/km, + = inversion): pooled %.1f, %s" % (
        len(ids), pooled["min"][1], ", ".join("%d: %.1f (n %d)" % (z, v["min"][1], v["n"]) for z, v in sorted(fits.items())) or "no zone fits"))
    if notes:
        log("tfield: inversions: " + "; ".join("%s: %s" % (z, n) for z, n in notes.items()))

    def fit_for(zarr, which):
        a = np.full(zarr.shape, pooled[which][0], np.float32)
        b = np.full(zarr.shape, pooled[which][1], np.float32)
        for z, v in fits.items():
            m = zarr == z
            a[m], b[m] = v[which][0], v[which][1]
        return a, b
    # residuals at the stations from the fit that applies to each station's zone
    a_x, b_x = fit_for(szone, "max")
    res_max = tmax - (a_x + b_x * selev / 1000.0)
    a_m, b_m = fit_for(szone, "min")
    res_min = tmin - (a_m + b_m * selev / 1000.0)
    tr = Transformer.from_crs("EPSG:4326", meta["crs"], always_xy=True)
    sx, sy = (np.asarray(v, float) for v in tr.transform(slon, slat))
    reach = p["tfield_idw_km"] * 1000.0
    kz = float(p["tfield_vertical_k"])
    shape = np.shape(latg)
    elev_c = np.asarray(lat["elev"], np.float32)
    if len(shape) == 2 and "transform" in meta:
        # the regular lattice: projected coordinates straight from the transform, so each station touches only its window
        t = meta["transform"]
        cx = t[2] + (np.arange(shape[1]) + 0.5) * t[0]
        cy = t[5] + (np.arange(shape[0]) + 0.5) * t[4]
        cx, cy = np.broadcast_to(cx[None, :], shape), np.broadcast_to(cy[:, None], shape)
        res_max_c, res_min_c = _idw(sx, sy, selev, [res_max, res_min], cx, cy, elev_c, reach, kz)
    else:
        cx, cy = tr.transform(np.asarray(long_, float).ravel(), np.asarray(latg, float).ravel())
        res_max_c, res_min_c = _idw(sx, sy, selev, [res_max, res_min], np.asarray(cx), np.asarray(cy), elev_c.ravel(), reach, kz)
        res_max_c, res_min_c = res_max_c.reshape(shape), res_min_c.reshape(shape)
    zone_c = np.asarray(lat["zone"])
    elev_km = elev_c / 1000.0
    a, b = fit_for(zone_c, "max")
    tmax_c = a + b * elev_km + res_max_c
    a, b = fit_for(zone_c, "min")
    tmin_c = a + b * elev_km + res_min_c
    loo = _loo(sx, sy, selev, a_x, b_x, a_m, b_m, selev, tmax, tmin, res_max, res_min, reach, kz)
    if loo:
        log("tfield: leave-one-out MAE tmax %.2f C, tmin %.2f C (n %d)" % (loo["tmax"], loo["tmin"], loo["n"]))
    return {"tmax_c": tmax_c.astype(np.float32), "tmin_c": tmin_c.astype(np.float32), "tmin_resid_c": res_min_c.astype(np.float32),
            "lapse_min": {str(z): round(v["min"][1], 2) for z, v in fits.items()}, "pooled_lapse_min": round(pooled["min"][1], 2),
            "inversions": {str(z): n for z, n in notes.items()}, "loo_mae": loo, "n": len(ids)}
