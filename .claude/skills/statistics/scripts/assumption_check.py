#!/usr/bin/env python3
"""Flag statistical assumption violations."""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import importlib.util as _ilu

_spec = _ilu.spec_from_file_location("_mathutils", Path(__file__).parent / "_mathutils.py")
_mu = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_mu)
_norm_cdf = _mu._norm_cdf


def check_normality(data: list[float]) -> dict:
    """Heuristic normality check via skewness and kurtosis."""
    n = len(data)
    if n < 3:
        return {"test": "normality", "status": "insufficient_data", "n": n}
    mean = sum(data) / n
    var = sum((x - mean)**2 for x in data) / (n - 1)
    sd = math.sqrt(var) if var > 0 else 0
    skew = _skewness(data, mean, sd, n)
    kurt = _kurtosis(data, mean, sd, n)
    violations = []
    if abs(skew) > 2:
        violations.append(f"skewness={skew:.2f} (|>2| suggests non-normality)")
    if abs(kurt - 3) > 7:
        violations.append(f"excess_kurtosis={kurt-3:.2f} (|>7| suggests non-normality)")
    return {
        "test": "normality",
        "n": n,
        "mean": mean,
        "sd": sd,
        "skewness": skew,
        "excess_kurtosis": kurt - 3,
        "violations": violations,
        "status": "fail" if violations else "pass",
        "note": "Heuristic check (|skew|>2 or |excess kurtosis|>7). For formal test use Shapiro-Wilk.",
    }


def check_variance(groups: list[list[float]]) -> dict:
    """Levene's test approximation using median-based deviations."""
    k = len(groups)
    ns = [len(g) for g in groups]
    N = sum(ns)
    # Use median-based Levene (Brown-Forsythe variant)
    meds = [sorted(g)[n // 2] for g, n in zip(groups, ns)]
    zij = [[abs(x - m) for x in g] for g, m in zip(groups, meds)]
    z_means = [sum(z) / len(z) for z in zij]
    z_grand = sum(sum(z) for z in zij) / N
    ss_between = sum(n * (zm - z_grand)**2 for n, zm in zip(ns, z_means))
    ss_within = sum(sum((z - zm)**2 for z in zg) for zg, zm in zip(zij, z_means))
    if ss_within == 0:
        return {"test": "variance_homogeneity", "status": "pass",
                "note": "All values identical within groups"}
    W = ((N - k) / (k - 1)) * ss_between / ss_within
    violation = W > 4.0
    return {
        "test": "variance_homogeneity",
        "levene_W": W,
        "df_between": k - 1,
        "df_within": N - k,
        "violations": ["Levene W > 4 suggests heterogeneity of variance"] if violation else [],
        "status": "fail" if violation else "pass",
        "note": "W>4 heuristic. For formal test compute p-value from F distribution.",
    }


def check_independence(data: list[float]) -> dict:
    """Durbin-Watson statistic for autocorrelation."""
    n = len(data)
    if n < 4:
        return {"test": "independence", "status": "insufficient_data", "n": n}
    mean = sum(data) / n
    residuals = [x - mean for x in data]
    numerator = sum((residuals[i] - residuals[i-1])**2 for i in range(1, n))
    denominator = sum(r**2 for r in residuals)
    dw = numerator / denominator if denominator > 0 else 2.0
    violations = []
    if dw < 1.5:
        violations.append(f"Durbin-Watson={dw:.2f} (<1.5 suggests positive autocorrelation)")
    elif dw > 2.5:
        violations.append(f"Durbin-Watson={dw:.2f} (>2.5 suggests negative autocorrelation)")
    return {
        "test": "independence",
        "durbin_watson": dw,
        "violations": violations,
        "status": "fail" if violations else "pass",
        "note": "DW heuristic only. Interpret with caution for non-regression contexts.",
    }


def _skewness(data: list[float], mean: float, sd: float, n: int) -> float:
    if sd == 0:
        return 0.0
    return (sum((x - mean)**3 for x in data) / n) / sd**3


def _kurtosis(data: list[float], mean: float, sd: float, n: int) -> float:
    if sd == 0:
        return 3.0
    return (sum((x - mean)**4 for x in data) / n) / sd**4


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--data", type=str, default=None,
                   help="JSON array of numbers, or JSON array of arrays for variance test")
    p.add_argument("--test", required=True,
                   choices=["normality", "variance", "independence"])
    args = p.parse_args()
    raw = json.loads(args.data)
    if args.test == "normality":
        result = check_normality([float(x) for x in raw])
    elif args.test == "variance":
        result = check_variance([[float(x) for x in g] for g in raw])
    elif args.test == "independence":
        result = check_independence([float(x) for x in raw])
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
