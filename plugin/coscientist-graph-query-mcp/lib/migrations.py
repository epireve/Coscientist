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
    # v0.57 — persistence tables for v0.51-v0.56 outputs (Wide Research,
    # debate, A5 trio, mode selector, db-notify audit). Same idempotent
    # pattern via _ensure_v9_tables(); skips if base sqlite_schema.sql
    # already created them.
]


SCHEMA_VERSIONS_DDL = """
CREATE TABLE IF NOT EXISTS schema_versions (
    version    INTEGER PRIMARY KEY,
    name       TEXT NOT NULL,
    applied_at TEXT NOT NULL
);
"""


# v0.65d — every version emitted by `ensure_current`, including
# in-code-only migrations (v4..v8 add columns via `_ensure_vN_columns`,
# v9..v10 add tables via `_ensure_vN_tables`). Kept as a single list
# so the monotonicity test can assert no version is silently skipped
# between the SQL-based MIGRATIONS list and the in-code migrations.
ALL_VERSIONS: tuple[int, ...] = (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15)


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

        # v0.57 persistence tables for v0.51-v0.56 outputs.
        # Skip on generic test DBs that don't carry the coscientist
        # base schema (no runs/papers_in_run/projects). These appear
        # in unit tests that pass custom migration lists.
        is_coscientist_db = (
            _table_exists(con, "runs")
            or _table_exists(con, "papers_in_run")
            or _table_exists(con, "projects")
        )
        if 9 not in applied and is_coscientist_db:
            _ensure_v9_tables(con)
            with con:
                con.execute(
                    "INSERT INTO schema_versions (version, name, applied_at) "
                    "VALUES (?, ?, ?)",
                    (9, "v0.57_persistence_for_recent_skills", now),
                )
            newly_applied.append(9)

        # v0.63 — citation_resolutions table for resolve-citation skill.
        # Same coscientist-DB guard as v9.
        if 10 not in applied and is_coscientist_db:
            _ensure_v10_tables(con)
            with con:
                con.execute(
                    "INSERT INTO schema_versions (version, name, applied_at) "
                    "VALUES (?, ?, ?)",
                    (10, "v0.63_citation_resolutions", now),
                )
            newly_applied.append(10)

        # v0.89 — execution traces (OpenTelemetry-style spans).
        if 11 not in applied and is_coscientist_db:
            _ensure_v11_tables(con)
            with con:
                con.execute(
                    "INSERT INTO schema_versions (version, name, applied_at) "
                    "VALUES (?, ?, ?)",
                    (11, "v0.89_execution_traces", now),
                )
            newly_applied.append(11)

        # v0.92 — agent quality scoring.
        if 12 not in applied and is_coscientist_db:
            _ensure_v12_tables(con)
            with con:
                con.execute(
                    "INSERT INTO schema_versions (version, name, applied_at) "
                    "VALUES (?, ?, ?)",
                    (12, "v0.92_agent_quality", now),
                )
            newly_applied.append(12)

        # v0.148 — institution + funder graph node kinds. Project-DB
        # only: gates on graph_nodes existence (project DBs have it,
        # run DBs do not).
        if 13 not in applied and _table_exists(con, "graph_nodes"):
            _ensure_v13_columns(con)
            _ensure_v13_indexes(con)
            with con:
                con.execute(
                    "INSERT INTO schema_versions (version, name, applied_at) "
                    "VALUES (?, ?, ?)",
                    (13, "v0.148_graph_institutions_funders", now),
                )
            newly_applied.append(13)

        # v0.153 — idea-tree columns on hypotheses (tree_id, depth,
        # branch_index) + composite index. Run-DB only: gates on
        # `hypotheses` table existence, so project DBs and unrelated
        # test DBs are unaffected.
        if 14 not in applied and _table_exists(con, "hypotheses"):
            _ensure_v14_columns(con)
            _ensure_v14_indexes(con)
            with con:
                con.execute(
                    "INSERT INTO schema_versions (version, name, applied_at) "
                    "VALUES (?, ?, ?)",
                    (14, "v0.153_hypotheses_idea_tree", now),
                )
            newly_applied.append(14)

        # v0.154 — thinking_log_json column on the four verdict-producing
        # tables (hypotheses, attack_findings, novelty_assessments,
        # publishability_verdicts) + partial index on hypotheses. Gates
        # on any of those tables existing so project DBs and unrelated
        # test DBs aren't touched.
        v15_gate = (
            _table_exists(con, "hypotheses")
            or _table_exists(con, "attack_findings")
            or _table_exists(con, "novelty_assessments")
            or _table_exists(con, "publishability_verdicts")
        )
        if 15 not in applied and v15_gate:
            _ensure_v15_columns(con)
            _ensure_v15_indexes(con)
            with con:
                con.execute(
                    "INSERT INTO schema_versions (version, name, applied_at) "
                    "VALUES (?, ?, ?)",
                    (15, "v0.154_thinking_log_json", now),
                )
            newly_applied.append(15)
    finally:
        con.close()
    return newly_applied


