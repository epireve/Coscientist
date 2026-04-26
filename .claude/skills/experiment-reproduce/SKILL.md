---
name: experiment-reproduce
description: Run a preregistered experiment in the reproducibility-mcp sandbox. Reads protocol.json budget + workspace, invokes the sandbox, parses metric from results.json (or stdout JSON), records result + advances state designed → preregistered → running → completed → analyzed → reproduced. Closes the Sakana experimentation loop.
when_to_use: User says "run the experiment", "reproduce experiment X", "execute preregistered protocol". Requires the experiment to be in `preregistered` state.
---

# experiment-reproduce

Closes the Sakana loop: design → preregister → **run sandboxed → analyze → reproduce**.

## Scripts

| Script | Subcommand | Purpose |
|---|---|---|
| `reproduce.py` | `run` | Execute preregistered experiment in sandbox; advance state |
| | `analyze` | Parse metric, compare to target, mark pass/fail; advance to `analyzed` |
| | `reproduce-check` | Re-run + verify metric within tolerance; advance to `reproduced` |
| | `status` | Show experiment + run history + verdict |

## Subcommands

```
reproduce.py run --experiment-id E --workspace /path/to/code [--entry-command "python entry.py"]
reproduce.py analyze --experiment-id E
reproduce.py reproduce-check --experiment-id E --tolerance 0.05
reproduce.py status --experiment-id E
```

## State machine

| Action | Transition |
|---|---|
| `run` | `preregistered → running → completed` (or `running → completed` with `error: true`) |
| `analyze` | `completed → analyzed` |
| `reproduce-check` | `analyzed → reproduced` (after second sandboxed run with matching metric) |

## Reading the metric

After sandbox run, the script looks for the primary metric in this order:

1. `<workspace>/result.json` — must contain `{"<metric_name>": <number>}`
2. Last line of stdout (must be valid JSON object with the metric key)
3. **Otherwise**: marked `error: true`, no metric recorded

## Pass / fail comparison

Reads `protocol.json["primary_metric"]`:
- `comparison`: one of `>=, >, <=, <, ==, !=`
- `target`: the number
- `value`: the recorded scalar from sandbox

If comparison holds → `passed: true`. Otherwise `passed: false`.

## Reproducibility check

`reproduce-check` runs the workspace a *second time* via the sandbox, then compares the new metric to the recorded one. Within `--tolerance` (default 5% relative diff) → `reproduced`. Otherwise stays `analyzed` with `reproduction_failed` flag.

## Storage

```
experiments/<eid>/
  manifest.json          # state advances here
  protocol.json          # primary_metric, budget
  runs/
    <audit_id>/
      result.json        # {audit_id, exit_code, wall_time, stdout_truncated, metric_value, error}
      stdout.log
      stderr.log
  analysis.json          # {primary_metric, recorded_value, target, comparison, passed}
  reproduction.json      # {reproduce_audit_id, second_value, diff, within_tolerance}
```

## Caveats

- Requires Docker daemon (via reproducibility-mcp).
- Workspace is mounted read-write by sandbox — intermediate files survive.
- Budget enforcement is strict: `protocol.budget.compute_seconds` is the hard timeout.
- The sandbox uses `--network none` — your script cannot fetch packages mid-run. Pre-install everything in the workspace.
