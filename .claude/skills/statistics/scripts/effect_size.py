#!/usr/bin/env python3
"""Effect size computation from summary statistics."""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def cohen_d(m1: float, m2: float, sd1: float, sd2: float, n1: int, n2: int) -> dict:
    sp = math.sqrt(((n1 - 1) * sd1**2 + (n2 - 1) * sd2**2) / (n1 + n2 - 2))
    d = (m1 - m2) / sp
    return {"kind": "cohen_d", "value": d, "pooled_sd": sp,
            "interpretation": _interp_d(abs(d))}


def glass_delta(m1: float, m2: float, sd_control: float) -> dict:
    delta = (m1 - m2) / sd_control
    return {"kind": "glass_delta", "value": delta,
            "interpretation": _interp_d(abs(delta))}


def hedges_g(m1: float, m2: float, sd1: float, sd2: float, n1: int, n2: int) -> dict:
    res = cohen_d(m1, m2, sd1, sd2, n1, n2)
    df = n1 + n2 - 2
    correction = 1 - 3 / (4 * df - 1)
    g = res["value"] * correction
    return {"kind": "hedges_g", "value": g, "correction_factor": correction,
            "interpretation": _interp_d(abs(g))}


def eta_squared(ss_effect: float, ss_total: float) -> dict:
    eta2 = ss_effect / ss_total
    return {"kind": "eta_squared", "value": eta2,
            "interpretation": _interp_eta(eta2)}


def omega_squared(ss_effect: float, ss_error: float, df_effect: int,
                  ms_error: float) -> dict:
    omega2 = (ss_effect - df_effect * ms_error) / (ss_effect + ss_error + ms_error)
    return {"kind": "omega_squared", "value": omega2,
            "interpretation": _interp_eta(omega2)}


def cramers_v(chi2: float, n: int, min_dim: int) -> dict:
    v = math.sqrt(chi2 / (n * (min_dim - 1)))
    return {"kind": "cramers_v", "value": v,
            "interpretation": _interp_v(v)}


def _interp_d(d: float) -> str:
    if d < 0.2: return "negligible"
    if d < 0.5: return "small"
    if d < 0.8: return "medium"
    return "large"


def _interp_eta(e: float) -> str:
    if e < 0.01: return "negligible"
    if e < 0.06: return "small"
    if e < 0.14: return "medium"
    return "large"


def _interp_v(v: float) -> str:
    if v < 0.1: return "negligible"
    if v < 0.3: return "small"
    if v < 0.5: return "medium"
    return "large"


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--kind", required=True,
                   choices=["cohen_d", "glass_delta", "hedges_g",
                            "eta_squared", "omega_squared", "cramers_v"])
    p.add_argument("--m1", type=float, default=None)
    p.add_argument("--m2", type=float, default=None)
    p.add_argument("--sd1", type=float, default=None)
    p.add_argument("--sd2", type=float, default=None)
    p.add_argument("--n1", type=int, default=None)
    p.add_argument("--n2", type=int, default=None)
    p.add_argument("--sd-control", type=float, default=None)
    p.add_argument("--ss-effect", type=float, default=None)
    p.add_argument("--ss-total", type=float, default=None)
    p.add_argument("--ss-error", type=float, default=None)
    p.add_argument("--df-effect", type=int, default=None)
    p.add_argument("--ms-error", type=float, default=None)
    p.add_argument("--chi2", type=float, default=None)
    p.add_argument("--n", type=int, default=None)
    p.add_argument("--min-dim", type=int, default=None)
    args = p.parse_args()

    kind = args.kind
    try:
        if kind == "cohen_d":
            result = cohen_d(args.m1, args.m2, args.sd1, args.sd2, args.n1, args.n2)
        elif kind == "glass_delta":
            result = glass_delta(args.m1, args.m2, args.sd_control)
        elif kind == "hedges_g":
            result = hedges_g(args.m1, args.m2, args.sd1, args.sd2, args.n1, args.n2)
        elif kind == "eta_squared":
            result = eta_squared(args.ss_effect, args.ss_total)
        elif kind == "omega_squared":
            result = omega_squared(args.ss_effect, args.ss_error, args.df_effect, args.ms_error)
        elif kind == "cramers_v":
            result = cramers_v(args.chi2, args.n, args.min_dim)
    except (TypeError, ValueError) as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
