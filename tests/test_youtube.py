"""YouTube-live webcams (youtube.py) with recorded-style Data API answers; the network stays blocked (conftest)."""
import html
import json
import urllib.parse

import pytest

import webcams
import youtube

KEY = "test-key-not-real"
NOW = 1_790_000_000
MR = "UCmissionridge000000000"


def video(vid, live=True, channel=MR, title="Midway Webcam", start="2026-05-18T18:20:22Z", end=None, maxres=True):
    th = {"default": {"url": "https://i.ytimg.com/vi/%s/default_live.jpg" % vid},
          "high": {"url": "https://i.ytimg.com/vi/%s/hqdefault_live.jpg" % vid},
          "standard": {"url": "https://i.ytimg.com/vi/%s/sddefault_live.jpg" % vid}}
    if maxres:
        th["maxres"] = {"url": "https://i.ytimg.com/vi/%s/maxresdefault_live.jpg" % vid}
    lsd = {"actualStartTime": start}
    if end:
        lsd["actualEndTime"] = end
    return {"id": vid, "snippet": {"channelId": channel, "channelTitle": "Mission Ridge (Ski Area)", "title": title,
                                   "liveBroadcastContent": "live" if live else "none", "thumbnails": th},
            "liveStreamingDetails": lsd}


class FakeYouTube:
    """Answers videos.list and search.list like the Data API does (search titles HTML-escaped)."""

    def __init__(self, videos, live_on=None):
        self.videos = {v["id"]: v for v in videos}
        self.live_on = live_on or {}          # channel -> [ids live now]
        self.urls = []

    def __call__(self, url, key):
        assert key == KEY
        self.urls.append(url)
        u = urllib.parse.urlparse(url)
        q = urllib.parse.parse_qs(u.query)
        if u.path.endswith("/videos"):
            return {"items": [self.videos[i] for i in q["id"][0].split(",") if i in self.videos]}
        if u.path.endswith("/search"):
            assert q["eventType"] == ["live"] and q["type"] == ["video"]
            return {"items": [{"id": {"kind": "youtube#video", "videoId": i},
                               "snippet": {"title": html.escape(self.videos[i]["snippet"]["title"], quote=True)}}
                              for i in self.live_on.get(q["channelId"][0], [])]}
        raise AssertionError("unexpected URL " + url)

    def searches(self):
        return [u for u in self.urls if "/search?" in u]


def cam(key="mission-ridge-midway", video_id="AlJPPPl1yIw", match="Midway", channel=None, site="mission-ridge", **kw):
    c = {"key": key, "name": "Mission Ridge - " + key.split("-")[-1].title(), "kind": "ski", "lat": 47.286,
         "lon": -120.4092, "video": video_id, "channel": channel, "match": match, "site": site,
         "owner": "Mission Ridge", "page": "https://www.missionridge.com/mountain-report/#webcam"}
    c.update(kw)
    return c


@pytest.fixture
def files(tmp_path, monkeypatch):
    """A camera list and a state file in tmp; the key from the environment."""
    monkeypatch.setattr(youtube, "LIST", str(tmp_path / "webcams_youtube.json"))
    monkeypatch.setattr(youtube, "STATE", str(tmp_path / "data" / "youtube_cache.json"))
    monkeypatch.setattr(youtube, "ENV", str(tmp_path / "youtube.env"))
    monkeypatch.setenv("YT_API_KEY", KEY)

    def write(cams):
        with open(youtube.LIST, "w", encoding="utf-8") as f:
            json.dump({"cams": cams}, f)
    return write


def run(cams, fake, st=None, now=NOW):
    st = st if st is not None else youtube.load_state("/nonexistent")
    logs = []
    out = youtube.resolve(cams, youtube.Api(KEY, fake), st, now=now, log=logs.append)
    return out, st, logs


# ------------------------------------------------------------------ no key
def test_no_key_means_no_youtube_cameras_and_no_network(files, monkeypatch):
    files([cam()])
    monkeypatch.delenv("YT_API_KEY")
    logs = []
    assert youtube.cams(log=logs.append) == []      # conftest makes any HTTP request raise
    assert logs == ["webcams: no YT_API_KEY, so no YouTube cameras this run"]


