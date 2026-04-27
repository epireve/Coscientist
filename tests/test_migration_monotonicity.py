"""v0.65d — migration version monotonicity invariants.

Asserts:
  1. ALL_VERSIONS is a strictly-increasing contiguous range starting at 1.
  2. Every entry in MIGRATIONS has a unique version number.
  3. After ensure_current() on a fresh coscientist DB, schema_versions
     rows match ALL_VERSIONS exactly (no skips, no extras).
  4. Running ensure_current() twice is a no-op the second time.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from tests.harness import TestCase, isolated_cache, run_tests
from lib.migrations import ALL_VERSIONS, MIGRATIONS, ensure_current


_REPO = Path(__file__).resolve().parents[1]
_SCHEMA = _REPO / "lib" / "sqlite_schema.sql"


def _new_coscientist_db(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.executescript(_SCHEMA.read_text())
    con.close()
    return path


class MigrationMonotonicityTests(TestCase):
    def test_all_versions_starts_at_one(self):
        self.assertEqual(ALL_VERSIONS[0], 1)

    def test_all_versions_strictly_increasing(self):
        for a, b in zip(ALL_VERSIONS, ALL_VERSIONS[1:]):
            self.assertLess(a, b,
                            f"versions not strictly increasing: {a} >= {b}")

    def test_all_versions_contiguous(self):
        # No gaps between consecutive versions.
        for a, b in zip(ALL_VERSIONS, ALL_VERSIONS[1:]):
            self.assertEqual(b - a, 1,
                             f"version gap: {a} -> {b}")

    def test_migrations_list_versions_unique(self):
        versions = [v for (v, _, _) in MIGRATIONS]
        self.assertEqual(len(versions), len(set(versions)),
                         f"duplicate version in MIGRATIONS: {versions}")

    def test_migrations_subset_of_all_versions(self):
        # Every SQL-based migration version must appear in ALL_VERSIONS.
        for (v, name, _) in MIGRATIONS:
            self.assertIn(
                v, ALL_VERSIONS,
                f"MIGRATIONS version {v} ({name!r}) not in ALL_VERSIONS",
            )

    def test_fresh_db_applies_all_versions(self):
        with isolated_cache() as root:
            db = _new_coscientist_db(root / "fresh.db")
            ensure_current(db)
            con = sqlite3.connect(db)
            try:
                rows = con.execute(
                    "SELECT version FROM schema_versions ORDER BY version"
                ).fetchall()
                applied = tuple(r[0] for r in rows)
            finally:
                con.close()
            self.assertEqual(
                applied, ALL_VERSIONS,
                f"applied versions {applied} != ALL_VERSIONS {ALL_VERSIONS}",
            )

    def test_ensure_current_idempotent(self):
        with isolated_cache() as root:
            db = _new_coscientist_db(root / "idem.db")
            first = ensure_current(db)
            second = ensure_current(db)
            self.assertEqual(second, [],
                             f"second ensure_current should be no-op, "
                             f"got {second}")
            # First call returned every version since fresh DB had none.
            self.assertEqual(tuple(first), ALL_VERSIONS)


if __name__ == "__main__":
    raise SystemExit(run_tests(MigrationMonotonicityTests))
