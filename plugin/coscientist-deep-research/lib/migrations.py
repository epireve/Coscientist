"""v0.13 — schema migration framework.

SQLite has no `ALTER TABLE IF NOT EXISTS` and limited DDL. We track
applied migrations in a `schema_versions` table and apply only the
unapplied ones on connect.

Each migration is a Python tuple `(version: int, name: str, sql: str)`.
Migrations run in version-ascending order. Once applied, a migration's
row in `schema_versions` records its name + applied_at.

Usage:
    from lib.migrations import ensure_current
    ensure_current(db_path)  # applies any unapplied migrations

This module is intentionally tiny — no migration generator, no rollback.
The base schema in `lib/sqlite_schema.sql` is still the source of truth
for fresh DBs. Migrations are *additive only* and used to bring older
DBs forward without reinitializing.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

# Each entry: (version, name, sql to apply)
# Add new migrations to the end. Never edit or reorder existing entries.
MIGRATIONS: list[tuple[int, str, str]] = [
    # Example migration. Real migrations land here as the schema evolves
    # post-v0.12.1. Until then, this list documents the framework.
    (1, "v0.13_schema_versions_init", """
        -- This migration is implicit: ensure_current() creates the
        -- schema_versions table itself before applying any migrations.
        -- Recorded here for traceability; the SQL below is a no-op.
        SELECT 1;
    """),
    (2, "v0.28_overnight_column", """
        -- Add overnight flag to runs table.
        -- SQLite does not support IF NOT EXISTS on ALTER TABLE, so we rely
        -- on the migration framework to call this exactly once per DB.
        ALTER TABLE runs ADD COLUMN overnight INTEGER NOT NULL DEFAULT 0;
    """),
    (3, "v0.38_evolution_rounds", """
        -- Tournament evolve-loop ledger. One row per round.
        CREATE TABLE IF NOT EXISTS evolution_rounds (
            round_id        INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id          TEXT NOT NULL,
            round_index     INTEGER NOT NULL,
            top_hyp_id      TEXT,
            top_elo         REAL,
            n_hypotheses    INTEGER NOT NULL,
            n_matches       INTEGER NOT NULL,
            n_new_children  INTEGER NOT NULL DEFAULT 0,
            plateau_count   INTEGER NOT NULL DEFAULT 0,
            started_at      TEXT NOT NULL,
            closed_at       TEXT,
            UNIQUE(run_id, round_index)
        );
        CREATE INDEX IF NOT EXISTS idx_evo_rounds_run
            ON evolution_rounds(run_id);
    """),
]


SCHEMA_VERSIONS_DDL = """
CREATE TABLE IF NOT EXISTS schema_versions (
    version    INTEGER PRIMARY KEY,
    name       TEXT NOT NULL,
    applied_at TEXT NOT NULL
);
"""


def applied_versions(db_path: Path) -> set[int]:
    """Return the set of migration versions already applied to this DB."""
    if not db_path.exists():
        return set()
    con = sqlite3.connect(db_path)
    try:
        con.execute(SCHEMA_VERSIONS_DDL)
        rows = con.execute("SELECT version FROM schema_versions").fetchall()
    finally:
        con.close()
    return {r[0] for r in rows}


def ensure_current(db_path: Path,
                   migrations: list[tuple[int, str, str]] = MIGRATIONS) -> list[int]:
    """Apply any migrations whose version is not yet recorded.

    Returns the list of versions newly applied (empty if already current).
    Idempotent: safe to call on every DB open.
    """
    if not db_path.exists():
        # Fresh DB — caller is responsible for the base schema. We just
        # ensure the schema_versions table exists so future migrations work.
        db_path.parent.mkdir(parents=True, exist_ok=True)

    con = sqlite3.connect(db_path)
    newly_applied: list[int] = []
    try:
        con.execute(SCHEMA_VERSIONS_DDL)
        applied = {r[0] for r in con.execute("SELECT version FROM schema_versions")}
        now = datetime.now(UTC).isoformat()
        for version, name, sql in sorted(migrations, key=lambda m: m[0]):
            if version in applied:
                continue
            with con:
                con.executescript(sql)
                con.execute(
                    "INSERT INTO schema_versions (version, name, applied_at) "
                    "VALUES (?, ?, ?)",
                    (version, name, now),
                )
            newly_applied.append(version)
    finally:
        con.close()
    return newly_applied


def current_version(db_path: Path) -> int:
    """Highest applied version, or 0 if none."""
    versions = applied_versions(db_path)
    return max(versions) if versions else 0
