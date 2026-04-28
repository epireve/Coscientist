"""Graph layer — citations, concepts, authors, personal links.

Backed by SQLite adjacency tables (graph_nodes, graph_edges) in the
project DB. Kuzu is the future upgrade when volume demands it — this
API is kept small so it maps cleanly onto either backend.

Node IDs are typed strings: `paper:<cid>`, `concept:<slug>`,
`author:<s2_id>`, `manuscript:<mid>`. This makes kind-filtering cheap.

Edge relations (lowercase, hyphenated):
  cites, cited-by, extends, refutes, uses, depends-on, coauthored,
  about, authored-by, in-project
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime

from lib.project import project_db_path

VALID_KINDS = {"paper", "concept", "author", "manuscript", "experiment", "topic"}
VALID_RELATIONS = {
    "cites",
    "cited-by",
    "extends",
    "refutes",
    "uses",
    "depends-on",
    "coauthored",
    "about",
    "authored-by",
    "in-project",
}


def _connect(project_id: str) -> sqlite3.Connection:
    """v0.82: WAL-mode connection (consistency with lib.project._connect).

    lib.graph mutates graph_nodes + graph_edges, so it's a writer too.
    Matching project.py's WAL retrofit closes the inconsistency.
    """
    db = project_db_path(project_id)
    if not db.exists():
        raise FileNotFoundError(f"no project DB at {db} — create the project first")
    from lib.cache import connect_wal
    con = connect_wal(db)
    con.row_factory = sqlite3.Row
    return con


def node_id(kind: str, ref: str) -> str:
    if kind not in VALID_KINDS:
        raise ValueError(f"unknown kind: {kind}")
    return f"{kind}:{ref}"


def add_node(
    project_id: str,
    kind: str,
    ref: str,
    label: str,
    data: dict | None = None,
) -> str:
    nid = node_id(kind, ref)
    con = _connect(project_id)
    with con:
        con.execute(
            "INSERT OR IGNORE INTO graph_nodes (node_id, kind, label, data_json, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (nid, kind, label, json.dumps(data) if data else None, datetime.now(UTC).isoformat()),
        )
    con.close()
    return nid


def add_edge(
    project_id: str,
    from_nid: str,
    to_nid: str,
    relation: str,
    weight: float = 1.0,
    data: dict | None = None,
) -> None:
    if relation not in VALID_RELATIONS:
        raise ValueError(f"unknown relation: {relation}")
    con = _connect(project_id)
    with con:
        con.execute(
            "INSERT INTO graph_edges (from_node, to_node, relation, weight, data_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                from_nid,
                to_nid,
                relation,
                weight,
                json.dumps(data) if data else None,
                datetime.now(UTC).isoformat(),
            ),
        )
    con.close()


def neighbors(
    project_id: str,
    nid: str,
    relation: str | None = None,
    direction: str = "out",
) -> list[dict]:
    """Return neighboring node rows. direction ∈ {out, in, both}."""
    con = _connect(project_id)
    params: list = [nid]
    if direction == "out":
        q = "SELECT n.* FROM graph_edges e JOIN graph_nodes n ON n.node_id=e.to_node WHERE e.from_node=?"
    elif direction == "in":
        q = "SELECT n.* FROM graph_edges e JOIN graph_nodes n ON n.node_id=e.from_node WHERE e.to_node=?"
    else:
        q = (
            "SELECT n.* FROM graph_edges e JOIN graph_nodes n "
            "ON n.node_id=CASE WHEN e.from_node=? THEN e.to_node ELSE e.from_node END "
            "WHERE ? IN (e.from_node, e.to_node)"
        )
        params = [nid, nid]
    if relation:
        q += " AND e.relation=?"
        params.append(relation)
    rows = con.execute(q, params).fetchall()
    con.close()
    return [dict(r) for r in rows]


def walk(
    project_id: str,
    start_nid: str,
    relation: str,
    max_hops: int = 2,
) -> list[dict]:
    """BFS walk along a single relation up to max_hops. Returns all nodes reached."""
    seen: set[str] = {start_nid}
    frontier = [start_nid]
    out: list[dict] = []
    for _ in range(max_hops):
        next_frontier: list[str] = []
        for nid in frontier:
            for n in neighbors(project_id, nid, relation=relation, direction="out"):
                if n["node_id"] not in seen:
                    seen.add(n["node_id"])
                    next_frontier.append(n["node_id"])
                    out.append(n)
        frontier = next_frontier
        if not frontier:
            break
    return out


def in_degree(project_id: str, nid: str, relation: str | None = None) -> int:
    con = _connect(project_id)
    if relation:
        row = con.execute(
            "SELECT COUNT(*) FROM graph_edges WHERE to_node=? AND relation=?", (nid, relation)
        ).fetchone()
    else:
        row = con.execute("SELECT COUNT(*) FROM graph_edges WHERE to_node=?", (nid,)).fetchone()
    con.close()
    return row[0]


def hubs(project_id: str, kind: str, relation: str = "cites", top_k: int = 20) -> list[dict]:
    """Top-k nodes of a given kind by in-degree on a relation.

    Useful for 'who are the central papers in this concept graph'.
    """
    con = _connect(project_id)
    rows = con.execute(
        "SELECT n.*, COUNT(e.edge_id) AS degree "
        "FROM graph_nodes n LEFT JOIN graph_edges e ON e.to_node=n.node_id AND e.relation=? "
        "WHERE n.kind=? "
        "GROUP BY n.node_id "
        "ORDER BY degree DESC LIMIT ?",
        (relation, kind, top_k),
    ).fetchall()
    con.close()
    return [dict(r) for r in rows]


def shortest_path(
    project_id: str,
    start: str,
    end: str,
    max_hops: int = 4,
    relation: str | None = None,
) -> list[str] | None:
    """v0.79 — BFS shortest path from `start` to `end` along directed
    edges. Optionally filtered by a single relation.

    Returns the inclusive node-id path (length = number of hops) or
    None if no path exists within `max_hops`. `start == end` returns
    a length-0 path containing just the start.

    Promoted from graph-query-mcp v0.74 — same algorithm, exposed in
    Python so callers don't need to spawn a sub-process.
    """
    from collections import deque
    if start == end:
        return [start]
    con = _connect(project_id)
    try:
        if relation:
            edge_q = (
                "SELECT to_node FROM graph_edges "
                "WHERE from_node=? AND relation=?"
            )
            def _next(n: str) -> list[str]:
                return [r[0] for r in con.execute(edge_q, (n, relation))]
        else:
            edge_q = "SELECT to_node FROM graph_edges WHERE from_node=?"
            def _next(n: str) -> list[str]:
                return [r[0] for r in con.execute(edge_q, (n,))]

        seen: dict[str, str | None] = {start: None}
        q: deque[tuple[str, int]] = deque([(start, 0)])
        while q:
            cur, depth = q.popleft()
            if depth >= max_hops:
                continue
            for nxt in _next(cur):
                if nxt in seen:
                    continue
                seen[nxt] = cur
                if nxt == end:
                    path: list[str] = [end]
                    while seen[path[-1]] is not None:
                        path.append(seen[path[-1]])
                    path.reverse()
                    return path
                q.append((nxt, depth + 1))
    finally:
        con.close()
    return None
