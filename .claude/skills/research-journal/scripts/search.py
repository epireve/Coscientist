#!/usr/bin/env python3
"""research-journal: substring search across journal entry bodies."""

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


def _project_db(project_id: str) -> Path:
    p = cache_root() / "projects" / project_id / "project.db"
    if not p.exists():
        raise SystemExit(f"no project DB at {p}")
    return p


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--project-id", required=True)
    p.add_argument("--query", required=True)
    p.add_argument("--limit", type=int, default=50)
    args = p.parse_args()

    if not args.query.strip():
        raise SystemExit("empty query")

    con = sqlite3.connect(_project_db(args.project_id))
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT entry_id, entry_date, body, tags, links FROM journal_entries "
        "WHERE project_id=? AND lower(body) LIKE ? "
        "ORDER BY entry_date DESC, entry_id DESC LIMIT ?",
        (args.project_id, f"%{args.query.lower()}%", args.limit),
    ).fetchall()
    con.close()

    out = []
    for r in rows:
        d = dict(r)
        try:
            d["tags"] = json.loads(d["tags"]) if d["tags"] else []
        except json.JSONDecodeError:
            d["tags"] = []
        try:
            d["links"] = json.loads(d["links"]) if d["links"] else {}
        except json.JSONDecodeError:
            d["links"] = {}
        # short snippet around the match
        body = d["body"]
        idx = body.lower().find(args.query.lower())
        if idx >= 0:
            start = max(0, idx - 60)
            end = min(len(body), idx + len(args.query) + 60)
            d["snippet"] = ("..." if start > 0 else "") + body[start:end] + ("..." if end < len(body) else "")
        out.append(d)

    print(json.dumps({"query": args.query, "matches": len(out), "results": out},
                     indent=2, default=str))


if __name__ == "__main__":
    main()
