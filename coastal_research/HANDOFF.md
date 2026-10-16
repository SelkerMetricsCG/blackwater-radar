# Handoff: Coastal section (2026-10-15 19:20)

## State now
**Live.** Pushed as `b95c603` (tests green), first data on R2 at 15:07-15:12, page deployed 15:2x (Worker version
`5f238b31`, live page identical to `web/index.html`). Local and live checks passed (four layers, cards, click-anywhere
rows, phone sheet, no console errors). Spec and ledger:
`docs/superpowers/specs/2026-10-13-coastal-section-design.md`; plan `docs/superpowers/plans/2026-10-13-coastal-section.md`;
catalogue `CATALOG.md`; checks `CHECKS.md` (three headline numbers match their sources; two rows open for the live check).
Surface currents flow layer **live** since 19:10 (pushed `aa3e2c0`, CI green, deploy version `30243ce8` with the Worker route; first cycle sscofs t21z + wcofs t03z on R2; live page identical to `web/index.html`). Spec `docs/superpowers/specs/2026-10-13-currents-flow-layer-design.md`.
2026-10-15: GSHHG land mask (`currents_landmask_pnw.png`, `coastal_research/make_landmask.py`) and particles that die on land,
pushed `706cb9a`, deployed; cycle names carry `-m1`; Chris confirmed the coast is clean at 17:28.

Swell forecast **live** 2026-10-15 19:1x: pushed `8e34c09` + CI fix `66930da` (green), deploy version `5ba5b59f`; first data on R2 from the 19:04 hourly run (swell 57 steps, nwps 25 h, 26 of 29 beaches, 14 buoy forecasts).

## Next steps, in order
1. Tide predictions fill 60 stations per run; the tide layer is complete by about 18:00 on 2026-10-13.
2. Live check still to do: the two open rows in `CHECKS.md` (CDIP 46211 against cdip.ucsd.edu, Tofino's next high against CHS),
   the Westport tide curve against CO-OPS's plot, and the marine zone colours against the CWF text.
3. Chris's judgment calls to confirm: spec §6 rows 1-13 (bins, stale thresholds, the cosine curve, the 60-per-run refresh).
4. Live check of the currents layer still to do: particle direction at Admiralty Inlet against the Tides & currents layer's flood/ebb for the same hour (`CHECKS.md`); the spec's judgment calls (§5) await Chris.

## Deferred (catalogued with endpoints in `CATALOG.md`)
Spot table with per-spot checklist (needs Chris's review of `user_needs.md`), HF radar surface currents, HRDPS wind for the Strait, biotoxin and beach-closure layers, Canadian marine areas,
per-spot wind timelines, other regions (`coastal` flag in `region.py`), the home-built tide model (would feed the same renderer; score it against the 53 current stations).
Swell (2026-10-15): swell particle animation; Environment Canada wave model for BC; Tofino and Short Sands beaches have no NWPS sample (outside the nests).

## Gotchas
- `tides.py` takes about 100 s while the prediction cache fills; steady state is far shorter.
- The marine zone outlines are simplified to 0.002 deg for the page; the raw ones stay in `zone_cache.json`.
- The scratch preview (`build_scratch.py`, `serve_scratch.py`, launch entry `coastal-scratch`) lives in this session's
  scratchpad and dies with it; `.claude/launch.json` in radar still names it (harmless; remove the entry if it bothers).
- Worktree `scratchpad/radar-coastal` (branch `coastal`) can be removed: `git worktree remove <path>; git branch -d coastal`.
