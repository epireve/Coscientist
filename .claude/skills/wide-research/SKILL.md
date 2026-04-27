---
name: wide-research
description: Process N items (10-250) in parallel via orchestrator-worker fan-out. Modes — triage / read / rank / compare / survey / screen. Use when the task is "do this N times across these items" — paper-by-paper screening, per-paper full-text extraction, per-author publication maps, per-protocol feature comparison. Distinct from `deep-research` (single field-level synthesis); complementary via Wide → Deep handoff.
when_to_use: User has a list of items (papers, authors, protocols, datasets) and wants the same structured analysis applied to each. Auto-trigger when prompt contains "for each of these N", "process this list", "screen these papers", "compare across", or specifies an item count >10.
---

# wide-research

Orchestrator-Worker fan-out for processing many items. One sub-agent per item (capped at concurrency 30); each sub-agent runs in fresh context with filesystem-as-memory. Synthesizer collects file refs + summaries (not raw content) and produces roll-up.

## Architecture

```
User Query (typed: process N items)
    │
    ▼
ORCHESTRATOR
  - decompose into N TaskSpecs (one per item)
  - emit decomposition table for HITL Gate 1
    │
    ▼ (user approves)
FAN-OUT — N parallel sub-agents (asyncio.gather, cap 30)
  Each sub-agent:
    - fresh context window
    - own filesystem workspace at wide/<sub-id>/
    - tools restricted via subagent_type frontmatter (tool masking, not removal)
    - errors stay in context (Manus error-retention rule)
    - rewrites task_progress.md end-of-context every step (attention recitation)
    - writes result.json on COMPLETE
    │
    ▼ (HITL Gate 2 optional — mid-research preview)
FAN-IN — collect file refs + summaries
    │
    ▼ (HITL Gate 3 optional — flag items for re-run)
SYNTHESIZER (fresh context — only file refs, not raw content)
  - per-mode roll-up template
  - structured CSV + markdown report
    │
    ▼
OUTPUT
```

## Six TaskSpec types

| Type | Sub-agent objective | Output schema | Default budget |
|---|---|---|---|
| `triage` | Read abstract → relevance score → include/review/exclude | `{canonical_id, score, recommend, reason}` | 5 calls / 15K tokens |
| `read` | Acquire PDF → extract → structured per-paper data | `{method, dataset, results, limitations, claims, figures}` | 25 calls / 80K tokens |
| `rank` | Pairwise compare items → Elo update | `{item_a, item_b, winner, reasoning}` | 5 calls / 10K tokens |
| `compare` | Per-item feature extraction across fixed schema | per-spec | 15 calls / 40K tokens |
| `survey` | Per-author publication trajectory | `{author, h_index, recent_venues, top_papers}` | 10 calls / 30K tokens |
| `screen` | PRISMA-style include/exclude per criterion | `{canonical_id, include, criteria_failed}` | 8 calls / 20K tokens |

## Hard limits (production discipline)

- Min items: 10 (below this → use Quick or Deep)
- Max items: 250 (above this → use systematic-review skill)
- Concurrency cap: 30 (respect MCP rate limits)
- Per-sub-agent token budget: type-default
- Run-level $ ceiling: $50 unless `--allow-expensive`
- Token multiplier: ~15× single-agent (Anthropic-published)

## How to invoke

```bash
# 1. Init Wide run with items list
uv run python .claude/skills/wide-research/scripts/wide.py init \
  --query "Triage 100 BFT-edge papers for relevance to question Q" \
  --items /tmp/items.json \
  --type triage

# 2. Decompose + show plan (HITL Gate 1)
uv run python .claude/skills/wide-research/scripts/wide.py decompose \
  --run-id <wide-id>

# 3. User approves → orchestrator dispatches sub-agents
#    (v0.53.1 POC: single sub-agent synchronous;
#     v0.53.2: asyncio.gather parallel)

# 4. Collect results
uv run python .claude/skills/wide-research/scripts/wide.py collect \
  --run-id <wide-id> --format csv

# 5. Wide → Deep handoff (closes audit's 0% DOI gap)
uv run python .claude/skills/deep-research/scripts/db.py init \
  --question "..." \
  --seed-from-wide <wide-id> \
  --seed-top-k 30 \
  --seed-mode full-text   # if Wide ran read type; else 'abstract'
```

## What "done" looks like

- N TaskSpecs decomposed, one per item
- Each sub-agent has filesystem workspace at `~/.cache/coscientist/runs/run-<wide-id>/wide/<sub-id>/`
- Each sub-agent writes `result.json` to its workspace on COMPLETE
- Synthesizer roll-up at `runs/run-<wide-id>/wide-output.{csv,md}`
- Cost tracker logs final $ + token usage

## Engineering principles

From Manus + Anthropic production deployments:

1. **KV-cache stability** — TaskSpec.to_prompt() is deterministic, no timestamps, sorted-key JSON. 10× cost diff cached vs uncached.
2. **Filesystem-as-memory** — sub-agents write findings to workspace, keep only file paths in context. ~100:1 input:output ratio.
3. **Tool masking, not removal** — all tools defined upfront via `tools_allowed`; restriction enforced by Claude Code subagent_type frontmatter, not dynamic edits.
4. **Error retention** — sub-agent errors stay in context. Reading the error is the model's evidence to adapt.
5. **Attention recitation** — `task_progress.md` rewritten at end of context every step. Prevents lost-in-the-middle.
6. **Scope exclusions in TaskSpec** — explicit "other agents are covering X, Y, Z" prevents duplicate work (Anthropic-reported failure mode).

## What this skill does NOT do

- Field-level synthesis (use `deep-research`)
- Single-paper analysis (use direct paper-discovery + arxiv-to-markdown)
- Tournament-style hypothesis ranking (use `tournament` skill — `rank` TaskSpec type is for pairwise item comparison, not hypotheses)
- Systematic-review with PRISMA flow diagram (use `systematic-review` skill — `screen` TaskSpec is the screening step alone)

## Wide → Deep handoff

Wide outputs feed Deep's scout phase via `--seed-from-wide`. Three levels:

- **L1 seed**: Wide-triage CSV → Deep scout reads filtered top-K rows, MCP harvest skipped
- **L2 full-text**: Wide-read populates paper artifacts (`content.md`, `references.json`) so Deep's cartographer computes citation in-degree mechanically (not heuristic abstract inference)
- **L3 cumulative**: Deep → Wide → Deep refinement loop

Migration `runs.parent_run_id` + `runs.seed_mode` shipped in v0.53.5
(schema migration v8; idempotent in-code via `_ensure_v8_columns`).
After Wide finishes, run `wide.py synthesize --run-id <wide-id>
--write-outputs` to emit synthesis.json. Then:

```bash
uv run python .claude/skills/deep-research/scripts/db.py init \
  --question "Refined question" \
  --seed-from-wide <wide-id> \
  --seed-mode abstract     # or full-text, cumulative
```

The Deep run logs `parent_run_id` + `seed_mode` and pre-populates
`papers_in_run` with the top-K Wide outputs (role=`seed` for abstract
mode, role=`supporting` for full-text mode, both for cumulative).
Deep's scout phase reads these existing entries instead of cold-start
MCP harvesting.

## Output

Per sub-agent: `<workspace>/result.json` matching TaskSpec output_schema.

Run-level: `runs/run-<wide-id>/wide-output.csv` + `wide-output.md` (synthesizer roll-up).

Persisted across sessions. Read with `wide.py collect`.
