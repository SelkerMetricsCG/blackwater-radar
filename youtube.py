"""
YouTube-live webcams for webcams.py, through the YouTube Data API v3 and nothing else.

Cameras: webcams_youtube.json (kept by hand; built from the YouTube entries of cams_research/combined.json;
cams_research/make_extra.py never touches it). Key: YT_API_KEY from the environment (the hourly workflow's
secret of that name) or radar/youtube.env (one line YT_API_KEY=..., gitignored). Without a key there are no
YouTube cameras: nothing is fetched and one line is logged.

Each hourly run, per region:
  1. videos.list (part=snippet,liveStreamingDetails, up to 50 ids a call) for every camera's current video id.
     A live video shows the API's best thumbnail (maxres > standard > high), credited to YouTube on the map.
  2. A camera whose video is gone or no longer live: search.list on its channel (channelId, eventType=live,
     type=video) for the channel's live streams, matched to the camera by title (pick()). A match is saved in
     the state file and confirmed with one more videos.list; no match leaves the camera out this run.
  3. State in data/youtube_cache.json (current id, channel and title per camera; recent searches). cloud.py
     keeps it between runs (STATE_FILES); the _cache.json name keeps r2sync from publishing it.

YouTube API Services terms (Developer Policies, read 2026-09-27):
  - only https://www.googleapis.com/youtube/v3/ is requested: never i.ytimg.com (viewers' browsers load the
    thumbnails from the URLs the API returns) and never youtube.com pages (III.E.6, no scraping)
  - API data is refreshed every run; state the API hasn't confirmed for FORGET_D days is dropped (III.E.4)
  - map.html shows the YouTube icon and name, linked to the video, with every YouTube thumbnail (III.F.2),
    says which details are not from YouTube (III.E.4.h) and links YouTube's Terms and Google's Privacy Policy;
    terms.html is the site's terms and privacy notice (III.A)

Quota. The free tier is 10,000 units a day per key (reset at midnight Pacific), shared by the five region
jobs, which run every hour in parallel and overlap (one camera can be looked up by two regions):
  - videos.list costs 1 unit per call of up to 50 ids. 2026-09-27 list: pnw 62 ids (2 calls), sierra 35,
    utco 18, imw 39 (1 call each), ne 0 (no call); plus at most one confirming call after searches. At most
    9 calls an hour, about 220 units a day.
  - search.list costs 100 units. Each region makes at most SEARCH_CAP searches in any 24 hours (the times are
    in the state file): 5 x 10 x 100 = 5,000 units a day at worst (4,000 while ne has no YouTube cameras).
  Worst case about 5,200 units a day, leaving 4,800 for cams_research/youtube_enrich.py and growth.
  Every run logs the units it used and how many of the day's searches are spent.
The key travels in the X-goog-api-key header, never in a URL, so it can't reach a log.

Run standalone (no upload):  python youtube.py
"""
import calendar
import html
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

import region

ROOT = os.path.dirname(os.path.abspath(__file__))
LIST = os.path.join(ROOT, "webcams_youtube.json")
ENV = os.path.join(ROOT, "youtube.env")
STATE = os.path.join(region.data_dir(), "youtube_cache.json")
API = "https://www.googleapis.com/youtube/v3/"
UA = "BlackwaterRadar/1.0 (+https://radar.blackwaterlabs.org)"
SEARCH_CAP = 10        # search.list calls per region in any 24 hours (100 units each; see the budget above)
SEARCH_RETRY_H = 24    # a channel searched without a match is searched again after this long...
FORGET_D = 30          # ...and API data not confirmed for this many days is dropped (Developer Policies III.E.4)
THUMBS = ("maxres", "standard", "high")


class ApiError(Exception):
    def __init__(self, code, reason):
        super().__init__("HTTP %s %s" % (code, reason) if code else reason)
        self.code, self.reason = code, reason


def api_key():
    """The key from YT_API_KEY or radar/youtube.env, or None. Never log it."""
    key = os.environ.get("YT_API_KEY", "").strip()
    if not key and os.path.exists(ENV):
        with open(ENV, encoding="utf-8-sig") as f:
            for line in f:
                k, _, v = line.strip().partition("=")
                if k.strip() == "YT_API_KEY" and v.strip():
                    key = v.strip()
    return key or None


