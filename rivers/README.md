# rivers/ — the daily river analysis behind rivers.blackwaterlabs.org

Runs on GitHub Actions every morning (`.github/workflows/rivers.yml`, 15:30 UTC) and uploads to
the public `radar` bucket under `rivers/`. The site itself lives in `BlackwaterLabs/rivers/`
(its README explains the whole pipeline).

| File | What |
|---|---|
| `rivers_config.py` | The rivers: gauge, drainage area, SNOTEL stations (with per-river in-basin flags), default threshold and the preset list, flow bands, radar region, first water year. Add a river here. Four today: Peshastin (default), Plain, Icicle Creek, Monitor. |
| `run_rivers.py` | Runs the analysis for each river (`wenatchee/` package, same pipeline as `python -m wenatchee`), writes `out/<key>/output/`, uploads `web.js`, `report.txt`, the CSVs and `figures/*.png`, and `rivers/index.js` (the river list). One river failing does not stop the others. |
| `wenatchee/` | The analysis package. This is a copy of `BlackwaterLabs/Wenatchee_River_Analysis/wenatchee/` (the development copy, which has the self-test); `BlackwaterLabs/rivers/sync_analysis.bat` mirrors it here. Edit there, sync, commit, push. |
| `requirements.txt` | numpy, pandas, scipy, matplotlib, requests, boto3. |
| `out/` | Local outputs (gitignored). |

```
python rivers/run_rivers.py                      # all rivers, figures, upload (needs r2.env or R2_* env)
python rivers/run_rivers.py --no-upload          # local only
python rivers/run_rivers.py --only wenatchee-monitor --no-figures
```

About 3.5 minutes per river (the season-end block is recomputed at every preset threshold, roughly
15 s each), plus the upload; the four rivers take about 15 minutes on Actions.
