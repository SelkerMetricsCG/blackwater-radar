"""Data acquisition: USGS NWIS and NRCS SNOTEL, with an on-disk cache.

Every raw download is written to ``data_cache/`` verbatim. A re-run inside
``cfg.cache_max_age_hours`` reuses the cached copy, so iterating on the
analysis does not hammer the agencies' servers, and ``--offline`` works from
whatever was last downloaded.

Parsing notes (these are where the MATLAB version was fragile):

* USGS RDB has a type-definition row (``5s  15s  20d  14n  10s``) immediately
  after the column header. It does not start with ``#``, so it must be
  detected and skipped explicitly.
* The value column is *not* reliably column 4. It is named
  ``<tsid>_<param>_<stat>``, and a site can return more than one time series
  for the same parameter. We locate the column by name and, if there are
  several, combine them preferring the one with the most data.
* Values can be non-numeric (``Ice``, ``Eqp``, ``Ssn``, ``Bkw``, empty).
  Those become NaN and are dropped, not silently coerced.
* NRCS CSV has a ``Date,...`` header row that does not start with ``#``.
  Missing days come back as empty fields, which must become NaN rather than
  being appended as data.
"""

from __future__ import annotations

import hashlib
import io
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from .config import Config, Station

USER_AGENT = "wenatchee-runoff-analysis/2.0 (personal hydrology tool)"

NWIS_DV = "https://waterservices.usgs.gov/nwis/dv/"
# The successor to the legacy daily-values service. Used as a fallback when
# waterservices answers 503 (it does, intermittently, from cloud runners).
USGS_OGC_DAILY = "https://api.waterdata.usgs.gov/ogcapi/v0/collections/daily/items"
NRCS_REPORT = ("https://wcc.sc.egov.usda.gov/reportGenerator/view_csv/"
               "customSingleStationReport/daily")

# USGS qualifier strings that mean "no numeric value"
_NON_NUMERIC = {"", "ice", "eqp", "ssn", "bkw", "mnt", "dis", "rat", "***", "-"}


class FetchError(RuntimeError):
    pass


# --------------------------------------------------------------------------
# Cache
# --------------------------------------------------------------------------
def _cache_path(cfg: Config, key: str, url: str) -> Path:
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:10]
    return cfg.cache_dir / f"{key}.{digest}.txt"


def _get(cfg: Config, key: str, url: str, label: str) -> str:
    """Fetch ``url``, using / refreshing the on-disk cache."""
    path = _cache_path(cfg, key, url)
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.exists():
        age_h = (time.time() - path.stat().st_mtime) / 3600.0
        if cfg.offline or age_h < cfg.cache_max_age_hours:
            text = path.read_text(encoding="utf-8", errors="replace")
            print(f"    {label}: cache ({age_h:.1f} h old, {len(text):,} chars)")
            return text

    if cfg.offline:
        raise FetchError(f"--offline set but no cached copy of {label}")

    last_err: Exception | None = None
    for attempt in range(1, cfg.request_retries + 1):
        try:
            resp = requests.get(
                url, timeout=cfg.request_timeout_s,
                headers={"User-Agent": USER_AGENT},
            )
            resp.raise_for_status()
            text = resp.text
            if len(text.strip()) == 0:
                raise FetchError("empty response")
            path.write_text(text, encoding="utf-8")
            print(f"    {label}: downloaded ({len(text):,} chars)")
            return text
        except Exception as exc:      # noqa: BLE001 - retry anything transient
            last_err = exc
            if attempt < cfg.request_retries:
                time.sleep(4.0 * attempt)

    # Network failed. Fall back to a stale cache rather than losing the run.
    if path.exists():
        text = path.read_text(encoding="utf-8", errors="replace")
        age_h = (time.time() - path.stat().st_mtime) / 3600.0
        print(f"    {label}: DOWNLOAD FAILED ({last_err}); using stale cache "
              f"({age_h:.1f} h old)")
        return text
    raise FetchError(f"could not fetch {label}: {last_err}")


