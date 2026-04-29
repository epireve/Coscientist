#!/usr/bin/env python3
"""reference-agent: populate concept nodes + edges in the project graph.

Two sources:

1. **claims** (default, original v0.x behavior) — derive concept nodes
   lazily from a deep-research run's `claims` table. Each claim becomes
   a concept; supporting paper canonical_ids become `about` edges.

2. **openalex** (v0.151) — fetch OpenAlex topics for a paper and ingest
   them as concept nodes. Each work has up to 4 levels of hierarchy:
   topic ⊂ subfield ⊂ field ⊂ domain. We model each level as its own
   concept node and connect them via `depends-on` edges (subfield
   depends-on field, etc.). The paper itself gets `about` edges to each
   topic with `weight = score` (0.0–1.0).

   Concept ref = slug(display_name); duplicates dedupe via
   `add_node`'s `INSERT OR IGNORE`. Edges check existing rows first
   so re-runs are idempotent.

Errors NEVER raise — every failure path returns a dict with `error`.
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

from lib.cache import cache_root, paper_dir, run_db_path  # noqa: E402


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")


def _claim_concept_ref(claim_id: int, text: str) -> str:
    slug = _slug(text)[:40] or f"claim-{claim_id}"
    h = hashlib.blake2s(f"{claim_id}|{text}".encode(), digest_size=2).hexdigest()
    return f"{slug}-{h}"


def _project_db(project_id: str) -> Path:
    p = cache_root() / "projects" / project_id / "project.db"
    if not p.exists():
        raise FileNotFoundError(f"no project DB at {p}")
    return p


def _edge_exists(con, from_n: str, to_n: str, relation: str) -> bool:
    return con.execute(
        "SELECT 1 FROM graph_edges WHERE from_node=? AND to_node=? AND relation=? LIMIT 1",
        (from_n, to_n, relation),
    ).fetchone() is not None


def _has_v13(con) -> bool:
    cols = [r[1] for r in con.execute("PRAGMA table_info(graph_nodes)")]
    return "external_ids_json" in cols and "source" in cols


def _insert_concept(
    con, ref: str, label: str, *, openalex_id: str | None = None,
    wikidata_id: str | None = None, level: str | None = None,
    source: str = "openalex",
) -> tuple[str, bool]:
    """Insert a concept node by slug ref. Returns (node_id, created)."""
    nid = f"concept:{ref}"
    now = datetime.now(UTC).isoformat()
    ext: dict = {}
    if openalex_id:
        ext["openalex_id"] = openalex_id
    if wikidata_id:
        ext["wikidata_id"] = wikidata_id
    data = {"level": level} if level else None
    if _has_v13(con):
        cur = con.execute(
            "INSERT OR IGNORE INTO graph_nodes "
            "(node_id, kind, label, data_json, created_at, "
            "external_ids_json, source) VALUES (?, 'concept', ?, ?, ?, ?, ?)",
            (
                nid, label,
                json.dumps(data) if data else None,
                now,
                json.dumps(ext) if ext else None,
                source,
            ),
        )
    else:
        cur = con.execute(
            "INSERT OR IGNORE INTO graph_nodes "
            "(node_id, kind, label, data_json, created_at) "
            "VALUES (?, 'concept', ?, ?, ?)",
            (nid, label, json.dumps(data) if data else None, now),
        )
    return nid, bool(cur.rowcount)


def _ensure_paper_node(con, canonical_id: str) -> str:
    nid = f"paper:{canonical_id}"
    now = datetime.now(UTC).isoformat()
    con.execute(
        "INSERT OR IGNORE INTO graph_nodes "
        "(node_id, kind, label, data_json, created_at) "
        "VALUES (?, 'paper', ?, NULL, ?)",
        (nid, canonical_id, now),
    )
    return nid


def _insert_edge(
    con, from_nid: str, to_nid: str, relation: str,
    *, weight: float = 1.0, data: dict | None = None,
) -> bool:
    """Insert edge if not present. Returns True when newly created."""
    if _edge_exists(con, from_nid, to_nid, relation):
        return False
    now = datetime.now(UTC).isoformat()
    con.execute(
        "INSERT INTO graph_edges "
        "(from_node, to_node, relation, weight, data_json, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (from_nid, to_nid, relation, weight,
         json.dumps(data) if data else None, now),
    )
    return True


# =====================================================================
# Source: claims (original behavior, preserved)
# =====================================================================

def populate_from_claims(run_id: str, project_id: str) -> dict:
    run_db = run_db_path(run_id)
    if not run_db.exists():
        return {"error": f"no run DB at {run_db}"}
    try:
        proj_db = _project_db(project_id)
    except FileNotFoundError as e:
        return {"error": str(e)}

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
            concept_ref = _claim_concept_ref(c["claim_id"], cid_text)
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

            cids: list[str] = []
            if c["canonical_id"]:
                cids.append(c["canonical_id"])
            if c["supporting_ids"]:
                try:
                    cids.extend(json.loads(c["supporting_ids"]) or [])
                except json.JSONDecodeError:
                    pass
            cids = list(dict.fromkeys(x for x in cids if x))

            for paper_cid in cids:
                paper_node_id = _ensure_paper_node(proj_con, paper_cid)
                if _insert_edge(
                    proj_con, concept_node_id, paper_node_id, "about",
                    data={"claim_kind": c["kind"]},
                ):
                    edges_added += 1

    proj_con.close()
    return {
        "concepts_added": concepts_added,
        "edges_added": edges_added,
        "claims_processed": len(claims),
    }


# =====================================================================
# Source: openalex (v0.151 — new)
# =====================================================================

def _load_manifest(canonical_id: str) -> dict | None:
    mp = paper_dir(canonical_id) / "manifest.json"
    if not mp.exists():
        return None
    try:
        return json.loads(mp.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def _topic_oa_id(raw: str | None) -> str | None:
    """Strip OpenAlex URL prefix from topic id."""
    if not raw:
        return None
    s = raw.strip()
    for pre in ("https://openalex.org/", "http://openalex.org/"):
        if s.startswith(pre):
            return s[len(pre):]
    return s


def _ingest_topics_for_paper(
    proj_con, canonical_id: str, work: dict, *, min_score: float,
) -> dict:
    """Process topics from one OpenAlex work into the graph.

    Returns counters dict: {concepts_added, edges_added, topics_seen}.
    """
    topics = work.get("topics") or []
    if not topics:
        return {"concepts_added": 0, "edges_added": 0, "topics_seen": 0}

    paper_nid = _ensure_paper_node(proj_con, canonical_id)
    concepts_added = 0
    edges_added = 0
    topics_seen = 0

    for t in topics:
        score = float(t.get("score") or 0.0)
        if score < min_score:
            continue
        topics_seen += 1

        topic_name = t.get("display_name") or ""
        topic_ref = _slug(topic_name)
        if not topic_ref:
            continue
        topic_oa = _topic_oa_id(t.get("id"))
        topic_wd = t.get("wikidata_id")  # rarely present at topic level

        topic_nid, created = _insert_concept(
            proj_con, topic_ref, topic_name,
            openalex_id=topic_oa, wikidata_id=topic_wd,
            level="topic",
        )
        if created:
            concepts_added += 1

        # paper -[about]-> topic with weight=score
        if _insert_edge(
            proj_con, paper_nid, topic_nid, "about",
            weight=score, data={"source": "openalex"},
        ):
            edges_added += 1

        # Hierarchy: topic ⊂ subfield ⊂ field ⊂ domain
        prev_nid = topic_nid
        for level in ("subfield", "field", "domain"):
            node = t.get(level)
            if not node:
                continue
            nm = node.get("display_name") or ""
            ref = _slug(nm)
            if not ref:
                continue
            oa = _topic_oa_id(node.get("id"))
            wd = node.get("wikidata_id")
            level_nid, lcreated = _insert_concept(
                proj_con, ref, nm,
                openalex_id=oa, wikidata_id=wd,
                level=level,
            )
            if lcreated:
                concepts_added += 1
            # child -[depends-on]-> parent
            if _insert_edge(proj_con, prev_nid, level_nid, "depends-on"):
                edges_added += 1
            prev_nid = level_nid

    return {
        "concepts_added": concepts_added,
        "edges_added": edges_added,
        "topics_seen": topics_seen,
    }


def _list_project_papers(project_id: str) -> list[str]:
    """Return canonical_ids of every paper artifact in the project."""
    db = _project_db(project_id)
    con = sqlite3.connect(db)
    rows = con.execute(
        "SELECT artifact_id FROM artifact_index WHERE kind='paper'"
    ).fetchall()
    con.close()
    return [r[0] for r in rows]


def populate_from_openalex(
    project_id: str,
    *,
    paper_id: str | None = None,
    min_score: float = 0.5,
    client=None,
) -> dict:
    """Ingest OpenAlex topics for one paper or all papers in a project.

    `client` is optional — when None, builds a default `OpenAlexClient`.
    Tests inject a stub.
    """
    try:
        proj_db = _project_db(project_id)
    except FileNotFoundError as e:
        return {"error": str(e)}

    if paper_id:
        cids = [paper_id]
    else:
        cids = _list_project_papers(project_id)

    if not cids:
        return {
            "papers_processed": 0,
            "concepts_added": 0,
            "edges_added": 0,
            "topics_seen": 0,
        }

    if client is None:
        try:
            from lib.openalex_client import OpenAlexClient
            client = OpenAlexClient()
        except Exception as e:  # noqa: BLE001
            return {"error": f"failed to init OpenAlexClient: {e}"}

    proj_con = sqlite3.connect(proj_db)
    totals = {
        "papers_processed": 0,
        "concepts_added": 0,
        "edges_added": 0,
        "topics_seen": 0,
        "papers_skipped": [],
    }

    with proj_con:
        for cid in cids:
            manifest = _load_manifest(cid)
            if not manifest:
                totals["papers_skipped"].append(
                    {"paper_id": cid, "reason": "missing manifest"}
                )
                continue
            oa_id = manifest.get("openalex_id")
            doi = manifest.get("doi")
            lookup = oa_id or doi
            if not lookup:
                totals["papers_skipped"].append(
                    {"paper_id": cid, "reason": "no openalex_id or doi"}
                )
                continue
            work = client.get_work(lookup)
            if not isinstance(work, dict) or "error" in work:
                totals["papers_skipped"].append(
                    {
                        "paper_id": cid,
                        "reason": (
                            work.get("error") if isinstance(work, dict)
                            else "non-dict response"
                        ),
                    }
                )
                continue
            counts = _ingest_topics_for_paper(
                proj_con, cid, work, min_score=min_score,
            )
            totals["papers_processed"] += 1
            totals["concepts_added"] += counts["concepts_added"]
            totals["edges_added"] += counts["edges_added"]
            totals["topics_seen"] += counts["topics_seen"]

    proj_con.close()
    return totals


# Back-compat wrapper for the original call signature.
def populate(run_id: str, project_id: str) -> dict:
    return populate_from_claims(run_id, project_id)


# =====================================================================
# CLI
# =====================================================================

_CONCEPT_SOURCES = {"claims", "openalex"}


def _resolve_auto_source() -> tuple[str, str]:
    """Resolve --source auto via lib.source_selector. Returns (chosen, reason).

    Concept ingestion phase = "ingestion" (graph backbone). Selector picks
    openalex. Anything else (defensive) → fallback to openalex with warning.
    Note: 'claims' is *not* a selector output — it's a coscientist-internal
    derivation source, distinct from the source_selector's vocabulary.
    """
    try:
        from lib.source_selector import select_source
        rec = select_source(phase="ingestion")
        primary = rec.primary
        if primary == "openalex":
            return "openalex", rec.reasoning
        return (
            "openalex",
            f"selector returned {primary!r}; concepts only support "
            f"openalex via auto — falling back to openalex",
        )
    except Exception as e:  # noqa: BLE001
        return "openalex", f"selector failure: {e}; falling back to openalex"


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--source",
                   choices=["auto", "claims", "openalex"], default="auto",
                   help="auto = phase-aware via lib.source_selector "
                        "(default, ingestion → openalex); "
                        "claims = derive from run claims; "
                        "openalex = ingest OpenAlex topics")
    p.add_argument("--run-id", help="run id (required for --source claims)")
    p.add_argument("--project-id", required=True)
    p.add_argument("--paper-id",
                   help="single paper canonical_id (openalex source); "
                        "omit to batch all project papers")
    p.add_argument("--min-score", type=float, default=0.5,
                   help="min OpenAlex topic score to ingest (0.0–1.0)")
    args = p.parse_args()

    if args.source == "auto":
        chosen, reason = _resolve_auto_source()
        print(
            f"[source-selector] populate_concepts resolved auto -> "
            f"{chosen} (reason: {reason})",
            file=sys.stderr,
        )
        args.source = chosen

    if args.source == "claims":
        if not args.run_id:
            print(json.dumps({"error": "--run-id required for --source claims"}))
            sys.exit(2)
        result = populate_from_claims(args.run_id, args.project_id)
    else:
        result = populate_from_openalex(
            args.project_id,
            paper_id=args.paper_id,
            min_score=args.min_score,
        )

    print(json.dumps(result, indent=2))
    if isinstance(result, dict) and "error" in result:
        sys.exit(1)


if __name__ == "__main__":
    main()
