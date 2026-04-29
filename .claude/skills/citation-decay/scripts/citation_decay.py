#!/usr/bin/env python3
"""citation-decay: read-only citation-freshness aggregation.

Edges:
  - `cites` : citer_paper → target_paper (from=citer, to=target)

Years come from each paper's `metadata.json["year"]` (best-effort).

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

DEFAULT_CURRENT_YEAR = 2026


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


def _cid_from_nid(nid: str) -> str:
    return nid.split(":", 1)[1] if ":" in nid else nid


def _paper_exists(con: sqlite3.Connection, paper_nid: str) -> bool:
    try:
        row = con.execute(
            "SELECT 1 FROM graph_nodes WHERE node_id=? AND kind='paper'",
            (paper_nid,),
        ).fetchone()
    except sqlite3.OperationalError:
        return False
    return row is not None


def _citers_of(con: sqlite3.Connection, paper_nid: str) -> list[str]:
    """Return list of citer node_ids citing the target paper."""
    try:
        rows = con.execute(
            "SELECT DISTINCT from_node FROM graph_edges "
            "WHERE to_node=? AND relation='cites'",
            (paper_nid,),
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    return [r[0] for r in rows]


def _all_paper_nodes(con: sqlite3.Connection) -> list[str]:
    try:
        rows = con.execute(
            "SELECT node_id FROM graph_nodes WHERE kind='paper'"
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    return [r[0] for r in rows]


def for_paper(
    project_id: str,
    canonical_id: str,
    decay_years: int = 5,
    current_year: int = DEFAULT_CURRENT_YEAR,
) -> dict:
    con = _open(project_id)
    if con is None:
        return {"error": f"no project DB for {project_id}"}
    try:
        paper_nid = f"paper:{canonical_id}"
        if not _paper_exists(con, paper_nid):
            return {"error": f"paper node not found: {paper_nid}"}
        target_year = _paper_year(canonical_id)
        if target_year is None:
            return {"error": f"no year in metadata.json for {canonical_id}"}
        citers = _citers_of(con, paper_nid)
        year_buckets: dict[int, int] = {}
        for c_nid in citers:
            c_cid = _cid_from_nid(c_nid)
            cy = _paper_year(c_cid)
            if cy is None:
                continue
            year_buckets[cy] = year_buckets.get(cy, 0) + 1
        most_recent = max(year_buckets) if year_buckets else None
        cutoff = current_year - decay_years
        recent_window_count = sum(
            n for y, n in year_buckets.items() if y >= cutoff
        )
        return {
            "project_id": project_id,
            "canonical_id": canonical_id,
            "paper_nid": paper_nid,
            "paper_year": target_year,
            "current_year": current_year,
            "decay_years": decay_years,
            "total_citations": len(citers),
            "year_buckets": dict(sorted(year_buckets.items())),
            "most_recent_citer_year": most_recent,
            "recent_window_count": recent_window_count,
        }
    finally:
        con.close()


def velocity(
    project_id: str,
    top_n: int = 20,
    current_year: int = DEFAULT_CURRENT_YEAR,
) -> dict:
    con = _open(project_id)
    if con is None:
        return {"error": f"no project DB for {project_id}"}
    try:
        paper_nids = _all_paper_nodes(con)
        rows: list[dict] = []
        for nid in paper_nids:
            cid = _cid_from_nid(nid)
            py = _paper_year(cid)
            if py is None:
                continue
            citers = _citers_of(con, nid)
            n = len(citers)
            age = max(1, current_year - py)
            v = n / age
            rows.append({
                "paper_nid": nid,
                "canonical_id": cid,
                "paper_year": py,
                "total_citations": n,
                "age_years": age,
                "velocity": round(v, 4),
            })
        rows.sort(key=lambda r: (-r["velocity"], -r["total_citations"],
                                 r["canonical_id"]))
        rows = rows[:top_n]
        return {
            "project_id": project_id,
            "current_year": current_year,
            "top_n": top_n,
            "papers": rows,
        }
    finally:
        con.close()


def stale(
    project_id: str,
    min_citations: int = 5,
    decay_years: int = 5,
    current_year: int = DEFAULT_CURRENT_YEAR,
) -> dict:
    con = _open(project_id)
    if con is None:
        return {"error": f"no project DB for {project_id}"}
    try:
        paper_nids = _all_paper_nodes(con)
        cutoff = current_year - decay_years
        flagged: list[dict] = []
        for nid in paper_nids:
            cid = _cid_from_nid(nid)
            py = _paper_year(cid)
            if py is None:
                continue
            citers = _citers_of(con, nid)
            n = len(citers)
            if n < min_citations:
                continue
            most_recent: int | None = None
            for c_nid in citers:
                cy = _paper_year(_cid_from_nid(c_nid))
                if cy is None:
                    continue
                if most_recent is None or cy > most_recent:
                    most_recent = cy
            # Stale: zero recent citers (most_recent missing OR < cutoff)
            if most_recent is not None and most_recent >= cutoff:
                continue
            flagged.append({
                "paper_nid": nid,
                "canonical_id": cid,
                "paper_year": py,
                "total_citations": n,
                "most_recent_citer_year": most_recent,
            })
        flagged.sort(key=lambda r: (-r["total_citations"], r["canonical_id"]))
        return {
            "project_id": project_id,
            "min_citations": min_citations,
            "decay_years": decay_years,
            "current_year": current_year,
            "stale": flagged,
        }
    finally:
        con.close()


def _format_text(payload: dict) -> str:
    if "error" in payload:
        return f"ERROR: {payload['error']}"
    lines: list[str] = []
    if "year_buckets" in payload:
        lines.append(
            f"Citations of {payload['canonical_id']} "
            f"(year={payload['paper_year']}): "
            f"{payload['total_citations']} total, "
            f"{payload['recent_window_count']} in last "
            f"{payload['decay_years']}y"
        )
        mr = payload["most_recent_citer_year"]
        lines.append(
            f"  most recent citer year: {mr if mr is not None else '(none)'}"
        )
        for y, n in payload["year_buckets"].items():
            lines.append(f"  {y}: {n}")
        if not payload["year_buckets"]:
            lines.append("  (no citers with known year)")
    elif "papers" in payload:
        lines.append(
            f"Citation velocity (top {payload['top_n']}, "
            f"current_year={payload['current_year']}):"
        )
        for r in payload["papers"]:
            lines.append(
                f"  {r['velocity']:6.2f}/yr  "
                f"{r['total_citations']:4d} cites / {r['age_years']:3d}y  "
                f"{r['canonical_id']}"
            )
        if not payload["papers"]:
            lines.append("  (no papers with known year)")
    elif "stale" in payload:
        lines.append(
            f"Stale papers (min_citations={payload['min_citations']}, "
            f"decay_years={payload['decay_years']}, "
            f"current_year={payload['current_year']}): "
            f"{len(payload['stale'])} flagged"
        )
        for r in payload["stale"]:
            mr = r["most_recent_citer_year"]
            mr_s = str(mr) if mr is not None else "(none)"
            lines.append(
                f"  {r['total_citations']:4d}  {r['canonical_id']} "
                f"(year={r['paper_year']}, last cite={mr_s})"
            )
        if not payload["stale"]:
            lines.append("  (none)")
    else:
        return json.dumps(payload, indent=2)
    return "\n".join(lines)


def _emit(payload: dict, fmt: str) -> None:
    if fmt == "text":
        print(_format_text(payload))
    else:
        print(json.dumps(payload, indent=2))


def cmd_for_paper(args: argparse.Namespace) -> None:
    _emit(for_paper(args.project_id, args.canonical_id,
                    args.decay_years, args.current_year), args.format)


def cmd_velocity(args: argparse.Namespace) -> None:
    _emit(velocity(args.project_id, args.top_n, args.current_year),
          args.format)


def cmd_stale(args: argparse.Namespace) -> None:
    _emit(stale(args.project_id, args.min_citations, args.decay_years,
                args.current_year), args.format)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Read-only citation-freshness aggregation.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    pf = sub.add_parser("for-paper",
                        help="Citation freshness for one paper")
    pf.add_argument("--project-id", required=True)
    pf.add_argument("--canonical-id", required=True)
    pf.add_argument("--decay-years", type=int, default=5)
    pf.add_argument("--current-year", type=int, default=DEFAULT_CURRENT_YEAR)
    pf.add_argument("--format", choices=["json", "text"], default="json")
    pf.set_defaults(func=cmd_for_paper)

    pv = sub.add_parser("velocity",
                        help="Papers ranked by citations/year")
    pv.add_argument("--project-id", required=True)
    pv.add_argument("--top-n", type=int, default=20)
    pv.add_argument("--current-year", type=int, default=DEFAULT_CURRENT_YEAR)
    pv.add_argument("--format", choices=["json", "text"], default="json")
    pv.set_defaults(func=cmd_velocity)

    ps = sub.add_parser("stale",
                        help="High-citation papers with no recent citers")
    ps.add_argument("--project-id", required=True)
    ps.add_argument("--min-citations", type=int, default=5)
    ps.add_argument("--decay-years", type=int, default=5)
    ps.add_argument("--current-year", type=int, default=DEFAULT_CURRENT_YEAR)
    ps.add_argument("--format", choices=["json", "text"], default="json")
    ps.set_defaults(func=cmd_stale)

    return p


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
