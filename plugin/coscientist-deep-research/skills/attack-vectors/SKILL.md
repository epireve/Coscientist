---
name: attack-vectors
description: Runs a checklist of named adversarial attacks against a paper or manuscript — p-hacking, HARKing, selective baselines, missing controls, underpowered, circular reasoning, oversold deltas, irreproducibility. Each attack returns either "pass", "minor", or "fatal" with evidence. Used by the `red-team` sub-agent.
when_to_use: A sub-agent is about to emit a critique. Run this first to replace generic objections with specific, named attack findings.
---

# attack-vectors

Generic critique is cheap. Named attacks are useful. This skill runs a structured checklist of known methodological failure modes and produces an attack log with severity per attack.

## The checklist

| # | Attack | What it catches | Evidence required |
|---|---|---|---|
| 1 | p-hacking | Multiple comparisons without correction; unexplained p-values clustered near 0.05 | Report must show correction (Bonferroni, FDR, pre-registration); OR suspicious p-value distribution |
| 2 | HARKing | Hypothesizing After Results Known — hypothesis framed to match findings | Pre-registration present? Hypotheses in intro match exploratory analyses? |
| 3 | Selective baselines | Compared only to weak baselines; SOTA baseline omitted | List of baselines actually used vs. current literature's strong baselines |
| 4 | Missing controls | No negative control, no ablation, no placebo condition | Controls section present and adequate for the claim |
| 5 | Confounders | Known confounding variables not measured or controlled | Methods section addresses the obvious confounders for this domain |
| 6 | Underpowered | Sample size too small to detect claimed effect | Power analysis reported; OR n justified by pre-specified criterion |
| 7 | Circular reasoning | Evaluation uses training data, or defines the outcome in terms of the predictor | Data splits explicit; outcome and predictor independent |
| 8 | Oversold delta | Abstract claims larger improvement than tables show | Abstract numbers match table numbers; headline claim within CI |
| 9 | Irreproducibility | No code, no data, insufficient method detail | Code link valid? Data available? Hyperparameters complete? |
| 10 | Cherry-picked test set | Performance on one favorable test set generalized | Multiple datasets tested, or one dataset explicitly justified |
| 11 | Inappropriate statistics | Wrong test for the data distribution or sample size | Test matches data type; assumptions checked |
| 12 | Goodhart's law | Optimizes a metric that doesn't capture the stated goal | Metric discussed as a proxy; secondary metrics reported |

Add more attacks per domain. Keep the checklist small and sharp, not comprehensive-but-useless.

## Agent-facing procedure

1. Read the target paper's `content.md` + `metadata.json` + any `figures/`, `tables/`, `equations.json`.
2. Walk the checklist. For each attack, render a verdict: `pass`, `minor`, or `fatal`, with one-sentence evidence.
3. For `fatal` findings, steelman the paper first — is there a reading under which this isn't a fatal flaw? If yes, demote to `minor`.
4. Emit JSON; pipe to the checker:

```bash
uv run python .claude/skills/attack-vectors/scripts/check.py \
  --input /tmp/attack-findings.json \
  --target-canonical-id <cid>
```

The checker validates structure and writes the attack log to the paper's artifact under `attack_findings.json`. On fatal findings, it logs a row in the `attack_findings` table with `severity='fatal'`.

## Principles this enforces

From `RESEARCHER.md`: **4 (Tension, not fake consensus)**, **8 (Steelman before attack)**.

## What this skill does NOT do

- Does not judge overall publishability (that's `publishability-check`)
- Does not assess novelty (that's `novelty-check`)
- Does not produce critique prose — it produces a structured finding list the `red-team` sub-agent turns into a review
