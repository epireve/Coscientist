"""v0.168 — schema_versions monotonicity + completeness asserts.

Catches three silent-skip bugs in `lib/migrations.py`:

1. ALL_VERSIONS skips a number (e.g. 1,2,4 — missing 3).
2. ALL_VERSIONS contains duplicates.
3. A `_ensure_vN_columns` / `_ensure_vN_tables` / `_ensure_vN_indexes`
   helper exists in code, or a `migrations_sql/vN.sql` file exists on
   disk, but `N` isn't in ALL_VERSIONS — meaning the migration is
   silently dead code (or worse, the test for it doesn't fire).
4. ALL_VERSIONS contains an N for which neither an SQL file nor an
   in-code helper exists.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from tests import _shim  # noqa: F401
from tests.harness import TestCase, run_tests

_REPO = Path(__file__).resolve().parent.parent
_LIB = _REPO / "lib"


class SchemaVersionsMonotonicityTests(TestCase):

    def setUp(self):
        self._mig_text = (_LIB / "migrations.py").read_text()
        self._sql_dir = _LIB / "migrations_sql"
        # Import inside test methods to avoid module-level side effects
        # if migrations.py changes shape.
        sys.path.insert(0, str(_REPO))
        from lib.migrations import ALL_VERSIONS  # noqa: E402
        self._all = tuple(ALL_VERSIONS)

    def test_all_versions_strictly_monotonic(self):
        """ALL_VERSIONS must be strictly ascending — no gaps, no dupes."""
        # No duplicates.
        self.assertEqual(
            len(self._all), len(set(self._all)),
            f"duplicate version in ALL_VERSIONS: {self._all}",
        )
        # Sorted ascending.
        self.assertEqual(
            list(self._all), sorted(self._all),
            f"ALL_VERSIONS not ascending: {self._all}",
        )
        # No gaps — must be a contiguous run starting at min.
        if self._all:
            expected = tuple(range(min(self._all), max(self._all) + 1))
            self.assertEqual(
                self._all, expected,
                f"ALL_VERSIONS has gaps: {self._all}, expected contiguous {expected}",
            )

    def test_every_helper_has_all_versions_entry(self):
        """Every `_ensure_vN_(columns|tables|indexes)` in migrations.py
        must have N in ALL_VERSIONS — else helper is silently dead."""
        helper_pat = re.compile(
            r"def\s+_ensure_v(\d+)_(?:columns|tables|indexes)\s*\("
        )
        helpers = {int(m.group(1)) for m in helper_pat.finditer(self._mig_text)}
        missing = helpers - set(self._all)
        self.assertFalse(
            missing,
            f"helpers exist for versions not in ALL_VERSIONS: {sorted(missing)}",
        )

    def test_every_sql_file_has_all_versions_entry(self):
        """Every `migrations_sql/vN.sql` must have N in ALL_VERSIONS."""
        sql_pat = re.compile(r"^v(\d+)\.sql$")
        sql_versions = set()
        for p in self._sql_dir.glob("v*.sql"):
            m = sql_pat.match(p.name)
            if m:
                sql_versions.add(int(m.group(1)))
        missing = sql_versions - set(self._all)
        self.assertFalse(
            missing,
            f"SQL files exist for versions not in ALL_VERSIONS: {sorted(missing)}",
        )

    def test_every_all_versions_entry_has_sql_or_helper(self):
        """Every version in ALL_VERSIONS must have either a v{N}.sql
        file on disk OR an `_ensure_vN_(columns|tables|indexes)` helper
        in migrations.py — else the version is bogus."""
        helper_pat = re.compile(
            r"def\s+_ensure_v(\d+)_(?:columns|tables|indexes)\s*\("
        )
        helpers = {int(m.group(1)) for m in helper_pat.finditer(self._mig_text)}

        sql_pat = re.compile(r"^v(\d+)\.sql$")
        sql_versions = set()
        for p in self._sql_dir.glob("v*.sql"):
            m = sql_pat.match(p.name)
            if m:
                sql_versions.add(int(m.group(1)))

        # Also count entries in the SQL-based MIGRATIONS list — these
        # carry their SQL inline (versions 1, 2, 3 in the current code).
        # Detect them by scanning the MIGRATIONS list block.
        mig_list_pat = re.compile(r"\(\s*(\d+)\s*,\s*\"v[\d._]+_")
        inline_versions = {
            int(m.group(1)) for m in mig_list_pat.finditer(self._mig_text)
        }

        provided = helpers | sql_versions | inline_versions
        missing = set(self._all) - provided
        self.assertFalse(
            missing,
            f"versions in ALL_VERSIONS lack SQL or helper: {sorted(missing)}",
        )


if __name__ == "__main__":
    sys.exit(run_tests(SchemaVersionsMonotonicityTests))
