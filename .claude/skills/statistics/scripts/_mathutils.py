"""Internal math helpers for statistics skill. Pure stdlib — no scipy/numpy."""
from __future__ import annotations
import math


def _norm_cdf(x: float) -> float:
    """Normal CDF via Abramowitz & Stegun 26.2.17 rational approximation.
    Max error < 7.5e-8."""
    p = 0.2316419
    b1, b2, b3, b4, b5 = 0.319381530, -0.356563782, 1.781477937, -1.821255978, 1.330274429
    t = 1.0 / (1.0 + p * abs(x))
    poly = t * (b1 + t * (b2 + t * (b3 + t * (b4 + t * b5))))
    cdf = 1.0 - (1.0 / math.sqrt(2 * math.pi)) * math.exp(-0.5 * x * x) * poly
    return cdf if x >= 0 else 1.0 - cdf


def _norm_ppf(p: float) -> float:
    """Inverse normal CDF via Acklam 2003 rational approximation.
    Max error < 1.15e-9 for p in (0, 1)."""
    a = [-3.969683028665376e+01, 2.209460984245205e+02,
         -2.759285104469687e+02, 1.383577518672690e+02,
         -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02,
         -1.556989798598866e+02, 6.680131188771972e+01,
         -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01,
         -2.400758277161838e+00, -2.549732539343734e+00,
          4.374664141464968e+00,  2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01,
         2.445134137142996e+00, 3.754408661907416e+00]
    p_low, p_high = 0.02425, 1 - 0.02425
    if p < p_low:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
               ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    elif p <= p_high:
        q = p - 0.5
        r = q * q
        return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / \
               (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)
    else:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
                ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)


def _chi2_cdf_wh(x: float, k: float) -> float:
    """Chi-squared CDF via Wilson-Hilferty normal approximation.
    Reasonable for k >= 1, x > 0."""
    if x <= 0:
        return 0.0
    mu = 1 - 2.0 / (9 * k)
    sigma = math.sqrt(2.0 / (9 * k))
    z = ((x / k) ** (1.0 / 3.0) - mu) / sigma
    return _norm_cdf(z)


def _t_cdf(t: float, df: float) -> float:
    """Approximate CDF for t-distribution using normal approximation for large df."""
    if df > 30:
        return _norm_cdf(t)
    # For smaller df, use a better approximation
    try:
        return _norm_cdf(t * (1 - 1 / (4 * df)) ** 0.5)
    except Exception:
        return _norm_cdf(t)
