---
name: idea-attacker
description: Use when you want an adversarial stress-test of your own hypothesis or idea outside a deep-research run. Harder than rude (which is pipeline-bound). Attacks by name using a structured checklist for early-stage ideas. Writes a machine-readable attack report and can persist it to the project DB.
when_to_use: When the user says "attack this idea", "stress-test my hypothesis", "what's wrong with this", "try to disprove this". Not for finished papers (use attack-vectors + red-team for those).
---

# idea-attacker

Standalone adversarial agent. Takes a free-text hypothesis statement + optional context; attacks it with a named checklist; writes a structured report.

## Scripts

| Script | CLI | Purpose |
|---|---|---|
| `gate.py` | `--input <report.json> [--project-id P] [--hyp-id H]` | Validate + optionally persist attack report |

## Attack checklist (idea-stage, distinct from paper-stage in attack-vectors)

| Attack | What it checks |
|---|---|
| `untestable` | Can this hypothesis be falsified by any feasible experiment? |
| `already-known` | Is this already established? (prior art, textbook knowledge) |
| `confounded-by-design` | Does the proposed method conflate cause and effect by construction? |
| `base-rate-neglect` | Does the hypothesis ignore the prior probability of the effect? |
| `scope-too-broad` | Is the claim too general to survive even one counterexample? |
| `implementation-wall` | Is there a blocking engineering or resource constraint that makes the experiment impossible in practice? |
| `incentive-problem` | Will participants / systems / institutions behave as assumed? |
| `measurement-gap` | Can the key variables actually be measured at the precision required? |
| `wrong-level` | Is the hypothesis pitched at the wrong scale (molecular when it's systemic, systemic when it's molecular)? |
| `status-quo-survives` | Does the null hypothesis (things stay the same) explain the proposed observations equally well? |

## Report schema

```json
{
  "hyp_id": "optional-stable-id",
  "statement": "<hypothesis text>",
  "steelman": "<strongest case for this hypothesis, one paragraph>",
  "attacks": [
    {
      "attack": "<name from checklist>",
      "verdict": "pass | minor | fatal",
      "evidence": "<specific, not generic>",
      "steelman": "<required when verdict=fatal: strongest counter>",
      "killer_test": "<cheapest observation that resolves this attack; required when verdict!=pass>"
    }
  ],
  "weakest_link": "<name of the single attack most likely to kill this idea>",
  "survival": 1,
  "survival_reasoning": "<why this score>"
}
```

`survival` scale:
- 5 = no obvious flaw; ready for experimental design
- 4 = one plausible risk, has a cheap test
- 3 = one major assumption under real tension; test it first
- 2 = prior work strongly suggests this won't work as stated
- 1 = specific blocking constraint makes it nearly unrunnable

## Gate rules (enforced by `gate.py`)

- All 10 attacks present exactly once
- `verdict` ∈ {pass, minor, fatal}
- Every `fatal` has non-empty `steelman` + non-empty `killer_test`
- Every non-`pass` verdict has non-empty `evidence` (no generic "needs more work")
- `survival` is int 1–5
- `weakest_link` names one of the 10 attack keys

## Persistence (optional)

With `--project-id`: writes report to `projects/<pid>/idea_attacks/<hyp_id>.json` and inserts a `journal_entries` row summarising the outcome.

## Storage

```
projects/<project_id>/
  idea_attacks/
    <hyp_id>.json    # attack report
```
