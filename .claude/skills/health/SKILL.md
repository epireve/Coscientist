---
name: health
description: Single-shot diagnostics dump across the entire Coscientist stack. Walks every run DB and surfaces active runs, stale/hung spans, tool-call latency by name (slowest first), per-agent quality leaderboard (lowest mean first), and total failed-span count. Pure read-only aggregation over v0.93–v0.105 instrumentation. One command, one operator view.
when_to_use: User says "health check", "is anything stuck", "show me what's running", "tool latency", "agent quality across runs", "failed spans", "what's broken". Also the recommended first stop during a live `/deep-research` smoke test or daily review.
---

# health

Pure aggregation across `~/.cache/coscientist/runs/run-*.db`. Combines:

- **active runs** — traces with `status='running'`
- **stale spans** — running spans past `--max-age` minutes (via v0.97)
- **tool-call latency** — by-tool n/n_errors/mean/p50/p95/max (via v0.100)
- **agent quality leaderboard** — per-agent mean/min/max/latest (via v0.96)
- **failed spans total** — count of `status='error'` across all traces

Read-only. Never mutates DBs.

## CLI

```bash
# Markdown dump (human-readable)
uv run python -m lib.health

# JSON for scripting
uv run python -m lib.health --format json

# Custom stale-span threshold (default 30 min)
uv run python -m lib.health --max-age 60
```

## Output sections (md)

1. **Header** — n_runs, n_active, n_stale, total failed spans
2. **Active runs** — running traces with start time
3. **Stale spans** — running spans past threshold (kind/name/age)
4. **Tool-call latency** — top 10 slowest tools by mean ms
5. **Agent quality** — agents sorted lowest-mean-first (regression hint)

If all sections empty, output reads `_No data — instrumentation hasn't logged yet._`

## Distinct from

- `project-dashboard` — per-project artifact + manuscript view; this is run-trace-centric
- `audit-query` — log files (PDF fetches, Docker runs); this is span tables (v0.89+)
- `trace-status` — same data shape but per-run; health aggregates across all runs

## Pairs with

- `lib.trace_render` — drill into one trace after health flags it
- `lib.trace_status --stale-only --mark-error` — auto-close stale spans health surfaces
- `lib.agent_quality leaderboard` — same quality data, raw

## Exit test

`/health` shows zero stale spans AND no failed_spans_total spike vs.
prior runs. Smoke test passes when health dump is boring.

## CLI flag reference (drift coverage)

- `health.py`: `--no-alerts`, `--show-thresholds`
