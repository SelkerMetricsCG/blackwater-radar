# Method card: new snow as a storm total

**What it does.** For a window (12–72 h on the SNOTEL layer, 1–24 h for Weather stations and the "New snow"
interpolation) it smooths the station's hourly snow-depth record with a 3-reading running median (over the whole
record, so the window's first reading is smoothed with its real neighbours; the record's first and last readings are
left as they are), then reports the largest rise from any reading to a later, higher reading in that window. Rises below the noise floor
count as 0. Code: `newsnow.py`; parameters: `snotel_config.yaml`.

**Intuition.** New snow shows up as the depth climbing. Once snowfall stops, the new layer settles, so the depth at
the end of the window understates what fell. Measuring from the low point before the rise to the peak after it gives
the snowfall before settling eats into it: what "we got 14 inches last night" means.

**Assumptions.**
- The sensor's patch of ground gets the same snow as its surroundings (no drifting or scouring under it).
- One storm dominates the window. With two storms and settling between them, the larger rise is reported, not the sum.
- Hourly readings; the window's first reading is within 1 h of its start and the latest within 3 h of now.
- A single-hour excursion that comes straight back is a bad reading, not snow (see `ANOMALY_LOG.md`).

**Failure modes.**
- Brief dips or spikes in the depth record read as a rise. Winter 2025-26 showed many, often at 00:00 (Mt Hood Test Site
  2026-04-20: a one-hour dip from about 55 in to 2 in, which the unsmoothed storm total called 49 in). The running
  median removes single-hour excursions. On the 87 windows with a smoothed storm total of 4 in or more at the five
  test sites it left the total unchanged on 63, 1 in lower on 19 and 2–4 in lower on 5 (a one-hour peak trimmed, or a
  spike removed).
- Depth is reported in whole inches, so 1–2 in rises are within the noise; the floor handles that.
- Wind drifting under the sensor reads as new snow; scouring hides it.
- Two storms in one window: understated (the larger rise, not the sum).
- Rain on snow: depth falls, the total is 0 although precipitation fell (the precipitation gauge covers that).
- At some sites the depth sensor drops out more often during storms (Paradise, Alpine Meadows); the window then
  shows no value rather than a wrong one.

**Simpler methods shown beside it in the check** (`snotel_check/out/fig_*.png`): A = end minus start (what the map
showed before), C = end minus the window's lowest reading, and B = the storm total without smoothing.

**How the published method differs.** Ryan et al. (2008) estimated 6-h snowfall by summing positive depth changes
over 5- or 60-minute intervals after applying compaction routines (p. 667), smoothing noisy sensor data with 1- and
3-h moving averages first (p. 672–673). The largest-rise method here needs no compaction model and does not add up
sensor noise across many small rises; the price is that it reports the larger of two separate storms in a window,
not their sum.

**Independent check.** Implied new-snow density = pillow SWE gain ÷ storm total, from a different sensor (the pillow,
not the ultrasonic). Fresh snow is typically about 5–20 % water. At the five test sites, over the 77 November–April
windows with a smoothed storm total of 4 in or more and a pillow record, implied density had median 12 % (p10 5 %,
p90 23 %), and 81 % fell between 5 and 20 %. Exceptions worth knowing are in `ANOMALY_LOG.md` (a pillow that stopped
responding at Stevens in late March).

**Parameters and where they came from.** `snotel_config.yaml`: a 3-reading median (the smoothed and unsmoothed totals
differ on storm days at every test site) and a noise floor of 2.5 in, set just above the pooled dry-spell p95 of the
smoothed storm total (2.0 in; p99 3.0 in; 158 Dec–Mar windows with no SWE and no precipitation rise;
`snotel_check/out/summary.txt`). At 2.5 in, 2 of those 158 dry windows still show new snow (16 at a 2.0 in floor), and
76 windows with a 2 in rise read 0 (64 of them had some precipitation or SWE gain). Window slack 1 h and 3 h are
judgment calls.

**Reference.** Ryan, W. A., N. J. Doesken and S. R. Fassnacht (2008): Evaluation of ultrasonic snow depth sensors for
U.S. snow measurements. *Journal of Atmospheric and Oceanic Technology* 25, 667–684
(https://climate.colostate.edu/pdfs/2008JAOT25_5_667-684~Ryan_etal-evaluating_snow_depth_sensors.pdf).
- p. 667: the sensors "report the depth of snow directly beneath on average within 1 cm" of manual observations.
- p. 672: noisy sensor data were smoothed with moving averages before estimating snowfall.
- p. 679: wind and uneven snow surfaces disturb the sound pulse and cause imprecise readings.
- p. 682: "The sensor resolution introduces problems into calculating snowfall": coarser resolution gave more false
  snowfall reports. SNOTEL hourly depth is reported in whole inches.
