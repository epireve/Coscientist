# The 10-agent Expedition

Narrative walkthrough of `/deep-research`. The pipeline runs ten
specialized sub-agents in three phases with three human-in-the-loop
review breaks.

## Why ten agents?

Each persona has a single job + a single context window. Splitting
"do research" into ten roles lets each one focus narrowly without
context pollution. It also makes failures isolatable: if `chronicler`
returns weak output, you can re-run only that one without touching
the others.

## Pipeline overview

```
              ┌────────────────────────────────────┐
              │ User question → /deep-research     │
              └──────────────┬─────────────────────┘
                             │
                          [BREAK 0] — confirm source pool
                             │
                       ┌─────▼─────┐
                       │  Scout    │ ← phase 0
                       └─────┬─────┘
                             │
        ╔════════════════════╪════════════════════╗
        ║                    │ phase 1            ║
        ║    ┌───────────────┼─────────────────┐  ║
        ║    │               │                 │  ║
        ║  Carto-       Chrono-           Surveyor  (parallel dispatch)
        ║  grapher      logist                       v0.51
        ║    │               │                 │  ║
        ║    └───────────────┼─────────────────┘  ║
        ╚════════════════════╪════════════════════╝
                             │
                          [BREAK 1] — validate foundation
                             │
                       ┌─────▼─────┐
                       │ Synthe-   │ ← phase 2a
                       │ sist      │
                       └─────┬─────┘
                             │
                       ┌─────▼─────┐
                       │ Architect │ ← phase 2b
                       └─────┬─────┘
                             │
                       ┌─────▼─────┐
                       │ Inquisitor│ ← phase 2c (adversarial)
                       └─────┬─────┘
                             │
                       ┌─────▼─────┐
                       │  Weaver   │ ← phase 2d (narrative)
                       └─────┬─────┘
                             │
                          [BREAK 2] — approve coherence
                             │
                       ┌─────▼─────┐
                       │ Visionary │ ← phase 3a
                       └─────┬─────┘
                             │
                       ┌─────▼─────┐
                       │  Steward  │ ← phase 3b — final artifacts
                       └─────┬─────┘
                             │
                  ┌──────────▼──────────┐
                  │ brief.md            │
                  │ understanding_map.md│
                  │ RUN-RECOVERY.md     │
                  └─────────────────────┘
```

## Phase 0 — Reconnaissance

### Scout

Sweeps the field for candidate papers. Reads the orchestrator-
harvested MCP results from a shortlist file (Consensus +
paper-search + academic + Semantic Scholar) and writes paper
artifact stubs.

**Input**: research question.
**Output**: 30–60 paper stubs in `papers/<cid>/manifest.json`.
**Done when**: every paper has a canonical_id, title, year, abstract.

→ **BREAK 0** — user reviews the source pool, redirects if too
narrow / too noisy.

## Phase 1 — Foundation (parallel)

These three run concurrently (v0.51).

### Cartographer

Identifies the intellectual ancestors of the field — seminal
papers, foundational works, what everything else cites. Walks the
Semantic Scholar citation graph two hops from the seed papers.

**Done when**: a list of ≥10 seminal works, each anchored to
≥3 citing papers in the corpus.

### Chronicler

Traces the chronological arc — what was tried, abandoned, paradigm
shifts. Distinguishes consensus from dead ends. Pulls retrospectives
and survey papers.

**Done when**: a 5–8-era timeline with named transitions.

### Surveyor

Maps the genuine gaps — questions the field hasn't answered,
measurements missing, phenomena nobody tried to explain. Probes for
null results.

**Done when**: ≥5 specific gaps named, each with a "why this
matters" sentence.

→ **BREAK 1** — user validates the foundation. Synthesist won't
run on a weak base.

## Phase 2 — Synthesis

### Synthesist (2a)

Extracts strong implications. What does the set of findings *imply*
that no single paper states outright? Combinatorial reasoning
across the corpus.

**Done when**: ≥3 cross-paper implications, each with citations.

### Architect (2b)

Proposes novel approaches to the gaps. Elevated token budget — gets
room to think hard. Uses adjacent-field precedents.

**Done when**: ≥3 candidate approaches, each with method sketch +
falsifier + predicted observable.

### Inquisitor (2c) — adversarial

Stress-tests Architect's proposals. Finds the weakest link, names
the assumption most likely to fail, proposes the cheapest experiment
that would kill the strongest proposal.

**Done when**: every Architect proposal has either a steelman or a
named killer experiment.

### Weaver (2d) — narrative

Narrates coherence across accumulated claims. Sharpens the original
question. Maps where the field agrees, disagrees, and talks past
itself.

**Done when**: a single coherent story, ≤2 pages, citing every
phase 1 + 2 contribution.

→ **BREAK 2** — user approves coherence + specifies final artifact
format.

## Phase 3 — Forward-looking

### Visionary

Opens genuinely new research directions. Angles not raised by any
single paper or by Architect. Uses cross-field analogues.

**Done when**: ≥3 directions, each with a cross-field analogue +
why-now argument.

### Steward

Produces the final artifacts. Read-only over the run; no new
claims. Just packages everything into:

- **`brief.md`** — the Research Brief (5–8 pages)
- **`understanding_map.md`** — six-section Understanding Map
- **`RUN-RECOVERY.md`** — instructions to resume / re-run

## After the pipeline

`/research-eval` runs automatically:

- Reference quality audit (every claim cites ≥1 real paper)
- Claim attribution check (no orphan claims)

If >30% claims are unattributed, the run aborts with a warning —
something went wrong upstream.

## Three modes share this pipeline

| Mode | Adaptation |
|---|---|
| Quick | Skip phases 1–3; Scout + Steward only |
| Deep | Full pipeline as drawn |
| Wide | N parallel sub-agents process N items, optionally seed a Deep run |

## Resumption

Any run can be interrupted and resumed. Run state lives in
`runs/run-<rid>.db`. Phases with `completed_at IS NULL` get
re-invoked. Break responses are persisted; resuming respects
prior approvals.

## Why this works (and where it strains)

**Works because**:
- Specialized context windows beat one fat agent on synthesis quality.
- Three break points let the user redirect cheaply before
  expensive synthesis fires.
- Phase 1 parallelism cuts wall-clock 3× without quality loss.
- Adversarial Inquisitor catches the "confidently wrong" failure
  mode that single-pass synthesis loves.

**Strains under**:
- Sub-agent timeouts (stream-idle ≈ 12 min in some runtimes).
  See ROADMAP §"Live smoke-test status".
- Cross-runtime MCP inheritance — sub-agents may not see MCPs the
  orchestrator does.
- Cost: full Deep run is $3–5 per question.

## See also

- `.claude/skills/deep-research/SKILL.md` — operator-facing
- `.claude/agents/<persona>.md` — what each persona does
- [`docs/architecture.md`](./architecture.md) — system layout
- `RESEARCHER.md` — research principles every persona follows
