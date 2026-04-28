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

### v0.19 — tighten the remaining 6 personas (commits ea6ba4f + e9a0064)

Auditor's second pass against `vision`, `theorist`, `rude`, `synthesizer`, `thinker`, `scribe` found the same Minor severity finding for all six — loose output specs. v0.19 applied the v0.18 schema pattern to each. Now all 9 deep-research personas have explicit JSON schemas in their `## Output` section.

ROADMAP also got a re-test entry confirming the smoke-test egress block from earlier in the session is environmental and persistent (probed with a fresh search_papers call, same 403). Plus a third runtime constraint surfaced: general-purpose sub-agents that need many tool calls before persisting reliably die at the Claude API stream-idle timeout (3 confirmed instances this session). Read-only Explore sub-agents and orchestrator-driven work are fine.

### v0.20 — pdf-extract dry-run harness (commit 0004c65)

Same v0.15/v0.16 playbook applied to pdf-extract. 12 tests covering pre-extract guards, the docling-not-installed branch, idempotency, argparse edges, plus three CRACK-pinning tests documenting issues to fix later: no `state==acquired` guard, no PDF magic-byte check, no `artifact_lock`. Suite 310 → 322.

### v0.21 — manuscript subsystem end-to-end dogfood (commit 8534470)

End-to-end run of `ingest → validate_citations → audit gate → critique gate → reflect gate` on a synthetic 800-word manuscript with mixed citation styles, a duplicate-author-year bib collision (wang2020 × 2), an orphan reference, and a dangling cite. Exercises every code path that's been only unit-tested. Surfaced one real UX crack: the bib parser supports three styles (`[N]`, `- bullet`, `@article{key, ...}`) but silently loses pandoc-style `@key prose` entries. Pinned with assertEqual(len, 0). Suite 322 → 324.

### v0.22 — MCP setup guide (commit e58aae0)

User asked which MCPs need API keys and where to get them. Researched the 7 upstream repos via WebFetch and consolidated into `docs/MCP-SETUP.md`: per-MCP table + sign-up URLs + the practical note that institutional users mostly don't need IEEE/Springer/Elsevier search keys because `institutional-access` (Playwright + OpenAthens) handles paid PDFs without per-publisher subscriptions.

### v0.46.4 — SEEKER → Expedition rebrand (25 personas across 6 narrative phases)

The 31-persona roster regrouped under six phases: **Expedition** (deep-research, 10), **Workshop** (manuscript subsystem, 6), **Tribunal** (critical judgment, 5), **Laboratory** (experimentation, 3), **Tournament** (hypothesis evolution, 2), **Archive** (knowledge layer, 5). Five names kept verbatim because they're already idiomatic in academic literature: novelty-auditor, publishability-judge, red-team, peer-reviewer, ranker.

| Phase A renames | Phase B-F renames |
|---|---|
| social → scout | manuscript-drafter → drafter |
| grounder → cartographer | manuscript-auditor → verifier |
| historian → chronicler | manuscript-critic → panel |
| gaper → surveyor | manuscript-reflector → diviner |
| vision → synthesist | manuscript-reviser → reviser |
| theorist → architect | manuscript-formatter → compositor |
| rude → inquisitor | idea-attacker → advocate |
| synthesizer → weaver | dataset-curator → curator |
| thinker → visionary | grant-writer → funder |
| scribe → steward | evolver → mutator |
| | reference-agent → librarian |
| | writing-style → stylist |
| | research-journal → diarist |
| | project-dashboard → watchman |
| | cross-project-memory → indexer |

Backward compat: `db.py PHASE_ALIASES` translates old SEEKER phase names → new Expedition names so in-flight runs from before v0.46.4 continue working. SQLite `phases.name` is TEXT — old run-DB rows survive untouched.

Live smoke validated: `db.py init` → `db.py next-phase` returns `scout`; `db.py record-phase --phase social --start` silently rewrites to `scout` and records OK.

### v0.46.3 — orchestration glue (Plan 5 Stage 4)

`db.py resume` now reports a `harvests:` section listing each search-using persona × phase + whether the shortlist file exists. `deep-research/SKILL.md` step 2 documents the per-persona MCP harvest mapping the orchestrator must perform before invoking each search persona.

### v0.46.2 — persona refactor (Plan 5 Stage 3)

Six search-using personas now read pre-harvested shortlist files instead of calling MCPs directly. Tools list shrunk from `["Bash", "Read", "Write", "mcp__consensus", ...]` to `["Bash", "Read", "Write"]` for: scout, cartographer, chronicler, surveyor, architect, visionary. Each body adds a "harvest.py show" instruction with graceful-degradation note when shortlist absent.

### v0.46.1 — harvest.py orchestrator-side MCP writer (Plan 5 Stage 2)

`.claude/skills/deep-research/scripts/harvest.py` with subcommands `write | status | show`. Ingests MCP results from stdin (or `--input-file`), dedups via paper-discovery's `merge_entries + rank`, applies per-persona budget caps (scout: 200/30, cartographer: 30/20, chronicler: 50/15, surveyor: 25/10, architect: 30/15, visionary: 30/15), saves shortlist via `lib.persona_input.save()`. Critical design: harvest.py does NOT call MCPs itself — orchestrator collects results and pipes them in. Tests: 14.

### v0.46 — lib.persona_input shortlist contract (Plan 5 Stage 1)

`lib/persona_input.py` — the read/write contract for per-persona shortlist files under `~/.cache/coscientist/runs/run-<id>/inputs/<persona>-<phase>.json`. Foundation for the orchestrator-calls-MCPs refactor (smoke-test resume item 3). PersonaInput dataclass + atomic save (tmp + rename) + load with schema-version validation + exists/list_for_run discovery helpers + canonical layout via `run_inputs_dir(run_id)` in `lib/cache.py`. Tests: 15.

### v0.45 — audit-rotate: size/age-based rotation for both audit logs

Companion to v0.44 audit-query. Pure stdlib, atomic via `Path.rename`.
Subcommands: `inspect | rotate | list-archives`. Rotation is rename
(never delete) — archives sit next to the live file with a UTC-stamp
suffix (`audit.log.20260427T093015Z`). Producers reopen the live
path on each write, so the swap is invisible. 11 new tests. Suite
988/0 (+11).

### v0.44 — audit-query: read-only forensic view over both audit logs

New `audit-query` skill aggregates over `~/.cache/coscientist/audit.log`
(PDF fetches) and `~/.cache/coscientist/sandbox_audit.log` (Docker runs).
Subcommands: `fetches | sandbox | summary`. Pure stdlib. Handles both
JSONL and the legacy free-text `key=value` lines paper-acquire wrote in
v0.1. `--format md` for one-screen forensic markdown render. Read-only
— never mutates either file. 12 new tests (FetchesTests, SandboxTests,
SummaryTests, CliTests). Suite 977/0 (+12).

### v0.43.1 — green suite hotfix

Two test regressions surfaced after v0.43:

1. `test_login_requires_credentials` passed only when developer had no
   `.env`. The script's `_load_env_file()` reads repo-root `.env`
   regardless of cwd, so stripping env vars wasn't sufficient. Added
   `COSCIENTIST_NO_ENV_FILE=1` opt-out the test sets explicitly;
   production behavior unchanged.

2. `test_docling_missing_errors_cleanly_on_default_engine` assumed
   `docling` absence → non-zero exit. With `pymupdf` installed,
   auto-mode `vision_fallback` opens the synthetic PDF and writes
   placeholder content.md, so extract.py succeeds. Test now accepts
   either clean-failure OR a recorded vision fallback in
   `extraction.log`.

Also: tightened Elsevier adapter with `wait_for_load_state("networkidle")`
+ debug print of landed URL/title before selector cascade. Suite 965/0.

### v0.43 — cookie-import bypass for captcha-walled OpenAthens

Direct Playwright login to UM's OpenAthens portal hit an endless
"Are you a robot?" captcha loop even with anti-detection (UA spoof,
`navigator.webdriver` patch, persistent context, real Chrome via
`channel="chrome"`). Pivoted to a workaround: log in via real Chrome,
export cookies via Cookie-Editor extension, import to Playwright
`storage_state.json` via new `import_cookies.py`. Normalises Cookie-Editor
JSON → Playwright schema (sameSite mapping, expirationDate→expires).
26 cookies imported across 7 domains; auth round-trip works.

