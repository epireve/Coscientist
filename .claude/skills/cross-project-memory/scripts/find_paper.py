#!/usr/bin/env python3
"""cross-project-memory: find every project containing a given paper."""

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


def _project_dbs() -> list[tuple[str, Path]]:
    base = cache_root() / "projects"
    if not base.exists():
        return []
    return [
        (p.name, p / "project.db")
        for p in sorted(base.iterdir())
        if (p / "project.db").exists()
    ]


def _candidate_canonical_ids(canonical_id: str | None, doi: str | None,
                              title_fragment: str | None) -> list[str]:
    """Resolve the lookup criteria to canonical_ids by scanning paper artifacts."""
    if canonical_id:
        return [canonical_id]
    base = cache_root() / "papers"
    if not base.exists():
        return []
    matches: list[str] = []
    title_low = (title_fragment or "").lower()
    for paper_dir in base.iterdir():
        cid = paper_dir.name
        manifest_p = paper_dir / "manifest.json"
        meta_p = paper_dir / "metadata.json"
        if not manifest_p.exists():
            continue
        try:
            manifest = json.loads(manifest_p.read_text())
        except json.JSONDecodeError:
            continue
        if doi and (manifest.get("doi") or "").lower() == doi.lower():
            matches.append(cid)
            continue
        if title_low and meta_p.exists():
            try:
                meta = json.loads(meta_p.read_text())
            except json.JSONDecodeError:
                continue
            if title_low in (meta.get("title") or "").lower():
                matches.append(cid)
    return matches


def _project_appearance(con: sqlite3.Connection, pid: str, cid: str) -> dict | None:
    """Where does this canonical_id appear in this project?"""
    row = con.execute(
        "SELECT name FROM projects WHERE project_id=?", (pid,)
    ).fetchone()
    name = row[0] if row else pid

    in_index = con.execute(
        "SELECT state FROM artifact_index WHERE artifact_id=? AND project_id=?",
        (cid, pid),
    ).fetchone()
    reading = con.execute(
        "SELECT state FROM reading_state WHERE canonical_id=? AND project_id=?",
        (cid, pid),
    ).fetchone()
    citing_manuscripts = [
        r[0] for r in con.execute(
            "SELECT DISTINCT manuscript_id FROM manuscript_citations "
            "WHERE resolved_canonical_id=?", (cid,),
        )
    ]
    in_graph = con.execute(
        "SELECT 1 FROM graph_nodes WHERE node_id=?", (f"paper:{cid}",),
    ).fetchone() is not None

    if not (in_index or reading or citing_manuscripts or in_graph):
        return None

    if in_index:
        kind = "registered"
    elif citing_manuscripts:
        kind = "cited"
    elif reading:
        kind = "reading-tracked"
    else:
        kind = "graph-only"

    return {
        "project_id": pid,
        "project_name": name,
        "kind": kind,
        "artifact_state": in_index[0] if in_index else None,
        "reading_state": reading[0] if reading else None,
        "citing_manuscripts": citing_manuscripts,
        "in_graph": in_graph,
    }


def main() -> None:
    p = argparse.ArgumentParser()
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--canonical-id")
    g.add_argument("--doi")
    g.add_argument("--title")
    args = p.parse_args()

    cids = _candidate_canonical_ids(args.canonical_id, args.doi, args.title)
    if not cids:
        print(json.dumps({"matches": 0, "papers": []}, indent=2))
        return

    out: list[dict] = []
    for cid in cids:
        appearances: list[dict] = []
        for pid, db_path in _project_dbs():
            con = sqlite3.connect(db_path)
            ap = _project_appearance(con, pid, cid)
            con.close()
            if ap:
                appearances.append(ap)
        out.append({"canonical_id": cid, "appearances": appearances})

    print(json.dumps({
        "matches": len(out),
        "papers": out,
    }, indent=2, default=str))


if __name__ == "__main__":
    main()
