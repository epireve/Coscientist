# Smoke-test runbook

How to run a `/deep-research` pipeline and pinpoint where things break,
using the v0.93–v0.100 traceability + quality stack.

## Prereqs

- `uv` available (`uv run` works)
- MCPs registered (consensus, paper-search, semantic-scholar, academic)
  via `.mcp.json`
- Optional: `COSCIENTIST_TRACE_DB` and `COSCIENTIST_TRACE_ID` exported
  if you want MCP tool-call spans to emit (orchestrator sets these
  automatically for in-pipeline calls)

## Step 1 — Start a run

```bash
uv run python .claude/skills/deep-research/scripts/db.py init \
  --question "<your question>"
# → prints run_id, e.g. run-abc123def
```

The DB lives at `~/.cache/coscientist/runs/run-<rid>.db`. Migration
v11 + v12 are applied on init, so traces, spans, span_events, and
agent_quality tables are ready.

## Step 2 — Watch traces in real time

In another shell, scan all runs:

```bash
uv run python -m lib.trace_status
```

Or one run:

```bash
uv run python -m lib.trace_status --run-id <rid>
```

Output shows:
- run status (running / ok / error)
- span counts by kind (phase, tool-call, gate, harvest)
- latest phase fired
- most recent error if any

JSON variant for scripting:

```bash
uv run python -m lib.trace_status --run-id <rid> --format json
```

## Step 3 — Render a full timeline

After the run completes (or partway through):

```bash
uv run python -m lib.trace_render \
  --db ~/.cache/coscientist/runs/run-<rid>.db \
  --trace-id <rid> \
  --format md > /tmp/trace.md
```

Markdown timeline with all spans + events. Failed spans flagged ❌,
slow spans (>5s) flagged in mermaid output.

For a visual mermaid:

```bash
uv run python -m lib.trace_render \
  --db ~/.cache/coscientist/runs/run-<rid>.db \
  --trace-id <rid> \
  --format mermaid > /tmp/trace.mmd
```

## Step 4 — Find stale / hung spans

If a phase or sub-agent crashed without closing its span,
status stays `running` indefinitely. Detect:

```bash
uv run python -m lib.trace_status --stale-only --max-age 30
```

Or for one run:

```bash
uv run python -m lib.trace_status --stale-only --run-id <rid> \
  --max-age 30
```

To auto-close stale spans (mutates DB):

```bash
uv run python -m lib.trace_status --stale-only --mark-error \
  --reason "phase crashed mid-run"
```

## Step 5 — Inspect tool-call latency

Which MCPs are hot, which fail often:

```bash
uv run python -m lib.trace_status --tool-latency --run-id <rid>
```

Cross-run aggregate:

```bash
uv run python -m lib.trace_status --tool-latency
```

Reports n, n_errors, mean_ms, p50_ms, p95_ms, max_ms per tool name.
Sorted slowest-first in markdown output.

## Step 6 — Per-agent quality scores

The auto-rubric runs on phase complete (v0.94 hook) for personas
with rubrics: scout, surveyor, architect, synthesist, weaver.
Inspect:

```bash
uv run python -m lib.agent_quality summary \
  --db ~/.cache/coscientist/runs/run-<rid>.db \
  --run-id <rid>
```

Cross-run leaderboard:

```bash
uv run python -m lib.agent_quality leaderboard
```

Surfaces "scout consistently 0.4 — investigate" patterns across
multiple runs.

## Step 7 — LLM-judge (optional, manual)

For deeper quality assessment, dispatch the `quality-judge`
sub-agent via Claude Code's Task tool:

1. Get the structured prompt:

   ```python
   from lib.agent_quality import emit_judge_prompt
   prompt = emit_judge_prompt(
       agent_name="scout",
       artifact_path=Path("/path/to/artifact.json"),
   )
   ```

2. Dispatch via Task tool with `subagent_type="quality-judge"` +
   the prompt.

3. Persist the JSON verdict:

   ```python
   from lib.agent_quality import persist_judge_result
   persist_judge_result(
       db, run_id=rid, span_id=None, agent_name="scout",
       artifact_path=path, judge_json=sub_agent_response,
   )
   ```

## Step 8 — Resume a paused run

```bash
uv run python .claude/skills/deep-research/scripts/db.py resume \
  --run-id <rid>
```

Picks up at the first phase with `completed_at IS NULL`. If a stale
span is in the way, run step 4 first.

## Common failure patterns

| Symptom | Diagnosis | Fix |
|---|---|---|
| Run stuck on phase X | Stale span (--stale-only catches it) | --mark-error then resume |
| MCP returning errors | tool-latency shows n_errors > 0 | Check `.mcp.json` + API keys |
| Quality score 0 | Rubric criteria all fail (artifact malformed) | Re-run that phase or fix artifact |
| No spans emitting | Migration v11 not applied | `lib.migrations.ensure_current(db)` |
| trace-status empty | Run started before v0.93 hookup | Pre-instrumentation runs not retrofitted |

## What's NOT instrumented (yet)

- Sub-agent dispatches via Task tool — orchestrator is markdown-driven,
  no programmatic span wrap. Manual span emission possible from
  inside sub-agents but not done by default.
- Persona output JSON shape validation — auto-rubric checks
  semantic content but not strict schema. Future work.

## Safety

All instrumentation is best-effort. Tracing failures never break
the parent run. If `trace_status` itself errors, the pipeline
keeps running — observability is opt-in, not load-bearing.
