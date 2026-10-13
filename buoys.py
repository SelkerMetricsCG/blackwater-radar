"""
Buoys and shore stations (the map's Coastal > "Buoys & shore stations" layer).
Every half-hour run, for a region with "coastal" set:
  data/buoys.js   window.BUOYS = {updated, updated_t, stations: [...]}   (shape: spec §3)
Sources, all free and keyless (spec §5; coastal_research/waves_buoys.md, nanoos_ioos.md):
  NDBC latest_obs.txt (every station, newest row) + realtime2/<id>.txt (history, waves; the 3 m buoys show MM waves in
  latest_obs) + realtime2/<id>.spec (swell / wind-wave split); CDIP's ERDDAP for its six Waveriders (overwrites the
  NDBC relay rows); ECCC Datamart SWOB-ML for the Canadian buoys (NDBC's relay shows a wrong period and no direction);
  NANOOS ERDDAP (Cha'ba, Se'lhaem, ORCA, PISCES) and Backyard Buoys ERDDAP (Spotters); NOAA CO-OPS wind and water
  temperature at the tide gauges that have those sensors (station list from tides.py's cache, else CO-OPS metadata).
Units: ft, mph, °F, mb; times epoch seconds. A station is kept when it has waves, wind or water temperature; past
STALE_H it is marked stale, past DROP_H it is dropped.
Design: docs/superpowers/specs/2026-10-13-coastal-section-design.md.
Run standalone (writes local files, uploads nothing):  python buoys.py
"""
import calendar
import csv
import datetime as dt
import io
import json
import math
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

import region

DATA = region.data_dir()
OUT = os.path.join(DATA, "buoys.js")
UA = "RadarTracker/1.0 (personal weather map)"
TIMEOUT = 20
TRIES = 2

STALE_H = 6                 # hollow dot after this many hours without a report (decision 1)
DROP_H = 24                 # dropped after this many
RELAY_SLACK_S = 3600        # a partner row (CDIP, ECCC, CO-OPS, NANOOS) older than the relay row by more than this
                            # only fills gaps instead of overwriting
TRACE_H = 24

STATION_TABLE = "https://www.ndbc.noaa.gov/data/stations/station_table.txt"
LATEST_OBS = "https://www.ndbc.noaa.gov/data/latest_obs/latest_obs.txt"
REALTIME = "https://www.ndbc.noaa.gov/data/realtime2/{id}.{ext}"
REALTIME_RANGE = {"txt": "bytes=0-19999", "spec": "bytes=0-1999"}   # files are newest first: ~30 h of 10-min rows
NDBC_PAGE = "https://www.ndbc.noaa.gov/station_page.php?station={id}"

CDIP_RELAY = {"036": "46211", "162": "46243", "179": "46248", "248": "46267", "270": "46278", "139": "46229"}
CDIP_URL = ("https://erddap.cdip.ucsd.edu/erddap/tabledap/wave_agg.csv?station_id,time,latitude,longitude,"
            "waveHs,waveTp,waveDp,waveTa&time%3E=now-6hours&waveFlagPrimary=1&station_id=~%22("
            + "%7C".join(sorted(CDIP_RELAY)) + ")%22&orderByMax(%22station_id,time%22)")
CDIP_PAGE = "https://cdip.ucsd.edu/m/products/?stn={id}p1"

ECCC_IDS = {"4600206": "46206", "4600146": "46146", "4600304": "46304",
            "4600131": "46131"}    # Sentry Shoal: inside region.bbox() (north edge 52.5 N), not in the plan's list
ECCC_DIR = "https://dd.weather.gc.ca/today/observations/swob-ml/marine/moored-buoys/{day}/{wmo}/"
ECCC_DIR_DATED = "https://dd.weather.gc.ca/{day}/WXO-DD/observations/swob-ml/marine/moored-buoys/{day}/{wmo}/"

COOPS_META = "https://api.tidesandcurrents.noaa.gov/mdapi/prod/webapi/stations.json?type=waterlevels&expand=sensors"
COOPS_DATA = ("https://api.tidesandcurrents.noaa.gov/api/prod/datagetter?product={product}&station={id}"
              "&date=latest&units=english&time_zone=gmt&format=json")
COOPS_PAGE = "https://tidesandcurrents.noaa.gov/stationhome.html?id={id}"
COOPS_SLEEP_S = 0.2

CREDIT_CDIP = "Data courtesy of CDIP"
CREDIT_ECCC = "Data Source: Environment and Climate Change Canada"
CREDIT_BYB = "Quileute Tribe / Quinault Indian Nation (Backyard Buoys, CC BY-NC 4.0)"
CREDIT_NANOOS = "NANOOS / UW Applied Physics Laboratory"

