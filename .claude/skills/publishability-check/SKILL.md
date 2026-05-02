---
name: publishability-check
description: Gate-enforced publishability verdict. For each target venue, requires a committed probability, three factors that most move the verdict, and a declared kill criterion. Rejects hedge words and missing kill criteria. Used by the `publishability-judge` sub-agent.
when_to_use: A sub-agent is about to advise whether a manuscript is publishable at a given venue or list of venues. Run this gate first — it will refuse a verdict that lacks probabilities, factors, or a kill criterion.
---

# publishability-check

A discipline layer. It does not decide publishability — it refuses un-committed verdicts and structures the ones that pass.

## What a publishability verdict must contain

Per target venue:

```
venue: NeurIPS 2026
verdict: accept | reject | borderline-with-revisions
probability_of_acceptance: 0.0-1.0      # committed number
factors_up: [ {factor: "...", weight: -1..+1}, ... ]   # ≥ 3
factors_down: [ {factor: "...", weight: -1..+1}, ... ] # ≥ 3
kill_criterion: "<specific observation that would flip this verdict>"
tier_up_requirements: "<what would need to change to recommend a higher-tier venue>"
reasoning: "<short, specific, no hedge words>"
```

## Agent-facing procedure

1. Read the novelty assessment (output of `novelty-check`) — it's required input.
2. Read the attack-vector findings (output of `attack-vectors`) if available.
3. For each target venue, evaluate novelty + significance + methodology + scope + execution against that venue's rubric. Use a reference calibration set if the user has one under `~/.cache/coscientist/calibration/`.
4. For each venue, commit to a probability. List ≥3 factors pushing up and ≥3 pushing down, each with a signed weight.
5. Declare a kill criterion — a specific observation that would flip the verdict. Write it *before* finalizing the probability.
6. Emit JSON and pipe to the gate:

```bash
uv run python .claude/skills/publishability-check/scripts/gate.py \
  --input /tmp/publish-report.json \
  --target-manuscript-id <mid>
```

The gate exits non-zero if:
- Any venue lacks a probability number
- Any venue has fewer than 3 up-factors or 3 down-factors
- Any kill criterion is missing or vague ("if it's bad", "depends on reviewers")
- Reasoning contains hedge words ("may", "could potentially", "seems to")
- Probability is inconsistent with the verdict (e.g., `verdict=accept` with `p=0.3`)

## Principles this enforces

From `RESEARCHER.md`: **7 (Commit to a Number)**, **9 (Premortem)**, **10 (Kill Criteria)**, **8 (Steelman — the strongest case for publishability must be made before attacking)**.

## Calibration anchors (optional but recommended)

The user can maintain a calibration set at `~/.cache/coscientist/calibration/venues/<venue-slug>.json`:

```json
{
  "venue": "NeurIPS 2024",
  "accepted": [{"title": "...", "reasons_for_accept": [...]}, ...],
  "rejected": [{"title": "...", "reasons_for_reject": [...]}, ...],
  "borderline": [...]
}
```

When present, the gate will append a calibration-drift warning if the verdict's reasoning doesn't reference any case from the set. The warning does not block — it nudges.

## CLI flag reference (drift coverage)

- `gate.py`: `--allow-uncalibrated`
