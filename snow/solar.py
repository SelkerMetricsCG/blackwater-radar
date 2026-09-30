"""
Solar term for the snow-conditions model: sun position, clear-sky irradiance on an inclined cell, cloud
scaling and daily totals. Pure numpy, no network. Parameters and their sources: snow/snow_config.yaml (solar).

  sun_position(lat, lon, t_utc)                       -> (elevation deg, azimuth deg from N clockwise)
  clear_sky_direct(elev_deg, alt_m)                    -> direct-normal W/m2 (0 below the horizon)
  cos_incidence(sun_el, sun_az, slope_deg, aspect_deg) -> cos of the angle between sun and the cell's normal
  daily_mj(lat, lon, date, slope_deg, aspect_deg, alt_m, cloud=0)
                                                       -> MJ/m2 on the slope for that day (arrays welcome)
  daily_components_binned(...)                         -> {"direct", "diffuse", "global_flat"} MJ/m2 per cell
  terrain_irradiance(parts, terrain_factor, svf)       -> MJ/m2 with horizon shading, sky view and terrain reflection
                                                          (Dozier & Frew 1990)
Sun position is NOAA's spreadsheet algorithm (Meeus), good to ~0.1 deg, plenty for a 100 m cell.
"""
import datetime as dt
import math
import os

import numpy as np

ROOT = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(ROOT, "snow_config.yaml")


def load_config(path=CONFIG):
    import yaml
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)["solar"]


def _julian_century(t_utc):
    jd = t_utc.replace(tzinfo=dt.timezone.utc).timestamp() / 86400.0 + 2440587.5
    return (jd - 2451545.0) / 36525.0


def sun_position(lat, lon, t_utc):
    """(elevation deg, azimuth deg clockwise from north) at naive-UTC datetime t_utc; lat/lon may be arrays"""
    T = _julian_century(t_utc)
    L0 = (280.46646 + T * (36000.76983 + T * 0.0003032)) % 360
    M = 357.52911 + T * (35999.05029 - 0.0001537 * T)
    e = 0.016708634 - T * (0.000042037 + 0.0000001267 * T)
    Mr = math.radians(M)
    C = (math.sin(Mr) * (1.914602 - T * (0.004817 + 0.000014 * T)) + math.sin(2 * Mr) * (0.019993 - 0.000101 * T)
         + math.sin(3 * Mr) * 0.000289)
    true_lon = L0 + C
    omega = 125.04 - 1934.136 * T
    app_lon = true_lon - 0.00569 - 0.00478 * math.sin(math.radians(omega))
    eps0 = 23 + (26 + ((21.448 - T * (46.815 + T * (0.00059 - T * 0.001813)))) / 60) / 60
    eps = eps0 + 0.00256 * math.cos(math.radians(omega))
    decl = math.degrees(math.asin(math.sin(math.radians(eps)) * math.sin(math.radians(app_lon))))
    y = math.tan(math.radians(eps / 2)) ** 2
    L0r, er = math.radians(L0), e
    eqt = 4 * math.degrees(y * math.sin(2 * L0r) - 2 * er * math.sin(Mr) + 4 * er * y * math.sin(Mr) * math.cos(2 * L0r)
                           - 0.5 * y * y * math.sin(4 * L0r) - 1.25 * er * er * math.sin(2 * Mr))      # minutes
    minutes = t_utc.hour * 60 + t_utc.minute + t_utc.second / 60
    lat, lon = np.asarray(lat, float), np.asarray(lon, float)
    tst = (minutes + eqt + 4 * lon) % 1440
    ha = np.where(tst / 4 < 0, tst / 4 + 180, tst / 4 - 180)
    latr, dr, har = np.radians(lat), math.radians(decl), np.radians(ha)
    cosz = np.sin(latr) * math.sin(dr) + np.cos(latr) * math.cos(dr) * np.cos(har)
    z = np.degrees(np.arccos(np.clip(cosz, -1, 1)))
    el = 90 - z
    denom = np.cos(latr) * np.sin(np.radians(z))
    with np.errstate(invalid="ignore", divide="ignore"):
        cosaz = np.clip((np.sin(latr) * cosz - math.sin(dr)) / np.where(denom == 0, np.nan, denom), -1, 1)
    az = np.degrees(np.arccos(cosaz))
    az = np.where(np.isnan(az), 180.0, az)
    az = np.where(ha > 0, (az + 180) % 360, (540 - az) % 360)
    return el, az


