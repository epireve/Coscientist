# Coscientist — project guide for Claude

This is an academic-research-agent toolkit built as atomic skills. Read this file before working on anything in `.claude/`.

**Companion docs**:
- [`RESEARCHER.md`](./RESEARCHER.md) — principles for any research agent (sub-agents especially). Karpathy-style principle-as-antidote.
- [`ROADMAP.md`](./ROADMAP.md) — where this project is going, what's in flight, what's parked.

## Three research modes (`lib/mode_selector.py`)

| Mode | When | Cost | Time |
|---|---|---|---|
| **Quick** | Single concrete one-shot, no per-item iteration | $0.05–0.30 | 30s–2m |
| **Deep** | Open-ended research question — runs the 10-phase Expedition | $3–5 | 15–25 min (after v0.51 parallelization) |
| **Wide** | N items processed identically (10 ≤ N ≤ 250) — orchestrator-worker fan-out | $5–30 (cap $50) | 5–20 min |

`select_mode(question, items=, explicit_mode=)` → `ModeRecommendation` with confidence + warnings. Wide → Deep handoff via `db.py init --seed-from-wide`.

## Recent landings (v0.51–v0.114)

- v0.51 Phase 1 parallel dispatch (`db.py next-phase-batch`)
- v0.52 search-strategy depth (PICO/SPIDER + adversarial critique + era detection + cross-persona disagreement + concept velocity)
- v0.53 Wide Research mode + Wide → Deep handoff (migration v8: `runs.parent_run_id`, `runs.seed_mode`)
- v0.54 brief richness — hypothesis cards, evidence tables, discussion questions, RUN-RECOVERY.md
- v0.55 A5 trio — `gap-analyzer`, `contribution-mapper`, `venue-match`
- v0.56 self-play debate — PRO + CON + JUDGE for high-stakes verdicts
- **v0.89–v0.92** observability foundation — execution traces (migration v11), agent quality scoring (migration v12), trace renderer
- **v0.93–v0.96** instrumentation hookup — phase / harvest / gate / MCP tool-call spans (env-var context), auto-quality hook on phase complete, cross-run leaderboard
- **v0.97–v0.100** smoke-test infra — stale-span detector + auto-close, version-parser audit (v0.100 sorts after v0.99), tool-call latency aggregator
- **v0.101–v0.105** persona schemas + rubrics — `--quality-artifact` separate from `--output-json`, 10 personas registered, dict-aware OG rubrics
- **v0.106–v0.110** `lib.health` one-shot diagnostics + `/health` skill + harvest/gate summaries + trace pruning
- **v0.111–v0.114** prune empty DBs, tool-call error spans actually error (bug fix), alert thresholds + exit codes, threshold config file

Every landing has a test class registered in `tests/run_all.py`. Run `uv run python tests/run_all.py` for the full suite (~1860 tests).

## The contract: polymorphic artifacts

Every skill reads/writes one of several kinds of artifact, each with its own state machine but a shared directory layout and manifest structure.

```
~/.cache/coscientist/
  papers/<paper_id>/           # kind=paper         — lib.paper_artifact.PaperArtifact
  manuscripts/<mid>/           # kind=manuscript    — lib.artifact.ManuscriptArtifact
  experiments/<eid>/           # kind=experiment    — lib.artifact.ExperimentArtifact
  datasets/<did>/              # kind=dataset
  figures/<fid>/               # kind=figure
  reviews/<rid>/                # kind=review
  grants/<gid>/                 # kind=grant
  journal/<jid>/                # kind=journal-entry
  protocols/<pid>/              # kind=protocol
  negative_results/<id>/        # kind=negative-result (v0.31)
  dmps/<dmp_id>/                # data management plans (v0.32)
  irb/<application_id>/         # IRB applications (v0.32)
  registered_reports/<rr_id>/   # Stage 1/2 RR pathway (v0.32)
  runs/run-<run_id>.db          # deep-research run logs (SQLite)
  projects/<project_id>/        # project-level container
    project.db                  # project-scoped SQLite (tables: projects,
                                # artifact_index, graph_nodes, graph_edges, etc.)
```

### Paper artifact layout (canonical)

The pattern all other kinds follow:

