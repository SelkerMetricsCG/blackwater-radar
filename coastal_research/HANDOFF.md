# Handoff: Coastal section research (2026-10-13 13:25)

## State now
Research done, nothing built. Chris asked (2026-10-13) for a new "Coastal" section of the radar map for PNW surfers
and kiters. Start with `CATALOG.md` (merged catalogue, first-build recommendation, open questions), then the
per-topic files for endpoints and station tables: `waves_buoys.md`, `tides_currents_sst.md`, `wind.md`,
`nanoos_ioos.md`, `webcams.md`, `user_needs.md` (gaps, walkthroughs, draft spot table). All untracked, not committed.

## Next steps
1. Chris answers the open questions in `CATALOG.md` section 4 (licences, Gorge, spots vs layers, owner asks).
2. Brainstorm and spec the section (`docs/superpowers/specs/`), then build in a radar worktree with the usual
   conventions (one module per source, `data/*.js`, tests with network blocked).
3. Quick wins that need no design: fix the Kalaloch cam URL, prune the dead Cannon Beach CBCC cam, add the Yaquina
   bar still and the ranked YouTube ids in `webcams.md` (verify thumbnails with `cams_research/youtube_enrich.py`).

## Gotchas
- Free tier only; no scraping where forbidden; no Synoptic/iKitesurf/Windy/Windguru; YouTube only via `youtube.py`.
- Agents sent a generic User-Agent and no personal data; keep it that way in any module.
- Several coordinates in the spot table and webcam list are best-effort; check on the map before use.
