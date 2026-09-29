# Slope-angle layer: anomaly log

## 1. Horizontal strip of 27–34° ground near 5,250 km N (2026-09-28)
- **Seen:** the 90 m overview (`work/diag/4_slope_overview.png`) shows a band of dense yellow and orange between
  about 5,245 and 5,255 km north, 640–700 km east (UTM 10N), sharper-edged than the ground north and south of it.
- **Rival explanations:** (a) real terrain; (b) a lidar flight whose bare earth is rough (low vegetation or rock
  left in), which would show as extra pixel-scale 27°+ speckle; (c) a seam between two flights on a cell edge.
- **Tests:** flights per cell (`work/dem3/*.json`): the steep row n524 and the calm row n523 are both almost all
  WA_CentralWildfire_D22, so the jump falls between cells from the same flight, against (c). Slope from the USGS 10 m
  DEM over the same area (`work/diag/5_strip_check.png`) shows the same band; share ≥27° by 5 km row tracks the 3 m
  layer everywhere (3 m is 3–5 points higher throughout, as finer data catches more short pitches), against (b).
- **Independence caveat:** the USGS 10 m DEM may itself be built from the same lidar here, so this rules out errors in
  our processing, not in the lidar. A flight-level roughness artefact would, however, be pixel-scale and would not
  survive resampling to 10 m.
- **Status:** real terrain: the south flank of the Stuart Range and the Wenatchee Mountains, with the Teanaway /
  Swauk lowlands starting just south of it. Shown to Chris 2026-09-28. No change to the build.
