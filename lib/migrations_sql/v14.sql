-- v0.153 — idea-tree columns on hypotheses table.
--
-- Upgrades hypotheses from a 1-level parent_hyp_id lineage into a
-- proper rooted tree. Adds:
--   1. tree_id        — root hypothesis groups all nodes in one tree
--                       (root.tree_id == root.hyp_id)
--   2. depth          — root=0, children=1, grandchildren=2, ...
--   3. branch_index   — sibling ordering within parent (0-based)
--
-- Plus composite index on (tree_id, depth) for fast subtree+BFS walks.
--
-- Idempotent: ALTER TABLE ADD COLUMN guarded in
-- lib.migrations._ensure_v14_columns. Index uses IF NOT EXISTS.

CREATE INDEX IF NOT EXISTS idx_hypotheses_tree_depth
    ON hypotheses(tree_id, depth);
