---
name: debate
description: Self-play debate for high-stakes verdicts (novelty, publishability, red-team). Two opposing instances (PRO + CON) each produce evidence-anchored positions; a judge instance scores both and commits to a verdict. Sharpens single-pass model output by forcing both sides on the record.
when_to_use: A high-stakes verdict needs sharper grounding than a single-pass call. Examples — borderline novelty claim against a known-similar paper, publishability decision near a tier boundary, red-team's "fatal flaw" claim that the author disputes. Distinct from `novelty-check` / `publishability-check` / `attack-vectors` (those are gates; debate is conflict-resolution).
---

# debate

Three sub-agents, structured contract:

```
[ orchestrator ]
   ├─→ debate-pro    (argues FOR the claim)  ──┐
   ├─→ debate-con    (argues AGAINST)        ──┤
   │                                            ▼
   └─→ debate-judge  (scores both; commits verdict)
```

## Verdict topics

- **novelty** — PRO: "this contribution is novel" / CON: "already known"
- **publishability** — PRO: "publishable at tier X" / CON: "below bar"
- **red-team** — PRO: "no fatal flaw" / CON: "fatal flaw exists"

## What each side must produce

```json
{
  "side": "pro|con",
  "statement": "<one paragraph; no hedges; concrete>",
  "evidence_anchors": [
    {"canonical_id": "...", "claim_quote": "...", "why_relevant": "..."}
  ],
  "rebuttal_to_other": "<one paragraph; round 2 only>"
}
```

Minimum 3 anchors per side. Real `canonical_id`s required.

## Judge scoring (4 axes, each 0..1)

| Axis | What it measures |
|---|---|
| `evidence_groundedness` | anchors resolve to real `canonical_id`s |
| `argument_specificity` | concrete signals (numbers, experiments, cites); hedges penalized |
| `rebuttal_responsiveness` | rebuttal addresses the other's strongest point |
| `falsifiability` | side declared what would change its verdict |

Verdict = `pro | con | draw` (delta < 0.05 → draw). Judge writes
reasoning paragraph + a **kill_criterion** (specific observation that
would flip the verdict).

## How to invoke

```bash
# 1. Init the debate (writes spec.json)
uv run python .claude/skills/debate/scripts/debate.py init \
  --topic novelty \
  --target-id <cid-or-mid> \
  --target-claim "..." \
  [--min-anchors 3]

# 2. Orchestrator dispatches debate-pro and debate-con as parallel
#    sub-agents (single message, two Task calls).

# 3. After both return, dispatch debate-judge with both positions.

# 4. Score + persist
uv run python .claude/skills/debate/scripts/debate.py finalize \
  --debate-id <id> \
  --pro /path/to/pro.json \
  --con /path/to/con.json \
  --judge /path/to/judge.json
```

## What "done" looks like

- `~/.cache/coscientist/runs/run-<rid>/debates/<debate_id>/` contains
  `spec.json`, `pro.json`, `con.json`, `judge.json`, `transcript.md`
- Verdict committed (no hedge words; kill_criterion declared)
- Mechanical scores match judge's declared scores within ±0.1 (if
  not, judge re-prompted or flagged for human review)

## What this skill does NOT do

- Does not run an LLM-free decision (the judge is still an LLM call;
  mechanical scoring is a gate, not a replacement)
- Does not replace `novelty-check` / `publishability-check` (those
  remain the discipline gates; debate is escalation when the gate's
  output is borderline)
- Does not chain debates (one round of opening + one round of
  rebuttal — `n_rounds=2` default)
