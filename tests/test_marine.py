"""Marine forecasts (marine.py): NWS coastal-waters zones, period parsing, surf zone forecasts, output (no network)."""
import datetime as dt
import json
import os
import urllib.error

import pytest

import marine

FX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "coastal")
API = "https://api.weather.gov"
PZZ150 = API + "/zones/forecast/PZZ150"


def fx(name):
    with open(os.path.join(FX, name), "rb") as f:
        return f.read()


def serve(files, calls=None):
    """a stand-in for marine.fetch: known URLs answer from the fixtures, anything else is a 404"""
    def fetch(url):
        if calls is not None:
            calls.append(url)
        if url not in files:
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
        return files[url]
    return fetch


FILES = {
    marine.ZONES_URL: fx("nws_zones_coastal.json"),
    PZZ150: fx("nws_zone_PZZ150.json"),
    PZZ150 + "/forecast": fx("nws_zone_forecast_PZZ150.json"),
    API + "/products/types/SRF/locations/PQR": fx("nws_products_srf_PQR.json"),
    API + "/products/e0906b70-a983-40ea-8757-1fa7a09c5e05": fx("nws_product_srf.json"),
}


@pytest.fixture
def job(tmp_path, monkeypatch):
    monkeypatch.setattr(marine, "OUT", str(tmp_path / "marine.js"))
    monkeypatch.setattr(marine, "ZONES", str(tmp_path / "zone_cache.json"))
    monkeypatch.setattr(marine, "_down", False)
    monkeypatch.setitem(marine.region.cfg(), "coastal", True)
    monkeypatch.setitem(marine.region.cfg(), "marine_cwa", ["SEW", "PQR"])
    return tmp_path


def read_out(path):
    text = open(path, encoding="utf-8").read()
    assert text.startswith("window.MARINE = ") and text.rstrip().endswith(";")
    return json.loads(text[len("window.MARINE = "):].rstrip().rstrip(";"))


# ---------- period text ----------
@pytest.mark.parametrize("text,wind,seas", [
    ("W wind 15 to 25 kt. Seas 6 to 8 ft.", 25, 8),
    ("NW wind 10 kt becoming 20 kt in the afternoon. Seas 4 ft.", 20, 4),
    ("Variable winds less than 10 kt.", None, None),
    ("Light winds. Seas 2 ft or less.", None, 2),
    ("S wind 30 to 40 kt with gusts to 50 kt. Seas 12 to 15 ft.", 50, 15),
    # real PZZ150 period text (2026-10-13): the wave-detail heights are not "seas"
    ("SE wind 5 to 10 kt, rising to 10 to 15 kt late this morning and afternoon. Seas 4 to 6 ft. "
     "Wave Detail: S 4 ft at 5 seconds, W 4 ft at 14 seconds and SW 2 ft at 16 seconds. A chance of rain.", 15, 6),
    ("SE wind around 5 kt. Seas 4 to 6 ft. Wave Detail: W 5 ft at 11 seconds and SW 2 ft at 15 seconds.", 5, 6),
    ("W wind 10 to 15 kt. Seas 6 ft building to 9 ft in the afternoon.", 15, 9),
    ("Seas 3 to 5 ft with a west swell 8 ft at 13 seconds.", None, 5),
    # Columbia River Bar (PZZ210): an ebb current in kt is not wind, and its decimal is not "61 kt"
    ("Strong ebb current of 5.61 kt at 658 PM Tuesday. Seas 6 ft.", None, 6),
    ("", None, None),
    (None, None, None),
])
def test_period_parse_variants(text, wind, seas):
    assert marine.parse_period(text) == (wind, seas)


def test_bar_zone_general_seas_period():
    """bar forecasts put the seas in a period named 'General Seas' with no 'Seas' label in the text"""
    periods, issued = marine._periods({"properties": {"updated": "2026-10-13T13:20:00-07:00", "periods": [
        {"name": "In The Main Channel", "detailedForecast": ""},
        {"name": "General Seas", "detailedForecast": "4 to 5 ft building to 5 to 6 ft Wednesday evening."}]}})
    assert [(p["wind_kt_max"], p["seas_ft_max"]) for p in periods] == [(None, None), (None, 6)]
    assert issued == int(dt.datetime(2026, 10, 13, 20, 20, tzinfo=dt.timezone.utc).timestamp())


# ---------- zones ----------
def test_zones_filtered_by_cwa():
    listing = json.loads(fx("nws_zones_coastal.json"))
    sew = marine.zones_for(["SEW"], listing)
    assert [z["id"] for z in sew] == ["PZZ150", "PZZ153"]
    assert sew[0]["cwa"] == "SEW" and sew[0]["url"] == PZZ150
    assert sew[0]["name"].startswith("Coastal Waters From Cape Flattery")
    assert len(marine.zones_for(["SEW", "PQR"], listing)) == 4
    assert marine.zones_for(["MFR"], listing) == []
    assert marine.zones_for(["SEW"], fx("nws_zones_coastal.json").decode())[0]["id"] == "PZZ150"   # text accepted too


def test_zone_geometry_cached(job, monkeypatch):
    calls = []
    monkeypatch.setattr(marine, "fetch", serve(FILES, calls))
    marine.build(log=lambda *a: None)
    assert calls.count(PZZ150) == 1
    cache = json.load(open(job / "zone_cache.json", encoding="utf-8"))
    assert cache[PZZ150]["type"] == "Polygon"                      # keyed by the zone URL, like alerts.py
    calls.clear()
    marine.build(log=lambda *a: None)
    assert PZZ150 not in calls and PZZ150 + "/forecast" in calls   # geometry from the cache, forecast refetched


