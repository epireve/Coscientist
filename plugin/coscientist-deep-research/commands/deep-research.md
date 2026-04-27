---
description: Run the 10-agent deep research pipeline on a question. Use `/deep-research "your question"` to start a new run or `/deep-research --resume <run_id>` to continue one.
argument-hint: "<research question>" | --resume <run_id>
---

# /deep-research

Starts (or resumes) the Coscientist deep-research pipeline. Invokes the `deep-research` skill bundled in this plugin.

Plugin root: `${CLAUDE_PLUGIN_ROOT}` — all scripts referenced below live under it.

## For a new run

The user has supplied: `$ARGUMENTS`

1. Parse arguments:
   - If starts with `--resume`, extract the run_id and resume that run.
   - Otherwise, treat the whole argument string as the research question.

2. New run procedure:
   a. Initialize the run:
      ```bash
      uv run python ${CLAUDE_PLUGIN_ROOT}/skills/deep-research/scripts/db.py init --question "<question>"
      ```
      Prints a `run_id`.
   b. Read `${CLAUDE_PLUGIN_ROOT}/skills/deep-research/SKILL.md` for the full orchestration procedure.
   c. Drive the pipeline phase by phase:
      - Before each phase, check the next action:
        ```bash
        uv run python ${CLAUDE_PLUGIN_ROOT}/skills/deep-research/scripts/db.py next-phase --run-id <id>
        ```
      - If it returns an agent name (e.g., `scout`), invoke that sub-agent via the `Task` tool with `subagent_type=<name>`. Before launching, record phase start:
        ```bash
        uv run python ${CLAUDE_PLUGIN_ROOT}/skills/deep-research/scripts/db.py record-phase --run-id <id> --phase <name> --start
        ```
      - After the sub-agent returns, save its structured output to a temp JSON and record completion:
        ```bash
        uv run python ${CLAUDE_PLUGIN_ROOT}/skills/deep-research/scripts/db.py record-phase --run-id <id> --phase <name> --complete --output-json /tmp/phase-output.json
        ```
      - For search-using personas (scout, cartographer, chronicler, surveyor, architect, visionary), harvest MCP results into a shortlist file *before* invoking. Source priority: Consensus first → Semantic Scholar second → Google Scholar third (paper-search MCP). Pipe MCP results into:
        ```bash
        echo '<json-array>' | uv run python ${CLAUDE_PLUGIN_ROOT}/skills/deep-research/scripts/harvest.py write \
          --run-id <id> --persona <name> --phase <phaseN> --query "<question>"
        ```
      - If `next-phase` returns `BREAK_<n>`, prompt the user with `AskUserQuestion`. Record:
        ```bash
        uv run python ${CLAUDE_PLUGIN_ROOT}/skills/deep-research/scripts/db.py record-break --run-id <id> --break-number <n> --prompt
        # ... ask the user ...
        uv run python ${CLAUDE_PLUGIN_ROOT}/skills/deep-research/scripts/db.py record-break --run-id <id> --break-number <n> --resolve --user-input "<their answer>"
        ```
      - If returns `DONE`, finalize: print brief/map paths.

3. On any error, record it and stop — do not silently skip a phase.

## For resuming

```bash
uv run python ${CLAUDE_PLUGIN_ROOT}/skills/deep-research/scripts/db.py resume --run-id <run_id>
```

Continue from the next phase.

## Guardrails

- Never skip a break point.
- Never bypass `paper-acquire`'s triage gate.
- Source-priority rule: Consensus → Semantic Scholar → Google Scholar. Fall through on rate-limit; do not abort.
