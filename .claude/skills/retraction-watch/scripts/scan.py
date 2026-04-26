#!/usr/bin/env python3
"""retraction-watch: scan cited papers for retraction status.

Updates retraction_flags in the project DB for all papers that either:
  (a) have no existing flag, or
  (b) have not been checked in the last --max-age-days days.

In --dry-run mode: prints what would be checked, does not update DB or call MCPs.
In normal mode: caller (Claude agent) is expected to perform MCP lookups using
the list of canonical_ids printed to stdout, then call this script again with
--input <results.json> to persist the results.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lib.cache import cache_root  # noqa: E402


def _project_db(project_id: str) -> Path:
    return cache_root() / "projects" / project_id / "project.db"


def _open(project_id: str) -> sqlite3.Connection:
    db = _project_db(project_id)
    if not db.exists():
        raise SystemExit(f"no project DB at {db}")
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    return con


def _all_cited_papers(con: sqlite3.Connection) -> list[str]:
    """Return all canonical_ids referenced in the project (artifact_index + manuscript_citations)."""
    ids: set[str] = set()
    # Papers in artifact_index (kind=paper)
    try:
        rows = con.execute(
            "SELECT artifact_id FROM artifact_index WHERE kind='paper'"
        ).fetchall()
        for r in rows:
            if r["artifact_id"]:
                ids.add(r["artifact_id"])
    except sqlite3.OperationalError:
        pass
    # Papers cited in manuscripts
    try:
        rows = con.execute(
            "SELECT DISTINCT resolved_canonical_id FROM manuscript_citations "
            "WHERE resolved_canonical_id IS NOT NULL"
        ).fetchall()
        for r in rows:
            if r["resolved_canonical_id"]:
                ids.add(r["resolved_canonical_id"])
    except sqlite3.OperationalError:
        pass
    # Graph nodes of kind=paper
    try:
        rows = con.execute(
            "SELECT node_id FROM graph_nodes WHERE kind='paper'"
        ).fetchall()
        for r in rows:
            nid = r["node_id"] or ""
            cid = nid.removeprefix("paper:")
            if cid and not cid.startswith("unresolved:"):
                ids.add(cid)
    except sqlite3.OperationalError:
        pass
    return sorted(ids)


def _existing_flags(con: sqlite3.Connection) -> dict[str, sqlite3.Row]:
    try:
        rows = con.execute(
            "SELECT canonical_id, retracted, source, detail, checked_at "
            "FROM retraction_flags"
        ).fetchall()
        return {r["canonical_id"]: r for r in rows}
    except sqlite3.OperationalError:
        return {}


def _needs_check(flag: sqlite3.Row | None, max_age_days: int) -> bool:
    if flag is None:
        return True
    checked = flag["checked_at"]
    if not checked:
        return True
    try:
        dt = datetime.fromisoformat(checked)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return datetime.now(UTC) - dt > timedelta(days=max_age_days)
    except ValueError:
        return True


def cmd_list(args: argparse.Namespace) -> None:
    """List papers needing a retraction check (no DB writes)."""
    con = _open(args.project_id)
    all_ids = _all_cited_papers(con)
    if args.canonical_id:
        all_ids = [c for c in all_ids if c == args.canonical_id]
    flags = _existing_flags(con)
    to_check = [cid for cid in all_ids if _needs_check(flags.get(cid), args.max_age_days)]
    con.close()
    result = {
        "project_id": args.project_id,
        "total_papers": len(all_ids),
        "to_check": to_check,
        "already_current": len(all_ids) - len(to_check),
        "max_age_days": args.max_age_days,
        "mode": "dry_run" if args.dry_run else "list",
    }
    print(json.dumps(result, indent=2))


def cmd_persist(args: argparse.Namespace) -> None:
    """Persist MCP lookup results into retraction_flags."""
    results_path = Path(args.input)
    if not results_path.exists():
        raise SystemExit(f"input file not found: {results_path}")
    items = json.loads(results_path.read_text())
    if not isinstance(items, list):
        raise SystemExit("input must be a JSON array of {canonical_id, retracted, source, detail?}")

    con = _open(args.project_id)
    now = datetime.now(UTC).isoformat()
    saved = 0
    errors: list[str] = []

    with con:
        # Ensure table exists (may be absent in very old DBs)
        con.execute("""
            CREATE TABLE IF NOT EXISTS retraction_flags (
                flag_id      INTEGER PRIMARY KEY AUTOINCREMENT,
                canonical_id TEXT NOT NULL UNIQUE,
                retracted    INTEGER NOT NULL,
                source       TEXT NOT NULL,
                detail       TEXT,
                checked_at   TEXT NOT NULL
            )
        """)
        for item in items:
            cid = item.get("canonical_id")
            if not cid:
                errors.append("missing canonical_id")
                continue
            retracted = 1 if item.get("retracted") else 0
            source = item.get("source", "semantic-scholar")
            detail = item.get("detail")
            con.execute(
                "INSERT INTO retraction_flags "
                "(canonical_id, retracted, source, detail, checked_at) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(canonical_id) DO UPDATE SET "
                "retracted=excluded.retracted, source=excluded.source, "
                "detail=excluded.detail, checked_at=excluded.checked_at",
                (cid, retracted, source, detail, now),
            )
            saved += 1

    con.close()
    print(json.dumps({
        "saved": saved,
        "errors": errors,
        "project_id": args.project_id,
    }, indent=2))


def main() -> None:
    p = argparse.ArgumentParser(
        description="Scan project papers for retraction status."
    )
    p.add_argument("--project-id", required=True)
    p.add_argument("--canonical-id", default=None,
                   help="Check only this paper (default: all)")
    p.add_argument("--max-age-days", type=int, default=7,
                   help="Re-check papers checked more than N days ago (default: 7)")
    p.add_argument("--dry-run", action="store_true", default=False,
                   help="Print what would be checked; do not modify DB")
    p.add_argument("--input", default=None,
                   help="JSON results file to persist (from MCP lookup)")
    args = p.parse_args()

    if args.input:
        cmd_persist(args)
    else:
        cmd_list(args)


if __name__ == "__main__":
    main()
