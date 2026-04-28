# Coscientist

A personal academic-research-agent toolkit for Claude Code. Assembled Lego-style from atomic skills + existing MCP servers rather than a monolithic app.

## What it does

Given a research question, an agent works through it end-to-end:

1. **Discovery** — searches across Consensus (200M+ papers), Semantic Scholar, arXiv, PubMed, bioRxiv, IEEE, Springer, and 20+ other sources in parallel.
2. **Triage** — decides per-paper whether the abstract/TLDR is enough, or whether full text is needed.
3. **Acquisition** — fetches PDFs through an open-access fallback chain, falling through to your institution's access via OpenAthens when OA sources don't have it.
4. **Extraction** — Docling converts PDFs into structured Markdown with figures, tables, equations, and references preserved.
5. **Analysis** — 10 specialized sub-agents (Scout, Cartographer, Chronicler, Surveyor, Synthesist, Architect, Inquisitor, Weaver, Visionary, Steward) work through the corpus with three human-in-the-loop review breaks. Phase 1 personas run in parallel (v0.51).
6. **Tournament** (v0.123) — Architect + Visionary hypotheses ranked via pairwise Elo before downstream personas judge them; Inquisitor + Steward read the leaderboard, not raw output order.
7. **Critical judgment** (v0.3 + v0.55 + v0.56) — gate-enforced novelty / publishability / attack-vector audits with self-play debate (PRO + CON + JUDGE) for borderline verdicts.
8. **Output** — Research Brief + six-section Understanding Map + RUN-RECOVERY.md, every claim traceable to source paper. Brief includes hypothesis cards, evidence tables, Socratic discussion questions (v0.54).
9. **Observability** (v0.89–v0.133) — every phase + tool-call + gate + harvest + sub-agent emits an OpenTelemetry-style span. Auto-rubric scores agent quality on phase complete. Health dump (`/health`) surfaces stale runs, slow MCPs, low-quality agents, decline trends, gate rejection patterns. OTLP export for Jaeger/Honeycomb. Alert thresholds + CI exit codes + per-project overlay.

Beyond the literature pipeline, Coscientist supports the full research lifecycle:

- **Manuscripts**: ingest → audit → critique → reflect → draft → revise → format → version (markdown-first, pandoc export to LaTeX/.docx/PDF)
- **Experiments**: design → preregister → Docker-sandboxed run → analyze → reproduce
- **Datasets**: register → Zenodo deposit → version
- **Grants/IRB/DMP**: NIH / NSF / ERC / Wellcome funder-specific scaffolds
- **Personal knowledge layer**: research journal, project dashboard, cross-project memory, citation alerts, retraction watch, preprint alerts
- **Wide Research**: orchestrator-worker fan-out for N-item parallel processing (10-250 items, 6 task types)

## Three research modes

`lib/mode_selector.py` picks the right mode automatically.

| Mode | Use for | Cost | Time |
|---|---|---|---|
| **Quick** | Concrete one-shot ("summarize this", "list venues") | $0.05–0.30 | 30s–2m |
| **Deep** | Open-ended research question | $3–5 | 15–25 min |
| **Wide** | N items processed identically (10 ≤ N ≤ 250) | $5–30 (cap $50) | 5–20 min |

**Wide → Deep handoff** (v0.53.5): triage 100 papers via Wide, then seed Deep from the top-30 shortlist:

```bash
# 1. Wide-triage 100 papers
uv run python .claude/skills/wide-research/scripts/wide.py init \
  --query "..." --items items.json --type triage
# (Gate 1 approve → orchestrator dispatches sub-agents → synthesize)

# 2. Deep run, seeded from Wide
uv run python .claude/skills/deep-research/scripts/db.py init \
  --question "..." --seed-from-wide <wide-id> --seed-mode abstract
```

## Quick start

```bash
# 1. Clone + install
git clone https://github.com/epireve/coscientist.git
cd coscientist
uv sync --extra dev --extra mcp

# 2. Configure MCP credentials (template has placeholders for keys)
cp .mcp.json.example .mcp.json
# Edit .mcp.json — fill <semantic_scholar_api_key> etc with real keys

# 3. Install pre-commit hook (auto-regens checksums + indexes)
scripts/install_hooks.sh

# 4. Verify
uv run python tests/run_all.py        # 1900+ tests, ~25s
uv run python -m lib.health           # diagnostics dump

# 5. Run your first deep-research
uv run python .claude/skills/deep-research/scripts/db.py init \
  --question "<your research question>"
# Returns a run_id. Then dispatch sub-agents per orchestrator
# instructions in .claude/skills/deep-research/SKILL.md.
```

