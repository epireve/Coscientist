#!/usr/bin/env python3
"""manuscript-ingest: resolve raw citation keys to canonical_ids.

When a manuscript is ingested we record raw citation keys (like
"vaswani2017") without knowing which canonical paper they refer to.
This script fills in the `resolved_canonical_id` column later — either:

- When the agent provides a mapping after running the Zotero sync or a
  Semantic Scholar lookup
- When manuscript-audit explicitly maps them during claim analysis

It also upgrades the graph: the `paper:unresolved:<key>` placeholder
node is replaced/merged with the real `paper:<canonical_id>` node, and
the `cites` edge is moved.

Input JSON:
  [
    {"citation_key": "vaswani2017",
     "canonical_id": "vaswani_2017_attention_abc123",
     "source": "manual|zotero|semantic-scholar"},
    ...
  ]
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lib.cache import cache_root  # noqa: E402

VALID_SOURCES = {"manual", "zotero", "semantic-scholar", "audit"}


def _project_db(project_id: str) -> Path:
    p = cache_root() / "projects" / project_id / "project.db"
    if not p.exists():
        raise SystemExit(f"no project DB at {p}")
    return p


def resolve(manuscript_id: str, resolutions: list[dict],
            project_id: str) -> dict:
    db = _project_db(project_id)
    con = sqlite3.connect(db)
    now = datetime.now(UTC).isoformat()

    updated = 0
    edges_migrated = 0
    errors: list[str] = []

    with con:
        for r in resolutions:
            key = r.get("citation_key")
            cid = r.get("canonical_id")
            source = r.get("source", "manual")
            if not key or not cid:
                errors.append(f"missing citation_key or canonical_id: {r}")
                continue
            if source not in VALID_SOURCES:
                errors.append(f"source {source!r} not in {sorted(VALID_SOURCES)}")
                continue

            # Update every row in manuscript_citations for this (mid, key)
            cur = con.execute(
                "UPDATE manuscript_citations "
                "SET resolved_canonical_id=?, resolution_source=?, at=? "
                "WHERE manuscript_id=? AND citation_key=? "
                "AND (resolved_canonical_id IS NULL OR resolved_canonical_id=?)",
                (cid, source, now, manuscript_id, key, cid),
            )
            updated += cur.rowcount

            # Graph migration: replace manuscript→unresolved-paper with manuscript→real-paper
            ms_node = f"manuscript:{manuscript_id}"
            unresolved_node = f"paper:unresolved:{key}"
            real_node = f"paper:{cid}"

            # Ensure real paper node exists
            con.execute(
                "INSERT OR IGNORE INTO graph_nodes "
                "(node_id, kind, label, data_json, created_at) "
                "VALUES (?, 'paper', ?, NULL, ?)",
                (real_node, cid, now),
            )

            # If an edge already exists from ms to real, skip; otherwise
            # replace the unresolved edge
            real_exists = con.execute(
                "SELECT 1 FROM graph_edges "
                "WHERE from_node=? AND to_node=? AND relation='cites'",
                (ms_node, real_node),
            ).fetchone()
            if not real_exists:
                cur_edge = con.execute(
                    "UPDATE graph_edges SET to_node=? "
                    "WHERE from_node=? AND to_node=? AND relation='cites'",
                    (real_node, ms_node, unresolved_node),
                )
                if cur_edge.rowcount:
                    edges_migrated += 1

            # Drop the now-unused unresolved placeholder node if no remaining
            # edges reference it
            still_used = con.execute(
                "SELECT 1 FROM graph_edges WHERE from_node=? OR to_node=?",
                (unresolved_node, unresolved_node),
            ).fetchone()
            if not still_used:
                con.execute(
                    "DELETE FROM graph_nodes WHERE node_id=?",
                    (unresolved_node,),
                )

    con.close()

    if errors:
        for e in errors:
            print(f"[resolve-citations] WARN: {e}", file=sys.stderr)

    return {
        "citation_rows_updated": updated,
        "graph_edges_migrated": edges_migrated,
        "errors": len(errors),
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True)
    p.add_argument("--manuscript-id", required=True)
    p.add_argument("--project-id", required=True)
    args = p.parse_args()

    resolutions = json.loads(Path(args.input).read_text())
    if not isinstance(resolutions, list):
        raise SystemExit("input must be a JSON array")

    result = resolve(args.manuscript_id, resolutions, args.project_id)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
