# Idea-Tree Usage

Operator guide for rooted-hypothesis-tree workflow. Lands across v0.153 (record), v0.156 (tree-aware ranker), v0.158 (auto-prune), v0.171 (mermaid viz).

## What it is

Hypotheses don't live as flat list. They form **rooted trees**: each tree-root is one core stance, branches are method/domain forks, leaves are concrete falsifiable claims. Tournament Elo runs over tree, not over pool. Subtrees prune when undermatched. Pattern mirrors Google Co-Scientist Generation→Reflection→Ranking→Evolution loop.

Three entities matter:

- **`tree_root`** — top hypothesis. Created with `--tree-root` flag. Has no parent.
- **`parent_hyp_id`** — link from child to parent. Builds the tree.
- **`branch_index`** — sibling order under same parent. Optional, for stable rendering.

Tree lives in `hypotheses` table (run DB). Edges = `parent_hyp_id` self-reference.

## When to use it

- **Phase 2 architect output.** Architect (deep-research Phase 2) emits 3–5 tree-roots, each with 2–4 children. Replaces flat hypothesis list.
- **Mutator children** (Phase E). Every mutator-generated child links via `--parent-hyp-id` to its parent.
- **Manual hypothesis sketching.** Operator sketching alternative paths during Break 1 review.

Skip flat hypotheses when output is one-shot (use Quick mode). Use trees when at least one root has ≥2 plausible branches.

## How to use it

### Record a root

```bash
uv run python .claude/skills/tournament/scripts/record_hypothesis.py \
  --run-id <rid> \
  --agent-name architect \
  --hyp-id arch-root-1 \
  --statement "Sparse activations cause downstream brittleness." \
  --tree-root
```

### Record a child

```bash
uv run python .claude/skills/tournament/scripts/record_hypothesis.py \
  --run-id <rid> \
  --agent-name mutator \
  --hyp-id arch-root-1-A \
  --statement "Sparsity-induced brittleness emerges only at >70% zero ratio." \
  --parent-hyp-id arch-root-1 \
  --branch-index 0 \
  --falsifiers '["Brittleness flat across 30-90% sparsity"]' \
  --supporting-ids '["paper:foo_2024_a1b2c3"]'
```

Children inherit ancestry via `parent_hyp_id`. No `--tree-root` flag on children.

### Run tournament with auto-prune

```bash
uv run python .claude/skills/tournament/scripts/record_match.py \
  --run-id <rid> \
  --hyp-a arch-root-1-A \
  --hyp-b arch-root-2-B \
  --winner a \
  --auto-prune \
  --prune-threshold 1100 \
  --prune-min-matches 3
```

Auto-prune kills subtrees whose Elo < threshold after min-matches. Default thresholds (1100 / 3) = conservative.

### Tree-aware leaderboard

```bash
uv run python -m lib.tree_ranker leaderboard \
  --run-db ~/.cache/coscientist/runs/run-<rid>.db \
  --tree-id arch-root-1
```

Output: per-node Elo, depth, child-count, pruned-flag. Subtree mean Elo aggregated up to root.

### Pairs strategy (which match next)

```bash
uv run python -m lib.tree_ranker pairs \
  --run-db <path> \
  --tree-id arch-root-1 \
  --strategy sibling-first
```

Strategies: `sibling-first` (compare siblings before cross-tree), `cross-tree` (root vs root), `mixed`.

### Manual prune

```bash
uv run python -m lib.tree_ranker prune \
  --run-db <path> \
  --tree-id arch-root-1 \
  --threshold 1100 \
  --min-matches 3
```

Prints subtree-IDs that would prune. Add `--apply` to commit.

## Reading the leaderboard

Columns:

- **hyp_id** — node identifier
- **elo** — current Elo (default 1200, gain on win, lose on loss)
- **n_matches** — match count
- **depth** — distance from root (0 = root)
- **subtree_mean** — mean Elo across descendants
- **pruned** — bool, true if killed

Top of board = strongest claim *in current matchups*. Subtree mean below threshold + parent above = "good idea, weak children" — investigate before pruning whole subtree.

## Visualizing

```bash
uv run python -m lib.tree_viz \
  --run-db <path> \
  --tree-id arch-root-1 \
  > tree.md
```

Emits mermaid `graph TD` block. Nodes colored:

- **green** — Elo ≥ 1300
- **red** — Elo < 1100 (prune-candidate)
- **default** — middle band

Render in any mermaid-aware viewer (GitHub, Obsidian, VS Code mermaid preview).

## Pruning policy

Default thresholds:

| Param | Default | Meaning |
|---|---|---|
| `--prune-threshold` | 1100 | Elo floor — anything below + min-matches pruned |
| `--prune-min-matches` | 3 | Match count required before prune eligible |

When to override:

- **More aggressive** (1150 / 2): exploratory phase, want fast convergence on top 2–3 trees. Cuts noise early.
- **More conservative** (1080 / 5): high-stakes verdict (publishability, novelty). Don't kill weak-but-not-tested branches prematurely.
- **Disable**: omit `--auto-prune`. Run manual `tree_ranker prune --apply` after operator review.

Prune is destructive (sets `pruned=1` flag); restore by direct DB edit.

## Troubleshooting

### Orphan nodes

Symptom: node has `parent_hyp_id` but parent missing.

Cause: parent recorded after child (impossible if CLI used in order), or parent deleted.

Fix: re-record parent, or null out child's `parent_hyp_id` to promote to root.

### Depth bombs

Symptom: tree goes 8+ deep, leaderboard becomes unreadable.

Cause: mutator chain ran unbounded. Each child mutator generates grandchildren.

Fix: cap mutator depth to 3 in caller. Beyond depth 3 the marginal value drops; explore breadth instead.

### Undermatched subtrees

Symptom: subtree shows `n_matches=0` for all nodes after tournament runs.

Cause: pairs strategy never picked it (e.g. sibling-first stayed within first root).

Fix: switch to `--strategy mixed` or `cross-tree` for at least one round. Or manually queue matches via `record_match.py`.

### Auto-prune kills too much

Symptom: half the tree pruned after first round.

Cause: `--prune-threshold 1100` + `--prune-min-matches 3` triggered on every loser.

Fix: raise min-matches to 5, or disable auto-prune for first N rounds and run manual prune after.

### Leaderboard looks stale

Symptom: subtree_mean doesn't match new match outcomes.

Cause: leaderboard caches per-call; recompute is on-read but DB may be in transaction.

Fix: re-run with fresh process. Subtree mean is computed from current `elo` column at query time — no caching layer.

## See also

- `lib/idea_tree.py` — schema + `get_tree` reader
- `lib/tree_ranker.py` — pair selection, prune logic, leaderboard
- `lib/tree_viz.py` — mermaid renderer
- `.claude/agents/idea-tree-generator.md` — sub-agent that produces trees
- `.claude/skills/tournament/SKILL.md` — top-level skill description
