# Handoff: Coastal section (2026-10-13 14:50)

## State now
Built, merged to `main` (commits `deab3b1`..`f0be997` plus the handoff), **not yet pushed or deployed**. Local check in
the in-app browser passed (four layers, cards, click-anywhere rows, phone sheet, no console errors). Spec and ledger:
`docs/superpowers/specs/2026-10-13-coastal-section-design.md`; plan `docs/superpowers/plans/2026-10-13-coastal-section.md`;
catalogue `CATALOG.md`; checks `CHECKS.md` (three headline numbers match their sources; two rows open for the live check).

## Next steps, in order
1. Chris pushes `main` (9 commits). Then the first runs: buoys and tides in the next radar job whose minute is :00-:14 or
   :30-:44; marine and SST in the next hourly job (minute 4). Check R2: `pnw/data/buoys.js`, `tides.js`, `marine.js`, `sst.js`.
   Tide predictions fill 60 stations per run, so the tide layer is complete about 3 h after the first run.
2. `python build_web.py` is done; Chris runs the deploy; diff the live page against `web/index.html`.
3. Live check: the two open rows in `CHECKS.md` (CDIP 46211 against cdip.ucsd.edu, Tofino's next high against CHS),
   the Westport tide curve against CO-OPS's plot, and the marine zone colours against the CWF text.
4. Chris's judgment calls to confirm: spec §6 rows 1-13 (bins, stale thresholds, the cosine curve, the 60-per-run refresh).

## Deferred (catalogued with endpoints in `CATALOG.md`)
Spot table with per-spot checklist (needs Chris's review of `user_needs.md`), HF radar surface currents, GFS-Wave swell
raster, NWPS nearshore waves, HRDPS wind for the Strait, biotoxin and beach-closure layers, Canadian marine areas,
per-spot wind timelines, other regions (`coastal` flag in `region.py`).

## Gotchas
- `tides.py` takes about 100 s while the prediction cache fills; steady state is far shorter.
- The marine zone outlines are simplified to 0.002 deg for the page; the raw ones stay in `zone_cache.json`.
- The scratch preview (`build_scratch.py`, `serve_scratch.py`, launch entry `coastal-scratch`) lives in this session's
  scratchpad and dies with it; `.claude/launch.json` in radar still names it (harmless; remove the entry if it bothers).
- Worktree `scratchpad/radar-coastal` (branch `coastal`) can be removed: `git worktree remove <path>; git branch -d coastal`.
