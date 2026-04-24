#!/usr/bin/env python3
"""reference-agent: ingest Zotero items into the paper cache + project graph.

Input JSON: flat list of Zotero item dicts (see SKILL.md for shape).
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

from lib.cache import cache_root  # noqa: E402


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")[:60] or "untitled"


def derive_canonical_id(title: str, year: int | None, first_author: str | None,
                        doi: str | None) -> str:
    author_part = (_slug(first_author or "anon").split("-") or ["anon"])[-1]
    year_part = str(year) if year else "nd"
    title_part = _slug(title)[:60] or "untitled"
    fingerprint = (doi or f"{title}|{year}|{first_author}").lower()
    h = hashlib.blake2s(fingerprint.encode("utf-8"), digest_size=3).hexdigest()
    return f"{author_part}_{year_part}_{title_part}_{h}"


def paper_dir(cid: str) -> Path:
    p = cache_root() / "papers" / cid
    p.mkdir(parents=True, exist_ok=True)
    (p / "figures").mkdir(exist_ok=True)
    (p / "tables").mkdir(exist_ok=True)
    (p / "raw").mkdir(exist_ok=True)
    return p


def write_artifact(item: dict) -> str:
    title = item.get("title") or "untitled"
    authors = item.get("authors") or []
    first_author = authors[0] if authors else None
    cid = derive_canonical_id(title, item.get("year"), first_author, item.get("doi"))
    pd = paper_dir(cid)
    now = datetime.now(UTC).isoformat()

    manifest_path = pd / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
    else:
        manifest = {
            "canonical_id": cid, "state": "discovered",
            "created_at": now, "sources_tried": [],
        }
    manifest["doi"] = manifest.get("doi") or item.get("doi")
    manifest["updated_at"] = now
    manifest_path.write_text(json.dumps(manifest, indent=2))

    metadata_path = pd / "metadata.json"
    metadata = {}
    if metadata_path.exists():
        metadata = json.loads(metadata_path.read_text())
    metadata.setdefault("discovered_via", [])
    if "zotero" not in metadata["discovered_via"]:
        metadata["discovered_via"].append("zotero")
    metadata["title"] = metadata.get("title") or title
    metadata["authors"] = metadata.get("authors") or authors
    metadata["year"] = metadata.get("year") or item.get("year")
    metadata["abstract"] = metadata.get("abstract") or item.get("abstract")
    metadata["venue"] = metadata.get("venue") or item.get("venue")
    metadata["keywords"] = metadata.get("keywords") or item.get("tags") or []
    metadata.setdefault("claims", [])
    metadata_path.write_text(json.dumps(metadata, indent=2))
    return cid


def sync_project(items: list[dict], project_id: str) -> dict:
    """Write artifacts + update project DB (zotero_links + graph_nodes + artifact_index)."""
    # Connect to project DB — init if needed
    proj_root = cache_root() / "projects" / project_id
    proj_root.mkdir(parents=True, exist_ok=True)
    db_path = proj_root / "project.db"
    fresh = not db_path.exists()
    con = sqlite3.connect(db_path)
    if fresh:
        schema = (_REPO_ROOT / "lib" / "sqlite_schema.sql").read_text()
        con.executescript(schema)

    added = 0
    linked = 0
    now = datetime.now(UTC).isoformat()

    with con:
        for item in items:
            cid = write_artifact(item)
            added += 1

            # zotero_links
            zkey = item.get("zotero_key")
            zlib = item.get("zotero_library")
            if zkey:
                cur = con.execute(
                    "INSERT OR IGNORE INTO zotero_links "
                    "(canonical_id, zotero_key, zotero_library, synced_at) "
                    "VALUES (?, ?, ?, ?)",
                    (cid, zkey, zlib, now),
                )
                if cur.rowcount:
                    linked += 1

            # artifact_index
            con.execute(
                "INSERT OR REPLACE INTO artifact_index "
                "(artifact_id, kind, project_id, state, path, created_at, updated_at) "
                "VALUES (?, 'paper', ?, 'discovered', ?, "
                "COALESCE((SELECT created_at FROM artifact_index WHERE artifact_id=?), ?), ?)",
                (cid, project_id, str(paper_dir(cid)), cid, now, now),
            )

            # graph_nodes — paper
            paper_node = f"paper:{cid}"
            con.execute(
                "INSERT OR IGNORE INTO graph_nodes (node_id, kind, label, data_json, created_at) "
                "VALUES (?, 'paper', ?, ?, ?)",
                (paper_node, item.get("title", cid),
                 json.dumps({"doi": item.get("doi"), "year": item.get("year")}), now),
            )

            # graph_nodes — authors + authored-by edges
            for author in item.get("authors") or []:
                author_id = f"author:{_slug(author)}"
                con.execute(
                    "INSERT OR IGNORE INTO graph_nodes "
                    "(node_id, kind, label, data_json, created_at) "
                    "VALUES (?, 'author', ?, NULL, ?)",
                    (author_id, author, now),
                )
                con.execute(
                    "INSERT INTO graph_edges "
                    "(from_node, to_node, relation, weight, data_json, created_at) "
                    "VALUES (?, ?, 'authored-by', 1.0, NULL, ?)",
                    (paper_node, author_id, now),
                )

            # Default reading_state = to-read (don't overwrite)
            con.execute(
                "INSERT OR IGNORE INTO reading_state "
                "(canonical_id, project_id, state, updated_at) "
                "VALUES (?, ?, 'to-read', ?)",
                (cid, project_id, now),
            )

    con.close()
    return {"added": added, "linked_to_zotero": linked}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True)
    p.add_argument("--project-id", required=True)
    args = p.parse_args()

    items = json.loads(Path(args.input).read_text())
    if not isinstance(items, list):
        raise SystemExit("input must be a JSON array")

    result = sync_project(items, args.project_id)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
