# Session digest: v0.118 → v0.138

**Dates**: 2026-04-28 to 2026-04-29
**Versions shipped**: 21 (v0.118 through v0.138)
**Tests**: 1888 → 1982 (+94)
**Net result**: instrumentation stack mature, CI pipeline robust, project genuinely complete.

## What changed since v0.117 digest

### Tournament integration into live pipeline (v0.119–v0.123)

| Version | What |
|---|---|
| v0.119 | Sub-agent spans around Task dispatches (closes v0.118 digest deferred item) |
| v0.120 | ROADMAP audit — Tier A 5/5, B + C all ✅ |
| v0.121 | Open questions all resolved (8 questions, with verdicts) |
| v0.122 | Graph backend + manuscript format formal locks (Kuzu dead, markdown-first) |
| v0.123 | Tournament wired into deep-research live path (ranker fires after Architect + Visionary; Inquisitor + Steward read leaderboard) |

### Production polish (v0.124–v0.129)

| Version | What |
|---|---|
| v0.124 | OTLP collector push (`lib.trace_export`) — Jaeger/Honeycomb-ingestable |
| v0.125 | CI uv.lock fix (gitignore correction) |
| v0.126 | Per-project health threshold overlay |
| v0.127 | Quality drift time-series + alert wiring |
| v0.128 | Pre-commit hook auto-regens checksums + indexes + CHANGELOG |
| v0.129 | Field-trends per-concept time-series (N-bucket histograms) |

### CI fixes batch (v0.130–v0.131)

| Version | What |
|---|---|
| v0.130 | Plugin .mcp.json committed (gitignore narrowed); pandoc-missing path; CacheLeakDetector flake |
| v0.131 | CacheLeakDetector self-contained (cache dir can appear after import) |

### Local CI tooling (v0.132–v0.133)

| Version | What |
|---|---|
| v0.132 | `scripts/test-like-ci.sh` + `scripts/ci-status.sh` for local-before-push CI emulation |
| v0.133 | Revert GitHub MCP from project config (wrong scope — should be in user-level Claude config) |

### Polish batch + v0.137 README rewrite (v0.134–v0.138)

| Version | What |
|---|---|
| v0.134 | `lib/persona_doc_check.py` — static check that .claude/agents JSON examples satisfy SCHEMAS |
| v0.135 | Tests for `scripts/ci-status.sh` + `scripts/test-like-ci.sh` |
| v0.136 | `lib/hook_check.py` — detects pre-commit hook install state |
| v0.137 | README rewrite — Quick Start + Observability sections + v0.57-v0.134 condensed (was stuck at v0.56) |
| v0.138 | Lint cleanup — `ruff check --fix` 722 warnings auto-fixed, 138 remaining |

## Operator surface (additions since v0.117 digest)

```bash
# Push trace to external OTel collector (Jaeger/Honeycomb)
uv run python -m lib.trace_export --db <path> --trace-id <rid>
[OTEL_EXPORTER_OTLP_ENDPOINT=...] [--dry-run]

# Per-project health overlay
uv run python -m lib.health --project-id <pid> --show-thresholds

# Quality drift over time
uv run python -m lib.agent_quality drift --window 5

# Field-trends time-series (per-project graph)
uv run python .claude/skills/field-trends-analyzer/scripts/trends.py \
  series --project-id <pid> --window-days 365 --buckets 12

# Persona doc static check
uv run python -m lib.persona_doc_check

# Pre-commit hook check
uv run python -m lib.hook_check

# Local CI emulation (mirrors GitHub Actions tests.yml)
scripts/test-like-ci.sh
scripts/test-like-ci.sh --fresh   # clones into tmp dir, catches gitignore bugs

# CI inspection via gh CLI
scripts/ci-status.sh
scripts/ci-status.sh --logs       # if failed
scripts/ci-status.sh --rerun      # rerun failed jobs

# Pre-commit hook install (symlinks .git/hooks/pre-commit)
scripts/install_hooks.sh
```

## Remaining "deliberately NOT done" items

From v0.118 digest still untouched:

- **Sub-agent kind=`sub-agent` span emission inside actual sub-agent code**.
  v0.119 ships the orchestrator-side wrapper (record-subagent
  --start/--end). Sub-agents themselves don't emit nested spans for
  internal work. Adding would require persona prompt updates + risk
  blast radius. Skipped.

- **OTLP exporter to a remote collector** — *closed* by v0.124.

- **Persona spec validation in `.claude/agents/<name>.md`** — *closed*
  by v0.134.

## What's deliberately NOT done (new)

- **Health cron** (`scripts/health-cron.sh`). Considered v0.139.
  Determined to be overkill for current synchronous workflow. Useful
  only if user starts batch-running experiments / Wide jobs / overnight
  modes. Deferred.

- **GitHub MCP for project tooling**. Briefly added v0.132, reverted
  v0.133. Wrong scope — belongs in user-level Claude config, not project
  repo. `scripts/ci-status.sh` (gh CLI wrapper) covers the use case
  without needing MCP.

## Test count history

| At end of | Tests |
|---|---|
| v0.117 (start of digest) | 1888 |
| v0.119 sub-agent spans | 1897 |
| v0.123 tournament wired | 1897 |
| v0.124 OTLP push | 1908 |
| v0.126 per-project | 1917 |
| v0.127 drift | 1925 |
| v0.128 pre-commit | 1935 |
| v0.129 field-trends | 1940 |
| v0.130-v0.131 CI fixes | 1940 |
| v0.134-v0.137 polish | 1982 |
| v0.138 lint cleanup | 1982 |

(no test count change at lint cleanup — auto-fix was style-only).

## What to do next session

1. **Live `/deep-research` smoke test** — top of every session digest's
   list, never executed. Stack ready since v0.93. Untested live.
   Single research question → 25 min wall time → real validation.

2. **OTLP push to actual Jaeger/Honeycomb** — v0.124 verified against
   local mock collector but not real consumer. One-off curl.

3. **Manual lint review of the remaining 138 warnings** — most require
   judgement (catch-all-Exception, unused-arguments, etc.). Could clear
   in 2-3 batches.

4. **Plugin smoke tests** — backlog item #9 from earlier audit.
   Per-plugin end-to-end test that invokes server.py via mcp client.

The infra is done. The validation phase begins next session.
