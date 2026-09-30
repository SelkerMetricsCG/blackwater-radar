"""
Sunrise and sunset on the terrain for a point and a date, from the lattice's horizon angles: the first and last
times the sun's elevation clears the terrain's horizon in the sun's direction. For checking the terrain shading
against ShadeMap, SunCalc or a watch on the ridge.

  python -m snow.sunhours --lat 47.494 --lon -120.833 --date 2026-12-21 [--tz -8]
"""
import argparse
import datetime as dt

import numpy as np

from snow import forcing, solar


def horizon_at(horizon, azimuth, azimuths=None):
    """the terrain horizon angle toward an azimuth, interpolated between the directions the lattice holds"""
    n = len(horizon)
    az = azimuths or (solar.DIR16_AZ if n == 16 else [k * 360.0 / n for k in range(n)])
    a = azimuth % 360.0
    order = sorted(range(n), key=lambda k: az[k])
    for i, k in enumerate(order):
        k2 = order[(i + 1) % n]
        a0, a1 = az[k], az[k2] if az[k2] > az[k] else az[k2] + 360.0
        aa = a if a >= a0 else a + 360.0
        if a0 <= aa <= a1:
            frac = (aa - a0) / (a1 - a0) if a1 > a0 else 0.0
            return (1 - frac) * float(horizon[k]) + frac * float(horizon[k2])
    return float(horizon[order[0]])


def sun_on_terrain(horizon, lat, lon, date, tz_offset_h, step_min=2):
    """(first, last, hours) local times the sun is above the terrain, and total hours of direct sun"""
    t0 = dt.datetime(date.year, date.month, date.day) - dt.timedelta(hours=tz_offset_h)
    first = last = None
    n = 0
    for m in range(0, 1440, step_min):
        t = t0 + dt.timedelta(minutes=m)
        el, az = solar.sun_position(lat, lon, t)
        if el > horizon_at(horizon, float(az)) and el > 0:
            n += 1
            local = t + dt.timedelta(hours=tz_offset_h)
            first = first or local
            last = local
    return first, last, n * step_min / 60.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lat", type=float, required=True)
    ap.add_argument("--lon", type=float, required=True)
    ap.add_argument("--date", required=True)
    ap.add_argument("--tz", type=float, default=-8)
    a = ap.parse_args()
    from snow import replay
    lat, meta = replay.load_lattice()
    r, c = forcing.cell_of(meta, [a.lat], [a.lon])
    if r[0] < 0 or "horizon" not in lat:
        raise SystemExit("point outside the lattice, or the lattice has no horizon layer (rebuild with snow static)")
    hz = lat["horizon"][:, r[0], c[0]]
    date = dt.date.fromisoformat(a.date)
    flat = np.zeros(len(hz), np.uint8)
    f1, l1, h1 = sun_on_terrain(flat, a.lat, a.lon, date, a.tz)
    f2, l2, h2 = sun_on_terrain(hz, a.lat, a.lon, date, a.tz)
    print("cell %d,%d elev %d m, horizon by direction (N clockwise, %d directions): %s" % (r[0], c[0], lat["elev"][r[0], c[0]], len(hz), hz.tolist()))
    print("flat horizon:    sun %s to %s, %.1f h" % (f1.strftime("%H:%M") if f1 else "-", l1.strftime("%H:%M") if l1 else "-", h1))
    print("with terrain:    sun %s to %s, %.1f h" % (f2.strftime("%H:%M") if f2 else "-", l2.strftime("%H:%M") if l2 else "-", h2))


if __name__ == "__main__":
    main()
