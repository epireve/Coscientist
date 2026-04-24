---
name: manuscript-reflect
description: Gate-enforced "ultrathink your own work" skill. Exposes the argument structure, makes implicit assumptions explicit, maps the evidence chain, identifies the weakest link, and proposes the single experiment that would most strengthen the work.
when_to_use: You want to understand what your manuscript is actually arguing — structurally — before submitting or before designing next experiments. Used by the `manuscript-reflector` sub-agent.
---

# manuscript-reflect

Not critique. Not audit. Not a review. A structural analysis: what are you claiming, what holds it up, and where does it break?

## What a reflection report must contain

```
{
  "manuscript_id": "...",
  "argument_structure": {
    "thesis": "<single sentence>",
    "premises": ["...", "...", ...],               // ≥ 2
    "evidence_chain": [
      {
        "claim": "...",
        "evidence": ["canonical_id1", ...],        // may include "self" for original data
        "strength": 0.0-1.0
      },
      ...
    ],
    "conclusion": "..."
  },
  "implicit_assumptions": [
    {
      "assumption": "...",
      "fragility": "low|medium|high",
      "consequence_if_false": "..."
    },
    ...                                             // ≥ 2
  ],
  "weakest_link": {
    "what": "...",
    "why": "<specific>",
    "related_assumption_id": "<optional>"
  },
  "one_experiment": {
    "description": "<specific enough to execute>",
    "expected_impact": "<how this strengthens the argument>",
    "cost_estimate": "<rough — days/weeks/months>"
  }
}
```

## Agent-facing procedure

1. Read `source.md`. Read `audit_report.json` and `critique_report.json` if available — they inform but don't replace your structural read.
2. Write the **thesis** in one sentence, your words. If you need two sentences, you don't yet understand the argument.
3. Write the **premises** — the load-bearing assertions the thesis rests on. Minimum two.
4. Trace the **evidence chain**: for each premise, what evidence supports it? How strong is that support? Use `canonical_id` where the evidence is external; use `"self"` where it's the manuscript's own data.
5. Surface **implicit assumptions** — the things the manuscript assumes without stating. Mark each with fragility and what happens if it's false.
6. Identify the **weakest link** — the single point where the argument is most likely to fail. Specific, not "the sample size".
7. Propose **one experiment** that would most strengthen the work. Not a research program — one experiment. Specific enough to execute.
8. Pipe to the gate:

```bash
uv run python .claude/skills/manuscript-reflect/scripts/gate.py \
  --input /tmp/reflect-report.json \
  --manuscript-id <mid>
```

## The gate rejects

- Missing thesis, weakest_link, or one_experiment
- Fewer than 2 premises
- Fewer than 2 implicit_assumptions
- Empty evidence_chain
- Any section containing hedge words
- An evidence_chain entry with `strength` outside [0, 1]
- A `one_experiment.description` vague enough to not actually be an experiment ("more research", "further investigation")

## Principles this enforces

From `RESEARCHER.md`: **7 (Commit to a Number — for strength + fragility)**, **9 (Premortem — weakest_link is the premortem)**, **11 (Stop — one experiment, not a program)**.

## Outputs

- `~/.cache/coscientist/manuscripts/<mid>/reflect_report.json`
- Row in `manuscript_reflections` with the full JSON
- `manifest.state` advances to `critiqued` (reflect is part of the pre-revision analysis bundle)