# --------------------------------------------------------------------------
# USGS NWIS daily values
# --------------------------------------------------------------------------
def parse_nwis_rdb(text: str, param_code: str) -> pd.Series:
    """Parse a USGS RDB daily-values response into a date-indexed Series.

    Returns an empty float Series if the response holds no usable data.
    """
    empty = pd.Series(dtype=float, name=param_code)
    if not text:
        return empty

    header: list[str] | None = None
    rows: list[list[str]] = []
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        parts = line.rstrip("\n").split("\t")
        if header is None:
            header = parts
            continue
        # The RDB type-definition row: every field looks like "15s" / "20d".
        if all(p[:-1].isdigit() and p[-1:].isalpha() for p in parts if p):
            continue
        rows.append(parts)

    if header is None or not rows:
        return empty

    df = pd.DataFrame(rows, columns=header)
    if "datetime" not in df.columns:
        return empty

    # Value columns are named "<tsid>_<param>_<stat>"; the "_cd" twins are
    # qualifier flags, not data.
    value_cols = [c for c in df.columns
                  if f"_{param_code}_" in c and not c.endswith("_cd")]
    if not value_cols:
        return empty

    dates = pd.to_datetime(df["datetime"], format="%Y-%m-%d", errors="coerce")

    series_list: list[pd.Series] = []
    for col in value_cols:
        raw = df[col].astype(str).str.strip()
        raw = raw.where(~raw.str.lower().isin(_NON_NUMERIC))
        vals = pd.to_numeric(raw, errors="coerce")
        s = pd.Series(vals.to_numpy(), index=dates).dropna()
        s = s[~s.index.isna()]
        series_list.append(s)

    # More than one time series for the same parameter: prefer the longest,
    # then fill its gaps from the others.
    series_list.sort(key=len, reverse=True)
    combined = series_list[0]
    for other in series_list[1:]:
        combined = combined.combine_first(other)

    combined = combined[~combined.index.duplicated(keep="first")].sort_index()
    combined.name = param_code
    return combined.astype(float)


def fetch_usgs_daily(cfg: Config, param_code: str, start: str, label: str,
                     stat_code: str = "00003") -> pd.Series:
    """Daily values from NWIS. stat_code 00003 = mean, 00001 = max, 00002 = min.

    The legacy RDB service is tried first (it is what the parser and the
    on-disk cache were written for). If every retry fails, the same series is
    pulled from the newer USGS OGC API instead, so a flaky afternoon at
    waterservices.usgs.gov does not lose the day's run.
    """
    end = pd.Timestamp.today().strftime("%Y-%m-%d")
    url = (f"{NWIS_DV}?format=rdb&sites={cfg.usgs_site}"
           f"&startDT={start}&endDT={end}"
           f"&parameterCd={param_code}&statCd={stat_code}")
    try:
        text = _get(cfg, f"usgs_{cfg.usgs_site}_{param_code}_{stat_code}", url, label)
        return parse_nwis_rdb(text, param_code)
    except FetchError as exc:
        print(f"    {label}: legacy service failed ({exc}); trying the OGC API")
        return fetch_usgs_daily_ogc(cfg, param_code, start, end, label, stat_code)


