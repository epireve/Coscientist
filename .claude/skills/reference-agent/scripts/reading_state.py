#!/usr/bin/env python3
"""reference-agent: get/set per-project reading state for a paper.

State machine: to-read → reading → read → annotated → cited | skipped
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

VALID_STATES = {"to-read", "reading", "read", "annotated", "cited", "skipped"}


def _project_db(project_id: str) -> Path:
    p = cache_root() / "projects" / project_id / "project.db"
    if not p.exists():
        raise SystemExit(f"no project DB at {p} — create the project first")
    return p


def set_state(project_id: str, cid: str, state: str, notes: str | None) -> None:
    if state not in VALID_STATES:
        raise SystemExit(f"state {state!r} not in {sorted(VALID_STATES)}")
    con = sqlite3.connect(_project_db(project_id))
    now = datetime.now(UTC).isoformat()
    with con:
        con.execute(
            "INSERT INTO reading_state (canonical_id, project_id, state, notes, updated_at) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(canonical_id, project_id) DO UPDATE SET "
            "state=excluded.state, notes=excluded.notes, updated_at=excluded.updated_at",
            (cid, project_id, state, notes, now),
        )
    con.close()


def get_state(project_id: str, cid: str) -> str | None:
    con = sqlite3.connect(_project_db(project_id))
    row = con.execute(
        "SELECT state FROM reading_state WHERE canonical_id=? AND project_id=?",
        (cid, project_id),
    ).fetchone()
    con.close()
    return row[0] if row else None


def list_by_state(project_id: str, state: str | None) -> list[dict]:
    con = sqlite3.connect(_project_db(project_id))
    con.row_factory = sqlite3.Row
    if state:
        if state not in VALID_STATES:
            raise SystemExit(f"state {state!r} not in {sorted(VALID_STATES)}")
        rows = con.execute(
            "SELECT * FROM reading_state WHERE project_id=? AND state=? "
            "ORDER BY updated_at DESC",
            (project_id, state),
        ).fetchall()
    else:
        rows = con.execute(
            "SELECT * FROM reading_state WHERE project_id=? ORDER BY state, updated_at DESC",
            (project_id,),
        ).fetchall()
    con.close()
    return [dict(r) for r in rows]


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--canonical-id")
    p.add_argument("--project-id", required=True)
    p.add_argument("--state", default=None, choices=sorted(VALID_STATES))
    p.add_argument("--notes", default=None)
    p.add_argument("--get", action="store_true")
    p.add_argument("--list-by-state", default=None)
    p.add_argument("--list-all", action="store_true")
    args = p.parse_args()

    if args.list_all or args.list_by_state:
        items = list_by_state(args.project_id, args.list_by_state)
        print(json.dumps(items, indent=2, default=str))
        return

    if not args.canonical_id:
        raise SystemExit("--canonical-id required (or use --list-all/--list-by-state)")

    if args.get:
        print(get_state(args.project_id, args.canonical_id) or "unknown")
        return

    if not args.state:
        raise SystemExit("--state or --get required")

    set_state(args.project_id, args.canonical_id, args.state, args.notes)
    print(f"{args.canonical_id} → {args.state}")


if __name__ == "__main__":
    main()
