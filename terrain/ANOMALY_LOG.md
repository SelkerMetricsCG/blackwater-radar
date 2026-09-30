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

## 2026-09-30: check 4, two places far from the snow model's sun hours
- **Seen:** `python terrain/check_snow.py` (18 place-days): median difference -0.18 h, but Heather Meadows (Baker)
  3.6 h vs 7.0 h on 20 Mar and 9.3 vs 13.4 h on 21 Jun (sun arriving 14:32 instead of 11:08), and Colchuck Lake on
  21 Jun 9.9 vs 11.6 h (sun leaving 18:26 instead of 20:08). Figure `work/diag/4_horizon_vs_snow.png`.
- **Rival explanations:** (a) real: terrain within ~100 m of the sample point that 100 m cells average away;
  (b) the snow model's 16-direction interpolation missing a notch or spur; (c) a lidar spike or pit;
  (d) a fault in the layer's walk (unlikely after check 3, but untested on real terrain there);
  (e) a registration offset between the tiles and the ground.
- **Tests and evidence:**
  - Horizon at every degree from the tiles vs the lattice's 16 values: the gaps sit in whole sectors (Heather SE-S,
    tiles 44-60 deg vs lattice 27-35; Colchuck WNW, a smooth ~21 deg hump vs 7-9), not between two lattice
    directions: against (b).
  - Where the highest angle occurs along each sightline: Heather 19-75 m from the point (terrain 18-76 m above it);
    Colchuck 6 m (2 m above): near-field terrain, (a).
  - Transects: Heather's point is on a steep bank rising south from a flat lake surface (1,290 m) that lies 25-125 m
    north; Colchuck's point is 6 m above the hydro-flattened lake (1,694.8 m; published 5,570 ft) on its north-west
    shore, water to the east and south. Smooth, consistent profiles: against (c).
  - Independent sensor: the satellite basemap with the live slope-angle layer (same lidar, separate pipeline) at
    Heather Meadows, zoom 16: the steep band (35-60 deg) lies exactly on the imagery's south shore and the point at
    its foot: against (e). (An earlier zoom-17 look with the shade overlay on was misread as "point mid-lake"; the
    overlay had darkened the bank.)
- **Conclusion:** (a). The readout answers for the exact ~6 m spot clicked; the snow model's cell is a 100 m average.
  On banks, shores and cliff feet they differ, and the layer is the one that fits the spot. The other 15 place-days
  agree within about half an hour of sun. No change made. For Chris: whether the popup should say "for this exact
  spot" (it is implied by the click).
