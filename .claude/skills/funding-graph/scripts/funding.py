#!/usr/bin/env python3
"""funding-graph: read-only aggregation over project graph for funders +
institutions (v0.148 schema v13).

Edges:
  - `funded-by`       : paper       → funder       (from=paper, to=funder)
  - `affiliated-with` : author      → institution  (from=author, to=institution)
  - `authored-by`     : paper       → author       (from=paper, to=author)

All errors return `{error: ...}` dicts — never raises.
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


def _node_label(con: sqlite3.Connection, nid: str, kind: str | None = None) -> str | None:
    try:
        if kind:
            row = con.execute(
                "SELECT label FROM graph_nodes WHERE node_id=? AND kind=?",
                (nid, kind),
            ).fetchone()
        else:
            row = con.execute(
                "SELECT label FROM graph_nodes WHERE node_id=?", (nid,),
            ).fetchone()
    except sqlite3.OperationalError:
        return None
    return row["label"] if row else None


def _node_exists(con: sqlite3.Connection, nid: str, kind: str) -> bool:
    return _node_label(con, nid, kind) is not None


def _grouped_count(con: sqlite3.Connection, relation: str, kind: str) -> list[dict]:
    """Group edges by to_node for given relation; join graph_nodes for label.
    Returns [{node_id, label, paper_count}, ...] sorted desc.
    """
    try:
        rows = con.execute(
            "SELECT n.node_id AS node_id, n.label AS label, "
            "COUNT(DISTINCT e.from_node) AS paper_count "
            "FROM graph_edges e JOIN graph_nodes n ON n.node_id = e.to_node "
            "WHERE e.relation=? AND n.kind=? "
            "GROUP BY n.node_id, n.label",
            (relation, kind),
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    out = [{
        "node_id": r["node_id"],
        "label": r["label"],
        "paper_count": r["paper_count"],
    } for r in rows]
    out.sort(key=lambda x: (-x["paper_count"], x["label"] or ""))
    return out


def papers_by_funder(project_id: str) -> dict:
    con = _open(project_id)
    if con is None:
        return {"error": f"no project DB for {project_id}"}
    try:
        return {
            "project_id": project_id,
            "kind": "funder",
            "funders": _grouped_count(con, "funded-by", "funder"),
        }
    finally:
        con.close()


def papers_by_institution(project_id: str) -> dict:
    """Count distinct papers per institution (papers authored by an author
    affiliated with that institution)."""
    con = _open(project_id)
    if con is None:
        return {"error": f"no project DB for {project_id}"}
    try:
        try:
            rows = con.execute(
                "SELECT inst.node_id AS node_id, inst.label AS label, "
                "COUNT(DISTINCT pa.from_node) AS paper_count "
                "FROM graph_edges aff "
                "JOIN graph_nodes inst ON inst.node_id = aff.to_node "
                "JOIN graph_edges pa ON pa.to_node = aff.from_node "
                "    AND pa.relation = 'authored-by' "
                "WHERE aff.relation='affiliated-with' AND inst.kind='institution' "
                "GROUP BY inst.node_id, inst.label"
            ).fetchall()
        except sqlite3.OperationalError:
            rows = []
        out = [{
            "node_id": r["node_id"],
            "label": r["label"],
            "paper_count": r["paper_count"],
        } for r in rows]
        out.sort(key=lambda x: (-x["paper_count"], x["label"] or ""))
        return {
            "project_id": project_id,
            "kind": "institution",
            "institutions": out,
        }
    finally:
        con.close()


def for_funder(project_id: str, funder_nid: str) -> dict:
    con = _open(project_id)
    if con is None:
        return {"error": f"no project DB for {project_id}"}
    try:
        if not _node_exists(con, funder_nid, "funder"):
            return {"error": f"funder node not found: {funder_nid}"}
        label = _node_label(con, funder_nid, "funder") or funder_nid
        try:
            paper_rows = con.execute(
                "SELECT DISTINCT from_node FROM graph_edges "
                "WHERE to_node=? AND relation='funded-by'",
                (funder_nid,),
            ).fetchall()
        except sqlite3.OperationalError:
            paper_rows = []
        papers: list[dict] = []
        author_set: dict[str, str] = {}
        for r in paper_rows:
            p_nid = r[0]
            p_label = _node_label(con, p_nid, "paper") or p_nid
            try:
                a_rows = con.execute(
                    "SELECT DISTINCT to_node FROM graph_edges "
                    "WHERE from_node=? AND relation='authored-by'",
                    (p_nid,),
                ).fetchall()
            except sqlite3.OperationalError:
                a_rows = []
            authors_here = []
            for ar in a_rows:
                a_nid = ar[0]
                a_label = _node_label(con, a_nid, "author") or a_nid
                authors_here.append({"author_nid": a_nid, "label": a_label})
                author_set[a_nid] = a_label
            papers.append({
                "paper_nid": p_nid,
                "label": p_label,
                "authors": authors_here,
            })
        papers.sort(key=lambda x: (x["label"] or "", x["paper_nid"]))
        authors = [{"author_nid": k, "label": v} for k, v in author_set.items()]
        authors.sort(key=lambda x: (x["label"] or "", x["author_nid"]))
        return {
            "project_id": project_id,
            "funder_nid": funder_nid,
            "funder_label": label,
            "paper_count": len(papers),
            "papers": papers,
            "authors": authors,
        }
    finally:
        con.close()


def for_institution(project_id: str, institution_nid: str) -> dict:
    con = _open(project_id)
    if con is None:
        return {"error": f"no project DB for {project_id}"}
    try:
        if not _node_exists(con, institution_nid, "institution"):
            return {"error": f"institution node not found: {institution_nid}"}
        label = _node_label(con, institution_nid, "institution") or institution_nid
        try:
            author_rows = con.execute(
                "SELECT DISTINCT from_node FROM graph_edges "
                "WHERE to_node=? AND relation='affiliated-with'",
                (institution_nid,),
            ).fetchall()
        except sqlite3.OperationalError:
            author_rows = []
        authors: list[dict] = []
        paper_set: dict[str, str] = {}
        for r in author_rows:
            a_nid = r[0]
            a_label = _node_label(con, a_nid, "author") or a_nid
            try:
                p_rows = con.execute(
                    "SELECT DISTINCT from_node FROM graph_edges "
                    "WHERE to_node=? AND relation='authored-by'",
                    (a_nid,),
                ).fetchall()
            except sqlite3.OperationalError:
                p_rows = []
            papers_here = []
            for pr in p_rows:
                p_nid = pr[0]
                p_label = _node_label(con, p_nid, "paper") or p_nid
                papers_here.append({"paper_nid": p_nid, "label": p_label})
                paper_set[p_nid] = p_label
            authors.append({
                "author_nid": a_nid,
                "label": a_label,
                "papers": papers_here,
            })
        authors.sort(key=lambda x: (x["label"] or "", x["author_nid"]))
        papers = [{"paper_nid": k, "label": v} for k, v in paper_set.items()]
        papers.sort(key=lambda x: (x["label"] or "", x["paper_nid"]))
        return {
            "project_id": project_id,
            "institution_nid": institution_nid,
            "institution_label": label,
            "author_count": len(authors),
            "authors": authors,
            "papers": papers,
        }
    finally:
        con.close()


def dominant_funders(
    project_id: str,
    min_papers: int = 5,
    threshold: float = 0.6,
) -> dict:
    """For each author, compute funder concentration. Flag authors with
    >= min_papers AND top-funder-ratio >= threshold."""
    con = _open(project_id)
    if con is None:
        return {"error": f"no project DB for {project_id}"}
    try:
        # All authored-by edges: paper -> author
        try:
            rows = con.execute(
                "SELECT from_node, to_node FROM graph_edges "
                "WHERE relation='authored-by'"
            ).fetchall()
        except sqlite3.OperationalError:
            rows = []
        author_papers: dict[str, set[str]] = {}
        for r in rows:
            author_papers.setdefault(r[1], set()).add(r[0])

        # All funded-by edges: paper -> funder
        try:
            f_rows = con.execute(
                "SELECT from_node, to_node FROM graph_edges "
                "WHERE relation='funded-by'"
            ).fetchall()
        except sqlite3.OperationalError:
            f_rows = []
        paper_funders: dict[str, list[str]] = {}
        for r in f_rows:
            paper_funders.setdefault(r[0], []).append(r[1])

        flagged: list[dict] = []
        for a_nid, papers in author_papers.items():
            n_total = len(papers)
            if n_total < min_papers:
                continue
            funder_count: dict[str, int] = {}
            for p in papers:
                for f in paper_funders.get(p, []):
                    funder_count[f] = funder_count.get(f, 0) + 1
            if not funder_count:
                continue
            top_f = max(funder_count, key=lambda k: funder_count[k])
            top_n = funder_count[top_f]
            ratio = top_n / n_total
            if ratio < threshold:
                continue
            a_label = _node_label(con, a_nid, "author") or a_nid
            f_label = _node_label(con, top_f, "funder") or top_f
            flagged.append({
                "author_nid": a_nid,
                "author_label": a_label,
                "paper_count": n_total,
                "dominant_funder_nid": top_f,
                "dominant_funder_label": f_label,
                "funder_papers": top_n,
                "ratio": round(ratio, 4),
            })
        flagged.sort(key=lambda x: (-x["ratio"], -x["paper_count"], x["author_label"]))
        return {
            "project_id": project_id,
            "min_papers": min_papers,
            "threshold": threshold,
            "flagged": flagged,
        }
    finally:
        con.close()


def _format_text(payload: dict) -> str:
    if "error" in payload:
        return f"ERROR: {payload['error']}"
    lines: list[str] = []
    if "funders" in payload:
        lines.append(f"Papers by funder ({len(payload['funders'])}):")
        for f in payload["funders"]:
            lines.append(f"  {f['paper_count']:4d}  {f['label']}  ({f['node_id']})")
        if not payload["funders"]:
            lines.append("  (none)")
    elif "institutions" in payload:
        lines.append(f"Papers by institution ({len(payload['institutions'])}):")
        for i in payload["institutions"]:
            lines.append(f"  {i['paper_count']:4d}  {i['label']}  ({i['node_id']})")
        if not payload["institutions"]:
            lines.append("  (none)")
    elif "funder_label" in payload:
        lines.append(
            f"Funder {payload['funder_label']} ({payload['funder_nid']}): "
            f"{payload['paper_count']} papers, {len(payload['authors'])} authors"
        )
        for p in payload["papers"]:
            lines.append(f"  - {p['label']} ({p['paper_nid']})")
            for a in p["authors"]:
                lines.append(f"      · {a['label']}")
    elif "institution_label" in payload:
        lines.append(
            f"Institution {payload['institution_label']} ({payload['institution_nid']}): "
            f"{payload['author_count']} authors, {len(payload['papers'])} papers"
        )
        for a in payload["authors"]:
            lines.append(f"  - {a['label']} ({a['author_nid']})")
            for p in a["papers"]:
                lines.append(f"      · {p['label']}")
    elif "flagged" in payload:
        lines.append(
            f"Dominant funders (min_papers={payload['min_papers']}, "
            f"threshold={payload['threshold']}): {len(payload['flagged'])} flagged"
        )
        for f in payload["flagged"]:
            lines.append(
                f"  {f['ratio']:.2f}  {f['author_label']}  "
                f"({f['funder_papers']}/{f['paper_count']} from "
                f"{f['dominant_funder_label']})"
            )
        if not payload["flagged"]:
            lines.append("  (none)")
    else:
        return json.dumps(payload, indent=2)
    return "\n".join(lines)


def _emit(payload: dict, fmt: str) -> None:
    if fmt == "text":
        print(_format_text(payload))
    else:
        print(json.dumps(payload, indent=2))


def cmd_papers_by_funder(args: argparse.Namespace) -> None:
    _emit(papers_by_funder(args.project_id), args.format)


def cmd_papers_by_institution(args: argparse.Namespace) -> None:
    _emit(papers_by_institution(args.project_id), args.format)


def cmd_for_funder(args: argparse.Namespace) -> None:
    _emit(for_funder(args.project_id, args.funder_nid), args.format)


def cmd_for_institution(args: argparse.Namespace) -> None:
    _emit(for_institution(args.project_id, args.institution_nid), args.format)


def cmd_dominant_funders(args: argparse.Namespace) -> None:
    _emit(
        dominant_funders(args.project_id, args.min_papers, args.threshold),
        args.format,
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Read-only funding aggregation over project graph.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    pf = sub.add_parser("papers-by-funder", help="Papers per funder, sorted desc")
    pf.add_argument("--project-id", required=True)
    pf.add_argument("--format", choices=["json", "text"], default="json")
    pf.set_defaults(func=cmd_papers_by_funder)

    pi = sub.add_parser("papers-by-institution",
                        help="Papers per institution, sorted desc")
    pi.add_argument("--project-id", required=True)
    pi.add_argument("--format", choices=["json", "text"], default="json")
    pi.set_defaults(func=cmd_papers_by_institution)

    ff = sub.add_parser("for-funder",
                        help="Papers + authors funded by a specific funder")
    ff.add_argument("--project-id", required=True)
    ff.add_argument("--funder-nid", required=True, help="e.g. funder:nih")
    ff.add_argument("--format", choices=["json", "text"], default="json")
    ff.set_defaults(func=cmd_for_funder)

    fi = sub.add_parser("for-institution",
                        help="Authors + papers at a specific institution")
    fi.add_argument("--project-id", required=True)
    fi.add_argument("--institution-nid", required=True,
                    help="e.g. institution:mit")
    fi.add_argument("--format", choices=["json", "text"], default="json")
    fi.set_defaults(func=cmd_for_institution)

    df = sub.add_parser("dominant-funders",
                        help="Authors where one funder dominates")
    df.add_argument("--project-id", required=True)
    df.add_argument("--min-papers", type=int, default=5)
    df.add_argument("--threshold", type=float, default=0.6)
    df.add_argument("--format", choices=["json", "text"], default="json")
    df.set_defaults(func=cmd_dominant_funders)

    return p


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
