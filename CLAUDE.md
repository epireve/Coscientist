# Coscientist — project guide for Claude

This is an academic-research-agent toolkit built as atomic skills. Read this file before working on anything in `.claude/`.

**Companion docs**:
- [`RESEARCHER.md`](./RESEARCHER.md) — principles for any research agent (sub-agents especially). Karpathy-style principle-as-antidote.
- [`ROADMAP.md`](./ROADMAP.md) — where this project is going, what's in flight, what's parked.

## The contract: paper artifact

Every skill reads/writes one canonical artifact layout. Never invent new fields — extend this:

```
~/.cache/coscientist/papers/<paper_id>/
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
```

`paper_id` format: slugified `<first_author_last>_<year>_<short_title>` with a 6-char hash suffix for uniqueness. Use `lib.cache.paper_dir(canonical_id)` — never hand-build paths.

Per-paper state machine: `discovered → triaged → acquired → extracted → read → cited`. Stored in `manifest.json["state"]`. Only skills move papers between states.

## The contract: run log

Deep research runs persist to SQLite at `.coscientist/run-<run_id>.db`. Schema in `lib/sqlite_schema.sql`. Tables: `runs`, `phases`, `agents`, `queries`, `papers_in_run`, `claims`, `citations`, `breaks`, `notes`, `artifacts`, `audit`.

Resume works by replaying phases whose `completed_at IS NULL`. Never write directly — use `.claude/skills/deep-research/scripts/db.py` helpers.

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

10 personas live in `.claude/agents/`. Each has its own context window. The orchestrator invokes them in order:

`social → grounder → historian → gaper → [BREAK 1] → vision → theorist → rude → synthesizer → [BREAK 2] → thinker → scribe`

Break 0 happens after `social`. The 3 breaks are hard stops that ask the user to confirm/redirect before continuing.

Sub-agents consume artifacts + the run DB as their context. They never touch raw PDFs or publisher websites — they call the atomic skills.

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

Work happens on branch `claude/analyze-research-agent-repos-DdVMQ`. Never push to a different branch without explicit approval.
