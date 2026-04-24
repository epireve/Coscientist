# Coscientist Roadmap

Where this project is headed and why. This is a living document — reshape freely as priorities shift, but don't silently drop items; move them to "parked" with a reason.

## Vision

A personal research partner that covers the *full* research lifecycle: discovering → reading → synthesizing → critiquing → proposing → experimenting → writing → publishing → reflecting. Assembled from atomic skills + existing MCP servers, composable through a shared on-disk contract. Lego, not monolith.

The current v0.1 is a literature-synthesis pipeline. The point of the roadmap is the rest.

## Shipped

### v0.1 — literature-synthesis pipeline (commit c9e2ea4)

- 8 atomic skills: `paper-discovery`, `paper-triage`, `paper-acquire`, `institutional-access`, `arxiv-to-markdown`, `pdf-extract`, `research-eval`, `deep-research`
- 10 sub-agents under `deep-research`: social, grounder, historian, gaper, vision, theorist, rude, synthesizer, thinker, scribe
- 7 MCP server registrations: consensus, paper-search, academic, semantic-scholar, playwright, browser-use, zotero
- Paper artifact contract on disk; SQLite run log with resume
- Guardrails: triage-gate before acquire, 10s publisher rate limit, audit log, Sci-Hub off by default

### v0.2 — ROADMAP + RESEARCHER principles + Karpathy absorption (commits 4a3c8d5, bc135fa)

- `ROADMAP.md` with this structure (tier A/B/C, shipped list, open decisions)
- `RESEARCHER.md` with 11 research-agent principles: triage before acquiring, cite what you've read, doubt the extractor, narrate tension, register bias upfront, name five, commit to a number, steelman before attack, premortem, kill criteria, stop when you should
- 4 engineering principles in `CLAUDE.md` from karpathy-skills
- Sub-agent mapping table linking principles to each agent

### v0.3 — A5 critical-judgment + Karpathy retrofit + structural refactor foundation (commit 885035b)

- A5 skills: `novelty-check`, `publishability-check`, `attack-vectors` (gate-enforced discipline)
- A5 sub-agents: `novelty-auditor`, `publishability-judge`, `red-team`
- Karpathy retrofit on all 10 existing sub-agents (minimal-scope tools, declarative goals, exit-test clauses, RESEARCHER.md references)
- Structural refactor foundation (non-breaking):
  - `projects` table + `lib/project.py` — top-level research container
  - `artifact_index` table + `lib/artifact.py` — polymorphic artifact kinds (manuscript, experiment, dataset, figure, review, grant, journal-entry, protocol) with per-kind state machines
  - `graph_nodes` + `graph_edges` tables + `lib/graph.py` — citation/concept/author graph (SQLite adjacency; Kuzu upgrade deferred)
  - `hypotheses` + `tournament_matches` tables — Elo-ranked hypotheses with parent lineage (schema only; Tournament ranker is Tier B)
- Schema now 20 tables total

### v0.3.1 — smoke test suite (commit 96bdeb9)

- `tests/` with dependency-free harness (no pytest required)
- 53 tests across 8 areas: schema, paper artifact regression, project/artifact/graph, deep-research state machine, A5 gates (accept + reject per condition), agent frontmatter
- `tests/_shim.py` slugify stub lets suite run without `uv sync`
- Caught two bugs during first run — both fixed

### v0.4 — manuscript-ingest subsystem (A1 first cut)

Ingest + analyze-your-own-work skills. Does not yet include draft/revise/format/version — those are a later iteration.

- 4 new skills: `manuscript-ingest`, `manuscript-audit`, `manuscript-critique`, `manuscript-reflect` — each with a gate script that refuses un-grounded output
- 3 new sub-agents: `manuscript-auditor`, `manuscript-critic` (four reviewer personas), `manuscript-reflector` ("ultrathink your own work")
- 4 schema tables: `manuscript_claims`, `manuscript_audit_findings`, `manuscript_critique_findings`, `manuscript_reflections`
- 23 new tests (76 total suite); 0 failures

### v0.5 — reference-agent skill (A2 first cut)

