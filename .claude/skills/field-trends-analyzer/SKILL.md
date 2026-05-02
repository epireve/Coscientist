---
name: field-trends-analyzer
description: Read-only aggregation over the project graph to surface trending concepts, paper-citation momentum, and rising authors. Pure SQL on graph_nodes + graph_edges. Computes per-concept paper count, per-paper in-degree (cites), recency-weighted scores, and identifies "rising" vs "declining" topics by comparing two time windows.
when_to_use: User says "what topics are trending", "rising concepts", "field momentum", "what's hot", "which papers are gaining citations". After reference-agent's populate_concepts.py has run.
---

# field-trends-analyzer

Read-only over the project graph. No writes. Surfaces trends by comparing two time windows.

## Scripts

| Script | CLI | Purpose |
|---|---|---|
| `trends.py` | subcommands: `concepts`, `papers`, `authors`, `momentum`, `summary` | Main entry |

## Subcommands

```
trends.py concepts --project-id P [--top 20]
trends.py papers --project-id P [--top 20] [--rank-by citations|pagerank]
trends.py authors --project-id P [--top 20]
trends.py momentum --project-id P [--window-recent 90] [--window-past 365] [--top 20]
trends.py summary --project-id P
```

## Metrics

**concepts** — top-N concept nodes by `about` edge count (papers tagged with that concept).

**papers** — top-N paper nodes ranked by `--rank-by`: `citations` (default — `cites` in-degree) or `pagerank` (v0.179 — power-iteration over the citation graph; surfaces influence-weighted ranking even when raw cite count is low).

**authors** — top-N author nodes by `authored-by` count.

**momentum** — for each concept: count papers added (created_at) in the recent window vs past window. Rising = recent_count > past_count. Decline = recent < past. Plateau = roughly equal.

**summary** — combined view of all four.

## Caveats

- Graph must be populated. Run `reference-agent/scripts/populate_citations.py` and `populate_concepts.py` first.
- "Trending" is computed within *this project's* graph, not global field trends. For global trends, use Semantic Scholar's recommendation/trend APIs.
- Read-only by construction — verifies file mtime unchanged after queries.

## CLI flag reference (drift coverage)

- `trends.py`: `--buckets`, `--window-days`
