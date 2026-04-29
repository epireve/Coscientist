---
name: citation-decay
description: Read-only citation-freshness analytics — recent-citers, citation velocity, stale-paper detection. Pure SQL on graph + per-paper metadata.json years.
when_to_use: Asking "is this paper still active in the literature?" or "which classic papers in my project are stale (no recent citers)?"
---

# citation-decay

Read-only over the project graph. No writes. Surfaces citation freshness
signals by joining `cites` edges (citer → target) with each paper's
`metadata.json["year"]`.

## Scripts

| Script | Subcommands | Purpose |
|---|---|---|
| `citation_decay.py` | `for-paper`, `velocity`, `stale` | Citation-freshness aggregation |

## Subcommands

```
citation_decay.py for-paper --project-id P --canonical-id CID
                            [--decay-years 5] [--current-year 2026]
                            [--format json|text]
citation_decay.py velocity  --project-id P [--top-n 20]
                            [--current-year 2026] [--format json|text]
citation_decay.py stale     --project-id P [--min-citations 5]
                            [--decay-years 5] [--current-year 2026]
                            [--format json|text]
```

## Algorithm

**for-paper**:
1. Find target paper node + year from `metadata.json["year"]`.
2. Pull `cites` edges where `to_node = paper:<cid>` (the citers).
3. Bucket each citer by its own year (skip citers without year).
4. Return `{year_buckets, most_recent_citer_year, total_citations,
   recent_window_count}` where recent-window covers the last
   `decay-years` relative to `current-year`.

**velocity**:
1. For each paper node with a known year:
   - Count incoming `cites` edges.
   - velocity = citations / max(1, current_year - paper_year).
2. Sort desc; cap at `--top-n`.

**stale**:
1. For each paper with a known year and `total_citations >= min_citations`:
   - Find max(citer_year). If `< current_year - decay_years` → stale.
2. Return list sorted by total_citations DESC.

## Caveats

- Year extracted from `metadata.json["year"]` per paper (best-effort).
  Papers without year are silently skipped from velocity / stale and
  return an error dict from `for-paper`.
- `current_year` defaults to 2026; override via `--current-year` for
  testability.
- Errors return `{error: ...}` dicts — never raises.
- Pure read-only by construction; no graph mutations.
