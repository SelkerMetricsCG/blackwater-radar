# Slope-angle layer (WA Cascades)

Static tiles for the map's Terrain → Slope angle layer: CalTopo's bands (27–29, 30–31, 32–34, 35–45, 46–50,
51–59, 60°+) from USGS 1 m lidar averaged to 3 m, with the USGS 10 m DEM where there is no lidar. Live since
2026-09-28 (commit `6c6fa71`, deployed with `afc3e8f`). Map code: the `slope angle` section of `map.html`.

- `slope_config.yaml`: every parameter, with its source; judgment calls and library defaults are flagged.
- `build_slope.py`: stages `selftest inventory dem slope tiles check`, run with QGIS Python from this folder
  (`"C:\Program Files\QGIS 3.34.13\bin\python-qgis-ltr.bat" build_slope.py <stages>`). Each stage appends a line to
  `work/accounting.log` and draws a figure in `work/diag/`. Cells with a `.json` are skipped, so a stopped run resumes.
- `upload_tiles.py`: uploads zoom 11–15 to R2 `pnw/slope/v1/` (Chris runs it; resumable via `work/uploaded.txt`).
- `ANOMALY_LOG.md`: things that looked odd and how they were checked.

Tiles are cached as immutable: a rebuild must upload to a new prefix (`v2`) and the map's tile URL must change with it.

The first build (2026-09-27/28) downloaded about 200 GB over ~22 h on Chris's ~40 Mbps line. `work/` keeps the 3 m DEMs
(`dem3/`, 13 GB), the classed slope (`slope3/`) and the 10 m fallback (4 GB), so re-colouring or re-tiling needs no
downloads (the local tiles were deleted 2026-09-28 once on R2; `tiles` rebuilds them in about an hour); to add area, extend
`area.bbox_lonlat` and re-run from `inventory` (existing cells are skipped).

Gotchas found on the way:
- The TNM listing's `sizeInBytes` is stale for files USGS re-saved; check downloads against the server's Content-Length.
- GeoTIFF palettes drop alpha: "flatter than 27°" came out opaque black until the palette was reset on the VRT.
- Windows numpy defaults to int32 for sums; pixel counts for the whole area overflow it.
- gdal2tiles `--processes` on Windows re-imports the script: keep everything behind `if __name__ == "__main__"`.
- Slope must be computed in ground metres (UTM), never web-mercator metres (under-reads by cos(latitude)).
- The PC sleeping stalls downloads for up to 5 min after wake; keep it awake during a build.
- Open question: Mt Rainier's west half has no USGS 1 m lidar (10 m there); the WA DNR lidar portal was not checked.