Brings Zotero into the paper cache + makes the graph layer usable in practice.

- 1 new skill: `reference-agent` with four scripts — `sync_from_zotero.py`, `export_bibtex.py`, `reading_state.py`, `mark_retracted.py`
- 1 new sub-agent: `reference-agent` — orchestrates Zotero MCP calls, never speculates
- 3 schema tables: `reading_state`, `retraction_flags`, `zotero_links`
- Per-project per-paper reading state machine: `to-read → reading → read → annotated → cited | skipped`
- BibTeX export with embedded `canonical_id` in `note` for round-trip traceability
- 14 new tests (90 total; 0 failures)

Graph-layer Kuzu upgrade still deferred; SQLite adjacency works and tests exercise add/walk/hubs/in_degree.

### v0.5.1 — integration + regression test suite

- `tests/test_integration.py` with 14 tests across: end-to-end research flow, cross-skill artifact contract, schema regression (column checks, UNIQUE constraints, CASCADE semantics), compilation meta, config validation, layout regression
- Caught + fixed: gratuitous `slugify` dependency in `lib/project.py` that broke `manuscript-ingest` under `--project-id`; replaced with inline `_slug()` — `lib/project.py` now has zero external-package deps
- 104 tests total; 0 failures

### v0.6 — citation + concept graph population (A2 completion)

Fills in the two remaining A2 items. The graph layer now has actual data flowing into it.

- 2 new scripts in `reference-agent/`:
  - `populate_citations.py` — takes JSON from Semantic Scholar refs/citations; creates `cites` + `cited-by` edges in the project graph. Idempotent, creates paper nodes on demand
  - `populate_concepts.py` — scans a run's `claims` table; creates `concept` nodes + `about` edges to each claim's `canonical_id` + `supporting_ids`. Idempotent, no MCP calls needed
- Reference-agent SKILL.md + sub-agent persona updated with new capabilities
- 6 new tests (110 total; 0 failures) — edge creation, idempotency on re-run, empty-run handling, records missing from_canonical_id skipped
- A2 fully complete. Kuzu migration still parked.

### v0.7 — writing-style subsystem (A3)

Pure deterministic text analysis — no LLM, no external deps beyond stdlib. Produces a per-project style profile and numerical deviation audits.

- New skill `writing-style` with three scripts + a shared `_textstats.py`:
  - `fingerprint.py` — extract lexical + syntactic + structural stats from N prior manuscripts; writes `style_profile.json`; updates `projects.style_profile_path`
  - `audit.py` — per-paragraph deviation report against the profile; severity via z-scores + rate ratios (info / minor / major)
  - `apply.py` — paragraph-level critique via stdin for drafting-time feedback
- New sub-agent `writing-style` — refuses to fingerprint from <2 samples, reports with numbers not vibes
- Style profile captures: top content terms, hedge density, first-person rate, British/American spelling, sentence length mean + std, passive voice rate, paragraph length mean + std, signpost phrases
- 14 new tests (124 total; 0 failures)

A3 done. Pair with future `manuscript-draft` (v0.9+) for drafting-time enforcement.

### v0.8 — manuscript auditability (closes a real gap)

Before v0.8, ingesting a manuscript didn't record its citations anywhere queryable, audits wrote only to the run DB (lost outside deep-research runs), and nothing from the user's own drafts landed in the project graph. v0.8 closes these gaps so every manuscript operation leaves a durable, queryable trail.

Schema (+1 table, 25 total):
- `manuscript_citations` — every raw citation key extracted from the source, keyed on (manuscript_id, citation_key, location), with optional `resolved_canonical_id` + `resolution_source`

`manuscript-ingest` (significantly enhanced):
- Inline citation parser handles `\cite{key1,key2}`, `\citep{}`, pandoc `[@key]`, numeric `[1,2,3]`, and `(Author et al., Year)` styles
- Location tracking by section header + paragraph index
- With `--project-id`: writes every citation to `manuscript_citations`, creates `manuscript:<mid>` graph node, creates `paper:unresolved:<key>` placeholder nodes, adds `cites` edges from manuscript to each placeholder

