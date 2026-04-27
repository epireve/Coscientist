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
    # v0.50.4 — papers_in_run audit-log columns. Handled in code below
    # via _ensure_v4_columns() because base sqlite_schema.sql also lists
    # them (fresh DB), and SQLite ALTER TABLE has no IF NOT EXISTS guard.
    # v0.52.1 — runs.search_strategy_json. Same idempotent-in-code
    # pattern via _ensure_v5_columns().
    # v0.52.2 — runs.strategy_critique_json. Same pattern via
    # _ensure_v6_columns().
    # v0.52.4 — papers_in_run.disagreement_score. Pattern via
    # _ensure_v7_columns().
    # v0.53.5 — runs.parent_run_id + runs.seed_mode for Wide → Deep
    # handoff lineage. Pattern via _ensure_v8_columns().
]


SCHEMA_VERSIONS_DDL = """
CREATE TABLE IF NOT EXISTS schema_versions (
    version    INTEGER PRIMARY KEY,
    name       TEXT NOT NULL,
    applied_at TEXT NOT NULL
);
"""


def _table_exists(con: sqlite3.Connection, name: str) -> bool:
    row = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    return row is not None


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

        # v0.50.4 audit-log columns — idempotent in-code migration.
        # Only record version if the target table exists in this DB; a
        # custom-migrations DB (e.g. unit test) without papers_in_run
        # should not be marked as having applied this baseline.
        if 4 not in applied and _table_exists(con, "papers_in_run"):
            _ensure_v4_columns(con)
            with con:
                con.execute(
                    "INSERT INTO schema_versions (version, name, applied_at) "
                    "VALUES (?, ?, ?)",
                    (4, "v0.50.4_papers_in_run_audit_columns", now),
                )
            newly_applied.append(4)

        # v0.52.1 search-strategy column on runs — same idempotent path
        if 5 not in applied and _table_exists(con, "runs"):
            _ensure_v5_columns(con)
            with con:
                con.execute(
                    "INSERT INTO schema_versions (version, name, applied_at) "
                    "VALUES (?, ?, ?)",
                    (5, "v0.52.1_runs_search_strategy", now),
                )
            newly_applied.append(5)

        # v0.52.2 strategy-critique column on runs
        if 6 not in applied and _table_exists(con, "runs"):
            _ensure_v6_columns(con)
            with con:
                con.execute(
                    "INSERT INTO schema_versions (version, name, applied_at) "
                    "VALUES (?, ?, ?)",
                    (6, "v0.52.2_runs_strategy_critique", now),
                )
            newly_applied.append(6)

        # v0.52.4 disagreement-score column on papers_in_run
        if 7 not in applied and _table_exists(con, "papers_in_run"):
            _ensure_v7_columns(con)
            with con:
                con.execute(
                    "INSERT INTO schema_versions (version, name, applied_at) "
                    "VALUES (?, ?, ?)",
                    (7, "v0.52.4_papers_in_run_disagreement", now),
                )
            newly_applied.append(7)

        # v0.53.5 Wide → Deep handoff lineage on runs
        if 8 not in applied and _table_exists(con, "runs"):
            _ensure_v8_columns(con)
            with con:
                con.execute(
                    "INSERT INTO schema_versions (version, name, applied_at) "
                    "VALUES (?, ?, ?)",
                    (8, "v0.53.5_runs_parent_and_seed_mode", now),
                )
            newly_applied.append(8)
    finally:
        con.close()
    return newly_applied


def _ensure_v8_columns(con: sqlite3.Connection) -> None:
    """Add parent_run_id + seed_mode to runs if missing.

    v0.53.5 — Wide → Deep handoff lineage. parent_run_id points back
    at the Wide run that seeded this Deep run; seed_mode records the
    handoff level (none|abstract|full-text|cumulative).
    """
    if not _table_exists(con, "runs"):
        return
    cols = {row[1] for row in con.execute("PRAGMA table_info(runs)")}
    with con:
        if "parent_run_id" not in cols:
            con.execute(
                "ALTER TABLE runs ADD COLUMN parent_run_id TEXT"
            )
        if "seed_mode" not in cols:
            con.execute(
                "ALTER TABLE runs ADD COLUMN seed_mode TEXT"
            )


def _ensure_v7_columns(con: sqlite3.Connection) -> None:
    """Add disagreement_score to papers_in_run if missing.

    v0.52.4 — cross-persona disagreement signal. Papers surfaced by
    some personas but missed by others are high-leverage. Score in
    [0, 1] computed by lib.disagreement; persisted here for steward
    + weaver to surface in brief.
    """
    if not _table_exists(con, "papers_in_run"):
        return
    cols = {row[1] for row in con.execute("PRAGMA table_info(papers_in_run)")}
    with con:
        if "disagreement_score" not in cols:
            con.execute(
                "ALTER TABLE papers_in_run ADD COLUMN disagreement_score REAL"
            )


def _ensure_v6_columns(con: sqlite3.Connection) -> None:
    """Add strategy_critique_json to runs if missing.

    v0.52.2 — captures adversarial critique of the search strategy
    from the search-strategy-critique skill. Inquisitor attacks the
    decomposition before Phase 1 fires.
    """
    if not _table_exists(con, "runs"):
        return
    cols = {row[1] for row in con.execute("PRAGMA table_info(runs)")}
    with con:
        if "strategy_critique_json" not in cols:
            con.execute(
                "ALTER TABLE runs ADD COLUMN strategy_critique_json TEXT"
            )


def _ensure_v5_columns(con: sqlite3.Connection) -> None:
    """Add search_strategy_json to runs if missing.

    v0.52.1 — captures framework selection (PICO/SPIDER/Decomposition)
    + sub-area decomposition declared at Break 0. Persona harvests
    read this to gate which sub-area they cover.
    """
    if not _table_exists(con, "runs"):
        return
    cols = {row[1] for row in con.execute("PRAGMA table_info(runs)")}
    with con:
        if "search_strategy_json" not in cols:
            con.execute(
                "ALTER TABLE runs ADD COLUMN search_strategy_json TEXT"
            )


def _ensure_v4_columns(con: sqlite3.Connection) -> None:
    """Add harvest_count + cites_per_year to papers_in_run if missing.

    Inspired by Consensus's official skills (April 2026): repeat-hit signal
    + cites-per-year heuristic surface foundational papers mechanically.
    Fresh DBs already have these via sqlite_schema.sql; older DBs need them
    bolted on. Both paths recorded as v4 in schema_versions.
    """
    if not _table_exists(con, "papers_in_run"):
        return
    cols = {row[1] for row in con.execute("PRAGMA table_info(papers_in_run)")}
    with con:
        if "harvest_count" not in cols:
            con.execute(
                "ALTER TABLE papers_in_run ADD COLUMN "
                "harvest_count INTEGER NOT NULL DEFAULT 1"
            )
        if "cites_per_year" not in cols:
            con.execute(
                "ALTER TABLE papers_in_run ADD COLUMN cites_per_year REAL"
            )


def current_version(db_path: Path) -> int:
    """Highest applied version, or 0 if none."""
    versions = applied_versions(db_path)
    return max(versions) if versions else 0
