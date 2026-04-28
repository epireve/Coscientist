"""DB notify helper (v0.57).

Every skill that writes rows to a Coscientist DB calls
`record_write(con, table, n_rows, skill, run_id=, detail=)`. This:

  1. Inserts a row into `db_writes` audit table (if it exists).
  2. Returns a structured dict the caller can print to stdout/stderr
     so the user (and any orchestrating agent) sees:
         "[db-notify] wrote 3 rows in `gap_analyses` (skill=gap-analyzer)"

Keeps DB persistence visible. Closes the gap where v0.51-v0.56 skills
wrote files only and the user couldn't tell what landed where.

Pure stdlib. Safe to call from any skill — silently no-ops if the
db_writes table is missing (older DBs without migration v9).
"""
from __future__ import annotations

import sqlite3
from datetime import UTC, datetime


def record_write(
    con: sqlite3.Connection,
    target_table: str,
    n_rows: int,
    skill_or_lib: str,
    *,
    run_id: str | None = None,
    detail: str | None = None,
) -> dict:
    """Append to db_writes; return a structured notification.

    Args:
        con: open sqlite3 connection to a coscientist DB
        target_table: name of the table that just received writes
        n_rows: number of rows inserted
        skill_or_lib: identifier of caller (e.g. "wide-research", "debate")
        run_id: optional scoping (run_id, wide_run_id, debate_id, project_id)
        detail: free-text — fits cleanly in audit summary

    Returns:
        dict with notification fields. The caller is responsible for
        emitting it (typically via json.dumps to stdout, or
        format_notification() for human-readable).
    """
    now = datetime.now(UTC).isoformat()
    note = {
        "kind": "db-notify",
        "target_table": target_table,
        "n_rows": n_rows,
        "skill_or_lib": skill_or_lib,
        "run_id": run_id,
        "detail": detail,
        "at": now,
    }
    if not _table_exists(con, "db_writes"):
        # Older DB without migration v9 — return note but don't crash
        note["persisted"] = False
        return note
    with con:
        con.execute(
            "INSERT INTO db_writes "
            "(target_table, n_rows, skill_or_lib, run_id, detail, at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (target_table, n_rows, skill_or_lib, run_id, detail, now),
        )
    note["persisted"] = True
    return note


def format_notification(note: dict) -> str:
    """Render a notification dict as a one-line human-readable string."""
    table = note.get("target_table", "?")
    n = note.get("n_rows", 0)
    skill = note.get("skill_or_lib", "?")
    parts = [f"[db-notify] wrote {n} row{'s' if n != 1 else ''} in `{table}`",
             f"(skill={skill})"]
    rid = note.get("run_id")
    if rid:
        parts.append(f"run={rid}")
    detail = note.get("detail")
    if detail:
        parts.append(f"— {detail}")
    if note.get("persisted") is False:
        parts.append("(audit row NOT persisted — DB pre-v0.57)")
    return " ".join(parts)


def summarize_writes(
    con: sqlite3.Connection,
    *,
    run_id: str | None = None,
    skill_or_lib: str | None = None,
    since: str | None = None,
) -> list[dict]:
    """Read db_writes rows. Pure read-only.

    Returns list of {target_table, total_rows, n_writes, last_at}.
    Filterable by run_id / skill / time cutoff (ISO timestamp).
    """
    if not _table_exists(con, "db_writes"):
        return []
    where = []
    params: list = []
    if run_id is not None:
        where.append("run_id = ?")
        params.append(run_id)
    if skill_or_lib is not None:
        where.append("skill_or_lib = ?")
        params.append(skill_or_lib)
    if since is not None:
        where.append("at >= ?")
        params.append(since)
    where_clause = (" WHERE " + " AND ".join(where)) if where else ""
    rows = con.execute(
        "SELECT target_table, SUM(n_rows) AS total_rows, "
        "COUNT(*) AS n_writes, MAX(at) AS last_at "
        f"FROM db_writes{where_clause} "
        "GROUP BY target_table ORDER BY total_rows DESC",
        params,
    ).fetchall()
    return [
        {
            "target_table": r[0],
            "total_rows": int(r[1] or 0),
            "n_writes": int(r[2] or 0),
            "last_at": r[3],
        }
        for r in rows
    ]


