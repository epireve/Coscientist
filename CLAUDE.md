# Coscientist — project guide for Claude

This is an academic-research-agent toolkit built as atomic skills. Read this file before working on anything in `.claude/`.

**Companion docs**:
- [`RESEARCHER.md`](./RESEARCHER.md) — principles for any research agent (sub-agents especially). Karpathy-style principle-as-antidote.
- [`ROADMAP.md`](./ROADMAP.md) — where this project is going, what's in flight, what's parked.

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

Only skills move artifacts between states. Kind-specific helpers live in `lib.artifact` (new kinds) and `lib.paper_artifact` (existing PaperArtifact — kept stable, not migrated).

## The contract: run log + project DB

Two SQLite scopes, both using the same schema at `lib/sqlite_schema.sql`:

- **Per-run DB**: `~/.cache/coscientist/runs/run-<run_id>.db` — one deep-research run. Tables driving the pipeline: `runs`, `phases`, `agents`, `queries`, `papers_in_run`, `claims`, `citations`, `breaks`, `notes`, `artifacts`, `audit`. Plus the A5 judgment tables: `novelty_assessments`, `publishability_verdicts`, `attack_findings`, `hypotheses`, `tournament_matches`.
- **Per-project DB**: `~/.cache/coscientist/projects/<project_id>/project.db` — cross-run container. Tables `projects`, `artifact_index`, `graph_nodes`, `graph_edges`.

Resume works by replaying run phases whose `completed_at IS NULL`. Never write directly to either DB — use `.claude/skills/deep-research/scripts/db.py` (runs), `lib/project.py` (projects), or `lib/graph.py` (graph edges).

## The graph layer

Citations, concepts, authors, manuscripts — stored as typed nodes + labeled edges in the project DB. Node IDs: `paper:<cid>`, `concept:<slug>`, `author:<s2_id>`, `manuscript:<mid>`. Edge relations: `cites | cited-by | extends | refutes | uses | depends-on | coauthored | about | authored-by | in-project`.

API is deliberately small (`lib/graph.py`): `add_node`, `add_edge`, `neighbors`, `walk`, `in_degree`, `hubs`. Kuzu is the planned upgrade when volume demands it — the surface here is designed to map cleanly.

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

## Sub-agents (under `deep-research`)

13 personas live in `.claude/agents/`. Each has its own context window and a minimal `tools:` restriction. The orchestrator invokes the deep-research pipeline in order:

`social → grounder → historian → gaper → [BREAK 1] → vision → theorist → rude → synthesizer → [BREAK 2] → thinker → scribe`

Break 0 happens after `social`. The 3 breaks are hard stops that ask the user to confirm/redirect before continuing.

Three additional agents are invoked by other workflows (not the deep-research pipeline):

- `novelty-auditor` — structured novelty assessment via the `novelty-check` gate
- `publishability-judge` — venue-calibrated publishability verdict via `publishability-check`
- `red-team` — named-attack-vector critique of finished work via `attack-vectors`
- `manuscript-drafter` — section-by-section drafting via the `manuscript-draft` skill; reads outline.json + research context, fills each section, tracks word counts and cite keys

These are used by manuscript-audit / manuscript-critique workflows, and by the tournament/evolution subsystem when it lands.

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
