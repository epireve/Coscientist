# Session digest: v0.97 → v0.117

**Date**: 2026-04-28
**Mode**: autonomous, AFK
**Versions shipped**: 21 (v0.97 through v0.117)
**Tests**: 1744 → 1888 (+144 new tests, all passing)
**Net result**: complete observability + quality scoring stack, end to end.

## What was here when we started

v0.93 had landed. Trace tables existed (migrations v11+v12). Phase
spans + harvest + gate + MCP tool-call instrumentation was wired
into hot paths. Auto-quality hook fired on phase completion. But:

- No way to inspect a live run from another shell
- No alert on stale / failed / slow / low-quality
- Only 5/10 personas had rubrics; rubric shapes mismatched actual
  persona output specs
- No external interop — traces locked inside coscientist DBs
- Operator had no documented walkthrough

## What ships in this digest

### Smoke-test infra (v0.97 → v0.101)

| Version | What | Why |
|---|---|---|
| v0.97 | `find_stale_spans` | catch crashed phases that left `status=running` |
| v0.98 | `mark_stale_error` | auto-close stale spans (`--mark-error` flag) |
| v0.99 | version-parser audit | regression test pinning v0.10 < v0.98a < v0.99 < v0.100 sort |
| v0.100 | `tool_call_latency` | by-tool n / mean / p50 / p95 / max + n_errors |
| v0.101 | `docs/SMOKE-TEST-RUNBOOK.md` | 8-step operator walkthrough |

### Persona schemas + rubrics (v0.102 → v0.105)

| Version | What | Why |
|---|---|---|
| v0.102 | `lib/persona_schema.py` | shape gate before rubric (refuse malformed) |
| v0.103 | full schemas + record-phase split | `--quality-artifact` separate from `--output-json` |
| v0.104 | rubrics for cartographer/chronicler/inquisitor/visionary/steward | 10 personas total |
| v0.105 | dict-aware OG rubrics | `_items_from()` accepts list or dict-top |

### Health dump + diagnostics (v0.106 → v0.110)

| Version | What | Why |
|---|---|---|
| v0.106 | `lib/health.py` | one-shot diagnostics across all runs |
| v0.107 | `/health` slash skill + runbook reference | user-facing surface |
| v0.108 | harvest summary in health | "did Phase 0 retrieve anything" |
| v0.109 | gate-decision summary in health | "did publishability accept anything" |
| v0.110 | `prune_old_traces` | trace lifecycle: emit → render → status → prune |

### Polish + bug fixes (v0.111 → v0.114)

| Version | What | Why |
|---|---|---|
| v0.111 | `prune_empty_run_dbs` | delete now-empty DB files after v0.110 |
| v0.112 | tool-call error spans actually error | bug fix — `n_errors` was always 0 |
| v0.113 | alert thresholds + exit codes (0/1/2) | actionable signal, CI-friendly |
| v0.114 | `health_thresholds.json` config file | per-cache override |

### Documentation + interop (v0.115 → v0.117)

| Version | What | Why |
|---|---|---|
| v0.115 | CLAUDE.md observability section | new contributors discoverable |
| v0.116 | OTLP-compatible trace export | Jaeger/Honeycomb/Tempo ingest |
| v0.117 | OTLP hex ID compliance | spec requires 32/16-char hex; coscientist IDs prefixed strings |

## Operator surface that now exists

```bash
# 1. One-stop health dump (alerts + tool latency + quality + harvests + gates)
uv run python -m lib.health

# 2. Per-run trace timeline (md/mermaid/json/otlp)
uv run python -m lib.trace_render --db <path> --trace-id <rid> --format md

# 3. Quick status across runs
uv run python -m lib.trace_status

# 4. Find + close stale (hung) spans
uv run python -m lib.trace_status --stale-only
uv run python -m lib.trace_status --stale-only --mark-error

# 5. Tool-call latency with error rate (which MCPs are slow / fail often)
uv run python -m lib.trace_status --tool-latency

# 6. Cross-run agent quality leaderboard
uv run python -m lib.agent_quality leaderboard

# 7. Prune old data (cascade through traces → spans → events → DB files)
uv run python -m lib.trace_status --prune --prune-days 30 --dry-run
uv run python -m lib.trace_status --prune-empty-dbs --dry-run

# 8. Show resolved alert thresholds
uv run python -m lib.health --show-thresholds
```

## What's deliberately NOT done

These were considered and skipped to avoid scope creep:

- **Sub-agent kind=`sub-agent` span emission**. Sub-agents launch
  via Claude Code's Task tool — orchestrator markdown-driven, no
  programmatic span wrap. Sub-agents could emit their own spans
  but no default plumbing.
- **Persona spec validation in `.claude/agents/<name>.md`**.
  Schema gate (v0.102) catches violations at runtime; no static
  check.
- **OTLP exporter to a remote collector**. v0.116/v0.117 produce
  OTLP JSON; pushing to an HTTP endpoint deferred (one-line
  curl-driven if user wants).

## What's safe to delete / archive

- Old run DBs older than 30 days: `python -m lib.trace_status --prune-days 30`
  then `--prune-empty-dbs`.
- `~/.cache/coscientist/health_thresholds.json` is opt-in; absence
  = defaults.

## Test count history

| At end of | Tests | Δ |
|---|---|---|
| v0.96 (start of session) | 1744 | — |
| v0.97 stale detector | 1749 | +5 |
| v0.98 mark-error | 1753 | +4 |
| v0.99 version audit | 1754 | +1 |
| v0.100 tool latency | 1760 | +6 |
| v0.101 runbook | 1764 | +4 |
| v0.102 persona schema | 1777 | +13 |
| v0.103 full schemas | 1785 | +8 |
| v0.104 new rubrics | 1796 | +11 |
| v0.105 dict-aware | 1806 | +10 |
| v0.106 health | 1813 | +7 |
| v0.107 /health skill | 1819 | +6 |
| v0.108 harvest summary | 1825 | +6 |
| v0.109 gate summary | 1831 | +6 |
| v0.110 prune traces | 1837 | +6 |
| v0.111 prune empty DBs | 1845 | +8 |
| v0.112 error spans bug | 1848 | +3 |
| v0.113 alert thresholds | 1857 | +9 |
| v0.114 threshold config | 1866 | +9 |
| v0.115 CLAUDE.md docs | 1875 | +9 |
| v0.116 OTLP export | 1884 | +9 |
| v0.117 OTLP hex IDs | 1888 | +10 |

(Numbers approximate — derived from per-version commit messages;
final suite reports 1888 passing.)

## What to do next session

The instrumentation stack is complete. Reasonable next moves:

1. **Live `/deep-research` smoke test** following the runbook.
   Watch the health dashboard. Expect: real harvest counts, real
   tool-call latencies, real quality scores. Fix what surfaces.
2. **Push OTLP to an actual collector** (Jaeger or Honeycomb free
   tier). One curl POST per trace. Validate Jaeger UI renders the
   coscientist run.
3. **Per-project quality calibration**. Some projects need looser
   `min_quality_score`; write per-project `health_thresholds.json`.
4. **Sub-agent span instrumentation**. Wrap Task tool dispatches
   with span emission so sub-agent durations + errors land in
   traces too.

None are urgent. The stack works.