def per_table_counts(con: sqlite3.Connection) -> dict[str, int]:
    """Live row counts across all user tables in this DB.

    Useful for the audit-query 'records' subcommand. Excludes
    schema_versions + sqlite_* internals.
    """
    rows = con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%' AND name != 'schema_versions' "
        "ORDER BY name"
    ).fetchall()
    out: dict[str, int] = {}
    for (name,) in rows:
        try:
            n = con.execute(
                f"SELECT COUNT(*) FROM \"{name}\""
            ).fetchone()[0]
            out[name] = int(n)
        except sqlite3.Error:
            out[name] = -1
    return out


def prune_writes(
    con: sqlite3.Connection,
    *,
    keep_last_n: int | None = None,
    older_than: str | None = None,
) -> dict:
    """v0.69 — bounded retention for db_writes.

    Deletes rows that fall outside the retention window. Two modes
    (combinable):
      keep_last_n: keep only the N newest rows (by `at` timestamp).
      older_than: delete every row with `at < older_than`.

    Returns: {deleted: N, remaining: M, table_present: bool}.
    Idempotent. Read-only when both args are None.
    """
    if not _table_exists(con, "db_writes"):
        return {"deleted": 0, "remaining": 0, "table_present": False}
    if keep_last_n is None and older_than is None:
        n = con.execute("SELECT COUNT(*) FROM db_writes").fetchone()[0]
        return {"deleted": 0, "remaining": int(n), "table_present": True}

    deleted = 0
    with con:
        if older_than is not None:
            cur = con.execute(
                "DELETE FROM db_writes WHERE at < ?",
                (older_than,),
            )
            deleted += cur.rowcount or 0
        if keep_last_n is not None and keep_last_n >= 0:
            # Keep the N newest by at; delete older. Use write_id (PK,
            # autoincrement) for tiebreaks on equal timestamps.
            cur = con.execute(
                "DELETE FROM db_writes WHERE write_id NOT IN ("
                "  SELECT write_id FROM db_writes "
                "  ORDER BY at DESC, write_id DESC LIMIT ?"
                ")",
                (keep_last_n,),
            )
            deleted += cur.rowcount or 0

    remaining = con.execute("SELECT COUNT(*) FROM db_writes").fetchone()[0]
    return {
        "deleted": deleted,
        "remaining": int(remaining),
        "table_present": True,
    }


def prune_writes_all_dbs(
    cache_root,
    *,
    keep_last_n: int | None = None,
    older_than: str | None = None,
) -> dict:
    """v0.80 — sweep prune_writes across every coscientist DB.

    Walks ~/.cache/coscientist/runs/*.db + projects/*/project.db,
    applies the same retention rules to each. Read-only on DBs that
    don't have the db_writes table yet.

    Returns: {dbs_scanned, total_deleted, total_remaining,
              per_db: [{path, deleted, remaining}, ...]}.
    """
    from pathlib import Path
    root = Path(cache_root)
    candidates: list[Path] = []
    runs_dir = root / "runs"
    if runs_dir.exists():
        candidates.extend(p for p in runs_dir.glob("*.db") if p.is_file())
    projects_dir = root / "projects"
    if projects_dir.exists():
        for proj in projects_dir.iterdir():
            db = proj / "project.db"
            if db.exists():
                candidates.append(db)
    per_db: list[dict] = []
    total_deleted = 0
    total_remaining = 0
    for db_path in sorted(candidates):
        try:
            con = sqlite3.connect(db_path)
        except sqlite3.Error:
            continue
        try:
            res = prune_writes(
                con, keep_last_n=keep_last_n, older_than=older_than,
            )
        finally:
            con.close()
        per_db.append({
            "path": str(db_path),
            "deleted": res.get("deleted", 0),
            "remaining": res.get("remaining", 0),
            "table_present": res.get("table_present", False),
        })
        total_deleted += res.get("deleted", 0)
        total_remaining += res.get("remaining", 0)
    return {
        "dbs_scanned": len(candidates),
        "total_deleted": total_deleted,
        "total_remaining": total_remaining,
        "per_db": per_db,
    }


def _table_exists(con: sqlite3.Connection, name: str) -> bool:
    row = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    return row is not None
