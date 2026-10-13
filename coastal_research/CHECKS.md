# Coastal section: independent checks (2026-10-13)

Each headline number from the modules' first local runs, against the source itself, fetched again by hand
(curl, generic User-Agent) a few minutes later. Verification protocol: one independent check per headline number.

| What | Module value | Source value | Source | Result |
|---|---|---|---|---|
| 46041 Cape Elizabeth waves | 4.3 ft, 11 s, 288°, water 53.8 °F | 1.3 m (4.27 ft), 11 s, 288°, 12.1 °C (53.8 °F) at 20:20Z | `realtime2/46041.txt` | match |
| Westport (9441102) next high | 14:42 PDT, 9.43 ft MLLW | 14:42, 9.434 ft | CO-OPS predictions, `interval=hilo`, `time_zone=lst_ldt` | match |
| Deception Pass (PUG1701, bin 33) | flood 4.05 kt 15:19, slack 17:58, ebb 6.45 kt 20:52 | 15:19 flood 4.05, 17:58 slack, 20:52 ebb -6.45 | CO-OPS `currents_predictions`, `MAX_SLACK` | match (the module stores speed as a positive number with the kind) |
| SST at 46041's position | 53.7 °F (cell 47.325, -124.725; next cell north 53.0) | buoy water temperature 53.8 °F (NDBC) | Geo-Polar Blended 2026-10-12 vs the buoy on 10-13 | within 0.1 °F at the pixel; the analysis is a day older than the buoy |
| 46211 Grays Harbor (CDIP relay) | 3.5 ft, 11.1 s, 292° (CDIP swell 2.6 ft 15.4 s 270°) | not re-checked by hand | CDIP ERDDAP | open: compare with cdip.ucsd.edu stn 036 at the live check |
| Tofino (CHS) next high | not yet in the cache at the first run (predictions fill 60 stations per run) | | CHS IWLS | open: check at the live check |

Still to do at the live check (after the first Actions runs and the deploy): the two open rows above; the page's
tide curve against CO-OPS's plotted curve at Westport (the cosine between extremes is a judgment call); the marine
zone colours against the CWF text; the SST legend against the overlay.
