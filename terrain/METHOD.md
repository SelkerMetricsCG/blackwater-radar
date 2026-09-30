# Method card: sun and shade on terrain

What the map's Sun & shade layer computes, precisely enough to re-implement it without reading the page code.
Every number named here lives in `terrain_config.yaml` (`render:`), where its source is recorded.

## What it does
For a ground point P and an instant t, P is **in direct sun** when all three hold:
1. the sun is above the flat horizon (apparent elevation e > 0);
2. the ground at P faces the sun (self-shade test);
3. no terrain between P and `reach_km` toward the sun rises above the straight line from P to the sun (cast shade).

Intuition: stand on the spot, look toward the sun, and ask whether the ground you stand on tilts away from it or a
ridge blocks it. Clouds, trees, snow depth and buildings are not in the model.

## Inputs
- Elevation tiles: web-mercator XYZ, 256 x 256 px, Terrarium encoding
  `elev_m = R*256 + G + B/256 - 32768`; R = G = B = 0 means no data; a missing tile is all no data.
  Zoom 14 (about 6.5 m on the ground at 47.5 N) to 11 over the box, zoom 10 (about 100 m) over the box plus 30 km.
- Web mercator sphere radius Rm = 6378137 m. Pixel (i, j) of tile (z, x, y) has its centre at
  `X = -pi*Rm + (256*x + i + 0.5) * res_z`, `Y = pi*Rm - (256*y + j + 0.5) * res_z`, `res_z = 2*pi*Rm / (256 * 2^z)`;
  `lat = 2*atan(exp(Y/Rm)) - pi/2`, `lon = X/Rm` (radians). One ground metre is `cosh(Y/Rm)` mercator metres.

## Elevation at a point
Bilinear interpolation between the four surrounding pixel centres of one zoom's grid; if any of the four is no
data, the value is no data. The **near grid** is zoom 14 for the click readout (the map uses its view zoom capped at
14); the **far grid** is zoom 10. A near-grid no-data value falls back to the far grid; far no data means "no
terrain" (it can never shade).

## Sun position
NOAA's solar-position spreadsheet algorithm (Meeus), as in `snow/solar.py` `sun_position`: from the UTC instant,
the Julian century gives the sun's declination and the equation of time; the true solar time at the point's
longitude gives the hour angle; then true elevation e0 and azimuth A (degrees clockwise from north).
Apparent elevation e = e0 + r(e0) with NOAA's refraction r in degrees (e0 in degrees, tan in radians):
- e0 > 85: r = 0
- 5 < e0 <= 85: r = (58.1/tan e0 - 0.07/tan^3 e0 + 0.000086/tan^5 e0) / 3600
- -0.575 < e0 <= 5: r = (1735 + e0*(-518.2 + e0*(103.4 + e0*(-12.79 + e0*0.711)))) / 3600
- e0 <= -0.575: r = (-20.772 / tan e0) / 3600

## Self-shade test
g = the near grid's pixel size in ground metres at P (`res_z / cosh(Y/Rm)`). Sample the near grid bilinearly at
P +- one grid pixel east-west and north-south: `dzdx = (zE - zW) / (2g)`, `dzdy = (zN - zS) / (2g)`.
Normal n = (-dzdx, -dzdy, 1) (east, north, up), sun vector s = (cos e sin A, cos e cos A, sin e).
P is self-shaded when n . s <= 0.

## Cast-shade walk
- Start height h0 = z(P) + `bias_m`.
- Distances along the ground toward azimuth A: d1 = g_near; then d(k+1) = d(k) + max(g, `growth` * d(k)), where
  g is g_near while d(k) < `near_reach_km` and g_far (the far grid's ground pixel) after; stop past `reach_km`.
- Position at distance d: `Ym = Y0 + 0.5*d*cos(A)*cosh(Y0/Rm)`, then
  `X = X0 + d*sin(A)*cosh(Ym/Rm)`, `Y = Y0 + d*cos(A)*cosh(Ym/Rm)`.
- Terrain there: the near grid while d <= `near_reach_km` (far grid where the near grid has no data), the far grid
  beyond. Effective height `zt = z - d^2 * (1 - k) / (2 * Re)` (Earth curvature lessened by terrestrial refraction,
  Re = `earth_radius_m`, k = `refraction_k`).
- The ray's height `hr = h0 + d * tan(e)`. P is cast-shaded when zt > hr at any step.
- Early exit (speed only, changes nothing): stop when hr exceeds the highest elevation in the loaded data.

## Click readout
For the chosen date, every `readout_step_min` minutes from 00:00 to 24:00 Pacific: evaluate the three conditions.
A window is a run of consecutive lit steps, reported from its first to its last lit step; hours = lit steps x step.
"Flat horizon" = first and last step with e > 0.

## Assumptions and failure modes
- Bare earth: trees are not terrain. In forest the ground is shadier than drawn.
- A peak narrower than the walk's step at that distance can be stepped over (the steps grow to 1 % of the distance,
  so about 100-250 m past 10 km); a missed summit lowers the horizon there by a fraction of a degree.
- The map's near grid follows the view zoom: zoomed out (zoom 10-13) small ridges and gullies are averaged away,
  so the picture sharpens as you zoom in. The click readout always uses zoom 14.
- Terrain beyond 25 km is ignored (at a 5 degree sun a 2,000 m wall shades 23 km).
- North of 49 N there is no data (USGS stops at the border): BC terrain casts no shade.
- The web-mercator sphere differs from the WGS84 ellipsoid by about 0.1 % in ground distance.
- Apparent elevation <= 0 counts as night even where a summit would see the sun over a lower horizon.

## References
- NOAA Global Monitoring Laboratory, Solar Calculation Details and the NOAA_Solar_Calculations_day spreadsheet
  (gml.noaa.gov/grad/solcalc/calcdetails.html); J. Meeus, Astronomical Algorithms (1991).
- Terrestrial refraction coefficient 0.13: Gauss's standard mean value, used in trigonometric levelling; see
  W. Torge and J. Müller, Geodesy, 4th ed. (2012), chapter on atmospheric refraction (page not yet checked).
  It moves the answer little: at 25 km curvature drops the terrain 49 m, refraction gives back 6 m.
- Terrarium encoding: Mapzen / AWS Terrain Tiles documentation (github.com/tilezen/joerd, docs/formats.md).