```
papers/<paper_id>/
  manifest.json       # canonical_id, doi, arxiv_id, state, sources_tried[]
  metadata.json       # title, authors, venue, year, abstract, tldr, claims[]
  content.md          # structured markdown (post-extract)
  frontmatter.yaml
  figures/            # png/svg
  figures.json        # [{id, caption, page, bbox, type}]
  tables/             # .md + .csv
  equations.json
  references.json     # parsed bibliography, DOIs resolved
  raw/                # original pdf/html
  extraction.log
  novelty_assessment.json   # when novelty-auditor has run
  attack_findings.json      # when red-team has run
```

`paper_id` format: slugified `<first_author_last>_<year>_<short_title>` with a 6-char hash suffix. Use `lib.cache.paper_dir(canonical_id)` — never hand-build paths.

### Per-kind state machines (in `lib.artifact.STATES`)

- paper: `discovered → triaged → acquired → extracted → read → cited`
- manuscript: `drafted → audited → critiqued → revised → submitted → published`
- experiment: `designed → preregistered → running → completed → analyzed → reproduced`
- dataset: `registered → deposited → versioned`
- figure: `drafted → styled → finalized`
- review: `drafted → submitted`
- grant: `drafted → submitted → awarded|rejected`
- protocol: `drafted → approved → executed`
- negative-result: `logged → analyzed → shared`

Only skills move artifacts between states. Kind-specific helpers live in `lib.artifact` (new kinds) and `lib.paper_artifact` (existing PaperArtifact — kept stable, not migrated).

## The contract: run log + project DB

Two SQLite scopes, both using the same schema at `lib/sqlite_schema.sql`:

- **Per-run DB**: `~/.cache/coscientist/runs/run-<run_id>.db` — one deep-research run. Tables driving the pipeline: `runs`, `phases`, `agents`, `queries`, `papers_in_run`, `claims`, `citations`, `breaks`, `notes`, `artifacts`, `audit`. Plus the A5 judgment tables: `novelty_assessments`, `publishability_verdicts`, `attack_findings`, `hypotheses`, `tournament_matches`.
- **Per-project DB**: `~/.cache/coscientist/projects/<project_id>/project.db` — cross-run container. Tables `projects`, `artifact_index`, `graph_nodes`, `graph_edges`.

Resume works by replaying run phases whose `completed_at IS NULL`. Never write directly to either DB — use `.claude/skills/deep-research/scripts/db.py` (runs), `lib/project.py` (projects), or `lib/graph.py` (graph edges).

## The graph layer

Citations, concepts, authors, manuscripts — stored as typed nodes + labeled edges in the project DB. Node IDs: `paper:<cid>`, `concept:<slug>`, `author:<s2_id>`, `manuscript:<mid>`. Edge relations: `cites | cited-by | extends | refutes | uses | depends-on | coauthored | about | authored-by | in-project`.

API is deliberately small (`lib/graph.py`): `add_node`, `add_edge`, `neighbors`, `walk`, `in_degree`, `hubs`. Kuzu is the planned upgrade when volume demands it — the surface here is designed to map cleanly.

## Observability stack (v0.89–v0.114)

Three-table OpenTelemetry-style trace model lives in every coscientist DB (added by migrations v11+v12):

- **`traces`** — one row per run. Status: running / ok / error.
- **`spans`** — kind ∈ {`phase`, `sub-agent`, `tool-call`, `gate`, `persist`, `harvest`, `other`}. Auto-records `started_at` / `ended_at` / `duration_ms` / `status` / `error_kind` / `error_msg` / `attrs_json`.
- **`span_events`** — append-only side notes per span (e.g. `harvest_write` payload, `schema_error` from v0.102 gate).
- **`agent_quality`** — per-persona auto-rubric or LLM-judge scores. 10 personas registered.

### How to instrument

- **From Python**: `from lib.trace import start_span` — context manager that auto-closes on exit, captures exceptions as `status='error'`.
- **From MCP servers**: `lib.trace.maybe_emit_tool_call(tool_name, args_summary, result_summary, error=...)` reads `COSCIENTIST_TRACE_DB` + `COSCIENTIST_TRACE_ID` env vars set by the orchestrator. Best-effort — silent no-op if env unset.
- **From gates**: `lib.gate_trace.emit_gate_span(run_id, gate_name, verdict, errors, ...)`.
- **Auto-quality hook**: `db.py record-phase --complete --output-json X --quality-artifact Y` runs `persona_schema.validate` on `--output-json` (schema gate) and `agent_quality.score_auto` on `--quality-artifact` (rubric).

