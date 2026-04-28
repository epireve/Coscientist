#!/usr/bin/env python3
"""Power analysis — solve for n, power, or alpha."""
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
_norm_ppf = _mu._norm_ppf
_chi2_cdf_wh = _mu._chi2_cdf_wh


def _power_t(n: int, effect_size: float, alpha: float, tails: int = 2) -> float:
    """Two-sample t-test power approximation."""
    z_alpha = _norm_ppf(1 - alpha / tails)
    ncp = effect_size * math.sqrt(n / 2)
    return _norm_cdf(ncp - z_alpha) + _norm_cdf(-ncp - z_alpha)


def _power_z(n: int, effect_size: float, alpha: float, tails: int = 2) -> float:
    z_alpha = _norm_ppf(1 - alpha / tails)
    ncp = effect_size * math.sqrt(n)
    return _norm_cdf(ncp - z_alpha) + _norm_cdf(-ncp - z_alpha)


def _power_chi2(n: int, effect_size: float, alpha: float, df: int = 1) -> float:
    """Chi-squared test power via non-central approximation."""
    # Find critical value by bisection
    lo, hi = 0.0, 200.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if _chi2_cdf_wh(mid, df) < 1 - alpha:
            lo = mid
        else:
            hi = mid
    crit = (lo + hi) / 2
    ncp = n * effect_size ** 2
    # Power = P(chi2(df, ncp) > crit) using shift approximation
    shifted = crit - ncp
    if shifted <= 0:
        return 1.0
    return 1 - _chi2_cdf_wh(shifted, df)


def _power_anova(n_per_group: int, effect_size: float, alpha: float,
                 k: int = 2) -> float:
    """One-way ANOVA power via F approximation."""
    ncp = n_per_group * k * effect_size ** 2
    df_between = k - 1
    df_within = k * (n_per_group - 1)

    def f_cdf_approx(x):
        if x <= 0:
            return 0.0
        z = ((x / (df_between / df_within)) ** (1 / 3) *
             (1 - 2 / (9 * df_within)) - (1 - 2 / (9 * df_between))) / \
            math.sqrt(2 / (9 * df_within) + 2 / (9 * df_between))
        return _norm_cdf(z)

    # Find critical F by bisection
    lo, hi = 0.0, 50.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if f_cdf_approx(mid) < 1 - alpha:
            lo = mid
        else:
            hi = mid
    f_crit = (lo + hi) / 2
    # Power via non-central F approximation
    power = 1.0 - f_cdf_approx(f_crit * df_between / (df_between + ncp))
    return max(0.0, min(1.0, power))


POWER_FN = {
    "t": _power_t,
    "z": _power_z,
    "chi2": _power_chi2,
    "anova": _power_anova,
}


def solve_n(test: str, effect_size: float, alpha: float, power: float,
            **kwargs) -> dict:
    fn = POWER_FN[test]
    lo, hi = 2, 100_000
    for _ in range(50):
        mid = (lo + hi) // 2
        p = fn(mid, effect_size, alpha, **kwargs)
        if p < power:
            lo = mid
        else:
            hi = mid
    n = hi
    actual_power = fn(n, effect_size, alpha, **kwargs)
    return {"solve_for": "n", "n": n, "actual_power": actual_power,
            "effect_size": effect_size, "alpha": alpha, "target_power": power,
            "test": test}


def solve_power(test: str, n: int, effect_size: float, alpha: float,
                **kwargs) -> dict:
    fn = POWER_FN[test]
    power = fn(n, effect_size, alpha, **kwargs)
    return {"solve_for": "power", "power": power,
            "n": n, "effect_size": effect_size, "alpha": alpha, "test": test}


def solve_alpha(test: str, n: int, effect_size: float, power: float,
                **kwargs) -> dict:
    """Find alpha such that power function equals target power.
    Power increases as alpha increases (more liberal), so bisect accordingly."""
    fn = POWER_FN[test]
    lo, hi = 1e-6, 0.5
    for _ in range(60):
        mid = (lo + hi) / 2
        p = fn(n, effect_size, mid, **kwargs)
        if p < power:
            # Need more power → increase alpha
            lo = mid
        else:
            # Too much power → decrease alpha
            hi = mid
    alpha = (lo + hi) / 2
    return {"solve_for": "alpha", "alpha": alpha,
            "n": n, "effect_size": effect_size, "target_power": power, "test": test}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--test", required=True, choices=["t", "z", "chi2", "anova"])
    p.add_argument("--effect-size", type=float, default=None)
    p.add_argument("--alpha", type=float, default=None)
    p.add_argument("--power", type=float, default=None)
    p.add_argument("--n", type=int, default=None)
    p.add_argument("--groups", type=int, default=2)
    args = p.parse_args()

    kwargs = {}
    if args.test == "anova":
        kwargs["k"] = args.groups

    missing = [x for x in [args.effect_size, args.alpha, args.power, args.n]
               if x is None]
    if len(missing) != 1:
        print(json.dumps({"error": "exactly one of --effect-size/--alpha/--power/--n must be omitted"}),
              file=sys.stderr)
        sys.exit(1)

    if args.n is None:
        result = solve_n(args.test, args.effect_size, args.alpha, args.power, **kwargs)
    elif args.power is None:
        result = solve_power(args.test, args.n, args.effect_size, args.alpha, **kwargs)
    elif args.alpha is None:
        result = solve_alpha(args.test, args.n, args.effect_size, args.power, **kwargs)
    else:
        print(json.dumps({"error": "cannot solve for effect-size yet"}), file=sys.stderr)
        sys.exit(1)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
