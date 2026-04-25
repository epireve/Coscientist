#!/usr/bin/env python3
"""cross-project-memory: keyword search across every project DB."""

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

VALID_KINDS = {"papers", "concepts", "manuscripts", "journal"}


def _project_dbs() -> list[tuple[str, Path]]:
    base = cache_root() / "projects"
    if not base.exists():
        return []
    return [
        (p.name, p / "project.db")
        for p in sorted(base.iterdir())
        if (p / "project.db").exists()
    ]


def _project_name(con: sqlite3.Connection, pid: str) -> str:
    row = con.execute(
        "SELECT name FROM projects WHERE project_id=?", (pid,)
    ).fetchone()
    return row[0] if row else pid


def _search_papers(con: sqlite3.Connection, pid: str, query: str, limit: int) -> list[dict]:
    """Match paper artifacts referenced by this project (via artifact_index)."""
    rows = con.execute(
        "SELECT artifact_id FROM artifact_index "
        "WHERE project_id=? AND kind='paper'", (pid,),
    ).fetchall()
    hits: list[dict] = []
    qlow = query.lower()
    for (cid,) in rows:
        meta_path = cache_root() / "papers" / cid / "metadata.json"
        if not meta_path.exists():
            continue
        try:
            meta = json.loads(meta_path.read_text())
        except json.JSONDecodeError:
            continue
        title = (meta.get("title") or "").lower()
        abstract = (meta.get("abstract") or "").lower()
        if qlow in title or qlow in abstract:
            hits.append({
                "kind": "paper",
                "project_id": pid,
                "canonical_id": cid,
                "title": meta.get("title"),
                "year": meta.get("year"),
                "matched_in": "title" if qlow in title else "abstract",
            })
            if len(hits) >= limit:
                break
    return hits


def _search_concepts(con: sqlite3.Connection, pid: str, query: str, limit: int) -> list[dict]:
    rows = con.execute(
        "SELECT node_id, label, data_json FROM graph_nodes "
        "WHERE kind='concept' AND lower(label) LIKE ? LIMIT ?",
        (f"%{query.lower()}%", limit),
    ).fetchall()
    return [
        {"kind": "concept", "project_id": pid, "node_id": nid, "label": label}
        for nid, label, _ in rows
    ]


def _search_manuscripts(con: sqlite3.Connection, pid: str, query: str, limit: int) -> list[dict]:
    rows = con.execute(
        "SELECT manuscript_id, claim_id, text FROM manuscript_claims "
        "WHERE lower(text) LIKE ? LIMIT ?",
        (f"%{query.lower()}%", limit),
    ).fetchall()
    return [
        {"kind": "manuscript-claim", "project_id": pid,
         "manuscript_id": mid, "claim_id": cid,
         "snippet": text[:200] + ("..." if len(text) > 200 else "")}
        for mid, cid, text in rows
    ]


def _search_journal(con: sqlite3.Connection, pid: str, query: str, limit: int) -> list[dict]:
    rows = con.execute(
        "SELECT entry_id, entry_date, body FROM journal_entries "
        "WHERE project_id=? AND lower(body) LIKE ? "
        "ORDER BY entry_date DESC LIMIT ?",
        (pid, f"%{query.lower()}%", limit),
    ).fetchall()
    return [
        {"kind": "journal-entry", "project_id": pid,
         "entry_id": eid, "entry_date": date,
         "snippet": body[:200] + ("..." if len(body) > 200 else "")}
        for eid, date, body in rows
    ]


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--query", required=True)
    p.add_argument("--kinds", default="papers,concepts,manuscripts,journal")
    p.add_argument("--limit", type=int, default=50)
    args = p.parse_args()

    if not args.query.strip():
        raise SystemExit("empty query")

    requested = {k.strip() for k in args.kinds.split(",") if k.strip()}
    bad = requested - VALID_KINDS
    if bad:
        raise SystemExit(f"unknown kinds: {sorted(bad)}; valid={sorted(VALID_KINDS)}")

    all_hits: list[dict] = []
    project_names: dict[str, str] = {}

    for pid, db_path in _project_dbs():
        con = sqlite3.connect(db_path)
        project_names[pid] = _project_name(con, pid)
        per_project_remaining = args.limit
        if "papers" in requested and per_project_remaining > 0:
            hits = _search_papers(con, pid, args.query, per_project_remaining)
            all_hits.extend(hits)
            per_project_remaining -= len(hits)
        if "concepts" in requested and per_project_remaining > 0:
            hits = _search_concepts(con, pid, args.query, per_project_remaining)
            all_hits.extend(hits)
            per_project_remaining -= len(hits)
        if "manuscripts" in requested and per_project_remaining > 0:
            hits = _search_manuscripts(con, pid, args.query, per_project_remaining)
            all_hits.extend(hits)
            per_project_remaining -= len(hits)
        if "journal" in requested and per_project_remaining > 0:
            hits = _search_journal(con, pid, args.query, per_project_remaining)
            all_hits.extend(hits)
        con.close()

    # Annotate each hit with project_name and group by kind
    for hit in all_hits:
        hit["project_name"] = project_names.get(hit["project_id"], hit["project_id"])

    grouped: dict[str, list[dict]] = {}
    for hit in all_hits:
        grouped.setdefault(hit["kind"], []).append(hit)

    print(json.dumps({
        "query": args.query,
        "projects_searched": len(project_names),
        "total_hits": len(all_hits),
        "hits_by_kind": {k: len(v) for k, v in grouped.items()},
        "results": grouped,
    }, indent=2, default=str))


if __name__ == "__main__":
    main()
