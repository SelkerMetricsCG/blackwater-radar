"""The rivers the dashboard covers. One entry per gauge.

Adding a river is one entry here: the USGS daily-value gauge, its drainage
area (from the USGS site file), the SNOTEL stations that index its snowpack,
and the flow below which the paddling season is over. The analysis package
(``wenatchee/``) is river-agnostic; every station id and threshold it uses
comes from this file through ``run_rivers.py``.

``key`` becomes the R2 prefix (rivers/<key>/...) and the value in the site's
river picker, so keep it a plain slug. ``region`` is the radar-site region
whose hourly ``rivers.js`` / ``stations.js`` feed carries the live values.
"""

# SNOTEL stations by NRCS site id. ``in_basin`` is whether the station sits
# inside the river's own drainage; an index station outside it is legitimate
# (standard operational practice) but is labelled as such on the page.
STATIONS = {
    606: dict(site_id=606, name="Lyman Lake", state="WA", elev_ft=5990, in_basin=False,
              note="Glacier Peak/Suiattle drainage - OUT of basin, high elevation"),
    791: dict(site_id=791, name="Stevens Pass", state="WA", elev_ft=4060, in_basin=True,
              note="West side, long record"),
    507: dict(site_id=507, name="Grouse Camp", state="WA", elev_ft=5020, in_basin=True,
              note="Upper Wenatchee / Chiwawa"),
    352: dict(site_id=352, name="Blewett Pass", state="WA", elev_ft=4270, in_basin=True,
              note="SE basin, lower divide"),
}

# Kayaker-meaningful flow bands (cfs). Per river, because 3,000 cfs is a
# different river on the Wenatchee and on a creek.
WENATCHEE_BINS = dict(
    edges=(0, 1000, 2000, 3000, 5000, 8000, 12000, float("inf")),
    labels=("<1k", "1-2k", "2-3k", "3-5k", "5-8k", "8-12k", ">12k"),
    desc=("Low / baseflow - river is out", "Mellow float, easy rapids",
          "Fun class II-III, good flow", "Pushy class III, strong current",
          "High water, big moves", "Expert only, near flood stage",
          "Bank full / flooding"),
)

ICICLE_BINS = dict(
    edges=(0, 500, 1000, 1500, 2000, 3000, 4000, float("inf")),
    labels=("<500", "500-1k", "1-1.5k", "1.5-2k", "2-3k", "3-4k", ">4k"),
    desc=("Low", "Low-moderate", "Moderate", "Moderate-high", "High", "Very high", "Flood"),
)
# Season-end presets the site can flip between (the buttons).
WENATCHEE_THRESHOLDS = (1000.0, 2000.0, 3000.0, 4000.0, 5000.0, 6000.0, 7000.0, 8000.0, 9000.0, 10000.0)
ICICLE_THRESHOLDS = (500.0, 1000.0, 1500.0, 2000.0, 2500.0, 3000.0, 3500.0, 4000.0)

RIVERS = [
    # First entry is the site's default river: kayakers read Peshastin.
    dict(
        key="wenatchee-peshastin",
        name="Wenatchee River at Peshastin",
        short="Wenatchee at Peshastin",
        river="Wenatchee River",
        usgs="12459000",
        drainage_mi2=1000.0,
        lat=47.5831, lon=-120.6195,
        stations=[606, 791, 507, 352],
        temp_stations=[606, 791],
        runnable_cfs=1000.0,
        thresholds=WENATCHEE_THRESHOLDS,
        bins=WENATCHEE_BINS,
        region="pnw",
        start_wy=1990,
        blurb=("The paddlers' gauge: the Leavenworth to Peshastin reach, above the Dryden "
               "diversions. No water-temperature record at this site."),
    ),
    dict(
        key="wenatchee-plain",
        name="Wenatchee River at Plain",
        short="Wenatchee at Plain",
        river="Wenatchee River",
        usgs="12457000",
        drainage_mi2=591.0,
        lat=47.7631, lon=-120.6650,
        stations=[606, 791, 507, 352],
        # Only Stevens Pass (Nason Creek) drains to Plain; the Chiwawa (Grouse Camp) joins below the gauge.
        in_basin={791: True, 507: False, 352: False, 606: False},
        temp_stations=[606, 791],
        runnable_cfs=1000.0,
        thresholds=WENATCHEE_THRESHOLDS,
        bins=WENATCHEE_BINS,
        region="pnw",
        start_wy=1990,
        blurb=("The upper river below Lake Wenatchee and Nason Creek, above the Chiwawa. "
               "No diversions of note above it; no water-temperature record."),
    ),
    dict(
        key="icicle-creek",
        name="Icicle Creek above Snow Creek near Leavenworth",
        short="Icicle Creek",
        river="Icicle Creek",
        usgs="12458000",
        drainage_mi2=193.0,
        lat=47.5411, lon=-120.7189,
        stations=[606, 791, 507, 352],
        # No SNOTEL sits inside the Icicle drainage; all four are index stations.
        in_basin={791: False, 507: False, 352: False, 606: False},
        temp_stations=[606, 791],
        runnable_cfs=1000.0,
        thresholds=ICICLE_THRESHOLDS,
        bins=ICICLE_BINS,
        region="pnw",
        start_wy=1994,          # the daily record starts 1 Oct 1993
        blurb=("The Icicle above the Snow Creek confluence and the hatchery diversion, in the Alpine "
               "Lakes. A smaller, flashier stream: thresholds run 500 to 4,000 cfs here."),
    ),
    dict(
        key="wenatchee-monitor",
        name="Wenatchee River at Monitor",
        short="Wenatchee at Monitor",
        river="Wenatchee River",
        usgs="12462500",
        drainage_mi2=1301.0,
        lat=47.4993, lon=-120.4245,
        stations=[606, 791, 507, 352],
        temp_stations=[606, 791],
        runnable_cfs=1000.0,
        thresholds=WENATCHEE_THRESHOLDS,
        bins=WENATCHEE_BINS,
        region="pnw",
        start_wy=1990,
        blurb=("The hydrology gauge: the lower river below the Dryden, Icicle and Peshastin "
               "irrigation diversions, with the water-temperature record. Summer flows here are "
               "net of withdrawal; paddlers read Peshastin."),
    ),
]
