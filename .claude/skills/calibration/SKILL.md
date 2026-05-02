---
name: calibration
description: Manage per-venue calibration sets — known-accepted/rejected/borderline papers used by `publishability-check` to anchor verdicts against empirical priors. Pure stdlib, filesystem-backed (~/.cache/coscientist/calibration/venues/).
when_to_use: User wants to maintain a calibration corpus for a venue (NeurIPS / ICLR / Nature / etc.) so the publishability-check gate has empirical anchors. Add accepted papers with reasons-for-accept, rejected with reasons-for-reject, borderline with notes. The calibration anchors live alongside `publishability-check`'s gate which reads them.
---

# calibration

Maintains a per-venue reference set so publishability verdicts can be
calibrated against the user's own historical labels.

## Storage

`~/.cache/coscientist/calibration/venues/<venue-slug>.json`:

```json
{
  "venue": "NeurIPS 2024",
  "accepted":   [{title, canonical_id?, doi?, year?, reasons_for_accept, added_at}],
  "rejected":   [{title, canonical_id?, doi?, year?, reasons_for_reject, added_at}],
  "borderline": [{title, canonical_id?, doi?, year?, outcome, notes, added_at}]
}
```

Reads/writes via `lib/calibration.py`. Slug is lowercase + hyphenated.

## How to invoke

```bash
# Initialize a new venue (no-op if exists)
uv run python .claude/skills/calibration/scripts/manage.py init \
  --venue "NeurIPS 2024"

# Add a case
uv run python .claude/skills/calibration/scripts/manage.py add \
  --venue "NeurIPS 2024" \
  --bucket accepted \
  --title "Attention Is All You Need" \
  --canonical-id vaswani_2017_attention \
  --year 2017 \
  --reasons "novel architecture" "strong empirical results"

uv run python .claude/skills/calibration/scripts/manage.py add \
  --venue "NeurIPS 2024" \
  --bucket borderline \
  --title "Some paper that almost made it" \
  --outcome "reject after rebuttal" \
  --notes "scope was too narrow"

# Remove a case
uv run python .claude/skills/calibration/scripts/manage.py remove \
  --venue "NeurIPS 2024" \
  --bucket accepted \
  --canonical-id vaswani_2017_attention

# View summary
uv run python .claude/skills/calibration/scripts/manage.py show \
  --venue "NeurIPS 2024"

# Read-only health check
uv run python .claude/skills/calibration/scripts/manage.py check \
  --venue "NeurIPS 2024"

# List all venues with calibration sets
uv run python .claude/skills/calibration/scripts/manage.py list

# Emit prompt-ready anchor block for a venue (paste into publishability-judge)
uv run python .claude/skills/calibration/scripts/manage.py anchors \
  --venue "NeurIPS 2024" --format md
uv run python .claude/skills/calibration/scripts/manage.py anchors \
  --venue "NeurIPS 2024" --format json --max-per-bucket 5
```

## What "done" looks like

- ≥3 cases per bucket recommended (the `check` subcommand flags below this)
- ≥1 with `canonical_id` to anchor against the paper artifact cache
- `publishability-check` no longer emits "calibration drift" warnings
  for this venue (since the gate now finds matching cases)

## What this skill does NOT do

- Doesn't decide acceptance verdicts (that's `publishability-judge` +
  `publishability-check`)
- Doesn't fetch papers (use `paper-discovery` + `paper-acquire`)
- Doesn't graph the calibration set (that's `graph-viz` once a venue
  has graph nodes for its calibration anchors)

## CLI flag reference (drift coverage)

- `manage.py`: `--cache-root`, `--doi`
