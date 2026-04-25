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

### v0.9 — citation validation completeness

Answers the question "what happens when we can't resolve references, or a citation isn't in the ref list?" Before v0.9 the answer was "nothing is flagged". Now every failure mode is detected, persisted, and surfaced to the author.

Schema (+1 table, 26 total):
- `manuscript_references` — parsed bibliography entries with ordinal, entry_key, raw_text, doi, year, resolved_canonical_id; UNIQUE on `(manuscript_id, ordinal)`

Enhanced `manuscript-ingest`:
- Bibliography parser detects `## References` / `## Bibliography` / `## Works Cited` sections
- Handles three bib styles: numbered `[1]`, markdown bullets `-`, and BibTeX blocks `@article{key, ...}`
- Extracts DOI, year, title (BibTeX), and infers `entry_key` from Author+Year patterns when not explicit
- Writes every bib entry into `manuscript_references`

New script `manuscript-ingest/scripts/validate_citations.py`:
- Four cross-checks:
  - **dangling-citation** (major): in-text key with no matching bib entry
  - **orphan-reference** (minor): bib entry never cited
  - **unresolved-citation** (minor): citation_key with NULL resolved_canonical_id
  - **broken-reference** (major): canonical_id set but paper artifact missing on disk
- Fuzzy matching: exact key, numeric ordinal, and author-year heuristic
- Writes `validation_report.json` to the manuscript artifact
- Populates `manuscript_audit_findings` with `claim_id='citation-validator:<key>'` so findings surface alongside audit results
- `--fail-on-major` for CI gating (exits 2 on dangling or broken)

Audit gate: `VALID_KINDS` extended to accept the four new kinds, so the manuscript-auditor sub-agent can also emit them directly.

Sub-agent persona update: `manuscript-auditor.md` now runs `validate_citations.py` first and reports dangling/broken findings to the author in the summary — these are flagged as **integrity issues** that need fixing before submission.

Tests (17 new, 158 total; 0 failing):
- Bib parser: numbered, bullet, BibTeX-block styles; no-bib-section case; entry_key inference
- Ingest writes references: manuscript_references populated with correct ordinals and years
- Validation: clean manuscript passes; each of the 4 failure modes detected independently; `--fail-on-major` exits 2; findings land in manuscript_audit_findings
- Audit gate: accepts `dangling-citation` and `broken-reference` kinds
- Schema: table + UNIQUE constraint on (manuscript_id, ordinal) enforced

### v0.10 — citation key collision disambiguation

Answers: "what if `wang2020` matches two different Wang-2020 papers in the bib?" Before v0.10, the matcher silently picked the first hit — wrong attribution, no flag. Now collisions are auto-suffixed `wang2020a` / `wang2020b` and any in-text key that maps to >1 entry is flagged.

Schema (column added to `manuscript_references`):
- `disambiguated_key` — entry_key + a/b/c suffix for collisions; equal to entry_key when unique; new index `idx_msrefs_disamb`

Disambiguation logic in `manuscript-ingest`:
- New `disambiguate_entry_keys(entries)` helper groups by inferred entry_key; collisions get suffixes by ordinal order (earliest = `a`)
- New `collision_groups(entries)` helper returns just the colliding groups for reporting
- Persistence path now writes `disambiguated_key` column

`validate_citations.py` upgrades:
- `_match_bib_candidates` returns *all* matches (not just first) so collisions surface
- New finding kind `ambiguous-citation` (major) when one in-text key matches ≥2 bib entries — includes `candidates` list with the suggested disambiguated keys to rewrite to
- `disambiguated_key` exact match (e.g. author wrote `\cite{wang2020a}`) takes precedence over `entry_key` match — clean resolve
- New `collision_groups` section in the report surfaces the bib's internal collisions even when no in-text citation is currently ambiguous (so author can future-proof)
- `--fail-on-major` now also triggers on ambiguous

Audit gate `VALID_KINDS` extended with `ambiguous-citation`. Sub-agent `manuscript-auditor.md` updated.

