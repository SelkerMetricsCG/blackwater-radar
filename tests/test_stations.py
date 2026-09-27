"""HADS parsing in stations.py (no network: fetch and the metadata cache are replaced)."""
import datetime as dt
import time

import stations


def test_a_gauge_with_only_blank_values_does_not_drop_the_rest(monkeypatch):
    # 2026-09-27: Colorado gauge VCRC2 sent 181 PC lines with an empty value; the one gauge took down
    # every HADS station in the utco, sierra and imw regions (IndexError on an empty series)
    now = dt.datetime.now().replace(second=0, microsecond=0)
    utc = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None, second=0, microsecond=0)
    lines = []
    for h in range(25, -1, -1):
        ts = (utc - dt.timedelta(hours=h)).strftime("%Y-%m-%d %H:%M")
        lines.append("1900A51C|VCRC2|PC|%s||  |" % ts)
        lines.append("DD0012AB|GOOD1|PC|%s|%.2f|  |" % (ts, 10.0 + 0.01 * (25 - h)))
    meta = {"VCRC2": {"lat": 39.0, "lon": -106.0, "owner": "X"}, "GOOD1": {"lat": 39.1, "lon": -106.1, "owner": "X"}}
    monkeypatch.setattr(stations, "_cache", lambda: {"_t": time.time(), "hads_meta": meta})
    monkeypatch.setattr(stations, "HADS_STATES", ["CO"])
    monkeypatch.setattr(stations, "fetch", lambda *a, **k: "\n".join(lines).encode())
    out = stations.hads(now, lambda *a: None)
    assert [r["id"] for r in out] == ["GOOD1"]
