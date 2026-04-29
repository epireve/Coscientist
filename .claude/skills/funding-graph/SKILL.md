---
name: funding-graph
description: Read-only aggregation — papers per funder, papers per institution, funder-author overlap, dominant-funder detection. Pure SQL.
when_to_use: Asking "who funded this work?", "which institutions dominate this topic?", "is this author dependent on one funder?".
---

# funding-graph

Read-only over the project graph. No writes. Surfaces funding patterns
from v0.148 schema v13 `kind=funder` + `kind=institution` nodes and
`relation=funded-by` (paper → funder) + `relation=affiliated-with`
(author → institution) edges.

## Scripts

| Script | Subcommands | Purpose |
|---|---|---|
| `funding.py` | `papers-by-funder`, `papers-by-institution`, `for-funder`, `for-institution`, `dominant-funders` | Funding aggregation |

## Subcommands

```
funding.py papers-by-funder        --project-id P [--format json|text]
funding.py papers-by-institution   --project-id P [--format json|text]
funding.py for-funder              --project-id P --funder-nid funder:X      [--format json|text]
funding.py for-institution         --project-id P --institution-nid institution:Y [--format json|text]
funding.py dominant-funders        --project-id P [--min-papers 5] [--threshold 0.6] [--format json|text]
```

## Algorithm

**papers-by-funder** / **papers-by-institution**:
1. Group `graph_edges` by `to_node` filtered by relation
   (`funded-by` for funders, `affiliated-with` for institutions).
2. Join with `graph_nodes` for label.
3. Sort by paper count DESC, label ASC tiebreak.

**for-funder**: papers funded by X plus authors of those papers (via
`authored-by`).

**for-institution**: authors at Y plus papers each authored.

**dominant-funders**: for every author, compute (#papers funded by
funder F) / (#papers by author). Flag authors where the top funder's
ratio ≥ `--threshold` AND #papers ≥ `--min-papers`.

## Caveats

- Errors return `{error: ...}` dicts — never raises.
- Pure read-only by construction; no graph mutations.
- Concept-only graphs (no funders/institutions) return clean empty
  results.
