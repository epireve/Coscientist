#!/usr/bin/env python3
"""reference-agent: populate citation edges in the project graph.

Input JSON: list of citation records pulled from Semantic Scholar (via
mcp__semantic-scholar__get_paper_references and get_paper_citations):

[
  {
    "from_canonical_id": "vaswani_2017_attention_abc123",
    "references": [
      {"canonical_id": "bahdanau_2014_xxx", "title": "...", "year": 2014}
    ],
    "citations": [
      {"canonical_id": "devlin_2019_bert_yyy", "title": "...", "year": 2019}
    ]
  },
  ...
]

For each record:
- Ensure the `from` paper exists as a graph_node (create if missing)
- For each reference: create graph_node + `cites` edge from→ref + `cited-by` edge ref→from
- For each citation: create graph_node + `cited-by` edge from→citer + `cites` edge citer→from

Idempotent: re-running is safe. Existing nodes/edges are not duplicated
at the data level; edges with the same (from, to, relation) are
allowed to recur, but we de-dupe at script level against the DB.
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


def _project_db(project_id: str) -> Path:
    p = cache_root() / "projects" / project_id / "project.db"
    if not p.exists():
        raise SystemExit(f"no project DB at {p}")
    return p


def _ensure_node(con: sqlite3.Connection, cid: str, label: str,
                 data: dict, now: str) -> str:
    node_id = f"paper:{cid}"
    con.execute(
        "INSERT OR IGNORE INTO graph_nodes (node_id, kind, label, data_json, created_at) "
        "VALUES (?, 'paper', ?, ?, ?)",
        (node_id, label, json.dumps(data) if data else None, now),
    )
    return node_id


def _edge_exists(con: sqlite3.Connection, from_n: str, to_n: str, relation: str) -> bool:
    row = con.execute(
        "SELECT 1 FROM graph_edges WHERE from_node=? AND to_node=? AND relation=? LIMIT 1",
        (from_n, to_n, relation),
    ).fetchone()
    return row is not None


def _add_edge_if_new(con: sqlite3.Connection, from_n: str, to_n: str,
                     relation: str, now: str) -> bool:
    if _edge_exists(con, from_n, to_n, relation):
        return False
    con.execute(
        "INSERT INTO graph_edges (from_node, to_node, relation, weight, data_json, created_at) "
        "VALUES (?, ?, ?, 1.0, NULL, ?)",
        (from_n, to_n, relation, now),
    )
    return True


def populate(records: list[dict], project_id: str) -> dict:
    con = sqlite3.connect(_project_db(project_id))
    now = datetime.now(UTC).isoformat()
    added_nodes = 0
    added_edges = 0
    skipped = 0

    with con:
        for rec in records:
            from_cid = rec.get("from_canonical_id")
            if not from_cid:
                skipped += 1
                continue
            from_node = _ensure_node(con, from_cid, from_cid, {}, now)

            for ref in rec.get("references") or []:
                rcid = ref.get("canonical_id")
                if not rcid:
                    continue
                ref_node = _ensure_node(
                    con, rcid, ref.get("title") or rcid,
                    {"year": ref.get("year"), "doi": ref.get("doi")}, now,
                )
                if _add_edge_if_new(con, from_node, ref_node, "cites", now):
                    added_edges += 1
                if _add_edge_if_new(con, ref_node, from_node, "cited-by", now):
                    added_edges += 1

            for cit in rec.get("citations") or []:
                ccid = cit.get("canonical_id")
                if not ccid:
                    continue
                cit_node = _ensure_node(
                    con, ccid, cit.get("title") or ccid,
                    {"year": cit.get("year"), "doi": cit.get("doi")}, now,
                )
                if _add_edge_if_new(con, cit_node, from_node, "cites", now):
                    added_edges += 1
                if _add_edge_if_new(con, from_node, cit_node, "cited-by", now):
                    added_edges += 1

        # Count nodes added during this batch (approximate via comparison is complex;
        # report via rowid delta isn't portable — just report edges added, nodes
        # are INSERT OR IGNORE).
        added_nodes = con.execute(
            "SELECT COUNT(*) FROM graph_nodes WHERE created_at=?",
            (now,),
        ).fetchone()[0]

    con.close()
    return {"edges_added": added_edges, "nodes_touched": added_nodes, "skipped": skipped}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True)
    p.add_argument("--project-id", required=True)
    args = p.parse_args()

    records = json.loads(Path(args.input).read_text())
    if not isinstance(records, list):
        raise SystemExit("input must be a JSON array")

    result = populate(records, args.project_id)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
