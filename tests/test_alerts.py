"""Alerts layer (alerts.py): marine area in the URL, window clipping of zone shapes (no network)."""
import json
import os

import alerts
import region

BBOX = (41.0, 49.7, -126.6, -112.5)          # the pnw window, rounded


def test_alert_url_adds_marine_area_for_coastal_regions():
    assert alerts.alert_url(["WA", "OR"], True).split("area=")[1].split("&")[0] == "WA,OR,PZ"
    assert "PZ" not in alerts.alert_url(["UT", "CO"], False)


def test_in_window_drops_a_polygon_wholly_outside():
    inside = {"type": "Polygon", "coordinates": [[[-124.5, 46.0], [-124.0, 46.0], [-124.0, 46.5], [-124.5, 46.0]]]}
    outside = {"type": "Polygon", "coordinates": [[[-123.0, 37.0], [-122.5, 37.0], [-122.5, 37.5], [-123.0, 37.0]]]}
    assert alerts.in_window(inside, BBOX) and not alerts.in_window(outside, BBOX)


def test_in_window_handles_multipolygon_and_straddling_shapes():
    # a PZ zone running down the coast: partly inside counts as inside
    straddle = {"type": "Polygon", "coordinates": [[[-125.0, 40.0], [-124.0, 40.0], [-124.0, 42.0], [-125.0, 42.0], [-125.0, 40.0]]]}
    multi = {"type": "MultiPolygon", "coordinates": [
        [[[-123.0, 37.0], [-122.5, 37.0], [-122.5, 37.5], [-123.0, 37.0]]],
        [[[-124.5, 46.0], [-124.0, 46.0], [-124.0, 46.5], [-124.5, 46.0]]]]}
    multi_out = {"type": "MultiPolygon", "coordinates": [
        [[[-123.0, 37.0], [-122.5, 37.0], [-122.5, 37.5], [-123.0, 37.0]]],
        [[[-120.0, 33.0], [-119.5, 33.0], [-119.5, 33.5], [-120.0, 33.0]]]]}
    assert alerts.in_window(straddle, BBOX)
    assert alerts.in_window(multi, BBOX)
    assert not alerts.in_window(multi_out, BBOX)


def _feature(zone_url, geometry=None):
    return {"type": "Feature", "geometry": geometry,
            "properties": {"id": zone_url, "event": "Small Craft Advisory", "headline": "h", "affectedZones": [zone_url]}}


def test_build_drops_shapes_outside_the_window_and_keeps_shapeless_features(tmp_path, monkeypatch):
    out = tmp_path / "alerts.js"
    zones = tmp_path / "zone_cache.json"
    inside = {"type": "Polygon", "coordinates": [[[-124.5, 46.0], [-124.0, 46.0], [-124.0, 46.5], [-124.5, 46.0]]]}
    outside = {"type": "Polygon", "coordinates": [[[-123.0, 37.0], [-122.5, 37.0], [-122.5, 37.5], [-123.0, 37.0]]]}
    zones.write_text(json.dumps({"https://z/in": inside, "https://z/out": outside, "https://z/none": None}), encoding="utf-8")
    payload = {"features": [_feature("https://z/in"), _feature("https://z/out"), _feature("https://z/none")]}
    monkeypatch.setattr(alerts, "OUT", str(out))
    monkeypatch.setattr(alerts, "ZONES", str(zones))
    monkeypatch.setattr(alerts, "DATA", str(tmp_path))
    monkeypatch.setattr(alerts, "fetch", lambda url, **kw: json.dumps(payload).encode())
    monkeypatch.setattr(region, "bbox", lambda: BBOX)
    assert alerts.build(log=lambda *a: None) == 3                    # the count is of active alerts, as before
    data = json.loads(out.read_text(encoding="utf-8").split("= ", 1)[1].rstrip(";\n"))
    assert [f["properties"]["id"] for f in data["features"]] == ["https://z/in"]