def test_key_comes_from_youtube_env_when_the_variable_is_missing(files, monkeypatch):
    monkeypatch.delenv("YT_API_KEY")
    with open(youtube.ENV, "w", encoding="utf-8-sig") as f:
        f.write("YT_API_KEY=abc123\n")
    assert youtube.api_key() == "abc123"


# ------------------------------------------------------------------ live
def test_live_video_shows_the_api_thumbnail_with_youtube_fields(files):
    files([cam()])
    fake = FakeYouTube([video("AlJPPPl1yIw")])
    got = youtube.cams(log=lambda m: None, get=fake)
    assert len(got) == 1
    r = got[0]
    assert r["img"] == "https://i.ytimg.com/vi/AlJPPPl1yIw/maxresdefault_live.jpg"
    assert r["yt"] == "AlJPPPl1yIw" and r["src"] == "YouTube" and r["ts"] is None
    assert r["since"] == 1779128422                      # 2026-05-18T18:20:22Z
    assert r["owner"] == "Mission Ridge" and r["link"].startswith("https://www.missionridge.com/")
    assert fake.searches() == []                          # a live video costs one videos.list, no search
    # the job learnt the channel from the API on first contact
    st = youtube.load_state()
    assert st["cams"]["mission-ridge-midway"]["channel"] == MR


def test_thumbnail_falls_back_to_standard_then_high():
    assert youtube.thumb(video("a", maxres=False)).endswith("/sddefault_live.jpg")
    v = video("a", maxres=False)
    del v["snippet"]["thumbnails"]["standard"]
    assert youtube.thumb(v).endswith("/hqdefault_live.jpg")


def test_owner_and_link_fall_back_to_the_channel():
    c = cam(owner="", page="")
    r = youtube.record(c, video("AlJPPPl1yIw"))
    assert r["owner"] == "Mission Ridge (Ski Area)" and r["link"] == "https://www.youtube.com/channel/" + MR


def test_youtube_views_keep_their_video_ids_when_grouped():
    a = youtube.record(cam(), video("AlJPPPl1yIw"))
    b = youtube.record(cam("mission-ridge-mimi", "TERghSgEi_o", "Mimi"), video("TERghSgEi_o", title="Mimi Webcam"))
    sites = webcams.group([a, b])
    assert len(sites) == 1
    assert [(v["yt"], v["since"]) for v in sites[0]["views"]] == [(a["yt"], a["since"]), (b["yt"], b["since"])]


# ------------------------------------------------------------------ ended stream -> search by title
def test_ended_video_is_found_again_by_title_and_saved(files):
    files([cam()])
    fake = FakeYouTube([video("AlJPPPl1yIw", live=False, end="2026-09-27T10:00:00Z"),
                        video("NEWmidway01", title="Midway Webcam"), video("NEWsunspot1", title="Sunspot Webcam")],
                       live_on={MR: ["NEWsunspot1", "NEWmidway01"]})
    got = youtube.cams(log=lambda m: None, get=fake)
    assert [r["yt"] for r in got] == ["NEWmidway01"]
    assert got[0]["img"] == "https://i.ytimg.com/vi/NEWmidway01/maxresdefault_live.jpg"
    assert len(fake.searches()) == 1 and "channelId=" + MR in fake.searches()[0]
    st = youtube.load_state()
    assert st["cams"]["mission-ridge-midway"]["id"] == "NEWmidway01"
    # next run starts from the saved id: one videos.list, no search
    fake.urls.clear()
    got = youtube.cams(log=lambda m: None, get=fake)
    assert [r["yt"] for r in got] == ["NEWmidway01"] and fake.searches() == []


def test_a_camera_without_an_id_uses_its_sites_channel(files):
    files([cam(), cam("mission-ridge-mimi", None, "Mimi")])
    fake = FakeYouTube([video("AlJPPPl1yIw"), video("MIMIlive001", title="Mimi Webcam")],
                       live_on={MR: ["AlJPPPl1yIw", "MIMIlive001"]})
    got = youtube.cams(log=lambda m: None, get=fake)
    assert sorted(r["yt"] for r in got) == ["AlJPPPl1yIw", "MIMIlive001"]


