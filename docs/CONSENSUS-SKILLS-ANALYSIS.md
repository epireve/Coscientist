# Consensus Skills — analysis + lessons for Coscientist

Three official Consensus-MCP skills shipped 2026-04. Reviewed for what we should adopt, adapt, or skip.

## Inventory

| Skill | Trigger | Output | Tool budget |
|---|---|---|---|
| `literature-review-helper` | "I'm starting a lit review on X" | .docx research guide (8 sections) | 5/10/20 searches user-selectable |
| `consensus-grant-finder` | "find grants for my research" | .docx grant overview (9 sections) | 5 Consensus + 2 RePORTER + N NOSI fetches |
| `recommended-reading-list` | "build reading list from this syllabus" | .docx with discussion Qs per paper | 1-2 queries per topic × 6-12 sections |

## Patterns worth stealing

### 1. **Plan-tier detection** (all 3 skills)

Parse first Consensus response for "Found X, showing top Y" language. Detected tier (unauthenticated ~3 / Free ~10 / Pro ~20) drives expectations + audit log entry. **Coscientist gap**: orchestrator doesn't currently surface tier; harvest budget assumes uniform results. Should add to `harvest.py write` summary output.

### 2. **Audit log as first-class section** (all 3)

Every generated artifact has Section N = "Audit Log" with:
- Search query table (#, query, filters, returned, status)
- Three counters: queries sent / papers received / papers cited
- Failed-search row preserved (never silently skipped)
- Plan-tier disclosure
- Coverage notes ("if results sparse, may be plan limit not gap")

**Coscientist parallel**: We have `db.py` phase logging + `harvest.py status` + `audit-query` skill but no per-run "what was searched, what came back, what was cited" rolled into a single artifact section. **Lesson**: `steward` should emit an Audit Log section alongside Brief + Map.

### 3. **Three-counter discipline** (all 3)

Distinguish:
- queries_sent (orchestrator action)
- papers_received (post-dedup raw shortlist)
- papers_cited (made it into output)

We track all three implicitly across `harvest.py` + `papers_in_run` + steward output, but not explicitly summarized. **Action**: add to steward template.

### 4. **Strict source discipline** (literature-review)

> "Only cite papers that Consensus returned in this session. Never supplement with papers from training knowledge without clearly labeling them `[Not from Consensus — model knowledge]` and excluding them from all counts."

Coscientist personas have RESEARCHER.md but no explicit "no training knowledge" rule that survives sub-agent context. **Lesson**: add explicit `[Not from corpus]` labeling rule to all 10 Expedition sub-agent prompts. Currently relies on principle 1 (Triage Before Acquiring) which is implicit.

### 5. **Sequential rate-limit handling** (all 3)

> "Run Consensus searches sequentially with minimum 1-second pause. Wait for response before next call. On failure: wait 3s, retry once, log."

We have `lib/rate_limit.py` for publishers + scout's MCP fall-through but no codified "1 RPS Consensus" enforcement. **Action**: bake into `harvest.py` MCP-call wrapping (per-MCP rate-limit table), not orchestrator-recipe.

### 6. **PICO / SPIDER framework switch** (literature-review)

> "Start with PICO. Fall back to SPIDER for qualitative, Decomposition for tech/applied."

Coscientist's surveyor identifies gaps but doesn't apply a methodology framework. **Possible add**: framework-tagged gaps (population, intervention, comparison, outcome) for clinical questions. Likely over-fit for our cross-domain use though — skip unless user asks for clinical-track skill.

### 7. **Era-gated searches** (literature-review standard+ tiers)

Run one `year_max: 2015` + one `year_min: 2021` on same sub-area to surface "field evolved" deltas. Cleanly extracts terminology shifts, conclusion shifts, methodology evolution.

**Coscientist parallel**: chronicler does this implicitly via narrative. **Could improve**: chronicler's harvest could include explicit era-gated S2 queries, not just retrospectives. Add to chronicler harvest priority bullets.

### 8. **Repeat-hit + recurring-author cross-search intelligence** (literature-review)

> "Track papers across every search. Paper appearing in 3 of 5 sub-area searches is foundational. Track author names — recurring authors signal dominant research groups."

Coscientist's `merge.py` dedups by canonical_id but doesn't surface "appeared in N searches" as signal. **Action**: extend `papers_in_run` row schema with `harvest_count` (incremented when same cid appears across multiple persona harvests). Cartographer's "seminal works" detection becomes mechanical.

### 9. **Citations-per-year heuristic** (literature-review)

> "2023 paper with 150 citations is much stronger signal than 2008 paper with 150 citations."

Cheap signal. Compute on the fly in cartographer/chronicler. Add column to `papers_in_run`.

### 10. **Program officer recommendation** (grant-finder)

> "Always include a program officer recommendation. This is the single most valuable piece of advice for any grant applicant."

Direct match for our `funder` agent (in Phase D Laboratory). Currently funder drafts Specific Aims but doesn't surface PO outreach as default action item. **Action**: add to funder.md.

### 11. **NIH RePORTER POST-with-curl** (grant-finder)

> "RePORTER API requires POST. Use bash curl, never web_fetch."

If we add RePORTER MCP later (currently not wired), inherit this. Document in MCP onboarding notes.

### 12. **Discussion-question generation tied to learning outcomes** (reading-list)

For each paper: 1-sentence summary + 1 discussion question linking to course learning outcome. Forces synthesis beyond recall.

**Coscientist parallel**: steward could emit per-key-paper discussion question linking to research-question's facets. Currently brief.md is descriptive not interrogative. **Possible add**: optional "Discussion Questions" section in steward template.

## Patterns to skip

### Output-format lock-in (.docx mandatory)

All 3 ship .docx via JS `docx` package. Tied to Anthropic public skill repo `/mnt/skills/public/docx/`. We're markdown-first per CLAUDE.md ("Markdown-first; export to LaTeX/docx via manuscript-format"). Stick with brief.md + understanding_map.md as primary; let `manuscript-format` handle docx export if user wants.

### Single-MCP fixation

Consensus skills all use ONLY Consensus (+ RePORTER for grant-finder). We use 4-5 MCPs with priority fallthrough. Don't collapse to single-source — our diversity is a feature.

### `sendPrompt` interactive checkpoint

> ```javascript
> sendPrompt("Quick scan — 5 searches")
> sendPrompt("Standard review — 10 searches")
> ```

Anthropic-app-specific affordance (clickable choice chips). Claude Code uses `AskUserQuestion`. Keep break-points pattern, don't graft `sendPrompt`.

### Mandatory .docx audit appendix

Useful concept (see #2 above), but we should adapt to markdown. .docx audit log is heavy + reader-unfriendly for code-context use.

## Concrete actions (ranked)

| Priority | Action | Effort |
|---|---|---|
| P1 | Add Audit Log section to steward template (queries/received/cited counters + failed searches) | Small — edit steward.md + understanding_map.md template |
| P1 | Add `harvest_count` column to `papers_in_run`; bump on each persona's merge | Small — schema migration + merge.py |
| P2 | Add `[Not from corpus]` explicit-label rule to all 10 Expedition agents | Small — 10 frontmatter edits |
| P2 | Add citations-per-year computed field to merge.py + surface to cartographer | Small |
| P2 | Plan-tier detection in `harvest.py` (parse "showing top X" from Consensus) | Small |
| P3 | Bake 1 RPS sequential enforcement into `harvest.py` MCP-call wrapping | Medium — needs per-MCP rate-limit table |
| P3 | Era-gated searches as explicit chronicler harvest pattern | Small — add to chronicler harvest config |
| P3 | Funder agent: always include PO contact recommendation | Small — funder.md edit |
| P4 | Optional discussion-questions section in steward output | Small — template flag |

## Bottom line

Consensus's three skills are **single-purpose, single-source, .docx-output, audit-heavy**. Coscientist is **multi-purpose, multi-source, markdown-first, persistence-heavy**. We don't need to copy them — we need to import their *audit discipline* + *plan-tier awareness* + *cross-search intelligence* (repeat-hits, recurring authors, citations-per-year) into our existing pipeline.

Most valuable single steal: **Audit Log section** in steward output. Brings us closer to "researcher can verify exactly what was searched and what made it into the brief" — same trust principle Consensus calls "data integrity."