OWNERS = {"N": "NOAA NDBC", "O": "NOAA CO-OPS", "PT": "NOAA CO-OPS (PORTS)", "C": "Environment and Climate Change Canada",
          "R": "Scripps CDIP", "NA": "NANOOS", "OO": "Ocean Observatories Initiative", "NR": "NOAA NERRS"}

M_FT, MS_MPH, KT_MPH, KMH_MPH = 3.28084, 2.23694, 1.15078, 0.621371
WAVE_KEYS = ("hs_ft", "dpd_s", "apd_s", "mwd_deg")
MET_KEYS = ("wspd_mph", "gust_mph", "wdir_deg", "wtmp_f", "atmp_f", "pres_mb")
SPLIT_KEYS = ("swh_ft", "swp_s", "swd_deg", "wwh_ft", "wwp_s", "wwd_deg", "steep")
COMPASS = ("N NNE NE ENE E ESE SE SSE S SSW SW WSW W WNW NW NNW").split()


# ---- units -------------------------------------------------------------------------------------------------------

def _r1(v):
    return None if v is None else round(v, 1)


def _deg(v):
    return None if v is None else int(math.floor(v + 0.5)) % 360


def m_ft(v):
    return None if v is None else round(v * M_FT, 1)


def ms_mph(v):
    return None if v is None else round(v * MS_MPH, 1)


def kt_mph(v):
    return None if v is None else round(v * KT_MPH, 1)


def kmh_mph(v):
    return None if v is None else round(v * KMH_MPH, 1)


def c_f(v):
    return None if v is None else round(v * 9 / 5 + 32, 1)


def _num(s):
    if s is None:
        return None
    try:
        v = float(s)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(v) else v


def _compass(s):
    s = (s or "").strip().upper()
    return _deg(COMPASS.index(s) * 22.5) if s in COMPASS else None


def _iso(s):
    """'2026-10-13T20:00:00Z' or '2026-10-13T20:05:00.000Z' -> epoch s"""
    s = s.strip().rstrip("Z").split(".")[0]
    return calendar.timegm(time.strptime(s, "%Y-%m-%dT%H:%M:%S"))


def _in(lat, lon, bbox):
    lat0, lat1, lon0, lon1 = bbox
    return lat0 <= lat <= lat1 and lon0 <= lon <= lon1


# ---- NDBC --------------------------------------------------------------------------------------------------------

def _ndbc_row(names, parts):
    """one whitespace-split NDBC row -> record in the site's units (columns found by header name)"""
    col = dict(zip(names, parts))
    g = lambda k: _num(col.get(k)) if col.get(k) not in (None, "MM") else None   # noqa: E731
    yy = int(col.get("YYYY") or col.get("YY"))
    t = calendar.timegm((yy, int(col["MM"]), int(col["DD"]), int(col["hh"]), int(col["mm"]), 0))
    return {"t": t, "hs_ft": m_ft(g("WVHT")), "dpd_s": _r1(g("DPD")), "apd_s": _r1(g("APD")), "mwd_deg": _deg(g("MWD")),
            "wspd_mph": ms_mph(g("WSPD")), "gust_mph": ms_mph(g("GST")), "wdir_deg": _deg(g("WDIR")),
            "wtmp_f": c_f(g("WTMP")), "atmp_f": c_f(g("ATMP")), "pres_mb": _r1(g("PRES"))}


def _header(line):
    names = line.lstrip("#").split()
    return names


def parse_latest_obs(text, bbox):
    """latest_obs.txt -> {ID: record with id, lat, lon, t and the fields}, window-filtered"""
    lines = text.splitlines()
    names = _header(lines[0])
    out = {}
    for line in lines[1:]:
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) != len(names):
            continue
        try:
            lat, lon = float(parts[1]), float(parts[2])
            if not _in(lat, lon, bbox):
                continue
            rec = _ndbc_row(names, parts)
        except (ValueError, KeyError):
            continue
        sid = parts[0].upper()
        rec.update(id=sid, lat=lat, lon=lon)
        out[sid] = rec
    return out


def _complete_lines(text):
    """a ranged download can end mid-row: drop the partial last line"""
    return text if text.endswith("\n") else text[:text.rfind("\n") + 1]


