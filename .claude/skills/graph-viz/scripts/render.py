#!/usr/bin/env python3
"""graph-viz: render the project graph as a mermaid markdown block.

Read-only. Pulls nodes + edges from the per-project SQLite DB and
hands them to lib.graph_viz.render_mermaid().
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

# Repo-root resolution (works for both repo + plugin install layouts).
_HERE = Path(__file__).resolve()
for parent in (_HERE.parents[3], _HERE.parents[4]):
    if (parent / "lib" / "graph_viz.py").exists():
        if str(parent) not in sys.path:
            sys.path.insert(0, str(parent))
        break

from lib import graph_viz  # noqa: E402
from lib.project import project_db_path  # noqa: E402


def _load_graph(project_id: str, kind: str | None = None) -> tuple[list[dict], list[dict]]:
    db = project_db_path(project_id)
    if not db.exists():
        raise SystemExit(f"no project DB at {db}")
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    if kind:
        node_rows = con.execute(
            "SELECT * FROM graph_nodes WHERE kind=?", (kind,)
        ).fetchall()
    else:
        node_rows = con.execute("SELECT * FROM graph_nodes").fetchall()
    nodes = [dict(r) for r in node_rows]
    keep = {n["node_id"] for n in nodes}

    edge_rows = con.execute("SELECT * FROM graph_edges").fetchall()
    edges = [dict(r) for r in edge_rows if r["from_node"] in keep and r["to_node"] in keep]

    # Annotate in-degree for ranking.
    in_deg: dict[str, int] = {}
    for e in edges:
        in_deg[e["to_node"]] = in_deg.get(e["to_node"], 0) + 1
    for n in nodes:
        n["in_degree"] = in_deg.get(n["node_id"], 0)

    con.close()
    return nodes, edges


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--project-id", required=True)
    p.add_argument("--root", help="node_id (e.g. concept:foo) to center subgraph on")
    p.add_argument(
        "--direction",
        choices=["cites", "cited-by"],
        help="for paper lineage: forward (cites) or backward (cited-by)",
    )
    p.add_argument("--depth", type=int, default=2)
    p.add_argument(
        "--kind",
        choices=["paper", "concept", "author", "manuscript"],
        help="restrict node kinds",
    )
    p.add_argument("--max-nodes", type=int, default=50)
    p.add_argument("--hide-labels-above", type=int, default=20)
    p.add_argument("--out", type=str, help="write to file instead of stdout")
    args = p.parse_args()

    nodes, edges = _load_graph(args.project_id, kind=args.kind)

    if args.root and args.direction:
        # Paper-lineage mode.
        cid = args.root
        text = graph_viz.render_paper_lineage(
            nodes, edges, cid,
            direction=args.direction,
            depth=args.depth,
            max_nodes=args.max_nodes,
            hide_labels_above=args.hide_labels_above,
        )
    elif args.root:
        # Generic BFS subgraph.
        text = graph_viz.render_concept_subgraph(
            nodes, edges, args.root,
            depth=args.depth,
            max_nodes=args.max_nodes,
            hide_labels_above=args.hide_labels_above,
        )
    else:
        text = graph_viz.render_mermaid(
            nodes, edges,
            max_nodes=args.max_nodes,
            hide_labels_above=args.hide_labels_above,
        )

    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)


if __name__ == "__main__":
    main()
