"""v0.155 — tree-aware ranker helpers.

Tournament v1 paired hypotheses by Elo (`pairwise.py`). v0.155 adds
tree-aware pairing — children of the same parent (siblings), every
pair within a tree (round-robin), or pairs sharing a depth band
(depth-bands). Plus subtree-mean Elo aggregation and bulk pruning
of underperforming subtrees once a minimum match count is reached.

Pure stdlib. WAL mode via `lib.cache.connect_wal`. Errors are
returned as dicts with an "error" key — never raised.
"""

from __future__ import annotations

import itertools
import sqlite3
from collections import defaultdict
from pathlib import Path

from lib.cache import connect_wal
from lib.idea_tree import get_subtree, get_tree, prune_subtree

DEFAULT_ELO = 1200.0
VALID_STRATEGIES = ("siblings", "round-robin", "depth-bands")


def _row_to_dict(cur: sqlite3.Cursor, row: tuple) -> dict:
    cols = [d[0] for d in cur.description]
    return dict(zip(cols, row, strict=False))


def tree_pairs(
    run_db: Path | str,
    tree_id: str,
    strategy: str = "siblings",
) -> list[tuple[str, str]]:
    """Emit (hyp_a, hyp_b) pairs scoped to a single tree.

    Strategies:
      - "siblings": every pair sharing a parent_hyp_id
      - "round-robin": every pair within the tree (C(n,2))
      - "depth-bands": every pair sharing the same depth

    Empty tree or unknown strategy → []. Pairs are ordered
    deterministically (by hyp_id ascending within each pair, and by
    insertion order across pairs).
    """
    if strategy not in VALID_STRATEGIES:
        return []
    nodes = get_tree(run_db, tree_id)
    if not nodes:
        return []

    pairs: list[tuple[str, str]] = []
    if strategy == "round-robin":
        ids = sorted(n["hyp_id"] for n in nodes)
        pairs = list(itertools.combinations(ids, 2))
    elif strategy == "siblings":
        by_parent: dict[str, list[str]] = defaultdict(list)
        for n in nodes:
            parent = n.get("parent_hyp_id")
            if parent:
                by_parent[parent].append(n["hyp_id"])
        for parent in sorted(by_parent.keys()):
            sibs = sorted(by_parent[parent])
            pairs.extend(itertools.combinations(sibs, 2))
    elif strategy == "depth-bands":
        by_depth: dict[int, list[str]] = defaultdict(list)
        for n in nodes:
            d = n.get("depth", 0) or 0
            by_depth[d].append(n["hyp_id"])
        for depth in sorted(by_depth.keys()):
            ids = sorted(by_depth[depth])
            if len(ids) >= 2:
                pairs.extend(itertools.combinations(ids, 2))
    return pairs


def subtree_mean_elo(run_db: Path | str, root_hyp_id: str) -> float:
    """Mean Elo of every node in the subtree rooted at root_hyp_id.

    Returns DEFAULT_ELO (1200.0) if the subtree is empty or the
    root is missing.
    """
    nodes = get_subtree(run_db, root_hyp_id)
    if not nodes:
        return DEFAULT_ELO
    elos = [
        float(n["elo"]) if n.get("elo") is not None else DEFAULT_ELO
        for n in nodes
    ]
    if not elos:
        return DEFAULT_ELO
    return sum(elos) / len(elos)


def prune_low_elo_subtrees(
    run_db: Path | str,
    tree_id: str,
    *,
    threshold: float = 1100.0,
    min_matches: int = 3,
) -> list[str]:
    """Prune subtrees rooted at depth >= 1 whose mean Elo is strictly
    below `threshold`, but only once every node in the subtree has
    n_matches >= min_matches.

    Returns the list of pruned root hyp_ids. Never prunes the tree
    root itself (depth=0). If two candidate subtrees overlap, the
    higher-up subtree wins — descendants are already gone.
    """
    nodes = get_tree(run_db, tree_id)
    if not nodes:
        return []

    # Sort by depth ascending so we evaluate higher subtrees first;
    # once a parent is pruned its descendants vanish from get_subtree.
    candidates = [n for n in nodes if (n.get("depth") or 0) >= 1]
    candidates.sort(key=lambda n: (n.get("depth") or 0, n.get("branch_index") or 0))

    pruned: list[str] = []
    pruned_set: set[str] = set()
    for n in candidates:
        hyp_id = n["hyp_id"]
        if hyp_id in pruned_set:
            continue
        sub = get_subtree(run_db, hyp_id)
        if not sub:
            continue
        # Skip if any node hasn't reached min_matches yet.
        immature = any(
            (s.get("n_matches") or 0) < min_matches for s in sub
        )
        if immature:
            continue
        # Skip if any node was already pruned via an ancestor.
        if any(s["hyp_id"] in pruned_set for s in sub):
            continue
        elos = [
            float(s["elo"]) if s.get("elo") is not None else DEFAULT_ELO
            for s in sub
        ]
        mean = sum(elos) / len(elos) if elos else DEFAULT_ELO
        if mean < threshold:
            prune_subtree(run_db, hyp_id)
            pruned.append(hyp_id)
            pruned_set.update(s["hyp_id"] for s in sub)
    return pruned


def tree_leaderboard(run_db: Path | str, tree_id: str) -> list[dict]:
    """Tree-scoped leaderboard. Returns a list of dicts ordered by
    Elo descending, then hyp_id ascending. Each row carries depth +
    parent_hyp_id columns alongside the standard tournament fields.
    """
    db = Path(run_db)
    if not db.exists():
        return []
    con = connect_wal(db)
    try:
        cur = con.execute(
            "SELECT hyp_id, agent_name, statement, elo, n_matches, "
            "n_wins, n_losses, parent_hyp_id, depth, branch_index, tree_id "
            "FROM hypotheses WHERE tree_id=? "
            "ORDER BY elo DESC, hyp_id ASC",
            (tree_id,),
        )
        rows = [_row_to_dict(cur, r) for r in cur.fetchall()]
    finally:
        con.close()
    return rows
