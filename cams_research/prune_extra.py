"""
Check every curated camera in radar/webcams_extra.json from this PC and list the ones that don't load.
The hourly job can't do this itself: several camera hosts refuse or 404 GitHub's runners while serving
browsers fine. Run from radar/ on a home connection:

    python cams_research/prune_extra.py            # list failures only
    python cams_research/prune_extra.py --apply    # also remove them from webcams_extra.json

Entries marked robots are skipped (their sites ask not to be fetched by scripts). Check twice, a few hours
apart, before --apply: some cameras drop out for a while at night or in the off-season.
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
    bad = [(c, st, why) for c, (st, ts, why) in zip(todo, res) if st != "ok"]
    for c, st, why in bad:
        print("%-11s %-12s %s" % (st, why, c["name"]))
    print("%d of %d curated cameras failed from this PC" % (len(bad), len(todo)))
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
