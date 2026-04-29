"""v0.169 — defense-in-depth byte-equal check on plugin-vendored copies.

The graph-query-mcp plugin vendors `lib/migrations.py`, the entire
`lib/migrations_sql/` directory, and `lib/sqlite_schema.sql` so the
plugin can be installed standalone. A CHECKSUMS.txt drift gate exists
elsewhere (see test_v0_85_plugin_polish, test_v0_142_plugin_smoke), but
those are SHA-based — this test asserts the recent migration SQL files
(v13, v14, v15) and `sqlite_schema.sql` are byte-for-byte identical
between root and plugin. Bytes match → SHAs match, but a direct
byte-compare gives a clearer failure mode.
"""

from __future__ import annotations

import sys
from pathlib import Path

from tests import _shim  # noqa: F401
from tests.harness import TestCase, run_tests

_REPO = Path(__file__).resolve().parent.parent
_LIB_ROOT = _REPO / "lib"
_LIB_PLUGIN = _REPO / "plugin" / "coscientist-graph-query-mcp" / "lib"


def _assert_byte_equal(test: TestCase, rel: str) -> None:
    src = _LIB_ROOT / rel
    dst = _LIB_PLUGIN / rel
    test.assertTrue(src.exists(), f"missing root file: {src}")
    test.assertTrue(dst.exists(), f"missing plugin file: {dst}")
    src_bytes = src.read_bytes()
    dst_bytes = dst.read_bytes()
    test.assertEqual(
        src_bytes, dst_bytes,
        f"plugin drift: {rel} differs ({len(src_bytes)} vs {len(dst_bytes)} bytes)",
    )


class V15PluginDriftTests(TestCase):
    """Recent migration SQL byte-equal between root + plugin."""

    def test_v15_sql_byte_equal(self):
        _assert_byte_equal(self, "migrations_sql/v15.sql")

    def test_v14_sql_byte_equal(self):
        _assert_byte_equal(self, "migrations_sql/v14.sql")

    def test_v13_sql_byte_equal(self):
        _assert_byte_equal(self, "migrations_sql/v13.sql")

    def test_sqlite_schema_byte_equal(self):
        _assert_byte_equal(self, "sqlite_schema.sql")

    def test_migrations_py_byte_equal(self):
        # Defense-in-depth: also verify migrations.py itself doesn't
        # drift — a vendored helper out of sync with the SQL files
        # silently breaks the plugin.
        _assert_byte_equal(self, "migrations.py")


if __name__ == "__main__":
    sys.exit(run_tests(V15PluginDriftTests))
