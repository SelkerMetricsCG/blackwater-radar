# Sun & shade: anomaly log

## 2026-09-30: z10 mosaic colour scale ran to -800,000 m ("0.00 % no data")
- **Seen:** `work/diag/1_mosaics.png` (first build): the zoom-10 mosaic's colour bar spanned 0 to -900,000 m, and the
  accounting line said the mosaic had no no-data at all, although the ring reaches north of the US border.
- **Rival explanations:** (a) artefact: the warp forced one no-data value (-9999) on every source, while USGS 1 arc-second
  tiles mark no-data as -999999, so those pixels were averaged in as terrain; (b) real: bad cells in a USGS tile.
- **Test:** (a) predicts values near -999999 wherever a USGS tile has no-data pixels, and blends of it at their edges;
  (b) predicts spikes that survive a correct no-data setting. The code passed `srcNodata=-9999` to every source, and
  with each source's own no-data value the second build has none left: (a). Where the few -999999 pixels were was
  not traced (not north of 49 N, which turned out to be covered).
- **Effect on the first tiles:** no false elevations. Any average containing a -999999 pixel is negative, and the
  Terrarium encoder clips negatives to its no-data code, so those pixels read as "no terrain"; the fringe of no-data
  was wider than it should be.
- **Decision:** each source keeps its own no-data value; values below -1000 m count as no-data everywhere
  (`build_terrain.py` `warp_to`, `read_window`); mosaics and tiles rebuilt (commit "each warp source keeps its own
  no-data value"). Status: fixed. Second build (16:08): colour scale 0-4,400 m, the ring fully covered, including BC
  north of 49 N (USGS's border tiles carry Canadian terrain), `work/diag/1_mosaics.png`.
