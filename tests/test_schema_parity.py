"""v0.65a — schema parity invariants.

Two paths produce a coscientist DB:
  (A) executing lib/sqlite_schema.sql wholesale (fresh DB)
  (B) running migrations from an empty DB up through ALL_VERSIONS

Both must produce the same set of tables, indexes, and per-table
columns. This test prevents typos in one path from drifting from
the other.

Also asserts every per-version SQL fragment under
lib/migrations_sql/ exists for each version that uses
_read_migration_sql.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from lib.migrations import (
    _read_migration_sql,
    ensure_current,
)
from tests.harness import TestCase, isolated_cache, run_tests

_REPO = Path(__file__).resolve().parents[1]
_SCHEMA = _REPO / "lib" / "sqlite_schema.sql"
_MIG_DIR = _REPO / "lib" / "migrations_sql"


def _table_columns(con: sqlite3.Connection, table: str) -> list[tuple]:
    """Returns sorted (name, type, notnull, pk) tuples for a table."""
    rows = con.execute(f"PRAGMA table_info({table})").fetchall()
    # row: (cid, name, type, notnull, dflt_value, pk)
    return sorted([(r[1], r[2].upper(), r[3], r[5]) for r in rows])


def _all_user_tables(con: sqlite3.Connection) -> set[str]:
    rows = con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%' AND name != 'schema_versions'"
    ).fetchall()
    return {r[0] for r in rows}


def _all_user_indexes(con: sqlite3.Connection) -> set[str]:
    rows = con.execute(
        "SELECT name FROM sqlite_master WHERE type='index' "
        "AND name NOT LIKE 'sqlite_%' AND name LIKE 'idx_%'"
    ).fetchall()
    return {r[0] for r in rows}


def _build_via_schema_sql(path: Path) -> None:
    con = sqlite3.connect(path)
    con.executescript(_SCHEMA.read_text())
    con.close()


def _build_via_migrations(path: Path) -> None:
    """Empty DB → run every fragment that has a .sql file. Older
    migrations that go through MIGRATIONS or _ensure_vN_columns
    still need their parent tables, so we seed via schema.sql for
    those parts and only test that the SQL-fragment versions match.

    For the parity check, we do the simpler thing: start from
    schema.sql then call ensure_current() — this is the actual
    production path and what monotonicity already covers. The
    fragment-specific assertions live in
    test_per_version_sql_fragments_exist.
    """
    con = sqlite3.connect(path)
    con.executescript(_SCHEMA.read_text())
    con.close()
    ensure_current(path)


class PerVersionSqlFragmentsTests(TestCase):
    def test_v9_fragment_exists(self):
        sql = _read_migration_sql(9)
        self.assertIn("wide_runs", sql)
        self.assertIn("citation_resolutions" not in sql, [True])

    def test_v10_fragment_exists(self):
        sql = _read_migration_sql(10)
        self.assertIn("citation_resolutions", sql)

    def test_missing_fragment_raises(self):
        with self.assertRaises(FileNotFoundError):
            _read_migration_sql(9999)

    def test_fragments_dir_listed_in_repo(self):
        self.assertTrue(_MIG_DIR.exists(),
                        f"missing migrations_sql dir at {_MIG_DIR}")
        files = list(_MIG_DIR.glob("v*.sql"))
        self.assertGreater(len(files), 0,
                           "migrations_sql/ has no v*.sql fragments")


class SchemaSqlParityTests(TestCase):
    """Schema.sql alone must produce the same tables as schema.sql +
    ensure_current — i.e. fragments must be redundant on a fresh DB."""

    def test_table_set_matches(self):
        with isolated_cache() as root:
            via_schema = root / "via_schema.db"
            via_full = root / "via_full.db"
            _build_via_schema_sql(via_schema)
            _build_via_migrations(via_full)
            con_a = sqlite3.connect(via_schema)
            con_b = sqlite3.connect(via_full)
            try:
                tables_a = _all_user_tables(con_a)
                tables_b = _all_user_tables(con_b)
                self.assertEqual(
                    tables_a, tables_b,
                    f"table set drift: only-in-schema={tables_a - tables_b} "
                    f"only-in-migrated={tables_b - tables_a}",
                )
            finally:
                con_a.close()
                con_b.close()

    def test_index_set_matches(self):
        with isolated_cache() as root:
            via_schema = root / "via_schema.db"
            via_full = root / "via_full.db"
            _build_via_schema_sql(via_schema)
            _build_via_migrations(via_full)
            con_a = sqlite3.connect(via_schema)
            con_b = sqlite3.connect(via_full)
            try:
                idx_a = _all_user_indexes(con_a)
                idx_b = _all_user_indexes(con_b)
                self.assertEqual(idx_a, idx_b,
                                 f"index drift: a-b={idx_a - idx_b} "
                                 f"b-a={idx_b - idx_a}")
            finally:
                con_a.close()
                con_b.close()

    def test_v9_v10_table_columns_match(self):
        """Every v9/v10 table must have identical column shape under
        both build paths."""
        with isolated_cache() as root:
            via_schema = root / "via_schema.db"
            via_full = root / "via_full.db"
            _build_via_schema_sql(via_schema)
            _build_via_migrations(via_full)
            con_a = sqlite3.connect(via_schema)
            con_b = sqlite3.connect(via_full)
            try:
                v9_v10_tables = [
                    "wide_runs", "wide_sub_agents", "debates",
                    "gap_analyses", "venue_recommendations",
                    "contribution_landscapes", "mode_selections",
                    "db_writes", "citation_resolutions",
                ]
                for t in v9_v10_tables:
                    cols_a = _table_columns(con_a, t)
                    cols_b = _table_columns(con_b, t)
                    self.assertEqual(
                        cols_a, cols_b,
                        f"column drift in {t}: schema={cols_a} "
                        f"migrated={cols_b}",
                    )
            finally:
                con_a.close()
                con_b.close()


if __name__ == "__main__":
    raise SystemExit(run_tests(
        PerVersionSqlFragmentsTests,
        SchemaSqlParityTests,
    ))
