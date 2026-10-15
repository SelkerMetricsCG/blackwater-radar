"""
Land mask for the surface-currents grid (currents.py), built once on a PC and committed:
  currents_landmask_<region>.png   1-bit PNG, 255 = water, 0 = land, on the 0.01 deg output grid of out_grid()
                                   (north row first, same orientation as the hour PNGs)

Source: GSHHG full-resolution shoreline (Wessel & Smith, LGPL), level 1 (land of the continents and islands).
A cell is land when its centre lies inside a land polygon, so a cell is water only if its centre is in the sea;
a 0.01 deg cell is about 0.7 mi wide, so the drawn water can still reach half a cell (~0.35 mi) onto the shore.
Lakes (level 2) are left as land: the ocean models have no values there.

Usage (PC only; needs geopandas and rasterio from the main Python):
  python coastal_research/make_landmask.py <path to GSHHS_f_L1.shp> [region]
"""
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import geopandas as gpd                      # noqa: E402
from PIL import Image                        # noqa: E402
from rasterio import features               # noqa: E402
from rasterio.transform import from_origin   # noqa: E402

shp = sys.argv[1]
if len(sys.argv) > 2:
    os.environ["REGION"] = sys.argv[2]
import currents                              # noqa: E402  (after REGION is set)
import region                                # noqa: E402

lat_c, lon_c, bbox = currents.out_grid()
ny, nx = len(lat_c), len(lon_c)
step = currents.STEP
lat0, lat1, lon0, lon1 = bbox
land = gpd.read_file(shp, bbox=(lon0 - 0.1, lat0 - 0.1, lon1 + 0.1, lat1 + 0.1))
print("GSHHG level 1 polygons in the window:", len(land))
transform = from_origin(lon0, lat1, step, step)          # north-up: row 0 is the top edge
mask = features.rasterize(((geom, 1) for geom in land.geometry), out_shape=(ny, nx), transform=transform,
                          fill=0, all_touched=False, dtype="uint8")   # centre-in-polygon rule
water = (mask == 0)
out = os.path.join(ROOT, "currents_landmask_%s.png" % region.KEY)
Image.fromarray(np.where(water, 255, 0).astype(np.uint8)).convert("1").save(out, optimize=True)
print("wrote", out, "%d x %d, %.1f %% water" % (nx, ny, 100 * water.mean()))
