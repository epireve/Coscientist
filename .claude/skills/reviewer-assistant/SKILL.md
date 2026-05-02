---
name: reviewer-assistant
description: When you are reviewing someone else's manuscript (peer review). Ingests their PDF/markdown, extracts claims, organizes a structured review draft with strengths/weaknesses/specific-comments/required-revisions/recommendation. Stores under reviews/<review_id>/. Distinct from manuscript-critique (which audits your OWN work) and peer-review (which simulates the full cycle for your own paper).
when_to_use: User says "I'm reviewing this paper", "draft my review for journal X", "structure peer review", "review for NeurIPS". Not for self-critique — use manuscript-critique for that.
---

# reviewer-assistant

Helps draft a structured peer-review when you are the reviewer. Builds review artifact under `reviews/<review_id>/`.

## Scripts

| Script | CLI | Purpose |
|---|---|---|
| `review.py` | subcommands: `init`, `add-comment`, `set-recommendation`, `export`, `status` | Main entry |

## Subcommands

```
review.py init --target-title "T" --venue "NeurIPS|ICLR|Nature|generic" [--strengths-count 3] [--weaknesses-count 3]
review.py add-comment --review-id RID --section "strengths|weaknesses|specific|required" --comment "text"
review.py set-recommendation --review-id RID --decision "accept|weak-accept|borderline|weak-reject|reject" --confidence 1-5
review.py export --review-id RID [--format markdown|json]
review.py status --review-id RID
```

## Review structure

Every review has 5 sections:

1. **Summary** — one-paragraph synopsis of what the paper does
2. **Strengths** — typically 3 items
3. **Weaknesses** — typically 3 items
4. **Specific comments** — line-by-line / section-by-section observations
5. **Required revisions** — what must change before the paper is acceptable

Plus:
- **Recommendation** — accept | weak-accept | borderline | weak-reject | reject
- **Confidence** — 1 (low) to 5 (high) on the reviewer's expertise in the topic

## Venue templates

| Venue | Tone | Length | Specific extras |
|---|---|---|---|
| `neurips` | Direct, technical | ~800 words | Soundness, Presentation, Contribution, Questions for Authors |
| `iclr` | Public, rebuttal-aware | ~700 words | Same as NeurIPS + flag for ethics |
| `nature` | Editorial-style | ~500 words | "Significant advance"? Two-step decision |
| `generic` | Balanced | ~600 words | Standard 5-section |

## Storage

```
reviews/<review_id>/
  manifest.json     # artifact_id, kind=review, state, created_at
  review.json       # structured review (sections, comments, recommendation)
  source.md         # rendered markdown of the review (output of export)
```

`review_id` = `slug(target_title)_<6-char blake2s hash>`

## State machine

`drafted → submitted` (existing review state machine).

## Linking

With `--project-id`, registers in `artifact_index` (kind=`review`).

## What this skill does NOT do

- Doesn't fetch the paper — bring your own PDF or markdown
- Doesn't pass judgment for you — it's a scaffold; you fill in substance
- Doesn't substitute for manuscript-audit (claim verification on YOUR manuscript)

## CLI flag reference (drift coverage)

- `review.py`: `--force`
