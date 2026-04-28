"""v0.153 — idea-tree helpers for the rooted hypothesis tree.

Upgrades the 1-level `parent_hyp_id` lineage on `hypotheses` into a
proper rooted tree. Schema columns (added by migration v14):
  - `tree_id` — root hypothesis groups all nodes in one tree
                 (root.tree_id == root.hyp_id)
  - `depth` — root=0, children=1, grandchildren=2, ...
  - `branch_index` — sibling ordering within parent (0-based)

Surface area is intentionally small. record_root / record_child do
not insert new rows themselves — they assume the row was created
upstream (e.g. tournament's record_hypothesis.py) and stamp the
tree-shape columns afterwards. This keeps the existing insert path
unchanged in v0.153; v0.154/v0.155 will wire record_hypothesis.py
to call these directly.

Pure stdlib. WAL mode via lib.cache.connect_wal.
"""

from __future__ import annotations

import sqlite3
from collections import deque
from pathlib import Path

from lib.cache import connect_wal


def _row_to_dict(cur: sqlite3.Cursor, row: tuple) -> dict:
    cols = [d[0] for d in cur.description]
    return dict(zip(cols, row, strict=False))


def record_root_hypothesis(
    run_db: Path | str,
    hyp_id: str,
    **fields,
) -> str:
    """Stamp `hyp_id` as a tree root. tree_id := hyp_id, depth := 0,
    branch_index := 0 (single root per tree).

    `fields` is accepted for API symmetry with record_child_hypothesis
    but is ignored here — additional columns belong to the upstream
    INSERT path (record_hypothesis.py). Returns the assigned tree_id.
    """
    db = Path(run_db)
    con = connect_wal(db)
    try:
        with con:
            con.execute(
                "UPDATE hypotheses SET tree_id=?, depth=0, branch_index=0 "
                "WHERE hyp_id=?",
                (hyp_id, hyp_id),
            )
    finally:
        con.close()
    return hyp_id


def record_child_hypothesis(
    run_db: Path | str,
    parent_hyp_id: str,
    hyp_id: str,
    **fields,
) -> None:
    """Stamp `hyp_id` as a child of `parent_hyp_id`.

    Looks up parent's tree_id + depth, sets child's tree_id to
    parent's, depth to parent.depth + 1, and branch_index to the
    next available sibling slot (count of existing children).

    `parent_hyp_id` field on the hypotheses row is NOT updated here —
    record_hypothesis.py owns that. This call only stamps the
    tree-shape columns. Raises if parent is missing.
    """
    db = Path(run_db)
    con = connect_wal(db)
    try:
        row = con.execute(
            "SELECT tree_id, depth FROM hypotheses WHERE hyp_id=?",
            (parent_hyp_id,),
        ).fetchone()
        if row is None:
            raise ValueError(
                f"parent hypothesis {parent_hyp_id!r} not found in {db}"
            )
        parent_tree_id, parent_depth = row
        if parent_tree_id is None:
            # Parent never had its tree-shape stamped. Treat it as root
            # of its own tree to avoid orphan children. Idempotent.
            parent_tree_id = parent_hyp_id
            with con:
                con.execute(
                    "UPDATE hypotheses SET tree_id=?, depth=0, "
                    "branch_index=0 WHERE hyp_id=? AND tree_id IS NULL",
                    (parent_tree_id, parent_hyp_id),
                )
            parent_depth = 0
        # Next sibling slot = number of existing children of this parent
        # at depth = parent_depth + 1 in the same tree.
        sibling_count = con.execute(
            "SELECT COUNT(*) FROM hypotheses "
            "WHERE tree_id=? AND parent_hyp_id=?",
            (parent_tree_id, parent_hyp_id),
        ).fetchone()[0]
        with con:
            con.execute(
                "UPDATE hypotheses SET tree_id=?, depth=?, branch_index=? "
                "WHERE hyp_id=?",
                (parent_tree_id, parent_depth + 1, sibling_count, hyp_id),
            )
    finally:
        con.close()


def get_tree(run_db: Path | str, tree_id: str) -> list[dict]:
    """Return all nodes in a tree, ordered by (depth, branch_index).

    Each row is a dict mirroring the hypotheses columns. Returns
    [] if the tree_id does not exist.
    """
    db = Path(run_db)
    con = connect_wal(db)
    try:
        cur = con.execute(
            "SELECT * FROM hypotheses WHERE tree_id=? "
            "ORDER BY depth ASC, branch_index ASC",
            (tree_id,),
        )
        return [_row_to_dict(cur, row) for row in cur.fetchall()]
    finally:
        con.close()


def get_subtree(run_db: Path | str, hyp_id: str) -> list[dict]:
    """Return the subtree rooted at `hyp_id` in BFS order.

    Includes `hyp_id` itself. Walks via `parent_hyp_id` so it works
    even if tree_id is partially populated. Order: BFS top-down,
    siblings by branch_index ASC.
    """
    db = Path(run_db)
    con = connect_wal(db)
    try:
        # Pre-fetch every row keyed by hyp_id so the BFS doesn't issue
        # a query per node. Cheap for run-DB volumes (<1k hypotheses).
        cur = con.execute(
            "SELECT * FROM hypotheses ORDER BY branch_index ASC"
        )
        all_rows = [_row_to_dict(cur, row) for row in cur.fetchall()]
    finally:
        con.close()

    by_id: dict[str, dict] = {r["hyp_id"]: r for r in all_rows}
    children: dict[str, list[dict]] = {}
    for r in all_rows:
        p = r.get("parent_hyp_id")
        if p:
            children.setdefault(p, []).append(r)
    # Sort children deterministically.
    for kids in children.values():
        kids.sort(key=lambda r: (r.get("branch_index") or 0))

    if hyp_id not in by_id:
        return []
    out: list[dict] = []
    queue: deque[dict] = deque([by_id[hyp_id]])
    while queue:
        node = queue.popleft()
        out.append(node)
        for kid in children.get(node["hyp_id"], []):
            queue.append(kid)
    return out


def prune_subtree(run_db: Path | str, hyp_id: str) -> int:
    """Delete the subtree rooted at `hyp_id` (inclusive). Returns
    the number of rows deleted. No-op (returns 0) if `hyp_id` is
    missing.

    Used by tree-aware ranker (future) to drop low-quality branches
    once the tournament has settled.
    """
    nodes = get_subtree(run_db, hyp_id)
    if not nodes:
        return 0
    ids = [n["hyp_id"] for n in nodes]
    db = Path(run_db)
    con = connect_wal(db)
    try:
        with con:
            placeholders = ",".join("?" for _ in ids)
            cur = con.execute(
                f"DELETE FROM hypotheses WHERE hyp_id IN ({placeholders})",
                ids,
            )
            return cur.rowcount or len(ids)
    finally:
        con.close()
