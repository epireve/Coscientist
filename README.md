# Coscientist

A personal academic-research-agent toolkit for Claude Code. Assembled Lego-style from atomic skills + existing MCP servers rather than a monolithic app.

## What it does

Given a research question, an agent works through it end-to-end:

1. **Discovery** — searches across Consensus (200M+ papers), Semantic Scholar, arXiv, PubMed, bioRxiv, IEEE, Springer, and 20+ other sources in parallel.
2. **Triage** — decides per-paper whether the abstract/TLDR is enough, or whether full text is needed.
3. **Acquisition** — fetches PDFs through an open-access fallback chain, falling through to your institution's access via OpenAthens when OA sources don't have it.
4. **Extraction** — Docling converts PDFs into structured Markdown with figures, tables, equations, and references preserved.
5. **Analysis** — 10 specialized sub-agents (Grounder, Historian, Gaper, Vision, Theorist, Rude, Synthesizer, Thinker, Scribe, Social) work through the corpus with three human-in-the-loop review breaks.
6. **Output** — produces a Research Brief + six-section Understanding Map, with every claim traceable to its source paper in a SQLite run log.

## Architecture

Each skill is atomic and does one job. Skills compose through a shared **paper artifact** on disk — no skill calls another skill directly, so any piece can be swapped out.

```
~/.cache/coscientist/papers/<paper_id>/
  manifest.json       metadata.json
  content.md          frontmatter.yaml
  figures/  tables/   references.json
  equations.json      raw/  extraction.log
```

State flows: `discovered → triaged → acquired → extracted → read → cited`.

## Skills

### Literature pipeline (v0.1)

| Skill | Job |
|---|---|
| `/paper-discovery` | Multi-source search with dedup across discovery MCPs |
| `/paper-triage` | Decide metadata-sufficient vs full-text-needed |
| `/paper-acquire` | OA fallback chain + handoff to institutional access |
| `/institutional-access` | OpenAthens login + per-publisher PDF fetch via Playwright |
| `/arxiv-to-markdown` | Fast path for arXiv: HTML → clean Markdown |
| `/pdf-extract` | Docling extraction + Claude vision fallback |
| `/research-eval` | Reference and claim auditing |
| `/deep-research` | Orchestrates the 10 sub-agents end-to-end |

### Critical judgment (v0.3)

Gate-enforced novelty + publishability + attack-vector analysis. Each skill's gate script refuses un-grounded verdicts — no hedging, no novelty claims without 5+ anchors, no fatal attacks without steelman.

| Skill | Job |
|---|---|
| `novelty-check` | Enforce novelty-report structure (decomposition, ≥5 anchors, committed verdict) |
| `publishability-check` | Enforce venue verdicts with probability + kill criterion + factors |
| `attack-vectors` | Named-attack checklist with pass/minor/fatal + evidence + steelman |

Associated sub-agents: `novelty-auditor`, `publishability-judge`, `red-team`.

### Manuscript subsystem (v0.4 + v0.8 + v0.9)

Ingest your own drafts and analyze them with the same discipline used for external papers. v0.8 added full project-level auditability (every citation + claim + finding is durably recorded in the project graph). v0.9 added citation validation — every dangling/orphan/unresolved/broken reference is now explicitly flagged to the author.

| Skill | Job |
|---|---|
| `manuscript-ingest` | Copy a markdown draft into a `manuscript` artifact; parse inline citations **and bibliography section** (v0.9); record in `manuscript_citations` + `manuscript_references` tables + graph with `cites` edges to placeholder paper nodes |
| `manuscript-ingest/resolve_citations.py` | Map raw citation keys → canonical_ids; migrate graph edges to resolved paper nodes |
| `manuscript-ingest/validate_citations.py` (v0.9 + v0.10) | Cross-check in-text vs bib; flag `dangling-citation` / `orphan-reference` / `unresolved-citation` / `broken-reference` / `ambiguous-citation`; writes `validation_report.json` + populates `manuscript_audit_findings` so the author sees every integrity issue in one place. v0.10 also auto-suffixes colliding entry keys (`wang2020` × 2 → `wang2020a` + `wang2020b`) |
| `manuscript-audit` | Per-claim audit against cited sources; flags overclaim / uncited / unsupported / outdated / retracted + the 4 new v0.9 kinds; adds concept nodes + `about` edges to the project graph |
| `manuscript-critique` | Four reviewer personas (methodological / theoretical / big-picture / nitpicky) with committed verdict + confidence |
| `manuscript-reflect` | Thesis + premises + evidence chain + implicit assumptions + weakest link + one-experiment recommendation |

All three gate scripts accept `--project-id` (in addition to `--run-id`), so findings persist across sessions even outside a deep-research run.

Associated sub-agents: `manuscript-auditor`, `manuscript-critic`, `manuscript-reflector`.

### Reference agent (v0.5 + v0.6)

Zotero ↔ Coscientist bridge + graph-layer ops. Uses the Zotero MCP; never speculates.

| Script under `reference-agent/` | Job |
|---|---|
| `sync_from_zotero.py` | Ingest Zotero items → paper artifacts + author graph + default `to-read` state |
| `export_bibtex.py` | Emit `.bib` for a manuscript's cited sources or a deep-research run's `papers_in_run` |
| `reading_state.py` | Per-project per-paper reading state: `to-read → reading → read → annotated → cited \| skipped` |
| `mark_retracted.py` | Record retraction flags so `manuscript-audit` catches them automatically |
| `populate_citations.py` | Turn Semantic Scholar refs/citations into `cites` / `cited-by` edges in the project graph |
| `populate_concepts.py` | Promote run-log claims into `concept` nodes + `about` edges |

