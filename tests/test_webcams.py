"""Road/fire classification, grouping by pole and road-camera thinning in webcams.py (no network)."""
import webcams


def cam(i, lat, lon, kind="road", name=None):
    return {"id": i, "name": name or "cam %s" % i, "lat": lat, "lon": lon, "img": "https://x/%s.jpg" % i,
            "ts": 0, "kind": kind, "src": "WSDOT"}


def test_road_is_decided_by_agency_not_name():
    assert webcams.is_road("CALTRANS") and webcams.is_road("udot") and webcams.is_road(" WSDOT ")
    assert not webcams.is_road("PG&E") and not webcams.is_road("HPWREN") and not webcams.is_road("FAA")


def test_stevens_east_and_west_share_one_marker_and_keep_both_views():
    # real positions from AlertWest, 2026-09-27: about 160 m apart
    west = cam(1, 47.74519, -121.09029, name="US 2 at MP 643 West Stevens Pass-Ski Lodge")
    east = cam(2, 47.74612, -121.08870, name="US 2 at MP 646 East Stevens Pass Summit")
    sites = webcams.thin(webcams.group([west, east]))
    assert len(sites) == 1
    assert [v["name"] for v in sites[0]["views"]] == [west["name"], east["name"]]


def test_different_kinds_are_not_grouped():
    sites = webcams.group([cam(1, 47.0, -121.0), cam(2, 47.0, -121.0, kind="ski")])
    assert len(sites) == 2


def test_rural_road_sites_keep_3_km_spacing():
    # Snoqualmie Pass area, well outside every metro circle; sites 2 km and 4 km from the first
    a, b, c = cam(1, 47.42, -121.41), cam(2, 47.42 + 2 / 111.2, -121.41), cam(3, 47.42 + 4 / 111.2, -121.41)
    kept = {s["id"] for s in webcams.thin(webcams.group([a, b, c]))}
    assert kept == {1, 3}


def test_urban_road_sites_keep_10_km_spacing():
    # I-5 through Seattle: a site every 2 miles for 12 km
    sites = [cam(i, 47.55 + i * 3.2 / 111.2, -122.32) for i in range(5)]
    kept = webcams.thin(webcams.group(sites))
    assert len(kept) == 2


def test_site_with_more_views_wins_the_spacing():
    lone = cam(1, 47.42, -121.41)
    pair = [cam(2, 47.43, -121.41), cam(3, 47.4302, -121.4101)]
    kept = webcams.thin(webcams.group([lone] + pair))
    assert [s["id"] for s in kept] == [2]


def test_other_kinds_are_never_thinned():
    skis = [cam(i, 47.0 + i * 0.5 / 111.2, -121.0, kind="ski") for i in range(4)]
    assert len(webcams.thin(webcams.group(skis))) == 4


class _Resp:
    def __init__(self, body, ctype="image/jpeg"):
        self.body, self.headers, self.status = body, {"Content-Type": ctype}, 200

    def read(self, n=-1):
        return self.body[:n]

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _urlopen_returning(result):
    def fake(req, timeout=None):
        if isinstance(result, Exception):
            raise result
        return result
    return fake


def test_check_image_keeps_cameras_the_runner_is_refused(monkeypatch):
    import urllib.error
    for err in (urllib.error.HTTPError("u", 403, "Forbidden", {}, None), TimeoutError()):
        monkeypatch.setattr(webcams.urllib.request, "urlopen", _urlopen_returning(err))
        assert webcams.check_image("https://x/a.jpg")[0] == "unreachable"


def test_check_image_drops_only_what_the_host_says_is_gone(monkeypatch):
    import urllib.error
    monkeypatch.setattr(webcams.urllib.request, "urlopen", _urlopen_returning(urllib.error.HTTPError("u", 404, "Not Found", {}, None)))
    assert webcams.check_image("https://x/a.jpg")[0] == "gone"
    monkeypatch.setattr(webcams.urllib.request, "urlopen", _urlopen_returning(_Resp(b"<html>", "text/html")))
    assert webcams.check_image("https://x/a.jpg")[0] == "gone"
    monkeypatch.setattr(webcams.urllib.request, "urlopen", _urlopen_returning(_Resp(b"\x89PNG\r\n\x1a\n", "image/png")))
    assert webcams.check_image("https://player.brownrice.com/snapshot/x")[0] == "gone"
    monkeypatch.setattr(webcams.urllib.request, "urlopen", _urlopen_returning(_Resp(b"\xff\xd8\xff\xe0")))
    assert webcams.check_image("https://x/a.jpg")[0] == "ok"


def test_only_a_brownrice_offline_card_drops_a_curated_camera():
    assert webcams.drops("gone", "offline card")
    for state, why in (("gone", "HTTP 404"), ("gone", "not an image"), ("unreachable", "HTTP 403"),
                       ("unreachable", "TimeoutError"), ("ok", "")):
        assert not webcams.drops(state, why)
