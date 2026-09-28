# Anomaly log (radar)

One entry per anomaly, per `~/.claude/verification-protocol.md` (colleague mode). Evidence files are in
`snotel_check/out/` (regenerate with `python snotel_check/check_newsnow.py`).

## 2026-09-27: one-hour dips in SNOTEL hourly snow depth, often at 00:00
- **Seen:** readings that drop and come straight back in the next hour. Mt Hood Test Site 2026-04-20 00:00 fell from
  about 55 in to 2 in (`fig_651.png`), and dipped 2 in at 00:00 on 12, 14, 15 and 16 Dec; Alpine Meadows dipped 5-14 in
  at 00:00 on 27-30 May; Paradise had 133 hourly excursions of 2 in or more over the winter.
- **Why it matters:** a dip followed by the return reads as a rise, so the raw storm total (B) called the Mt Hood dip
  49 in of new snow; Paradise's raw B differs from the smoothed B3 on 22 of its 27 raw storm days (Alpine Meadows
  25 of 36, Blewett 5 of 9, Mt Hood 6 of 30, Stevens 3 of 22).
- **Hypotheses:** (1) instrument or logger artefact (a bad echo, or a routine that runs at midnight); predicts single-hour
  excursions, many at the same clock hour, no matching change in SWE or precipitation. (2) processing: a daily value or
  a different reading substituted at 00:00; predicts the same clock-hour pattern, possibly exact repeats of another
  element's value. (3) real change in depth; predicts a matching change in SWE, and no instant recovery. Rejected for
  the large cases: depth recovers within an hour and SWE is flat.
- **Test so far:** SWE and precipitation flat across the Mt Hood 04-20 dip (`windows_651.csv`: dSWE -0.7, dP 0.0 over the window).
- **Decision:** a 3-sample running median over the whole record before the storm total (`despike_width: 3`). It
  removes single-hour excursions; on the 87 windows with a smoothed total of 4 in or more it left 63 unchanged, 19
  1 in lower and 5 2-4 in lower (Stevens 2026-01-07: 17 in either way). Chosen by Claude under Chris's 2026-09-27
  "no stop" instruction; Chris to review.
- **Status:** handled by the filter; the cause (1 vs 2) is not established.

## 2026-09-27: Stevens Pass pillow flat through a 13 in snowfall, 2026-03-25 to 03-30
- **Seen:** window ending 2026-03-26 07:00: depth +12 in (B 13), precipitation gauge +0.9 in, pillow SWE 23.2 -> 23.2 in,
  and flat (23.1-23.3) through 03-30 (`raw_791_2025-10-01.json`).
- **Hypotheses:** (1) pillow bridging (a crust or ice layer carrying the new load past the pillow); predicts SWE lagging
  then catching up, or staying low against the gauge. (2) wind drifting under the depth sensor (depth artefact);
  predicts a flat gauge. (3) real 13 in of snow the pillow missed at ~7 % density; predicts gauge and depth agree.
- **Evidence:** the gauge (+0.9 in) and the depth sensor are independent of each other and agree, so (2) is unlikely;
  the pillow never caught up within 4 days, so a pillow-side problem (1) is the likely cause.
- **Decision:** none needed for the map's new-snow number (depth-based). The density check for this storm is not usable.
- **Status:** open (pillow cause unconfirmed); Chris's field knowledge of Stevens welcome.

## 2026-09-27: SNOTEL depth sensors drop out more often during precipitation at some sites
- **Seen:** winter 2025-26 hourly SNWD returned: Paradise 4,284 of 5,832 h (73 %); straight-line stretches in
  `fig_679.png` span its largest rises (early January, and 60 -> 119 in in March), so those storms produce no window.
- **Test:** share of SNWD hours missing while the gauge rose >= 0.1 in over the last 3 h vs otherwise (15 Nov-15 Apr):
  Paradise 44 % vs 30 %, Alpine Meadows 16 % vs 9 %, Stevens 0 % vs 0 %.
- **Hypotheses:** (1) the ultrasonic echo is lost in heavy snowfall or blowing snow (Ryan et al. 2008, p. 679, on wind
  and uneven surfaces disturbing the pulse); predicts gaps concentrated in storms. (2) NRCS quality control removes
  flagged values; predicts gaps unrelated to weather. (3) telemetry outages; predicts all elements missing together
  (not seen: PREC and WTEQ returned 97-99 % at Paradise).
- **Reading:** the excess during precipitation supports (1); the 30 % baseline at Paradise says (2) or a failing sensor
  also contributes.
- **Decision:** none. The coverage rule (`start_slack_h`, `end_slack_h`) makes such windows show "no reading" rather
  than a wrong number. Consequence to know: at gap-prone sites the new-snow value can be missing during the biggest storms.