Associated sub-agent: `reference-agent`.

### Writing-style subsystem (v0.7)

Pure deterministic voice-matching — no LLM, no external deps. Fingerprints your academic voice from prior manuscripts and flags drift in new drafts.

| Script under `writing-style/` | Job |
|---|---|
| `fingerprint.py` | Aggregate lexical + syntactic + structural stats from ≥2 prior manuscripts → `style_profile.json` |
| `audit.py` | Per-paragraph deviation report against the profile; severities via z-score + rate ratios |
| `apply.py` | Paragraph-level critique via stdin for drafting-time feedback |

Associated sub-agent: `writing-style`.

### Personal knowledge layer (v0.11)

Daily research-life utilities. All deterministic — no LLM, no MCP fetches.

| Skill | Job |
|---|---|
| `research-journal` | Capture / list / search daily lab-notebook entries; per-project, time-stamped, with optional links to runs/papers/manuscripts. Mirrors to disk for greppability |
| `project-dashboard` | Read-only single-screen view across all projects (or one): activity, reading state, manuscripts by state, open audit issues, graph stats. JSON or Markdown |
| `cross-project-memory` | Read-only search and lookup across all project DBs. Find papers/concepts/claims/journal entries; given a paper, list every project containing it |

Associated sub-agents: `research-journal`, `project-dashboard`, `cross-project-memory`.

### Tournament + evolution (v0.12)

Pairwise self-play over candidate hypotheses with Elo ranking, plus parent-tracked mutation. Google AI Co-scientist's pattern.

| Script under `tournament/` | Job |
|---|---|
| `record_hypothesis.py` | Register a hypothesis (from theorist / thinker / evolver) at default Elo 1200 |
| `record_match.py` | Update both hypotheses' Elo (K=32) given a winner; persist match + reasoning |
| `pairwise.py` | Emit pairings: round-robin / top-k-vs-rest / top-k-internal; `--exclude-played` |
| `leaderboard.py` | Top-N by Elo with W-L-M counts and ancestor lineage |

Associated sub-agents: `ranker` (pairwise judge), `evolver` (sharpen / recombine / re-aim top-K).

## MCP servers used

Registered in `.mcp.json`:

- **Consensus** (HTTP+OAuth) — semantic search + claim extraction over 200M papers
- **paper-search-mcp** — 25+ sources, OA fallback downloads
- **academic-mcp** — 19+ sources including IEEE/Springer/ScienceDirect
- **Semantic Scholar** — citation graph traversal
- **Playwright MCP** — scripted browser for institutional-access
- **browser-use MCP** — LLM-guided browser fallback
- **Zotero** (local) — wraps Zotero's HTTP API for institutional PDF resolution + permanent library

## Setup

```bash
# Python deps (Docling, Playwright, arxiv2markdown, etc.)
uv sync

# One-time: bootstrap OpenAthens session for institutional-access
uv run python .claude/skills/institutional-access/scripts/login.py

# Playwright browsers
uv run playwright install chromium
```

Then in Claude Code: `/deep-research "your research question"`.

## Guardrails

The `institutional-access` skill enforces:

- **10 second delay** between PDF fetches per publisher domain
- **Triage gate**: no PDF is fetched unless `paper-triage` explicitly marked the paper as needing full text
- **Audit log**: every download recorded with DOI, timestamp, source tier
- Sci-Hub tier disabled by default

## Running tests

No pytest dependency; the harness is in-repo. Run the full smoke suite:

```bash
python3 -m tests.run_all
```

Currently 53 tests across schema, artifact contract, project/artifact/graph lib, deep-research state machine, the three A5 gate scripts, and agent frontmatter.

## Where this is going

See [`ROADMAP.md`](./ROADMAP.md) for the full plan — manuscript writing + versioning, reference agent with citation/concept graph, writing-style fingerprints, personal knowledge layer, tournament-ranked hypothesis evolution (Google Co-scientist pattern), PRISMA systematic review, Sakana-style experimentation loop, and more. The same file tracks what's shipped per version.

See [`RESEARCHER.md`](./RESEARCHER.md) for the 11 principles any agent should follow when doing research work inside this system. Shaped after Karpathy's composable-principle approach: every rule names a specific LLM failure mode and a test to check you followed it.

## Credits

Ports concepts and code from three MIT-licensed projects:

- [anvix9/basis_research_agents](https://github.com/anvix9/basis_research_agents) — the 10-agent SEEKER pipeline
- [timf34/arxiv2md](https://github.com/timf34/arxiv2md) — arXiv HTML to Markdown
- [openags/paper-search-mcp](https://github.com/openags/paper-search-mcp) — multi-source academic search

Design patterns and principles borrowed from:

- [Sakana AI Scientist](https://sakana.ai/ai-scientist/) — fixed-budget experimentation loops, code-execute iteration, automated self-review
- [Google AI Co-scientist](https://research.google/blog/accelerating-scientific-breakthroughs-with-an-ai-co-scientist/) — tournament/Elo hypothesis ranking, evolution agent, hierarchical supervisor
- [karpathy/autoresearch](https://github.com/karpathy/autoresearch) — fixed-time comparable experiments, minimal-scope file edits, `program.md` as canonical instruction file
- [forrestchang/andrej-karpathy-skills](https://github.com/forrestchang/andrej-karpathy-skills) — principle-as-antidote prose, "the test" verification, declarative over imperative

## License

MIT.
