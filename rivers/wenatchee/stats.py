"""Regression, skill scoring and trend testing.

The MATLAB original reported bare in-sample r-squared for roughly thirty
fitted slopes and never printed an interval. Everything here exists to make
each reported number falsifiable:

* :class:`Fit` carries a genuine prediction interval (t multiplier plus the
  leverage term), leave-one-out skill, and a flag for when the prediction
  sits outside the calibration range.
* :func:`fit_ols` can work in log space, back-transforming the mean with
  Duan's smearing estimator, which keeps volumes positive and stabilises the
  variance that otherwise scales with the mean.
* :func:`trend` uses Theil-Sen with a Mann-Kendall test and the Hamed-Rao
  autocorrelation correction, so a trend is only claimed when the record can
  actually support it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy import stats


# --------------------------------------------------------------------------
# Skill scores
# --------------------------------------------------------------------------
def skill_score(observed: np.ndarray, predicted: np.ndarray) -> float:
    """Nash-Sutcliffe / 1 - SSE/SST.

    Deliberately allowed to go negative: on out-of-sample predictions a
    negative value is the honest statement that the model is worse than
    predicting the mean. Never substitute squared correlation, which hides
    bias and scale errors.
    """
    obs = np.asarray(observed, dtype=float)
    pred = np.asarray(predicted, dtype=float)
    ok = np.isfinite(obs) & np.isfinite(pred)
    if ok.sum() < 3:
        return float("nan")
    obs, pred = obs[ok], pred[ok]
    ss_tot = float(np.sum((obs - obs.mean()) ** 2))
    if ss_tot == 0:
        return float("nan")
    return 1.0 - float(np.sum((obs - pred) ** 2)) / ss_tot


def rmse(observed: np.ndarray, predicted: np.ndarray) -> float:
    obs, pred = np.asarray(observed, float), np.asarray(predicted, float)
    ok = np.isfinite(obs) & np.isfinite(pred)
    return float(np.sqrt(np.mean((obs[ok] - pred[ok]) ** 2))) if ok.sum() else float("nan")


def mae(observed: np.ndarray, predicted: np.ndarray) -> float:
    obs, pred = np.asarray(observed, float), np.asarray(predicted, float)
    ok = np.isfinite(obs) & np.isfinite(pred)
    return float(np.mean(np.abs(obs[ok] - pred[ok]))) if ok.sum() else float("nan")


# --------------------------------------------------------------------------
# Ordinary least squares with honest intervals
# --------------------------------------------------------------------------
@dataclass
class Prediction:
    value: float
    lo: float
    hi: float
    level: float
    leverage: float          # h0 = 1/n + (x0-xbar)^2/Sxx
    extrapolated: bool       # x0 outside the calibration range
    high_leverage: bool      # h0 above 2*(k+1)/n

    def __str__(self) -> str:
        flag = " [EXTRAPOLATED]" if self.extrapolated else ""
        return f"{self.value:,.0f} ({self.level:.0%} PI {self.lo:,.0f}-{self.hi:,.0f}){flag}"


@dataclass
class Fit:
    """A one-predictor least-squares fit and everything needed to judge it."""

    name: str
    x: np.ndarray
    y: np.ndarray
    slope: float
    intercept: float
    n: int
    r2: float                 # in-sample
    adj_r2: float
    loocv_r2: float           # 1 - PRESS/SST; can be negative
    s: float                  # residual standard error, n-2 dof
    se_slope: float
    p_value: float            # two-sided, slope != 0
    rmse: float
    mae: float
    x_mean: float
    sxx: float
    x_min: float
    x_max: float
    log_x: bool = False
    log_y: bool = False
    duan: float = 1.0         # smearing factor for log-y back-transform
    residuals: np.ndarray = field(default_factory=lambda: np.array([]))
    cooks_d: np.ndarray = field(default_factory=lambda: np.array([]))
    y_units: str = ""

    # -- prediction ------------------------------------------------------
    def predict(self, x0: float, level: float = 0.80) -> Prediction:
        if not np.isfinite(x0):
            return Prediction(np.nan, np.nan, np.nan, level, np.nan, False, False)
        xt = np.log(x0) if self.log_x else float(x0)
        yhat = self.intercept + self.slope * xt

        h0 = 1.0 / self.n + (xt - self.x_mean) ** 2 / self.sxx if self.sxx > 0 else np.nan
        tcrit = stats.t.ppf(0.5 + level / 2.0, self.n - 2)
        half = tcrit * self.s * np.sqrt(1.0 + h0)
        lo, hi = yhat - half, yhat + half

        if self.log_y:
            # Duan smearing for the mean; interval bounds are quantiles and
            # back-transform exactly.
            yhat = float(np.exp(yhat) * self.duan)
            lo, hi = float(np.exp(lo)), float(np.exp(hi))

        return Prediction(
            value=float(yhat), lo=float(lo), hi=float(hi), level=level,
            leverage=float(h0),
            extrapolated=bool(xt < self.x_min or xt > self.x_max),
            high_leverage=bool(np.isfinite(h0) and h0 > 4.0 / self.n),
        )

    def line(self, n: int = 100) -> tuple[np.ndarray, np.ndarray]:
        """Fitted line over the calibration range only.

        Plotted fit lines are clipped to the data. Drawing a regression line
        down to SWE = 0 when the data start at 15 inches visually asserts a
        relationship the record cannot support.
        """
        xt = np.linspace(self.x_min, self.x_max, n)
        yt = self.intercept + self.slope * xt
        if self.log_y:
            yt = np.exp(yt) * self.duan
        return (np.exp(xt) if self.log_x else xt), yt

    # -- reporting -------------------------------------------------------
    @property
    def significant(self) -> bool:
        return bool(np.isfinite(self.p_value) and self.p_value < 0.01)

    def summary(self) -> str:
        return (f"n={self.n}  r2={self.r2:.2f}  adj={self.adj_r2:.2f}  "
                f"LOOCV={self.loocv_r2:.2f}  RMSE={self.rmse:,.0f}{self.y_units}  "
                f"p={self.p_value:.4f}")

    @property
    def influential(self) -> np.ndarray:
        """Indices with Cook's distance above the conventional 4/n cutoff."""
        if self.cooks_d.size == 0:
            return np.array([], dtype=int)
        return np.flatnonzero(self.cooks_d > 4.0 / self.n)


