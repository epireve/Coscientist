"""v0.45.2 unit tests for lib.cache helpers."""

import sys
from pathlib import Path

from tests import _shim  # noqa: F401
from tests.harness import TestCase, isolated_cache, run_tests


class ArchivesForTests(TestCase):
    def _setup(self) -> Path:
        from lib.cache import audit_log_path
        live = audit_log_path()
        live.write_text("live\n")
        return live

    def test_returns_empty_when_no_archives(self):
        with isolated_cache():
            from lib.cache import archives_for
            live = self._setup()
            self.assertEqual(archives_for(live), [])

    def test_finds_archives_with_canonical_stamp(self):
        with isolated_cache():
            from lib.cache import archives_for
            live = self._setup()
            a1 = live.with_name(f"{live.name}.20260101T000000Z")
            a2 = live.with_name(f"{live.name}.20260301T000000Z")
            a1.write_text("old")
            a2.write_text("newer")
            out = archives_for(live)
            self.assertEqual([p.name for p in out],
                             [a1.name, a2.name])  # oldest→newest

    def test_finds_archives_with_collision_suffix(self):
        with isolated_cache():
            from lib.cache import archives_for
            live = self._setup()
            collision = live.with_name(
                f"{live.name}.20260101T000000Z_42"
            )
            collision.write_text("x")
            self.assertEqual(
                [p.name for p in archives_for(live)],
                [collision.name],
            )

    def test_ignores_unrelated_files(self):
        with isolated_cache():
            from lib.cache import archives_for
            live = self._setup()
            (live.parent / "audit.log.bak").write_text("not-an-archive")
            (live.parent / "other.20260101T000000Z").write_text("x")
            self.assertEqual(archives_for(live), [])

    def test_does_not_include_live_file(self):
        with isolated_cache():
            from lib.cache import archives_for
            live = self._setup()
            archive = live.with_name(f"{live.name}.20260101T000000Z")
            archive.write_text("x")
            out = archives_for(live)
            self.assertNotIn(live, out)
            self.assertIn(archive, out)

    def test_no_parent_dir_returns_empty(self):
        from lib.cache import archives_for
        # Path under a directory that doesn't exist
        nonexistent = Path("/tmp/coscientist-nonexistent-xyz/audit.log")
        self.assertEqual(archives_for(nonexistent), [])


if __name__ == "__main__":
    sys.exit(run_tests(ArchivesForTests))