### How to inspect

| Question | Command |
|---|---|
| What's running, what's stuck, slowest tools, lowest-quality agents? | `uv run python -m lib.health` (exits non-zero on alerts) |
| One run's full timeline? | `uv run python -m lib.trace_render --db <path> --trace-id <rid>` |
| Span counts + latest phase per run? | `uv run python -m lib.trace_status [--run-id X]` |
| Spans still `running` past N min? | `uv run python -m lib.trace_status --stale-only [--mark-error]` |
| Cross-run agent quality leaderboard? | `uv run python -m lib.agent_quality leaderboard` |
| Tool-call latency (p50/p95/error rate)? | `uv run python -m lib.trace_status --tool-latency` |
| Delete old data? | `uv run python -m lib.trace_status --prune --prune-days 30` then `--prune-empty-dbs` |

### Health alerts

`lib.health.evaluate_alerts(report)` derives named alerts from thresholds. Defaults in `lib.health.DEFAULT_THRESHOLDS`; override per-cache via `~/.cache/coscientist/health_thresholds.json`. CLI exit codes: `0` clean, `1` warns only, `2` any crit. CI/cron-friendly.

### Instrumentation invariants

1. **Best-effort.** Tracing failures NEVER break the parent flow. All emit helpers wrap in `try/except: pass`.
2. **Pure stdlib.** `lib/trace.py`, `lib/trace_status.py`, `lib/trace_render.py`, `lib/health.py`, `lib/agent_quality.py`, `lib/persona_schema.py` — no external deps.
3. **WAL mode.** All DB writes via `lib.cache.connect_wal`.
4. **Schema-as-single-source.** `lib/sqlite_schema.sql` mirrors every migration; `lib/migrations.py` applies forward.

See `docs/SMOKE-TEST-RUNBOOK.md` for the operator walkthrough.

## Skill composition rules

1. **Skills don't call other skills.** They read/write artifacts. The orchestrator (`deep-research`) is the only place that invokes a sequence.
2. **MCPs over custom code.** Prefer Consensus / paper-search-mcp / academic-mcp / Semantic Scholar over writing HTTP clients. Scripts are for local logic (extraction, browser automation, DB).
3. **Artifacts go in the cache, not the repo.** `~/.cache/coscientist/` is gitignored at the user level. Nothing in this repo should reference `/home/user/...`.
4. **Everything logs.** PDF fetches especially — `institutional-access` writes every download to `~/.cache/coscientist/audit.log` with DOI + timestamp + tier.

## Guardrails (non-negotiable)

- `paper-acquire` MUST check `manifest.json["state"] == "triaged"` and `manifest.json["triage"]["sufficient"] == false` before fetching any PDF. No speculative downloads.
- `institutional-access` MUST honor 10s delay per publisher domain. Use `lib.rate_limit.wait(domain)`.
- Sci-Hub tier is disabled unless `COSCIENTIST_ALLOW_SCIHUB=1`. Off by default.
- Playwright runs headful with persistent context (not `--headless`) to match a real profile.

## Sub-agents (under `deep-research` and elsewhere)

40+ personas live in `.claude/agents/`. Each has its own context window and a minimal `tools:` restriction. Grouped into 8 phases (A–H).

### Phase A — The Expedition (deep-research pipeline)

`scout → cartographer ║ chronicler ║ surveyor → [BREAK 1] → synthesist → architect → inquisitor → weaver → [BREAK 2] → visionary → steward`

Phase 1 (cartographer/chronicler/surveyor) runs as a single concurrent batch (v0.51 — see `lib/phase_groups.py`). All other transitions sequential.

Break 0 fires after `scout`. The 3 breaks are hard stops that prompt the user to confirm/redirect before continuing. Old SEEKER names — social, grounder, historian, gaper, vision, theorist, rude, synthesizer, thinker, scribe — accepted as aliases via `db.py PHASE_ALIASES` for in-flight runs.

### Phase B — The Workshop (manuscript subsystem)

`verifier`, `panel`, `diviner`, `drafter`, `compositor`, `reviser`.

- `drafter` — section-by-section drafting via `manuscript-draft`
- `compositor` — pandoc export via `manuscript-format`
- `reviser` — respond-to-reviewers via `manuscript-revise`

### Phase C — The Tribunal (critical judgment)

