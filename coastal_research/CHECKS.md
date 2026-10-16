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
| SSCOFS h01 at Admiralty Inlet (48.15 N, -122.75 E) | u = -0.74, v = +0.40 m/s | native cell -0.745 / 0.399 m/s | OPeNDAP SSCOFS t15z f001 (valid 2026-10-13 16:00 UTC; cycle sscofs t15z + wcofs t03z) | match |
| SSCOFS h01 at the Columbia bar (46.25 N, -124.05 E) | u = -1.40, v = +0.10 m/s | native cell -1.390 / 0.093 m/s | OPeNDAP SSCOFS t15z f001 (valid 2026-10-13 16:00 UTC; cycle sscofs t15z + wcofs t03z) | match |
| Land mask (2026-10-15) | live h01 frame: 167,239 water cells, 8,561 (5.1 %) on GSHHG land; masked local frame: 158,678 water cells, 0 on land | GSHHG 2.3.7 full-resolution level 1 | `coastal_research/make_landmask.py` | match; visual check at Rockaway Beach, Grays Harbor and Elliott Bay: particles stop at the shore |
| GFS-Wave hour 0 at 46041 (PNG vs model grid) | 3.0 ft, 12.0 s, 292° | 3.1 ft, 11.9 s, 292° (GFS-Wave 18Z 2026-10-15 model grid) | GFS-Wave wcoast 0.16° grid, f000 | match (18Z 2026-10-15) |
| GFS-Wave hour 0 at 46050 (PNG vs model grid) | 4.3 ft, 12.0 s, 292° | 4.3 ft, 12.0 s, 292° (same run) | GFS-Wave wcoast 0.16° grid, f000 | match (18Z 2026-10-15) |
| NWPS Westport offshore cell hour 0 | 2.3 ft, 12.5 s, from 236° (pqr 18Z) | not yet | buoy 46211 at the live check | open: compare with buoy 46211 at the live check |
| GFS-Wave vs observed at 46041 | GFS-Wave hour 0 at 46041 (as above) | observed Hs/period/direction for 46041 | NDBC `realtime2/46041.txt` | open for the live check (the buoy card shows both) |

Still to do at the live check (after the first Actions runs and the deploy): the two open rows above; the page's
tide curve against CO-OPS's plotted curve at Westport (the cosine between extremes is a judgment call); the marine
zone colours against the CWF text; the SST legend against the overlay; the particle direction at Admiralty Inlet against the Tides & currents layer's flood/ebb at the same hour.
