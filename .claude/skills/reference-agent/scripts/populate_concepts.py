#!/usr/bin/env python3
"""reference-agent: populate concept edges in the project graph from a run's claims.

For each claim in a deep-research run DB:
- Create a concept node keyed on slug(claim_text[:40]) + claim_id hash
- Add `about` edges from the concept node to each supporting paper
- For `tension` claims: add `about` edges to both sides' papers

Scans the run DB's `claims` table directly; no MCP calls.

The concept graph lets us ask questions like "which papers are the
most connected to this concept?" by running graph.hubs on concepts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lib.cache import cache_root, run_db_path  # noqa: E402


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")


def _concept_id(claim_id: int, text: str) -> str:
    slug = _slug(text)[:40] or f"claim-{claim_id}"
    h = hashlib.blake2s(f"{claim_id}|{text}".encode(), digest_size=2).hexdigest()
    return f"{slug}-{h}"


def _project_db(project_id: str) -> Path:
    p = cache_root() / "projects" / project_id / "project.db"
    if not p.exists():
        raise SystemExit(f"no project DB at {p}")
    return p


def _edge_exists(con, from_n: str, to_n: str, relation: str) -> bool:
    return con.execute(
        "SELECT 1 FROM graph_edges WHERE from_node=? AND to_node=? AND relation=? LIMIT 1",
        (from_n, to_n, relation),
    ).fetchone() is not None


def populate(run_id: str, project_id: str) -> dict:
    run_db = run_db_path(run_id)
    if not run_db.exists():
        raise SystemExit(f"no run DB at {run_db}")
    proj_db = _project_db(project_id)

    run_con = sqlite3.connect(run_db)
    run_con.row_factory = sqlite3.Row
    claims = run_con.execute(
        "SELECT claim_id, canonical_id, agent_name, text, kind, supporting_ids "
        "FROM claims WHERE run_id=?",
        (run_id,),
    ).fetchall()
    run_con.close()

    if not claims:
        return {"concepts_added": 0, "edges_added": 0, "claims_processed": 0}

    proj_con = sqlite3.connect(proj_db)
    now = datetime.now(UTC).isoformat()
    concepts_added = 0
    edges_added = 0

    with proj_con:
        for c in claims:
            cid_text = c["text"] or ""
            concept_ref = _concept_id(c["claim_id"], cid_text)
            concept_node_id = f"concept:{concept_ref}"

            cur = proj_con.execute(
                "INSERT OR IGNORE INTO graph_nodes "
                "(node_id, kind, label, data_json, created_at) "
                "VALUES (?, 'concept', ?, ?, ?)",
                (
                    concept_node_id,
                    cid_text[:120],
                    json.dumps({"kind": c["kind"], "agent": c["agent_name"]}),
                    now,
                ),
            )
            if cur.rowcount:
                concepts_added += 1

            # Collect all supporting paper canonical_ids
            cids: list[str] = []
            if c["canonical_id"]:
                cids.append(c["canonical_id"])
            if c["supporting_ids"]:
                try:
                    cids.extend(json.loads(c["supporting_ids"]) or [])
                except json.JSONDecodeError:
                    pass
            cids = list(dict.fromkeys(x for x in cids if x))  # uniq + nonempty

            for paper_cid in cids:
                paper_node_id = f"paper:{paper_cid}"
                # Ensure the paper node exists (may not yet if this project
                # doesn't contain it)
                proj_con.execute(
                    "INSERT OR IGNORE INTO graph_nodes "
                    "(node_id, kind, label, data_json, created_at) "
                    "VALUES (?, 'paper', ?, NULL, ?)",
                    (paper_node_id, paper_cid, now),
                )
                if not _edge_exists(proj_con, concept_node_id, paper_node_id, "about"):
                    proj_con.execute(
                        "INSERT INTO graph_edges "
                        "(from_node, to_node, relation, weight, data_json, created_at) "
                        "VALUES (?, ?, 'about', 1.0, ?, ?)",
                        (
                            concept_node_id, paper_node_id,
                            json.dumps({"claim_kind": c["kind"]}),
                            now,
                        ),
                    )
                    edges_added += 1

    proj_con.close()
    return {
        "concepts_added": concepts_added,
        "edges_added": edges_added,
        "claims_processed": len(claims),
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--run-id", required=True)
    p.add_argument("--project-id", required=True)
    args = p.parse_args()

    result = populate(args.run_id, args.project_id)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
