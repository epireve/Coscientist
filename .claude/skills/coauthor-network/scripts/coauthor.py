#!/usr/bin/env python3
"""coauthor-network: read-only coauthor aggregation over project graph.

Edges: `authored-by` is paper → author (from_node=paper:..., to_node=author:...).
So the papers authored by X are rows where to_node=X AND relation='authored-by';
the authors of paper P are rows where from_node=P AND relation='authored-by'.

All errors return dicts with an "error" key — never raise.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lib.cache import cache_root  # noqa: E402


def _db_path(project_id: str) -> Path:
    return cache_root() / "projects" / project_id / "project.db"


def _open(project_id: str) -> sqlite3.Connection | None:
    db = _db_path(project_id)
    if not db.exists():
        return None
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    return con


def _paper_year(canonical_id: str) -> int | None:
    """Best-effort year lookup from paper artifact metadata.json."""
    p = cache_root() / "papers" / canonical_id / "metadata.json"
    if not p.exists():
        return None
    try:
        meta = json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    y = meta.get("year")
    if isinstance(y, int):
        return y
    if isinstance(y, str) and y.isdigit():
        return int(y)
    return None


def _papers_of_author(con: sqlite3.Connection, author_nid: str) -> list[str]:
    """Return list of paper node_ids the author is authored-by source for."""
    try:
        rows = con.execute(
            "SELECT DISTINCT from_node FROM graph_edges "
            "WHERE to_node=? AND relation='authored-by'",
            (author_nid,),
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    return [r[0] for r in rows]


def _authors_of_paper(con: sqlite3.Connection, paper_nid: str) -> list[str]:
    try:
        rows = con.execute(
            "SELECT DISTINCT to_node FROM graph_edges "
            "WHERE from_node=? AND relation='authored-by'",
            (paper_nid,),
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    return [r[0] for r in rows]


def _author_label(con: sqlite3.Connection, author_nid: str) -> str | None:
    try:
        row = con.execute(
            "SELECT label FROM graph_nodes WHERE node_id=? AND kind='author'",
            (author_nid,),
        ).fetchone()
    except sqlite3.OperationalError:
        return None
    return row["label"] if row else None


def _author_exists(con: sqlite3.Connection, author_nid: str) -> bool:
    return _author_label(con, author_nid) is not None


def for_author(project_id: str, author_nid: str) -> dict:
    con = _open(project_id)
    if con is None:
        return {"error": f"no project DB for {project_id}"}
    try:
        if not _author_exists(con, author_nid):
            return {"error": f"author node not found: {author_nid}"}
        my_label = _author_label(con, author_nid) or author_nid
        papers = _papers_of_author(con, author_nid)
        # coauthor_nid -> {shared_papers, paper_ids[], years[]}
        agg: dict[str, dict] = {}
        for p_nid in papers:
            others = [a for a in _authors_of_paper(con, p_nid)
                      if a != author_nid]
            cid = p_nid.split(":", 1)[1] if ":" in p_nid else p_nid
            year = _paper_year(cid)
            for o in others:
                rec = agg.setdefault(o, {
                    "shared_papers": 0,
                    "paper_ids": [],
                    "years": [],
                })
                rec["shared_papers"] += 1
                rec["paper_ids"].append(p_nid)
                if year is not None:
                    rec["years"].append(year)
        # Build output rows
        out = []
        for nid, rec in agg.items():
            label = _author_label(con, nid) or nid
            years = rec["years"]
            yr_min = min(years) if years else None
            yr_max = max(years) if years else None
            out.append({
                "author_nid": nid,
                "label": label,
                "shared_papers": rec["shared_papers"],
                "paper_ids": rec["paper_ids"],
                "year_min": yr_min,
                "year_max": yr_max,
            })
        # Sort: shared_papers DESC, label ASC tiebreak
        out.sort(key=lambda r: (-r["shared_papers"], r["label"]))
        return {
            "project_id": project_id,
            "author_nid": author_nid,
            "author_label": my_label,
            "paper_count": len(papers),
            "coauthors": out,
        }
    finally:
        con.close()


def for_paper(project_id: str, canonical_id: str) -> dict:
    con = _open(project_id)
    if con is None:
        return {"error": f"no project DB for {project_id}"}
    try:
        paper_nid = f"paper:{canonical_id}"
        try:
            row = con.execute(
                "SELECT label FROM graph_nodes WHERE node_id=? AND kind='paper'",
                (paper_nid,),
            ).fetchone()
        except sqlite3.OperationalError:
            row = None
        if not row:
            return {"error": f"paper node not found: {paper_nid}"}
        authors = _authors_of_paper(con, paper_nid)
    finally:
        con.close()
    by_author: dict[str, dict] = {}
    for a in authors:
        sub = for_author(project_id, a)
        if "error" in sub:
            continue
        by_author[a] = {
            "label": sub["author_label"],
            "paper_count": sub["paper_count"],
            "coauthors": sub["coauthors"],
        }
    return {
        "project_id": project_id,
        "canonical_id": canonical_id,
        "paper_nid": paper_nid,
        "authors": authors,
        "by_author": by_author,
    }


def cliques(project_id: str, min_shared: int = 2) -> dict:
    con = _open(project_id)
    if con is None:
        return {"error": f"no project DB for {project_id}"}
    try:
        # Build paper -> [authors] map
        try:
            rows = con.execute(
                "SELECT from_node, to_node FROM graph_edges "
                "WHERE relation='authored-by'"
            ).fetchall()
        except sqlite3.OperationalError:
            rows = []
        paper_authors: dict[str, list[str]] = {}
        for r in rows:
            paper_authors.setdefault(r[0], []).append(r[1])
        # Pair counts: frozenset(a,b) -> shared papers
        pair_counts: dict[frozenset, int] = {}
        # Adjacency for triangle expansion
        adj: dict[str, set[str]] = {}
        for authors in paper_authors.values():
            uniq = list(set(authors))
            for i in range(len(uniq)):
                for j in range(i + 1, len(uniq)):
                    key = frozenset((uniq[i], uniq[j]))
                    pair_counts[key] = pair_counts.get(key, 0) + 1
        # Filter pairs >= threshold
        qualifying_pairs: dict[frozenset, int] = {
            k: v for k, v in pair_counts.items() if v >= min_shared
        }
        for pair in qualifying_pairs:
            a, b = list(pair)
            adj.setdefault(a, set()).add(b)
            adj.setdefault(b, set()).add(a)
        # Triangle expansion: for each qualifying pair (a,b) find c with
        # (a,c) and (b,c) both qualifying.
        seen_triangles: set[frozenset] = set()
        triangles: list[dict] = []
        nodes_sorted = sorted(adj.keys())
        for a in nodes_sorted:
            neighbors_a = adj.get(a, set())
            for b in sorted(neighbors_a):
                if b <= a:
                    continue
                for c in sorted(adj.get(b, set())):
                    if c <= b:
                        continue
                    if c in neighbors_a:
                        tri = frozenset((a, b, c))
                        if tri in seen_triangles:
                            continue
                        seen_triangles.add(tri)
                        # Min shared across the 3 pairs
                        s = min(
                            qualifying_pairs[frozenset((a, b))],
                            qualifying_pairs[frozenset((a, c))],
                            qualifying_pairs[frozenset((b, c))],
                        )
                        labels = [
                            _author_label(con, n) or n for n in (a, b, c)
                        ]
                        triangles.append({
                            "authors": [a, b, c],
                            "labels": labels,
                            "shared_papers": s,
                        })
        # Pairs (size-2 cliques) — return only pairs not subsumed by triangle?
        # Spec says "groups with >= min-shared papers" + triangle expansion;
        # return pairs as size-2 records too for visibility.
        pair_records: list[dict] = []
        for pair, n in qualifying_pairs.items():
            a, b = sorted(pair)
            pair_records.append({
                "authors": [a, b],
                "labels": [
                    _author_label(con, a) or a,
                    _author_label(con, b) or b,
                ],
                "shared_papers": n,
            })
        # Sort triangles + pairs by shared_papers desc, then by labels
        triangles.sort(key=lambda r: (-r["shared_papers"], r["labels"]))
        pair_records.sort(key=lambda r: (-r["shared_papers"], r["labels"]))
        return {
            "project_id": project_id,
            "min_shared": min_shared,
            "triangles": triangles,
            "pairs": pair_records,
        }
    finally:
        con.close()


def _format_text(payload: dict) -> str:
    if "error" in payload:
        return f"ERROR: {payload['error']}"
    lines: list[str] = []
    if "coauthors" in payload and "author_label" in payload:
        lines.append(
            f"Coauthors of {payload['author_label']} "
            f"({payload['author_nid']}, "
            f"{payload['paper_count']} papers):"
        )
        for c in payload["coauthors"]:
            yr = ""
            if c["year_min"] is not None and c["year_max"] is not None:
                yr = f" [{c['year_min']}-{c['year_max']}]"
            lines.append(
                f"  {c['shared_papers']:3d}  {c['label']}  "
                f"({c['author_nid']}){yr}"
            )
        if not payload["coauthors"]:
            lines.append("  (none)")
    elif "by_author" in payload:
        lines.append(
            f"Coauthor map for paper {payload['canonical_id']}:"
        )
        for nid, rec in payload["by_author"].items():
            lines.append(f"  {rec['label']} ({nid})")
            for c in rec["coauthors"][:10]:
                lines.append(
                    f"      {c['shared_papers']:3d}  {c['label']}"
                )
    elif "triangles" in payload:
        lines.append(
            f"Cliques (min_shared={payload['min_shared']}):"
        )
        lines.append(f"  triangles: {len(payload['triangles'])}")
        for t in payload["triangles"]:
            lines.append(
                f"    [{t['shared_papers']}] " + " + ".join(t["labels"])
            )
        lines.append(f"  pairs: {len(payload['pairs'])}")
        for p in payload["pairs"][:50]:
            lines.append(
                f"    [{p['shared_papers']}] " + " + ".join(p["labels"])
            )
    else:
        return json.dumps(payload, indent=2)
    return "\n".join(lines)


def _emit(payload: dict, fmt: str) -> None:
    if fmt == "text":
        print(_format_text(payload))
    else:
        print(json.dumps(payload, indent=2))


def cmd_for_author(args: argparse.Namespace) -> None:
    _emit(for_author(args.project_id, args.author_nid), args.format)


def cmd_for_paper(args: argparse.Namespace) -> None:
    _emit(for_paper(args.project_id, args.canonical_id), args.format)


def cmd_cliques(args: argparse.Namespace) -> None:
    _emit(cliques(args.project_id, args.min_shared), args.format)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Read-only coauthor-network aggregation over project graph.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    pa = sub.add_parser("for-author",
                        help="Coauthors of a specific author")
    pa.add_argument("--project-id", required=True)
    pa.add_argument("--author-nid", required=True,
                    help="e.g. author:doe-j")
    pa.add_argument("--format", choices=["json", "text"], default="json")
    pa.set_defaults(func=cmd_for_author)

    pp = sub.add_parser("for-paper",
                        help="Coauthor map starting from a paper")
    pp.add_argument("--project-id", required=True)
    pp.add_argument("--canonical-id", required=True)
    pp.add_argument("--format", choices=["json", "text"], default="json")
    pp.set_defaults(func=cmd_for_paper)

    pc = sub.add_parser("cliques",
                        help="Coauthor cliques (pairs + triangles)")
    pc.add_argument("--project-id", required=True)
    pc.add_argument("--min-shared", type=int, default=2)
    pc.add_argument("--format", choices=["json", "text"], default="json")
    pc.set_defaults(func=cmd_cliques)

    return p


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