def air_mass(elev_deg):
    """Kasten & Young (1989) relative optical air mass; inf below the horizon"""
    e = np.asarray(elev_deg, float)
    with np.errstate(divide="ignore", invalid="ignore"):
        am = 1.0 / (np.sin(np.radians(e)) + 0.50572 * (e + 6.07995) ** -1.6364)
    return np.where(e <= 0, np.inf, am)


def clear_sky_direct(elev_deg, alt_m=0.0, cfg=None):
    """direct-normal irradiance W/m2 on a clear day (Meinel & Meinel with Laue's altitude term)"""
    cfg = cfg or load_config()
    h = np.asarray(alt_m, float) / 1000.0
    am = air_mass(elev_deg)
    with np.errstate(over="ignore", invalid="ignore"):
        tau = (1 - 0.14 * h) * 0.7 ** (am ** 0.678) + 0.14 * h
    out = cfg["solar_constant_w_m2"] * tau
    return np.where(np.asarray(elev_deg, float) <= 0, 0.0, out)


def cos_incidence(sun_el, sun_az, slope_deg, aspect_deg):
    """cosine of the angle between the sun and the cell normal; flat cells (aspect < 0) use slope 0"""
    s = np.radians(np.asarray(slope_deg, float))
    a = np.radians(np.where(np.asarray(aspect_deg, float) < 0, 0.0, aspect_deg))
    s = np.where(np.asarray(aspect_deg, float) < 0, 0.0, s)
    z = np.radians(90 - np.asarray(sun_el, float))
    saz = np.radians(np.asarray(sun_az, float))
    c = np.cos(z) * np.cos(s) + np.sin(z) * np.sin(s) * np.cos(saz - a)
    return np.clip(c, 0, 1)


def cloud_factor(cloud, cfg=None):
    """Kasten & Czeplak: global irradiance fraction under cloud fraction 0..1"""
    cfg = cfg or load_config()
    n = np.clip(np.asarray(cloud, float), 0, 1)
    return 1 - cfg["cloud_a"] * n ** cfg["cloud_b"]


def _clear_parts(lat, lon, t_utc, slope_deg, aspect_deg, alt_m, cfg):
    """clear-sky W/m2 at one instant: (direct on the cell, isotropic diffuse on the cell, direct + diffuse flat)"""
    el, az = sun_position(lat, lon, t_utc)
    dni = clear_sky_direct(el, alt_m, cfg)
    direct = dni * cos_incidence(el, az, slope_deg, aspect_deg)
    s = np.radians(np.where(np.asarray(aspect_deg, float) < 0, 0.0, slope_deg))
    flat_direct = dni * np.sin(np.radians(np.clip(el, 0, 90)))
    diffuse = cfg["diffuse_fraction"] * flat_direct * (1 + np.cos(s)) / 2
    global_flat = flat_direct * (1 + cfg["diffuse_fraction"])
    return direct, diffuse, global_flat


def _cloud_split(direct, diffuse, global_flat, cloud, cfg):
    """apply the cloud to clear-sky parts. The global total (direct + diffuse) follows Kasten & Czeplak as in
    `irradiance`; the split assumes the direct beam scales by (1 - n), n the cloud fraction (the sun shows for the
    clear share of the sky), and the diffuse part takes the rest of the cloud-scaled global, so it rises under cloud.
    n - cloud_a n^cloud_b >= 0 on 0..1 keeps the diffuse part non-negative. Returns (direct, diffuse, global_flat)."""
    n = np.clip(np.asarray(cloud, float), 0, 1)
    cf = cloud_factor(n, cfg)
    d = direct * (1 - n)
    return d, (direct + diffuse) * cf - d, global_flat * cf


def irradiance(lat, lon, t_utc, slope_deg, aspect_deg, alt_m=0.0, cloud=0.0, cfg=None):
    """W/m2 on the inclined cell at one instant: direct + isotropic diffuse, scaled by cloud"""
    cfg = cfg or load_config()
    direct, diffuse, _ = _clear_parts(lat, lon, t_utc, slope_deg, aspect_deg, alt_m, cfg)
    return (direct + diffuse) * cloud_factor(cloud, cfg)