def _get(url, key):
    """GET one Data API URL -> parsed JSON. The key travels in a header, so it is never part of a URL or a log line."""
    if not url.startswith(API):
        raise ValueError("youtube.py only calls the YouTube Data API")
    req = urllib.request.Request(url, headers={"X-goog-api-key": key, "User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        reason = "error"
        try:
            err = json.loads(e.read())["error"]
            reason = (err.get("errors") or [{}])[0].get("reason") or err.get("status") or reason
        except Exception:  # noqa: BLE001
            pass
        raise ApiError(e.code, str(reason).replace(key, "***")) from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise ApiError(0, type(e).__name__) from None


class Api:
    """The two Data API calls the job makes, with a running count of quota units."""

    def __init__(self, key, get=None):
        self.key, self.get = key, get or _get
        self.units = self.n_videos = self.n_search = 0

    def videos(self, ids):
        """{id: item} for the ids YouTube still has (deleted and private videos are simply missing)."""
        out = {}
        ids = list(ids)
        for i in range(0, len(ids), 50):
            q = urllib.parse.urlencode({
                "part": "snippet,liveStreamingDetails", "id": ",".join(ids[i:i + 50]), "maxResults": 50,
                "fields": "items(id,snippet(channelId,channelTitle,title,liveBroadcastContent,thumbnails),"
                          "liveStreamingDetails(actualStartTime,actualEndTime))"})
            self.units += 1
            self.n_videos += 1
            for it in self.get(API + "videos?" + q, self.key).get("items", []):
                out[it["id"]] = it
        return out

    def search(self, channel):
        """[(id, title)] of the channel's live streams right now."""
        q = urllib.parse.urlencode({"part": "snippet", "channelId": channel, "eventType": "live", "type": "video",
                                    "maxResults": 50, "fields": "items(id(videoId),snippet(title))"})
        self.units += 100
        self.n_search += 1
        d = self.get(API + "search?" + q, self.key)
        # search.list titles come HTML-escaped ("Everett&#39;s 8800 Cam"); videos.list titles don't
        return [(it["id"]["videoId"], html.unescape(it["snippet"]["title"])) for it in d.get("items", [])
                if it.get("id", {}).get("videoId")]


def load_list(path=None):
    with open(path or LIST, encoding="utf-8") as f:
        return json.load(f)["cams"]


def load_state(path=None):
    try:
        with open(path or STATE, encoding="utf-8") as f:
            st = json.load(f)
    except (OSError, ValueError):
        st = {}
    st.setdefault("cams", {})
    st.setdefault("channels", {})
    st.setdefault("searches", [])
    return st


def save_state(st, path=None):
    path = path or STATE
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        json.dump(st, f, indent=0, sort_keys=True)
    os.replace(path + ".tmp", path)


def prune(st, now):
    """Drop API data older than FORGET_D days and search times older than a day."""
    old = now - FORGET_D * 86400
    st["cams"] = {k: e for k, e in st["cams"].items() if e.get("seen", now) >= old}
    st["channels"] = {k: e for k, e in st["channels"].items() if e.get("searched", now) >= old}
    st["searches"] = [t for t in st["searches"] if t > now - 86400]


def is_live(item):
    return item.get("snippet", {}).get("liveBroadcastContent") == "live"


def thumb(item):
    th = item.get("snippet", {}).get("thumbnails", {})
    for k in THUMBS:
        if th.get(k, {}).get("url"):
            return th[k]["url"]
    return None


def epoch(iso):
    if not iso:
        return None
    try:
        return calendar.timegm(time.strptime(iso[:19], "%Y-%m-%dT%H:%M:%S"))
    except ValueError:
        return None


def pick(cam, cands, old_title, sole):
    """The live stream (id, title) among cands that is this camera, or None when unsure.
    With a match word: the one title containing it (the old title breaks a tie). Without: the stream with the
    camera's old title, or the only stream when the camera is its channel's only one here."""
    m = (cam.get("match") or "").lower()
    if m:
        hits = [x for x in cands if m in x[1].lower()]
        if len(hits) == 1:
            return hits[0]
        same = [x for x in hits if old_title and x[1] == old_title]
        return same[0] if len(same) == 1 else None
    same = [x for x in cands if old_title and x[1] == old_title]
    if len(same) == 1:
        return same[0]
    return cands[0] if sole and len(cands) == 1 else None


def resolve(cams, api, st, now=None, log=print):
    """-> [(camera, video item)] for the cameras live now. Updates st (the state) in place."""
    now = int(now or time.time())
    prune(st, now)
    sc = st["cams"]
    cur = {}
    for c in cams:
        e = sc.get(c["key"])
        if e and e.get("list") != c.get("video"):  # the list's id was edited by hand: start again from it
            sc.pop(c["key"])
            e = None
        cur[c["key"]] = (e or {}).get("id") or c.get("video")
    items = api.videos(sorted({v for v in cur.values() if v}))

    live, need = {}, []
    for c in cams:
        e = sc.setdefault(c["key"], {"list": c.get("video")})
        it = items.get(cur[c["key"]]) if cur[c["key"]] else None
        if it:
            sn = it["snippet"]
            e.update(id=it["id"], channel=sn.get("channelId"), title=sn.get("title"), seen=now)
            if is_live(it):
                e["live"] = now
                live[c["key"]] = it
                continue
        need.append(c)

    def channel_of(c):
        for o in [c] + [o for o in cams if o is not c and o.get("site") == c.get("site")]:
            ch = sc.get(o["key"], {}).get("channel") or o.get("channel")
            if ch:
                return ch
        return None

    by_ch, no_ch = {}, []
    for c in need:
        ch = channel_of(c)
        (by_ch.setdefault(ch, []) if ch else no_ch).append(c)

    def due(ch):
        searched = st["channels"].get(ch, {}).get("searched", 0)
        last_live = max(sc.get(c["key"], {}).get("live", 0) for c in by_ch[ch])
        return last_live > searched or now - searched >= SEARCH_RETRY_H * 3600, last_live, searched

    order = sorted((ch for ch in by_ch if due(ch)[0]),
                   key=lambda ch: (due(ch)[1] <= due(ch)[2], -due(ch)[1], due(ch)[2], ch))
    found, skipped, quota_hit = {}, 0, False
    for ch in order:
        if quota_hit or len(st["searches"]) >= SEARCH_CAP:
            skipped += 1
            continue
        try:
            streams = api.search(ch)
        except ApiError as e:
            log("youtube: search failed (%s)" % e)
            quota_hit = e.reason in ("quotaExceeded", "dailyLimitExceeded", "rateLimitExceeded")
            st["searches"].append(now)
            continue
        st["searches"].append(now)
        st["channels"][ch] = {"searched": now}
        taken = {live[c["key"]]["id"] for c in cams if c["key"] in live and channel_of(c) == ch}
        cands = [x for x in streams if x[0] not in taken]
        on_ch = [c for c in cams if channel_of(c) == ch]
        for c in sorted(by_ch[ch], key=lambda c: not c.get("match")):
            got = pick(c, cands, sc.get(c["key"], {}).get("title"), sole=len(on_ch) == 1)
            if got:
                cands.remove(got)
                found[c["key"]] = got[0]
                sc[c["key"]] = {"list": c.get("video"), "id": got[0], "channel": ch, "title": got[1], "seen": now}
    if found:
        items = api.videos(sorted(set(found.values())))
        for c in need:
            it = items.get(found.get(c["key"]))
            if it and is_live(it):
                sc[c["key"]].update(title=it["snippet"].get("title"), seen=now, live=now)
                live[c["key"]] = it

    # two cameras on one stream (a camera without a label found its sibling's stream): keep the labelled one
    out, used = [], set()
    for c in sorted((c for c in cams if c["key"] in live), key=lambda c: not c.get("match")):
        vid = live[c["key"]]["id"]
        if vid not in used:
            used.add(vid)
            out.append((c, live[c["key"]]))
    gone = [c["name"] for c in cams if c["key"] not in live]
    log("youtube: %d cameras, %d live (%d found again by search); %d left out%s; %d searches this run, %d of %d "
        "in the last 24 h%s; %d quota units this run" % (
            len(cams), len(out), sum(1 for c, _ in out if c["key"] in found), len(gone),
            (" (" + "; ".join(gone[:8]) + ("; ..." if len(gone) > 8 else "") + ")") if gone else "",
            api.n_search, len(st["searches"]), SEARCH_CAP,
            (", %d channels waiting for the search cap" % skipped) if skipped else "", api.units))
    if no_ch:
        log("youtube: no channel known for %s" % "; ".join(c["name"] for c in no_ch))
    return out


def record(c, it):
    """One camera for webcams.js (it joins webcams.group like any other; `yt` marks it for the map)."""
    sn = it["snippet"]
    chan = sn.get("channelId")
    rec = {"id": "yt-" + c["key"], "name": c["name"], "lat": c["lat"], "lon": c["lon"], "img": thumb(it), "ts": None,
           "kind": c["kind"], "src": "YouTube", "owner": c.get("owner") or sn.get("channelTitle") or "",
           "link": c.get("page") or ("https://www.youtube.com/channel/" + chan if chan else ""),
           "yt": it["id"], "since": epoch(it.get("liveStreamingDetails", {}).get("actualStartTime"))}
    if c.get("stake"):
        rec["stake"] = True
    return rec


def cams(log=print, inside=None, get=None):
    """Live YouTube cameras in the region window, ready for webcams.js; [] without a key."""
    key = api_key()
    if not key:
        log("webcams: no YT_API_KEY, so no YouTube cameras this run")
        return []
    try:
        todo = [c for c in load_list() if not c.get("off") and (inside is None or inside(c["lat"], c["lon"]))]
    except (OSError, ValueError, KeyError) as e:
        log("youtube: camera list unreadable (%s)" % type(e).__name__)
        return []
    if not todo:
        return []
    st = load_state()
    api = Api(key, get)
    try:
        live = resolve(todo, api, st, log=log)
    except ApiError as e:
        log("youtube: videos.list failed (%s), so no YouTube cameras this run; %d quota units used" % (e, api.units))
        return []
    finally:
        save_state(st)
    return [record(c, it) for c, it in live if thumb(it)]


if __name__ == "__main__":
    lat0, lat1, lon0, lon1 = region.bbox()
    got = cams(inside=lambda la, lo: lat0 <= la <= lat1 and lon0 <= lo <= lon1)
    print("%d live YouTube cameras in %s" % (len(got), region.KEY))
