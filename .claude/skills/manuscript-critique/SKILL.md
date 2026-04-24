---
name: manuscript-critique
description: Gate-enforced four-reviewer critique of a user's manuscript. Each reviewer persona (methodological, theoretical, big-picture, nitpicky) produces structured findings with severity. Fatal findings require a steelman paragraph. Delivers a committed overall verdict.
when_to_use: You have an ingested manuscript and want reviewer-style critique before submitting. Used by the `manuscript-critic` sub-agent.
---

# manuscript-critique

Four distinct lenses, each with its own bias and focus. The gate enforces that you actually applied all four — skipping a persona is the most common failure mode.

## The four reviewers

| Reviewer | Focus |
|---|---|
| **methodological** | stats, controls, sample size, confounders, data integrity |
| **theoretical** | logic, assumptions, circular reasoning, framework coherence |
| **big_picture** | what does this contribute, why now, where does it sit in the field |
| **nitpicky** | writing, figures, missing citations, inconsistent notation |

## What a critique report must contain

```
{
  "manuscript_id": "...",
  "reviewers": {
    "methodological": {
      "findings": [
        {
          "id": "meth-1",
          "severity": "fatal|major|minor",
          "location": "§4 Table 2",
          "issue": "<specific>",
          "suggested_fix": "<actionable>",
          "steelman": "<required when severity=fatal>"
        }
      ],
      "summary": "<one paragraph, no hedging>"
    },
    "theoretical": {...},
    "big_picture": {...},
    "nitpicky": {...}
  },
  "overall_verdict": "accept|borderline|reject",
  "confidence": 0.0-1.0,
  "strongest_finding_id": "<ref>"
}
```

## Agent-facing procedure

1. Read `source.md`. Optionally read `audit_report.json` if an audit ran first — it informs the `nitpicky` reviewer.
2. For each of the four personas, walk the manuscript with *that persona's* lens and nothing else. Do not mix concerns.
3. Record findings with specific `location` (section/paragraph/figure reference). Generic "the paper is unclear" is a non-finding.
4. Severity discipline:
   - **fatal** = paper should not be submitted until fixed. Requires a steelman — the strongest reading under which this is *not* fatal.
   - **major** = would trigger a "major revision" from a careful reviewer
   - **minor** = would be noted but not block acceptance
5. Commit to an overall verdict + confidence. No hedging.
6. Pipe to the gate:

```bash
uv run python .claude/skills/manuscript-critique/scripts/gate.py \
  --input /tmp/critique-report.json \
  --manuscript-id <mid>
```

The gate rejects:
- Missing any of the four reviewer personas
- A reviewer with zero findings AND no explicit summary stating "no issues at this level"
- A `fatal` finding without a steelman
- An overall_verdict not in {accept, borderline, reject}
- A confidence/verdict mismatch (e.g. `accept` with confidence < 0.6)
- Hedge words in summaries

## Principles this enforces

From `RESEARCHER.md`: **4 (Narrate Tension)**, **7 (Commit to a Number)**, **8 (Steelman Before Attack)**.

## Outputs

- `~/.cache/coscientist/manuscripts/<mid>/critique_report.json`
- Rows in `manuscript_critique_findings` — one per finding, indexed by reviewer
- `manifest.state` advances to `critiqued` (or stays if already past)