def test_search_titles_are_unescaped_before_matching(files):
    files([cam(match="Everett's")])
    fake = FakeYouTube([video("AlJPPPl1yIw", live=False), video("EVERETT0001", title="Everett's 8800 Cam")],
                       live_on={MR: ["EVERETT0001"]})
    assert [r["yt"] for r in youtube.cams(log=lambda m: None, get=fake)] == ["EVERETT0001"]


def test_no_matching_replacement_leaves_the_camera_out_and_waits_a_day(files):
    files([cam()])
    fake = FakeYouTube([video("AlJPPPl1yIw", live=False), video("OTHER000001", title="Sunspot Webcam")],
                       live_on={MR: ["OTHER000001"]})
    logs = []
    assert youtube.cams(log=logs.append, get=fake) == []
    assert any("left out (Mission Ridge - Midway)" in m for m in logs)
    assert len(fake.searches()) == 1
    # an hour later the channel is not searched again (it was searched after the camera was last live)
    fake.urls.clear()
    assert youtube.cams(log=lambda m: None, get=fake) == [] and fake.searches() == []


def test_a_restart_after_the_last_search_is_searched_at_once():
    c = cam()
    st = youtube.load_state("/nonexistent")
    st["channels"][MR] = {"searched": NOW - 3600}
    st["cams"][c["key"]] = {"list": c["video"], "id": c["video"], "channel": MR, "seen": NOW - 600, "live": NOW - 600}
    fake = FakeYouTube([video("AlJPPPl1yIw", live=False), video("NEWmidway01")], live_on={MR: ["NEWmidway01"]})
    out, st, _ = run([c], fake, st)
    assert [it["id"] for _, it in out] == ["NEWmidway01"] and len(fake.searches()) == 1


# ------------------------------------------------------------------ quota
def test_search_cap_stops_further_searches():
    cams = [cam("a-%d" % i, "VID%08d" % i, None, channel="UCchan%03d" % i, site="s%d" % i)
            for i in range(youtube.SEARCH_CAP + 3)]
    fake = FakeYouTube([video("VID%08d" % i, live=False, channel="UCchan%03d" % i) for i in range(len(cams))])
    out, st, logs = run(cams, fake)
    assert out == [] and len(fake.searches()) == youtube.SEARCH_CAP
    assert len(st["searches"]) == youtube.SEARCH_CAP and "3 channels waiting for the search cap" in logs[0]
    # later the same day: the cap counts searches over the last 24 h, so none are left
    fake.urls.clear()
    run(cams, fake, st, now=NOW + 3 * 3600)
    assert fake.searches() == []
    # a day after the first searches the cap frees up again
    fake.urls.clear()
    run(cams, fake, st, now=NOW + 86400 + 60)
    assert len(fake.searches()) == youtube.SEARCH_CAP


def test_quota_exceeded_stops_searching_for_the_run():
    cams = [cam("a-%d" % i, "VID%08d" % i, None, channel="UCchan%03d" % i, site="s%d" % i) for i in range(3)]
    fake = FakeYouTube([video("VID%08d" % i, live=False, channel="UCchan%03d" % i) for i in range(3)])

    def get(url, key):
        if "/search?" in url:
            fake.urls.append(url)
            raise youtube.ApiError(403, "quotaExceeded")
        return fake(url, key)
    out, st, logs = run(cams, get)
    assert out == [] and len(fake.searches()) == 1
    assert any("quotaExceeded" in m for m in logs)


def test_units_are_counted_per_call():
    api = youtube.Api(KEY, FakeYouTube([video("VID%08d" % i) for i in range(60)], live_on={MR: []}))
    api.videos(["VID%08d" % i for i in range(60)])
    api.search(MR)
    assert (api.n_videos, api.n_search, api.units) == (2, 1, 102)