def test_zone_cache_is_shared_with_alerts_style_entries(job, monkeypatch):
    """an entry alerts.py left as None (a failed fetch) is retried, not trusted; other entries are kept"""
    with open(job / "zone_cache.json", "w", encoding="utf-8") as f:
        json.dump({PZZ150: None, API + "/zones/forecast/WAZ001": {"type": "Polygon", "coordinates": []}}, f)
    calls = []
    monkeypatch.setattr(marine, "fetch", serve(FILES, calls))
    marine.build(log=lambda *a: None)
    assert PZZ150 in calls
    cache = json.load(open(job / "zone_cache.json", encoding="utf-8"))
    assert API + "/zones/forecast/WAZ001" in cache and cache[PZZ150]["type"] == "Polygon"


# ---------- surf zone forecast ----------
def test_srf_latest_product():
    listing = json.loads(fx("nws_products_srf_PQR.json"))
    assert marine.latest_product(listing) == API + "/products/e0906b70-a983-40ea-8757-1fa7a09c5e05"
    assert marine.latest_product({"@graph": []}) is None                    # SEW issues none
    text, issued = marine.srf_text(fx("nws_product_srf.json"))
    assert "SURF ZONE FORECAST" in text and "LONG BEACH WASHINGTON" in text
    assert len(text) <= 2500
    assert issued == int(dt.datetime(2026, 10, 13, 13, 2, tzinfo=dt.timezone.utc).timestamp())


# ---------- build ----------
def test_output_shape(job, monkeypatch):
    log = []
    monkeypatch.setattr(marine, "fetch", serve(FILES))
    n = marine.build(log=log.append)
    out = read_out(job / "marine.js")
    assert set(out) == {"updated", "updated_t", "zones", "srf"}
    assert n == 1 and [z["id"] for z in out["zones"]] == ["PZZ150"]        # the other three have no geometry
    z = out["zones"][0]
    assert set(z) == {"id", "name", "cwa", "geometry", "periods", "issued", "link"}
    assert z["cwa"] == "SEW" and z["link"] == "https://forecast.weather.gov/shmrn.php?mz=pzz150"
    assert z["issued"] == int(dt.datetime(2026, 10, 13, 8, 22, tzinfo=dt.timezone.utc).timestamp())
    assert len(z["periods"]) == 6 and [p["name"] for p in z["periods"]][:2] == ["Today", "Tonight"]
    first = z["periods"][0]
    assert set(first) == {"name", "text", "wind_kt_max", "seas_ft_max"}
    assert first["wind_kt_max"] == 15 and first["seas_ft_max"] == 6 and first["text"].startswith("SE wind")
    x, y = z["geometry"]["coordinates"][0][0]
    assert round(x, 4) == x and round(y, 4) == y and -126 < x < -124 and 47 < y < 49
    assert set(out["srf"]) == {"PQR"}                                       # SEW: the listing 404s here -> none
    assert out["srf"]["PQR"]["issued"] == int(dt.datetime(2026, 10, 13, 13, 2, tzinfo=dt.timezone.utc).timestamp())
    assert "Surf Height" in out["srf"]["PQR"]["text"] and out["srf"]["PQR"]["link"].startswith("https://forecast.weather.gov/")
    assert log[-1] == "marine: 1 zones, 1 surf-zone forecasts, 3 failed"   # three zones without fixtures; SEW SRF 404 = none, not a failure


def test_not_coastal_region_does_not_fetch(job, monkeypatch):
    monkeypatch.setitem(marine.region.cfg(), "coastal", False)
    monkeypatch.setattr(marine, "fetch", serve({}, None))
    assert marine.build(log=lambda *a: None) == 0
    assert not os.path.exists(job / "marine.js")


def test_cwa_list_falls_back_to_the_four_offices(monkeypatch):
    monkeypatch.delitem(marine.region.cfg(), "marine_cwa", raising=False)
    assert marine.cwas() == ["SEW", "PQR", "MFR", "EKA"]
    monkeypatch.setitem(marine.region.cfg(), "marine_cwa", ["SEW"])
    assert marine.cwas() == ["SEW"]


def test_a_hung_host_is_skipped_for_the_rest_of_the_job(monkeypatch):
    monkeypatch.setattr(marine, "_down", False)
    calls = []

    def hang(url, timeout=30, tries=2):
        calls.append(url)
        raise urllib.error.URLError(TimeoutError("timed out"))

    monkeypatch.setattr(marine.alerts, "fetch", hang)
    with pytest.raises(marine.HostDown):
        marine.fetch(PZZ150)
    with pytest.raises(marine.HostDown):
        marine.fetch(PZZ150 + "/forecast")
    assert calls == [PZZ150]                                                 # the second call never waited


def test_an_http_error_does_not_mark_the_host_down(monkeypatch):
    monkeypatch.setattr(marine, "_down", False)

    def missing(url, timeout=30, tries=2):
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)

    monkeypatch.setattr(marine.alerts, "fetch", missing)
    with pytest.raises(urllib.error.HTTPError):
        marine.fetch(PZZ150)
    assert marine._down is False
