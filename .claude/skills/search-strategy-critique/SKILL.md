---
name: search-strategy-critique
description: Adversarial critique of a deep-research run's search strategy BEFORE Phase 1 fires. Inquisitor-style attack on the framework + sub-area decomposition itself, not the hypotheses produced from it. Catches blind spots, missing anti-coverage, redundant sub-areas, premature commitments before they cost two phases of bad foundation.
when_to_use: After `db.py set-strategy` has locked a search strategy for a run, BEFORE the orchestrator dispatches cartographer/chronicler/surveyor harvests. Returns critique JSON; orchestrator decides whether to surface to user, auto-revise, or proceed with acknowledged risks.
---

# search-strategy-critique

Most pipelines ask the user "is this strategy OK?" once and proceed. We attack the strategy itself first — adversarially — because a flawed decomposition costs two phases of bad foundation that no downstream phase can recover.

## Why this exists

Imagine the user's question is "human digital memory with adaptive forgetting mechanics" and the orchestrator's framework-suggest picks **Decomposition** with sub-areas:

- M (Core mechanism) → spaced-rep + ML unlearning
- A (Applications) → memory aids + lifelogging
- L (Limitations) → privacy + metamemory
- C (Comparisons) → vs uniform-TTL, no-decay

Looks reasonable. **But the strategy is silently committed to:**

1. **Treating "forgetting" as one phenomenon.** Cartographer + chronicler + surveyor all harvest under that assumption. The Bannon-vs-Harvey founder rift is invisible until synthesist surfaces it 4 phases later.
2. **No neuroscience sub-area.** Visionary will scramble for a cross-field bridge at Phase 3 because no earlier persona was assigned the cog-neuro angle.
3. **Anti-coverage missing.** No sub-area covers "papers arguing forgetting is harmful, NOT a feature." Asymmetric corpus.

A pre-Phase 1 critic catches all three. That's the point.

## What "done" looks like

A `strategy_critique.json` written to the run DB, with structured findings:

- **blind_spots**: angles the strategy misses entirely (the Bannon-rift example)
- **missing_anti_coverage**: opposing views not represented as sub-areas
- **redundant_sub_areas**: pairs that overlap such that one persona will starve
- **premature_commitments**: assumptions baked into sub-area phrasings the user may not realize
- **verdict**: `accept` | `revise` | `reject`

Output is consumed by the orchestrator at Break 0+1 (post-set-strategy, pre-Phase 1) — surfaced to user, who either revises or acknowledges.

## How to operate (agent-facing)

You're invoked by the orchestrator AFTER `db.py set-strategy` has locked a strategy and BEFORE Phase 1 fires.

**Step 1**: Read the locked strategy:

```bash
uv run python .claude/skills/deep-research/scripts/db.py get-strategy --run-id <run_id>
```

**Step 2**: Read the run question:

```bash
sqlite3 ~/.cache/coscientist/runs/run-<id>.db "SELECT question FROM runs"
```

**Step 3**: Read scout's harvest if Break 0 already produced one (gives you concrete papers to test the strategy against, not just the question):

```bash
uv run python .claude/skills/deep-research/scripts/harvest.py show \
  --run-id <run_id> --persona scout --phase phase0
```

**Step 4**: Adversarially attack the strategy. For each component below, name at least one specific finding or report none-found explicitly:

### Attack vectors

1. **Blind spots** — angles not covered by any sub-area. Look for:
   - Founder tensions in the field that don't map to any sub-area
   - Adjacent-field analogues (cross-pollination) absent from the decomposition
   - Methodological angles missing (e.g. only theory sub-areas, no empirical)
   - Stakeholder perspectives missing (e.g. user, regulator, developer, critic)

2. **Missing anti-coverage** — for each sub-area, what's the *opposing view* and is it represented?
   - If sub-area is "memory aids → augment recall", is the "memory aids → harm" position represented?
   - If sub-area is "RTBF → privacy-protective", is "RTBF → epistemically harmful" represented?

3. **Redundant sub-areas** — pairs of sub-areas that overlap so much that:
   - Two personas will harvest the same papers
   - The decomposition is structurally over-counting one angle and under-counting another

4. **Premature commitments** — phrasings in sub-area `query_seed` or `label` that bake in unstated assumptions:
   - "Adaptive forgetting" presupposes forgetting is one mechanism (vs decay vs deletion vs trace shift)
   - "Memory augmentation" presupposes augmenting is the goal (Bannon disagrees)
   - "Lifelogging" presupposes capture-first framing

5. **Coverage asymmetry** — does the persona-assignment plan over-task one persona and starve another?
   - If 4 of 5 sub-areas are assigned to cartographer, chronicler will produce thin output

### Verdict rule

- **accept** — zero high-severity findings; minor revisions optional
- **revise** — ≥1 high-severity blind spot OR ≥1 missing anti-coverage that materially shapes the corpus
- **reject** — strategy structurally broken (e.g. no sub-areas, all assigned to same persona, framework mismatch with question)

## Output

Single JSON object. Write to stdout for the orchestrator to consume + persist via `db.py critique-strategy`:

```json
{
  "blind_spots": [
    {"angle": "Founder rift between forgetting-as-feature and forgetting-as-deficit",
     "why_missed": "All sub-areas frame forgetting as one mechanism; no sub-area explicitly covers the meta-debate.",
     "severity": "high"}
  ],
  "missing_anti_coverage": [
    {"sub_area": "Applications: memory aids + lifelogging",
     "opposing_view": "Memory aids cause harm via metamemory distortion + privacy leak",
     "why_needed": "Without it, corpus is pro-augmentation biased; surveyor will under-detect harm-side gaps."}
  ],
  "redundant_sub_areas": [],
  "premature_commitments": [
    {"sub_area": "Core mechanism",
     "assumption": "Forgetting is one mechanism (decay)",
     "could_be_false_if": "ML-unlearning step-functions ≠ Ebbinghaus curves; the field uses 'forgetting' for ≥3 mechanistically distinct phenomena."}
  ],
  "coverage_asymmetry": [],
  "verdict": "revise",
  "recommendation": "Add anti-coverage sub-area (forgetting-as-harm). Reframe Core mechanism to 'forgetting MECHANISMS plural — decay, deletion, trace shift'.",
  "confidence": 0.82
}
```

## Exit test

Before handing back, verify:

1. Every finding cites a specific sub-area, framework component, or phrasing — no abstract attacks.
2. Verdict is consistent with finding severity (no "accept" with high-severity blind spots).
3. Recommendation is actionable (e.g. "add sub-area X" not "consider whether Y").
4. Confidence is committed (a number 0.0-1.0, not hedged language).

If any fail, correct or report.

## What you do NOT do

- No new search queries (read-only over locked strategy + scout harvest)
- No phase advancement
- No paper artifact writes
- No claim insertion
