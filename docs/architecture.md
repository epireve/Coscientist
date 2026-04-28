# Architecture

Coscientist is built Lego-style: atomic skills, custom MCP servers,
and Claude Code plugins, all composing through artifacts on disk.
This doc maps the moving parts.

## Two-tier mental model

```
                   ┌─────────────────────────────────────┐
                   │  Claude Code agent (you)            │
                   └──┬──────────────────────────────────┘
                      │ slash commands · MCP tools · skill invocations
       ┌──────────────┼─────────────┬─────────────────────┐
       ▼              ▼             ▼                     ▼
 ┌──────────┐  ┌────────────┐  ┌──────────┐         ┌──────────────┐
 │ skills/  │  │ agents/    │  │ mcp/     │         │ external     │
 │ (CLI)    │  │ (personas) │  │ servers  │         │ MCPs         │
 └────┬─────┘  └────┬───────┘  └────┬─────┘         └──────┬───────┘
      │             │               │                       │
      └──────┬──────┴───────────────┴───────────────────────┘
             ▼
   ~/.cache/coscientist/    ← Single source of artifact truth
   ├── papers/<cid>/
   ├── manuscripts/<mid>/
   ├── experiments/<eid>/
   ├── runs/run-<rid>.db    ← per-run SQLite
   └── projects/<pid>/
       └── project.db        ← per-project SQLite
```

**Tier 1 — orchestration** (Claude Code agent + sub-agents):
read SKILL.md frontmatter, invoke skill scripts via Bash, dispatch
sub-agents via the Task tool, call MCP tools via JSON-RPC.

**Tier 2 — artifacts on disk**: every skill reads/writes one or
more artifact directories or SQLite tables. No skill calls another
skill directly. Re-running a skill is idempotent.

## Artifact contract

Every artifact lives under `~/.cache/coscientist/<kind>/<id>/` and
has at least:

| File | Required | Purpose |
|---|---|---|
| `manifest.json` | yes | `id`, `kind`, `state`, timestamps, source-tracking |
| `metadata.json` | yes | Title, authors, year, abstract (where applicable) |
| `<kind>-specific files` | varies | `content.md`, `frontmatter.yaml`, `figures/`, … |

The state machine for each kind is enumerated in `lib.artifact.STATES`:

| Kind | States |
|---|---|
| paper | `discovered → triaged → acquired → extracted → read → cited` |
| manuscript | `drafted → audited → critiqued → revised → submitted → published` |
| experiment | `designed → preregistered → running → completed → analyzed → reproduced` |
| dataset | `registered → deposited → versioned` |
| figure | `drafted → styled → finalized` |
| review | `drafted → submitted` |
| grant | `drafted → submitted → awarded\|rejected` |
| protocol | `drafted → approved → executed` |
| negative-result | `logged → analyzed → shared` |

Only skills move artifacts between states. The state machine is
enforced by gate scripts (e.g. `paper-acquire` refuses to fetch a
paper not in `triaged` state).

## SQLite scopes

Two distinct DB scopes, both using `lib/sqlite_schema.sql`:

| DB | Path | Purpose |
|---|---|---|
| Per-run | `~/.cache/coscientist/runs/run-<rid>.db` | One deep-research run. Phases, papers_in_run, claims, citations, breaks, hypotheses |
| Per-project | `~/.cache/coscientist/projects/<pid>/project.db` | Cross-run container. Projects, artifact_index, graph_nodes, graph_edges, manuscripts, reading_state |

Both go through `lib.migrations.ensure_current` on every open.
WAL mode enforced via `lib.cache.connect_wal` (v0.66 + v0.71 +
v0.82).

## Migration framework

Two paths:

1. **SQL-only DDL**: add `lib/migrations_sql/v<N>.sql` + a
   `_ensure_v<N>_tables` helper that runs `executescript`.
2. **In-code**: add `_ensure_v<N>_columns(con)` for ALTER TABLE
   logic SQLite can't gate.

`lib/migrations.py::ALL_VERSIONS` must remain contiguous starting
at 1. Enforced by `tests/test_migration_monotonicity.py`.

