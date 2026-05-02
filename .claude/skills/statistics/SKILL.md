---
name: statistics
description: Statistical computation helpers — effect sizes, power analysis, meta-analysis, test selection, assumption checking. Pure stdlib Python, no scipy/numpy/pandas.
when_to_use: When a sub-agent or manuscript workflow needs effect sizes, sample size estimates, or heterogeneity stats for a meta-analysis. Also used by manuscript-auditor to flag underpowered claims.
---

# statistics

Pure-stdlib statistical primitives designed to run inside any sub-agent context.

## Scripts

| Script | CLI | Purpose |
|---|---|---|
| `effect_size.py` | `--kind cohen_d\|glass_delta\|hedges_g\|eta_squared\|omega_squared\|cramers_v` | Compute effect size from summary stats |
| `power.py` | `--test t\|z\|chi2\|anova --effect-size N --alpha N --power N` | Solve for missing arg (n, power, or alpha) |
| `meta_analysis.py` | `--input studies.json --method fixed\|random` | Fixed/random-effects meta-analysis |
| `test_select.py` | `--n N --groups N --paired --outcome continuous\|ordinal\|binary\|count` | Recommend appropriate test |
| `assumption_check.py` | `--data '[1,2,3...]' --test normality\|variance\|independence` | Flag assumption violations |

## Shared math

`_mathutils.py` — internal module (not CLI). Provides:
- `_norm_cdf(x)` — Abramowitz & Stegun 26.2.17 rational approximation
- `_norm_ppf(p)` — Acklam 2003 rational approximation
- `_chi2_cdf_wh(x, k)` — Wilson-Hilferty normal approximation

## Effect-size flag reference (v0.208 drift sweep)

`effect_size.py --kind <kind>` accepts these stat-input flags depending on kind:

- **cohen_d / glass_delta / hedges_g** (continuous, two groups):
  `--m1`, `--m2`, `--sd1`, `--sd2`, `--n1`, `--n2`, `--sd-control` (Glass)
- **eta_squared / omega_squared** (ANOVA):
  `--ss-effect`, `--ss-error`, `--ss-total`, `--df-effect`, `--ms-error`
- **cramers_v** (chi-square):
  `--chi2`, `--n` (total sample), `--min-dim` (min(rows,cols))
