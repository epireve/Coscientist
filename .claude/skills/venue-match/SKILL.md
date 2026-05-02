---
name: venue-match
description: Data-backed venue recommendation. Scores a manuscript's characteristics against a built-in registry of common research venues (NeurIPS, ICLR, Nature, eLife, PLOS ONE, arXiv, etc.) on domain match, kind, novelty, rigor, OA preference, and deadline fit. Returns top-K with explained tradeoffs.
when_to_use: User has a finished or near-finished manuscript and wants to pick the right venue. Or earlier — they want to see which venues their work could realistically target as they refine novelty/rigor.
---

# venue-match

Pure scoring against a built-in registry of ~15 venues. Each venue
declares: type (conference/journal/workshop/preprint/registered-report),
tier (A/B/C), domains, accepted paper kinds, impact factor, OA flag,
typical acceptance rate, review turnaround.

Score components (weights):

- **Domain match** (0.30): manuscript domain ∈ venue domains
- **Kind match** (0.20): manuscript kind ∈ venue accepts_kinds
- **Novelty alignment** (0.15): A-tier needs ≥0.7, B-tier ≥0.4
- **Rigor alignment** (0.15): A-tier needs ≥0.7, B-tier ≥0.5
- **Open access** (0.10): if user states OA intent and venue is OA
- **Deadline fit** (0.05): venue review turnaround ≤ user deadline

`require_tier=A` filters out lower-tier venues (hard constraint).

## How to invoke

```bash
uv run python .claude/skills/venue-match/scripts/recommend.py \
  --domains ml --kind empirical \
  --novelty 0.8 --rigor 0.8 \
  [--open-science --deadline-days 90 --require-tier A] \
  [--top-k 5] [--write-output recommendations.md]
```

`--domains` accepts space-separated list (`ml nlp` for an ML+NLP paper).

## What "done" looks like

- Per-venue score in [0, 1] + ranked recommendations.
- Per-venue reasons-for + reasons-against (so the user understands
  the tradeoff, not just the rank).
- Markdown brief renderable via `lib.venue_match.render_brief`.

## What this skill does NOT do

- Does not query live conference deadlines or call-for-papers (the
  registry is approximate; verify specific cycles separately).
- Does not write the cover letter (use `manuscript-format` then
  manual edit).
- Does not predict acceptance probability beyond the registry's
  typical rate.

## CLI flag reference (drift coverage)

- `recommend.py`: `--audience`, `--persist-db`