def parse_realtime(text, hours=26):
    """realtime2/<ID>.txt -> rows newest first (keys t + WAVE_KEYS + MET_KEYS), the newest `hours` only"""
    lines = _complete_lines(text).splitlines()
    if not lines:
        return []
    names = _header(lines[0])
    rows = []
    for line in lines[1:]:
        if line.startswith("#") or not line.strip():
            continue
        parts = line.split()
        if len(parts) != len(names):
            continue
        try:
            row = _ndbc_row(names, parts)
        except (ValueError, KeyError):
            continue
        if rows and row["t"] < rows[0]["t"] - hours * 3600:
            break
        rows.append(row)
    rows.sort(key=lambda r: -r["t"])
    return rows


def parse_spec(text):
    """realtime2/<ID>.spec -> newest row: t, swh_ft, swp_s, swd_deg, wwh_ft, wwp_s, wwd_deg, steep ({} if none)"""
    lines = _complete_lines(text).splitlines()
    if not lines:
        return {}
    names = _header(lines[0])
    for line in lines[1:]:
        if line.startswith("#") or not line.strip():
            continue
        parts = line.split()
        if len(parts) != len(names):
            continue
        col = dict(zip(names, parts))
        g = lambda k: _num(col.get(k)) if col.get(k) != "MM" else None   # noqa: E731
        steep = col.get("STEEPNESS")
        try:
            t = calendar.timegm((int(col["YY"]), int(col["MM"]), int(col["DD"]), int(col["hh"]), int(col["mm"]), 0))
        except (KeyError, ValueError):
            continue
        return {"t": t, "swh_ft": m_ft(g("SwH")), "swp_s": _r1(g("SwP")), "swd_deg": _compass(col.get("SwD")),
                "wwh_ft": m_ft(g("WWH")), "wwp_s": _r1(g("WWP")), "wwd_deg": _compass(col.get("WWD")),
                "steep": steep if steep and steep not in ("MM", "N/A") else None}
    return {}


