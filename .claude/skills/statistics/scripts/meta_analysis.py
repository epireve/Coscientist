#!/usr/bin/env python3
"""Fixed/random-effects meta-analysis."""
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


def fixed_effects(studies: list[dict]) -> dict:
    """DerSimonian-Laird fixed effects."""
    yi = [s["effect"] for s in studies]
    vi = [s["variance"] for s in studies]
    wi = [1 / v for v in vi]
    W = sum(wi)
    theta = sum(w * y for w, y in zip(wi, yi)) / W
    var_theta = 1 / W
    se = math.sqrt(var_theta)
    z = theta / se
    p = 2 * (1 - _norm_cdf(abs(z)))
    ci_lo = theta - 1.96 * se
    ci_hi = theta + 1.96 * se
    Q = sum(w * (y - theta)**2 for w, y in zip(wi, yi))
    k = len(studies)
    return {
        "method": "fixed",
        "pooled_effect": theta,
        "se": se,
        "ci_95": [ci_lo, ci_hi],
        "z": z,
        "p_value": p,
        "Q": Q,
        "df": k - 1,
        "I2": max(0.0, (Q - (k - 1)) / Q) if Q > 0 else 0.0,
        "k": k,
    }


def random_effects(studies: list[dict]) -> dict:
    """DerSimonian-Laird random effects."""
    yi = [s["effect"] for s in studies]
    vi = [s["variance"] for s in studies]
    wi = [1 / v for v in vi]
    W = sum(wi)
    W2 = sum(w**2 for w in wi)
    theta_fe = sum(w * y for w, y in zip(wi, yi)) / W
    Q = sum(w * (y - theta_fe)**2 for w, y in zip(wi, yi))
    k = len(studies)
    c = W - W2 / W
    tau2 = max(0.0, (Q - (k - 1)) / c)
    wi_re = [1 / (v + tau2) for v in vi]
    W_re = sum(wi_re)
    theta = sum(w * y for w, y in zip(wi_re, yi)) / W_re
    var_theta = 1 / W_re
    se = math.sqrt(var_theta)
    z = theta / se
    p = 2 * (1 - _norm_cdf(abs(z)))
    ci_lo = theta - 1.96 * se
    ci_hi = theta + 1.96 * se
    I2 = max(0.0, (Q - (k - 1)) / Q) if Q > 0 else 0.0
    return {
        "method": "random",
        "pooled_effect": theta,
        "se": se,
        "ci_95": [ci_lo, ci_hi],
        "z": z,
        "p_value": p,
        "Q": Q,
        "df": k - 1,
        "I2": I2,
        "tau2": tau2,
        "k": k,
        "heterogeneity": "low" if I2 < 0.25 else "moderate" if I2 < 0.75 else "high",
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True,
                   help="JSON file with list of {effect, variance, label?}")
    p.add_argument("--method", default="random", choices=["fixed", "random"])
    args = p.parse_args()
    studies = json.loads(Path(args.input).read_text())
    if args.method == "fixed":
        result = fixed_effects(studies)
    else:
        result = random_effects(studies)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
