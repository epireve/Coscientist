---
name: meta-research
description: Cross-project career trajectory + publication trends + concept overlap. Read-only aggregation across all project DBs. Combines artifact_index counts, manuscript states, reading_state, and graph nodes into a single meta-view. Distinct from project-dashboard (single-project snapshot) and cross-project-memory (search lookup).
when_to_use: User says "career trajectory", "publication trend", "what have I been working on", "cross-project overlap", "year in review", "research patterns".
---

# meta-research

Read-only aggregation across all project DBs. Pure SQL — never writes.

## Scripts

| Script | Subcommand | Purpose |
|---|---|---|
| `meta.py` | `trajectory` | Per-year manuscript counts by state |
| | `concepts` | Concepts shared across ≥2 projects (overlap) |
| | `productivity` | Per-project artifact counts + activity windows |
| | `summary` | Combined view with all three |

## Subcommands

```
meta.py trajectory [--years 5]
meta.py concepts [--min-projects 2]
meta.py productivity [--include-archived]
meta.py summary [--years 5] [--format json|md]
```

## Metrics

**trajectory** — for each year in window: count manuscripts by state (drafted/submitted/published) across all projects.

**concepts** — concept nodes appearing in ≥N project graphs. Returns `{concept, project_count, projects: [pid, ...]}`.

**productivity** — per-project: total papers/manuscripts/experiments/grants/datasets, days since last activity (newest artifact updated_at), age in days.

**summary** — combines all three plus active-project marker.

## Format

`json` (default) — machine-readable. `md` — daily-review table format.

## Caveats

- "Year" is computed from artifact `created_at`. If you ingest old papers today, they get bucketed to today.
- "Concept overlap" requires `populate_concepts.py` to have run on each project. Empty if no concept nodes exist.
- Read-only by construction — verifies file mtimes unchanged after queries.