For Claude Code plugin install (recommended for end users) see Install section below.

## Install

```bash
/plugin marketplace add epireve/coscientist

# Full deep-research pipeline (10-agent Expedition + skills + agents)
/plugin install coscientist-deep-research@coscientist

# Custom MCP servers (each installable independently)
/plugin install coscientist-retraction-mcp@coscientist
/plugin install coscientist-manuscript-mcp@coscientist
/plugin install coscientist-graph-query-mcp@coscientist
```

| Plugin | What it adds |
|---|---|
| `coscientist-deep-research` | 11 skills + 10 agents + `/deep-research` slash command |
| `coscientist-retraction-mcp` | MCP server for retraction status (Crossref + PubPeer). 3 tools. |
| `coscientist-manuscript-mcp` | MCP server: .docx / .tex / .md → AST. 4 tools. |
| `coscientist-graph-query-mcp` | Read-only MCP over the per-project citation graph. 6 tools. |

Full server inventory + tool reference: [MCP_SERVERS.md](./MCP_SERVERS.md).

Coscientist also consumes several third-party MCPs (Consensus,
paper-search, semantic-scholar, academic, zotero, playwright,
browser-use). They're not republished here — see
[EXTERNAL_MCPS.md](./EXTERNAL_MCPS.md) for setup.

### Install troubleshooting

| Symptom | Likely cause + fix |
|---|---|
| `/plugin install` fails with "marketplace not found" | Run `/plugin marketplace add epireve/coscientist` first. |
| MCP server doesn't appear in `claude mcp list` after install | Plugin's `.mcp.json` uses `${CLAUDE_PLUGIN_ROOT}` — make sure your Claude Code version supports plugin env vars (≥ 2.0.0). |
| `mcp` package not found at runtime | Either install via `uv sync --extra mcp` (source tree) or rely on `uv run --with mcp` declared inside each plugin's `.mcp.json`. |
| `pandoc not on PATH` errors from `manuscript-mcp` | Only `.docx` parsing needs pandoc. Install via `brew install pandoc` or distro package manager. Markdown + LaTeX paths work without it. |
| `coscientist-graph-query-mcp` errors `lib.graph not found` | Plugin vendors its own `lib/`; check that `plugin/coscientist-graph-query-mcp/lib/graph.py` exists. The marketplace install should include it. |
| Want to verify everything before reporting a bug? | Run `uv run python -m lib.install_check --with-mcp-list`. Returns a structured JSON report on every plugin + (optionally) `claude mcp list` output. |

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

## Sub-agent personas (40+ across 8 phases)

| Phase | Personas | Job |
|---|---|---|
| **A. The Expedition** | scout, cartographer, chronicler, surveyor, synthesist, architect, inquisitor, weaver, visionary, steward | 10-agent deep-research pipeline with 3 HITL breaks. Phase 1 (cartographer/chronicler/surveyor) runs concurrently (v0.51). |
| **B. The Workshop** | drafter, verifier, panel, diviner, reviser, compositor | Manuscript subsystem — write, audit, critique, reflect, respond-to-reviewers, export. |
| **C. The Tribunal** | novelty-auditor, publishability-judge, red-team, advocate, peer-reviewer | Critical-judgment subsystem. |
| **D. The Laboratory** | experimentalist, curator, funder | Sakana-loop experiment + dataset + grant scaffolds. |
| **E. The Tournament** | ranker, mutator | Pairwise Elo + evolution (Google Co-scientist pattern). |
| **F. The Archive** | librarian, stylist, diarist, watchman, indexer | Personal knowledge layer — Zotero bridge, voice fingerprint, journal, dashboard, cross-project search. |
| **G. Wide Research** *(v0.53.6)* | wide-triage, wide-read, wide-rank, wide-compare, wide-survey, wide-screen | One per Wide TaskSpec type. Dispatched by `wide.py` to process N items in parallel (cap 30 concurrent). |
| **H. Self-play debate** *(v0.56)* | debate-pro, debate-con, debate-judge | PRO + CON argue opposing sides of a verdict (novelty / publishability / red-team); judge scores both and commits. |

**Backward compatibility**: in-flight runs from before v0.46.4 continue working — `db.py PHASE_ALIASES` silently translates old SEEKER phase names (social, grounder, historian, gaper, vision, theorist, rude, synthesizer, thinker, scribe) into new Expedition names.

