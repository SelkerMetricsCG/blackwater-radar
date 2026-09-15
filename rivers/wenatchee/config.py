"""Configuration for the Wenatchee River snowpack-runoff analysis.

Everything tunable lives here. Nothing else in the package hard-codes a
station id, a threshold, or a unit conversion.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Sequence

import pandas as pd

# --------------------------------------------------------------------------
# Unit conversions
# --------------------------------------------------------------------------
CFS_TO_M3S = 0.028316846592           # exact: 0.3048^3
SECONDS_PER_DAY = 86400.0
M3_PER_ACRE_FOOT = 1233.48183754752   # exact
# One cfs sustained for one day, in acre-feet:
AF_PER_CFS_DAY = CFS_TO_M3S * SECONDS_PER_DAY / M3_PER_ACRE_FOOT   # 1.98347...


@dataclass(frozen=True)
class Station:
    """A SNOTEL station."""

    site_id: int
    name: str
    state: str
    elev_ft: int
    in_basin: bool          # inside the Wenatchee drainage?
    note: str = ""

    @property
    def triplet(self) -> str:
        return f"{self.site_id}:{self.state}:SNTL"


# --------------------------------------------------------------------------
# The station set
# --------------------------------------------------------------------------
# The four stations of the original MATLAB analysis, plus in-basin candidates
# that let the tool test whether the out-of-basin Lyman Lake predictor is
# actually necessary. "--stations core" uses only the original four.
CORE_STATIONS: tuple[Station, ...] = (
    Station(606, "Lyman Lake", "WA", 5990, in_basin=False,
            note="Glacier Peak/Suiattle drainage - OUT of basin, high elevation"),
    Station(791, "Stevens Pass", "WA", 4060, in_basin=True,
            note="West side, long record"),
    Station(507, "Grouse Camp", "WA", 5020, in_basin=True,
            note="Upper Wenatchee / Chiwawa"),
    Station(352, "Blewett Pass", "WA", 4270, in_basin=True,
            note="SE basin, lower divide"),
)

# Additional in-basin / nearby stations, tested when --stations extended.
EXTENDED_STATIONS: tuple[Station, ...] = (
    Station(672, "Trinity", "WA", 4980, in_basin=True,
            note="Upper Chiwawa - in basin, high elevation"),
    Station(909, "Fish Lake", "WA", 3400, in_basin=True,
            note="Near Lake Wenatchee - in basin, low elevation"),
    Station(680, "Tunnel Ave", "WA", 3760, in_basin=True,
            note="Upper Wenatchee - in basin"),
    Station(898, "Pope Ridge", "WA", 3510, in_basin=True,
            note="East basin - in basin, low elevation"),
)


@dataclass
class Config:
    # --- Gauge -----------------------------------------------------------
    usgs_site: str = "12462500"          # Wenatchee River at Monitor, WA
    usgs_site_name: str = "Wenatchee River at Monitor"
    drainage_mi2: float = 1301.0

    # --- Stations --------------------------------------------------------
    stations: tuple[Station, ...] = CORE_STATIONS
    # Stations whose air temperature drives the degree-day melt index.
    temp_station_ids: tuple[int, ...] = (606, 791)

    # --- Analysis window -------------------------------------------------
    start_wy: int = 1990
    end_wy: int | None = None            # None -> infer from the data
    # Run the forecast as if today were this date. None -> the last day of
    # observed flow. Setting it to a past date turns the tool into a
    # hindcast, which is how the forecast models get verified.
    as_of: pd.Timestamp | None = None

    # --- Data completeness ----------------------------------------------
    min_days_full_wy: int = 355          # days of Q required to call a WY complete
    min_days_current_wy: int = 60        # days of Q required to analyse current WY
    min_swe_days_per_wy: int = 150       # SNOTEL days required to trust a station-year
    # A station-year is only used in the composite if the station reported
    # through this day-of-water-year (DOY 183 = Apr 1). Guards against a
    # station that dropped out in February faking a low "peak".
    swe_required_through_doy: int = 183
    # A station-year with a peak below this is treated as a dead sensor,
    # not a snow-free year, and excluded from the composite.
    min_peak_swe_in: float = 2.0

    # --- Snowpack index --------------------------------------------------
    # Fixed here, NOT selected per run. The MATLAB version fitted six
    # weighting schemes and reported the winner's in-sample r2 as if it had
    # been specified in advance; every downstream analysis then inherited a
    # choice made on noise. The tool still scores all candidates by
    # leave-one-out skill and prints the table, but the index it uses is
    # whatever this setting says.
    #   peak_swe_in  - mean of station peak SWE in inches (default)
    #   peak_swe_pct - each station as % of its own median, then averaged
    #   apr1_swe_in  - mean Apr-1 SWE, the NRCS operational convention
    snow_index: str = "peak_swe_in"

    # --- Volume accounting ----------------------------------------------
    # "peak" : window starts at each year's composite peak-SWE date (original)
    # "apr1" : window starts Apr 1 every year (fixed length, no window bias)
    volume_window: str = "apr1"
    volume_end_month: int = 9
    volume_end_day: int = 30

    # --- Forecast models -------------------------------------------------
    analog_swe_tolerance_in: float = 8.0  # +/- inches for analog selection
    analog_min_count: int = 5             # widen tolerance until at least this many
    analog_max_count: int = 12            # keep the envelope meaningful
    analog_scale_window_days: int = 7     # days averaged for the analog scale factor
    analog_scale_clip: tuple[float, float] = (0.25, 4.0)   # cap the scale factor
    recession_tau_days: float = 40.0      # exponential tail if analogs run short

    # --- Degree-day melt index -------------------------------------------
    base_temp_f: float = 32.0

    # --- Ecology ---------------------------------------------------------
    # The WA state standard for salmonid spawning/rearing is 17.5 C as a
    # 7-day average of daily MAXIMA (7-DADMax). Daily-mean data understates
    # that, so the tool reports both and labels which is which.
    salmon_thresh_c: float = 17.5
    sustained_below_days: int = 7         # consecutive days for "sustained" drop
    runnable_cfs: float = 1000.0          # kayak season-end threshold
    # Issue date for the validated season-end forecast. Spring, because that
    # is when the question actually gets asked.
    season_issue_month: int = 5
    season_issue_day: int = 1

    # --- Flow bins (kayaker-meaningful) ----------------------------------
    flow_bin_edges: tuple[float, ...] = (0, 1000, 2000, 3000, 5000, 8000, 12000, float("inf"))
    flow_bin_labels: tuple[str, ...] = ("<1k", "1-2k", "2-3k", "3-5k", "5-8k", "8-12k", ">12k")
    flow_bin_desc: tuple[str, ...] = (
        "Low / baseflow - river is out",
        "Mellow float, easy rapids",
        "Fun class II-III, good flow",
        "Pushy class III, strong current",
        "High water, big moves",
        "Expert only, near flood stage",
        "Bank full / flooding",
    )

    # --- Statistics ------------------------------------------------------
    bootstrap_n: int = 2000
    rng_seed: int = 20260501
    prediction_interval: float = 0.80     # central interval reported
    # Minimum sample size before a fitted slope is allowed to be reported.
    # With n=4 and one predictor, r2 must exceed 0.90 to be significant at
    # all, so small-n fits are suppressed rather than narrated.
    min_n_for_regression: int = 15
    # Below this r2, a relationship is treated as noise and not narrated.
    # With ~15 reported fits at n~35, the Bonferroni threshold is r2 ~ 0.25.
    min_r2_to_narrate: float = 0.25

    # --- Paths / fetching -------------------------------------------------
    root: Path = field(default_factory=lambda: Path(__file__).resolve().parent.parent)
    cache_max_age_hours: float = 12.0
    offline: bool = False
    request_timeout_s: float = 90.0
    request_retries: int = 3

    # --- Output ----------------------------------------------------------
    figure_dpi: int = 130
    show_figures: bool = False
    make_figures: bool = True
    # Web export (output/web.js + web.json) for the rivers dashboard, and the
    # season-end forecast re-issued on every day of the spring so the page can
    # show how the call moved. Additive: neither changes a reported number.
    make_web: bool = True
    make_track: bool = True
    track_start: tuple[int, int] = (3, 1)     # (month, day) of the first re-issue
    track_end: tuple[int, int] = (6, 15)
    track_step_days: int = 1

    # ---------------------------------------------------------------------
    @property
    def cache_dir(self) -> Path:
        return self.root / "data_cache"

    @property
    def output_dir(self) -> Path:
        return self.root / "output"

    @property
    def figure_dir(self) -> Path:
        return self.output_dir / "figures"

    def station_by_id(self, site_id: int) -> Station | None:
        for s in self.stations:
            if s.site_id == site_id:
                return s
        return None

    def with_stations(self, stations: Sequence[Station]) -> "Config":
        return replace(self, stations=tuple(stations))


# --------------------------------------------------------------------------
# Plot formatting shared across figures
# --------------------------------------------------------------------------
# First day-of-water-year of each month, on the common 365-day axis.
# The MATLAB version ended this vector at 335, which drew every 'Sep' tick
# one day early: Aug 1 is day 305 and August has 31 days, so Sep 1 is 336.
MONTH_START_DOY = (1, 32, 62, 93, 124, 152, 183, 213, 244, 274, 305, 336)
MONTH_LABELS = ("Oct", "Nov", "Dec", "Jan", "Feb", "Mar",
                "Apr", "May", "Jun", "Jul", "Aug", "Sep")

STATION_COLORS = {
    "Lyman Lake": "#9A19CC",
    "Stevens Pass": "#0073BD",
    "Grouse Camp": "#D9541A",
    "Blewett Pass": "#78AB31",
    "Trinity": "#1B9E77",
    "Fish Lake": "#E7298A",
    "Tunnel Ave": "#7570B3",
    "Pope Ridge": "#A6761D",
}

DECADE_COLORS = ("#3366CC", "#33B24D", "#E68019", "#CC1A1A")

FLOW_BIN_COLORS = ("#CCCCCC", "#99CC99", "#33B24D", "#1A80E6",
                   "#E69919", "#E63333", "#991A99")

CURRENT_COLOR = "#D62728"     # the partial water year, everywhere
HIST_COLOR = "#808080"