Tests (14 new, 172 total; 0 failing):
- Disambiguation unit: unique pass-through; 2-way and 3-way collisions; None entry_key untouched; collision_groups helper
- Ingest persistence: `disambiguated_key` column populated correctly for collisions
- Validation: ambiguous detected when bib has 2 wang2020 + in-text uses plain `wang2020`; `\cite{wang2020a}` resolves cleanly with no ambiguous finding; collision_groups surfaced even without in-text ambiguity; `--fail-on-major` triggers on ambiguous; ambiguous-citation lands in manuscript_audit_findings
- Audit gate: accepts `ambiguous-citation` kind
- Schema: `disambiguated_key` column + index present

### v0.11 — personal knowledge layer (A4 complete)

The everyday research-life layer: capture observations, see your status across projects, find things you've already encountered. All read/write operations are deterministic; no LLM, no MCP fetches.

Schema (+1 table, 27 total):
- `journal_entries` — daily lab-notebook rows: date, body, JSON tags, JSON links to papers/manuscripts/runs/experiments

Three new skills + three new sub-agents:

**research-journal**:
- `add_entry.py` — append entry from stdin or `--text`; tags + links optional; date defaults to today UTC
- `list_entries.py` — filter by date range, tag, linked paper/manuscript/run
- `search.py` — case-insensitive substring search across bodies with snippet
- Mirrors every entry to `projects/<pid>/journal/<entry_id>.md` for greppability with non-Coscientist tools
- Sub-agent: `research-journal` — bias for capture over ceremony, validate links exist before recording, never edit existing entries (immutable log)

**project-dashboard**:
- `dashboard.py` — read-only aggregate across all projects (or one with `--project-id`)
- Reports: identity, last-7-day activity, reading state counts, manuscripts by state, open audit issues by kind, recent journal entries, graph stats
- JSON or Markdown output (`--format md` for daily review docs)
- Sub-agent: `project-dashboard` — read-only by construction, no editorializing

**cross-project-memory**:
- `search.py` — keyword search across paper titles/abstracts, concept nodes, manuscript_claims, journal entries; group by kind; respect `--kinds` filter
- `find_paper.py` — given canonical_id / DOI / title-fragment, list every project containing it with its state in each (registered, cited, reading-tracked, graph-only)
- Sub-agent: `cross-project-memory` — iterates every project DB, never writes, doesn't synthesize (use `/deep-research` if you want synthesis)

Tests (23 new, 195 total; 0 failing):
- Journal add: writes DB row + disk mirror; stdin path; tags + links round-trip; empty body rejected
- Journal list: all / by tag / by date range / by linked paper
- Journal search: substring match with snippet; empty query rejected
- Dashboard: empty state; aggregates one project (reading state, audit kinds, recent journal); markdown format renders; unknown project rejected
- Cross-project search: finds papers across 2 projects; finds journal entries; kinds filter works; invalid kind rejected
- Find paper: by canonical_id / DOI / title fragment; no-match returns empty appearances
- Schema: journal_entries table present

A4 complete. Tier A is now ✅ A1 (manuscript ingest+audit+critique+reflect, draft/revise/format/version pending), ✅ A2 (reference agent + graph), ✅ A3 (writing-style), ✅ A4 (personal knowledge layer), ✅ A5 (critical judgment). The four remaining A1 sub-skills (draft/revise/format/version) are pure generation work; everything analytical for Tier A is shipped.

### v0.12 — Tournament Elo + Evolution (Tier B first cut)

Google Co-scientist's pattern, applied. Pairwise self-play between candidate hypotheses; the top of the leaderboard gets mutated and re-enters. Every match recorded with the judge's reasoning; lineage walked via parent_hyp_id.

New skill `tournament` (4 scripts):
- `record_hypothesis.py` — register a hypothesis at default Elo 1200; rejects duplicate IDs, validates JSON arrays
- `record_match.py` — Elo update with K=32 (standard formula); winner can be a hyp_id or `draw`; counters incremented atomically; match row persisted with judge_reasoning
- `pairwise.py` — three strategies: round-robin, top-k-vs-rest, top-k-internal; `--exclude-played` skips already-judged pairs
- `leaderboard.py` — top-N by Elo with W-L-M counts and ancestor lineage (walks parent_hyp_id back to root)