## Documentation

| Doc | What |
|---|---|
| [`docs/architecture.md`](./docs/architecture.md) | System layout: artifact contract, SQLite scopes, migration framework, sub-agent phases |
| [`docs/research-loop.md`](./docs/research-loop.md) | Narrative walkthrough of the 10-agent Expedition pipeline |
| [`CONTRIBUTING.md`](./CONTRIBUTING.md) | How to add a new skill / agent / MCP / migration |
| [`SECURITY.md`](./SECURITY.md) | Vulnerability reporting + hardening posture |
| [`CODE_OF_CONDUCT.md`](./CODE_OF_CONDUCT.md) | Standard code of conduct |
| [`SKILLS.md`](./SKILLS.md) | Auto-generated index of all 64 skills |
| [`MCP_SERVERS.md`](./MCP_SERVERS.md) | Auto-generated index of custom MCPs |
| [`EXTERNAL_MCPS.md`](./EXTERNAL_MCPS.md) | Third-party MCPs Coscientist consumes |
| [`CHANGELOG.md`](./CHANGELOG.md) | Auto-generated from ROADMAP.md |
| [`CLAUDE.md`](./CLAUDE.md) | Agent-facing project guide |
| [`RESEARCHER.md`](./RESEARCHER.md) | Research principles for sub-agents |
| [`ROADMAP.md`](./ROADMAP.md) | Full version log + future work |

## Skills

For a complete auto-generated index of every skill with frontmatter
description, see [SKILLS.md](./SKILLS.md). Regenerate via `uv run
python -m lib.skill_index > SKILLS.md` (a CI test enforces parity).

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
| `record_hypothesis.py` | Register a hypothesis (from architect / visionary / mutator) at default Elo 1200 |
| `record_match.py` | Update both hypotheses' Elo (K=32) given a winner; persist match + reasoning |
| `pairwise.py` | Emit pairings: round-robin / top-k-vs-rest / top-k-internal; `--exclude-played` |
| `leaderboard.py` | Top-N by Elo with W-L-M counts and ancestor lineage |

Associated sub-agents: `ranker` (pairwise judge), `evolver` (sharpen / recombine / re-aim top-K).

### Infrastructure & smoke tests (v0.12.1 → v0.23)

After the feature surface stabilised we did multiple tightening passes — primitives, adoption, dry-run harnesses, persona-quality cleanup, plus full subsystem dogfooding:

- **v0.12.1** — five hardening fixes (hedge-word context-stripping, PDF magic-byte integrity check, novelty-anchor uniqueness, Elo K-factor decay, calibration band hard-fail).
- **v0.13** — five infrastructure primitives in `lib/`: `migrations.py` (idempotent schema migrations), `transaction.py` (multi-DB atomic writes), `lockfile.py` (concurrent-write serialisation), `retry.py` (sync + async retry-with-backoff), and journal disk-mirror drift detection.
- **v0.14** — wired those primitives into the seven skills that needed them. Atomicity proof: dropping a target table mid-run rolls back the run-DB write too.
- **v0.15** — dry-run harness for the deep-research run-pipeline state machine. Surfaced + fixed a silent no-op on unknown phase names.
- **v0.16-v0.17** — dry-run harness for the per-paper state machine + closed two cracks (audit-log gap on integrity reject; non-monotonic triage).
- **v0.18-v0.19** — persona output JSON schemas tightened on all 9 deep-research personas (grounder/historian/gaper, then vision/theorist/rude/synthesizer/thinker/scribe) after live smoke-test exposed shape ambiguity.
- **v0.20** — pdf-extract dry-run harness with 4 CRACK-pinning tests; **v0.23** closed all four (state guard, PDF integrity, artifact_lock, pandoc-style bib parser).
- **v0.21** — manuscript subsystem end-to-end dogfood across `ingest → validate → audit → critique → reflect`.
- **v0.22** — `docs/MCP-SETUP.md` consolidated MCP API-key requirements.

### A1 manuscript-subsystem completion (v0.26 → v0.27)

Four sub-skills completing the A1 manuscript lifecycle:

| Skill | Job |
|---|---|
| `manuscript-draft` | Outline → section → revision scaffold with 5 venue templates (IMRaD, NeurIPS, ACL, Nature, thesis) |
| `manuscript-format` | Pandoc-driven export to LaTeX/.docx/PDF; strips placeholders; venue-aware |
| `manuscript-revise` | Respond-to-reviewers — parses structured review, emits response letter + revision plan; advances to `revised` |
| `manuscript-version` | Lightweight snapshot history (snapshot/log/diff/restore); auto-snapshots before restore; pure filesystem |

