# Sun & shade: anomaly log

## 2026-09-30: z10 mosaic colour scale ran to -800,000 m ("0.00 % no data")
- **Seen:** `work/diag/1_mosaics.png` (first build): the zoom-10 mosaic's colour bar spanned 0 to -900,000 m, and the
  accounting line said the mosaic had no no-data at all, although the ring reaches north of the US border.
- **Rival explanations:** (a) artefact: the warp forced one no-data value (-9999) on every source, while USGS 1 arc-second
  tiles mark no-data as -999999, so those pixels were averaged in as terrain; (b) real: bad cells in a USGS tile.
- **Test:** (a) predicts values near -999999 only where USGS tiles have no coverage (north of 49 N) and blends of it at
  their edges; (b) predicts isolated spikes anywhere. The code passed `srcNodata=-9999` to every source: (a).
- **Effect on the first tiles:** no false elevations. Any average containing a -999999 pixel is negative, and the
  Terrarium encoder clips negatives to its no-data code, so those pixels read as "no terrain"; the fringe of no-data
  was wider than it should be.
- **Decision:** each source keeps its own no-data value; values below -1000 m count as no-data everywhere
  (`build_terrain.py` `warp_to`, `read_window`); mosaics and tiles rebuilt (commit "each warp source keeps its own
  no-data value"). Status: fixed; second build's figure and accounting line are the check.