- **Status:** open, informational.

## 2026-09-27: soil moisture reading exactly 0.0 % at 26 sensor depths
- **Seen:** local SNOTEL build 2026-09-27 ~10:30 PDT (pnw): 26 site/depth pairs report exactly 0.0 % volumetric water,
  e.g. Beaver Pass 2 and 4 in, Park Creek Ridge 2, 4 and 20 in, Chemult Alternate 20 in, Tipton 20 in, Mores Creek
  Summit 8 and 20 in, Soldier R.S. 20 in.
- **Hypotheses:** (1) failed or out-of-range sensor reporting its floor; predicts exactly 0.0 for long stretches,
  including wet periods, and at depths that stay moist. (2) real, very dry soil after the summer; predicts small
  non-zero values that respond to rain, shallow depths first. Exactly 0.0 at 20 in favours (1) at those sensors.
- **Test to run:** each sensor's record through last winter's wet season (a failed sensor stays at 0.0).
- **Decision:** none yet. The map shows the values as reported (spec judgment call: Chris decides whether to hide them).
- **Status:** open, for Chris.

## 2026-09-27: AirFire's NowCast for the newest hour can lag one hour (air quality check, Boundary County ID)
- **Seen:** data check 2026-09-28 ~03:00 UTC (pnw), `smoke_research/aq_check.py`: AirNow's PM25_AQI matched AirFire's
  NowCast (2024 breakpoints) at 241 of 242 stations; the exception, Boundary County (160210002, Idaho DEQ), had AirNow
  AQI 7 at 01 UTC against AirFire NowCast 2.3 ug/m3 (AQI 13). Hours 22, 23 and 00 UTC agreed exactly (0.7, 1.7, 2.3 ->
  AQI 4, 9, 13). AirFire's 01 UTC NowCast equals its 00 UTC value, and its in-progress 02 UTC row holds 1.3 (AQI 7),
  which is AirNow's 01 UTC value.
- **Hypotheses:** (1) the site's 01 UTC reading reached AirFire late, so AirFire computed the 01 UTC NowCast without it
  (carried forward) and folded it into the next row; predicts agreement at every other hour and at most sites.
  (2) AirFire and AirNow use different instruments at the site; rejected: AirFire has one deployment for the AQSID and
  the earlier hours agree. (3) a bug in our comparison; rejected: the same code agrees at 241 stations and every other hour.
- **Why it matters:** permanent monitors show AirNow's own AQI, so they are unaffected. Temporary monitors take AQI from
  AirFire's NowCast, so a late reading could leave a temporary monitor's newest hour one hour stale.
- **Decision:** none; the layer uses AirFire only for temporary monitors (spec decision 9). Chris to decide whether that
  one-hour risk matters.
- **Status:** explained (hypothesis 1), open for Chris.

## 2026-09-28: fires check (b): Hay Creek Complex perimeter 29 ac against 200,292 ac reported
- **Seen:** `smoke_research/fires_check.py pnw` joined one perimeter to the Hay Creek Complex (OR, 200,292 ac, 100 %
  contained): a 29 ac polygon named Esau Canyon carrying the complex's IRWIN id. 12 of 135 perimeters in the window had
  no fire in `fires.js`; four of them (0476 Hoag 50,224 ac, 0449 Porcupine Ridge 79,225, 0584 Cottonwood 15,659,
  0460 Hopkin 11,366) lie 13-31 km from the complex's point, all mapped 1,444 h ago; Crosswhite (355,065 ac) sits 69 km away.
- **Hypotheses:** (1) complex children's polygons carry the child's IRWIN id; `fires.py` drops children from the incident
  list, so their polygons become orphans and the complex keeps only a stray piece; predicts the orphans' ids are children
  whose `CpxID` is the complex. (2) a WFIGS data-entry error on one polygon; predicts no pattern across the orphans.
- **Test:** WFIGS `IsCpxChild=1` query, 2026-09-28 15:40 UTC: 18 children nationally, all 18 with `CpxID` equal to a
  current complex's IRWIN id; Porcupine Ridge and Hoag point to Hay Creek, Crosswhite to Rowe Creek. (1) supported.
- **Effect on the map as built:** the polygons still draw under their own names; the complex's card and `perim` flag
  refer to the 29 ac piece; hotspots inside a child's polygon link to an id that is not a fire, so the complex's
  24 h hotspot count misses them.
- **Status:** fixed 2026-09-28 (a2c6248, 0e8413e): child polygons and GOES links are relabelled to the parent via
  `CpxID`; the store keeps raw ids; Hay Creek itself has since left the WFIGS current layers (checked 14:29 PDT).