def hourly_trace(rows):
    """rows newest first -> (24 hourly hs_ft values ending at the hour of the newest wave row, epoch of slot 0)"""
    waves = [r for r in rows if r.get("hs_ft") is not None]
    if not waves:
        return None, None
    end = waves[0]["t"] // 3600 * 3600
    t0 = end - (TRACE_H - 1) * 3600
    trace = [None] * TRACE_H
    for r in waves:                                  # newest first: the first row seen in an hour wins
        i = (r["t"] // 3600 * 3600 - t0) // 3600
        if 0 <= i < TRACE_H and trace[i] is None:
            trace[i] = r["hs_ft"]
    return trace, t0


def parse_station_table(text):
    """station_table.txt -> {ID: {owner, name, coops}}; coops is the CO-OPS id for NOS gauges ('9441102 - Westport')"""
    out = {}
    for line in text.splitlines():
        if line.startswith("#") or "|" not in line:
            continue
        f = [x.strip() for x in line.split("|")]
        if len(f) < 5:
            continue
        sid, owner, raw = f[0].upper(), f[1], f[4]
        m = re.match(r"^(\d{7})\s*-\s*(.+)$", raw)
        out[sid] = {"owner": owner, "name": clean_name(raw), "coops": m.group(1) if m else None}
    return out


def clean_name(raw):
    """'CAPE ELIZABETH - 45NM NW of Aberdeen, WA' -> 'Cape Elizabeth'; '9441102 - Westport, WA' -> 'Westport, WA';
    'Grays Harbor, WA (036)' -> 'Grays Harbor, WA'"""
    s = re.sub(r"\s*\([^)]*\)", "", raw.replace("&#176;", "")).strip()
    parts = [p.strip() for p in s.split(" - ")]
    s = parts[1] if re.fullmatch(r"\d{7}", parts[0]) and len(parts) > 1 else parts[0]
    if s.upper() == s:
        s = " ".join(w.capitalize() for w in s.split())
        s = re.sub(r", ([A-Za-z]{2})$", lambda m: ", " + m.group(1).upper(), s)
    return s


# ---- partners ----------------------------------------------------------------------------------------------------

def parse_cdip(csv_text):
    """CDIP ERDDAP wave_agg CSV -> {cdip_id: {t, hs_ft, dpd_s, mwd_deg, apd_s[, lat, lon]}} (newest row per station)"""
    rows = list(csv.reader(io.StringIO(csv_text)))
    if len(rows) < 3:
        return {}
    names = rows[0]
    out = {}
    for parts in rows[2:]:                           # row 1 is the units row
        col = dict(zip(names, parts))
        sid = (col.get("station_id") or "").strip()
        try:
            t = _iso(col["time"])
        except (KeyError, ValueError):
            continue
        if not sid or (sid in out and out[sid]["t"] >= t):
            continue
        rec = {"t": t, "hs_ft": m_ft(_num(col.get("waveHs"))), "dpd_s": _r1(_num(col.get("waveTp"))),
               "mwd_deg": _deg(_num(col.get("waveDp"))), "apd_s": _r1(_num(col.get("waveTa")))}
        lat, lon = _num(col.get("latitude")), _num(col.get("longitude"))
        if lat is not None and lon is not None:
            rec.update(lat=round(lat, 4), lon=round(lon, 4))
        out[sid] = rec
    return out


def parse_swob(xml_text):
    """ECCC SWOB-ML moored-buoy XML -> record (peak period and peak direction, which NDBC's relay lacks)"""
    root = ET.fromstring(xml_text.encode("utf-8") if isinstance(xml_text, str) else xml_text)
    v = {}
    for el in root.iter():
        if el.tag.rsplit("}", 1)[-1] == "element" and el.get("name") and el.get("name") not in v:
            v[el.get("name")] = el.get("value")
    n = lambda k: _num(v.get(k)) if v.get(k) not in (None, "MSNG") else None   # noqa: E731
    lat = n("crnt_buoy_lat") if n("crnt_buoy_lat") is not None else n("lat")
    lon = n("crnt_buoy_long") if n("crnt_buoy_long") is not None else n("long")
    hs = n("avg_sig_wave_hgt_pst20mts")
    if hs is None:
        hs = n("spetrl_sig_wave_hgt_pst20mts")
    name = v.get("stn_nam") or ""
    return {"id": v.get("wmo_id_extnd"), "name": " ".join(w.capitalize() for w in name.split()),
            "lat": None if lat is None else round(lat, 4), "lon": None if lon is None else round(lon, 4),
            "t": _iso(v["date_tm"]) if v.get("date_tm") else None,
            "hs_ft": m_ft(hs), "dpd_s": _r1(n("pk_wave_pd_pst20mts")), "apd_s": _r1(n("avg_wave_pd_pst20mts")),
            "mwd_deg": _deg(n("avg_pk_wave_dir_pst20mts")),
            "wspd_mph": kmh_mph(n("avg_wnd_spd_pst10mts")), "gust_mph": kmh_mph(n("max_wnd_spd_pst10mts")),
            "wdir_deg": _deg(n("avg_wnd_dir_pst10mts")), "wtmp_f": c_f(n("avg_sea_sfc_temp_pst10mts")),
            "atmp_f": c_f(n("avg_air_temp_pst10mts")), "pres_mb": _r1(n("avg_mslp_pst10mts"))}


# NANOOS / Backyard Buoys ERDDAP. mapping: output key -> (ERDDAP variable, converter). The QC column is the variable
# plus the dataset's suffix; only QARTOD flags 1 (pass) and 2 (not evaluated) are used.
NWEM = "https://nwem.apl.washington.edu"         # erddap.nanoos.org 302s here (plain http) and drops the query
BYB = "https://erddap.backyardbuoys.org"          # erddap.nanoos.org 302s Backyard Buoys datasets here
MET = {"wspd_mph": ("wind_speed", ms_mph), "wdir_deg": ("wind_from_direction", _deg),
       "pres_mb": ("air_pressure_at_mean_sea_level", _r1), "atmp_f": ("air_temperature", c_f)}
MET_GUST = dict(MET, gust_mph=("wind_speed_of_gust", ms_mph))
HYDRO = {"wtmp_f": ("sea_water_temperature", c_f)}
WAVES = {"hs_ft": ("sea_surface_wave_significant_height", m_ft), "apd_s": ("sea_surface_wave_mean_period", _r1),
         "dpd_s": ("sea_surface_wave_period_at_variance_spectral_density_maximum", _r1),
         "mwd_deg": ("sea_surface_wave_from_direction_at_variance_spectral_density_maximum", _deg),
         "wtmp_f": ("sea_water_temperature", c_f)}
QA, QB = "_qc_aggregate", "_qc_agg"
NVS = "https://nvs.nanoos.org/Explorer"


def _apl(sid, name, datasets, ndbc=None):
    return {"id": sid, "name": name, "src": "NANOOS", "owner": "UW Applied Physics Laboratory", "credit": CREDIT_NANOOS,
            "link": NVS, "ndbc": ndbc, "datasets": [(NWEM, ds, m, QA) for ds, m in datasets]}


def _byb(key, name, tribe):
    ds = "backyardbuoys_" + key
    return {"id": "byb_" + key, "name": name, "src": "BYB", "owner": tribe + " (Backyard Buoys)", "credit": CREDIT_BYB,
            "link": BYB + "/erddap/tabledap/%s.html" % ds, "ndbc": None, "datasets": [(BYB, ds, WAVES, QB)]}


NANOOS_STATIONS = [
    _apl("46119", "Cha'ba (La Push)", [("chaba_met", MET_GUST), ("chaba_ctd_nrt", HYDRO)], ndbc="46119"),
    _apl("46118", "Se'lhaem (Bellingham Bay)", [("bellinghambay_met", MET_GUST), ("bellinghambay_surfhydro", HYDRO)],
         ndbc="46118"),
    _apl("orca1", "ORCA Twanoh (Hood Canal)", [("orca1_met", MET)]),
    _apl("orca2", "ORCA Hoodsport (Hood Canal)", [("orca2_met", MET)]),
    _apl("orca3", "ORCA Hansville", [("orca3_met", MET)]),
    _apl("orca4", "ORCA Dabob Bay", [("orca4_met", MET)]),
    _apl("npby1", "ORCA Point Wells", [("npby1_met", MET)]),
    _apl("npby2", "ORCA Carr Inlet", [("npby2_met", MET)]),
    _apl("pisces1", "PISCES South (Hood Canal)", [("pisces1_met", MET_GUST)]),
    _apl("pisces2", "PISCES North (Hood Canal)", [("pisces2_met", MET_GUST)]),
    _apl("pisces3", "PISCES East (Hood Canal)", [("pisces3_met", MET_GUST)]),
    _byb("quileute_center", "Quileute Center (La Push)", "Quileute Tribe"),
    _byb("quileute_north", "Quileute North (La Push)", "Quileute Tribe"),
    _byb("quileute_south", "Quileute South (La Push)", "Quileute Tribe"),
    _byb("quinault_north", "Quinault North (Taholah)", "Quinault Indian Nation"),
    _byb("quinault_mid", "Quinault Mid (Taholah)", "Quinault Indian Nation"),
    _byb("quinault_south", "Quinault South (Taholah)", "Quinault Indian Nation"),
]


def erddap_url(host, dataset, mapping, qc):
    vs = [v for v, _ in mapping.values()]
    cols = ["time", "latitude", "longitude"] + vs + [v + qc for v in vs]
    return "%s/erddap/tabledap/%s.json?%s&time%%3E=now-6hours" % (host, dataset, ",".join(cols))


def parse_erddap(json_text, mapping):
    """ERDDAP tabledap JSON -> {t, lat, lon, <keys>}: per key the newest value whose QC flag is 1 or 2"""
    table = json.loads(json_text)["table"]
    names = table["columnNames"]
    idx = {n: i for i, n in enumerate(names)}
    rows = sorted(table["rows"], key=lambda r: r[idx["time"]], reverse=True)
    out, used = {}, []
    for key, (var, conv) in mapping.items():
        if var not in idx:
            continue
        qi = idx.get(var + QA, idx.get(var + QB))
        for r in rows:
            val = r[idx[var]]
            if val is None or (qi is not None and r[qi] not in (1, 2, None)):
                continue
            out[key] = conv(float(val))
            used.append(r)
            break
    if used:
        newest = max(used, key=lambda r: r[idx["time"]])
        out["t"] = _iso(newest[idx["time"]])
        if "latitude" in idx and newest[idx["latitude"]] is not None:
            out["lat"], out["lon"] = round(newest[idx["latitude"]], 4), round(newest[idx["longitude"]], 4)
    return out


def nanoos_record(st, parsed):
    """one NANOOS_STATIONS entry + its parsed datasets -> a station record (None when nothing came back)"""
    parsed = [p for p in parsed if p and p.get("t")]
    if not parsed:
        return None
    rec = {k: st[k] for k in ("id", "name", "src", "owner", "credit", "link", "ndbc")}
    for p in sorted(parsed, key=lambda p: p["t"]):
        rec.update({k: v for k, v in p.items() if v is not None and k != "t"})
    rec["t"] = max(p["t"] for p in parsed)
    return rec


def parse_coops(json_text):
    """CO-OPS datagetter date=latest JSON (wind or water_temperature, units=english) -> record ({} on error)"""
    d = json.loads(json_text)
    rows = d.get("data") or []
    if not rows:
        return {}
    r = rows[-1]
    t = calendar.timegm(time.strptime(r["t"], "%Y-%m-%d %H:%M"))
    if "s" in r:                                     # wind, knots
        return {"t": t, "wspd_mph": kt_mph(_num(r.get("s"))), "gust_mph": kt_mph(_num(r.get("g"))),
                "wdir_deg": _deg(_num(r.get("d")))}
    return {"t": t, "wtmp_f": _r1(_num(r.get("v")))}  # water temperature, °F


def coops_url(product, sid):
    return COOPS_DATA.format(product=product, id=sid)


def coops_sensor_stations(json_text, bbox):
    """CO-OPS mdapi stations.json?type=waterlevels&expand=sensors -> window stations with a live wind or water-temp
    sensor: [{id, name, lat, lon, src, sensors}] (the same shape tides.py caches)"""
    out = []
    for s in json.loads(json_text).get("stations", []):
        lat, lon = s.get("lat"), s.get("lng", s.get("lon"))
        if lat is None or lon is None or not _in(lat, lon, bbox):
            continue
        sens = s.get("sensors") or {}
        sens = sens.get("sensors", []) if isinstance(sens, dict) else sens
        have = set()
        for x in sens:
            if x.get("status") != 1:
                continue
            nm = (x.get("name") or "").lower()
            if nm == "wind":
                have.add("wind")
            elif nm == "water temperature":
                have.add("wtemp")
            elif nm.endswith(" wl"):
                have.add("wl")
        if have & {"wind", "wtemp"}:
            out.append({"id": str(s["id"]), "name": s.get("name"), "lat": lat, "lon": lon, "src": "COOPS",
                        "sensors": sorted(have)})
    return sorted(out, key=lambda m: m["id"])


def _cache_meta(cache):
    """tides_cache.json's meta, in whichever container tides.py keeps it -> list of meta records"""
    meta = cache.get("meta") if isinstance(cache, dict) else None
    recs = []
    if isinstance(meta, list):
        recs = meta
    elif isinstance(meta, dict):
        for v in meta.values():
            if isinstance(v, list):
                recs.extend(v)
            elif isinstance(v, dict) and "id" in v:
                recs.append(v)
            elif isinstance(v, dict):
                recs.extend(x for x in v.values() if isinstance(x, dict) and "id" in x)
    return [r for r in recs if isinstance(r, dict) and r.get("sensors") and r.get("src", "COOPS") == "COOPS"]


def coops_record(meta, parsed, table=None):
    """a CO-OPS meta record + its parsed observations -> station record; `ndbc` names NDBC's relay of the same gauge"""
    parsed = [p for p in parsed if p and p.get("t")]
    if not parsed:
        return None
    relay = None
    for sid, info in (table or {}).items():
        if info.get("coops") == meta["id"]:
            relay = sid
            break
    rec = {"id": meta["id"], "name": meta.get("name") or meta["id"], "lat": meta.get("lat"), "lon": meta.get("lon"),
           "src": "COOPS", "owner": "NOAA CO-OPS", "credit": None, "link": COOPS_PAGE.format(id=meta["id"]),
           "ndbc": relay}
    for p in parsed:
        rec.update({k: v for k, v in p.items() if v is not None and k != "t"})
    rec["t"] = max(p["t"] for p in parsed)
    return rec


# ---- merge -------------------------------------------------------------------------------------------------------

def _overlay(base, rec, keys):
    """copy rec's values over base: all of them when rec is not much older than base's matching time, else only gaps"""
    newer = rec.get("t") is not None and rec["t"] >= (base.get("_wt" if keys is WAVE_KEYS else "t") or 0) - RELAY_SLACK_S
    for k in keys:
        v = rec.get(k)
        if v is not None and (newer or base.get(k) is None):
            base[k] = v
    return newer


def merge(latest, realtime=None, spec=None, cdip=None, eccc=None, others=(), table=None, now=None):
    """-> list of station records in the BUOYS shape (None values dropped, stale flagged, old ones removed)"""
    realtime, spec, cdip, eccc, table = realtime or {}, spec or {}, cdip or {}, eccc or {}, table or {}
    now = time.time() if now is None else now
    st = {}
    for sid, rec in latest.items():
        r = dict(rec)
        info = table.get(sid, {})
        r.update(name=info.get("name") or sid, owner=OWNERS.get(info.get("owner"), info.get("owner") or "NOAA NDBC"),
                 src="NDBC", link=NDBC_PAGE.format(id=sid.lower()), credit=None)
        r["_wt"] = r["t"] if r.get("hs_ft") is not None else None
        rows = realtime.get(sid) or []
        if rows:
            for k in MET_KEYS:                       # gaps in the newest row filled from the last 3 h of history
                if r.get(k) is None:
                    r[k] = next((x[k] for x in rows if x[k] is not None and x["t"] >= r["t"] - 3 * 3600), None)
            waves = [x for x in rows if x["hs_ft"] is not None]
            if waves and r["_wt"] is None and waves[0]["t"] >= r["t"] - STALE_H * 3600:
                w0 = waves[0]["t"]
                for k in WAVE_KEYS:
                    r[k] = next((x[k] for x in waves if x[k] is not None and x["t"] >= w0 - 3600), None)
                r["_wt"] = w0
                r["t"] = max(r["t"], w0)
            trace, t0 = hourly_trace(rows)
            if trace and any(v is not None for v in trace):
                r["trace"], r["trace_t0"] = trace, t0
        sp = spec.get(sid)
        if sp and r.get("_wt") and abs(sp["t"] - r["_wt"]) <= 2 * 3600:
            r.update({k: sp.get(k) for k in SPLIT_KEYS})
        st[sid] = r
    for cid, c in cdip.items():
        nid = CDIP_RELAY.get(cid)
        if not nid:
            continue
        r = st.get(nid)
        if r is None:
            if c.get("lat") is None:
                continue
            r = st[nid] = {"id": nid, "lat": c["lat"], "lon": c["lon"], "t": c["t"],
                           "name": (table.get(nid) or {}).get("name") or "CDIP " + cid, "_wt": None}
        if _overlay(r, c, WAVE_KEYS):
            r["_wt"] = c["t"]
            r["t"] = max(r.get("t") or 0, c["t"])
        r.update(src="CDIP", owner="Scripps CDIP", credit=CREDIT_CDIP, link=CDIP_PAGE.format(id=cid))
    for wmo, e in eccc.items():
        nid = ECCC_IDS.get(wmo)
        if not nid or not e or e.get("t") is None:
            continue
        r = st.get(nid)
        if r is None:
            if e.get("lat") is None:
                continue
            r = st[nid] = {"id": nid, "lat": e["lat"], "lon": e["lon"], "t": e["t"], "name": e.get("name") or nid,
                           "_wt": None, "link": NDBC_PAGE.format(id=nid)}
        if _overlay(r, e, WAVE_KEYS):
            r["_wt"] = e["t"]
        _overlay(r, e, MET_KEYS)
        r["t"] = max(r.get("t") or 0, e["t"])
        r.update(src="ECCC", owner="Environment and Climate Change Canada", credit=CREDIT_ECCC)
    for o in others:
        if not o:
            continue
        nid = (o.get("ndbc") or "").upper()
        base = st.pop(nid, None) if nid else None
        if base is None:
            base = {"_wt": None}
        else:
            o = dict(o)
            if o.get("lat") is None:
                o.pop("lat", None), o.pop("lon", None)
        _overlay(base, o, WAVE_KEYS)
        _overlay(base, o, MET_KEYS)
        for k in ("id", "name", "src", "owner", "credit", "link", "lat", "lon"):
            if k in o:
                base[k] = o[k]
        base["t"] = max(base.get("t") or 0, o["t"])
        st[o["id"]] = base
    out = []
    for r in st.values():
        if r.get("lat") is None or r.get("lon") is None:
            continue
        if r.get("hs_ft") is None and r.get("wspd_mph") is None and r.get("wtmp_f") is None:
            continue
        age = now - r["t"]
        if age > DROP_H * 3600:
            continue
        rec = {k: v for k, v in r.items() if v is not None and not k.startswith("_") and k != "ndbc"}
        rec["credit"] = r.get("credit")
        rec["t"] = int(r["t"])
        if age > STALE_H * 3600:
            rec["stale"] = True
        out.append(rec)
    return sorted(out, key=lambda s: (-s["lat"], s["id"]))


# ---- fetch and build ---------------------------------------------------------------------------------------------

class HostDown(Exception):
    """a host that timed out or refused earlier in this run is skipped (airquality.HostDown pattern)"""


_DOWN = set()


def fetch(url, headers=None):
    """GET -> bytes; 2 tries, 20 s timeout; HTTP errors are raised at once (404 = no file / no data)"""
    host = urllib.parse.urlsplit(url).netloc
    if host in _DOWN:
        raise HostDown(url)
    h = {"User-Agent": UA}
    h.update(headers or {})
    last = None
    for i in range(TRIES):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=TIMEOUT) as r:
                return r.read()
        except urllib.error.HTTPError:
            raise
        except OSError as e:                         # URLError, timeouts, refused connections
            last = e
            if i + 1 < TRIES:
                time.sleep(2)
    _DOWN.add(host)
    raise last