def fetch_usgs_daily_ogc(cfg: Config, param_code: str, start: str, end: str,
                         label: str, stat_code: str = "00003") -> pd.Series:
    """The same daily series from api.waterdata.usgs.gov (GeoJSON, paged)."""
    import json as _json

    url = (f"{USGS_OGC_DAILY}?monitoring_location_id=USGS-{cfg.usgs_site}"
           f"&parameter_code={param_code}&statistic_id={stat_code}"
           f"&time={start}/{end}&f=json&limit=50000")
    dates: list = []
    vals: list = []
    page = 0
    while url and page < 20:
        page += 1
        text = _get(cfg, f"usgs_ogc_{cfg.usgs_site}_{param_code}_{stat_code}_p{page}",
                    url, f"{label} (OGC page {page})")
        doc = _json.loads(text)
        for feat in doc.get("features", []):
            pr = feat.get("properties", {})
            v = pr.get("value")
            if v is None or str(v).strip().lower() in _NON_NUMERIC:
                continue
            try:
                vals.append(float(v))
            except ValueError:
                continue
            dates.append(pr.get("time"))
        url = next((l.get("href") for l in doc.get("links", [])
                    if l.get("rel") == "next"), None)
    if not vals:
        return pd.Series(dtype=float, name=param_code)
    s = pd.Series(vals, index=pd.to_datetime(dates, errors="coerce"))
    s = s[~s.index.isna()]
    s = s[~s.index.duplicated(keep="first")].sort_index()
    s.name = param_code
    return s.astype(float)


# --------------------------------------------------------------------------
# NRCS SNOTEL
# --------------------------------------------------------------------------
# Element code -> the column name fragment NRCS uses in the CSV header.
_SNOTEL_ELEMENTS = {
    "WTEQ": ("swe_in", "Snow Water Equivalent"),
    "TMAX": ("tmax_f", "Air Temperature Maximum"),
    "TMIN": ("tmin_f", "Air Temperature Minimum"),
    "TAVG": ("tavg_f", "Air Temperature Average"),
    "PREC": ("prec_in", "Precipitation Accumulation"),
}


def parse_snotel_csv(text: str) -> pd.DataFrame:
    """Parse an NRCS Report Generator CSV into a date-indexed DataFrame.

    Columns are renamed to the short names in ``_SNOTEL_ELEMENTS``.
    Missing values (empty fields) become NaN.
    """
    if not text:
        return pd.DataFrame()

    body = "\n".join(ln for ln in text.splitlines()
                     if ln and not ln.lstrip().startswith("#"))
    if not body.strip():
        return pd.DataFrame()

    df = pd.read_csv(io.StringIO(body))
    if df.empty or "Date" not in df.columns:
        return pd.DataFrame()

    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df = df.dropna(subset=["Date"]).set_index("Date").sort_index()

    rename: dict[str, str] = {}
    for col in df.columns:
        for _code, (short, fragment) in _SNOTEL_ELEMENTS.items():
            if col.startswith(fragment):
                rename[col] = short
                break
    df = df.rename(columns=rename)
    keep = [short for short, _ in _SNOTEL_ELEMENTS.values() if short in df.columns]
    df = df[keep].apply(pd.to_numeric, errors="coerce")
    return df[~df.index.duplicated(keep="first")]


def fetch_snotel(cfg: Config, station: Station,
                 elements: tuple[str, ...] = ("WTEQ", "TMAX", "TMIN", "PREC")
                 ) -> pd.DataFrame:
    end = pd.Timestamp.today().strftime("%Y-%m-%d")
    elem_str = ",".join(f"{e}::value" for e in elements)
    url = (f"{NRCS_REPORT}/{station.triplet}/"
           f"{cfg.start_wy - 1}-10-01,{end}/{elem_str}")
    label = f"{station.name} ({station.site_id}, {station.elev_ft} ft)"
    try:
        text = _get(cfg, f"snotel_{station.site_id}", url, label)
    except FetchError as exc:
        print(f"    {label}: UNAVAILABLE ({exc})")
        return pd.DataFrame()
    return parse_snotel_csv(text)


# --------------------------------------------------------------------------
# NOAA CPC Oceanic Nino Index (ENSO state)
# --------------------------------------------------------------------------
ONI_URL = "https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt"
_ONI_SEASONS = ("DJF", "JFM", "FMA", "MAM", "AMJ", "MJJ", "JJA", "JAS", "ASO", "SON", "OND", "NDJ")


