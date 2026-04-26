---
name: audit-query
description: Read-only query + summary over Coscientist's two append-only audit logs — `audit.log` (PDF fetches by paper-acquire / institutional-access) and `sandbox_audit.log` (every Docker run by reproducibility-mcp). Pure stdlib aggregator. Surfaces per-domain fetch rates, per-tier success counts, recent failures, sandbox error_class breakdown, OOM/timeout incidents, and total wall-time consumed. Distinct from `project-dashboard` (per-project view) — this one is global to the Coscientist cache.
when_to_use: User says "audit summary", "fetch stats", "sandbox usage", "what failed recently", "how many PDFs have I downloaded", "Docker time spent", or wants a forensic view of the audit logs without grepping by hand. Also useful before deleting/rotating logs — see what you'd lose.
---

# audit-query

Two log files, one tool. Both are append-only — this skill never writes.

## Logs

| File | Writer | Format | Records |
|---|---|---|---|
| `~/.cache/coscientist/audit.log` | `paper-acquire/record.py`, `institutional-access` | JSONL (newer) + space-separated key=value (legacy lines from v0.1) | Each PDF fetch: tier, doi/arxiv, status, source domain, size |
| `~/.cache/coscientist/sandbox_audit.log` | `reproducibility-mcp/sandbox.py` | JSONL | Each Docker run: audit_id, image, wall_time, exit_code, timed_out, memory_oom, error_class |

## Subcommands

```bash
# PDF fetch summary (tier breakdown, success/fail counts, recent failures)
uv run python .claude/skills/audit-query/scripts/query.py fetches \
  [--since YYYY-MM-DD] [--domain <substr>] [--limit 20]

# Sandbox run summary (error_class breakdown, OOM/timeout counts, wall-time total)
uv run python .claude/skills/audit-query/scripts/query.py sandbox \
  [--since YYYY-MM-DD] [--error-class timeout|killed_or_oom|...] [--limit 20]

# Combined dashboard (one-screen forensic view)
uv run python .claude/skills/audit-query/scripts/query.py summary \
  [--since YYYY-MM-DD]
```

All output JSON to stdout. `--format md` renders a markdown table.

## What it does NOT do

- Doesn't rotate / truncate / archive logs (that's a future `audit-rotate` skill if needed).
- Doesn't write to any DB or artifact.
- Doesn't fetch or run anything.

## Principles

From `RESEARCHER.md`: read-only, deterministic, surfaces signal without editorializing.
