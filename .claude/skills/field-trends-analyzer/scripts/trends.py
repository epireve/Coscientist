#!/usr/bin/env python3
"""field-trends-analyzer: aggregations over project graph (read-only)."""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lib.cache import cache_root  # noqa: E402


def _db_path(project_id: str) -> Path:
    return cache_root() / "projects" / project_id / "project.db"


def _open(project_id: str) -> sqlite3.Connection:
    db = _db_path(project_id)
    if not db.exists():
        raise SystemExit(f"no project DB at {db}")
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    return con


def cmd_concepts(args: argparse.Namespace) -> None:
    con = _open(args.project_id)
    try:
        try:
            rows = con.execute("""
                SELECT n.node_id, n.label,
                       COUNT(DISTINCT e.from_node) AS paper_count
                FROM graph_nodes n
                LEFT JOIN graph_edges e
                  ON e.to_node = n.node_id AND e.relation = 'about'
                WHERE n.kind = 'concept'
                GROUP BY n.node_id, n.label
                ORDER BY paper_count DESC
                LIMIT ?
            """, (args.top,)).fetchall()
        except sqlite3.OperationalError:
            rows = []
        out = [{"concept": r["label"], "node_id": r["node_id"],
                "paper_count": r["paper_count"]} for r in rows]
    finally:
        con.close()
    print(json.dumps({
        "project_id": args.project_id,
        "top": args.top,
        "concepts": out,
    }, indent=2))


def cmd_papers(args: argparse.Namespace) -> None:
    con = _open(args.project_id)
    try:
        try:
            rows = con.execute("""
                SELECT n.node_id, n.label,
                       COUNT(e.from_node) AS in_degree
                FROM graph_nodes n
                LEFT JOIN graph_edges e
                  ON e.to_node = n.node_id AND e.relation = 'cites'
                WHERE n.kind = 'paper'
                GROUP BY n.node_id, n.label
                ORDER BY in_degree DESC
                LIMIT ?
            """, (args.top,)).fetchall()
        except sqlite3.OperationalError:
            rows = []
        out = [{"label": r["label"], "node_id": r["node_id"],
                "in_degree": r["in_degree"]} for r in rows]
    finally:
        con.close()
    print(json.dumps({
        "project_id": args.project_id,
        "top": args.top,
        "papers": out,
    }, indent=2))


def cmd_authors(args: argparse.Namespace) -> None:
    con = _open(args.project_id)
    try:
        try:
            rows = con.execute("""
                SELECT n.node_id, n.label,
                       COUNT(e.from_node) AS paper_count
                FROM graph_nodes n
                LEFT JOIN graph_edges e
                  ON e.to_node = n.node_id AND e.relation = 'authored-by'
                WHERE n.kind = 'author'
                GROUP BY n.node_id, n.label
                ORDER BY paper_count DESC
                LIMIT ?
            """, (args.top,)).fetchall()
        except sqlite3.OperationalError:
            rows = []
        out = [{"author": r["label"], "node_id": r["node_id"],
                "paper_count": r["paper_count"]} for r in rows]
    finally:
        con.close()
    print(json.dumps({
        "project_id": args.project_id,
        "top": args.top,
        "authors": out,
    }, indent=2))


def cmd_momentum(args: argparse.Namespace) -> None:
    con = _open(args.project_id)
    now = datetime.now(UTC)
    recent_cutoff = (now - timedelta(days=args.window_recent)).isoformat()
    past_cutoff = (now - timedelta(days=args.window_past)).isoformat()

    out = []
    try:
        # All concepts and their related-paper creation timestamps
        try:
            concepts = con.execute("""
                SELECT node_id, label
                FROM graph_nodes
                WHERE kind = 'concept'
            """).fetchall()
        except sqlite3.OperationalError:
            concepts = []
        for c in concepts:
            # Papers connected via 'about' edge → look up paper node created_at
            try:
                rows = con.execute("""
                    SELECT n.created_at AS ts
                    FROM graph_edges e
                    JOIN graph_nodes n ON n.node_id = e.from_node
                    WHERE e.to_node = ? AND e.relation = 'about'
                      AND n.kind = 'paper'
                """, (c["node_id"],)).fetchall()
            except sqlite3.OperationalError:
                rows = []
            recent_count = sum(1 for r in rows if r["ts"] and r["ts"] >= recent_cutoff)
            past_count = sum(1 for r in rows
                             if r["ts"] and past_cutoff <= r["ts"] < recent_cutoff)
            total = len(rows)
            if total == 0:
                continue
            verdict = "plateau"
            if recent_count > past_count * 1.5 and recent_count >= 2:
                verdict = "rising"
            elif recent_count < past_count * 0.5 and past_count >= 2:
                verdict = "declining"
            out.append({
                "concept": c["label"],
                "node_id": c["node_id"],
                "recent_count": recent_count,
                "past_count": past_count,
                "total_count": total,
                "verdict": verdict,
            })
    finally:
        con.close()

    out.sort(key=lambda x: -x["recent_count"])
    out = out[:args.top]
    print(json.dumps({
        "project_id": args.project_id,
        "window_recent_days": args.window_recent,
        "window_past_days": args.window_past,
        "concepts": out,
    }, indent=2))


def cmd_summary(args: argparse.Namespace) -> None:
    """Combined view: top concepts + top papers + top authors + total counts."""
    con = _open(args.project_id)
    counts = {}
    try:
        for kind in ("paper", "concept", "author", "manuscript"):
            try:
                row = con.execute(
                    "SELECT COUNT(*) AS c FROM graph_nodes WHERE kind = ?",
                    (kind,),
                ).fetchone()
                counts[kind] = row["c"] if row else 0
            except sqlite3.OperationalError:
                counts[kind] = 0
        try:
            edge_row = con.execute(
                "SELECT COUNT(*) AS c FROM graph_edges"
            ).fetchone()
            edge_count = edge_row["c"] if edge_row else 0
        except sqlite3.OperationalError:
            edge_count = 0
    finally:
        con.close()

    print(json.dumps({
        "project_id": args.project_id,
        "node_counts": counts,
        "edge_count": edge_count,
    }, indent=2))


def main() -> None:
    p = argparse.ArgumentParser(description="Project graph trend analysis (read-only).")
    sub = p.add_subparsers(dest="cmd", required=True)

    pc = sub.add_parser("concepts")
    pc.add_argument("--project-id", required=True)
    pc.add_argument("--top", type=int, default=20)
    pc.set_defaults(func=cmd_concepts)

    pp = sub.add_parser("papers")
    pp.add_argument("--project-id", required=True)
    pp.add_argument("--top", type=int, default=20)
    pp.set_defaults(func=cmd_papers)

    pa = sub.add_parser("authors")
    pa.add_argument("--project-id", required=True)
    pa.add_argument("--top", type=int, default=20)
    pa.set_defaults(func=cmd_authors)

    pm = sub.add_parser("momentum")
    pm.add_argument("--project-id", required=True)
    pm.add_argument("--window-recent", type=int, default=90)
    pm.add_argument("--window-past", type=int, default=365)
    pm.add_argument("--top", type=int, default=20)
    pm.set_defaults(func=cmd_momentum)

    ps = sub.add_parser("summary")
    ps.add_argument("--project-id", required=True)
    ps.set_defaults(func=cmd_summary)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
