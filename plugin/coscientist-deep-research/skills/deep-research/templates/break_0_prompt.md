# Break 0 — confirm source pool

_Run `{{run_id}}` — fired after `social`, before `grounder`._

The source pool is broad on purpose. The user's job here is to confirm it covers the right interpretations, or redirect before grounder filters down.

---

## What the orchestrator summarizes before asking

Render this block to the user as plain prose + a short table. Pull values from the run DB (`papers_in_run`, `queries`, `runs.config_json`) and from social's structured output.

- **Question being researched:** {{question}}
- **Papers seeded:** {{n_papers}} unique candidates across {{n_queries}} queries to {{n_mcps}} MCPs
- **Interpretations social claims to have covered:**
  - {{interpretation_1_label}} — {{interpretation_1_count}} papers
  - {{interpretation_2_label}} — {{interpretation_2_count}} papers
  - {{interpretation_3_label}} — {{interpretation_3_count}} papers
  - {{interpretation_4_label}} — {{interpretation_4_count}} papers
- **Top candidates to spot-check** (year — title — first author — canonical_id):
  1. {{cand_1}}
  2. {{cand_2}}
  3. {{cand_3}}
  4. {{cand_4}}
  5. {{cand_5}}
  6. {{cand_6}}
  7. {{cand_7}}
  8. {{cand_8}}
- **Gaps or biases the orchestrator noticed:** {{noticed_gaps}}

The orchestrator should compute `noticed_gaps` itself — e.g. "all candidates are 2022+", "no non-English sources", "interpretation 3 has only 2 papers vs 18 for interpretation 1", "no review articles". Do not invent gaps; if none stand out, say "none obvious".

---

## The structured questions (for `AskUserQuestion`)

Send these three questions in one `AskUserQuestion` call. If the harness only supports one question per call, send them sequentially in the order below.

**Q1 — Pool acceptable?** (multiple-choice, single-select)

- "Accept — proceed to grounder"
- "Redirect — coverage is uneven or wrong"
- "Pause — I need to look at the candidate list myself first"

**Q2 — If redirecting, which interpretation needs more coverage?** (multiple-choice, multi-select; only relevant if Q1 = Redirect)

- {{interpretation_1_label}}
- {{interpretation_2_label}}
- {{interpretation_3_label}}
- {{interpretation_4_label}}
- "Other (specify in Q3)"
- "None of the above — narrow the question instead of broadening the pool"

**Q3 — Specific papers to add, drop, or flag as must-include?** (free-text)

Free-form. The user may paste DOIs, arXiv IDs, titles, or author/year stubs, optionally tagged `add:`, `drop:`, or `must-include:`.

If the harness's `AskUserQuestion` does not support free-text alongside multiple-choice, fall back to a single open-ended prompt that includes Q1/Q2/Q3 inline and asks the user to answer each.

---

## What the orchestrator does with each answer

- **Q1 = Accept** → record the resolution and move on:

  ```
  uv run python .claude/skills/deep-research/scripts/db.py record-break \
    --run-id {{run_id}} --break-number 0 --resolve \
    --user-input "accept; proceed to grounder"
  ```

  Then invoke `grounder` with the unmodified pool.

- **Q1 = Redirect** → do NOT resolve the break. Re-invoke `social` with a tighter scope built from Q2 + Q3 (e.g. add a search angle for the under-covered interpretation, or restrict to a date window). When social finishes its second pass, re-fire Break 0 with the updated counts. Only then resolve.

- **Q1 = Pause** → leave the break unresolved. Print the candidate list (paper_id, title, year, first author, source MCP) to stdout for the user to scan offline. Resume picks up at Break 0 next session.

- **Q3 has add/drop/must-include entries** (regardless of Q1) → write a `notes` row in the run DB capturing the user's instruction verbatim, tagged `break_0_directive`, then pass the parsed list to grounder via its phase input. Grounder is responsible for honoring `must-include` (these papers bypass its filter) and `drop` (these are removed from `papers_in_run`).

Resolve the break only after social's pool is in a state the user accepted, including any add/drop edits.

---

## Failure modes

- **"I don't know, you decide."** Do not silently pick. Re-prompt with a one-paragraph steelman of the strongest case for each interpretation, then ask the user to choose. If they still defer, accept the pool as-is and record the user's deferral verbatim in `--user-input` so the audit trail shows it.

- **User asks a clarifying question instead of answering.** Answer it from the run DB and social's output — do not speculate. Then re-issue the same three questions. Do not let the conversation drift onto a tangent that loses the break state.

- **User abandons mid-break.** The break row stays open (`resolved_at IS NULL`). The next `db.py next-phase --run-id <id>` call will return `BREAK_0` and the resume flow will re-prompt. Do not auto-resolve on timeout.

- **Social's interpretation labels look wrong to the user.** Treat this as Q1 = Redirect with a free-text Q3 explaining the relabeling. Re-invoke social with corrected angle descriptions in `runs.config_json`.

---

_The break is resolved only when `breaks.resolved_at` is non-null for `(run_id, break_number=0)`. Until then, do not start `grounder`._
