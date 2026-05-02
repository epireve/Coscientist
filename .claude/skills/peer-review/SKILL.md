---
name: peer-review
description: Multi-round journal peer-review cycle simulator — initial review, author response, final decision. Per-manuscript storage under `manuscripts/<mid>/peer_review/`. Distinct from `manuscript-critique` (single-shot) and `reviewer-assistant` (drafting reviews of someone else's paper).
when_to_use: User says "simulate peer review", "stress-test before submission", "what would reviewers ask", "rebut my own paper". Run before submitting to a journal to surface response-letter weak points across multiple revision rounds.
---

# peer-review

Simulates the full journal peer-review loop: initial review → revision → final decision. State stored in `manuscripts/<mid>/peer_review/`.

## Scripts

| Script | CLI | Purpose |
|---|---|---|
| `review.py` | `--mid M --venue V --round N` | Generate a structured reviewer report for round N |
| `respond.py` | `--mid M --round N --response-file PATH` | Record author response to round N reviews |
| `decide.py` | `--mid M` | Generate final editorial decision based on all rounds |
| `status.py` | `--mid M [--format json\|table]` | Show round history and current state |

## State machine

`pending → reviewed → responded → decided`

Each round: `review.py` → `respond.py` → (loop or) `decide.py`

## Storage

```
manuscripts/<mid>/peer_review/
  round_1/
    review.json      # reviewer reports
    response.json    # author response
  round_2/
    review.json
    response.json
  decision.json      # final editorial decision
  state.json         # current state + round count
```

## Review structure (review.json)

```json
{
  "mid": "...", "venue": "...", "round": 1,
  "reviewers": [
    {
      "id": "R1",
      "recommendation": "major_revision|minor_revision|accept|reject",
      "summary": "...",
      "strengths": ["..."],
      "weaknesses": ["..."],
      "required_changes": ["..."],
      "optional_changes": ["..."]
    }
  ],
  "meta_review": "...",
  "decision": "major_revision|minor_revision|accept|reject"
}
```

## CLI flag reference (drift coverage)

- `decide.py`: `--decision`, `--rationale`
