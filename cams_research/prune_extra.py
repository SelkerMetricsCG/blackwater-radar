"""
Check every curated camera in radar/webcams_extra.json from this PC and list the ones that don't load.
The hourly job can't do this itself: several camera hosts refuse or 404 GitHub's runners while serving
browsers fine. Run from radar/ on a home connection:

    python cams_research/prune_extra.py            # list failures only
    python cams_research/prune_extra.py --apply    # also remove them from webcams_extra.json

Entries marked robots are skipped (their sites ask not to be fetched by scripts). Server errors (5xx) and
timeouts are listed as temporary and never removed (Mt Bachelor's camera API returned 504 for an hour on
2026-09-27); --apply removes only 404/410, 401/403 and non-image answers. Some cameras still drop out for a
while at night or off-season, so check twice a few hours apart before --apply.
"""
import concurrent.futures as cf
import json
import os
import sys

RADAR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RADAR)

import webcams  # noqa: E402

EXTRA = os.path.join(RADAR, "webcams_extra.json")


def main(apply):
    d = json.load(open(EXTRA, encoding="utf-8"))
    todo = [c for c in d["cams"] if not c.get("robots")]
    with cf.ThreadPoolExecutor(12) as ex:
        res = list(ex.map(lambda c: webcams.check_image(c["img"]), todo))
    failed = [(c, st, why) for c, (st, ts, why) in zip(todo, res) if st != "ok"]
    temporary = lambda why: why.startswith("HTTP 5") or not why.startswith("HTTP") and why not in ("not an image", "offline card")
    for c, st, why in failed:
        print("%-11s %-14s %s" % ("temporary" if temporary(why) else st, why, c["name"]))
    bad = [f for f in failed if not temporary(f[2])]
    print("%d of %d curated cameras failed from this PC (%d temporary, kept)" % (len(failed), len(todo), len(failed) - len(bad)))
    if apply and bad:
        drop = {c["img"] for c, _, _ in bad}
        cams = [c for c in d["cams"] if c["img"] not in drop]
        with open(EXTRA, "w", encoding="utf-8") as f:
            f.write('{"note": %s,\n "cams": [\n' % json.dumps(d.get("note", "")))
            f.write(",\n".join(json.dumps(r, ensure_ascii=False) for r in cams))
            f.write("\n]}\n")
        print("removed %d; webcams_extra.json has %d cameras" % (len(bad), len(cams)))


if __name__ == "__main__":
    main("--apply" in sys.argv)
