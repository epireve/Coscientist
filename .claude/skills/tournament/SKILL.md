---
name: tournament
description: Pairwise Elo tournament over candidate hypotheses, plus evolutionary mutation of top-ranked candidates (Google AI Co-scientist pattern). Sharpens hypothesis quality by self-play; tracks parent→child lineage so you can see why a winning idea descended from earlier ones.
when_to_use: After `theorist` and `thinker` produce hypotheses in a deep-research run. Run pairwise matches, see the leaderboard, ask `evolver` to mutate the top-K, repeat.
---

# tournament

Implements pairwise self-play ranking over hypotheses. Inspired by Google AI Co-scientist's tournament + evolution loop.

## Schema we use (already in `lib/sqlite_schema.sql`)

- `hypotheses` — id, run_id, agent_name, gap_ref, parent_hyp_id, statement, method_sketch, predicted_observables (JSON), falsifiers (JSON), supporting_ids (JSON), elo (default 1200), n_matches, n_wins, n_losses, created_at
- `tournament_matches` — match_id, run_id, hyp_a, hyp_b, winner (hyp_id or 'draw'), judge_reasoning, at

## Four scripts

| Script | Job |
|---|---|
| `record_hypothesis.py` | Register a hypothesis (from theorist/thinker/evolver) at default Elo 1200 |
| `record_match.py` | Record a pairwise match outcome; update both hypotheses' Elo via the standard formula (K=32) |
| `pairwise.py` | Given a list of hypotheses, emit the round-robin or top-K-vs-rest pairings the `ranker` sub-agent should judge |
| `leaderboard.py` | Top-N by Elo with match-count stats and lineage info |

## record-hypothesis

```bash
uv run python .claude/skills/tournament/scripts/record_hypothesis.py \
  --run-id <run_id> \
  --agent-name theorist \
  --hyp-id hyp-001 \
  --statement "Transformers can replace evoformer at scale" \
  --method-sketch "..." \
  --predicted-observables '["TM-score parity at 100M params"]' \
  --falsifiers '["loss does not converge"]' \
  --supporting-ids vaswani_2017_x,jumper_2021_y \
  [--gap-ref gap-2] \
  [--parent-hyp-id hyp-005]
```

Defaults: `elo=1200`, `n_matches=0`, `n_wins=0`, `n_losses=0`. ID conflicts (same `hyp_id`) are rejected — IDs must be stable across runs.

## record-match

```bash
uv run python .claude/skills/tournament/scripts/record_match.py \
  --run-id <run_id> \
  --hyp-a hyp-001 --hyp-b hyp-007 \
  --winner hyp-001 \
  --judge-reasoning "hyp-001 has a clearer falsifier and cheaper killer experiment"
```

Standard Elo update with K=32:
- `E_a = 1 / (1 + 10^((R_b - R_a) / 400))`
- `R_a' = R_a + K * (S_a - E_a)` where `S_a` is 1, 0, or 0.5
- Both ratings updated atomically

`--winner` accepts a hypothesis ID or `draw`.

## pairwise

```bash
# Round-robin: every pair
uv run python .claude/skills/tournament/scripts/pairwise.py \
  --run-id <run_id> --strategy round-robin

# Top-K vs rest (cheaper for large N)
uv run python .claude/skills/tournament/scripts/pairwise.py \
  --run-id <run_id> --strategy top-k-vs-rest --top-k 3
```

Emits a JSON list of `{hyp_a, hyp_b}` for the `ranker` sub-agent to walk through.

## leaderboard

```bash
uv run python .claude/skills/tournament/scripts/leaderboard.py \
  --run-id <run_id> [--top 10]
```

Shows top-N hypotheses with Elo, win/loss/match counts, and parent lineage chain.

## Sub-agents

- **`ranker`** — pairwise judge. Given two hypotheses, picks the more promising one + records the match.
- **`evolver`** — takes the top-K Elo hypotheses, produces mutations/recombinations as children with `parent_hyp_id` set. Children re-enter the tournament.

## Principles

From `RESEARCHER.md`: **6 (Name Five)**, **7 (Commit to a Number — Elo is the number)**, **8 (Steelman before attack — pairwise judge must steelman both before picking)**.
