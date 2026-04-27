# Run Recovery — `{{run_id}}`

_v0.54 — retention transparency. The Research Brief is a summary
view; this document shows how to recover the **full** phase outputs
from the run DB at `~/.cache/coscientist/runs/run-{{run_id}}.db`._

## Why this exists

Three orthogonal stores back every run:

1. **`brief.md`** — curated summary, ≤2000 words, every claim cited
2. **`understanding_map.md`** — six-section learning document
3. **Run DB** — every persona's full structured output, every claim,
   every paper, every break user-input, every audit row

Nothing is "lost" between phases. The brief hides depth so it stays
readable; the DB keeps depth so you can recover it.

## Quick recipes

```bash
# Path
DB=~/.cache/coscientist/runs/run-{{run_id}}.db

# How many phases completed, and when
sqlite3 -header -column "$DB" \
  "SELECT name, started_at, completed_at FROM phases ORDER BY ordinal"

# All hypotheses with their predicted observables + falsifiers
sqlite3 -json "$DB" "
  SELECT
    hyp_id, agent_name, statement,
    json_extract(predicted_observables, '$') AS predicted_observables,
    json_extract(falsifiers, '$') AS falsifiers,
    json_extract(supporting_ids, '$') AS supporting_ids,
    elo
  FROM hypotheses
  ORDER BY elo DESC
"

# Full method_sketch for the top hypothesis
sqlite3 "$DB" \
  "SELECT method_sketch FROM hypotheses ORDER BY elo DESC LIMIT 1"

# Every claim from a specific persona, with confidence
sqlite3 -header -column "$DB" "
  SELECT kind, text, confidence, canonical_id
  FROM claims
  WHERE agent_name = 'architect'
  ORDER BY confidence DESC
"

# Phase outputs that brief.md condensed (one row = one phase's full JSON)
sqlite3 -json "$DB" \
  "SELECT name, output_json FROM phases WHERE completed_at IS NOT NULL"

# Specific persona's structured output
sqlite3 "$DB" \
  "SELECT json_extract(output_json, '\$') FROM phases WHERE name='surveyor'"

# What the user said at each break
sqlite3 -header -column "$DB" \
  "SELECT break_number, user_input, resolved_at FROM breaks ORDER BY break_number"

# All papers harvested in this run, by persona
sqlite3 -header -column "$DB" "
  SELECT canonical_id, added_in_phase, role, harvest_count
  FROM papers_in_run
  ORDER BY harvest_count DESC, added_in_phase
"

# Audit-eval results
cat ~/.cache/coscientist/runs/run-{{run_id}}/eval.md
```

## Persona output shapes

Each persona's `output_json` is structured JSON. The brief renders a
fraction of it. To see the rest:

| Persona | Carries |
|---|---|
| scout | `{candidate_papers: [...], n_seen, n_kept, queries_sent}` |
| cartographer | `{seminal_papers: [...], citation_indegrees: {...}}` |
| chronicler | `{eras: [...], inflections: [...]}` |
| surveyor | `{gaps: [...], anti_coverage: [...]}` |
| synthesist | `{implications: [...], synthesized_claims: [...]}` |
| architect | `{hypotheses: [...], method_sketches: [...]}` |
| inquisitor | `{attack_findings: [...], weakest_link: ...}` |
| weaver | `{coherence_map: ..., agreement_disagreement_table: ...}` |
| visionary | `{novel_directions: [...], cross_field_analogues: [...]}` |
| steward | `{brief_path, map_path, claims_cited, papers_cited, ...}` |

Use `json_extract(output_json, '$.<key>')` to pull a slice.

## Re-running

```bash
# Resume from current state
uv run python .claude/skills/deep-research/scripts/db.py resume \
  --run-id {{run_id}}

# Re-render brief from existing phase outputs (does not re-run agents)
uv run python .claude/skills/deep-research/scripts/db.py render-brief \
  --run-id {{run_id}}

# Spawn a child Wide run to refine a specific seam
uv run python .claude/skills/wide-research/scripts/wide.py init \
  --query "..." --items <items.json> --type read \
  --parent-run-id {{run_id}}
```

## Where the original record lives

- DB schema (canonical): `lib/sqlite_schema.sql`
- Migration history: `lib/migrations.py`
- Per-run dir: `~/.cache/coscientist/runs/run-{{run_id}}/`
  - `brief.md`, `understanding_map.md`, `eval.md`, this file
  - `inputs/<persona>-<phaseN>.json` — orchestrator-harvested
    shortlists fed to each persona

If `eval.md` reports >30% unattributed claims, the run is
unsafe to publish from. Investigate before citing.