def fetch_oni(cfg: Config) -> pd.DataFrame:
    """Three-month running ONI (deg C anomaly of Nino 3.4 SST) from NOAA CPC.

    Columns: season (DJF..NDJ), year (CPC's YR column: the year of the
    season's first month for OND/NDJ, otherwise the calendar year), total,
    anom. Empty frame if the download fails; ENSO context is optional.
    """
    try:
        text = _get(cfg, "oni", ONI_URL, "NOAA ONI (ENSO)")
    except FetchError as exc:
        print(f"    ONI unavailable ({exc}); ENSO context skipped")
        return pd.DataFrame(columns=["season", "year", "total", "anom"])
    rows = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 4 and parts[0] in _ONI_SEASONS:
            try:
                rows.append({"season": parts[0], "year": int(parts[1]),
                             "total": float(parts[2]), "anom": float(parts[3])})
            except ValueError:
                continue
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------
# Bundle
# --------------------------------------------------------------------------
@dataclass
class RawData:
    """Everything downloaded, before any analysis."""

    q_cfs: pd.Series                     # USGS daily mean discharge
    water_temp_c: pd.Series              # USGS daily mean water temperature
    water_temp_max_c: pd.Series          # USGS daily MAX water temperature
    snotel: dict[int, pd.DataFrame]      # site_id -> daily SWE/temp/precip
    stations: tuple[Station, ...]        # only stations that returned data
    fetched_at: pd.Timestamp

    @property
    def last_flow_date(self) -> pd.Timestamp:
        return self.q_cfs.index.max()


def fetch_all(cfg: Config) -> RawData:
    print("=" * 72)
    print("  FETCHING DATA")
    print("=" * 72)

    print(f"\n  USGS {cfg.usgs_site} - {cfg.usgs_site_name}")
    q = fetch_usgs_daily(cfg, "00060", f"{cfg.start_wy - 1}-10-01",
                         "daily mean discharge")
    if q.empty:
        raise FetchError("no USGS discharge data - cannot continue")
    # Physically impossible values guard the whole downstream analysis.
    bad = (q < 0) | (q > 200_000)
    if bad.any():
        print(f"    dropped {int(bad.sum())} out-of-range discharge values")
        q = q[~bad]
    print(f"    {len(q):,} days, {q.index.min():%Y-%m-%d} to {q.index.max():%Y-%m-%d}")

    wt = fetch_usgs_daily(cfg, "00010", "1990-01-01", "daily mean water temp")
    if not wt.empty:
        bad = (wt < -1) | (wt > 40)
        wt = wt[~bad]
        print(f"    {len(wt):,} days, {wt.index.min():%Y-%m-%d} to {wt.index.max():%Y-%m-%d}")
    else:
        print("    no water temperature record")

    # Daily MAXIMUM water temperature. The Washington salmonid criterion is a
    # 7-day average of daily maxima, so the daily mean alone cannot evaluate
    # it. Not every gauge publishes this; the analysis degrades gracefully and
    # says so when it is missing.
    wt_max = fetch_usgs_daily(cfg, "00010", "1990-01-01",
                              "daily max water temp", stat_code="00001")
    if not wt_max.empty:
        wt_max = wt_max[(wt_max >= -1) & (wt_max <= 40)]
        print(f"    {len(wt_max):,} days of daily maxima (for 7-DADMax)")
    else:
        print("    no daily-maximum water temperature (7-DADMax approximated)")

    print("\n  NRCS SNOTEL")
    snotel: dict[int, pd.DataFrame] = {}
    good: list[Station] = []
    for st in cfg.stations:
        df = fetch_snotel(cfg, st)
        if df.empty or "swe_in" not in df.columns or df["swe_in"].notna().sum() < 365:
            print(f"      -> insufficient data, station dropped")
            continue
        snotel[st.site_id] = df
        good.append(st)

    if not good:
        raise FetchError("no SNOTEL stations returned usable data")

    return RawData(
        q_cfs=q,
        water_temp_c=wt,
        water_temp_max_c=wt_max,
        snotel=snotel,
        stations=tuple(good),
        fetched_at=pd.Timestamp.now(),
    )
