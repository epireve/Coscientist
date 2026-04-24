---
name: deep-research
description: End-to-end research on a question using the 10-agent SEEKER pipeline. Discovers papers, triages them, acquires the full-text ones, extracts them, runs 10 sequential sub-agents with 3 human-in-the-loop breaks, and produces a Research Brief + six-section Understanding Map.
when_to_use: The user provides a research question and wants a thorough, traceable investigation — not just a quick literature search. Use `paper-discovery` alone for simple lookups.
---

# deep-research

Orchestrates the full pipeline. Owns the SQLite run log, the break points, and the sub-agent sequencing.

## How to invoke

```bash
# new run
uv run python .claude/skills/deep-research/scripts/db.py init \
  --question "Your research question" \
  [--config /path/to/config.json]

# returns a run_id — note it. Then run phases:
uv run python .claude/skills/deep-research/scripts/db.py resume --run-id <run_id>
```

Or use the slash command shortcut: `/deep-research "your question"`.

## The pipeline

```
  Social
    │
  [BREAK 0] — user confirms/redirects source pool
    │
  Grounder → Historian → Gaper
    │
  [BREAK 1] — user validates foundation; uploads Phase 2 instructions
    │
  Vision → Theorist → Rude → Synthesizer
    │
  [BREAK 2] — user approves coherence; specifies final artifact format
    │
  Thinker → Scribe
    │
  Research Brief + Understanding Map
```

Each sub-agent is invoked via Claude Code's native sub-agent mechanism — they run with independent context windows and return structured output that this orchestrator persists to the run DB.

## Orchestrator responsibilities (agent-facing)

When you (the calling Claude agent) run this skill:

1. **Create or resume the run** — `db.py init` or `db.py resume`.
2. **Invoke each sub-agent in order** — via Claude Code's `Task` tool with `subagent_type=<agent-name>`. Do not inline their prompts here; they are defined in `.claude/agents/`.
3. **After each agent completes**, call `db.py record-phase` with the agent's structured output.
4. **At break points**, stop the pipeline. Use `AskUserQuestion` to prompt the user. Record their input via `db.py record-break`. Do not proceed until resolved.
5. **If any agent errors or returns low-confidence output**, record the error and prompt the user — do not silently skip a phase.
6. **On completion**, the final Scribe phase produces the artifacts; the orchestrator runs `/research-eval` automatically before marking the run complete.

## Configuration (`config.json`)

Optional per-run config controlling which sources each agent uses. Schema:

```json
{
  "enabled_mcps": {
    "social":    ["consensus", "paper-search", "semantic-scholar", "academic"],
    "grounder":  ["consensus", "semantic-scholar"],
    "historian": ["consensus", "paper-search"],
    "gaper":     ["consensus"],
    "theorist":  ["semantic-scholar"],
    "thinker":   ["semantic-scholar"]
  },
  "max_papers_per_phase": 50,
  "allow_institutional_access": true
}
```

Missing keys use sensible defaults (all MCPs enabled, 50 papers cap).

## Resume semantics

`db.py resume --run-id <id>`:

1. Looks up the last phase with `completed_at IS NULL`
2. Invokes that agent fresh
3. Continues onward

A run can be interrupted and resumed across Claude Code sessions — the SQLite DB holds all state.

## Outputs

Written to `~/.cache/coscientist/runs/run-<run_id>/`:

- `brief.md` — the Research Brief
- `understanding_map.md` — the six-section Understanding Map
- `eval.md` — reference + claim audit report (from `/research-eval`)
- plus the SQLite DB (`~/.cache/coscientist/runs/run-<run_id>.db`)

## Guardrails

- Never skip a break. The human-in-the-loop review is the whole point of this pipeline.
- Never bypass `paper-acquire`'s triage gate, even when a sub-agent asks for full text urgently.
- Abort if `/research-eval` reports >30% unattributed claims — something went wrong upstream.
