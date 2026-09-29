"""
Solar term for the snow-conditions model: sun position, clear-sky irradiance on an inclined cell, cloud
scaling and daily totals. Pure numpy, no network. Parameters and their sources: snow/snow_config.yaml (solar).

  sun_position(lat, lon, t_utc)                       -> (elevation deg, azimuth deg from N clockwise)
  clear_sky_direct(elev_deg, alt_m)                    -> direct-normal W/m2 (0 below the horizon)
  cos_incidence(sun_el, sun_az, slope_deg, aspect_deg) -> cos of the angle between sun and the cell's normal
  daily_mj(lat, lon, date, slope_deg, aspect_deg, alt_m, cloud=0)
                                                       -> MJ/m2 on the slope for that day (arrays welcome)
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


def irradiance(lat, lon, t_utc, slope_deg, aspect_deg, alt_m=0.0, cloud=0.0, cfg=None):
    """W/m2 on the inclined cell at one instant: direct + isotropic diffuse, scaled by cloud"""
    cfg = cfg or load_config()
    el, az = sun_position(lat, lon, t_utc)
    dni = clear_sky_direct(el, alt_m, cfg)
    direct = dni * cos_incidence(el, az, slope_deg, aspect_deg)
    s = np.radians(np.where(np.asarray(aspect_deg, float) < 0, 0.0, slope_deg))
    diffuse = cfg["diffuse_fraction"] * dni * np.sin(np.radians(np.clip(el, 0, 90))) * (1 + np.cos(s)) / 2
    return (direct + diffuse) * cloud_factor(cloud, cfg)


def daily_mj(lat, lon, date, slope_deg, aspect_deg, alt_m=0.0, cloud=0.0, cfg=None):
    """MJ/m2 over the UTC day (00-24 UTC, i.e. 16:00 to 16:00 Pacific, which contains one full local daylight period)"""
    cfg = cfg or load_config()
    step = int(cfg["step_min"])
    total = np.zeros(np.broadcast(np.asarray(lat, float), np.asarray(slope_deg, float), np.asarray(aspect_deg, float)).shape)
    t0 = dt.datetime(date.year, date.month, date.day)
    for m in range(0, 1440, step):
        total = total + irradiance(lat, lon, t0 + dt.timedelta(minutes=m), slope_deg, aspect_deg, alt_m, cloud, cfg)
    return total * step * 60 / 1e6


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