Every new table mirrored into `lib/sqlite_schema.sql` so fresh DBs
work without migrations. Enforced by `tests/test_schema_parity.py`.

## Sub-agent phases

40+ personas in `.claude/agents/`, grouped into 8 phases:

| Phase | Personas | Job |
|---|---|---|
| **A. Expedition** | scout, cartographer, chronicler, surveyor, synthesist, architect, inquisitor, weaver, visionary, steward | 10-agent deep-research pipeline |
| **B. Workshop** | drafter, verifier, panel, diviner, reviser, compositor | Manuscript subsystem |
| **C. Tribunal** | novelty-auditor, publishability-judge, red-team, advocate, peer-reviewer | Critical judgment |
| **D. Laboratory** | experimentalist, curator, funder | Experiments + datasets + grants |
| **E. Tournament** | ranker, mutator | Pairwise Elo + evolution |
| **F. Archive** | librarian, stylist, diarist, watchman, indexer | Personal knowledge |
| **G. Wide Research** | wide-triage, wide-read, wide-rank, wide-compare, wide-survey, wide-screen | One per Wide TaskSpec |
| **H. Self-play debate** | debate-pro, debate-con, debate-judge | Adversarial verdict sharpening |

Each agent is a `.claude/agents/<name>.md` with YAML frontmatter
and a body describing what "done" looks like. Sub-agents have
independent context windows.

## Three research modes

`lib/mode_selector.py` picks the right mode automatically:

| Mode | When | Cost | Time |
|---|---|---|---|
| **Quick** | One-shot, no per-item iteration | $0.05–0.30 | 30s–2m |
| **Deep** | Open-ended research question | $3–5 | 15–25 min |
| **Wide** | N items processed identically (10 ≤ N ≤ 250) | $5–30 (cap $50) | 5–20 min |

Wide → Deep handoff via `db.py init --seed-from-wide`.

## Plugin distribution

Coscientist ships as a Claude Code plugin marketplace at
`epireve/coscientist`. Four plugins:

| Plugin | What it adds |
|---|---|
| `coscientist-deep-research` | 11 skills + 10 agents + `/deep-research` slash command |
| `coscientist-retraction-mcp` | MCP server: Crossref + PubPeer retraction lookups |
| `coscientist-manuscript-mcp` | MCP server: .docx / .tex / .md → AST |
| `coscientist-graph-query-mcp` | MCP server: read-only graph primitives |

Each plugin has its own `pyproject.toml`, `.mcp.json`, and
`CHECKSUMS.txt` for supply-chain verification.

## Test discipline

Pure-stdlib custom harness at `tests/harness.py` — no pytest.
Auto-discovery walks `tests/test_*.py`, picks up every
`class XTests(TestCase)`. Cache-leak detector runs last to catch
tests that bypass `isolated_cache()`.

| Tier | Examples |
|---|---|
| Unit | parser regex, Elo math, graph BFS |
| Integration | tournament lifecycle, scan→persist round trip |
| Smoke | CLI subprocess invocation |
| Parity | doc generators (SKILLS.md, MCP_SERVERS.md, CHANGELOG.md) |
| Invariant | migration monotonicity, schema parity, plugin manifest |

1600+ tests today. Suite green is a hard prerequisite for every commit.

## What this architecture is not

- **Not a monolith**: every skill is independently runnable + testable.
- **Not LLM-coupled in `lib/`**: zero LLM calls in `lib/`; LLM use
  is confined to sub-agents (which run in their own context windows).
- **Not service-oriented**: SQLite + filesystem only. No daemons,
  no API server. Restart safe.
- **Not auto-magical**: every state transition is an explicit
  command. No background workers.

## See also

- [`README.md`](../README.md) — what + how to install
- [`CLAUDE.md`](../CLAUDE.md) — agent-facing project guide
- [`CONTRIBUTING.md`](../CONTRIBUTING.md) — how to add new pieces
- [`RESEARCHER.md`](../RESEARCHER.md) — sub-agent research principles
- [`docs/research-loop.md`](./research-loop.md) — narrative of the
  10-agent Expedition pipeline
