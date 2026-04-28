#!/usr/bin/env python3
"""Recommend statistical test based on study design."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Rule tuple: (outcome, max_groups, paired, n_small, test_name, rationale)
RULES = [
    ("continuous", 2, True,  False, "paired_t",      "Two related samples, continuous — paired t-test."),
    ("continuous", 2, True,  True,  "wilcoxon",      "Two related samples, small n — Wilcoxon signed-rank."),
    ("continuous", 2, False, False, "independent_t", "Two independent groups, continuous — independent t-test."),
    ("continuous", 2, False, True,  "mann_whitney",  "Two independent groups, small n — Mann-Whitney U."),
    ("continuous", 3, False, False, "one_way_anova", "Three+ groups, continuous — one-way ANOVA."),
    ("continuous", 3, True,  False, "repeated_anova","Three+ related groups — repeated-measures ANOVA."),
    ("ordinal",    2, True,  False, "wilcoxon",      "Ordinal outcome, paired — Wilcoxon signed-rank."),
    ("ordinal",    2, False, False, "mann_whitney",  "Ordinal outcome, two groups — Mann-Whitney U."),
    ("ordinal",    3, False, False, "kruskal_wallis","Ordinal outcome, 3+ groups — Kruskal-Wallis."),
    ("binary",     2, False, False, "chi_squared",   "Binary outcome, two groups — chi-squared (or Fisher if expected < 5)."),
    ("binary",     2, True,  False, "mcnemar",       "Binary outcome, paired — McNemar's test."),
    ("count",      2, False, False, "poisson_reg",   "Count outcome — Poisson regression or negative binomial."),
]


def recommend(n: int, groups: int, paired: bool, outcome: str) -> dict:
    n_small = n < 30
    matches = []
    for r in RULES:
        r_outcome, r_max_groups, r_paired, r_n_small, test, rationale = r
        if r_outcome == outcome and r_max_groups >= groups and r_paired == paired and r_n_small == n_small:
            matches.append({"test": test, "rationale": rationale})
    if not matches:
        # Try without n_small constraint
        for r in RULES:
            r_outcome, r_max_groups, r_paired, r_n_small, test, rationale = r
            if r_outcome == outcome and r_max_groups >= groups and r_paired == paired:
                matches.append({"test": test, "rationale": rationale})
    if not matches:
        matches = [{"test": "consult_statistician",
                    "rationale": "No rule matched — consult a statistician."}]
    primary = matches[0]
    assumptions = _assumptions(primary["test"])
    return {
        "recommended_test": primary["test"],
        "rationale": primary["rationale"],
        "assumptions": assumptions,
        "alternatives": [m for m in matches[1:]],
        "inputs": {"n": n, "groups": groups, "paired": paired, "outcome": outcome},
    }


def _assumptions(test: str) -> list[str]:
    MAP = {
        "independent_t": ["normality (or n>=30 by CLT)", "homogeneity of variance", "independence"],
        "paired_t": ["normality of differences (or n>=30)", "independence of pairs"],
        "one_way_anova": ["normality per group (or n>=30)", "homogeneity of variance", "independence"],
        "chi_squared": ["expected cell counts >= 5", "independence of observations"],
        "mann_whitney": ["ordinal or continuous outcome", "independence"],
        "wilcoxon": ["symmetry of differences (for location test)"],
        "kruskal_wallis": ["independence", "ordinal or continuous outcome"],
        "mcnemar": ["matched pairs", "binary outcome"],
        "repeated_anova": ["sphericity", "normality of residuals"],
        "poisson_reg": ["counts non-negative", "mean ~ variance (equidispersion)"],
    }
    return MAP.get(test, [])


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--n", type=int, required=True)
    p.add_argument("--groups", type=int, default=2)
    p.add_argument("--paired", action="store_true", default=False)
    p.add_argument("--outcome", required=True,
                   choices=["continuous", "ordinal", "binary", "count"])
    args = p.parse_args()
    result = recommend(args.n, args.groups, args.paired, args.outcome)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
