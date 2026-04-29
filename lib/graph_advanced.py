"""Advanced graph algorithms — pure stdlib.

v0.179 — power-iteration PageRank over project graph_nodes/graph_edges.

Distinct from `lib.graph` (CRUD primitives) — this module hosts
read-only computational algorithms (PageRank, future: HITS, betweenness,
etc.). Operates on existing project DB; never writes back.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from lib.cache import connect_wal
from lib.project import project_db_path


def _open(project_id: str) -> sqlite3.Connection | None:
    db = project_db_path(project_id)
    if not db.exists():
        return None
    con = connect_wal(db)
    con.row_factory = sqlite3.Row
    return con


def pagerank(
    project_id: str,
    *,
    kind: str = "paper",
    damping: float = 0.85,
    iterations: int = 50,
    relation: str = "cites",
) -> dict[str, float]:
    """Power-iteration PageRank over `kind`-typed nodes connected by
    `relation` edges.

    Returns `{node_id: score}` with scores summing to ~1.0. Empty graph
    returns `{}`. Single isolated node returns `{node: 1.0}`.

    Self-loops are treated as out-edges to self — handled normally by
    the rank formula (no infinite recursion since iteration is bounded).

    Convergence: stops early when L1-delta < 1e-6 or after `iterations`
    iterations, whichever first.
    """
    con = _open(project_id)
    if con is None:
        return {}
    try:
        try:
            node_rows = con.execute(
                "SELECT node_id FROM graph_nodes WHERE kind=?",
                (kind,),
            ).fetchall()
        except sqlite3.OperationalError:
            return {}
        nodes = [r[0] for r in node_rows]
        n = len(nodes)
        if n == 0:
            return {}
        node_set = set(nodes)
        if n == 1:
            return {nodes[0]: 1.0}

        # Build inbound adjacency restricted to kind-typed nodes.
        try:
            edge_rows = con.execute(
                "SELECT from_node, to_node FROM graph_edges WHERE relation=?",
                (relation,),
            ).fetchall()
        except sqlite3.OperationalError:
            edge_rows = []
        inbound: dict[str, list[str]] = {nid: [] for nid in nodes}
        out_degree: dict[str, int] = {nid: 0 for nid in nodes}
        for fr, to in edge_rows:
            if fr in node_set and to in node_set:
                inbound[to].append(fr)
                out_degree[fr] += 1
    finally:
        con.close()

    # Initialize rank uniformly.
    r: dict[str, float] = {nid: 1.0 / n for nid in nodes}
    base = (1.0 - damping) / n

    for _ in range(iterations):
        # Dangling-node mass: nodes with out_degree==0 leak rank; redistribute.
        dangling_sum = sum(r[nid] for nid in nodes if out_degree[nid] == 0)
        dangling_share = damping * dangling_sum / n

        new_r: dict[str, float] = {}
        for nid in nodes:
            s = 0.0
            for src in inbound[nid]:
                od = out_degree[src]
                if od > 0:
                    s += r[src] / od
            new_r[nid] = base + damping * s + dangling_share

        delta = sum(abs(new_r[nid] - r[nid]) for nid in nodes)
        r = new_r
        if delta < 1e-6:
            break

    # Normalize defensively — should already sum ~1.0 with dangling fix.
    total = sum(r.values())
    if total > 0:
        r = {k: v / total for k, v in r.items()}
    return r
