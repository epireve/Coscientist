#!/usr/bin/env python3
"""graph-query: read-only CLI traversal over a project's graph.

Surfaces lib/graph.py primitives (walk, neighbors, in_degree, hubs) plus
shortest-path so agents can answer common graph questions without SQL.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import deque
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lib import graph  # noqa: E402
from lib.project import project_db_path  # noqa: E402


def _project_db(project_id: str) -> Path:
    return project_db_path(project_id)


def _ensure_project(project_id: str) -> None:
    db = _project_db(project_id)
    if not db.exists():
        raise SystemExit(f"no project DB at {db}")


def cmd_expand_citations(args: argparse.Namespace) -> dict:
    _ensure_project(args.project_id)
    start = args.node_id or graph.node_id("paper", args.canonical_id)
    nodes = graph.walk(args.project_id, start, args.relation, args.depth)
    return {
        "start": start,
        "relation": args.relation,
        "depth": args.depth,
        "count": len(nodes),
        "nodes": nodes,
    }


def cmd_in_degree(args: argparse.Namespace) -> dict:
    _ensure_project(args.project_id)
    nid = args.node_id or graph.node_id("paper", args.canonical_id)
    deg = graph.in_degree(args.project_id, nid, relation=args.relation)
    return {
        "node_id": nid,
        "relation": args.relation,
        "in_degree": deg,
    }


def cmd_hubs(args: argparse.Namespace) -> dict:
    _ensure_project(args.project_id)
    rows = graph.hubs(args.project_id, args.kind, args.relation, args.top)
    return {
        "kind": args.kind,
        "relation": args.relation,
        "top": args.top,
        "hubs": rows,
    }


def cmd_neighbors(args: argparse.Namespace) -> dict:
    _ensure_project(args.project_id)
    rows = graph.neighbors(
        args.project_id, args.node_id,
        relation=args.relation, direction=args.direction,
    )
    return {
        "node_id": args.node_id,
        "relation": args.relation,
        "direction": args.direction,
        "count": len(rows),
        "neighbors": rows,
    }


def _bfs_path(project_id: str, src: str, dst: str,
              max_hops: int) -> list[str] | None:
    """Find shortest undirected path src→dst over any relation, max_hops."""
    db = _project_db(project_id)
    con = sqlite3.connect(db)
    visited: dict[str, str | None] = {src: None}
    q: deque[tuple[str, int]] = deque([(src, 0)])
    while q:
        nid, hops = q.popleft()
        if nid == dst:
            # Reconstruct path
            path = [nid]
            while visited[path[-1]] is not None:
                path.append(visited[path[-1]])  # type: ignore
            con.close()
            return list(reversed(path))
        if hops >= max_hops:
            continue
        rows = con.execute(
            "SELECT from_node, to_node FROM graph_edges "
            "WHERE from_node=? OR to_node=?", (nid, nid),
        ).fetchall()
        for f, t in rows:
            other = t if f == nid else f
            if other not in visited:
                visited[other] = nid
                q.append((other, hops + 1))
    con.close()
    return None


def cmd_concept_path(args: argparse.Namespace) -> dict:
    _ensure_project(args.project_id)
    src = graph.node_id("paper", getattr(args, "from_"))
    dst = graph.node_id("paper", args.to)
    path = _bfs_path(args.project_id, src, dst, args.max_hops)
    return {
        "from": src,
        "to": dst,
        "max_hops": args.max_hops,
        "path": path,
        "found": path is not None,
        "length": (len(path) - 1) if path else None,
    }


def cmd_author_cluster(args: argparse.Namespace) -> dict:
    _ensure_project(args.project_id)
    nid = graph.node_id("author", args.s2_id)
    # 1-hop neighborhood gives co-authors via shared papers.
    # Implement: papers authored-by this author, then authors of those papers.
    db = _project_db(args.project_id)
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    # Papers authored by start author
    papers = [r["from_node"] for r in con.execute(
        "SELECT from_node FROM graph_edges "
        "WHERE to_node=? AND relation='authored-by'", (nid,),
    )]
    # Co-authors of those papers
    co_authors: set[str] = set()
    for p in papers:
        for r in con.execute(
            "SELECT to_node FROM graph_edges "
            "WHERE from_node=? AND relation='authored-by'", (p,),
        ):
            if r["to_node"] != nid:
                co_authors.add(r["to_node"])
    out_authors: list[dict] = []
    for a_nid in co_authors:
        row = con.execute(
            "SELECT * FROM graph_nodes WHERE node_id=?", (a_nid,),
        ).fetchone()
        if row:
            out_authors.append(dict(row))
    con.close()
    return {
        "author": nid,
        "depth": 1,
        "papers_authored": len(papers),
        "co_authors": out_authors,
        "co_author_count": len(out_authors),
    }


def _to_md(out: dict, cmd: str) -> str:
    lines = [f"# graph-query {cmd}"]
    if cmd == "expand-citations":
        lines += [f"- start: `{out['start']}`",
                  f"- relation: `{out['relation']}` (depth {out['depth']})",
                  f"- reached: **{out['count']}** nodes"]
        for n in out["nodes"][:30]:
            lines.append(f"  - `{n['node_id']}` — {n.get('label') or ''}")
    elif cmd == "in-degree":
        lines += [f"- node: `{out['node_id']}`",
                  f"- relation: `{out['relation']}`",
                  f"- in-degree: **{out['in_degree']}**"]
    elif cmd == "hubs":
        lines += [f"- kind: `{out['kind']}` "
                  f"(top {out['top']} by `{out['relation']}` in-degree)"]
        for h in out["hubs"]:
            lines.append(
                f"  - `{h['node_id']}` — degree={h.get('degree', 0)}"
            )
    elif cmd == "neighbors":
        lines += [f"- node: `{out['node_id']}` "
                  f"({out['direction']} via `{out['relation']}`)",
                  f"- count: **{out['count']}**"]
        for n in out["neighbors"][:30]:
            lines.append(f"  - `{n['node_id']}`")
    elif cmd == "concept-path":
        if out["found"]:
            lines += [f"- found path of length {out['length']}:"]
            for nid in out["path"]:
                lines.append(f"  → `{nid}`")
        else:
            lines.append(
                f"- no path within {out['max_hops']} hops "
                f"between {out['from']} and {out['to']}"
            )
    elif cmd == "author-cluster":
        lines += [f"- author: `{out['author']}`",
                  f"- papers authored: {out['papers_authored']}",
                  f"- co-authors: **{out['co_author_count']}**"]
        for a in out["co_authors"][:30]:
            lines.append(
                f"  - `{a['node_id']}` — {a.get('label') or ''}"
            )
    return "\n".join(lines) + "\n"


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--format", choices=["json", "md"], default="json")
    sub = p.add_subparsers(dest="cmd", required=True)

    e = sub.add_parser("expand-citations")
    e.add_argument("--project-id", required=True)
    g = e.add_mutually_exclusive_group(required=True)
    g.add_argument("--canonical-id")
    g.add_argument("--node-id")
    e.add_argument("--depth", type=int, default=2)
    e.add_argument("--relation", default="cites")
    e.set_defaults(func=cmd_expand_citations)

    i = sub.add_parser("in-degree")
    i.add_argument("--project-id", required=True)
    gi = i.add_mutually_exclusive_group(required=True)
    gi.add_argument("--canonical-id")
    gi.add_argument("--node-id")
    i.add_argument("--relation", default="cites")
    i.set_defaults(func=cmd_in_degree)

    h = sub.add_parser("hubs")
    h.add_argument("--project-id", required=True)
    h.add_argument("--kind", default="paper")
    h.add_argument("--relation", default="cites")
    h.add_argument("--top", type=int, default=20)
    h.set_defaults(func=cmd_hubs)

    n = sub.add_parser("neighbors")
    n.add_argument("--project-id", required=True)
    n.add_argument("--node-id", required=True)
    n.add_argument("--relation", default=None)
    n.add_argument("--direction", choices=["out", "in", "both"],
                    default="out")
    n.set_defaults(func=cmd_neighbors)

    c = sub.add_parser("concept-path")
    c.add_argument("--project-id", required=True)
    c.add_argument("--from", dest="from_", required=True)
    c.add_argument("--to", required=True)
    c.add_argument("--max-hops", type=int, default=4)
    c.set_defaults(func=cmd_concept_path)

    a = sub.add_parser("author-cluster")
    a.add_argument("--project-id", required=True)
    a.add_argument("--s2-id", required=True)
    a.add_argument("--depth", type=int, default=1)
    a.set_defaults(func=cmd_author_cluster)

    args = p.parse_args()
    out = args.func(args)
    if args.format == "md":
        sys.stdout.write(_to_md(out, args.cmd))
    else:
        sys.stdout.write(json.dumps(out, indent=2, default=str) + "\n")


if __name__ == "__main__":
    main()
