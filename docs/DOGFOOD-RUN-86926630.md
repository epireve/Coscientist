# Dogfood run 86926630 — findings

**Question**: How does sub-agent context isolation in multi-agent LLM systems affect task completion reliability?

**Date**: 2026-04-30
**Mode**: deep
**Phases completed**: scout (Phase 0) + Break 0 resolved
**Status**: paused mid-Phase-1 (cartographer/chronicler/surveyor batch dispatched but not consumed)

## Why paused

5 actionable bugs surfaced before Phase-1 dispatch was worth doing. Path B vindicated — real run found in 5 minutes what synthetic tests missed in 28 versions.

## Findings

### #1 — Semantic Scholar MCP 403 / circuit-breaker

Returns `403 Forbidden` then opens circuit breaker (5 failures threshold). Was working 2026-04-27 per ROADMAP entry; broken again now. Probably API rate-limit from prior burst.

**Trace**:
```
mcp__semantic-scholar__search_papers(query="multi-agent LLM context isolation task reliability", limit=10)
→ HTTPStatusError 403 → 3 retries → CircuitBreakerError E3004
```

**Severity**: Medium (we have OpenAlex + Consensus as fallbacks)
**Proposed fix v0.188**: `lib.health` flags MCPs returning >X% errors over rolling window. `lib.source_selector` consults health and auto-skips degraded sources from harvest plan.

### #2 — arXiv MCP relevance ranking broken — CLOSED v0.189

Query `multi-agent LLM context isolation reliability` returned 10 papers, all dated 2026-04-29, all unrelated:
1. "Turning the TIDE: Cross-Architecture Distillation for Diffusion Large Language Models"
2. "Optimizing Dynamic Metasurface Antenna Configurations..."
3. "Hyper Input Convex Neural Networks..."
4. "Select to Think: Unlocking SLM Potential..."

Looks date-sorted, not relevance-sorted. None of the obvious relevant papers (AutoGen, MAST, SagaLLM) surfaced.

**Severity**: High (paper-search MCP is one of 4 search sources; broken sort = 25% capacity loss)
**Proposed fix v0.189**: `mcp__paper-search__search_arxiv` wrapper needs `sort=relevance` default. If unfixable, route relevant queries to OpenAlex/Consensus instead.

### #3 — `papers_in_run.added_in_phase` uses legacy alias — CLOSED v0.190

Scout sub-agent wrote rows with `added_in_phase='social'` instead of `'scout'`. Aliasing layer works but DB persists pre-rebrand name. Inconsistent with v0.46.4 SEEKER → Expedition rename.

**Severity**: Low (alias resolves; cosmetic-only at query time)
**Proposed fix v0.190**: scout's record path writes canonical phase name (`scout`). Schema migration v16 renames existing rows. Same for grounder→cartographer, historian→chronicler, gaper→surveyor, theorist→architect, thinker→visionary, scribe→steward.

### #4 — `db.py record-phase --output-json` rejects inline JSON

```bash
db.py record-phase --output-json '{"papers_seeded": 6}'
→ FileNotFoundError: '{"papers_seeded": 6}'
```

Treats argument as file path. Inline JSON literal rejected. Forces user to write tmpfile.

**Severity**: High (developer-facing, caught in active dogfood, not edge case)
**Proposed fix v0.191**: argparse heuristic — try parse as JSON first, fall back to file path. OR rename to `--output-json-file` + add `--output-json-inline`. OR document the file-only behavior loudly in `--help`.

### #5 — Scout `thin_harvest` threshold ignores orchestrator intent — CLOSED v0.192

Scout reports `stopped_because: thin_harvest` when papers_seeded (6) < hard threshold (50). But orchestrator deliberately supplied 6 (the curated MCP results). No path to say "I know it's thin, that's fine."

**Severity**: Medium (sub-agent self-classifies as failure when orchestrator says it's complete)
**Proposed fix v0.192**: scout SKILL.md gains `--allow-thin` flag or reads per-harvest threshold from `harvest.py status`. Don't fail-classify when orchestrator's harvest budget was deliberately small.

### #6 — Consensus 3-result cap without auth — CLOSED v0.193

Every consensus query returns top-3 + sign-up nag. 60% of typical search budget (10 results) wasted.

**Severity**: Low (works as designed by Consensus)
**Proposed fix v0.193**: `lib.source_selector.call_budget` marks consensus as `requires_auth=true`. When unauth detected, treat each consensus call as 3-result harvest (not 10). Plan accordingly.

## Triage / proposed sequence

**v0.188** — degraded-source health flag (highest leverage, makes future runs more robust)
**v0.189** — arXiv relevance fix (or document the limitation)
**v0.191** — `record-phase --output-json` inline-vs-file (developer pain, fix today-easy)
**v0.190** — phase-name canonicalization + migration v16 (cleanest at low volume)
**v0.192** — scout thin-harvest semantics (smallest, fix when touching scout next)
**v0.193** — consensus auth-aware budgeting (smallest, drop into source_selector)

## Run artifacts

- `~/.cache/coscientist/runs/run-86926630.db` — paused at Phase 1 entry
- `~/.cache/coscientist/runs/run-86926630/inputs/scout-phase0.json` — 6 harvested papers
- 6 `papers_in_run` rows (state=`seed`)
- 6 paper artifact stubs under `~/.cache/coscientist/papers/`
