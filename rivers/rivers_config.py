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
        bins=WENATCHEE_BINS,
        region="pnw",
        start_wy=1990,
        blurb=("The paddlers' gauge: the Leavenworth to Peshastin reach, above the Dryden "
               "diversions. No water-temperature record at this site."),
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
        bins=WENATCHEE_BINS,
        region="pnw",
        start_wy=1990,
        blurb=("The hydrology gauge: the lower river below the Dryden, Icicle and Peshastin "
               "irrigation diversions, with the water-temperature record. Summer flows here are "
               "net of withdrawal; paddlers read Peshastin."),
    ),
]