`manuscript-audit`, `manuscript-critique`, `manuscript-reflect` gates:
- Each gate now accepts `--project-id` in addition to (or instead of) `--run-id`
- When both given, writes to both DBs; when only project given, persists cross-session
- `manuscript-audit` additionally creates `concept:<slug>-<hash>` nodes for each claim and adds `about` edges from manuscript → concept and concept → cited_sources, so the concept graph reflects what each manuscript asserts

New script `manuscript-ingest/scripts/resolve_citations.py`:
- Takes a JSON list of `{citation_key, canonical_id, source}` mappings
- Updates `manuscript_citations.resolved_canonical_id`
- Migrates graph edges: `paper:unresolved:<key>` → `paper:<canonical_id>`; deletes placeholder nodes once no edges reference them
- Accepts `source` ∈ {manual, zotero, semantic-scholar, audit}

Tests (17 new, 141 total; 0 failing):
- Citation parser: 6 tests covering all 4 inline styles + location tracking
- Ingest graph integration: project-id path populates tables + graph; no-project path still works silently
- Audit gate project-DB: writes claims, findings, concept nodes, and 2 about edges per claim (ms→concept + concept→paper); dual-write with both run-id + project-id
- Critique gate project-DB: findings persisted
- Reflect gate project-DB: reflection persisted
- Resolve citations: table update + edge migration + placeholder cleanup; invalid source rejected
- Schema: table + indexes + UNIQUE constraint on (manuscript_id, citation_key, location)

## Inspirations and what we take from them