`novelty-auditor`, `publishability-judge`, `red-team`, `advocate`, `peer-reviewer`. Used by manuscript-audit / manuscript-critique workflows.

### Phase D — The Laboratory (experimentation)

`experimentalist`, `curator`, `funder`.

### Phase E — The Tournament (hypothesis evolution)

`ranker`, `mutator`. Pairwise Elo + child-mutation pattern (Google Co-scientist).

### Phase F — The Archive (knowledge layer)

`librarian`, `stylist`, `diarist`, `watchman`, `indexer`.

### Phase G — Wide Research sub-agents (v0.53.6)

`wide-triage`, `wide-read`, `wide-rank`, `wide-compare`, `wide-survey`, `wide-screen`. One per Wide TaskSpec type. Dispatched by `wide.py` to process N items in parallel (orchestrator-worker fan-out, cap 30 concurrent).

### Phase H — Self-play debate (v0.56)

`debate-pro`, `debate-con`, `debate-judge`. PRO + CON argue opposing sides of a verdict (novelty / publishability / red-team); judge scores both and commits. Sharpens single-pass output for borderline calls. See `lib/debate.py` + `.claude/skills/debate/`.

All sub-agents:

- Follow `RESEARCHER.md` principles
- Declare their `tools:` restrictively in frontmatter (minimal-scope)
- Describe **what done looks like**, not procedural steps
- End with an **Exit test** clause they must pass before handing back
- Consume artifacts + DB state — they never touch raw PDFs or publisher websites directly

## When adding a new skill

1. Create `.claude/skills/<name>/SKILL.md` with frontmatter (`name`, `description`, `when_to_use`).
2. Read from / write to the paper artifact contract only.
3. If it needs a script, put it in `.claude/skills/<name>/scripts/` and make it CLI-invocable with explicit `--paper-id` / `--run-id` args.
4. Update this file's skill list.

## When adding a new publisher adapter

Add `.claude/skills/institutional-access/scripts/adapters/<publisher>.py` implementing `fetch_pdf(doi, page, storage_state) -> Path`. Adapters are ~20 lines each. Keep them tiny — when a publisher changes their HTML, the failure mode is "fall through to Tier 2 (browser-use)", not a broken skill.

## External projects this borrows from

- [anvix9/basis_research_agents](https://github.com/anvix9/basis_research_agents) (MIT) — 10-agent personas, eval scripts, SQLite schema concept, resume logic
- [timf34/arxiv2md](https://github.com/timf34/arxiv2md) (MIT) — used as a dependency (`arxiv2markdown` on PyPI)
- [openags/paper-search-mcp](https://github.com/openags/paper-search-mcp) (MIT) — used as an MCP, not vendored
- [LinXueyuanStdio/academic-mcp](https://github.com/LinXueyuanStdio/academic-mcp) (MIT) — used as an MCP, not vendored

## Working principles (for code in this repo)

Shaped after [karpathy-skills](https://github.com/forrestchang/andrej-karpathy-skills). These govern how we *build* Coscientist. The sibling `RESEARCHER.md` governs how sub-agents *do* research.

### 1. Think Before Coding

Don't silently assume. When a task is ambiguous (which MCP? which publisher adapter? which artifact field?) name the assumption or ask. Multiple interpretations usually exist; pick explicitly.

*The test*: before a non-trivial edit, can you state the assumption you made and where someone else would reasonably have chosen differently?

### 2. Simplicity First

No speculative abstractions. No "maybe we'll want this later" generalizations. Three similar adapters are better than a premature `AdapterBase`. Every layer of indirection is paid for in debugging.

*The test*: would a senior engineer reading this diff say "this is overcomplicated for what it does"?

### 3. Surgical Changes

When a task is "fix X", fix X. Don't refactor adjacent code, rename unrelated vars, or tidy imports that weren't yours. Match existing style. Remove only code the current change itself orphaned.

*The test*: does every line of this diff serve the requested change, or did you sweep in improvements?

### 4. Goal-Driven Execution

Prefer declarative success criteria over procedural steps. Sub-agent prompts should tell the agent *what done looks like* so it can loop until true, not *do step 1, then step 2*. Applies to `SKILL.md` files too.

*The test*: if the agent got interrupted mid-task, could it self-diagnose how close to done it is from what's on disk — or does it need to retrace your steps?

## Git

Work happens on branch `main`.