def irradiance_parts(lat, lon, t_utc, slope_deg, aspect_deg, alt_m=0.0, cloud=0.0, cfg=None):
    """`irradiance` by component: {"direct", "diffuse", "global_flat"} W/m2 at one instant, cloud applied as in
    `_cloud_split`; direct + diffuse equals `irradiance` (up to rounding)"""
    cfg = cfg or load_config()
    parts = _clear_parts(lat, lon, t_utc, slope_deg, aspect_deg, alt_m, cfg)
    return dict(zip(("direct", "diffuse", "global_flat"), _cloud_split(*parts, cloud, cfg)))


def daily_mj(lat, lon, date, slope_deg, aspect_deg, alt_m=0.0, cloud=0.0, cfg=None):
    """MJ/m2 over the UTC day (00-24 UTC, i.e. 16:00 to 16:00 Pacific, which contains one full local daylight period)"""
    cfg = cfg or load_config()
    step = int(cfg["step_min"])
    total = np.zeros(np.broadcast(np.asarray(lat, float), np.asarray(slope_deg, float), np.asarray(aspect_deg, float)).shape)
    t0 = dt.datetime(date.year, date.month, date.day)
    for m in range(0, 1440, step):
        total = total + irradiance(lat, lon, t0 + dt.timedelta(minutes=m), slope_deg, aspect_deg, alt_m, cloud, cfg)
    return total * step * 60 / 1e6


def daily_parts(lat, lon, date, slope_deg, aspect_deg, alt_m=0.0, cloud=0.0, cfg=None):
    """`daily_mj` by component: {"direct", "diffuse", "global_flat"} MJ/m2 over the UTC day, cloud (a daily value)
    applied as in `_cloud_split` after the clear-sky integration; direct + diffuse equals `daily_mj`"""
    cfg = cfg or load_config()
    step = int(cfg["step_min"])
    shape = np.broadcast(np.asarray(lat, float), np.asarray(slope_deg, float), np.asarray(aspect_deg, float)).shape
    sums = [np.zeros(shape) for _ in range(3)]
    t0 = dt.datetime(date.year, date.month, date.day)
    for m in range(0, 1440, step):
        parts = _clear_parts(lat, lon, t0 + dt.timedelta(minutes=m), slope_deg, aspect_deg, alt_m, cfg)
        for i in range(3):
            sums[i] = sums[i] + parts[i]
    k = step * 60 / 1e6
    return dict(zip(("direct", "diffuse", "global_flat"), _cloud_split(*(x * k for x in sums), cloud, cfg)))


DIR16_AZ = [0.0, 26.6, 45.0, 63.4, 90.0, 116.6, 135.0, 153.4, 180.0, 206.6, 225.0, 243.4, 270.0, 296.6, 315.0, 333.4]


def sector_of(az, azimuths=DIR16_AZ):
    """index of the nearest direction in `azimuths` (deg, clockwise from N) for each azimuth in az"""
    a = np.asarray(az, float)[..., None]
    d = np.abs((a - np.asarray(azimuths, float) + 180.0) % 360.0 - 180.0)
    return np.argmin(d, axis=-1)


def shading_table(lat_bins, date, cfg=None, lon0=-121.0, max_el=45, azimuths=DIR16_AZ):
    """for each latitude in lat_bins: (directions x max_el+1) the fraction of the day's clear-sky direct energy on a
    horizontal surface that arrives from that direction's sector with the sun below each elevation angle; used
    with a cell's horizon angles to get the share of the day's direct sun the surrounding terrain blocks"""
    cfg = cfg or load_config()
    step = int(cfg["step_min"])
    t0 = dt.datetime(date.year, date.month, date.day)
    lat_bins = np.asarray(lat_bins, float)
    hist = np.zeros((len(lat_bins), len(azimuths), max_el + 2))
    for m in range(0, 1440, step):
        el, az = sun_position(lat_bins, np.full(len(lat_bins), lon0), t0 + dt.timedelta(minutes=m))
        e = clear_sky_direct(el, 1000.0, cfg) * np.sin(np.radians(np.clip(el, 0, 90)))
        k = sector_of(az, azimuths)
        ei = np.clip(np.floor(el).astype(int) + 1, 0, max_el + 1)
        up = el > 0
        for i in np.nonzero(up)[0]:
            hist[i, k[i], ei[i]] += e[i]
    cum = np.cumsum(hist, axis=2)
    tot = hist.sum(axis=(1, 2))[:, None, None]
    return cum / np.where(tot > 0, tot, 1)


