---
name: reading-pace-analytics
description: Read-only velocity metrics from reading_state across projects — papers per week, current backlog by state, time-to-read distribution, and weekly trend. Pure aggregation; no writes.
when_to_use: User asks "how fast am I reading", "what's my paper backlog", "reading pace", "papers per week", or wants to see reading-velocity trends across projects.
---

# reading-pace-analytics

Per-project (or global) reading velocity. Reads `reading_state` rows. Pure aggregation — never mutates anything.

## Scripts

| Script | CLI | Purpose |
|---|---|---|
| `pace.py` | subcommands: `velocity`, `backlog`, `trend`, `summary` | Main entry |

## Subcommands

```
pace.py velocity [--project-id P] [--days 28]
pace.py backlog [--project-id P]
pace.py trend [--project-id P] [--weeks 12]
pace.py summary [--project-id P]
```

## Metrics

**velocity**:
- `papers_read_in_window` — count of rows whose state moved to `read` within the last N days (uses `updated_at`)
- `papers_per_week` — read count / weeks elapsed
- `cited_per_week` — same for `cited` state

**backlog**:
- count per state: `to-read | reading | read | annotated | cited | skipped`
- `untouched_to_read_count` — to-read rows older than 30 days (stale backlog)
- `oldest_to_read_age_days` — oldest pending paper

**trend**:
- weekly read counts for the last N weeks (returns 12-week rolling average)

**summary**:
- composite of all three above + total tracked papers

## Caveats

`reading_state` only stores the *current* state per (canonical_id, project_id) pair plus `updated_at` of the last transition. We do **not** have a full state-transition log — so:

- "papers read in window" = papers whose current state ∈ {read, annotated, cited} AND `updated_at` falls in window
- Trend over months with state churn (read → annotated → cited) will undercount because each row contributes once at most

For higher-fidelity tracking, future v0.32+ may add a `reading_state_history` table.