Two new sub-agents:
- **`ranker`** — pairwise judge with explicit criteria (falsifiability, operationalization, cost of decisive test, grounded precedent, novelty). Steelmans both before picking. `draw` only when criteria are genuinely indistinguishable.
- **`evolver`** — three evolution kinds (sharpen, recombine, re-aim); 2–4 children per call; required parent_hyp_id; falsifier list non-empty per child; ≥5 supporting_ids per child.

`theorist` and `thinker` updated to register every hypothesis they produce in the tournament table.

Tests (22 new, 217 total; 0 failing):
- Record-hypothesis: default Elo 1200, duplicate hyp_id rejected, parent lineage recorded, invalid agent rejected
- Record-match: equal-initial winner gains +16 / loser -16, counters updated, draw moves nothing when equal, **underdog wins gain MORE than +16** (validates the formula's asymmetry), match row + judge_reasoning persisted, invalid winner rejected, self-match rejected
- Pairwise: round-robin n choose 2; top-k-vs-rest k×rest; top-k-internal k choose 2; --exclude-played subtracts already-judged pairs; <2 hypotheses rejected
- Leaderboard: sorted by Elo desc; ancestor chain walks correctly through 3 generations; markdown format renders
- Elo math units: expected_score symmetric at equal ratings; 400-Elo diff yields ~0.909 expected; update is zero-sum

Tier B has its first big-pattern adoption. Statistics MCP, PRISMA, retraction watch, preprint alerts still pending.

### v0.12.1 — hardening pass (5 trivial anomalies closed)

Five small-but-real failure modes from the anomaly analysis, fixed inline:

- Hedge-word scan now strips quoted spans (`"…"`, `'…'`, backticks) before regex. Lets a manuscript *quote* a reviewer's hedge without the gate refusing the audit.
- `paper-acquire` integrity check on every accepted PDF: minimum 200 bytes + `%PDF-` magic-byte prefix. Catches paywall HTML masquerading as a PDF.
- Novelty-anchor uniqueness — each contribution must cite ≥5 *distinct* prior works (not the same paper five times).
- K-factor decay in Elo (32 → 16 after 10 matches → 8 after 30) so early upsets matter and late matches don't whip the leaderboard.
- Calibration soft→hard fail: a publishability verdict's confidence must lie within the verdict band.

`lib/paper_artifact.py` lost its `slugify` dependency the same way `lib/project.py` did in v0.5.1 — replaced with the same inline `_slug()`. Zero external deps for the canonical-id helper.

### v0.13 — infrastructure primitives (5 medium-impact items)

The five non-trivial items from the anomaly pass became their own library modules — no skills changed yet, just the building blocks:

- `lib/migrations.py` — schema-version tracking + idempotent `ensure_current(db)`. Solves "old run DB without the v0.5 tables crashes the gate."
- `lib/transaction.py` — `multi_db_tx(db_paths)` context manager: BEGIN both, COMMIT both on clean exit, ROLLBACK both on raise. Solves split-brain dual-writes.
- `lib/lockfile.py` — `artifact_lock(art_dir, timeout)` over fcntl with marker-file fallback. Solves concurrent paper-acquire + paper-triage racing on the same manifest.
- `lib/retry.py` — `retry_with_backoff` (sync) + `aretry_with_backoff` (async) with exponential delay + jitter and explicit retryable-exception tuple. Solves transient MCP/publisher 429s.
- Journal disk-mirror drift detection: `list_entries.py` warns on missing-or-tampered markdown mirrors so the SQLite row stays the source of truth.

22 new tests; suite at 251 passing.

### v0.14 — adopting v0.13 primitives in the skills that need them

Wires the v0.13 infrastructure into every site that has a real failure mode it solves. Pure plumbing — no new skills, no schema changes — but the failure modes are now actually closed.

- `lib/project._connect` and `deep-research/scripts/db.py::_connect` now call `migrations.ensure_current()` on every open, so an older project DB picks up new migrations transparently.
- `paper-acquire/scripts/record.py` and `paper-triage/scripts/record.py` wrap all manifest mutations in `artifact_lock(art.root, timeout=30.0)`. Concurrent record calls against the same paper now serialize.
- `institutional-access/scripts/fetch.py` calls `aretry_with_backoff(attempt, max_attempts=3, base_delay=2.0, retryable=(TimeoutError, ConnectionError, OSError, PWTimeout))` around `adapter.fetch_pdf`. `SessionExpired` deliberately stays non-retryable — bubbles to exit code 10 so the user re-runs `login.py`.
- `manuscript-{audit,critique,reflect}/scripts/gate.py` `persist()` now opens both run DB and project DB through `multi_db_tx`, so any failure on one side rolls back the other. The inner write helpers no longer manage their own transactions.

Tests (`test_v0_14_adoption.py`, 16 new; suite at 267 passing):

- Static checks that each skill imports the matching primitive (so the wiring isn't silently regressed).
- Behavioral check: opening a fresh project DB populates `schema_versions`.
- Behavioral check: 4 threads calling `paper-triage` `record_one` against the same paper all complete with no manifest corruption.
- Async retry primitive retries flaky `TimeoutError` then succeeds; gives up after `max_attempts`.
- Atomicity proof: drop the project-side target table before invoking each gate → gate exits non-zero **and** the run DB row never appears (multi_db_tx rolled back the first leg).
- Sanity: clean dual-write still produces one row in each DB.

### v0.15 — dry-run harness for the deep-research pipeline (commit 4d0ebc1)

Drives `db.py` end-to-end without sub-agents or MCPs. Catches mechanical bugs in the run-pipeline state machine before they burn live session time.

Surfaced one real crack: `record-phase` with an unknown phase name silently no-op'd the `UPDATE`. An orchestrator typo (e.g. `theroist` for `theorist`) would have desynced the DB from what the orchestrator believed was recorded. Fixed in the same commit — `cmd_record_phase` now rejects unknown phase names AND unknown `(run_id, phase)` pairs with explicit errors.

Coverage (`tests/test_deep_research_pipeline.py`, 24 new; suite at 291): init writes 10 phases in canonical order with migrations applied; next-phase advances through every phase; BREAK_0/1/2 fire after social/gaper/synthesizer; full happy-path reaches DONE; mid-phase crash + resume reports the right current phase; record-claim persists with all field combinations; breaks are idempotent on re-resolve; out-of-order completion still flags the missing intermediate.

### v0.16 — per-paper state-machine dry-run harness (commit a9d1621)

Same pattern as v0.15 but for the per-paper lifecycle (`discovered → triaged → acquired → extracted → read → cited`). Drives `paper-triage/scripts/record.py`, `paper-acquire/scripts/record.py`, and `paper-acquire/scripts/gate.py` via subprocess.

Surfaced two real cracks pinned with tests in current-broken-state form (then fixed in v0.17): (a) integrity-rejected fetches wrote nothing to the audit log, losing forensic evidence of publishers serving paywall HTML or truncated payloads; (b) re-running triage on an already-acquired paper silently demoted state back to `triaged` and overwrote the original triage rationale.

Coverage (`tests/test_paper_state_machine.py`, 17 new; suite at 308): state transitions for every legal arc; gate.py refuses untriaged + sufficient=true papers with the right exit codes; integrity check rejects sub-200-byte and non-`%PDF-` payloads; audit log appended on every fetch outcome; argparse edge cases (missing `--canonical-id`, etc.) error cleanly.

### v0.17 — closing both per-paper cracks (commit f8ffbfa)

Both v0.16 cracks fixed; the two CRACK-pinning tests flipped from "documents broken behavior" to "asserts correct behavior" + 2 new tests added.

- `paper-acquire/scripts/record.py`: integrity rejections now produce an `action=rejected` audit line (with detail + bytes) **before** the SystemExit raises. Forensic evidence survives the rejection. The audit-line write happens inside the artifact lock; the SystemExit raises after the lock releases so the line definitely lands.
- `paper-triage/scripts/record.py`: refuses to re-triage when state is in `{acquired, extracted, read, cited}` unless `--force` is passed. The escape hatch is real (corrupted PDF needs re-fetch decision) but explicit. Manifest state and triage block are preserved on refusal.

Tests (suite at 310; 2 CRACK-pinning tests replaced + 2 added):
- `test_rejected_pdf_writes_audit_line_then_raises`, `test_rejected_html_payload_writes_audit_line` — exercise both magic-bytes and size-check branches.
- `test_triage_after_acquire_refuses_to_demote`, `test_triage_after_acquire_with_force_demotes_explicitly` — cover both the safe default and the `--force` escape hatch.

### v0.18 — persona output JSON specs (preventative)

Acted on the persona auditor's findings from the live smoke-test session: `grounder.md`, `historian.md`, `gaper.md` had loose output specifications (`{canonical_id, title, why_seminal}` style — array? object? prose?), which the auditor predicted would fail at first invocation in the same shape-ambiguity way `social` did before its v0.16 persona fix.

Each persona's `## Output` section now contains an explicit JSON schema with named fields, types, and length constraints, framed as a fenced code block the orchestrator can parse straight into `phases.output_json`. Pure prose change; no test additions needed (the existing `AgentFrontmatterTests` regression test still passes).

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

## Live smoke-test status (run aa41d0cb, paused 2026-04-25)

The first attempt to drive `/deep-research` end-to-end on a real question
("How should digital memory systems implement forgetting mechanisms — and
which approaches actually serve human memory rather than replace it?")
**paused at the social phase** for runtime reasons unrelated to Coscientist
itself. The mechanical pipeline is validated; the agent-quality side is not.

**What was validated by the live attempt:**

- `db.py init` + phase-state machine work in production (run id `aa41d0cb`
  exists and resumes cleanly).
- `record-phase --start` + `--error` + `--complete` round-trip works.
- The dry-run harnesses (v0.15 + v0.16) caught every mechanical bug that
  could have been caught from disk artifacts alone.

**What broke (in order of discovery):**

1. **Social persona batched its writes.** First social invocation made 80
   tool calls / 12 minutes / 48 MCP queries with **zero papers persisted**
   before hitting the Claude API stream-idle timeout. Fixed in commit
   `e8a6c97`: `social.md` now mandates per-angle persistence
   (query → `merge.py --run-id` → verify count grew → next angle), with a
   per-invocation budget of 6 angles / 30 MCP calls and a structured
   output JSON shape.

2. **Sub-agents do not inherit MCP access in some runtimes.** The retry
   reported `claude mcp list` empty inside the sub-agent and HTTP fallback
   blocked at the egress proxy. So even with the persona fixed, the
   sub-agent had no search path.

3. **The runtime itself cannot reach external paper APIs.** Trying to
   drive social manually from the orchestrator (option "c" in the
   smoke-test plan) hit the same `403 Forbidden` from
   `api.semanticscholar.org` — the egress proxy blocks the API for the
   parent agent too. Not a Coscientist bug; an environment constraint.

**Resume plan when we move to a runtime with paper-API egress:**

- [ ] **Verify external API egress** — one `mcp__semantic-scholar__search_papers`
      call must return papers, not 403. Without this, nothing else matters.
- [ ] **Verify sub-agent MCP inheritance** — spawn a one-shot sub-agent that
      calls one MCP tool. If it errors with "no such tool", the per-persona
      `tools:` declarations don't actually grant MCP access in that
      runtime, and we need to either fix the runtime or pivot the
      architecture (see next item).
- [ ] **If sub-agent MCP inheritance is unfixable**, refactor to
      orchestrator-calls-MCPs: the parent agent invokes MCP tools, writes
      results to disk via `merge.py`, and spawns sub-agents with paths to
      the shortlist files instead of MCP tool names. This loses some
      sub-agent isolation but is robust to runtimes without MCP
      propagation. ≈1–2 hours of persona refactoring (social, grounder,
      historian, gaper, theorist, thinker — every persona that searches).
- [ ] **Re-run on `aa41d0cb`** — the run is intentionally left in
      `started_at`-only state on social so resume picks up at the same
      phase. Or start a fresh run; nothing valuable was persisted.
- [ ] **Fix the two cracks the per-paper harness found** (separate from
      the smoke-test pause): paper-acquire silently skips audit log on
      integrity rejection; paper-triage record_one demotes state on
      re-triage. Both have failing tests pinning current behavior.

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
