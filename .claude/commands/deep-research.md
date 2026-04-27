---
description: Run the 10-agent deep research pipeline on a question. Use `/deep-research "your question"` to start a new run or `/deep-research --resume <run_id>` to continue one.
argument-hint: "<research question>" | --resume <run_id>
---

# /deep-research

Starts (or resumes) the Coscientist deep-research pipeline. Invokes the `deep-research` skill.

## For a new run

The user has supplied: `$ARGUMENTS`

1. Parse arguments:
   - If starts with `--resume`, extract the run_id and resume that run.
   - Otherwise, treat the whole argument string as the research question.

2. New run procedure:
   a. Initialize the run:
      ```bash
      uv run python .claude/skills/deep-research/scripts/db.py init --question "<question>"
      ```
      This prints a `run_id`.
   b. Read `.claude/skills/deep-research/SKILL.md` for the full orchestration procedure.
   c. Drive the pipeline phase by phase:
      - Before each phase, check the next action:
        ```bash
        uv run python .claude/skills/deep-research/scripts/db.py next-phase --run-id <id>
        ```
      - If it returns an agent name (e.g., `scout`), invoke that sub-agent via the `Task` tool with `subagent_type=<name>`. Before launching, record phase start:
        ```bash
        uv run python .claude/skills/deep-research/scripts/db.py record-phase --run-id <id> --phase <name> --start
        ```
      - After the sub-agent returns, save its structured output to a temp JSON and record completion:
        ```bash
        uv run python .claude/skills/deep-research/scripts/db.py record-phase --run-id <id> --phase <name> --complete --output-json /tmp/phase-output.json
        ```
      - If it returns `BREAK_<n>`, prompt the user with `AskUserQuestion`. Record the break:
        ```bash
        uv run python .claude/skills/deep-research/scripts/db.py record-break --run-id <id> --break-number <n> --prompt
        # ... ask the user ...
        uv run python .claude/skills/deep-research/scripts/db.py record-break --run-id <id> --break-number <n> --resolve --user-input "<their answer>"
        ```
      - **At Break 0** (after scout, before Phase 1): run search-strategy enrichment block:
        ```bash
        # 1. Suggest framework + sub-area decomposition (PICO/SPIDER/Decomposition/hybrid)
        uv run python .claude/skills/deep-research/scripts/db.py suggest-strategy --run-id <id>
        # 2. Detect empirical paradigm-shift inflections in scout corpus
        uv run python .claude/skills/deep-research/scripts/db.py detect-eras --run-id <id> --format md --top-k 3
        # 3. Show user the suggested framework + inflections; ask user to confirm/edit sub-areas
        # 4. Persist user-confirmed strategy
        uv run python .claude/skills/deep-research/scripts/db.py set-strategy --run-id <id> --strategy-json /tmp/strategy.json
        # 5. Adversarially critique the strategy BEFORE Phase 1 fires
        # Invoke search-strategy-critique skill (returns critique JSON to /tmp/critique.json)
        uv run python .claude/skills/search-strategy-critique/scripts/gate.py persist --run-id <id> --input /tmp/critique.json
        # 6. If critique verdict=revise: surface to user, optionally re-do strategy
        # 7. Proceed to Phase 1 with critiqued strategy
        ```
      - **At Break 2** (after weaver, before visionary): run cross-persona disagreement scoring:
        ```bash
        # Surfaces high-leverage papers (some personas flagged, others missed) for steward to render in brief
        uv run python .claude/skills/deep-research/scripts/db.py compute-disagreement --run-id <id> --persist --format md
        ```
      - If it returns `DONE`, finalize: run `/research-eval`, print the brief/map paths.

3. On any error, record it and stop — do not silently skip a phase.

## For resuming

```bash
uv run python .claude/skills/deep-research/scripts/db.py resume --run-id <run_id>
```

Then continue from the next phase as above.

## Guardrails

- Never skip a break point.
- Never bypass `paper-acquire`'s triage gate.
- Abort the run if `/research-eval` reports >30% unattributed claims.