| Source | Pattern we adopt |
|---|---|
| [SEEKER](https://github.com/anvix9/basis_research_agents) | 10-agent pipeline, 3 human-in-the-loop breaks, SQLite audit trail, resume semantics |
| [arxiv2md](https://github.com/timf34/arxiv2md) | arXiv HTML → clean Markdown, avoid PDF when possible |
| [paper-search-mcp](https://github.com/openags/paper-search-mcp) | Unified multi-source search, OA-first download chain |
| [Sakana AI Scientist (v1/v2)](https://sakana.ai/ai-scientist/) | Code-execution iteration loop, novelty-check before run, fixed-budget experiments, automated self-review |
| [Google AI Co-scientist](https://research.google/blog/accelerating-scientific-breakthroughs-with-an-ai-co-scientist/) | Tournament/Elo ranking of hypotheses, evolution agent, hierarchical supervisor, wet-lab grounding |
| [karpathy/autoresearch](https://github.com/karpathy/autoresearch) | Fixed time-budget per experiment, single comparable metric, minimal-scope file edits, `program.md` as canonical instruction file, overnight-iteration UX |
| [karpathy-skills](https://github.com/forrestchang/andrej-karpathy-skills) | Principle-as-antidote prose, "the test" verification clause per principle, declarative over imperative, composable single-file guidance |

## Design principles (derived)

Applied to skills, sub-agents, and code. See `RESEARCHER.md` for the researcher-facing version and `CLAUDE.md` for the engineer-facing version.

1. **Principle-as-antidote** — every rule in `RESEARCHER.md` directly counters a known failure mode
2. **Declarative goals** — sub-agent prompts describe *what success looks like*, not procedural steps, wherever the task permits self-checking loops
3. **"The test"** — every sub-agent exits with an explicit verification clause
4. **Minimal-scope edits** — each sub-agent's `tools:` frontmatter restricts which files/MCPs it can touch
5. **Fixed budgets + single metric** — for anything experimental, one scalar comparable across iterations
6. **Lego composition** — skills communicate through artifacts on disk, never direct invocation
7. **Composable principle files** — project-level `CLAUDE.md` merges with `RESEARCHER.md` merges with user-level principles

## Tier A — next iteration (v0.2)

The four subsystems that most directly serve the user's stated use cases. Build in this order.

### A1. Manuscript subsystem (use cases: audit WIP, ultrathink own work, critique)

Ingest the user's own manuscripts and treat them as artifacts parallel to papers. State machine: `drafted → audited → critiqued → revised`.

- ✅ `manuscript-ingest` — ingest a markdown draft into an artifact (v0.4)
- ✅ `manuscript-audit` — extract every claim; verify each against its cited source; flag overclaim/uncited/unsupported/outdated/retracted (v0.4)
- ✅ `manuscript-critique` — four reviewer personas (methodological, theoretical, big-picture, nitpicky) with structured findings + committed overall verdict (v0.4)
- ✅ `manuscript-reflect` — argument structure, implicit assumptions, weakest link, one-experiment recommendation (v0.4)
- `manuscript-draft` — outline → section → revision cycle. Venue-specific templates (IMRaD, Nature, NeurIPS, ACL, thesis). Writes `\cite{key}` inline against Zotero in real time.
- `manuscript-revise` — respond-to-reviewers mode. Takes review + current draft; produces diff + response letter keyed to each point.
- `manuscript-format` — pandoc-driven export to venue template (LaTeX class, .docx, arXiv).
- `manuscript-version` — git + SQLite `manuscript_versions` table. Auto-commit each iteration with semantic messages. DB layer tracks word_count, claims_added/removed, reviewer_feedback_addressed per version.

Retraction checking in `manuscript-audit` is currently a manual fallback via Semantic Scholar. Moves to automatic once the `retraction-mcp` lands (Tier B).

### A2. Reference agent with graph layer

Promote citations/concepts/authors from rows to a real graph.

- ✅ Graph foundation — SQLite adjacency tables + `lib/graph.py` (v0.3). Kuzu upgrade still parked.
- ✅ `reference-agent` skill (v0.5): Zotero sync, reading-state per project, BibTeX export, retraction flags
- ✅ Author-graph edges via Zotero sync (`authored-by`)
- ✅ Citation edges — `populate_citations.py` (v0.6): Semantic Scholar refs/citations → `cites` + `cited-by` edges
- ✅ Concept edges — `populate_concepts.py` (v0.6): run claims → `concept` nodes + `about` edges
- **Still pending** (nice-to-have, not blocking):
  - CSL-JSON export (BibTeX only for now)
  - Dedicated "resolve incomplete citation" skill ("Smith 2020" → DOI) — sub-agent can do this today via Semantic Scholar MCP directly
  - Visualization (mermaid embed; Cytoscape.js if a web dashboard emerges)
  - Kuzu backend migration (deferred until volume demands it)

### A3. Writing-style subsystem

- ✅ `writing-style fingerprint` — extract your voice from N prior manuscripts (v0.7)
- ✅ `writing-style audit` — per-paragraph numeric deviation audit (v0.7)
- ✅ `writing-style apply` — paragraph-level critique via stdin (v0.7)
- **Still pending**: venue-style overlays ("NeurIPS expects 'we show'", "clinical expects passive voice") — handled by future `manuscript-format`

### A4. Personal knowledge layer (journal + dashboard + cross-project memory)

These three cluster tightly.

- `research-journal` — daily lab notebook. Ideas recorded as they arise, cross-referenced to runs/manuscripts/experiments. Time-stamped.
- `project-dashboard` — single view of all active projects, deadlines, reviews due, papers in flight. CLI + optional web.
- `cross-project-memory` — persistent knowledge graph across projects. "I know I've read this somewhere" search. Connection-mining across apparently-unrelated projects.

### A5. Critical-judgment subsystem (novelty, publishability, sharp critique)

Serves use cases: cross-check WIP, ultrathink own work, critique own/others' work. Structured to fight known LLM failure modes in judgment: sycophancy, status-quo hedging, confident claims without prior-art search, missing specific attack vectors, no calibration.

**New sub-agents:**

- `novelty-auditor` — decomposes a paper's claimed contributions into `(claim, method, domain, finding, metric)` tuples. For each tuple, runs targeted prior-art search: exact conceptual match, method-in-new-domain, scale-only change, finding-in-new-population. Produces a novelty matrix: per-contribution closest prior work + delta + delta-sufficiency verdict. Gate: cannot emit a verdict without naming ≥5 specific nearby papers by canonical_id.
- `publishability-judge` — rubric-based venue-calibrated judgment. Per target venue, evaluates novelty + significance + methodology + scope + execution against that venue's rubric. Calibrated against a user-maintained reference set of known-accepted/known-rejected/borderline papers. Outputs probability per venue (committed number, no hedging) + "what would need to change to move up a tier".
- `red-team` — upgrade of `rude` with explicit attack vectors, not generic critique. Checks by name: p-hacking signals, HARKing, selective baselines, missing controls, confounders, underpowered studies, circular reasoning, oversold deltas, irreproducibility. Outputs severity-rated attack log; verdict "would-kill-paper" vs "reviewer-2-concern".

**New skills:**

- `gap-analyzer` — operationalizes Gaper's output. For each gap: real or artifact of incomplete search? Addressable or hard-problem? Publishable if filled, at what venue tier? Adjacent fields with analog solutions? Expected difficulty (person-years, resources).
- `contribution-mapper` — positions a manuscript in the research landscape. Extracts contributions, maps to closest prior work via citation + semantic distance, computes method/domain/finding distances, emits a 2D landscape plot with your work located.
- `venue-match` — data-backed venue recommendation. Acceptance rates for work-like-yours, reviewer expectations per venue, deadline fit, impact/open-access/community-fit tradeoffs.

**Infrastructure:**

- **Self-play debate** for high-stakes verdicts: two instances of `novelty-auditor` argue opposing sides; `publishability-judge` decides on argument quality and evidence grounding.
- **Calibration anchors**: every judgment cites ≥5 specific prior works; verdicts without anchors are disqualified by the gate script.
- **User-maintained calibration set**: user labels their own historical accepts/rejects + borderline cases; anchors learned from this set tune the rubric over time.
- **Tournament Elo** (reuses the Tier B tournament ranker): pairwise comparisons of candidate hypotheses or manuscripts against the calibration set for recoverable quantified judgment.

**Why this is Tier A, not B**: without it, every other Tier A subsystem produces confident-sounding but un-calibrated output. Manuscript-audit needs novelty-auditor to avoid flagging "already known" claims as novel. Manuscript-critique is only as sharp as `red-team`. Reference-agent's graph only matters if we can tell hubs from noise.

## Tier B — medium horizon (v0.3+)

High value but narrower or more domain-dependent.

- **Tournament ranker + Evolution agent** (Google Co-scientist pattern): new sub-agents `ranker` (pairwise Elo tournament over Theorist/Thinker proposals) and `evolver` (mutate top-Elo candidates and re-tournament). Table `hypotheses` with Elo.
- **Systematic review (PRISMA)**: `systematic-review` skill with protocol-first declaration, documented exhaustive search, two-stage screening, risk-of-bias assessment, extraction forms, meta-analysis module, PRISMA flow diagram. New tables: `review_protocols`, `screening_decisions`, `extraction_rows`, `bias_assessments`.
- **Statistics MCP**: effect sizes, power analysis, meta-analysis, test selection, assumption checks. Reusable across manuscript-audit + systematic-review + experiment-design.
- **Figure agent**: venue-styled plots, caption consistency, alt-text, colorblind-safe palettes, vector vs raster decisions.
- **Peer-review simulator**: multi-round (initial review → revision → final decision), not single-shot critique.
- **Retraction watch daemon**: background alert when any paper you've cited is retracted.
- **Preprint alerts daemon**: daily arXiv/bioRxiv digest filtered to your topics + followed authors.
- **Grant-draft skill**: funder-specific templates (NIH, NSF, ERC, Wellcome). Significance + impact framing distinct from papers.
- **Red-team agent**: meaner than Rude. Specifically tries to disprove your best ideas. Separate persona, explicit trigger.
- **Overnight mode**: "run while I sleep" — discovery → triage → acquire → extract runs through the night; human-in-the-loop breaks are *queued*, not blocking. You review morning digest.

## Tier C — longer horizon

- **Sakana-style experimentation loop**: `experiment-design` + `experiment-reproduce` + a custom `reproducibility-mcp` that sandboxes exec (Docker / E2B / Modal). Measure with fixed compute + single metric per karpathy/autoresearch. This is what turns Coscientist from assistant → co-scientist.
- **Research project container**: persistent top-level object wrapping multiple runs, manuscripts, experiments, reading lists, knowledge graphs. Zotero collection per project.
- **Dataset agent**: track datasets used in your work with DOIs, licenses, versions, hashes. Zenodo/OSF deposit.
- **Slide-draft skill**: paper → beamer/pptx with key figures.
- **Data management plan generator**: for grants (NIH DMSP, NSF DMP).
- **Citation alerts**: "someone just cited your paper — here's context".
- **Reviewer-assistant skill**: when reviewing others' work, extract claims + check methods + draft structured review.
- **Negative-results logger**: dedicated artifact type for failed experiments.
- **Credit tracker**: CRediT taxonomy, who did what per paper.
- **Field-trends analyzer**: citation-momentum for approaches, topics rising/declining.
- **Reading-pace analytics**: your own velocity metrics.
- **Open-data deposit**: Zenodo/OSF/Figshare submission + DOI assignment.
- **Registered reports pathway** support.
- **Ethics/IRB skill**: IRB application drafting, conflict-of-interest tracker.
- **Meta-research skill**: publication trends, career trajectory analysis.

## Structural refactor (prerequisite to most Tier-A work)

Current schema is paper-centric. Three abstractions needed:

1. **Project** — persistent container wrapping multiple runs, manuscripts, experiments, datasets, reading lists, knowledge graphs, and a writing-style profile. Runs become child objects of projects.
2. **Polymorphic artifacts** — right now "artifact" ≈ "paper". Generalize to: paper, manuscript, experiment, dataset, figure, review, grant, journal-entry, protocol. Each has its own state machine but shares a common artifact root + common manifest structure.
3. **Graph layer** — citations, concepts, authors, personal links — orthogonal to per-artifact stores. Kuzu or SQLite adjacency.

**Recommendation**: do this refactor *before* starting Tier A. Each subsystem afterward benefits proportionally. Yes, it delays visible features. No, skipping it doesn't scale.

## MCP servers worth building custom

Not all skill scripts need to be MCPs. These earn MCP status because they're reusable cross-tool:

- **reproducibility-mcp** — sandboxed Python/shell exec (Docker or Modal or E2B backend). Primitive that experiment + manuscript-audit + systematic-review all need.
- **statistics-mcp** — effect sizes, meta-analysis, power, tests. Called by multiple skills.
- **retraction-mcp** — Retraction Watch + PubPeer wrapper. Pure lookup.
- **manuscript-mcp** — .docx / .tex / .md → structured AST. Once-only parsing that many skills consume.
- **graph-query-mcp** — wraps Kuzu with research-domain-friendly query primitives (`expand_citations`, `concept_path`, `author_cluster`).

## Open questions and decisions pending

1. Graph DB: Kuzu vs SQLite-adjacency vs Neo4j (lean toward Kuzu)
2. Manuscript format: LaTeX-first or markdown-first for `manuscript-draft`?
3. Refactor timing: before Tier A (recommended) or after?
4. Sandbox backend for reproducibility-mcp: Docker local / E2B / Modal / all three?
5. Tournament compute budget: willing to spend tokens on pairwise Elo, or start with top-K selection?
6. Research-project scope: one project per GitHub repo, or one repo hosts many projects?
7. "Overnight mode" breaks: queued-only, or user-configurable per-run?
8. Citation graph population: eagerly during discovery (slower, costlier) or lazily on demand?

## Parked (considered, deferred, not dropped)

- Neo4j integration — overkill for a personal tool
- Distributed/cloud agent deployment — keep local-first
- Non-English corpus support — out of scope for now

## How to use this roadmap

- Each iteration picks a clean subset and finishes it. No half-finished subsystems shipped.
- When an item ships, strike it through and note the version + commit.
- When priorities shift, move items between tiers rather than dropping them.
- When a new inspiration surfaces, add a row to the "Inspirations" table with a specific pattern adopted — not a vague "we should look at X".
