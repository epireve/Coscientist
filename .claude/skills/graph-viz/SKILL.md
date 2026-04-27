---
name: graph-viz
description: Render the per-project citation/concept/author graph as a mermaid markdown block. Read-only — surfaces `lib/graph_viz.py` over the project DB (`graph_nodes` + `graph_edges`). Different node shapes per kind (paper rectangle, concept circle, author flag, manuscript hexagon). Truncates dense graphs by in-degree, hides labels when overcrowded. Convenience modes for concept subgraphs and paper citation lineage. Counterpart of `graph-query` (which returns JSON walks).
when_to_use: User asks to "visualize the graph", "show citation graph as mermaid", "draw the concept network", "lineage of paper X", "subgraph around concept Y". Useful in manuscript appendices and journal entries where a static, GitHub-rendered graph is wanted. Never writes anything — pure renderer.
---

# graph-viz

Mermaid renderer over the per-project graph. Read-only; takes `graph_nodes` + `graph_edges` rows and produces a fenced ```` ```mermaid ```` markdown block.

## Subcommands

```bash
# Whole project graph (capped to top-N by in-degree)
uv run python .claude/skills/graph-viz/scripts/render.py \
  --project-id <pid> [--max-nodes 50] [--hide-labels-above 20] [--out file.md]

# BFS subgraph around any node (concept, paper, author, manuscript)
uv run python .claude/skills/graph-viz/scripts/render.py \
  --project-id <pid> --root <node-id> [--depth 2]

# Forward/backward citation lineage of a paper
uv run python .claude/skills/graph-viz/scripts/render.py \
  --project-id <pid> --root paper:<cid> --direction cites|cited-by [--depth 2]

# Filter by kind only (e.g. just concept↔paper edges)
uv run python .claude/skills/graph-viz/scripts/render.py \
  --project-id <pid> --kind concept
```

Mermaid markdown to stdout, or `--out file.md` to a file.

## Node shapes

| kind        | mermaid shape | example                |
|-------------|---------------|------------------------|
| paper       | `[label]`     | rectangle              |
| concept     | `((label))`   | circle                 |
| author      | `>label]`     | asymmetric flag        |
| manuscript  | `{{label}}`   | hexagon                |

Edges are labeled with their relation (`cites`, `about`, `authored-by`, …). Multiple edges between the same pair collapse into one labeled `relation ×N`.

## Truncation

- `--max-nodes` (default 50): cap on emitted nodes. Top-N by in-degree (when known) or input order.
- `--hide-labels-above` (default 20): drop node text above this size to keep mermaid legible. The safe IDs remain unique.

## What this does NOT do

- Doesn't fetch from MCPs.
- Doesn't write nodes or edges (use `reference-agent` populators).
- Doesn't compute layouts — mermaid handles that.
- Doesn't render images (mermaid is markdown; GitHub / VS Code render it).

## Principles

From `RESEARCHER.md`: read-only, deterministic, no opinions. Surfaces structure; lets the calling agent interpret. Output is plain text; viewable in any markdown reader that supports mermaid.