_MIG_SQL_DIR = Path(__file__).resolve().parent / "migrations_sql"


def _read_migration_sql(version: int) -> str:
    """Load v{N}.sql from lib/migrations_sql/. v0.65a — single source
    of DDL shared with lib/sqlite_schema.sql."""
    path = _MIG_SQL_DIR / f"v{version}.sql"
    if not path.exists():
        raise FileNotFoundError(
            f"migration SQL missing: {path} — every version that goes "
            f"through _read_migration_sql needs a sibling .sql file"
        )
    return path.read_text()


def _ensure_v9_tables(con: sqlite3.Connection) -> None:
    """v0.57 persistence tables. DDL loaded from migrations_sql/v9.sql
    (v0.65a — single source of DDL). All statements use IF NOT EXISTS,
    idempotent on fresh DBs that already have the tables."""
    with con:
        con.executescript(_read_migration_sql(9))


def _ensure_v10_tables(con: sqlite3.Connection) -> None:
    """v0.63 citation_resolutions table. DDL loaded from
    migrations_sql/v10.sql (v0.65a — single source of DDL).
    """
    with con:
        con.executescript(_read_migration_sql(10))


def _ensure_v11_tables(con: sqlite3.Connection) -> None:
    """v0.89 — execution traces (traces, spans, span_events).
    DDL in migrations_sql/v11.sql.
    """
    with con:
        con.executescript(_read_migration_sql(11))


def _ensure_v12_tables(con: sqlite3.Connection) -> None:
    """v0.92 — agent_quality table. DDL in migrations_sql/v12.sql."""
    with con:
        con.executescript(_read_migration_sql(12))


def _ensure_v13_columns(con: sqlite3.Connection) -> None:
    """v0.148 — graph_nodes.external_ids_json + graph_nodes.source.

    Stores all data provided by every source: openalex_id, ror_id, doi,
    arxiv_id, pmid, orcid, s2_corpus_id, semanticscholar_id, mag_id, ...
    `source` records which source last wrote this node.
    """
    cols = [r[1] for r in con.execute("PRAGMA table_info(graph_nodes)")]
    if "external_ids_json" not in cols:
        with con:
            con.execute(
                "ALTER TABLE graph_nodes ADD COLUMN external_ids_json TEXT"
            )
    if "source" not in cols:
        with con:
            con.execute(
                "ALTER TABLE graph_nodes ADD COLUMN source TEXT"
            )


def _ensure_v13_indexes(con: sqlite3.Connection) -> None:
    """v0.148 — partial indexes for institution/funder kinds + new
    relations. DDL in migrations_sql/v13.sql.
    """
    with con:
        con.executescript(_read_migration_sql(13))


def _ensure_v14_columns(con: sqlite3.Connection) -> None:
    """v0.153 — idea-tree columns on hypotheses.

    Adds tree_id (root grouping), depth (root=0, children=1, ...),
    and branch_index (sibling order within parent). Idempotent.
    """
    if not _table_exists(con, "hypotheses"):
        return
    cols = {row[1] for row in con.execute("PRAGMA table_info(hypotheses)")}
    with con:
        if "tree_id" not in cols:
            con.execute(
                "ALTER TABLE hypotheses ADD COLUMN tree_id TEXT"
            )
        if "depth" not in cols:
            con.execute(
                "ALTER TABLE hypotheses ADD COLUMN "
                "depth INTEGER NOT NULL DEFAULT 0"
            )
        if "branch_index" not in cols:
            con.execute(
                "ALTER TABLE hypotheses ADD COLUMN "
                "branch_index INTEGER NOT NULL DEFAULT 0"
            )


def _ensure_v14_indexes(con: sqlite3.Connection) -> None:
    """v0.153 — idx_hypotheses_tree_depth composite index. DDL in
    migrations_sql/v14.sql.
    """
    with con:
        con.executescript(_read_migration_sql(14))


_V15_TABLES: tuple[str, ...] = (
    "hypotheses",
    "attack_findings",
    "novelty_assessments",
    "publishability_verdicts",
)


def _ensure_v15_columns(con: sqlite3.Connection) -> None:
    """v0.154 — add `thinking_log_json TEXT` to the four verdict-
    producing tables. Idempotent: each ALTER guarded by a
    PRAGMA table_info check, and a missing target table is a no-op.
    """
    for tbl in _V15_TABLES:
        if not _table_exists(con, tbl):
            continue
        cols = {row[1] for row in con.execute(f"PRAGMA table_info({tbl})")}
        if "thinking_log_json" not in cols:
            with con:
                con.execute(
                    f"ALTER TABLE {tbl} ADD COLUMN thinking_log_json TEXT"
                )


def _ensure_v15_indexes(con: sqlite3.Connection) -> None:
    """v0.154 — partial index on hypotheses(hyp_id) WHERE
    thinking_log_json IS NOT NULL. Skips silently when the
    `hypotheses` table is absent so the index DDL doesn't error
    on partial DBs.
    """
    if not _table_exists(con, "hypotheses"):
        return
    with con:
        con.executescript(_read_migration_sql(15))


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
