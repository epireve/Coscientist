#!/usr/bin/env python3
"""research-journal: list journal entries with optional filters."""

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
    p.add_argument("--from", dest="date_from", default=None)
    p.add_argument("--to", dest="date_to", default=None)
    p.add_argument("--tag", default=None)
    p.add_argument("--linked-paper", default=None)
    p.add_argument("--linked-manuscript", default=None)
    p.add_argument("--linked-run", default=None)
    p.add_argument("--limit", type=int, default=200)
    args = p.parse_args()

    con = sqlite3.connect(_project_db(args.project_id))
    con.row_factory = sqlite3.Row

    where = ["project_id=?"]
    params: list = [args.project_id]
    if args.date_from:
        where.append("entry_date >= ?")
        params.append(args.date_from)
    if args.date_to:
        where.append("entry_date <= ?")
        params.append(args.date_to)

    rows = con.execute(
        f"SELECT * FROM journal_entries WHERE {' AND '.join(where)} "
        f"ORDER BY entry_date DESC, entry_id DESC LIMIT ?",
        (*params, args.limit),
    ).fetchall()
    con.close()

    out = []
    journal_dir = cache_root() / "projects" / args.project_id / "journal"
    drift_warnings: list[str] = []

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

        if args.tag and args.tag not in d["tags"]:
            continue
        if args.linked_paper and args.linked_paper not in d["links"].get("papers", []):
            continue
        if args.linked_manuscript and args.linked_manuscript not in d["links"].get("manuscripts", []):
            continue
        if args.linked_run and args.linked_run not in d["links"].get("runs", []):
            continue

        # v0.13: drift detection — disk mirror should contain the body verbatim
        mirror = journal_dir / f"{d['entry_id']}.md"
        if mirror.exists():
            disk_content = mirror.read_text()
            if d["body"] not in disk_content:
                drift_warnings.append(
                    f"entry {d['entry_id']} disk mirror has drifted from DB"
                )
                d["disk_drift"] = True
        else:
            drift_warnings.append(
                f"entry {d['entry_id']} disk mirror missing at {mirror}"
            )
            d["disk_missing"] = True

        out.append(d)

    if drift_warnings:
        for w in drift_warnings:
            print(f"[warn] {w}", file=sys.stderr)

    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()
