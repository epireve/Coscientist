---
name: research-eval
description: Audit a deep-research run for reference quality and claim attribution. Ports SEEKER's `eval_references.py` + `eval_claims.py`. Reports dangling references, uncited claims, and low-confidence attributions.
when_to_use: After `/deep-research` finishes a run (or after any phase), before trusting the Research Brief or Understanding Map. Also useful to spot-check any markdown doc with a bibliography.
---

# research-eval

Two audits, each a separate script:

## 1. Reference audit — `eval_references.py`

Scans a `run_id`'s papers and emits:

- **Dangling refs**: references in the brief/map that don't match any paper in `papers_in_run`
- **Orphan papers**: papers acquired but never cited in the final artifacts
- **DOI quality**: fraction of references with resolved DOIs vs just titles
- **Source diversity**: distribution across arXiv / PubMed / publishers

## 2. Claim audit — `eval_claims.py`

For each row in the `claims` table:

- Verifies `supporting_ids` exist in `papers_in_run`
- Flags claims with no supporting papers (agent-synthesized but unattributed)
- Spot-checks a sample by re-reading the paper's `content.md` and asking: does this claim appear?
- Scores confidence: `high` (direct quote/paraphrase), `medium` (inference), `low` (no textual basis)

## How to run

```bash
# reference audit
uv run python .claude/skills/research-eval/scripts/eval_references.py --run-id <run_id>

# claim audit
uv run python .claude/skills/research-eval/scripts/eval_claims.py --run-id <run_id>

# both, pretty
uv run python .claude/skills/research-eval/scripts/eval_references.py --run-id <run_id> --format md
```

## Outputs

- `~/.cache/coscientist/runs/run-<run_id>-eval.md` — human-readable report
- Rows inserted into the run's `audit` table tagged `action='eval'`
- Exit code non-zero when critical issues found (dangling refs, ≥30% unattributed claims)

## Guarantees

- Read-only over paper artifacts — never mutates `content.md` or references.json
- Idempotent — re-running replaces the previous report in place