def terrain_factor(horizon, lat, date, cfg=None, lat_step=0.5, direct_share=0.9, azimuths=None):
    """1 - direct_share x (share of the day's direct sun blocked by the terrain), per cell, from the horizon angles
    (deg) of each cell: (directions, N) array, directions at `azimuths` (16 by default, 8 octants if 8 rows).
    The default direct_share 0.9 is for callers that multiply the combined total of `daily_mj_binned`, where
    diffuse light (about a tenth) is folded in and not blocked. Pass direct_share=1.0 for the direct-only factor
    that `terrain_irradiance` takes."""
    cfg = cfg or load_config()
    hz_all = np.asarray(horizon)
    nd = hz_all.shape[0]
    if azimuths is None:
        azimuths = DIR16_AZ if nd == 16 else [k * 360.0 / nd for k in range(nd)]
    lat = np.asarray(lat, np.float32)
    li = np.round(lat / lat_step).astype(np.int64)
    bins, inv = np.unique(li, return_inverse=True)
    table = shading_table(bins * lat_step, date, cfg, azimuths=azimuths)            # (nbins, nd, 47)
    hz = np.clip(hz_all.astype(np.int64), 0, 45)
    blocked = np.zeros(lat.shape, np.float32)
    inv = inv.reshape(lat.shape)
    for k in range(nd):
        blocked += table[inv, k, hz[k]].astype(np.float32)
    return (1.0 - direct_share * np.clip(blocked, 0, 1)).astype(np.float32)


def refreeze_index(tmin_c, cloud, dewpoint_c, wind_ms):
    """0..1 how well the surface refroze overnight: 1 clear, dry, calm and cold; 0 warm, cloudy or windy.
    A placeholder shape until the first season's residuals exist (see the spec): the parameters here are
    judgment calls and will move to snow_config.yaml when they are fitted."""
    tmin, n, td, w = (np.asarray(x, float) for x in (tmin_c, cloud, dewpoint_c, wind_ms))
    cold = np.clip((2.0 - tmin) / 6.0, 0, 1)                   # 1 at or below -4 C, 0 above +2 C
    sky = 1 - np.clip(n, 0, 1) ** 2                           # radiative loss needs a clear sky
    dry = np.clip((0.0 - td) / 8.0, 0, 1)                      # a dewpoint below -8 C is fully dry
    calm = np.clip(1 - w / 8.0, 0, 1)                          # mixing above 8 m/s kills the inversion
    return cold * (0.5 * sky + 0.3 * dry + 0.2 * calm)


def daily_mj_binned(lat, lon, date, slope_deg, aspect_deg, alt_m, cloud=0.0, cfg=None,
                    lat_step=0.5, slope_step=1.0, aspect_step=5.0):
    """daily_mj over large cell arrays by way of a lookup: the clear-sky daily total is computed once per unique
    (latitude, slope, aspect) bin at sea level and at 1000 m, and each cell interpolates linearly in its
    elevation (the Meinel-Laue transmittance is linear in altitude, so this is exact). The per-cell cloud
    factor is applied after (it multiplies every instant equally when cloud is a daily value). Longitude only
    shifts the day's timing inside the UTC window, so the mean longitude stands for all cells. Bins: 0.5 deg
    latitude, 1 deg slope, 5 deg aspect: about 40k combinations over the lattice, a few seconds for 16 M cells
    against 13 min cell by cell (measured on the 2026-09-28 run)."""
    cfg = cfg or load_config()
    lat = np.asarray(lat, np.float32)
    shape = np.broadcast(lat, np.asarray(slope_deg), np.asarray(aspect_deg)).shape
    slope = np.broadcast_to(np.asarray(slope_deg, np.float32), shape)
    aspect = np.broadcast_to(np.asarray(aspect_deg, np.float32), shape)
    alt_km = np.broadcast_to(np.asarray(alt_m, np.float32), shape) / 1000.0
    flat = aspect < 0
    li = np.round(np.broadcast_to(lat, shape) / lat_step).astype(np.int64)
    si = np.where(flat, 0, np.round(slope / slope_step)).astype(np.int64)
    ai = np.where(flat, 0, np.round((aspect % 360) / aspect_step)).astype(np.int64)
    key = (li * 256 + si) * 128 + ai
    uk, inv = np.unique(key.ravel(), return_inverse=True)
    u_li, u_si, u_ai = uk // (256 * 128), (uk // 128) % 256, uk % 128
    u_aspect = np.where(u_si == 0, -1.0, u_ai * aspect_step)
    lon0 = float(np.nanmean(np.asarray(lon, np.float32)))
    c0 = daily_mj(u_li * lat_step, lon0, date, u_si * slope_step, u_aspect, 0.0, 0.0, cfg)
    c1 = daily_mj(u_li * lat_step, lon0, date, u_si * slope_step, u_aspect, 1000.0, 0.0, cfg)
    clear = c0[inv].reshape(shape) + (c1 - c0)[inv].reshape(shape) * alt_km
    return (clear * cloud_factor(cloud, cfg)).astype(np.float32)