def fit_ols(x, y, name: str = "", log_x: bool = False, log_y: bool = False,
            y_units: str = "") -> Fit | None:
    """Least-squares fit of y on x, optionally in log space.

    Returns None if fewer than 4 usable pairs remain.
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    ok = np.isfinite(x) & np.isfinite(y)
    if log_x:
        ok &= x > 0
    if log_y:
        ok &= y > 0
    if ok.sum() < 4:
        return None

    x_raw, y_raw = x[ok], y[ok]
    xt = np.log(x_raw) if log_x else x_raw
    yt = np.log(y_raw) if log_y else y_raw
    n = len(xt)

    lr = stats.linregress(xt, yt)
    resid = yt - (lr.intercept + lr.slope * xt)
    dof = n - 2
    s = float(np.sqrt(np.sum(resid ** 2) / dof)) if dof > 0 else float("nan")

    x_mean = float(np.mean(xt))
    sxx = float(np.sum((xt - x_mean) ** 2))

    # Leave-one-out via the hat-matrix shortcut: no refitting loop needed.
    h = 1.0 / n + (xt - x_mean) ** 2 / sxx if sxx > 0 else np.full(n, np.nan)
    press_resid = resid / (1.0 - h)
    ss_tot = float(np.sum((yt - yt.mean()) ** 2))
    loocv_r2 = (1.0 - float(np.sum(press_resid ** 2)) / ss_tot) if ss_tot > 0 else np.nan

    # Cook's distance, to expose single years that drive a slope.
    mse = float(np.sum(resid ** 2) / dof) if dof > 0 else np.nan
    cooks = (resid ** 2 / (2.0 * mse)) * (h / (1.0 - h) ** 2) if mse > 0 else np.zeros(n)

    r2 = float(lr.rvalue ** 2)
    adj_r2 = 1.0 - (1.0 - r2) * (n - 1) / (n - 2) if n > 2 else np.nan

    # Duan smearing: E[exp(resid)] corrects the retransformation bias that
    # makes exp(yhat) underestimate the mean.
    duan = float(np.mean(np.exp(resid))) if log_y else 1.0

    # Skill scores are reported in the original units, not log units.
    pred_native = lr.intercept + lr.slope * xt
    if log_y:
        pred_native = np.exp(pred_native) * duan

    return Fit(
        name=name, x=x_raw, y=y_raw,
        slope=float(lr.slope), intercept=float(lr.intercept), n=n,
        r2=r2, adj_r2=float(adj_r2), loocv_r2=float(loocv_r2),
        s=s, se_slope=float(lr.stderr), p_value=float(lr.pvalue),
        rmse=rmse(y_raw, pred_native), mae=mae(y_raw, pred_native),
        x_mean=x_mean, sxx=sxx, x_min=float(xt.min()), x_max=float(xt.max()),
        log_x=log_x, log_y=log_y, duan=duan,
        residuals=resid, cooks_d=np.asarray(cooks, dtype=float),
        y_units=y_units,
    )


# --------------------------------------------------------------------------
# Multiple regression (for nested model comparison)
# --------------------------------------------------------------------------
@dataclass
class MultiFit:
    name: str
    coefs: np.ndarray          # [intercept, b1, b2, ...]
    n: int
    k: int                     # number of predictors
    r2: float
    adj_r2: float
    loocv_r2: float
    rmse: float
    predictor_names: tuple[str, ...]

    def summary(self) -> str:
        return (f"n={self.n}  r2={self.r2:.2f}  adj={self.adj_r2:.2f}  "
                f"LOOCV={self.loocv_r2:.2f}  RMSE={self.rmse:,.0f}")


def fit_multi(X, y, predictor_names: tuple[str, ...], name: str = "",
              log_y: bool = False) -> MultiFit | None:
    """Multiple linear regression with leave-one-out skill.

    In-sample r2 can never decrease when a predictor is added, so comparing a
    2-predictor model to a 1-predictor model on r2 alone is meaningless: a
    pure-noise column raises r2 by about 1/(n-2). Adjusted r2 and LOOCV are
    reported so the comparison is real.
    """
    X = np.asarray(X, dtype=float)
    y = np.asarray(y, dtype=float)
    ok = np.isfinite(y) & np.all(np.isfinite(X), axis=1)
    if log_y:
        ok &= y > 0
    if ok.sum() < len(predictor_names) + 3:
        return None
    Xf, yf = X[ok], y[ok]
    yt = np.log(yf) if log_y else yf
    n, k = Xf.shape
    A = np.column_stack([np.ones(n), Xf])

    coefs, *_ = np.linalg.lstsq(A, yt, rcond=None)
    fitted = A @ coefs
    resid = yt - fitted
    ss_tot = float(np.sum((yt - yt.mean()) ** 2))
    r2 = 1.0 - float(np.sum(resid ** 2)) / ss_tot if ss_tot > 0 else np.nan
    adj = 1.0 - (1.0 - r2) * (n - 1) / (n - k - 1) if n > k + 1 else np.nan

    hat = A @ np.linalg.pinv(A.T @ A) @ A.T
    h = np.clip(np.diag(hat), 0, 1 - 1e-9)
    press = resid / (1.0 - h)
    loocv = 1.0 - float(np.sum(press ** 2)) / ss_tot if ss_tot > 0 else np.nan

    pred_native = np.exp(fitted) * float(np.mean(np.exp(resid))) if log_y else fitted
    return MultiFit(name=name, coefs=coefs, n=n, k=k, r2=float(r2),
                    adj_r2=float(adj), loocv_r2=float(loocv),
                    rmse=rmse(yf, pred_native), predictor_names=predictor_names)


# --------------------------------------------------------------------------
# Trend testing
# --------------------------------------------------------------------------
@dataclass
class Trend:
    """Theil-Sen slope with a Mann-Kendall test, autocorrelation-corrected."""

    name: str
    slope: float               # units per year
    intercept: float
    lo: float                  # 95% CI on the slope
    hi: float
    p_value: float             # Hamed-Rao corrected
    p_uncorrected: float
    n: int
    n_effective: float         # after the autocorrelation correction
    units: str = ""

    @property
    def significant(self) -> bool:
        return bool(np.isfinite(self.p_value) and self.p_value < 0.05)

    @property
    def verdict(self) -> str:
        if not np.isfinite(self.p_value):
            return "insufficient data"
        if not self.significant:
            return "not distinguishable from zero"
        return "significant"

    def describe(self) -> str:
        if not np.isfinite(self.slope):
            return f"{self.name}: insufficient data"
        core = (f"{self.slope:+.3g} {self.units}/yr "
                f"(95% CI {self.lo:+.3g} to {self.hi:+.3g}, p={self.p_value:.3f}")
        if self.n_effective < self.n * 0.95:
            core += f", n_eff={self.n_effective:.0f}/{self.n}"
        core += ")"
        if not self.significant:
            core += "  -- NOT SIGNIFICANT"
        return f"{self.name}: {core}"

    def line(self, x: np.ndarray) -> np.ndarray:
        return self.intercept + self.slope * np.asarray(x, dtype=float)


def _hamed_rao_variance(y: np.ndarray, s_var: float) -> tuple[float, float]:
    """Hamed & Rao (1998) variance correction for serial correlation.

    Returns (corrected variance, effective sample size).
    """
    n = len(y)
    if n < 10:
        return s_var, float(n)

    # Autocorrelation of the detrended ranks.
    x = np.arange(n, dtype=float)
    sen = np.median([(y[j] - y[i]) / (x[j] - x[i])
                     for i in range(n - 1) for j in range(i + 1, n)])
    detrended = y - sen * x
    ranks = stats.rankdata(detrended)
    ranks = ranks - ranks.mean()

    denom = float(np.sum(ranks ** 2))
    if denom == 0:
        return s_var, float(n)

    max_lag = n - 3
    rho = np.array([float(np.sum(ranks[:n - k] * ranks[k:])) / denom
                    for k in range(1, max_lag + 1)])

    # Keep only lags significant at 95%, per Hamed & Rao.
    bound = 1.96 / np.sqrt(n)
    rho = np.where(np.abs(rho) > bound, rho, 0.0)

    k = np.arange(1, max_lag + 1, dtype=float)
    terms = (n - k) * (n - k - 1) * (n - k - 2) * rho
    correction = 1.0 + (2.0 / (n * (n - 1) * (n - 2))) * float(np.sum(terms))
    correction = max(correction, 1e-6)
    return s_var * correction, float(n / correction)


def trend(years, values, name: str = "", units: str = "") -> Trend:
    """Theil-Sen slope + Mann-Kendall significance with autocorrelation correction.

    Preferred over ``polyfit`` for annual hydrologic series: it is robust to
    the one or two extreme years that otherwise drag an OLS line, and it comes
    with a significance test. Annual runoff carries ENSO/PDO persistence, so
    the naive test overstates significance; the Hamed-Rao correction inflates
    the variance to match the effective sample size.
    """
    x = np.asarray(years, dtype=float)
    y = np.asarray(values, dtype=float)
    ok = np.isfinite(x) & np.isfinite(y)
    x, y = x[ok], y[ok]
    n = len(x)
    if n < 8:
        return Trend(name, np.nan, np.nan, np.nan, np.nan, np.nan, np.nan,
                     n, float(n), units)

    order = np.argsort(x)
    x, y = x[order], y[order]

    sen = stats.theilslopes(y, x, alpha=0.95)
    slope, intercept, lo, hi = float(sen[0]), float(sen[1]), float(sen[2]), float(sen[3])

    # Mann-Kendall S and its variance, with tie correction.
    s = 0.0
    for i in range(n - 1):
        s += float(np.sum(np.sign(y[i + 1:] - y[i])))
    _, counts = np.unique(y, return_counts=True)
    tie_term = float(np.sum(counts * (counts - 1) * (2 * counts + 5)))
    s_var = (n * (n - 1) * (2 * n + 5) - tie_term) / 18.0

    def _p(var: float) -> float:
        if var <= 0:
            return float("nan")
        if s > 0:
            z = (s - 1) / np.sqrt(var)
        elif s < 0:
            z = (s + 1) / np.sqrt(var)
        else:
            z = 0.0
        return float(2.0 * (1.0 - stats.norm.cdf(abs(z))))

    p_raw = _p(s_var)
    s_var_c, n_eff = _hamed_rao_variance(y, s_var)
    p_corr = _p(s_var_c)

    return Trend(name=name, slope=slope, intercept=intercept, lo=lo, hi=hi,
                 p_value=p_corr, p_uncorrected=p_raw, n=n,
                 n_effective=n_eff, units=units)


# --------------------------------------------------------------------------
# DOY-aligned envelopes
# --------------------------------------------------------------------------
def envelope(matrix, quantiles=(0.25, 0.50, 0.75), min_count: int = 20):
    """Per-row quantiles with a minimum sample-size mask.

    Rows backed by fewer than ``min_count`` years are masked to NaN. Without
    this the envelope narrows or turns jagged wherever the record thins --
    an artefact of sample size that reads as real variability.
    """
    arr = np.asarray(matrix, dtype=float)
    counts = np.sum(np.isfinite(arr), axis=1)
    out = {}
    with np.errstate(all="ignore"):
        for q in quantiles:
            vals = np.nanquantile(arr, q, axis=1)
            vals = np.where(counts >= min_count, vals, np.nan)
            out[q] = vals
    return out, counts
