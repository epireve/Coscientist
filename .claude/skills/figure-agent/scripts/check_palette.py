#!/usr/bin/env python3
"""Check colorblind safety of an image or color list."""
from __future__ import annotations
import argparse, json, math, sys
from pathlib import Path
from typing import Sequence

_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Machado 2009 deuteranopia matrix (linear RGB)
DEUTERANOPIA = [
    [0.625, 0.375, 0.000],
    [0.700, 0.300, 0.000],
    [0.000, 0.300, 0.700],
]

# Machado 2009 protanopia matrix (linear RGB)
PROTANOPIA = [
    [0.567, 0.433, 0.000],
    [0.558, 0.442, 0.000],
    [0.000, 0.242, 0.758],
]

DELTA_E_THRESHOLD = 40.0


def _srgb_to_linear(c: float) -> float:
    c = max(0.0, min(1.0, c))
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _linear_to_srgb(c: float) -> float:
    c = max(0.0, min(1.0, c))
    return c * 12.92 if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055


def _apply_matrix(rgb: list[float], mat: list[list[float]]) -> list[float]:
    return [
        sum(mat[i][j] * rgb[j] for j in range(3))
        for i in range(3)
    ]


def _rgb_to_lab(rgb_srgb: list[float]) -> list[float]:
    """sRGB -> CIE Lab (D65 illuminant)."""
    lin = [_srgb_to_linear(c) for c in rgb_srgb]
    # sRGB to XYZ (D65)
    x = lin[0] * 0.4124564 + lin[1] * 0.3575761 + lin[2] * 0.1804375
    y = lin[0] * 0.2126729 + lin[1] * 0.7151522 + lin[2] * 0.0721750
    z = lin[0] * 0.0193339 + lin[1] * 0.1191920 + lin[2] * 0.9503041
    # Normalize by D65 white point
    xn, yn, zn = 0.95047, 1.00000, 1.08883
    def f(t):
        return t ** (1/3) if t > 0.008856 else 7.787 * t + 16/116
    fx, fy, fz = f(x / xn), f(y / yn), f(z / zn)
    L = 116 * fy - 16
    a = 500 * (fx - fy)
    b = 200 * (fy - fz)
    return [L, a, b]


def _delta_e_76(lab1: list[float], lab2: list[float]) -> float:
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(lab1, lab2)))


def simulate_color(rgb_srgb: list[float], deficiency: str) -> list[float]:
    """Simulate colorblind perception. rgb_srgb values in [0, 1]."""
    mat = DEUTERANOPIA if deficiency == "deuteranopia" else PROTANOPIA
    lin = [_srgb_to_linear(c) for c in rgb_srgb]
    sim_lin = _apply_matrix(lin, mat)
    return [_linear_to_srgb(c) for c in sim_lin]


def check_palette(colors: list[list[float]]) -> dict:
    """
    Check a list of colors (each [R, G, B] in 0-1) for colorblind safety.
    Returns warnings for pairs whose delta-E drops below threshold under simulation.
    """
    warnings = []
    for deficiency in ["deuteranopia", "protanopia"]:
        sim_colors = [simulate_color(c, deficiency) for c in colors]
        for i in range(len(colors)):
            for j in range(i + 1, len(colors)):
                de_orig = _delta_e_76(_rgb_to_lab(colors[i]), _rgb_to_lab(colors[j]))
                de_sim = _delta_e_76(_rgb_to_lab(sim_colors[i]), _rgb_to_lab(sim_colors[j]))
                if de_sim < DELTA_E_THRESHOLD and de_orig >= DELTA_E_THRESHOLD:
                    warnings.append({
                        "deficiency": deficiency,
                        "color_pair": [i, j],
                        "delta_e_original": round(de_orig, 2),
                        "delta_e_simulated": round(de_sim, 2),
                        "message": (
                            f"Colors {i} and {j} become hard to distinguish under "
                            f"{deficiency} (dE {de_sim:.1f} < {DELTA_E_THRESHOLD})"
                        ),
                    })
    return {
        "n_colors": len(colors),
        "warnings": warnings,
        "status": "fail" if warnings else "pass",
        "threshold": DELTA_E_THRESHOLD,
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--colors", type=str, required=True,
                   help="JSON array of [R,G,B] lists with values in 0-1")
    args = p.parse_args()
    colors = json.loads(args.colors)
    result = check_palette(colors)
    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    main()
