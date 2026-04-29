---
name: coauthor-network
description: Read-only aggregation over project graph — surfaces coauthor frequency, year-range, and shared-papers per author. Pure SQL. No writes.
when_to_use: Need to know "who collaborates with X" or "is there a research clique around topic Y?".
---

# coauthor-network

Read-only over the project graph. No writes. Surfaces coauthor structure
by walking `authored-by` edges (paper → author) and aggregating shared
papers per author pair.

## Scripts

| Script | Subcommands | Purpose |
|---|---|---|
| `coauthor.py` | `for-author`, `for-paper`, `cliques` | Coauthor aggregation |

## Subcommands

```
coauthor.py for-author --project-id P --author-nid author:X [--format json|text]
coauthor.py for-paper  --project-id P --canonical-id CID  [--format json|text]
coauthor.py cliques    --project-id P [--min-shared 2]    [--format json|text]
```

## Algorithm

**for-author**:
1. Find all paper nodes that this author is `authored-by` source for.
2. For each paper, find all OTHER authors of the same paper.
3. Aggregate per coauthor: shared_papers count, paper_ids list,
   year range pulled from each paper's `metadata.json` (if available).
4. Return list sorted by shared_papers DESC, then author label ASC.

**for-paper**:
1. Find authors of the target paper.
2. For each author, run `for-author` logic.
3. Merge into one response keyed by author_nid.

**cliques**:
1. Build adjacency map from `authored-by` edges.
2. Find pairs with ≥ `--min-shared` shared papers.
3. Greedy expand to triangles (a-b, b-c, a-c all present).
4. Return `[{authors: [...], shared_papers: N}, ...]`.

## Caveats

- Year extracted from `metadata.json["year"]` per paper (best-effort;
  paper artifacts without metadata are skipped from year-range).
- Errors return `{error: ...}` dicts — never raises.
- Pure read-only by construction; no graph mutations.
