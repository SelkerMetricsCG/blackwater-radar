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
