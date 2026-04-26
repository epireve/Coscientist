---
name: experiment-design
description: Design experiments with Karpathy-style discipline — single comparable metric, fixed compute budget, explicit hypothesis + falsifier. Pre-register protocols before running. Stores under experiments/<eid>/ as `experiment` artifact (state machine designed → preregistered → running → completed → analyzed → reproduced). Pairs with future reproducibility-mcp (v0.34) and registered-reports (v0.32) for full pre-registration.
when_to_use: User says "design experiment", "preregister", "experiment protocol", "what's the metric". Before running any experiment that should be reproducible.
---

# experiment-design

Karpathy-style experiment scaffold. Forces:
- **One** primary metric (scalar, comparable across runs)
- **Fixed** compute budget (seconds + memory cap)
- **Explicit** hypothesis + falsifier
- **Preregistered** before any data collection

## Scripts

| Script | Subcommand | Purpose |
|---|---|---|
| `design.py` | `init` | Create experiment artifact + protocol skeleton |
| | `variable` | Add independent / dependent / control variable |
| | `metric` | Set primary metric (one only — replaces if called twice) |
| | `preregister` | Validate protocol completeness; advance state to `preregistered`; optional link to RR |
| | `status` | Show protocol fields + completeness |
| | `list` | List experiments by state / project |

## Subcommands

```
design.py init --title "T" --hypothesis "H" --falsifier "F" [--project-id P]
design.py variable --experiment-id E --kind independent|dependent|control --name "x" --description "..."
design.py metric --experiment-id E --name "accuracy" --type scalar --target 0.85 --comparison ">="
design.py preregister --experiment-id E [--rr-id RR] [--budget-seconds 3600] [--memory-mb 4096]
design.py status --experiment-id E
design.py list [--project-id P] [--state STATE]
```

## Protocol schema (`protocol.json`)

```json
{
  "experiment_id": "test_acc_abc123",
  "title": "Test accuracy of method X on dataset Y",
  "hypothesis": "Method X achieves >=85% accuracy on dataset Y",
  "falsifier": "Method X achieves <70% accuracy on dataset Y (3 independent runs)",
  "variables": {
    "independent": [{"name": "method", "description": "X vs baseline"}],
    "dependent":   [{"name": "accuracy", "description": "Top-1 accuracy"}],
    "control":     [{"name": "seed", "description": "Random seed; held at 42"}]
  },
  "primary_metric": {
    "name": "accuracy",
    "type": "scalar",
    "target": 0.85,
    "comparison": ">="
  },
  "budget": {
    "compute_seconds": 3600,
    "memory_mb": 4096
  },
  "preregistration": {
    "preregistered_at": "2026-04-27T10:00:00+00:00",
    "rr_id": "optional-rr-id-link",
    "preregistration_path": "experiments/<eid>/preregistration.md"
  },
  "deviations": []
}
```

## Gates enforced by `preregister`

- ≥1 hypothesis (non-empty)
- ≥1 falsifier (non-empty, *not* the same text as hypothesis)
- ≥1 independent variable
- ≥1 dependent variable
- Exactly 1 primary metric set
- `budget.compute_seconds > 0` and `budget.memory_mb > 0`
- State must be `designed` (no re-preregistering without `--force`)

If `--rr-id` given, the linked Registered Report must be in state `stage-1-drafted` or later.

## Storage

```
experiments/<eid>/
  manifest.json
  protocol.json
  preregistration.md   # human-readable Stage 1 protocol (after preregister)
```

`eid` = `slug(title)_<6-char blake2s hash>`.

## Why these gates

From `RESEARCHER.md` principle 9 (Premortem) + 10 (Kill Criteria) + Karpathy's "fixed compute, single metric, comparable across iterations". The skill refuses to advance state without all four discipline elements present.

## What this skill does NOT do

- Doesn't run experiments — that's `experiment-reproduce` + `reproducibility-mcp` (v0.34/v0.35)
- Doesn't analyze results — that's a future skill
- Doesn't replace `registered-reports` — but can link to it via `--rr-id`