def daily_components_binned(lat, lon, date, slope_deg, aspect_deg, alt_m, cloud=0.0, cfg=None,
                            lat_step=0.5, slope_step=1.0, aspect_step=5.0):
    """`daily_mj_binned` by component, the same bins and altitude interpolation: {"direct": MJ/m2 direct on the
    inclined cell, "diffuse": isotropic diffuse on the cell, (1 + cos s) / 2, unshaded, "global_flat": direct +
    diffuse on a horizontal surface}, float32, each under the cell's cloud as in `_cloud_split` (direct + diffuse
    equals `daily_mj_binned`). Feed the dict to `terrain_irradiance`."""
    cfg = cfg or load_config()
    lat = np.asarray(lat, np.float32)
    shape = np.broadcast(lat, np.asarray(slope_deg), np.asarray(aspect_deg)).shape
    slope = np.broadcast_to(np.asarray(slope_deg, np.float32), shape)
    aspect = np.broadcast_to(np.asarray(aspect_deg, np.float32), shape)
    alt_km = np.broadcast_to(np.asarray(alt_m, np.float32), shape) / 1000.0
    flat = aspect < 0
    li = np.round(np.broadcast_to(lat, shape) / lat_step).astype(np.int64)
    si = np.where(flat, 0, np.round(slope / slope_step)).astype(np.int64)
    ai = np.where(flat, 0, np.round((aspect % 360) / aspect_step)).astype(np.int64)
    key = (li * 256 + si) * 128 + ai
    uk, inv = np.unique(key.ravel(), return_inverse=True)
    u_li, u_si, u_ai = uk // (256 * 128), (uk // 128) % 256, uk % 128
    u_aspect = np.where(u_si == 0, -1.0, u_ai * aspect_step)
    lon0 = float(np.nanmean(np.asarray(lon, np.float32)))
    p0 = daily_parts(u_li * lat_step, lon0, date, u_si * slope_step, u_aspect, 0.0, 0.0, cfg)
    p1 = daily_parts(u_li * lat_step, lon0, date, u_si * slope_step, u_aspect, 1000.0, 0.0, cfg)
    clear = [p0[k][inv].reshape(shape) + (p1[k] - p0[k])[inv].reshape(shape) * alt_km
             for k in ("direct", "diffuse", "global_flat")]
    parts = _cloud_split(*clear, cloud, cfg)
    return dict(zip(("direct", "diffuse", "global_flat"), (x.astype(np.float32) for x in parts)))


def terrain_irradiance(parts, terrain_factor, svf, terrain_albedo=None, cfg=None):
    """MJ/m2 (float32) on the cell with its surroundings (Dozier & Frew 1990): direct x terrain_factor (the
    direct-only factor, `terrain_factor(..., direct_share=1.0)`) + diffuse x svf + (1 - svf) x terrain_albedo x
    global_flat. `parts` is the dict from `daily_components_binned` (or `daily_parts`), svf the sky-view factor
    0..1 (the lattice stores percent; divide by 100 first), terrain_albedo the albedo of the surrounding terrain,
    from cfg["terrain_albedo"] (default 0.5) when not given."""
    if terrain_albedo is None:
        cfg = cfg or load_config()
        terrain_albedo = float(cfg.get("terrain_albedo", 0.5))
    v = np.clip(np.asarray(svf, np.float32), 0, 1)
    out = (parts["direct"] * np.asarray(terrain_factor, np.float32) + parts["diffuse"] * v
           + (1 - v) * terrain_albedo * parts["global_flat"])
    return np.asarray(out, np.float32)
