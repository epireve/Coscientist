---
name: cross-project-memory
description: Read-only search across all project DBs. Answers "I know I read this somewhere" and "which projects touched this paper / concept / author". Pure aggregation; never mutates anything.
when_to_use: Looking for a paper or concept you remember encountering but can't recall which project. Auditing how often a paper is cited across your work. Surfacing connections between apparently-unrelated projects.
---

# cross-project-memory

Iterates over every project DB under `~/.cache/coscientist/projects/<pid>/project.db` and unions the results.

## Two scripts

| Script | Job |
|---|---|
| `search.py` | Fuzzy keyword search across paper titles, manuscript claims, journal entries, and concept nodes |
| `find_paper.py` | Given a canonical_id, DOI, or title fragment, list every project that contains it (with state) |

## search

```bash
uv run python .claude/skills/cross-project-memory/scripts/search.py \
  --query "scaling law" \
  [--kinds papers,concepts,manuscripts,journal] \
  [--limit 50]
```

Searches across:
- **papers**: titles + abstracts of all paper artifacts referenced by any project
- **concepts**: graph_nodes of kind=concept (label match)
- **manuscripts**: manuscript_claims.text (your own assertions)
- **journal**: journal_entries.body

Returns hits grouped by kind with project context.

## find-paper

```bash
# By canonical_id
uv run python .claude/skills/cross-project-memory/scripts/find_paper.py \
  --canonical-id vaswani_2017_attention_abc

# By DOI
uv run python .claude/skills/cross-project-memory/scripts/find_paper.py \
  --doi 10.48550/arXiv.1706.03762

# By title fragment
uv run python .claude/skills/cross-project-memory/scripts/find_paper.py \
  --title "attention is all you need"
```

Returns: `[{project_id, project_name, kind: registered|cited|graph-only, reading_state, citing_manuscripts: [mid]}, ...]`.

## Outputs

JSON to stdout. Read-only — never modifies any DB or file.

## What this does NOT do

- Doesn't synthesize across projects (no LLM, no summary)
- Doesn't write to any DB
- Doesn't fetch papers from MCPs (works only with what's already cached)
