# Coscientist Roadmap

Where this project is headed and why. This is a living document — reshape freely as priorities shift, but don't silently drop items; move them to "parked" with a reason.

## Vision

A personal research partner that covers the *full* research lifecycle: discovering → reading → synthesizing → critiquing → proposing → experimenting → writing → publishing → reflecting. Assembled from atomic skills + existing MCP servers, composable through a shared on-disk contract. Lego, not monolith.

The current v0.1 is a literature-synthesis pipeline. The point of the roadmap is the rest.

## What exists today (v0.1)

- 8 atomic skills: `paper-discovery`, `paper-triage`, `paper-acquire`, `institutional-access`, `arxiv-to-markdown`, `pdf-extract`, `research-eval`, `deep-research`
- 10 sub-agents under `deep-research`: social, grounder, historian, gaper, vision, theorist, rude, synthesizer, thinker, scribe
- 7 MCP server registrations: consensus, paper-search, academic, semantic-scholar, playwright, browser-use, zotero
- Paper artifact contract on disk; SQLite run log with resume
- Guardrails: triage-gate before acquire, 10s publisher rate limit, audit log, Sci-Hub off by default

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

- `manuscript-audit` — extract every claim; verify each against its cited source (does that paper really say this?), retraction databases, and broader literature for contradicting evidence. Output annotated diff with issues flagged.
- `manuscript-critique` — four reviewer personas (methodological, theoretical, big-picture, nitpicky) producing a NeurIPS/Nature-style review doc.
- `manuscript-reflect` — the "ultrathink your own work" skill: expose argument structure, make implicit assumptions explicit, map evidence chains, identify weakest link, suggest the *one* experiment that would most strengthen it.
- `manuscript-draft` — outline → section → revision cycle. Venue-specific templates (IMRaD, Nature, NeurIPS, ACL, thesis). Writes `\cite{key}` inline against Zotero in real time.
- `manuscript-revise` — respond-to-reviewers mode. Takes review + current draft; produces diff + response letter keyed to each point.
- `manuscript-format` — pandoc-driven export to venue template (LaTeX class, .docx, arXiv).
- `manuscript-version` — git + SQLite `manuscript_versions` table. Auto-commit each iteration with semantic messages. DB layer tracks word_count, claims_added/removed, reviewer_feedback_addressed per version.

### A2. Reference agent with graph layer

Promote citations/concepts/authors from rows to a real graph.

- Graph DB decision: **Kuzu** (embedded, SQL-like, zero-config) preferred; fallback is SQLite adjacency tables.
- Four linked graphs:
  - Citation (papers + cites/cited-by via Semantic Scholar)
  - Concept (claims + `extends`/`refutes`/`uses`/`depends-on` edges, populated during SEEKER analysis phases)
  - Author (collaboration edges)
  - Personal (your reading, manuscripts, claims linked to the above)
- NetworkX for centrality/community/path analysis
- `reference-agent` skill features:
  - Bidirectional Zotero sync (discovery → Zotero; manual adds → agent sees them)
  - Duplicate detection across runs/collections
  - N-hop citation-graph walk on demand
  - BibTeX / CSL-JSON export per manuscript
  - Reading-state tracking: to-read, read, annotated, cited
  - Incomplete-citation resolution ("Smith 2020" → DOI)
  - Retraction watch integration
- Visualization: mermaid for markdown embeds; Cytoscape.js if a web dashboard emerges

### A3. Writing-style subsystem

- `writing-style fingerprint` — extract your voice from N prior manuscripts: lexical (terminology, hedge density, first-person, British/American), syntactic (sentence length, passive rate, clause depth), structural (paragraph length, signposting, section openings).
- `writing-style apply` — drafting-time enforcement that coaches `manuscript-draft`.
- `writing-style audit` — flag deviations in a new draft against your profile + against venue norms (word limits, section conventions, voice expectations like "we show" vs "it was demonstrated").

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
