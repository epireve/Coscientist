---
name: graph-query
description: Read-only CLI primitives over the per-project citation/concept/author graph. Surfaces `lib/graph.py` (BFS walk, neighbors, in-degree, hubs) plus path-finding so sub-agents can answer "who cites paper X up to depth 2", "what concepts connect papers A and B", "which papers are central in this corpus", "who are paper X's coauthors". Pure SQL on `graph_nodes` + `graph_edges` tables. Never mutates anything.
when_to_use: Sub-agents (architect, visionary, weaver) need to walk citations or concept graphs without hand-rolling SQL. User asks "who cites X", "central papers in topic Y", "concept path between two papers", "co-author cluster". Counterpart of `reference-agent` (which writes the graph).
---

# graph-query

Pure SQL on the per-project graph. Read-only — never writes nodes or edges.

## Subcommands

```bash
# BFS expand citations from a paper (defaults: relation=cites, depth=2)
uv run python .claude/skills/graph-query/scripts/query.py expand-citations \
  --project-id <pid> --canonical-id <cid> [--depth 2] [--relation cites]

# In-degree count for a node (how many papers cite this paper)
uv run python .claude/skills/graph-query/scripts/query.py in-degree \
  --project-id <pid> --canonical-id <cid> [--relation cites]

# Top-K hubs of a given kind
uv run python .claude/skills/graph-query/scripts/query.py hubs \
  --project-id <pid> --kind paper [--relation cites] [--top 20]

# Neighbors (one hop, optionally filtered by relation + direction)
uv run python .claude/skills/graph-query/scripts/query.py neighbors \
  --project-id <pid> --node-id paper:<cid> \
  [--relation cites] [--direction out|in|both]

# Shortest concept path between two papers (BFS over typed edges)
uv run python .claude/skills/graph-query/scripts/query.py concept-path \
  --project-id <pid> --from <cid> --to <cid> [--max-hops 4]

# Co-author cluster around an author node
uv run python .claude/skills/graph-query/scripts/query.py author-cluster \
  --project-id <pid> --s2-id <s2_id> [--depth 1]
```

JSON to stdout. `--format md` renders a readable markdown summary.

## Node ID format

`<kind>:<ref>` — e.g. `paper:vaswani_2017_x`, `concept:transformer-attention`, `author:1234567`.

Use `query.py expand-citations --canonical-id <cid>` if you only have a canonical_id; the script wraps it as `paper:<cid>`.

## What this does NOT do

- Doesn't fetch from MCPs — works only on what's already in the project DB.
- Doesn't write nodes or edges (use `reference-agent populate_concepts.py` etc. for writes).
- Doesn't synthesize / summarize — pure traversal only.

## Principles

From `RESEARCHER.md`: read-only, deterministic, no opinions. Surfaces structure; lets the calling agent interpret.