### Tier B completion (v0.28 → v0.30)

Major skills filling the medium-horizon roadmap:

| Skill | Job |
|---|---|
| `systematic-review` | PRISMA pipeline: protocol → search → 2-stage screen → extract → bias → flow diagram |
| `deep-research` *(overnight)* | `--overnight` mode: queue breaks instead of blocking; auto-digest |
| `statistics` | Effect sizes, power analysis, meta-analysis, test selection, assumption checks (pure stdlib) |
| `figure-agent` | Register/audit/caption figures; colorblind-safe palette validation (Machado 2009) |
| `peer-review` | Multi-round full peer-review cycle simulation per manuscript |
| `retraction-watch` | Two-phase scan of cited papers; alert + journal entry; status table |
| `preprint-alerts` | Per-project subscription to topics/authors/sources; daily digest filtering |
| `grant-draft` | NIH/NSF/ERC/Wellcome funder-specific section templates |
| `idea-attacker` | Standalone adversarial stress-tester for working hypotheses (10-attack checklist; gate-enforced) |

### Tier C Phases 1+2 (v0.31 → v0.32)

12 additional skills covering full research-life ergonomics:

**Phase 1 — quick wins** (v0.31):

| Skill | Job |
|---|---|
| `negative-results-logger` | First-class artifact for failed experiments (`logged → analyzed → shared`) |
| `dataset-agent` | Local registry with DOI/license/sha256 hash tracking + versions |
| `credit-tracker` | CRediT taxonomy (14 roles) per author per manuscript; audit + statement export |
| `reading-pace-analytics` | Read-only velocity/backlog/trend metrics over `reading_state` |
| `slide-draft` | Manuscript → beamer/pptx/revealjs/slidev via pandoc; 4 styles |
| `reviewer-assistant` | Scaffold for *your* peer review of someone else's paper (NeurIPS/ICLR/Nature/generic) |

**Phase 2 — medium-value** (v0.32):

| Skill | Job |
|---|---|
| `citation-alerts` | Two-phase tracker for who's citing your published papers; daily digests |
| `field-trends-analyzer` | Read-only graph aggregations: top concepts/papers/authors + rising/declining momentum |
| `dmp-generator` | NIH DMSP, NSF DMP, Wellcome OMP, ERC FAIR templates |
| `ethics-irb` | IRB application (exempt/expedited/full-board) + per-project COI registry |
| `registered-reports` | Stage 1/Stage 2 RR pathway state machine (7 monotonic states) |
| `zenodo-deposit` | Bridges `dataset-agent` to Zenodo REST API; mints DOIs (real auth + sandbox) |

### Tier C Phase 3 (v0.33 + v0.34)

Karpathy-style experimentation pipeline + Sakana-style sandboxed execution loop + cross-project analytics:

| Skill | Job |
|---|---|
| `experiment-design` | Karpathy-style discipline: single metric, fixed budget, hypothesis+falsifier, preregistration. New `experiment` artifact. |
| `reproducibility-mcp` | Docker-backed sandbox: `--network none`, memory/CPU/wall-time caps, read-only FS, non-root user, audit log. |
| `experiment-reproduce` | Closes Sakana loop: run preregistered protocol → analyze pass/fail → reproduce-check within tolerance. |
| `project-manager` | Project lifecycle CLI + single global active-project marker. |
| `meta-research` | Cross-project trajectory + concept overlap + productivity (read-only). |

Plus `reference-agent --format csl-json` flag.

### Sandbox + sub-agents + institutional-access (v0.35 → v0.43)

Hardened the sandbox boundary, added 4 new sub-agent personas, and built out institutional-access for any university — not just the original UM-only path.