def _epoch(now):
    if now is None:
        return time.time()
    if isinstance(now, dt.datetime):
        return now.timestamp()
    return float(now)


def _read_cache():
    try:
        with open(os.path.join(DATA, "tides_cache.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def build(log=print, now=None):
    if not region.cfg().get("coastal"):
        return 0
    now = _epoch(now)
    bbox = region.bbox()
    _DOWN.clear()
    failed = set()

    def get(url, headers=None):
        try:
            body = fetch(url, headers)
            return body.decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code not in (404, 416):
                failed.add(urllib.parse.urlsplit(url).netloc)
                log("buoys: HTTP %s %s" % (e.code, url.split("?")[0]))
        except HostDown:
            pass
        except Exception as e:  # noqa: BLE001
            failed.add(urllib.parse.urlsplit(url).netloc)
            log("buoys: %s %s" % (type(e).__name__, url.split("?")[0]))
        return None

    text = get(STATION_TABLE)
    table = parse_station_table(text) if text else {}
    text = get(LATEST_OBS)
    latest = parse_latest_obs(text, bbox) if text else {}

    realtime, spec = {}, {}
    for sid, rec in latest.items():
        if not (sid.isdigit() or any(rec.get(k) is not None for k in WAVE_KEYS)):
            continue                                 # C-MAN and NOS stations report no waves
        text = get(REALTIME.format(id=sid, ext="txt"), {"Range": REALTIME_RANGE["txt"]})
        rows = parse_realtime(text) if text else []
        if rows:
            realtime[sid] = rows
        if (table.get(sid) or {}).get("owner") != "C" and any(r["hs_ft"] is not None for r in rows):
            text = get(REALTIME.format(id=sid, ext="spec"), {"Range": REALTIME_RANGE["spec"]})
            sp = parse_spec(text) if text else {}
            if sp:
                spec[sid] = sp

    text = get(CDIP_URL)
    cdip = parse_cdip(text) if text else {}

    eccc = {}
    today = time.strftime("%Y%m%d", time.gmtime(now))
    yday = time.strftime("%Y%m%d", time.gmtime(now - 86400))
    for wmo in ECCC_IDS:
        for base in (ECCC_DIR.format(day=today, wmo=wmo), ECCC_DIR_DATED.format(day=yday, wmo=wmo)):
            listing = get(base)
            files = sorted(set(re.findall(r'href="(\d{4}-\d\d-\d\d-\d{4}-%s-AUTO-swob\.xml)"' % wmo, listing or "")))
            if files:
                xml = get(base + files[-1])
                if xml:
                    try:
                        eccc[wmo] = parse_swob(xml)
                    except (ET.ParseError, ValueError, KeyError) as e:
                        log("buoys: SWOB %s unreadable (%s)" % (wmo, e))
                break

    others = []
    for stn in NANOOS_STATIONS:
        parsed = []
        for host, ds, mapping, qc in stn["datasets"]:
            text = get(erddap_url(host, ds, mapping, qc))
            if text:
                try:
                    parsed.append(parse_erddap(text, mapping))
                except (ValueError, KeyError) as e:
                    log("buoys: %s unreadable (%s)" % (ds, e))
        rec = nanoos_record(stn, parsed)
        if rec:
            others.append(rec)

    cache = _read_cache()
    metas = _cache_meta(cache) if cache else []
    metas = [m for m in metas if m.get("lat") is not None and _in(m["lat"], m["lon"], bbox)
             and ({"wind", "wtemp"} & set(m.get("sensors") or []))]
    if not metas:
        text = get(COOPS_META)
        metas = coops_sensor_stations(text, bbox) if text else []
    for m in metas:
        parsed = []
        for product, sensor in (("wind", "wind"), ("water_temperature", "wtemp")):
            if sensor in (m.get("sensors") or []):
                text = get(coops_url(product, m["id"]))
                time.sleep(COOPS_SLEEP_S)
                if text:
                    try:
                        parsed.append(parse_coops(text))
                    except (ValueError, KeyError) as e:
                        log("buoys: CO-OPS %s %s unreadable (%s)" % (m["id"], product, e))
        rec = coops_record(m, parsed, table)
        if rec:
            others.append(rec)

    stations = merge(latest, realtime, spec, cdip, eccc, others, table, now)
    data = {"updated": dt.datetime.now().strftime("%a %b %d %I:%M %p"), "updated_t": int(time.time()),
            "stations": stations}
    os.makedirs(DATA, exist_ok=True)
    with open(OUT + ".tmp", "w", encoding="utf-8") as f:
        f.write("window.BUOYS = %s;\n" % json.dumps(data, separators=(",", ":")))
    os.replace(OUT + ".tmp", OUT)
    waves = sum(1 for s in stations if s.get("hs_ft") is not None)
    stale = sum(1 for s in stations if s.get("stale"))
    log("buoys: %d stations, %d with waves, %d stale, %d failed hosts" % (len(stations), waves, stale,
                                                                          len(failed | _DOWN)))
    return len(stations)


if __name__ == "__main__":
    t0 = time.time()
    build()
    print("done in %.0fs" % (time.time() - t0))
