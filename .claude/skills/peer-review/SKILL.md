---
name: peer-review
description: Use when simulating a full journal peer-review cycle — initial review, author response, and final decision. Multi-round, distinct from manuscript-critique which is single-shot. Run before submission to stress-test a manuscript across multiple rounds.
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