`fetch.py` refactored from `launch_persistent_context` (which collided
with daily-driver Chrome's lockfiles) to `launch` + `new_context` with
`storage_state` only. Captcha vendors block fresh Playwright profiles
even with cookies; using a real-Chrome export sidesteps the bot check.

### v0.42 + v0.42.1 — institution-agnostic IdP runner + smart DOI router + JSTOR

Generalised `idp_um.py` → `idp_runner.py`. Reads
`institutions/<slug>.json` config; `IDP_PROFILES` dict per IdP kind
(MS Entra, Shibboleth classic, CAS, SimpleSAML, Okta, Auth0, manual).
Any institution adds a JSON; no code changes.

Smart adapter resolver (`adapters/__init__.py`): prefix-first
(10.1016 → Elsevier, etc.) → host-fallback (HEAD-resolve `doi.org`) →
generic. JSTOR adapter added (10.2307). Clearer error message on
unknown publisher, dogfood paper artifact seeded for testing.

### v0.41 — ACM, Emerald, SAGE adapters + generic fallback

Three more publisher adapters + a `generic.py` fallback that tries
common PDF-link patterns. Total registry: ACM (10.1145), ACS (10.1021),
Elsevier (10.1016), Emerald (10.1108), IEEE (10.1109), JSTOR (10.2307),
Nature (10.1038), SAGE (10.1177), Springer (10.1007), Wiley (10.1002),
plus generic.

### v0.40 — UM (University Malaya) auto-login

First concrete institution config. OpenAthens federation entry through
UM's IdP. Stores `storage_state.json` under
`institutional-access/state/`. Headful Playwright; honours real-profile
constraints.

### v0.39 — institutional-access health check (dry-run)

`check.py` — adapter-signature regression check + Playwright readiness
+ `storage_state.json` presence + adapter registry size. Distinct from
`paper-acquire` (which fetches); this one validates the toolchain
without making a single network request. JSON output for `paper-acquire`
to consume before invoking institutional-access tier.

### v0.38 + v0.38.1 — tournament evolve-loop orchestration ledger

Out-of-band ledger (`evolution_rounds` table, schema migration v3) for
the tournament/evolution loop. `evolve_loop.py` subcommands:
`open-round | close-round | status | lineage`. Plateau detection
chains via prior-closed-round lookup (so consecutive rounds without
top-Elo improvement increment a counter). End-to-end integration test
spans open → record_match → record_hypothesis (child) → close → repeat.

### v0.37 — workspace lockfile + register v0.36 tests in run_all

`reproducibility-mcp/sandbox.py` cmd_run now wrapped in
`artifact_lock(workspace, timeout=lock_timeout)` to prevent concurrent
runs from racing on the same workspace dir. New `--lock-timeout` flag
(default 0 = fail fast). Also caught 15 v0.36 tests that had been
authored but not registered in `tests/run_all.py`
(DiagnoseTests, ValidateWorkspaceTests, CmdRunValidationTests,
WorkspaceLockTests). Wiring bug — not behavior bug. Suite jumped
from 912 → 927.

### v0.36 — tighten Docker error handling + edge cases

Hardening pass on the sandbox boundary. Suite 927/0 (+4 net vs v0.35).

**`reproducibility-mcp/sandbox.py`:**

- `_docker_diagnose()` — structured readiness check returning `{ready, reason, detail, remediation}`. Reasons: `binary_missing`, `daemon_down`, `daemon_slow`, `permission_denied`, `binary_broken`, `unknown`. `cmd_check` now emits these fields so callers (and humans) get an actionable hint instead of "Docker unreachable."
- `_classify_run_error(stderr, exit_code)` — maps Docker's actual failure modes to a tag: `image_not_found` (no such image / pull access denied / manifest unknown), `network_error`, `permission_denied`, `daemon_died`, `timeout` (exit 124), `killed_or_oom` (exit 137), `docker_invocation_error` (exit 125), `unknown`. Surfaced as `error_class` field in both audit log and run response.
- `_validate_workspace(path)` — pre-flight for the bind mount: rejects nonexistent / non-directory / non-readable / non-writable paths, **rejects symlinks** (mount-escape vector), rejects paths inside `/etc /var/run /proc /sys /dev`. Replaces the old inline `exists() / is_dir()` checks in `cmd_run`.
- Numeric guards in `cmd_run`: `memory_mb >= 16`, `cpus > 0`, `timeout_seconds > 0` — silently misconfigured runs are now SystemExit before invoking Docker.
- Audit-id collision guard: when caller passes `--audit-id` (e.g. from `experiment-reproduce`), refuses if the ID is already in the log. Auto-generated IDs are unique by `time_ns()` so unaffected.
- Audit-log writes now wrapped in `try/except OSError`. Disk-full / permission failures no longer crash the run; the run result is returned with a top-level `audit_log_warning` field instead. Run result is authoritative; audit log is best-effort.

**`experiment-reproduce/reproduce.py`:**

- `_is_finite_number(v)` helper. `_extract_metric()` now rejects non-finite values (NaN, ±Infinity) and Python booleans (which are `isinstance(_, int)` and would have slipped through). `cmd_analyze` re-validates the recorded `metric_value` and refuses to compare NaN/Inf to a target.

**Tests added:**

- `DiagnoseTests` (6) — error classification per Docker failure mode
- `ValidateWorkspaceTests` (5) — nonexistent / not-dir / symlink rejected / sensitive-path rejected / valid passes
- `CmdRunValidationTests` (4) — invalid memory / cpus / timeout / audit-id collision all SystemExit
- `MetricExtractionTests` extended (4) — NaN / Infinity / bool / `_is_finite_number` rounds

**Failure-mode dogfood — validated on real Docker (Desktop 4.70.0, Engine 29.4.0, darwin/arm64):**

| Test | Setup | Result |
|---|---|---|
| Timeout | `time.sleep(60)`, `--timeout-seconds 5` | audit `14dc8adb`: exit=124, `timed_out: true`, `error_class: "timeout"`, wall=5.06s |
| OOM | `bytearray(512 MB)`, `--memory-mb 64` | audit `ef9aeaf0`: exit=137, `memory_oom: true`, `error_class: "killed_or_oom"`, wall=0.12s |
| Script crash | `sys.exit(7)` | audit `f02c739f`: exit=7, `error_class: null` (passed through, not infra failure) |
| Image not found | `--image definitely-not-a-real-image:v999` | audit `03dff8d9`: exit=125, `error_class: "image_not_found"` |

All four paths classify correctly through the audit log + run response. Container teardown clean (no zombie containers via `docker ps -a`). The exit-code → `error_class` mapping that v0.36 wired is now live-validated.

### v0.35 — Sub-agent personas + live Sakana loop validated end-to-end

4 new personas + first successful end-to-end run of the Sakana experimentation loop on real Docker. Suite still 923 passing.

**Live integration test (Sakana loop, run `sakana_live_test_aca278`):**

After Docker Desktop daemon came up (intermittent on this machine due to broken symlink at `/usr/local/bin/docker`), the full pipeline ran:

| Phase | Audit ID | Wall time | Result |
|---|---|---|---|
| sandbox `check` | — | — | `ready: true` (Docker 29.4.0) |
| sandbox `run` (warmup) | `66518ce3` | 7.4s | exit 0, image pulled (~37 MB) |
| `experiment-design init` | — | — | state=`designed` |
| `variable` × 3 (indep+dep+control) | — | — | gates passed |
| `metric` (accuracy ≥ 0.85) | — | — | recorded |
| `preregister` (60s, 512MB) | — | — | state=`preregistered`; preregistration.md written |
| `experiment-reproduce run` | `96a32cf0` | 0.148s | state=`completed`, metric=0.92 from `result.json` |
| `analyze` | — | — | state=`analyzed`, `passed: true` (0.92 ≥ 0.85) |
| `reproduce-check` (5% tolerance) | `2215c728` | 0.148s | state=`reproduced`, diff=0%, within tolerance |

3 entries in `~/.cache/coscientist/sandbox_audit.log`. Per-run artifacts in `experiments/<eid>/runs/<audit_id>/`. The Sakana iteration loop is **operational on real Docker**, not just mocked.

**4 new sub-agent personas:**

- **experimentalist** — orchestrates the full Sakana loop (design → preregister → sandbox run → analyze → reproduce-check). Hard rules: single primary metric, fixed budget, hypothesis ≠ falsifier, sandbox-only execution, reproduce-check before believing. Names every failure mode (Docker down, OOM, timeout, script error, no metric, reproduction outside tolerance) with explicit recovery.
- **dataset-curator** — manages dataset artifacts end-to-end (register → hash → version → Zenodo prepare → deposit). Hard rules: hash before deposit, validate via prepare first, license required + explicit, sandbox before production, frozen on deposit.
- **peer-reviewer** — drafts structured peer review of someone else's manuscript. Distinct from manuscript-critic (own work) and peer-review simulator (own paper). Hard rules: no anonymous reasoning, steelman before each weakness, no pile-on, calibrated confidence, no self-reveal.
- **grant-writer** — funder-specific grant scaffolds (NIH/NSF/ERC/Wellcome). Specific Aims first, premortem each aim, Significance ≠ Innovation, parallel not serial aims, budget reality check, companion DMP/IRB.

`tests/test_agents.py` allowlist updated; LayoutRegressionTests still passes.

**Known intermittent issue:** Docker Desktop on this machine has a stale symlink (`/usr/local/bin/docker → /Applications/Docker.app/Contents/Resources/bin/docker`, which doesn't exist in Docker Desktop 4.x). The daemon comes up after `open /Applications/Docker.app` and stays reachable from already-running shells, but new shells sometimes can't find the binary. Workaround: reinstall Docker Desktop, or symlink to wherever the actual binary lives in this Docker version. Doesn't affect the skill itself — `sandbox.py check` correctly reports `ready: false` and refuses to run when daemon is unreachable.

**Failure-mode dogfood deferred:** Real-Docker tests of timeout / OOM / non-zero-exit paths are still pending — they run via the same sandbox.py `run` command, but the testbed lost docker-binary access mid-session before they could be exercised. Stub-mode tests (`tests/test_sandbox.py::RunRequiresDaemonTests` and `test_experiment_reproduce.py`) cover the *control-flow* of these failures via mocked `_docker_available`; what's not yet validated on real Docker is that exit code 137 (OOM) and exit code 124 (timeout) actually surface correctly through the audit log + `last_run` fields. Re-run after Docker is reinstalled with: a script that allocates >memory_mb and a script that sleeps past timeout_seconds.

**4 new sub-agent personas:**

- **experimentalist** — orchestrates the full Sakana loop (design → preregister → sandbox run → analyze → reproduce-check). Hard rules: single primary metric, fixed budget, hypothesis ≠ falsifier, sandbox-only execution, reproduce-check before believing. Names every failure mode (Docker down, OOM, timeout, script error, no metric, reproduction outside tolerance) with explicit recovery.
- **dataset-curator** — manages dataset artifacts end-to-end (register → hash → version → Zenodo prepare → deposit). Hard rules: hash before deposit, validate via prepare first, license required + explicit, sandbox before production, frozen on deposit.
- **peer-reviewer** — drafts structured peer review of someone else's manuscript. Distinct from manuscript-critic (own work) and peer-review simulator (own paper). Hard rules: no anonymous reasoning, steelman before each weakness, no pile-on, calibrated confidence, no self-reveal.
- **grant-writer** — funder-specific grant scaffolds (NIH/NSF/ERC/Wellcome). Specific Aims first, premortem each aim, Significance ≠ Innovation, parallel not serial aims, budget reality check, companion DMP/IRB.

`tests/test_agents.py` allowlist updated; LayoutRegressionTests still passes.

### v0.34 — Tier C Phase 3 complete: Sakana experimentation loop closed

2 new skills closing the experimentation pipeline. Suite at 923 passing, 0 failing (+29 tests vs v0.33).

**reproducibility-mcp** (Phase 3B) — Docker-backed sandbox CLI (despite name, not an MCP server). Subcommands: `check / run / audit`. Hardened security model: `--network none`, memory + CPU caps, `--read-only` filesystem with writable `/workspace` bind mount + `--tmpfs /tmp`, non-root user (1000:1000), `--security-opt no-new-privileges`, `--rm` cleanup, OOM detection (exit 137), wall-time timeout via `subprocess.run(timeout=)`, append-only audit log at `~/.cache/coscientist/sandbox_audit.log` (JSONL). 15 tests (helpers + build-args verification + audit log; integration tests use stubbed `_docker_available`).

**experiment-reproduce** (Phase 3C) — closes the Sakana loop. Subcommands: `run / analyze / reproduce-check / status`. Reads protocol.json budget + workspace, invokes sandbox, parses metric (priority: `result.json` → last stdout line as JSON), records per-run artifacts under `experiments/<eid>/runs/<audit_id>/`. State machine advances `preregistered → running → completed → analyzed → reproduced`. `analyze` computes pass/fail using protocol's comparison + target. `reproduce-check` runs second sandboxed pass and verifies metric within tolerance (default 5% relative diff). Rolls back state to `preregistered` on Docker failure. 14 tests (sandbox boundary mocked).

The full Sakana iteration loop is now operational:
- `experiment-design` — design + preregister with Karpathy discipline
- `reproducibility-mcp` — sandboxed exec, isolation, audit
- `experiment-reproduce` — orchestrate run + analyze + reproduce

### v0.33 — Tier C Phase 3 partial: experiment-design + project-manager + meta-research + cleanup

3 new skills + 1 enhancement + 1 deletion. Suite at 894 passing, 0 failing (+61 tests vs v0.32).

**experiment-design** (Phase 3A): Karpathy-style discipline scaffold. New `experiment` artifact under `experiments/<eid>/` with state machine `designed → preregistered → running → completed → analyzed → reproduced` (already in lib.artifact since v0.3). Subcommands: `init / variable / metric / preregister / status / list`. Gates: ≥1 hypothesis, ≥1 falsifier (must differ), ≥1 independent + ≥1 dependent variable, exactly 1 primary metric, budget > 0. Optional `--rr-id` link to registered-reports for full pre-registration. Generates human-readable `preregistration.md`. 26 tests.

**project-manager** (Phase 3D): Project lifecycle CLI wrapping `lib.project`. Subcommands: `init / list / activate / current / deactivate / archive / unarchive / status`. Single global active-project marker at `~/.cache/coscientist/active_project.json` — public `get_active_project_id()` API for other skills. Soft-delete archive (writes `archived_at`); auto-deactivates if archiving the active project. Distinct from project-dashboard (read-only view). 23 tests.

**meta-research** (Phase 3E): Cross-project read-only aggregation. Subcommands: `trajectory` (per-year manuscript counts by state), `concepts` (concepts in ≥N project graphs), `productivity` (per-project artifact counts + activity windows), `summary` (combined view; JSON or Markdown). Read-only by construction (verified via mtime). 12 tests.

**reference-agent enhancement**: `--format csl-json` flag on `export_bibtex.py`. Builds CSL-JSON with author family/given splitting, `issued.date-parts`, `container-title`, DOI, URL (arXiv).

**Deleted**: `frontier-orchestration` skill — orphan (MCP not registered, different domain). Use frontier-broker as user-scope MCP if needed.

Phase 3 incomplete — 3B (reproducibility-mcp Docker backend) + 3C (experiment-reproduce) still pending. Higher-risk; needs dedicated session.

### v0.32 — Tier C Phase 2: 6 medium-value skills

Six more skills extending coverage. Suite at 833 passing, 0 failing.

- **citation-alerts** (`projects/<pid>/citation_alerts/`): two-phase tracker like retraction-watch — `list` papers needing refresh → caller queries S2 `get_paper_citations` → `persist` deltas. Daily digest output. 14 tests.
- **field-trends-analyzer**: read-only over project graph (`graph_nodes` + `graph_edges`). Top concepts by paper-count, top papers by in-degree, top authors, momentum (recent vs past windows: rising/plateau/declining). 9 tests.
- **dmp-generator**: funder-specific DMP scaffolds (NIH DMSP, NSF DMP, Wellcome OMP, ERC FAIR). Section templates with target words and notes. 6 tests.
- **ethics-irb**: IRB application templates (exempt 3 sections / expedited 6 / full-board 9) + COI registry per project (6 types: funding/consulting/stock/family/advisory/other). 6 tests.
- **registered-reports**: 7-state monotonic machine (stage-1-drafted → submitted → in-principle-accepted → data-collected → stage-2-drafted → submitted → published). History tracking; `--force` for backwards. 5 tests.
- **zenodo-deposit**: bridges dataset-agent to Zenodo REST API. `prepare` validates + emits metadata.json (no network). `upload` makes real API calls (requires `$ZENODO_TOKEN`). Sandbox mode. 4 tests (prepare-only; upload tested by user with real token).

### v0.31 — Tier C Phase 1: 6 quick-win skills

Six skills using established CLI-script + filesystem-state patterns. 116 new tests; suite at 789 passing, 0 failing.

**negative-results-logger**: New artifact kind `negative-result` added to `lib.artifact` (STATES + kind_root mapping). Captures hypothesis/approach/expected/observed → root_cause/lessons → shared_via. Pure filesystem. 18 tests.

**dataset-agent**: Local registry under `datasets/<dataset_id>/` with manifest + record + versions. Hash subcommand walks path lists, computes sha256/blake2s/sha512 with 100MB safety threshold (`--force-large` to override). License field validated against OSI/CC list with warnings on unknown values. 19 tests.

**credit-tracker**: 14 CRediT roles per author per manuscript under `manuscripts/<mid>/credit/contributions.json`. Audit gate: required roles (conceptualization, methodology, writing-original-draft) must each have ≥1 author; non-zero exit if not. Statement export in narrative + table styles. 23 tests.

**reading-pace-analytics**: Read-only across all `project.db`s with `reading_state` table. velocity (papers/week in window), backlog (counts by state + untouched-to-read count + oldest age), trend (12-week buckets with 4-week rolling avg), summary (combined). Verified read-only via mtime check; handles missing-table gracefully. 13 tests.

**slide-draft**: Manuscript → slide deck via pandoc. Two-stage: `outline` (style template → outline.json) + `render` (pandoc to beamer/pptx/revealjs, or direct markdown for slidev). 4 styles: standard/short-talk/long-talk/poster. Section-aware content extraction with case-insensitive prefix matching; placeholder stripping before pandoc. 20 tests.

**reviewer-assistant**: Structured peer-review scaffold under `reviews/<review_id>/`. 5 sections (summary/strengths/weaknesses/specific/required) + recommendation (5-level) + confidence (1-5). 4 venue templates (NeurIPS/ICLR/Nature/generic) with venue-specific extra sections. Markdown + JSON export; status flags ready_to_submit when complete. Distinct from manuscript-critique (own work) and peer-review (own paper). 23 tests.

ROADMAP.md updated to mark all six as shipped; Phase 2 items tagged for next iteration.

### v0.29 — Tier B completion: statistics, figure-agent, peer-review, retraction-watch, preprint-alerts, grant-draft

Six remaining high-leverage Tier B skills shipped. All pure stdlib Python, no sub-agents required (skills orchestrate via CLI scripts). 124 new tests; suite at 651.

**statistics** (new skill, 6 modules):
- `math_utils.py` — mean, variance, std, SEM, Cohen's d, r from t, pooled std; all pure math
- `effect_size.py` — Cohen's d, Hedges' g, Glass's delta, r from t, r from F, eta squared, omega squared, Cramér's V
- `power.py` — approximate power for t-test, ANOVA, chi-square, correlation (z-transform); sample-size solver via binary search
- `meta_analysis.py` — fixed-effects + random-effects (DerSimonian-Laird); Q statistic, I², tau²; forest-plot data
- `test_select.py` — decision-tree recommender (paired/independent t, ANOVA, Kruskal, Wilcoxon, Mann-Whitney, Fisher, chi-square, Pearson/Spearman, regression)
- `assumption_check.py` — Shapiro-Wilk approximation, Levene's test, autocorrelation check; returns pass/warn/fail per assumption

**figure-agent** (new skill, 4 scripts):
- `register.py` — register a figure artifact; assigns `figure_id = slug(title)_blake2s[:6]`; stores `manifest.json`
- `audit.py` — checks: palette colorblind-safe (validates named palettes), alt_text present, caption ≥20 chars, format matches venue (vector for print, raster OK for web); writes `audit_report.json`
- `caption.py` — generate/update caption; word-count check against venue floor
- `list.py` — list all figures for a manuscript with status summary

**peer-review** (new skill, 4 scripts):
- `review.py` — `generate_review(mid, venue, round_num)`; NeurIPS/ACL/Nature/Science → 3 reviewers, others → 2; `FileExistsError` on duplicate round
- `respond.py` — `record_response(mid, round_num, response_data)`; `FileNotFoundError` if no review for that round
- `decide.py` — `make_decision(mid, decision, rationale)`; validates `{accept,reject,major_revision,minor_revision}`; `ValueError` if no reviews yet
- `status.py` — per-round has_review/has_response + final decision

**retraction-watch** (new skill, 3 scripts):
- `scan.py` — two modes: `list` (dry-run, unions artifact_index + manuscript_citations + graph_nodes) and `persist` (upsert MCP results into `retraction_flags`); stale-flag check via `checked_at` age
- `alert.py` — reads `retraction_flags WHERE retracted=1`; writes `retraction_alerts.json`; calls `research-journal/scripts/add_entry.py` via subprocess if retractions found
- `status.py` — counts + ASCII table; handles missing table in old DBs

**preprint-alerts** (new skill, 4 scripts):
- `subscribe.py` — merge or replace subscription (topics, authors, sources ∈ {arxiv,biorxiv,medrxiv})
- `digest.py` — case-insensitive topic substring match on title+abstract; author substring match; writes `digest_YYYY-MM-DD.json`
- `list_subs.py` — current subscription + ASCII table
- `history.py` — list past digests newest-first with cap

**grant-draft** (new skill, 2 scripts):
- `outline.py` — FUNDERS dict (NIH R01/R21/K99/F31, NSF Standard/CAREER/RAPID/EAGER, ERC Starting/Consolidator/Advanced, Wellcome Discovery/Investigator/Collaborative); `build_outline`, `build_source_md`, `make_grant_id`, `count_words`, `extract_section`
- `draft.py` — 4 subcommands: `init` (scaffold with YAML frontmatter + per-section PLACEHOLDERs), `section` (fill/replace + word-count update in outline), `status` (drafted vs placeholder counts + word totals), `funders` (list all templates)

### v0.28 — systematic-review skill + overnight mode (Tier B second cut)

Two parallel builds, both pure filesystem + SQLite, no sub-agents.

**systematic-review** (new skill):
- `review.py` — 7 subcommands: `init` (protocol-first; freezes after `search`), `search` (records query strings), `screen` (title_abstract → full_text two-stage; idempotent), `extract` (one row per field per paper), `bias` (low/unclear/high per RoB domain), `prisma` (ASCII flow diagram → `prisma.md`), `status` (counts at every stage)
- 4 new DB tables: `review_protocols`, `screening_decisions`, `extraction_rows`, `bias_assessments`
- Each protocol gets its own lightweight `review.db` under `reviews/<protocol_id>/` — self-contained, no coupling to run DBs
- `protocol_id` derivation: `slug(title)_blake2s(title::question)[:6]` — consistent with manuscript_id pattern
- 34 tests across 8 classes

**overnight mode** (extends `deep-research`):
- `overnight.py` — 3 subcommands: `queue-break` (auto-resolves break with placeholder; errors if already resolved), `digest` (writes `digest.md` with break prompts + auto-answers + phase table + output paths; idempotent), `status` (queued vs user-resolved vs pending)
- `db.py` extended: `--overnight` flag on `init`; `is_overnight(con, run_id) -> bool` helper; `overnight` column added via `lib/migrations.py` v0.28 migration (idempotent ALTER TABLE)
- `deep-research/SKILL.md` updated with full overnight mode section
- 17 tests across 4 classes; existing pipeline tests unaffected

Tests: 51 new, 507 total, 0 failing.

### v0.27 — manuscript-format, manuscript-revise, manuscript-version (A1 complete)

Three parallel builds completing the A1 manuscript subsystem. All skills coexist alongside `manuscript-draft` (v0.26) and feed each other: draft → version snapshot → format export; draft → ingest → critique → revise.

**manuscript-format** (new skill + agent):
- `format.py` — subcommands: `export` (pandoc to `.tex`/`.docx`/`.pdf`), `list` (show all exports), `clean` (remove exports dir)
- `pandoc_utils.py` — `pandoc_available()`, `strip_placeholders()` (removes `[PLACEHOLDER...]` blocks + HTML comments before export), `build_pandoc_args()` (venue-to-pandoc option map)
- Venue support: `neurips`, `acl`, `imrad`, `nature`, `thesis` — each maps to appropriate pandoc `--to` args; source.md never modified
- Sub-agent `manuscript-formatter` added; applies RESEARCHER.md principles 3 + 12

**manuscript-revise** (new skill + agent):
- `revise.py` — subcommands: `ingest-review` (parse → `review.json`), `plan` (section-keyed action list → `revision_notes.md`), `respond` (response stubs → `response_letter.md`; state → `revised`), `status` (pending responses count)
- `review_parser.py` — parses `Reviewer N:` headers + numbered comments (four styles); pure module, no CLI
- State guard: blocks if state in `{submitted, published}`; `--force` overrides
- Sub-agent `manuscript-reviser` added; applies RESEARCHER.md principles 8 + 12

**manuscript-version** (new skill, no sub-agent — mechanical):
- `version.py` — subcommands: `snapshot`, `log`, `diff`, `restore`
- `version_store.py` — `snapshot_hash`, `make_version_id`, `list_versions`, `latest_version`, `section_word_counts`; pure logic module
- Version IDs: `v<N>-<YYYYMMDD-HHMMSS>` — sortable integer prefix, human-readable timestamp; prefix-match for ergonomic CLI use
- Restore always auto-snapshots current state first; no SQLite — all metadata in `meta.json` per version

Tests (99 new, 456 total; 0 failing):
- manuscript-format: 31 tests (PandocUtilsTests, FormatExportTests, FormatListTests, FormatCleanTests, CliEdgeTests)
- manuscript-revise: 42 tests (ReviewParserTests, IngestReviewTests, PlanTests, RespondTests, StatusTests, StateGuardTests, CliEdgeTests)
- manuscript-version: 26 tests (VersionStoreTests, SnapshotTests, LogTests, DiffTests, RestoreTests, CliEdgeTests)

A1 subsystem is now complete. Tier A is fully shipped.

### v0.26 — manuscript-draft skill (A1 second cut)

First cut of structured manuscript drafting: outline → section → revision scaffold with venue templates.

New skill `manuscript-draft` (3 scripts + 5 templates):
- `draft.py` — CLI with four subcommands: `init` (scaffold), `section` (fill/update one section), `status` (progress table), `venues` (list templates)
- `outline.py` — Outline data model + template loading; `outline.json` tracks per-section status, word_count, cite_keys
- `section.py` — Operations on `source.md` (section extraction/replacement, word counting, cite-key harvesting from all four citation styles)
- Five venue templates: `imrad`, `neurips`, `acl`, `nature`, `thesis` — each with per-section `notes`, `target_words`, `required` flag
- `manuscript_id` deterministic from `title::venue` (same formula as `manuscript-ingest`)

New sub-agent `manuscript-drafter`:
- Reads `outline.json` + `source.md` + project claims/papers as research context
- Drafts section-by-section, persists via `draft.py section` after each
- Applies RESEARCHER.md principle 12 (Draft to Communicate, Not to Sound Impressive)
- Exit test: all assigned sections at status `drafted`, word counts ≥60% of target, all cite keys resolved or marked `[CITATION NEEDED]`

RESEARCHER.md:
- Added **Principle 12: Draft to Communicate, Not to Sound Impressive** — antidote to verbose hedge-laden academic prose; one hedge per claim, ceilings not floors
- Sub-agent mapping table updated

Tests (30 new, 357 total; 0 failing):
- Template: all 5 templates structurally valid (required fields, sorted ordinals, positive word_limit)
- Init: creates manifest/outline.json/source.md; state=drafted; all sections start as placeholder; source.md has correct headings + YAML frontmatter
- Idempotency: same title+venue → same ID; different venue → different ID; re-init without --force errors
- Section: updates source.md body; updates outline.json stats (word_count, status, cite_keys); revised status flag; unknown section/manuscript errors cleanly
- Status: prints table with correct columns; updates after section draft; errors on unknown manuscript
- CLI edges: missing --title / --venue / --manuscript-id; unknown venue rejected; --help lists all subcommands

### v0.23 — close the four CRACKs from v0.20 + v0.21

The two harnesses pinned a total of four CRACKs as `current-broken-behavior` tests. v0.23 fixes all four:

- **pdf-extract state guard**: refuses extraction on `discovered`/`triaged` (too early — paper-acquire hasn't run), or `read`/`cited` without `--force` (too late — already past extraction). `acquired` is the green-light state; `extracted` is a friendly no-op via the existing `has_full_text()` check.
- **pdf-extract PDF integrity check**: same magic-byte + min-size pre-check `paper-acquire/record.py` applies on the way in. Defence-in-depth — catches manually-dropped non-PDFs and post-acquire file replacements before docling sees them.
- **pdf-extract artifact_lock**: matches the paper-acquire/paper-triage pattern. Concurrent extracts on the same paper now serialise rather than racing on `content.md` / `figures/` / `extraction.log`.
- **manuscript-ingest pandoc-style `@key prose` bib parser**: now recognised as a fourth bib style alongside `[N]`, bullets, and `@article{key, ...}` BibTeX blocks. Explicit key is lifted from the `@key` prefix and stored as `entry_key` directly, bypassing the heuristic inferrer.

Tests: 4 CRACK-pinning tests replaced with fix-verification tests; 3 new behavioral tests (refuse-on-discovered, reject-html-at-extract-time, reject-too-small-at-extract-time); 1 new positive test for pandoc-bib parsing. Suite 324 → 327.

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
| [Consensus official skills](../docs/CONSENSUS-SKILLS-ANALYSIS.md) (April 2026) | Audit Log section as first-class output, three-counter discipline (queries/received/cited), plan-tier detection, repeat-hit + cites-per-year mechanical-foundation signals, source-discipline labeling, framework-driven sub-area decomposition (PICO/SPIDER/Decomposition), era-gated search planning |

## Design principles (derived)

Applied to skills, sub-agents, and code. See `RESEARCHER.md` for the researcher-facing version and `CLAUDE.md` for the engineer-facing version.

1. **Principle-as-antidote** — every rule in `RESEARCHER.md` directly counters a known failure mode
2. **Declarative goals** — sub-agent prompts describe *what success looks like*, not procedural steps, wherever the task permits self-checking loops
3. **"The test"** — every sub-agent exits with an explicit verification clause
4. **Minimal-scope edits** — each sub-agent's `tools:` frontmatter restricts which files/MCPs it can touch
5. **Fixed budgets + single metric** — for anything experimental, one scalar comparable across iterations
6. **Lego composition** — skills communicate through artifacts on disk, never direct invocation
7. **Composable principle files** — project-level `CLAUDE.md` merges with `RESEARCHER.md` merges with user-level principles

## Shipped: v0.51 → v0.117

### v0.117 — OTLP hex ID compliance ✅ (2026-04-28)

v0.116 emitted coscientist's prefixed string IDs (`trace-abc123`,
`span-def456`) directly. OTLP spec requires 32-char hex trace IDs
+ 16-char hex span IDs — Jaeger/Honeycomb/Tempo would reject.
Fixed.

`_to_hex_id(s, *, length)` strips `trace-`/`span-` prefix, filters
to hex, pads with leading zeros if short, truncates from start if
long. Empty/None → all-zero hex (OTLP "no parent" form).

Round-trip preserved: raw coscientist IDs added as
`coscientist.trace_id` (resource attr) and `coscientist.span_id`
(per-span attr). External tool can ingest via OTLP and still
correlate back.

Parent span IDs handled identically — present become 16-char hex,
absent become empty string.

10 new tests (6 _to_hex_id edge cases + 4 OTLP compliance:
trace 32-hex, span 16-hex, parent 16-hex with non-zero,
round-trip raw IDs in attrs). 1888 total passing.

### v0.116 — OTLP-compatible trace export ✅ (2026-04-28)

`lib.trace_render.render_otlp(payload)` emits OpenTelemetry OTLP
JSON shape so external tools (Jaeger, Honeycomb, Tempo) can
ingest a coscientist run trace via standard collectors.

Maps coscientist span kinds to OTLP `kind`:
- `tool-call` → CLIENT (3)
- everything else → INTERNAL (1)

OTLP status: `error` → 2 (ERROR + error_msg), `ok` → 1 (OK),
others → 0 (UNSET).

Resource attributes: `service.name=coscientist`,
`coscientist.run_id=<rid>`. Per-span attributes preserve
`coscientist.kind` + flattened attrs_json keys (capped at 512
chars). Events preserved with payload (capped at 1024).

`_iso_to_nano(iso)` helper converts ISO 8601 to nanoseconds
since epoch. Bad input returns 0.

CLI: `uv run python -m lib.trace_render --db <path>
--trace-id <rid> --format otlp`. New format choice alongside
mermaid / md / json.

9 new tests (iso_to_nano + 4 render_otlp scenarios + CLI).
1878 total passing.

### v0.115 — CLAUDE.md observability docs ✅ (2026-04-28)

Documents v0.89–v0.114 instrumentation stack in `CLAUDE.md` for
new contributors. Was zero coverage before.

**Recent landings** section expanded — includes v0.89–v0.114
landings with one-line summaries grouped by sub-range
(v0.89–v0.92 foundation, v0.93–v0.96 hookup, v0.97–v0.100 smoke
infra, v0.101–v0.105 schemas + rubrics, v0.106–v0.110 health,
v0.111–v0.114 polish + bug fix).

New "## Observability stack" section between graph layer and
skill rules:
- 4 tables (traces / spans / span_events / agent_quality) +
  span kinds enumeration
- "How to instrument" — 4 entry points (Python context manager,
  MCP env-var helper, gate helper, auto-quality hook)
- "How to inspect" — table mapping operator question to CLI
- Health alerts subsection — exit codes, config file
- 4 invariants (best-effort, pure stdlib, WAL mode,
  schema-as-single-source)
- Runbook reference

9 regression tests pin: section exists, lists 3 tables, lists
7 span kinds, mentions key modules, mentions env vars, lists
invariants, references runbook, recent-landings updated.

1869 total passing.

### v0.114 — health threshold config file ✅ (2026-04-28)

Hardcoded `DEFAULT_THRESHOLDS` (v0.113) reasonable but research
projects vary. Add JSON config at
`~/.cache/coscientist/health_thresholds.json` for user override.

`lib.health.load_thresholds(*, overrides=None, config_path=None)`
resolves with precedence:
DEFAULT_THRESHOLDS < config_file < overrides.

Bad config (missing/invalid JSON/wrong types/unknown keys) silent
fallback to defaults — health is observability, never breaks.
Int auto-coerced to float where field expects float.

`evaluate_alerts(report, *, thresholds=None, config_path=None)`
plumbs through to `load_thresholds`.

CLI: `--show-thresholds` prints resolved values + config path
as JSON, exits 0. Useful for debugging "why didn't my alert fire".

9 new tests (defaults / config / overrides / unknown / invalid
JSON / wrong-type rejection / int→float coercion / integration
+ CLI). 1860 total passing.

### v0.113 — alert thresholds in health dump ✅ (2026-04-28)

Health dump (v0.106) printed raw counts. v0.113 adds tunable
thresholds + alert evaluation. Actionable signal not numbers.

`lib.health.DEFAULT_THRESHOLDS`:
- `max_stale_spans` = 0
- `max_failed_spans` = 5
- `max_tool_error_rate` = 0.20 (20%)
- `min_quality_score` = 0.50
- `max_active_runs` = 10

`evaluate_alerts(report, thresholds=None)` returns list of
`{severity, code, message, value, threshold}`. Severity: `warn`
or `crit`.

Render shows "Alerts" banner first when present (🚨 crit, ⚠️ warn).

CLI exit codes:
- 0: no alerts
- 1: only warn alerts
- 2: at least one crit alert

`--no-alerts` flag suppresses evaluation (raw report).

CI/cron-friendly: `lib.health` exits non-zero when something
needs attention.

9 new tests. 1851 total passing.

### v0.112 — tool-call error spans actually error ✅ (2026-04-28)

**Bug fix.** v0.93c `maybe_emit_tool_call(error=...)` accepted
the error param but only logged it as event — span stayed
`status='ok'`. Tool-latency aggregator (v0.100) counted error
spans as successes. Gate-summary (v0.109) similar issue.

`maybe_emit_tool_call` now raises `_ToolCallError(error)` inside
the context manager when `error` is given. `_SpanHandle._close`
catches the exception, sets `status='error'` + `error_msg=<error>`
+ `error_kind='_ToolCallError'`. Caller never sees the exception
(swallowed in the same try/except).

All 3 MCP servers (retraction-mcp, manuscript-mcp,
graph-query-mcp) `_trace_emit` helpers extended with `error=`
param + every error-path call updated to forward the message.
Plugin sources resynced + checksums regenerated.

3 new tests (success path stays ok, error sets
status+msg+kind, n_errors counted in tool-latency aggregator).
1842 total passing.

### v0.111 — prune empty run DBs ✅ (2026-04-28)

`lib.trace_status.prune_empty_run_dbs(*, dry_run=False)`
companion to v0.110. Walks every `run-*.db`; deletes files
where both `traces` AND `phases` tables have zero rows.

Pairs with v0.110: prune old traces first, then run this to
remove the now-empty DB files. Cleans up sidecar files (-wal, -shm)
too.

CLI: `uv run python -m lib.trace_status --prune-empty-dbs
[--dry-run] [--format md|json]`. Returns `{n_deleted, deleted,
skipped, dry_run}`.

DBs with any phase OR trace state are skipped — never touches
live runs.

8 new tests (no-DBs, empty deleted, traces skip, phases skip,
dry-run preservation, mixed DBs, CLI dry-run, CLI actual).
1839 total passing.

### v0.110 — trace pruning ✅ (2026-04-28)

`lib.trace_status.prune_old_traces(db, *, max_age_days=30,
dry_run=False)` deletes traces with `status != 'running'` and
`completed_at < cutoff`. Cascade: span_events → spans → traces.

**Active runs never pruned** — `status='running'` exempt
regardless of age.

CLI: `uv run python -m lib.trace_status --prune
[--prune-days 30] [--dry-run] [--run-id <rid>] [--format md|json]`.
Without `--run-id` walks every run DB.

`--dry-run` returns counts without mutating; useful for "how much
would I free" check.

Returns: `{n_traces, n_spans, n_events, dry_run, db_path}` per
DB processed.

6 new tests (no-db, dry-run no-delete, actual delete with
recent-trace preservation, active-trace exemption, CLI dry-run +
CLI actual-prune). 1831 total passing.

### v0.109 — gate-decision summary in health ✅ (2026-04-28)

v0.93b emits gate-kind spans (publishability, novelty, future
gates) with verdict in attrs. Health (v0.106) ignored them. Fixed.

`lib.trace_status.gate_summary(db, *, trace_id=None)` aggregates
gate spans by name: n_total, n_ok, n_rejected, recent_errors
(top 3 error_msgs). `gate_summary_across_runs()` cross-run.

`lib.health.collect()` now returns `gates` key. Md renderer adds
"Gate decisions" section sorted by n_rejected descending; surfaces
recent error messages inline (top 2 per gate).

Operator can answer "did publishability accept anything across
runs" + "what's the most common rejection reason" in one
command.

6 new tests. 1825 total passing.

### v0.108 — harvest summary in health dump ✅ (2026-04-28)

v0.93b started writing `harvest_write` events on every harvest.py
call (raw_count/deduped_count/kept_count/queries_sent). Health
dump (v0.106) ignored them. Fixed.

`lib.trace_status.harvest_summary(db, *, trace_id=None)` extracts
all harvest spans + events, aggregates by persona. Returns n,
totals (raw/deduped/kept/queries), by-persona breakdown.

`harvest_summary_across_runs(roots=None)` companion for cross-run
view.

`lib.health.collect()` now includes `harvests` key. Md renderer
adds "Harvest activity (per persona)" section sorted by kept-count
descending.

Operator can now answer "did Phase 0 actually retrieve anything"
in one command.

6 new tests (per-DB aggregation + trace filter + cross-run +
health md integration). 1819 total passing.

### v0.107 — health skill + runbook integration ✅ (2026-04-28)

`/health` slash command. New skill at
`.claude/skills/health/SKILL.md` + wrapper script
`scripts/health.py` that forwards to `lib.health` (v0.106).

Discoverable through skill index: `SKILLS.md` regenerated to 65
total skills.

`docs/SMOKE-TEST-RUNBOOK.md` (v0.101) updated — Step 2 now
recommends `lib.health` as first-stop diagnostics, falls back to
`lib.trace_status` for trace-only views.

6 new tests pin: skill exists, frontmatter valid, mentions
lib.health + --max-age, wrapper script exists + runs end-to-end,
runbook references the module. 1813 total passing.

User-facing instrumentation surface complete.

### v0.106 — health dump ✅ (2026-04-28)

`lib/health.py` — single-shot diagnostics across the whole
coscientist stack. One command, one report.

`collect(*, max_age_minutes=30)` walks every `run-*.db` and
returns: n_runs, active (running traces), stale (running spans
past threshold, via v0.97), tool_latency (across runs, via
v0.100), quality (per-agent leaderboard, via v0.96),
failed_spans_total.

CLI: `uv run python -m lib.health [--format md|json] [--max-age 30]`.
md output includes top-10 slowest tools, lowest-mean agents,
active runs, stale spans.

Combines v0.95 + v0.96 + v0.97 + v0.100 into one operator view.

7 new tests (collect logic + md renderer + CLI). 1807 total
passing.

### v0.105 — dict-aware OG rubrics ✅ (2026-04-28)

The 5 v0.92 rubrics (scout/surveyor/architect/synthesist/weaver)
expected list-top input. v0.103 corrected schemas to dict-top
(matches actual persona output specs). Mismatch meant rubrics
ran against wrong shape unless `--quality-artifact` passed.

`_items_from(payload, list_field)` helper accepts list-top OR
dict-top (extracts named list field). All 5 OG rubrics use it
now. Bumped to version 0.2.

Rubric criteria realigned to actual persona specs:
- **architect**: falsifiers + method_sketch (was method+falsifier+observable)
- **weaver**: dict shape with sharpened_question + consensus +
  tensions (was text-loader with cite density). Loader switched
  json.

Backward-compat: list-top inputs still score correctly.

10 new tests for `_items_from` + dict-top scoring per persona +
backward-compat. v0.92 tests updated for new architect/weaver
shapes. 1800 total passing.

### v0.104 — rubrics for v0.103 personas ✅ (2026-04-28)

Five new rubrics in `lib.agent_quality.RUBRICS`: cartographer,
chronicler, inquisitor, visionary, steward. Total: 10 personas
with auto-quality scoring.

These score the record-phase output_json directly (dict-top with
phase + items[]) — no separate `--quality-artifact` needed.

Rubric criteria pulled from each persona's exit-test in
`.claude/agents/<name>.md`:

- **cartographer** (3 criteria): non-empty summary, ≥3 seminals,
  every seminal has `why_seminal`.
- **chronicler** (3): non-empty summary, ≥3 timeline events,
  every entry has `event`.
- **inquisitor** (4): ≥1 evaluation, every eval has steelman +
  killer_experiment + survival score.
- **visionary** (3): ≥2 directions, every direction has
  first_step + why_underexplored.
- **steward** (4): eval_passed=true, hedge_word_hits=0,
  ≥5 claims_cited, ≥10 papers_cited.

11 new tests covering registration + per-rubric scoring (high
and low) + integration via record-phase. 1790 total passing.

### v0.103 — full persona schemas + record-phase split ✅ (2026-04-28)

**Schema corrections** — v0.102 shipped scout/surveyor/architect/
synthesist as list-top; reading actual persona output specs in
`.claude/agents/*.md` revealed they all emit dict at top with
`phase` + summary + items[]. Same with weaver (consensus/tensions,
not agreements/disagreements). Fixed.

**Five new persona schemas**: cartographer, chronicler, inquisitor,
visionary, steward. All dict-top with persona-specific required
fields. Total: 10 personas registered.

**record-phase split (v0.94 → v0.103)**: separate `--output-json`
(record-phase contract — schema gate target) from `--quality-artifact`
(rubric target — richer persona-side artifact like
/tmp/scout-shortlist.json). v0.94 fallback removed: rubric
runs only when `--quality-artifact` passed. Schema gate runs
on `--output-json` independently.

**CLI**: `uv run python -m lib.persona_schema list` prints all
registered schemas as JSON. `validate` subcommand for explicit
shape check (backward-compat: bare `--agent` + `--artifact-path`
still works).

8 new tests (full schema coverage + list CLI + record-phase split).
v0.93 + v0.102 tests updated to match corrected shapes. 1779
total passing.

### v0.102 — persona output schema validator ✅ (2026-04-28)

`lib/persona_schema.py` — strict shape gate per persona. Auto-rubric
(v0.92) checks semantic content but not structure; this fills the
gap. Pure stdlib, no jsonschema dep.

`SCHEMAS` dict per persona (scout, surveyor, architect,
synthesist, weaver) declares top_kind (list|dict),
item_required_fields, dict_required_fields, min_items.

`validate(agent_name, artifact_path) -> ValidationResult` returns
ok/payload/error. Unknown agents pass permissively (schema is
opt-in).

CLI: `uv run python -m lib.persona_schema --agent scout
--artifact-path X.json`. Exits 0 if valid, 1 if not.

Wired into v0.94 auto-quality hook: invalid shape skips rubric
(would score garbage) and emits a `gate`-kind span named
`schema-<phase>` with a `schema_error` event. Visible in
trace-status + trace-render output.

13 new tests: scout list shape (4), weaver dict shape (3),
unknown-agent passthrough, file errors (2), CLI exit codes (2),
integration (invalid shape → no quality row + schema-gate span).
1772 total passing.

### v0.101 — smoke-test runbook ✅ (2026-04-28)

`docs/SMOKE-TEST-RUNBOOK.md` consolidates the v0.93–v0.100
instrumentation stack into one walkthrough. 8-step procedure:
start run → watch traces → render timeline → find stale spans
→ tool-call latency → quality scores → LLM-judge → resume.

Includes "common failure patterns" troubleshooting table and
"what's NOT instrumented yet" honest-about-gaps section.

4 regression tests pin runbook existence + required sections +
key module references + CLI flag mentions. 1759 total passing.

This is the operator-facing companion to v0.93+ instrumentation.
First live `/deep-research` smoke run will follow this runbook.

### v0.100 — tool-call latency aggregator ✅ (2026-04-28)

First three-digit minor in the 0.x line. v0.93c started recording
tool-call span durations via `start_span` context manager; this
release surfaces them.

`lib.trace_status.tool_call_latency(db, *, trace_id=None)`
aggregates by tool name: n, n_errors, mean_ms, p50_ms, p95_ms,
max_ms. Companion `tool_call_latency_across_runs(roots=None)`
for cross-run perf views.

CLI: `uv run python -m lib.trace_status --tool-latency
[--run-id <rid>] [--format md|json]`. md output sorts tools
slowest-first by mean.

Useful smoke-test signal: which MCPs are hot, which fail often,
where the latency budget actually goes.

6 new tests (no-db, by-name aggregation, trace filter, empty
cross-run, multi-db cross-run, CLI). 1755 total passing.

### v0.99 — version parser audit (pre-v0.100 defensive) ✅ (2026-04-28)

User opted to keep 0.x line going past v0.99 → v0.100 → v0.101...
instead of bumping to v1.0 prematurely. v1.0 reserved for the
true stable cut.

Audit found `lib/changelog.py` already tuple-based: `_version_key`
splits on dots, parses each segment as int, so v0.100 → (0, 100)
sorts correctly after v0.99 → (0, 99). ROADMAP heading regex
`v\d+\.\d+(?:\.\d+)?(?:[a-z])?` accepts three-digit minors.

No code change needed — added regression test pinning the
v0.10 < v0.98a < v0.99 < v0.100 ordering. Caught zero bugs but
prevents future contributor from "fixing" the parser into a
string sort.

`lib/migrations.py` uses int versions (1..12), unaffected.
No other version-string parsers found in repo.

1 new test. 1749 total passing.

### v0.98 — stale-span auto-close action ✅ (2026-04-28)

`lib.trace_status.mark_stale_error(db, *, max_age_minutes=30,
reason)` mutates stale running spans to `status='error'` with
`error_kind='stale'`, `error_msg=<reason>`, `ended_at=now`.

CLI: `uv run python -m lib.trace_status --stale-only
--mark-error [--reason "..."]`. Pairs with v0.97 detector —
v0.97 reports, v0.98 acts. Caller decides which to use.

4 new tests (no-stale noop, marks-error-with-reason,
completed-span-not-touched, CLI). 1748 total passing.

### v0.97 — stale-span detector ✅ (2026-04-28)

`lib.trace_status.find_stale_spans(db, *, max_age_minutes=30)`
returns spans still `status='running'` past the threshold —
phases / sub-agents that crashed without closing their span.

CLI: `uv run python -m lib.trace_status --stale-only
[--run-id <rid>] [--max-age 30] [--format md|json]`. Without
`--run-id` scans every run DB.

Reports kind/name/age but does not auto-mutate state — caller
decides whether to mark error or re-resume. Smoke-test
companion to v0.95 trace-status quick view.

5 new tests. 1744 total passing.

### v0.96 — cross-run agent quality leaderboard ✅ (2026-04-28)

`lib.agent_quality.leaderboard(roots=None)` walks every
`run-*.db` under `~/.cache/coscientist/runs/` and aggregates
`agent_quality` rows. Same shape as `summary()`, plus
per-agent `n_runs` (distinct run_ids) and global `n_dbs`.

CLI: `uv run python -m lib.agent_quality leaderboard
[--root <path>]`. Pre-v12 DBs (no `agent_quality` table)
gracefully skipped.

Pairs with v0.94 auto-quality hook: scores written
automatically on phase complete; leaderboard surfaces
"scout consistently 0.4 — investigate" patterns across runs.

4 new tests. 1739 total passing.

### v0.95 — trace-status quick view ✅ (2026-04-28)

`lib/trace_status.py` — compact "is run X alive, what phase, any
failed spans" without rendering full markdown timeline. Faster +
more scannable than `trace_render --format md` during live
smoke tests.

**API**: `summarize_trace(db_path, trace_id) -> dict`,
`summarize_runs(roots=None) -> list[dict]`. Counts spans by kind
+ status, surfaces latest phase + latest error.

**CLI**: `uv run python -m lib.trace_status [--run-id <rid>]
[--format md|json]`. No `--run-id` scans every `run-*.db` under
`~/.cache/coscientist/runs/`.

8 new tests covering missing-db / missing-trace / span counting
/ multi-run scan / md renderer / CLI. 1735 total passing.

### v0.94 — auto-quality hook on phase completion ✅ (2026-04-28)

`db.py record-phase --complete --output-json <path>` now triggers
`_maybe_auto_score(run_id, phase, output_json)`. When phase name
matches a `lib.agent_quality.RUBRICS` key (scout, surveyor,
architect, synthesist, weaver), the auto-rubric runs and persists
to `agent_quality` keyed by run_id. Non-rubric personas are
silent noops. All errors swallowed — quality scoring is pure
observability.

2 new tests: known-persona writes a row with high score on a
30-paper artifact; unknown-persona phase writes nothing. Total
suite 1727 passing.

This closes the v0.92 deferred item: "live data flowing into
agent_quality without operator action".

### v0.93 — instrumentation hookup ✅ (2026-04-28)

Wires the v0.89–v0.92 traceability/quality framework into live hot
paths. Framework existed but no live data flowed until now.

**v0.93a — phase span wrapper**: `db.py record-phase` now calls
`_emit_phase_span(run_id, phase, *, start, complete, error,
output_json)`. Each phase transition produces a `phase`-kind span;
errors capture `error_kind` + `error_msg`.

**v0.93b — harvest + gate spans**: `harvest.py` emits a `harvest`
span event (raw/deduped/kept counts + queries) after every write.
`publishability-check/gate.py` calls `lib.gate_trace.emit_gate_span`
on ok / warning / rejection paths. Helper module `lib/gate_trace.py`
shared across gates.

**v0.93c — MCP tool-call spans**: env-var trace context propagation
(`COSCIENTIST_TRACE_DB`, `COSCIENTIST_TRACE_ID`) so MCP servers
opt-in without API changes. `lib.trace.maybe_emit_tool_call` is a
best-effort emitter; `retraction-mcp.lookup_doi`,
`manuscript-mcp.parse_manuscript`, and
`graph-query-mcp.shortest_path` instrumented (success + error
paths). Plugin sources resynced.

**v0.93d — score-quality CLI**: `db.py score-quality --run-id X
--agent NAME --artifact-path P` runs the auto-rubric and persists
to `agent_quality`. Direct entry point for orchestrator hooks.

8 new tests covering env trace context, maybe_emit_tool_call
(noop + writes), gate trace (noop + ok + rejected), and end-to-end
phase span emission via CLI.

Plugin checksums regenerated. All instrumentation is best-effort:
parent flow never breaks if tracing fails.

## Shipped: v0.51 → v0.92

All items in this section are landed. See per-version notes.

### v0.92 — agent quality scoring ✅ (2026-04-28)

Three judging modes, one persistence target. Pairs with v0.89-v0.91
traceability for full visibility into both **what happened** and
**how well it happened**.

**Migration v12**: new `agent_quality` table. Same agent can be
scored by multiple judges (auto-rubric + llm-judge + future ranker);
all rows kept.

**`lib/agent_quality.py`** — three modes:

1. **auto-rubric** (`score_auto`): pure-stdlib structural checks.
   Rubrics for scout, surveyor, architect, synthesist, weaver.
   Reusable helpers: `count_at_least`, `every_item_has_fields`,
   `fraction_with_field`, `unique_kind_count`.
2. **llm-judge** (`emit_judge_prompt` + `persist_judge_result`):
   two-step protocol. Orchestrator dispatches the new
   `quality-judge` sub-agent (runs inside Claude Code's Task tool;
   no extra API plumbing) with a structured prompt; sub-agent
   returns JSON; orchestrator persists.
3. **ranker** (deferred to v0.93): pairwise tournament over agent
   outputs.

**`quality-judge` sub-agent** (`.claude/agents/quality-judge.md`):
reads artifact + rubric, returns JSON `{scores, reasoning}`.
Anti-pattern guidance against inflation/cherry-picking/hedging.
Calibration heuristics for typical score ranges.

**Trace renderer integration**: `render(payload, "md",
db_path=...)` appends "Agent quality" section reading from
`agent_quality` for the trace's run_id.

**CLI**: `uv run python -m lib.agent_quality summary --db <path>
[--run-id <rid>]`.

17 new tests covering migration v12, check helpers, score_auto
(high/low/unknown/partial/persist), judge protocol (prompt fields,
unknown-agent error, persist row, missing-scores graceful),
summary aggregation, renderer integration.

Plugin lib + checksums resynced. `tests/test_agents.EXPECTED_AGENTS`
extended.

Suite: 1700 → 1717 passing (+17).

### v0.91 — trace renderer CLI ✅ (2026-04-28)

Layer C of the traceability plan.

- `lib/trace_render.py::render_mermaid(payload)` — `graph TD`
  hierarchical span tree. Failed spans red (classDef), slow spans
  (>5s) yellow.
- `lib/trace_render.py::render_markdown(payload)` — chronological
  timeline with per-span event log + status emoji.
- `lib/trace_render.py::render_json(payload)` — full read-back.
- CLI: `uv run python -m lib.trace_render --db <path>
  --trace-id <tid> --format mermaid|md|json`.

8 tests: mermaid (empty/root/failed-painted), markdown (empty/
span-order/event-payload), JSON round-trip, invalid format rejected.

### v0.90 — error context capture ✅ (2026-04-28)

Layer B of the traceability plan.

- `lib/trace.py::capture_error_context(db, span, exc, *,
  stdout_tail, stderr_tail, snapshot_tables, max_bytes)` —
  appends `error_context` event with traceback, optional output
  tails, DB row-count snapshot. Bounded payload (4KB default).
- `start_span(..., capture_on_error=True, snapshot_tables=[...])`
  auto-fires capture before re-raise.
- Capture failure never masks original exception.

5 tests covering capture, no-flag = no-capture, snapshot_tables
(incl. missing tables → -1), bounding, capture failure doesn't
mask.

### v0.89 — execution traces (OpenTelemetry-style spans) ✅ (2026-04-28)

Layer A of the traceability plan. Lays the foundation for live
deep-research debugging.

**Migration v11** — three new tables:
- `traces` (trace_id, run_id, started_at, completed_at, status)
- `spans` (span_id, trace_id, parent_span_id, kind, name, started_at,
  ended_at, duration_ms, status, error_kind, error_msg, attrs_json)
- `span_events` (event_id, span_id, name, payload_json, at)

Plus 4 indexes. Mirrored in `lib/sqlite_schema.sql`.

**`lib/trace.py`** — pure-stdlib helper API:
- `init_trace(db_path, trace_id, run_id)` — idempotent.
- `start_span(db, trace_id, kind, name, parent_span_id=, attrs=)` —
  context manager. Auto-records started_at/ended_at/duration_ms.
  On exception: status='error' + error_kind + error_msg captured;
  exception re-raised after persistence.
- Span handle: `.event(name, payload)`, `.set_attrs(dict)`.
- `end_trace(db, trace_id, status)` — ok|error.
- `get_trace(db, trace_id)` — full read-back: trace + spans + events
  for renderer (v0.91).

Span `kind` enum: phase | sub-agent | tool-call | gate | persist |
harvest | other.

12 new tests in `tests/test_v0_89_traces.py`:
- 1 migration v11 (3 tables created)
- 3 trace lifecycle (init/end, idempotent, invalid-status rejected)
- 6 span context manager (ok records duration, error persists
  traceback, invalid-kind rejected, nested-parent, event payload,
  attrs persisted)
- 2 get_trace round-trip (full + missing returns None)

Suite: 1675 → 1687 passing (+12).

**Next**:
- v0.90 — error context capture (traceback persistence,
  stdout/stderr tail, DB state at failure)
- v0.91 — trace renderer CLI (mermaid + markdown + JSON)
- Then instrument `db.py` phases + MCP tool calls

### v0.88 — risk evaluation: WAL sweep + audit-self-log ✅ (2026-04-28)

Three risks identified post-v0.85; evaluated all three.

**Risk #1 — `prune_writes_all_dbs` opens plain sqlite3.connect**:
**REAL**. Could deadlock on parallel writers on legacy non-WAL
DBs. Fix: use `lib.cache.connect_wal`. Idempotent on already-WAL
DBs. Mirror of v0.66 retrofit pattern.

**Risk #2 — `db_check` FK enforcement is forward-only**:
**FALSE ALARM**. Re-read showed `db_check` calls
`PRAGMA foreign_key_check`, which is the retroactive validator.
The `PRAGMA foreign_keys=ON` line is just precautionary; the
violations check runs regardless. Added a regression test
(`test_fk_violation_detected_in_existing_data`) to lock the
behavior in.

**Risk #3 — `purge_archives` doesn't audit deletions**: **REAL**.
Paradoxical for a tool that exists to manage audit logs. Fix:
append a JSON-line entry to live audit.log on every successful
purge:
```json
{"kind":"audit-purge","at":"...","older_than_days":30,
 "n_deleted":3,"bytes_freed":12345,"paths":[...]}
```
Dry-run paths don't log (verified by test).

4 new tests in `tests/test_v0_88_risk_fixes.py`:
- 1 sweep-uses-WAL (journal_mode preserved after cross-DB sweep)
- 1 FK-retroactive-check (db_check finds existing FK violation)
- 2 purge-audit-trail (confirm logs entry; dry-run does not)

Suite: 1671 → 1675 passing (+4).

### v0.87 — backup/restore scripts + cleanups ✅ (2026-04-28)

Operational cleanups.

**Backup/restore scripts**:
- `scripts/backup_cache.sh` — tarball `~/.cache/coscientist/` (or
  `$COSCIENTIST_CACHE_DIR`) into a timestamped `.tar.gz`. Excludes
  `__pycache__`, `*.pyc`, `*.tmp`, WAL sidecar files. Bash strict
  mode.
- `scripts/restore_cache.sh` — reverse. Refuses to overwrite an
  existing cache without `--force`. Suggests running
  `lib.db_check` + `lib.install_check` post-restore.

**Cleanup audits**: confirmed no dead code (`deprecated` mentions
are legit feature naming in `concept_velocity.py`); confirmed
`tests/_tmp_*.json` files are gitignored and never tracked.

8 new tests in `tests/test_v0_87_cleanups.py`:
- 4 backup-restore (presence, executable bit, full round-trip,
  refuse-overwrite, strict mode)
- 2 scripts-dir (install_all present, all .sh executable)
- 1 tmp-files (gitignored, not tracked)

Suite: 1663 → 1671 passing (+8).

### v0.86 — docs ✅ (2026-04-28)

Four hand-curated docs added.

- **`docs/architecture.md`** — system layout: two-tier mental
  model (orchestration / artifacts), artifact contract + state
  machines, SQLite scopes, migration framework, 8-phase sub-agent
  organization, plugin distribution, test discipline.
- **`docs/research-loop.md`** — narrative walkthrough of the
  10-agent Expedition pipeline. Describes each persona's job,
  break points, parallel dispatch, why this works, where it
  strains.
- **`CODE_OF_CONDUCT.md`** — Contributor Covenant 2.1 adapted.
- **`SECURITY.md`** — vulnerability reporting channel, scope
  (in/out), hardening posture (CHECKSUMS, sandbox, audit logs,
  WAL, FK check), disclosure timeline.
- **`README.md`** — new "Documentation" section linking all 12
  top-level docs.

10 new tests in `tests/test_v0_86_docs.py`:
- 2 architecture (presence + core sections)
- 3 research-loop (presence + pipeline phases + three modes)
- 2 code-of-conduct (presence + email)
- 3 security (presence + reporting channel + scope/hardening)

Suite: 1653 → 1663 passing (+10).

### v0.85 — plugin uninstall cleanup + checksums + PyPI publish gate ✅ (2026-04-28)

Plugin polish triple.

**Plugin uninstall cleanup** (`lib/plugin_cleanup.py`): Claude Code
plugin spec doesn't define a formal uninstall hook (as of v2.0.x).
This module fills the gap with manual cleanup per plugin:
`retraction-mcp` drops `retraction_flags` rows where
`source='retraction-mcp'`. Other 3 plugins are no-op (no
persistent state). Dry-run by default; `--confirm` for actual
deletes.

**Plugin file checksums** (`lib/plugin_checksums.py`): SHA-256
manifest at `<plugin>/CHECKSUMS.txt` per plugin. Compatible with
standard `sha256sum -c`. CLI: `generate` + `verify`. All 4
plugins now have CHECKSUMS.txt files.

**PyPI publish gate**: `release.yml` publish step now gated on
`vars.PYPI_PUBLISH_ENABLED == 'true'` + trusted-publisher
configuration. Without that flag, the workflow only validates
the build. To enable:
```bash
gh variable set PYPI_PUBLISH_ENABLED --body 'true'
```

9 new tests in `tests/test_v0_85_plugin_polish.py`:
- 6 cleanup (unknown plugin, 3 no-op plugins, dry-run, confirm)
- 3 checksums (every plugin has manifest, verify passes,
  excludes `__pycache__` / `.pyc`)
- Updated `test_v0_83_release.py::test_publish_step_gated` to
  check for the new `PYPI_PUBLISH_ENABLED` flag.

Suite: 1644 → 1653 passing (+9).

### v0.84 — CONTRIBUTING.md + db_check + manuscript-mcp .docx fixture ✅ (2026-04-28)

Three closures.

**CONTRIBUTING.md**: Walks through how to add a new skill / agent /
custom MCP / schema migration. Documents 9 architecture invariants
each enforced by a specific test class. Pre-merge checklist + the
auto-generated docs that must stay in sync.

**`lib/db_check.py`**: Walks every coscientist DB
(`runs/*.db` + `projects/*/project.db`), reports schema-version
drift, FK violations, orphan graph_edges, missing tables. Read-only.
Run via `uv run python -m lib.db_check` for a structured JSON
health report.

**manuscript-mcp .docx fixture test**: `tests/test_v0_84_misc.py`
includes a real round-trip: pandoc converts markdown → .docx →
parse_manuscript → assert sections + word count surface. Skipped
when pandoc isn't on PATH; never crashes.

8 new tests:
- 2 CONTRIBUTING (presence + section coverage)
- 4 db_check (returns dict, healthy run/project DBs, detects
  migration drift)
- 2 manuscript-mcp docx (real round-trip + graceful no-pandoc)

Suite: 1636 → 1644 passing (+8).

### v0.83 — PyPI release workflow + install_all.sh ✅ (2026-04-28)

Two operational wins.

**PyPI release workflow** (`.github/workflows/release.yml`): Builds
sdist + wheel for each MCP plugin on tag push (`retraction-mcp-vX`,
`manuscript-mcp-vX`, `graph-query-mcp-vX`) or manual dispatch.
Publishes are gated (commented out) — operator turns it on once
trusted-publishing is configured. Until then the build job alone
validates packaging.

**install_all.sh** (`scripts/install_all.sh`): One-shot bash
script that runs `claude plugin marketplace add` then installs
all 4 Coscientist plugins. Uses bash strict mode, errors clearly
if `claude` CLI is missing, runs `claude mcp list` for verification
at the end. User-executable.

9 new tests in `tests/test_v0_83_release.py`:
- 4 release-workflow (file present, all 3 tag patterns, uv build,
  publish step gated)
- 5 install-script (file present, executable bit set, all 4
  plugins listed, marketplace-add precedes install, uses
  `set -e` strict mode)

Suite: 1627 → 1636 passing (+9).

### v0.82 — audit retention + lib.graph WAL consistency ✅ (2026-04-28)

Latent risk closure. Two items.

**Audit-archive retention**: `lib/audit_retention.py` parses
rotation stamps (`<base>.YYYYMMDDTHHMMSSZ`) to compute age, lists
audit + sandbox archives older than N days. `purge_archives()` is
opt-in via `confirm=True` — mirrors audit-rotate's "refuses to
delete archives without explicit user intent" doctrine. Audit-rotate
gains a `purge-archives` subcommand.

**lib.graph WAL retrofit**: `lib/graph.py::_connect` now uses
`lib.cache.connect_wal`, matching `lib/project.py` post-v0.71. Both
write to the same project DB; consistency closes a latent risk
where parallel writers could race.

9 new tests in `tests/test_v0_82_audit_retention.py`:
- 2 archive-age (from-stamp, zero-for-today)
- 3 list-archives (empty, finds-audit, filter-by-age)
- 3 purge (dry-run, confirm-deletes, zero-days-rejected)
- 1 graph-WAL (graph.add_node leaves journal_mode=wal)

Suite: 1618 → 1627 passing (+9).

### v0.81 — CI runner + install-check + README troubleshooting ✅ (2026-04-28)

Marketplace + infra polish. Four items.

**GitHub Actions CI**: `.github/workflows/tests.yml` runs the full
suite on push/PR against `main`, matrix Python 3.11 + 3.12. Uses
`uv sync --extra dev --extra mcp` and runs `tests/run_all.py`.
Lint step (ruff) is `continue-on-error` for now — informational.

**install_check CLI**: `lib/install_check.py` walks
`marketplace.json`, validates every declared plugin (plugin.json
present + parses, name/version match, server.py compiles, .mcp.json
valid). Optional `--with-mcp-list` shells out to `claude mcp list`
for runtime verification. Run: `uv run python -m lib.install_check`.

**README troubleshooting section**: 6 common install failures
documented with cause + fix. Includes pointer to `install_check`
for self-diagnosis.

**`mcp` dep verify test**: Asserts `pyproject.toml` declares
`mcp>=1.0` in the `mcp` optional-dep group (so `uv sync --extra mcp`
keeps working).

8 new tests in `tests/test_v0_81_infra.py`:
- CI workflow file present + invokes run_all.py
- pyproject mcp extra declared
- run_checks returns structured dict
- all known plugins healthy (no drift between marketplace + plugin.json)
- ≥ 4 plugins
- MCP plugins have valid server.py + .mcp.json
- README has troubleshooting section + references install_check

Suite: 1610 → 1618 passing (+8).

### v0.80 — plugin pyprojects + main() entries + cross-DB sweep ✅ (2026-04-28)

Three medium-tier improvements bundled.

**Plugin pyproject.toml per MCP**: Each of the 3 MCP plugins now
has its own `pyproject.toml` with name, version, license,
dependencies (`mcp>=1.0`), and a `[project.scripts]` console-script
entry. Unblocks PyPI-style publishing path
(`uvx coscientist-retraction-mcp`, etc.).

**Server `main()` entries**: Each `mcp/<name>-mcp/server.py` exposes
a `def main()` so console scripts can target `server:main`. Plugin
copies resynced; `ServerMainEntryTests` enforces byte equality.

**`prune_writes_all_dbs` sweep helper**: New
`lib.db_notify.prune_writes_all_dbs(cache_root, keep_last_n=,
older_than=)` walks every coscientist DB (`runs/*.db` +
`projects/*/project.db`) and applies the same retention rules.
audit-query gains a `prune-writes-all` subcommand.

9 new tests in `tests/test_v0_80_medium.py`:
- 4 plugin-pyproject tests (presence, console script, mcp dep,
  version match)
- 2 server-main tests (every server has main, plugin↔source byte
  parity)
- 3 sweep tests (empty cache, run-DB sweep, keep-last-N global)

Suite: 1601 → 1610 passing (+9).

### v0.79 — tournament integration + lib.shortest_path + CHANGELOG.md ✅ (2026-04-28)

Quick-win bundle: 3 items.

**Tournament integration tests** (`tests/test_tournament_integration.py`):
6 end-to-end tests on the `tournament` skill — register → match →
leaderboard → child lineage. Validates Elo zero-sum property, draw
neutrality, match-count accumulation, parent_hyp_id wiring,
duplicate hyp_id rejection. Pre-existing `test_tournament.py`
covered per-script units; this fills the lifecycle gap.

**Promote shortest_path to `lib.graph`**: BFS shortest-path was
introduced in graph-query-mcp v0.74 (MCP-only). v0.79 lifts it
into `lib.graph.shortest_path(project_id, start, end, max_hops=4,
relation=None)` — same algorithm, callable from any Python code.
The MCP server now delegates: `_bfs_shortest_path` is a 3-line
wrapper. 6 new unit tests in `tests/test_graph_shortest_path.py`
mirror the MCP coverage (self-path, two-hop, no-path,
max_hops cutoff, relation filter, one-hop direct).

**Auto-generated CHANGELOG.md**: `lib/changelog.py` parses ROADMAP's
`### v*` headings out of the `## Shipped` section, sorts by version
(letters become sub-indices: `v0.78a` → `(0, 78, 1)`), emits a
single CHANGELOG.md newest-first. `tests/test_changelog.py` has 6
tests covering the parser + version-key sort + parity check
(CHANGELOG.md byte-matches generator output, drift detected by CI).

Suite: 1583 → 1601 passing (+18).

### v0.78 — feature loop closure: retraction wiring + version sync + mcp dep ✅ (2026-04-28)

Three small, low-risk closures bundled.

**v0.78a — retraction-watch ↔ retraction-mcp wiring**

Closes the loop opened by v0.72. `retraction-watch/scan.py` gained
a `--mcp-lookup` subcommand that drives the `retraction-mcp`
`lookup_doi` function directly (Python import, not JSON-RPC), then
shapes the result for `cmd_persist`. Pair with `--auto-persist`
to write to `retraction_flags` in one shot.

- New `_doi_for_canonical(cid)` reads `~/.cache/coscientist/papers/<cid>/manifest.json`
  for the DOI.
- Papers without a known DOI are reported in `skipped_no_doi`,
  not silently dropped.
- Per-paper errors isolated.
- 5 new tests (`tests/test_v0_78_retraction_wiring.py`): unit tests
  for `_doi_for_canonical` (3 paths) + CLI smoke tests (skip-no-doi,
  empty project).
- SKILL.md updated with the new subcommand row + workflow block.

**v0.78b — deep-research plugin version sync**

`coscientist-deep-research` plugin was at 0.50.2 while the parent
project shipped past v0.77. Bumped both `plugin/coscientist-deep-research/.claude-plugin/plugin.json`
and the matching marketplace entry to **0.78.0**. Test
`test_plugin_json_version_matches` already enforces parity, so
either both move or neither.

**v0.78c — pin `mcp` dep**

Added `mcp>=1.0` to the `mcp` optional-dep group in
`pyproject.toml`. Source-tree devs can now run `uv sync --extra mcp`
to install the dep up front rather than relying on
`uv run --with mcp ...` per call. Plugin users still get it
transitively via `.mcp.json` invocations.

Suite: 1578 → 1583 passing (+5).

### v0.77 — EXTERNAL_MCPS.md + docs-presence tests ✅ (2026-04-28)

User question: "do we need to register all MCPs?" Answer: only the
ones we wrote. Third-party MCPs Coscientist consumes are dependencies,
not redistributables.

- `EXTERNAL_MCPS.md` — documents the 7 external MCPs: `consensus`,
  `paper-search`, `academic`, `semantic-scholar`, `playwright`,
  `browser-use`, `zotero`. Each entry: what it does, install
  command, API keys required, which Coscientist component uses it,
  upstream source.
- `README.md` updated — points at both `MCP_SERVERS.md` (custom)
  and `EXTERNAL_MCPS.md` (third-party).
- `tests/test_marketplace.py` extended with `DocsPresenceTests` (4
  tests): SKILLS.md / MCP_SERVERS.md / EXTERNAL_MCPS.md present,
  EXTERNAL_MCPS.md mentions every external MCP, README links to
  marketplace install + both index docs.

Doctrine: redistributing third-party MCPs under
`epireve/coscientist` would be vendoring without permission. We
list them with attribution and install instructions, full stop.

Suite: 1574 → 1578 passing (+4).

### v0.76 — retraction-mcp live integration tests (opt-in) ✅ (2026-04-28)

Existing v0.72 test suite is fully offline (mocked HTTP). v0.76
adds opt-in live tests that hit real Crossref + PubPeer endpoints.

- `tests/test_retraction_mcp_live.py` — 5 tests, gated by
  `COSCIENTIST_RUN_LIVE=1` env var. Skipped by default (so CI +
  default `tests/run_all.py` stay offline).
- Fixtures:
  * **Real DOI** (Vaswani 2017 attention paper) — should resolve,
    not be flagged as retracted.
  * **Known retraction** (Wakefield 1998 MMR-autism, Lancet) —
    must surface `is_retracted=True`.
  * **Nonsense DOI** — must return `found=False`.
  * **Batch lookup** — round-trip on 3 DOIs.
  * **PubPeer round-trip** — surface either `found=True` with
    comment count, or `found=False` if not tracked. Both valid.
- Run manually:
  ```bash
  COSCIENTIST_RUN_LIVE=1 uv run python tests/test_retraction_mcp_live.py
  ```

Suite total unchanged when offline: 1569 → 1574 passing (+5;
new live tests are no-ops without env var).

### v0.75 — MCP_SERVERS.md auto-index + README install docs ✅ (2026-04-28)

Mirrors v0.67 (SKILLS.md) for custom MCPs. Now there are 3 MCP
plugins, drift between code + docs becomes a real risk.

- `lib/mcp_index.py` — pure-stdlib generator. Walks
  `plugin/coscientist-*-mcp/.claude-plugin/plugin.json` + companion
  `.mcp.json` + `server/server.py`. Extracts plugin manifest fields
  (name, version, description, keywords) + the MCP server name +
  every `@mcp.tool()`-decorated function. Emits sorted markdown
  table + per-server detail blocks.
- `MCP_SERVERS.md` — generated index, 3 entries.
- `tests/test_mcp_index.py` — 11 tests:
  * discovery floor (≥3 MCPs)
  * every entry has name, version, description, server_name, tools
  * no duplicate names
  * known plugins all surface (retraction, manuscript, graph-query)
  * tool counts match per-server expectation (3, 4, 6)
  * `MCP_SERVERS.md` exists
  * byte-matches generator output (drift detector)
- `README.md` — new "Install" section. Documents the four
  `/plugin install` commands (deep-research + 3 MCPs) with one-line
  descriptions per plugin. Links to MCP_SERVERS.md for full tool
  reference.

Suite: 1558 → 1569 passing (+11).

### v0.74 — graph-query-mcp + marketplace plugin ✅ (2026-04-28)

Third (and final, for now) custom MCP. Read-only stdio server over
the per-project citation / concept / author graph. Wraps
`lib/graph.py` SQLite-adjacency primitives and adds BFS shortest-path
that the Python API didn't expose.

**Tools (6):**
- `neighbors(project_id, node_id, relation=None, direction="out")`
- `walk(project_id, start_node, relation, max_hops=2)` — BFS
- `in_degree(project_id, node_id, relation=None)`
- `hubs(project_id, kind, relation="cites", top_k=10)`
- `node_info(project_id, node_id)` — single-node lookup
- `shortest_path(project_id, start, end, max_hops=4, relation=None)` — new

**Tests:** `tests/test_graph_query_mcp.py` — 16 tests using a real
seeded project DB (5 nodes, 5 edges across `cites` + `about`
relations). Covers all 6 tools incl. relation filters, in/out
direction, disconnected components, and shortest-path edge cases
(self, missing, max_hops cutoff, relation-filtered no-path).

**Plugin (vendoring required):**

Unlike retraction-mcp + manuscript-mcp (both standalone), this MCP
needs `lib/graph.py` + `lib/cache.py` + `lib/project.py` +
`lib/migrations.py` + `lib/sqlite_schema.sql` + `lib/migrations_sql/`
to read project DBs. Plugin vendors them.

- `plugin/coscientist-graph-query-mcp/lib/` — vendored copy of the
  6 deps (5 .py + 1 .sql + migrations_sql/v9.sql + v10.sql).
- A new test class `GraphQueryMcpPluginTests` (8 tests) asserts every
  vendored file is byte-equal to its source — drift fails CI loudly.
- `plugin/coscientist-graph-query-mcp/.mcp.json` — uses
  `${CLAUDE_PLUGIN_ROOT}` so install location-agnostic.
- `.claude-plugin/marketplace.json` — entry added.

**Server path probe:** the source server.py probes `parents[1..3]`
to find `lib/graph.py`, so the same script works in source tree
(`<repo>/lib/`) or plugin install (`<plugin>/lib/`) without code
changes.

Suite: 1534 → 1558 passing (+24).

**Install:**
```bash
/plugin marketplace add epireve/coscientist
/plugin install coscientist-graph-query-mcp@coscientist
```

**Future work:** when `graph_nodes` + `graph_edges` outgrow
SQLite-adjacency, the Kuzu migration (parked) replaces only the
backend — these 6 tool signatures map 1:1 onto Cypher-style queries.

### v0.73 — manuscript-mcp + marketplace plugin ✅ (2026-04-28)

Second custom MCP. Stdio server that converts `.docx` / `.tex` /
`.md` (or raw text) into a structured AST: sections, citations,
word count.

**Tools (4):**
- `detect_format(path)` — sniff format from extension.
- `extract_sections(path_or_text, fmt="auto")` — heading tree
  with levels + spans.
- `extract_citations(path_or_text, fmt="auto")` — citation list
  + unique keys, supporting 4 styles: `latex` (`\cite`, `\citep`,
  `\citet`, `\citeauthor`), `pandoc` (`[@key]`, `[@a; @b]`),
  `numeric` (`[1]`, `[1,2-5]`), `author-year` (`(Smith, 2020)`).
- `parse_manuscript(path_or_text, fmt="auto")` — full AST.

**Format autodetect:** `.md`/`.markdown` → markdown; `.tex`/`.latex`
→ latex; `.docx` → docx (pandoc shell-out); raw text → markdown.

**Pure-stdlib for markdown + latex paths** — only `.docx` requires
pandoc. Missing pandoc returns a structured `{"error": "..."}`
rather than crashing.

**Tests:** `tests/test_manuscript_mcp.py` — 28 unit tests (format
detect 7, citations 9, sections 5, resolve_text 4, full AST 2,
docx fallback 1). All offline; pandoc absence simulated via
`unittest.mock.patch`.

**Plugin:**
- `plugin/coscientist-manuscript-mcp/.claude-plugin/plugin.json`
  — versioned 0.1.0, MIT.
- `plugin/coscientist-manuscript-mcp/server/server.py` — bundled,
  byte-equal to `mcp/manuscript-mcp/server.py` (test enforced).
- `plugin/coscientist-manuscript-mcp/.mcp.json` — uses
  `${CLAUDE_PLUGIN_ROOT}` so install location-agnostic.
- `.claude-plugin/marketplace.json` — entry added.

**Marketplace tests extended:** 12 → 17 (new `ManuscriptMcpPluginTests`
class with 5 tests mirroring the retraction-mcp shape).

Suite: 1501 → 1534 passing (+33).

**Install:**
```bash
/plugin marketplace add epireve/coscientist
/plugin install coscientist-manuscript-mcp@coscientist
```

### v0.72 — retraction-mcp + marketplace plugin ✅ (2026-04-28)

First custom MCP server. Wraps Crossref's `update-to` /
`updated-by` retraction notices and PubPeer's public publication
API. Pure-stdlib networking — no extra deps beyond the `mcp`
package itself. Also published as a Claude Code plugin via
`.claude-plugin/marketplace.json`.

**Source layout:**
- `mcp/retraction-mcp/server.py` — FastMCP stdio server.
  3 tools: `lookup_doi`, `batch_lookup`, `pubpeer_comments`.
- `mcp/retraction-mcp/README.md` — usage + tool reference.
- `tests/test_retraction_mcp.py` — 20 unit tests covering DOI
  normalization, Crossref message parsing (retraction vs correction
  vs EoC), HTTP error paths, batch ordering, PubPeer field-name
  variants. All offline (mocked HTTP).

**Plugin layout:**
- `plugin/coscientist-retraction-mcp/.claude-plugin/plugin.json`
  — versioned 0.1.0, MIT, requires Claude Code >= 2.0.0.
- `plugin/coscientist-retraction-mcp/server/server.py` — bundled
  copy of the source server. A test asserts byte-equality so the
  plugin can never ship stale code.
- `plugin/coscientist-retraction-mcp/.mcp.json` — declares the
  stdio server via `${CLAUDE_PLUGIN_ROOT}` so the plugin works
  after `/plugin install` regardless of clone path.
- `.claude-plugin/marketplace.json` — entry added alongside
  `coscientist-deep-research`.

**Marketplace + parity tests** (new, 12 tests, 1489 → 1501):
- marketplace.json parses + has owner + plugins fields.
- Every plugin entry has required fields (name/source/description/version).
- Every plugin source path exists; every plugin has a plugin.json.
- name + version match between marketplace.json and plugin.json.
- retraction-mcp plugin: server.py declares all 3 tools, .mcp.json
  declares stdio + uses `CLAUDE_PLUGIN_ROOT`, README present.
- Bundled server.py byte-matches `mcp/retraction-mcp/server.py`.

**Install path:**

```bash
/plugin marketplace add epireve/coscientist
/plugin install coscientist-retraction-mcp@coscientist
```

The MCP server then auto-registers and exposes the three tools.

**Remaining custom-MCP work (deferred):**
- v0.73 — manuscript-mcp (.docx / .tex / .md → AST).
- v0.74 — graph-query-mcp (SQLite-adjacency primitives; Kuzu still
  parked).

### v0.71 — connect_wal retrofit on project DBs ✅ (2026-04-27)

Project DB at `~/.cache/coscientist/projects/<pid>/project.db` is
written by ~10 different skills (artifact_index, graph_nodes,
graph_edges, reading_state, journal_entries, manuscript_claims,
audit findings...). High contention surface.

- `lib/project.py::_connect` now returns a WAL connection via
  `lib.cache.connect_wal`. Idempotent — pre-existing DBs upgrade
  transparently.
- 3 new tests (1466 → 1469 passing): `create()` produces WAL DB,
  `get()` preserves WAL on reopen, concurrent reader+writer don't
  collide.
- Cleanup: collapsed the fork in `_connect` (fresh vs existing) into
  a single linear flow — schema executescript only on first create,
  `ensure_current()` always runs (idempotent), then connect_wal.

### v0.69 — db_writes retention ✅ (2026-04-27)

`db_writes` is append-only and grows unbounded. Adds bounded
retention.

- `lib/db_notify.py::prune_writes(con, *, keep_last_n=, older_than=)`
  — deletes rows outside the retention window. Read-only when both
  args are None (just returns counts).
- `audit-query` gains `prune-writes` subcommand. Args: `--db-path`
  (required), `--keep-last-n N`, `--older-than ISO-TIMESTAMP`.
- 8 new tests (1458 → 1466 passing): no-args report, keep-last-N,
  keep-last-0 clears, older-than future / past, missing table,
  CLI smoke (count + keep).
- Idempotent. Safe to run on a stopped pipeline as part of a cron.

### v0.68 — deferred-mention sweep ✅ NO-ACTION (2026-04-27)

Audited 110 raw matches for `deferred|stub|placeholder` across
`lib/` + `.claude/`. Only 1 actual deferred-feature mention found
(`agents/librarian.md` — Zotero write ops, intentionally manual).
The remaining 109 are legit feature naming (`[PLACEHOLDER: ...]`
template markers in manuscript-draft / dmp-generator / grant-draft,
test stubs, manuscript section state machine values like
`placeholder | drafted | revised`). No backlog to triage.

### v0.66 — connect_wal retrofit on critical paths ✅ (2026-04-27)

Adopts the v0.65g `lib.cache.connect_wal` helper at the three
parallel-write surfaces. Eliminates SQLITE_BUSY risk in the
orchestrator-worker fan-out paths.

- `lib/skill_persist.py::_ensure_db` — every `persist_*` helper now
  returns a WAL connection.
- `.claude/skills/deep-research/scripts/db.py::_connect` — Phase-1
  parallel dispatch (cartographer + chronicler + surveyor concurrent)
  no longer races on the run DB.
- `.claude/skills/wide-research/scripts/wide.py::_connect_wide_db` —
  cap-30 sub-agent fan-out can persist results without contention.
- 2 new tests (1456 → 1458 passing): persist_* roundtrip leaves
  journal_mode=wal, deep-research `db.py init` produces WAL run DB.
- WAL is a per-DB on-disk flag; pre-existing rollback-journal DBs
  upgrade transparently on first connection through the retrofit.

### v0.67 — auto-generated SKILLS.md index ✅ (2026-04-27)

64 skills, no global index until now. Adding a new skill could
silently fail to surface in docs.

- `lib/skill_index.py` — pure-stdlib generator. Walks
  `.claude/skills/*/SKILL.md`, parses YAML frontmatter (name +
  description + when_to_use), emits sorted markdown table.
  Run as module: `uv run python -m lib.skill_index > SKILLS.md`.
- `SKILLS.md` — top-level index, 64 entries.
- `tests/test_skill_index.py` — 8 tests:
  * discovers ≥60 skills (ratchet)
  * every entry has name, description, when_to_use
  * frontmatter name field matches directory name
  * no duplicate names
  * `SKILLS.md` exists
  * `SKILLS.md` byte-matches generator output (drift detector)
- `README.md` updated to point at the index.

Suite: 1448 → 1456 passing.

### v0.65 — structural hardening ✅ (2026-04-27)

Six-commit pass on break-risk surface area. Each commit independently
revertable; none touched user-facing behavior.

- **v0.65b** — auto-discover test classes. `tests/run_all.py` shrank
  from ~520 LOC of manual import/registration to ~70 LOC of `pkgutil`
  walk. Priority modules (gates, integration) run first; cache-leak
  detector runs last. Surfaced 2 previously-orphaned test classes.
  Ratchet test (`test_runner_discovery.py`) prevents silent class loss.
- **v0.65d** — migration monotonicity invariants. New `ALL_VERSIONS`
  tuple in `lib/migrations.py`; 7 invariant tests (start-at-1,
  strictly increasing, contiguous, MIGRATIONS subset, fresh-DB =
  ALL_VERSIONS, idempotent re-run, MIGRATIONS unique).
- **v0.65a** — schema-as-single-source. v9/v10 DDL extracted to
  `lib/migrations_sql/v9.sql` + `v10.sql`; `_ensure_v9_tables` and
  `_ensure_v10_tables` now `executescript` from the fragment files.
  Removes ~140 LOC of duplicated DDL from `migrations.py`.
  `test_schema_parity.py` asserts schema.sql + migrations produce
  identical table set / index set / column shape.
- **v0.65f** — SKIPPED. After v0.65a `migrations.py` is 372 LOC; the
  growth that motivated splitting halted. Re-evaluate at v0.70+.
- **v0.65c** — skill/agent name invariants.
  `test_skill_agent_invariants.py` asserts every `PHASE_ALIASES`
  target maps to a real `.claude/agents/<name>.md`, no alias points
  at itself, every agent has YAML frontmatter, every agent is
  referenced somewhere outside its own file (orphan detector), and
  the v0.53.6 `wide-*` agents all exist.
- **v0.65e** — cache-leak detector. `test_cache_leak_detector.py`
  snapshots `~/.cache/coscientist/` at module-import time, asserts
  unchanged at end of suite. Runs last via new `_LATE_MODULES` tuple
  in `run_all.py`. Catches tests that bypass `isolated_cache()` and
  pollute real cache.
- **v0.65g** — WAL mode helper. New `lib.cache.connect_wal(db_path)`
  opens SQLite with `journal_mode=WAL` + `busy_timeout`. Opt-in for
  parallel writers (Wide Research orchestrator-worker). Idempotent;
  WAL persists per-DB. 7 tests cover mode set, persistence,
  busy_timeout, parent-dir creation, concurrent reader+writer.

Suite: 1410 → 1448 passing (+38). Three commits land this iteration:
b+d, a, c+e+g.

### v0.64 — audit-query resolutions subcommand ✅ (2026-04-27)

Surfaces v0.63's `citation_resolutions` table through the existing
`audit-query` skill. "How well is resolve-citation actually doing"
becomes a one-line CLI call.

- `audit-query/scripts/query.py` — new `resolutions` subcommand.
  Reports total / matched / unmatched / match rate / score buckets
  (`<0.3`, `0.3-0.5`, `0.5-0.7`, `0.7-0.9`, `>=0.9`) + the most
  recent N rows. Filters: `--run-id`, `--project-id`,
  `--matched-only`. Read-only — gracefully reports
  `table_present: false` for non-coscientist DBs.
- 5 new tests (1410 total; 0 failures): empty table, missing table,
  populated summary, matched-only filter, run-id filter.

### v0.63 — citation_resolutions persistence ✅ (2026-04-27)

Closes the v0.58 deferred persistence stub. resolve-citation now
records every resolution attempt — matched and below-threshold
alike — to the `citation_resolutions` table.

- Migration v10 — new table `citation_resolutions` (resolution_id,
  run_id, project_id, input_text, partial_json, matched, score,
  threshold, canonical_id, doi, title, year, candidate_json, at) +
  3 indexes. Same coscientist-DB guard pattern as v9.
- `lib/skill_persist.py` — `persist_citation_resolution()` helper
  + db-notify line. Mirrors persist_debate / persist_gap_analyses
  shape.
- `resolve-citation/scripts/resolve.py` — `--persist-db` is no
  longer a stub. Accepts `--db-path` (explicit), `--run-id` (resolves
  to runs/run-<id>.db), or `--project-id` (resolves to
  projects/<id>/project.db). Errors clearly when none provided.
- 7 new tests (1405 total; 0 failures): v10 migration creates table
  + idempotency, persist for matched, persist for below-threshold,
  db_writes audit row written, CLI smoke writes a row, CLI errors
  without target.

### v0.62 — calibration anchors integration ✅ (2026-04-27)

Wires the v0.61 calibration sets into `publishability-check`'s gate
and gives the `publishability-judge` agent a structured way to pull
anchor cases for a venue. Closes the "calibration anchors" loop in
the A5 critical-judgment subsystem.

- `publishability-check/scripts/gate.py` — `calibration_warning` now
  uses `lib.calibration.slugify_venue` + `lib.calibration.load`
  (single source of truth for slug + on-disk schema). New: warning
  also matches by `canonical_id` substring in reasoning, not only
  title prefix.
- `calibration/scripts/manage.py` — new `anchors` subcommand emits a
  prompt-ready anchor block for a venue. Markdown by default;
  `--format json` for programmatic use; `--max-per-bucket` caps
  cases per bucket. Designed to be piped into the publishability
  judge's prompt context.
- 4 new tests (1398 total; 0 failures): `anchors` md output,
  `anchors` json output, missing-venue nonzero exit, max-per-bucket
  cap honored.

### v0.61 — calibration set tooling ✅ (2026-04-27)

Operationalizes the "optional calibration anchors" hook documented in `publishability-check`. Per-venue reference set of known-accepted / -rejected / -borderline papers, lets the gate ground verdicts against empirical priors instead of pure model intuition.

- `lib/calibration.py` — `CalibrationSet`, `CalibrationCase`, `slugify_venue`, atomic `save`, `load`, `add_case` (refuses duplicate by canonical_id, then by case-insensitive title), `remove_case`, `render_summary` (markdown), `coverage_check` (flags `< 3` per bucket + missing buckets + anchored %). Pure stdlib.
- `.claude/skills/calibration/` — SKILL.md + `scripts/manage.py` CLI: `init` / `add` / `remove` / `show` / `check` / `list`. Storage at `~/.cache/coscientist/calibration/venues/<slug>.json`.
- 25 new tests (1394 total; 0 failures). 7 classes — case serialization, slugify, add/remove duplicates, save/load roundtrip, summary render, coverage thresholds, CLI smoke (init→add→show, remove, check, list, dup-rejection).

### v0.60 — writing-style venue overlays ✅ (2026-04-27)

Filled the pending "venue-style overlays" gap inside `writing-style`.
`lib/venue_style_overlay.py` registers 12 venues (NeurIPS / ICLR / ICML /
Nature / Science / eLife / NEJM / JAMA / PLOS ONE / arXiv / Annual
Reviews / Royal Society Open Science) with voice / tense / pronoun /
hedge-tolerance preferences, plus heuristic detectors and a markdown
brief renderer. `audit.py` gained `--venue` and `--venue-only` flags;
combined and venue-only paths share one report. Pure stdlib, regex
only — no NLP libs. 17 new tests, full suite 1369/1369 passing.

### v0.58 — resolve-citation skill ✅

Closes the long-pending "given a partial reference like 'Smith 2020', resolve it to a canonical paper" item. Pure-stdlib heuristic resolver feeding off orchestrator-harvested Semantic Scholar candidates.

- `lib/citation_resolver.py` — `parse_partial`, `score_match`, `pick_best`. Frozen `PartialCitation` dataclass; weighted score (45% authors, 25% year, 30% title token Jaccard); 0.5 acceptance threshold.
- `.claude/skills/resolve-citation/` — SKILL.md + `scripts/resolve.py` CLI with `--interactive` (parse-only) and `--candidates <path>` (score) modes. Orchestrator-harvest pattern; never calls MCPs itself. `--persist-db` emits a `[db-notify]` placeholder; full table persistence deferred.
- 17 new tests (1352 total; 0 failures). Handles "Smith 2020", "Vaswani et al., 2017 — Attention", multi-author with em-dash, and keyword-only-with-year inputs.

### v0.59 — graph-viz mermaid renderer ✅

Closes the leftover from earlier roadmap entries — "Visualization (mermaid embed; Cytoscape.js if a web dashboard emerges)". Pure-stdlib mermaid renderer over `graph_nodes` + `graph_edges`.

- `lib/graph_viz.py` — `render_mermaid`, `render_concept_subgraph`, `render_paper_lineage`. Distinct shapes per kind (paper rectangle, concept circle, author flag, manuscript hexagon); collapses parallel edges to `relation ×N`; truncates by in-degree; drops labels on dense graphs.
- `.claude/skills/graph-viz/` — SKILL.md + `scripts/render.py` CLI for whole-project, BFS-subgraph, and citation-lineage renders. Read-only — no DB writes.
- 11 new tests (1335 total; 0 failures). Counterpart of `graph-query` (which returns JSON walks).

### v0.57 — DB persistence + db-notify ✅ (2026-04-28)

User-flagged gap: outputs from v0.51-v0.56 (Wide Research, debate,
gap-analyzer, contribution-mapper, venue-match, mode-selector) were
written only to filesystem, not the SQLite databases. Many tables
had zero writers.

- Migration v9 — 8 new tables: `wide_runs`, `wide_sub_agents`,
  `debates`, `gap_analyses`, `venue_recommendations`,
  `contribution_landscapes`, `mode_selections`, `db_writes`.
  Idempotent in-code via `_ensure_v9_tables`; guarded against generic
  test DBs (only fires when `runs`/`papers_in_run`/`projects` exists).
- `lib/db_notify.py` — `record_write()` + `format_notification()`. Every
  skill that writes rows now emits a structured `[db-notify] wrote N
  rows in TABLE (skill=X)` line to stderr so the user/orchestrator
  sees DB activity in real time.
- `lib/skill_persist.py` — shared helpers: `persist_debate`,
  `persist_gap_analyses`, `persist_venue_recommendations`,
  `persist_contribution_landscape`, `persist_mode_selection`. Each
  opens a DB, runs migrations, writes rows, emits notification.
- Wide Research: `cmd_init` + `cmd_synthesize` write `wide_runs` +
  `wide_sub_agents` rows to per-Wide DB
  (`runs/wide-<rid>.db`); state transitions during synthesis update
  sub-agent rows (`COMPLETE`/`ERROR`/`INITIALIZED`).
- debate, gap-analyzer, contribution-mapper, venue-match: each gained
  `--persist-db <path>` flag.
- `audit-query records --db-path X` — new subcommand. Lists per-table
  row counts. With `--writes`, also dumps `db_writes` audit summary
  (per-table totals + last-write time).
- 15 tests (`test_v0_57_persistence.py`) covering migration, db-notify,
  per-skill persistence, Wide CLI end-to-end, audit-query records.

Full suite: 1324/1324 passing.

### v0.56 — Self-play debate ✅

A5 capstone. PRO + CON + JUDGE sub-agents argue opposing sides of a
verdict (novelty/publishability/red-team) with 4-axis judge scoring
(groundedness, specificity, responsiveness, falsifiability). Mechanical
scoring helpers double as test contracts; mechanical-vs-judge drift
flagged at 0.2 threshold. `lib/debate.py`, `.claude/skills/debate/`,
3 sub-agents (`debate-pro`, `debate-con`, `debate-judge`).

### v0.55 — A5 trio ✅

Closed remaining A5 sub-skills. `lib/gap_analyzer.py` (real-vs-artifact,
addressable, tier A/B/C/none, adjacent-field analogues, difficulty),
`lib/contribution_mapper.py` (method/domain/finding decomposition +
Jaccard distance + 2D landscape projection + ASCII grid),
`lib/venue_match.py` (15-venue registry + 6-component scoring +
reasons-for/against). Each gets a CLI under `.claude/skills/`.

### v0.54 — Brief richness + retention transparency ✅

`lib/brief_renderer.py` — 4 pure-stdlib renderers (hypothesis cards
sorted by Elo, evidence table grouped by claim.kind, Socratic
discussion questions, run_recovery substitution).
Templates extended; new `RUN-RECOVERY.md` template carries 25+
sqlite3 query recipes for reading full phase outputs from the run DB.

### v0.53 — Wide Research mode ✅

Full v0.53.1–v0.53.7 series. Quick/Deep/Wide three-mode architecture,
6 TaskSpec types (triage/read/rank/compare/survey/screen), HITL
Gates 1+2+3, $50 hard ceiling, 30-concurrent cap, telemetry/observability
(`observe`), timeout sweep, cycle guard, partial-data warning, Wide →
Deep handoff (`db.py init --seed-from-wide` + migration v8 for
`runs.parent_run_id` + `runs.seed_mode`), per-type synthesizer
fan-in, per-task `wide-*` sub-agents (wide-triage / wide-read /
wide-rank / wide-compare / wide-survey / wide-screen).
`lib/wide_research.py`, `lib/wide_synthesis.py`, `lib/mode_selector.py`,
`.claude/skills/wide-research/`.

### v0.52 — Search-strategy depth ✅

PICO/SPIDER/Decomposition framework selection (`lib/search_framework.py`),
adversarial pre-Phase-1 critique skill (`search-strategy-critique`),
Jensen-Shannon era detection (`lib/era_detection.py`), cross-persona
disagreement scoring (`lib/disagreement.py`), concept-velocity metric
(`lib/concept_velocity.py`). Migrations v5/v6/v7.

### v0.51 — Phase 1 parallel dispatch ✅

`lib/phase_groups.py` declares concurrency-safe groups (cartographer +
chronicler + surveyor). `db.py next-phase-batch` returns batch as JSON
(action: run/break/done/error). Steward reads `phases ORDER BY ordinal`
so concurrent completion preserves deterministic output.

### Original v0.51 → v0.53 plan (kept as historical reference)

Live validation run 79fa3b38 (April 2026, "human digital memory with adaptive forgetting mechanics") + analysis of Consensus's three official skills (literature-review-helper, consensus-grant-finder, recommended-reading-list) surfaced two action clusters: **speed/parallelization** and **search-strategy planning depth**.

### ~~v0.51 — Parallelization + speed~~ ✅

The Expedition pipeline currently runs 10 phases strictly sequentially. Most phases inside a phase-group are independent.

- **Parallel Phase 1**: cartographer + chronicler + surveyor are independent (read different harvests, no shared state). Dispatch as 3 concurrent `Task` calls in one orchestrator message. Saves ~6 min.
- **Partial parallel Phase 2**: synthesist + architect can run in parallel. Inquisitor depends on architect; weaver depends on synthesist + architect + inquisitor. Tree-DAG dispatch. Saves ~3 min.
- **Parallel MCP harvest within persona**: orchestrator currently fires Consensus → S2 → paper-search sequentially per persona. Issue all 3 in single tool-call batch. Saves ~1 min × 6 personas.
- **`--quiet` / `--milestone-only` flag for `db.py resume`**: suppress orchestrator narration tool calls between phases. Show only break points + final completion. Helps Cowork sessions stay readable. Saves ~2 min wall-clock on chatter alone.

Architectural blockers: none. Claude Code Agent tool already supports parallel invocation (single message + multiple Agent calls). Just needs orchestrator to issue them in batches.

Estimated total: 30–60 min → **15–25 min** (~50% faster).

### v0.52 — Search-strategy depth

Sequential plan: foundation first (framework + sub-area decomposition), then layered strategic intelligence on top.

- **v0.52.1 (SHIPPED)** — Framework + sub-area decomposition foundation. `lib/search_framework.py` (PICO/SPIDER/Decomposition templates + heuristic suggest), `runs.search_strategy_json` column (migration v5), 3 db.py CLI subcommands (suggest-strategy / get-strategy / set-strategy). User checkpoint at Break 0 before searches fire.

- **v0.52.2** — Adversarial search planning. Inquisitor attacks the search-strategy *before* Phase 1 fires. "What would we miss with this sub-area split? What angles are absent? What's the anti-coverage?" Catches blind-spots before they cost two phases of bad foundation.

- **v0.52.3** — Citation-network-gradient era detection. Replace arbitrary `year_min: 2015` buckets with empirically-detected inflection points. Trace forward-citation lineage from top-Elo seminals; find years where citation-vocabulary distribution shifts (Jensen-Shannon divergence over abstract n-grams).

- **v0.52.4** — Cross-persona disagreement scoring. Extend `harvest_count` (v0.50.4) with `disagreement_score` — papers where cartographer flags as seminal but surveyor flags as gap-creator are *more* important than consensus papers. Persona disagreement = high-leverage signal.

- **v0.52.5** — Adversarial query mutation. Per sub-area: emit three deliberately-divergent query variants (angle A, angle ¬A, angle ⊥A), run each, dedup. Union coverage > any single phrasing.

- **v0.52.6** — Concept-velocity metric. Per term in abstracts, track citation-pool growth/decline trajectory. Mechanical emerging-vs-deprecated vocabulary detection.

### v0.53 — Wide Research mode (orchestrator-worker fan-out)

Quality audit of run a933c2db (see `docs/QUALITY-AUDIT-a933c2db.md`) plus user-supplied Manus Wide Research blueprint motivate a third research mode.

**Three modes**:
- **Quick** — single-agent, single fact-finding, 30s-2min, $0.05-0.30
- **Deep** — existing 10-phase Expedition pipeline, 15-30 min, $3-5
- **Wide** — orchestrator-worker fan-out across N items (10-250), 5-20 min, $5-30

Wide complements Deep — use Wide to triage 100 papers → 30 → feed those 30 to Deep as scout's seed.

Architecture: orchestrator decomposes into N TaskSpecs → fan-out parallel sub-agents (each with fresh context, filesystem-as-memory, tool-masking state machine, error-retention policy, todo-recitation anti-drift) → synthesizer with fresh context receiving file refs + summaries (NOT raw content).

**Wide TaskSpec types**: `triage` (relevance scoring), `read` (PDF + extraction → structured per-paper data), `rank` (pairwise Elo), `compare` (per-item feature extraction), `survey` (per-author trajectory), `screen` (PRISMA-style include/exclude). User specifies via `--type` or auto-detected.

**Wide → Deep handoff** (clever, not glue):
- Level 1 — Wide-`triage` output → Deep scout via `--seed-from-wide <run_id> --seed-top-k N`
- Level 2 — Wide-`read` populates paper artifacts (content.md, references.json) so Deep's cartographer computes citation in-degree mechanically (not heuristic abstract inference). Synthesist stops speculating; brief becomes research-citable.
- Level 3 — Cumulative Deep → Wide → Deep refinement loop
- Migration: `runs.parent_run_id` + `runs.seed_mode`. Scout phase short-circuits when `--seed-from-wide` set.

Phasing:
- **v0.53.1** — TaskSpec dataclass + orchestrator decomposition + single sub-agent POC (`triage` type)
- **v0.53.2** — 3-5 sub-agent fan-out via asyncio.gather + HITL Gate 1
- **v0.53.3** — Scale to 30+ with concurrency caps, observability, HITL Gates 2+3
- **v0.53.4** — Synthesis quality + add `read`/`rank`/`compare`/`survey`/`screen` TaskSpec types
- **v0.53.5** — Wide → Deep handoff + mode-selector; auto-detect Quick/Deep/Wide

Full design in `docs/RESEARCH-MODES-PLAN.md`. References Manus (KV-cache stability, filesystem-as-memory, error retention, todo recitation, attention recitation) + Anthropic (orchestrator-worker, 15× token multiplier, 80% variance explained by token usage).

### v0.54 — Brief richness + retention transparency (optional)

User concern from run 79fa3b38: brief.md is 12K, looks short relative to upstream phase output (~21K total in DB). Reality: nothing lost — three orthogonal stores (brief, DB phase outputs, harvest shortlists) — but brief is summary view that hides depth.

- **Expanded brief.md template** — full hypothesis cards inline with method + falsifier + supporting_ids (currently 1-line summaries).
- **Discussion-questions section** in steward output (Consensus reading-list pattern) — Socratic prompts tying claims back to research question facets.
- **Per-section evidence tables** — claim × supporting_ids × confidence rendered as table not prose.
- **Recovery doc** — short `RUN-RECOVERY.md` showing how to query DB to recover full phase outputs (`sqlite3 ... SELECT json_extract(output_json, '$.hypotheses[0].method')`). Builds user confidence in the persistence model.

### Open question for v0.51

Does parallel Phase 1 dispatch break the Audit Log section's per-phase ordering? Audit Log assumes time-ordered phases. Possible fix: tag each persona's harvest with monotonic seq + sort by seq in steward template. Trivial, but worth verifying before v0.51 ships.

---

## Tier A — next iteration (v0.2)

The four subsystems that most directly serve the user's stated use cases. Build in this order.

### A1. Manuscript subsystem (use cases: audit WIP, ultrathink own work, critique)

Ingest the user's own manuscripts and treat them as artifacts parallel to papers. State machine: `drafted → audited → critiqued → revised`.

- ✅ `manuscript-ingest` — ingest a markdown draft into an artifact (v0.4)
- ✅ `manuscript-audit` — extract every claim; verify each against its cited source; flag overclaim/uncited/unsupported/outdated/retracted (v0.4)
- ✅ `manuscript-critique` — four reviewer personas (methodological, theoretical, big-picture, nitpicky) with structured findings + committed overall verdict (v0.4)
- ✅ `manuscript-reflect` — argument structure, implicit assumptions, weakest link, one-experiment recommendation (v0.4)
- ✅ `manuscript-draft` — outline → section → revision scaffold. Five venue templates (IMRaD, NeurIPS, ACL, Nature, thesis). Outline tracking + cite-key harvesting. Feeds into `manuscript-ingest`. (v0.26)
- ✅ `manuscript-revise` — respond-to-reviewers mode. Parses structured review; produces `response_letter.md` + `revision_notes.md`; advances state to `revised`. (v0.27)
- ✅ `manuscript-format` — pandoc-driven export (LaTeX, .docx, optional PDF); strips placeholders before export; writes to `exports/`; `list` + `clean` subcommands. (v0.27)
- ✅ `manuscript-version` — lightweight snapshot history; `snapshot`, `log`, `diff`, `restore`; auto-snapshots before restore; no SQLite — pure filesystem under `versions/<version_id>/`. (v0.27)

Retraction checking in `manuscript-audit` is currently a manual fallback via Semantic Scholar. Moves to automatic once the `retraction-mcp` lands (Tier B).

### A2. Reference agent with graph layer

Promote citations/concepts/authors from rows to a real graph.

- ✅ Graph foundation — SQLite adjacency tables + `lib/graph.py` (v0.3). Kuzu upgrade still parked.
- ✅ `reference-agent` skill (v0.5): Zotero sync, reading-state per project, BibTeX export, retraction flags
- ✅ Author-graph edges via Zotero sync (`authored-by`)
- ✅ Citation edges — `populate_citations.py` (v0.6): Semantic Scholar refs/citations → `cites` + `cited-by` edges
- ✅ Concept edges — `populate_concepts.py` (v0.6): run claims → `concept` nodes + `about` edges
- ✅ CSL-JSON export — `--format csl-json` flag on `reference-agent/scripts/export_bibtex.py` (v0.33)
- **Still pending** (nice-to-have, not blocking):
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
- ✅ **Systematic review (PRISMA)**: `systematic-review` skill — protocol-first init, search (freeze), two-stage screen, extract, bias, prisma, status. 4 new DB tables. (v0.28)
- ✅ **Statistics skill**: effect sizes, power analysis, meta-analysis, test selection, assumption checks. Pure stdlib — no external deps. 6 modules. (v0.29)
- ✅ **Figure agent**: register figures, audit palette/captions/alt-text, list by manuscript. (v0.29)
- ✅ **Peer-review simulator**: multi-round (review → respond → decide), per-manuscript storage under `manuscripts/<mid>/peer_review/`. (v0.29)
- ✅ **Retraction watch**: scan cited papers for retraction status, alert + journal entry on retractions, status table. Two-phase: `scan list` → MCP lookup by caller → `scan persist`. (v0.29)
- ✅ **Preprint alerts**: subscribe per project to topics + authors + sources; daily digest filtering; history. (v0.29)
- ✅ **Grant-draft skill**: funder-specific templates (NIH, NSF, ERC, Wellcome). `init` → `section` → `status`; significance+impact framing distinct from papers. (v0.29)
- ✅ **Idea-attacker agent**: standalone adversarial stress-tester for working hypotheses (outside deep-research runs). 10-attack checklist (untestable, already-known, confounded-by-design, base-rate-neglect, scope-too-broad, implementation-wall, incentive-problem, measurement-gap, wrong-level, status-quo-survives). Gate script enforces all 10 present + steelman on fatals + killer_test on non-pass verdicts. Persists to `projects/<pid>/idea_attacks/`. (v0.30)
- ✅ **Overnight mode**: breaks queued via `overnight.py queue-break` instead of blocking; `digest.md` written at end; `--overnight` flag on `db.py init`. (v0.28)

## Tier C — longer horizon

- ✅ **Sakana-style experimentation loop**: `experiment-design` (v0.33) + `reproducibility-mcp` Docker sandbox + `experiment-reproduce` (v0.34). Full loop: design → preregister → run sandboxed → analyze pass/fail → reproduce-check within tolerance.
- ✅ **Research project container**: `project-manager` skill — init/list/activate/archive/status; single global active marker. (v0.33)
- ✅ **Dataset agent**: local registry of datasets with DOIs, licenses, versions, content hashes (sha256/blake2s/sha512). State machine: `registered → deposited → versioned`. Zenodo deposit pending Phase 2. (v0.31)
- ✅ **Slide-draft skill**: manuscript → beamer/pptx/revealjs/slidev via pandoc. 4 styles (standard/short-talk/long-talk/poster) with section-aware content extraction. (v0.31)
- ✅ **Data management plan generator**: NIH DMSP, NSF DMP, Wellcome, ERC templates. (v0.32)
- ✅ **Citation alerts**: two-phase tracker (`list` → S2 lookup → `persist`); per-tracked-paper snapshots; daily digests. (v0.32)
- ✅ **Reviewer-assistant skill**: scaffold a structured peer review (5 sections + recommendation + confidence). 4 venue templates (NeurIPS/ICLR/Nature/generic). (v0.31)
- ✅ **Negative-results logger**: dedicated artifact kind `negative-result`. State: `logged → analyzed → shared`. (v0.31)
- ✅ **Credit tracker**: CRediT taxonomy (14 roles); per-manuscript with audit + statement export (narrative + table). (v0.31)
- ✅ **Field-trends analyzer**: read-only graph aggregations (concepts, papers, authors, rising/declining momentum). (v0.32)
- ✅ **Reading-pace analytics**: read-only velocity + backlog + trend over `reading_state` across projects. (v0.31)
- ✅ **Open-data deposit**: zenodo-deposit skill — bridges dataset-agent to Zenodo REST API; mints DOIs; sandbox option. (v0.32)
- ✅ **Registered reports pathway**: Stage 1/Stage 2 state machine with monotonic transitions; `--force` overrides. (v0.32)
- ✅ **Ethics/IRB skill**: IRB application templates (exempt/expedited/full-board) + per-project COI registry. (v0.32)
- ✅ **Meta-research skill**: cross-project trajectory + concept overlap + productivity. Read-only. JSON or Markdown. (v0.33)

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

**Re-test 2026-04-25 later in session**: probed item 1 of the resume
checklist with a fresh `mcp__semantic-scholar__search_papers` call from
the orchestrator (not a sub-agent). Same `403 Forbidden` from
`api.semanticscholar.org` after 3 retries. The egress block is still in
place; nothing in items 2–4 is testable from this runtime. Confirms
the constraint is environmental and persistent, not transient.

**Third runtime constraint (added 2026-04-25)**: in this runtime,
general-purpose sub-agents that need many tool calls before persisting
**reliably die at the Claude API stream-idle timeout**. Empirical record
this session:

- `social` (first attempt) — 80 tool calls / 12 minutes / 48 MCP queries,
  zero papers persisted before timeout. Fixed at the persona layer
  (per-angle persistence), but the underlying timeout still applied.
- `pdf-extract dry-run harness` sub-agent — 16 tool calls / ~2 min,
  no test file written.
- `manuscript dogfood` sub-agent — 22 tool calls / ~3 min,
  no test file written.

Read-only sub-agents (`Explore` subagent_type, used twice for persona
audits) finished cleanly both times. The pattern is: **substantial
code-writing or many-MCP-call sub-agents are unreliable here; read-only
investigation sub-agents are fine; orchestrator-driven code writing is
fine**. When resuming: prefer driving substantial work from the
orchestrator and using sub-agents for read-only investigation, or
chunk code-writing tasks small enough that each sub-agent invocation
finishes inside the stream-idle window.

**Resume plan when we move to a runtime with paper-API egress:**

- [x] **Verify external API egress** — one `mcp__semantic-scholar__search_papers`
      call must return papers, not 403. **Verified 2026-04-27**: from the
      orchestrator, the call returned 446,602 hits on
      "transformer attention mechanism" with limit=2 in this runtime. The
      egress block from the previous runtime is gone here.
- [x] **Verify sub-agent MCP inheritance** — spawn a one-shot sub-agent that
      calls one MCP tool. **Verified 2026-04-27, FAILED**: a probe sub-agent
      (general-purpose) reported `mcp__semantic-scholar__search_papers` is
      not in its tool set. So in this runtime, sub-agents do **not** inherit
      MCP access from the parent. Confirms the architectural pivot (next
      item) is required.
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
- [x] **Fix the two cracks the per-paper harness found** (separate from
      the smoke-test pause): paper-acquire silently skips audit log on
      integrity rejection (fixed v0.17 — `action=rejected` audit line
      before SystemExit); paper-triage record_one demotes state on
      re-triage (fixed v0.17 — `_DOWNSTREAM_STATES` guard refuses
      re-triage unless `--force`). Both have tests pinning correct
      behavior in `tests/test_paper_state_machine.py`.

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
