---
name: novelty-check
description: Gate-enforced novelty assessment. Decomposes a paper or manuscript's claimed contributions into `(claim, method, domain, finding, metric)` tuples, requires ≥5 specific prior-work anchors per contribution, and produces a novelty matrix per contribution with delta-sufficiency verdicts. Used by the `novelty-auditor` sub-agent.
when_to_use: A sub-agent (typically `novelty-auditor`) is about to assert that a paper, contribution, or hypothesis is novel. Run this first — it will refuse the verdict if the structure is thin.
---

# novelty-check

A discipline layer, not a judgment layer. It does not decide whether something is novel — it refuses un-grounded novelty claims and structures the ones that pass.

## What a novelty verdict must contain (the structure)

For each contribution the paper asserts:

```
contribution:
  id: contrib-1
  claim: "<verbatim from abstract/intro>"
  decomposition:
    method: "<what technique>"
    domain: "<what object/population>"
    finding: "<what was shown>"
    metric: "<what was measured>"
  anchors:                               # ≥ 5 required
    - canonical_id: <cid>
      closest_aspect: method|domain|finding|metric|scale
      delta: "<what's different in this paper>"
      delta_sufficient: true|false
  verdict: novel | incremental | not-novel
  confidence: 0.0-1.0
  reasoning: "<short, specific>"
```

A verdict without this shape is disqualified.

## Agent-facing procedure

1. For each contribution the target paper claims, build the decomposition tuple.
2. Search adjacent prior work to fill `anchors`. Use `semantic-scholar` citation/reference walks + `paper-search` for non-indexed sources.
3. For each anchor, state the delta in one sentence. Mark `delta_sufficient` per delta — is the delta large enough to count as novel *for this venue*?
4. Commit to a verdict per contribution with a confidence number.
5. Emit the full structure as JSON and pipe to the gate:

```bash
uv run python .claude/skills/novelty-check/scripts/gate.py \
  --input /tmp/novelty-report.json \
  --target-canonical-id <cid-of-paper-under-review>
```

The gate exits non-zero if:
- Any contribution has fewer than 5 anchors
- Any verdict is `novel` but all `delta_sufficient` are `false`
- Any verdict is a hedge word ("maybe", "potentially", "could be")
- Confidence is missing

On pass, the report is written to the paper's artifact under `novelty_assessment.json` and a row is inserted into `novelty_assessments`.

## Principles this enforces

From `RESEARCHER.md`: **6 (Name Five)**, **7 (Commit to a Number)**, **9 (Premortem — each contribution's verdict is challenged)**.

## What this skill does NOT do

- Does not synthesize the paper — it assumes you've already read it
- Does not produce a publishability verdict (that's `publishability-check`)
- Does not run attack vectors (that's `attack-vectors`)