| Version | What landed |
|---|---|
| v0.35 | 4 new personas (`experimentalist`, `dataset-curator`, `peer-reviewer`, `grant-writer`); first end-to-end live Sakana loop on real Docker. |
| v0.36 | Sandbox tightening: structured Docker readiness diagnosis, `error_class` taxonomy (`timeout`/`killed_or_oom`/`image_not_found`/...), workspace-path validation, NaN/Inf metric guards. |
| v0.37 | Workspace lockfile + 15 orphaned v0.36 tests wired in. |
| v0.38 | Tournament evolve-loop ledger (`evolution_rounds` table + schema migration v3) with plateau detection chained across closed rounds. |
| v0.39 | `institutional-access check` health check (adapter signatures, Playwright readiness, storage_state presence). |
| v0.40 → v0.42 | UM auto-login → 11 publisher adapters (ACM/ACS/Elsevier/Emerald/IEEE/JSTOR/Nature/SAGE/Springer/Wiley + generic) → smart DOI prefix-first router with host-fallback → fully institution-agnostic IdP runner reading `institutions/<slug>.json`. |
| v0.43 | Cookie-import bypass for captcha-walled OpenAthens portals: log in via real Chrome, export cookies, normalise into Playwright `storage_state.json`. |

### Audit-tools family + final coverage push (v0.44 → v0.45.7)

| Version | What landed |
|---|---|
| v0.44 | `audit-query` skill — read-only forensic view across `audit.log` (PDF fetches) + `sandbox_audit.log` (Docker runs). Subcommands `fetches | sandbox | summary`. Pure stdlib. Markdown render via `--format md`. |
| v0.45 | `audit-rotate` skill — size/age-based rotation by atomic `Path.rename`. Never deletes. Subcommands `inspect | rotate | list-archives`. |
| v0.45.1 | `audit-query --include-archives` flag unions over rotated archives. |
| v0.45.2 | Deduped archive discovery into `lib.cache.archives_for`. |
| v0.45.3 → v0.45.6 | Test coverage push: `research-eval` (eval_references + eval_claims), `paper-discovery` (merge/rank/CLI), `arxiv-to-markdown` (with mocked extractor), `lib.rate_limit`. Every skill + every lib module now has at least one test. |
| v0.45.7 | Stricter agent-frontmatter regression: name/description/tools required, name matches filename, tools parses as list (inline JSON or YAML block sequence), each tool is a known surface or recognised MCP namespace. Pins all 31 personas. |

Test suite progression: 251 (v0.13) → 310 (v0.17) → 507 (v0.28) → 651 (v0.29) → 673 (v0.30) → 789 (v0.31) → 833 (v0.32) → 894 (v0.33) → 923 (v0.34) → 927 (v0.36) → 965 (v0.43) → 1047 (v0.45.7) → 1133 (v0.53.7) → 1233 (v0.51) → 1251 (v0.54) → 1283 (v0.55) → **1309 (v0.56, current)**. All passing.

### v0.51 → v0.56 — Wide Research, parallelization, Tier-A capstone

| Version | What landed |
|---|---|
| v0.51 | Phase 1 parallel dispatch — cartographer/chronicler/surveyor run concurrently. 30-60min → 15-25min. |
| v0.52 | Search-strategy depth — PICO/SPIDER, adversarial pre-Phase-1 critique, era detection, concept velocity. |
| v0.53 | **Wide Research** mode + Wide → Deep handoff. 6 task types, HITL gates, $50 ceiling, telemetry. |
| v0.54 | Brief richness — hypothesis cards + evidence tables + Socratic questions + RUN-RECOVERY.md. |
| v0.55 | **A5 trio** — gap-analyzer + contribution-mapper + venue-match. |
| v0.56 | **Self-play debate** — PRO/CON/JUDGE for borderline novelty/publishability/red-team verdicts. |

### v0.57 → v0.92 — DB persistence, ranker integration, observability foundation

| Version | What landed |
|---|---|
| v0.57 | DB persistence + db-notify pattern. |
| v0.58 | `resolve-citation` skill — incomplete refs → canonical_ids via S2. |
| v0.59 | `graph-viz` mermaid renderer. |
| v0.60 | Writing-style venue overlays. |
| v0.73 → v0.78 | 3 custom MCPs shipped — retraction-mcp, manuscript-mcp, graph-query-mcp. Plugin marketplace. |
| v0.79 | Tournament integration tests + lib.shortest_path + auto-CHANGELOG. |
| v0.80 → v0.88 | Plugin polish + checksums + install-check + scripts.py audit + skill index regen tests. |
| v0.89 → v0.92 | **Observability foundation** — execution traces (migrations v11+v12), agent quality scoring, trace renderer, error-context capture. |

### v0.93 → v0.119 — Instrumentation hookup + smoke-test infra

Wires the v0.89-v0.92 observability framework into every hot path:

| Range | What landed |
|---|---|
| v0.93–v0.96 | Phase / harvest / gate / MCP tool-call spans. Auto-quality on phase complete. Cross-run leaderboard. |
| v0.97–v0.100 | Stale-span detector + auto-close. Tool-call latency aggregator. Smoke-test runbook. |
| v0.101–v0.105 | Persona schemas (10 personas) + record-phase split (`--quality-artifact` separate from `--output-json`). Dict-aware OG rubrics. |
| v0.106–v0.110 | `lib.health` one-shot diagnostics + `/health` skill + harvest/gate summaries. Trace pruning. |
| v0.111–v0.114 | Prune empty DBs. Tool-call error spans (bug fix). Alert thresholds + CI exit codes. Threshold config file. |
| v0.115–v0.117 | CLAUDE.md observability docs. **OTLP-compliant trace export** (Jaeger/Honeycomb-ingestable). |
| v0.118–v0.119 | Session digest. Sub-agent spans around Task dispatches. |

### v0.120 → v0.137 — Production polish

Roadmap audit shows Tier A 5/5 + Tier B + Tier C all ✅; observability stack complete + interoperable.

| Range | What landed |
|---|---|
| v0.120–v0.123 | ROADMAP audit; open questions resolved; manuscript markdown-first formal lock; tournament wired into deep-research live path. |
| v0.124 | OTLP collector push (`lib.trace_export`) — POST traces to Jaeger/Honeycomb. |
| v0.125 | CI uv.lock fix (gitignore correction). |
| v0.126–v0.127 | Per-project health threshold overlay. Quality drift time-series + alert. |
| v0.128 | Plugin pre-commit hook auto-regens checksums + indexes + CHANGELOG. |
| v0.129 | Field-trends per-concept time-series (N-bucket histograms). |
| v0.130–v0.131 | CI fixes — plugin .mcp.json committed; pandoc-missing path fix; CacheLeakDetector flake. |
| v0.132–v0.133 | `scripts/test-like-ci.sh` + `scripts/ci-status.sh` for local-before-push CI emulation. |
| v0.134 | Persona doc static check — JSON examples in `.claude/agents/<name>.md` validated against `lib.persona_schema.SCHEMAS`. |

For full version history with per-version detail see [CHANGELOG.md](./CHANGELOG.md) (auto-generated).

## Observability + diagnostics

Every run emits OpenTelemetry-style spans. One operator command:

```bash
# Single-shot diagnostics across every run
uv run python -m lib.health
# Returns: active runs, stale spans, tool latency (slowest first),
# quality leaderboard (lowest-mean first), failed-span count,
# harvest summary, gate decisions, quality drift trend.
# Exit 0 clean / 1 warns / 2 critical alerts.
```

Drill in:

```bash
# Full timeline for one run (mermaid / md / json / otlp)
uv run python -m lib.trace_render --db <path> --trace-id <rid> --format md

# Tool-call latency (p50/p95/error rate per MCP)
uv run python -m lib.trace_status --tool-latency

# Find + close hung spans
uv run python -m lib.trace_status --stale-only --mark-error

# Push to Jaeger/Honeycomb
uv run python -m lib.trace_export --db <path> --trace-id <rid>

# CI inspection
scripts/ci-status.sh
scripts/ci-status.sh --logs       # if failed
scripts/test-like-ci.sh           # emulate CI before push
```

See `docs/SMOKE-TEST-RUNBOOK.md` for the full operator walkthrough.

## MCP servers used

Registered in `.mcp.json`:

- **Consensus** (HTTP+OAuth) — semantic search + claim extraction over 200M papers
- **paper-search-mcp** — 25+ sources, OA fallback downloads
- **academic-mcp** — 19+ sources including IEEE/Springer/ScienceDirect
- **Semantic Scholar** — citation graph traversal
- **Playwright MCP** — scripted browser for institutional-access
- **browser-use MCP** — LLM-guided browser fallback
- **Zotero** (local) — wraps Zotero's HTTP API for institutional PDF resolution + permanent library

For per-MCP API-key requirements and where to obtain each (Semantic Scholar, OpenAI for browser-use, IEEE / Scopus / Springer / Elsevier for premium search, Zotero local-vs-Web), see [`docs/MCP-SETUP.md`](docs/MCP-SETUP.md).

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

Currently **1309 tests, 0 failing** across all skills, gates, lib primitives, dry-run harnesses, agent-frontmatter regression, Wide Research, mode selector, phase-group concurrency, brief renderer, A5 trio, self-play debate, and integration checks.

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
