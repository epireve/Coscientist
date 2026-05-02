---
name: gap-analyzer
description: Operationalizes Surveyor's gap output. For each gap, decides real-vs-artifact, addressable, publishability tier (A/B/C/none), adjacent-field analogues, and expected difficulty. Pure heuristic; LLM-free analysis.
when_to_use: After a deep-research run produces Surveyor output (Phase 1c) — the user wants per-gap structured analysis to triage which gaps are worth turning into projects. Or after manuscript-reflect identifies gaps in the user's own draft.
---

# gap-analyzer

Reads gaps from a deep-research run's Surveyor output (or from any
`{gap_id, kind, claim, supporting_ids, cross_check_query}` list) and
produces a structured per-gap analysis.

## What it answers per gap

- **Real or artifact**: is this a genuine gap, or did Surveyor miss
  prior work? Heuristic over `cross_check_query` + supporting count
  + supporting paper confidence.
- **Addressable**: would a single research project plausibly fill it?
  Driven by gap kind:
  - evidential → usually yes (run an experiment)
  - measurement → sometimes (build instrument)
  - conceptual → only with high-confidence support
- **Publishability tier (A/B/C/none)**: A-tier gaps have ≥4 high-conf
  supporters + clear novelty headroom; artifact gaps get `none`.
- **Adjacent-field analogues**: cross-domain hints. Pure keyword scan
  against `_ADJACENT_FIELD_HINTS` registry.
- **Expected difficulty (low/medium/high)**: by kind + addressability.

## How to invoke

```bash
# From a deep-research run (reads Surveyor's output_json)
uv run python .claude/skills/gap-analyzer/scripts/analyze.py \
  --run-id <run_id> [--write-output]

# From a JSON file of gaps (for ad-hoc / manuscript use)
uv run python .claude/skills/gap-analyzer/scripts/analyze.py \
  --gaps-file /path/to/gaps.json [--confidences /path/to/confs.json]
```

`--write-output` writes `gap_analysis.{json,md}` to the run dir.

## What "done" looks like

- Per-gap analysis: real/artifact verdict + tier + difficulty +
  analogues + reasoning.
- Markdown brief renderable via `lib.gap_analyzer.render_brief`.
- No new claims written — read-only over `claims` table.

## What this skill does NOT do

- Does not search prior work (that's Surveyor's job).
- Does not run experiments to test the gap (that's Sakana / Tier C).
- Does not re-rank gaps by Elo (that's tournament).

## CLI flag reference (drift coverage)

- `analyze.py`: `--persist-db`