# ------------------------------------------------------------------ what the job may fetch
class _Resp:
    def __init__(self, body):
        self.body = body

    def read(self, n=-1):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_the_job_only_ever_calls_the_data_api(files, monkeypatch, tmp_path):
    """Through the real transport: every request goes to www.googleapis.com/youtube/v3 with the key in a header,
    never to i.ytimg.com or youtube.com, and webcams.build never checks a YouTube thumbnail."""
    files([cam(), cam("mission-ridge-mimi", "TERghSgEi_o", "Mimi")])
    fake = FakeYouTube([video("AlJPPPl1yIw"), video("TERghSgEi_o", live=False), video("NEWmimi0001", title="Mimi Webcam")],
                       live_on={MR: ["AlJPPPl1yIw", "NEWmimi0001"]})
    seen = []

    def urlopen(req, timeout=None):
        seen.append((req.full_url, dict(req.header_items())))
        if not req.full_url.startswith("https://www.googleapis.com/youtube/v3/"):
            raise AssertionError("fetched " + req.full_url)
        return _Resp(json.dumps(fake(req.full_url, KEY)).encode())
    monkeypatch.setattr(youtube.urllib.request, "urlopen", urlopen)
    for name in ("alertwest", "usgs_hivis", "usgs_volcano", "ndbc"):
        monkeypatch.setattr(webcams, name, lambda: [])
    checked = []
    monkeypatch.setattr(webcams, "check_image", lambda url: checked.append(url) or ("ok", None, ""))
    monkeypatch.setattr(webcams, "EXTRA", str(tmp_path / "extra.json"))
    with open(webcams.EXTRA, "w", encoding="utf-8") as f:
        json.dump({"cams": []}, f)
    monkeypatch.setattr(webcams, "DATA", str(tmp_path / "data"))
    monkeypatch.setattr(webcams, "OUT", str(tmp_path / "data" / "webcams.js"))
    monkeypatch.setattr(webcams, "inside", lambda lat, lon: True)

    webcams.build(log=lambda m: None)

    assert seen and checked == []
    for url, headers in seen:
        assert url.startswith("https://www.googleapis.com/youtube/v3/")
        assert "ytimg" not in url and "youtube.com" not in url and KEY not in url
        assert headers.get("X-goog-api-key") == KEY and "@" not in headers.get("User-agent", "")
    with open(webcams.OUT, encoding="utf-8") as f:
        data = json.loads(f.read().split("=", 1)[1].strip().rstrip(";"))
    assert data["cams"] == []
    assert len(data["yt"]) == 1 and sorted(v["yt"] for v in data["yt"][0]["views"]) == ["AlJPPPl1yIw", "NEWmimi0001"]


# ------------------------------------------------------------------ matching and state hygiene
def test_pick_needs_one_clear_match():
    c = {"match": "Base"}
    two = [("a", "Bear Base Cam"), ("b", "Snow Valley's Base Area")]
    assert youtube.pick(c, two, None, sole=False) is None                      # ambiguous: leave it out
    assert youtube.pick(c, two, "Bear Base Cam", sole=False) == ("a", "Bear Base Cam")
    assert youtube.pick({"match": None}, [("x", "Anything")], None, sole=True) == ("x", "Anything")
    assert youtube.pick({"match": None}, [("x", "A"), ("y", "B")], None, sole=True) is None
    assert youtube.pick({"match": None}, [("x", "A"), ("y", "B")], "B", sole=False) == ("y", "B")


def test_api_data_older_than_30_days_is_dropped():
    st = {"cams": {"old": {"id": "x", "seen": NOW - 31 * 86400}, "new": {"id": "y", "seen": NOW - 86400}},
          "channels": {"UCold": {"searched": NOW - 31 * 86400}}, "searches": [NOW - 2 * 86400, NOW - 60]}
    youtube.prune(st, NOW)
    assert list(st["cams"]) == ["new"] and st["channels"] == {} and st["searches"] == [NOW - 60]


def test_editing_a_cameras_id_by_hand_overrides_the_saved_one():
    c = cam(video_id="HANDEDIT001")
    st = youtube.load_state("/nonexistent")
    st["cams"][c["key"]] = {"list": "AlJPPPl1yIw", "id": "OLDSAVED001", "channel": MR, "seen": NOW - 60}
    fake = FakeYouTube([video("HANDEDIT001"), video("OLDSAVED001")])
    out, st, _ = run([c], fake, st)
    assert [it["id"] for _, it in out] == ["HANDEDIT001"]


def test_two_cameras_on_one_stream_keep_the_labelled_one():
    a = cam("site-live", None, None, channel=MR, site="x")
    b = cam("site-tram", None, "Tram", channel=MR, site="x")
    fake = FakeYouTube([video("TRAM0000001", title="Lone Peak Tram Cam")], live_on={MR: ["TRAM0000001"]})
    out, _, _ = run([a, b], fake)
    assert [c["key"] for c, _ in out] == ["site-tram"]
