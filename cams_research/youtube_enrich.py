"""
Check radar/webcams_youtube.json against the YouTube Data API: which video ids are live, ended, upcoming or
missing, each stream's title and channel, and whether each camera's `match` word is in its title. With
--search N it also searches up to N channels (100 quota units each) for their live streams and shows which
stream the hourly job's pick() would give each camera that isn't live on its listed id.

Uses the same key as the hourly job (YT_API_KEY, or radar/youtube.env). Quota: one unit per 50 ids plus
100 per search; the hourly jobs need about 5,200 of the 10,000 daily units at worst, so keep --search small.
Run from radar/:

    python cams_research/youtube_enrich.py                 # videos.list only (4 units)
    python cams_research/youtube_enrich.py --search 12     # plus up to 12 channel searches (1,200 units)
    python cams_research/youtube_enrich.py --json out.json # also write the results

Nothing is written to webcams_youtube.json: edit match words by hand from the report. Channel ids stay out of
the list on purpose: the hourly job learns them from videos.list and keeps them in its state file, which it
refreshes, because API data may be stored for 30 days at most (Developer Policies III.E.4). The same goes for
--json output: delete it within 30 days.
"""
import argparse
import json
import os
import sys

RADAR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RADAR)

import youtube  # noqa: E402


def status(it):
    if not it:
        return "missing"
    lbc = it["snippet"].get("liveBroadcastContent")
    if lbc == "live":
        return "live"
    if lbc == "upcoming":
        return "upcoming"
    return "ended" if it.get("liveStreamingDetails", {}).get("actualEndTime") else "not live"


def main(n_search, json_out):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # stream titles carry emoji
    key = youtube.api_key()
    if not key:
        raise SystemExit("no key: put YT_API_KEY=... in %s" % youtube.ENV)
    cams = youtube.load_list()
    api = youtube.Api(key)
    items = api.videos(sorted({c["video"] for c in cams if c.get("video")}))
    rows = []
    for c in cams:
        it = items.get(c.get("video")) if c.get("video") else None
        sn = it["snippet"] if it else {}
        m = (c.get("match") or "").lower()
        rows.append({"key": c["key"], "name": c["name"], "off": bool(c.get("off")), "video": c.get("video"),
                     "status": status(it) if c.get("video") else "no id", "title": sn.get("title"),
                     "channel": sn.get("channelId") or c.get("channel"), "channel_title": sn.get("channelTitle"),
                     "match_ok": (m in (sn.get("title") or "").lower()) if (m and it) else None,
                     "thumb": youtube.thumb(it) if it else None})

    # channels for cameras that have none of their own: any camera of the same site
    by_site = {}
    for r, c in zip(rows, cams):
        if r["channel"]:
            by_site.setdefault(c["site"], r["channel"])
    for r, c in zip(rows, cams):
        r["channel"] = r["channel"] or by_site.get(c["site"])

    searched = {}
    if n_search:
        todo = []
        for r, c in zip(rows, cams):
            if r["status"] != "live" and not r["off"] and r["channel"] and r["channel"] not in todo:
                todo.append(r["channel"])
        todo.sort(key=lambda ch: not any(r["status"] == "no id" and r["channel"] == ch for r in rows))
        for ch in todo[:n_search]:
            try:
                searched[ch] = api.search(ch)
            except youtube.ApiError as e:
                print("search %s failed: %s" % (ch, e))
                break
        for ch, streams in searched.items():
            on_ch = [(r, c) for r, c in zip(rows, cams) if r["channel"] == ch and not r["off"]]
            taken = {r["video"] for r, _ in on_ch if r["status"] == "live"}
            cands = [s for s in streams if s[0] not in taken]
            for r, c in sorted(on_ch, key=lambda rc: not rc[1].get("match")):
                if r["status"] == "live":
                    continue
                got = youtube.pick(c, cands, r["title"], sole=len(on_ch) == 1)
                r["search_pick"] = got
                if got:
                    cands.remove(got)
            for r, _ in on_ch:
                r["channel_live"] = [t for _, t in streams]

    order = {"live": 0, "upcoming": 1, "ended": 2, "not live": 3, "missing": 4, "no id": 5}
    for r in sorted(rows, key=lambda r: (r["off"], order[r["status"]], r["name"])):
        flag = "" if r["match_ok"] in (None, True) else "  <- match word not in title"
        line = "%-9s %-3s %-58s %-26s%s" % (r["status"], "off" if r["off"] else "", r["name"][:58],
                                             (r["title"] or "")[:26], flag)
        if "search_pick" in r:
            line += "\n            search: %s" % (("-> %s %r" % r["search_pick"]) if r["search_pick"] else
                                                   "no pick among %r" % r.get("channel_live"))
        print(line)
    from collections import Counter
    print("\n%d cameras (%d off): %s" % (len(rows), sum(r["off"] for r in rows),
                                         dict(Counter(r["status"] for r in rows if not r["off"]))))
    print("match word missing from a live title: %s" % [r["name"] for r in rows if r["match_ok"] is False])
    print("no channel known: %s" % [r["name"] for r in rows if not r["channel"] and not r["off"]])
    print("searches: %d; quota used: %d units" % (api.n_search, api.units))
    if json_out:
        with open(json_out, "w", encoding="utf-8") as f:
            json.dump(rows, f, indent=1, ensure_ascii=False)
        print("wrote", json_out)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--search", type=int, default=0, help="search up to N channels (100 units each)")
    ap.add_argument("--json", help="write the results here (API data: delete within 30 days)")
    a = ap.parse_args()
    main(a.search, a.json)
