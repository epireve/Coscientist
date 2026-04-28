"""v0.82 — audit retention + lib.graph WAL consistency."""
from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from tests.harness import TestCase, isolated_cache, run_tests
from lib.audit_retention import (
    list_archives, purge_archives, _archive_age_days,
)
from lib.cache import audit_log_path
from lib import graph, project


_REPO = Path(__file__).resolve().parents[1]


def _make_archive(parent: Path, base: str, days_ago: int,
                  size_bytes: int = 100) -> Path:
    """Create a fake rotated archive file with a stamp N days old."""
    stamp = (
        datetime.now(UTC) - timedelta(days=days_ago)
    ).strftime("%Y%m%dT%H%M%SZ")
    p = parent / f"{base}.{stamp}"
    p.write_bytes(b"x" * size_bytes)
    return p


class ArchiveAgeTests(TestCase):
    def test_age_from_stamp(self):
        with isolated_cache() as root:
            audit = audit_log_path()
            p = _make_archive(audit.parent, "audit.log", days_ago=30)
            self.assertGreaterEqual(_archive_age_days(p), 29)

    def test_age_zero_for_today(self):
        with isolated_cache() as root:
            audit = audit_log_path()
            p = _make_archive(audit.parent, "audit.log", days_ago=0)
            self.assertEqual(_archive_age_days(p), 0)


class ListArchivesTests(TestCase):
    def test_empty_cache_returns_empty(self):
        with isolated_cache():
            self.assertEqual(list_archives(), [])

    def test_finds_audit_archives(self):
        with isolated_cache():
            audit = audit_log_path()
            audit.write_text("live")  # live file (not an archive)
            _make_archive(audit.parent, "audit.log", days_ago=10)
            _make_archive(audit.parent, "audit.log", days_ago=40)
            rows = list_archives()
            self.assertEqual(len(rows), 2)

    def test_filter_by_age(self):
        with isolated_cache():
            audit = audit_log_path()
            audit.write_text("live")
            _make_archive(audit.parent, "audit.log", days_ago=5)
            _make_archive(audit.parent, "audit.log", days_ago=60)
            rows = list_archives(older_than_days=30)
            self.assertEqual(len(rows), 1)
            self.assertGreaterEqual(rows[0].age_days, 30)


class PurgeArchivesTests(TestCase):
    def test_dry_run_does_not_delete(self):
        with isolated_cache():
            audit = audit_log_path()
            audit.write_text("live")
            _make_archive(audit.parent, "audit.log", days_ago=60)
            res = purge_archives(older_than_days=30, confirm=False)
            self.assertEqual(res["n_candidates"], 1)
            self.assertEqual(res["n_deleted"], 0)
            self.assertFalse(res["confirm"])
            # File still exists.
            self.assertEqual(len(list_archives()), 1)

    def test_confirm_deletes(self):
        with isolated_cache():
            audit = audit_log_path()
            audit.write_text("live")
            _make_archive(audit.parent, "audit.log", days_ago=60,
                           size_bytes=200)
            res = purge_archives(older_than_days=30, confirm=True)
            self.assertEqual(res["n_deleted"], 1)
            self.assertEqual(res["bytes_freed"], 200)
            self.assertEqual(len(list_archives()), 0)

    def test_zero_days_rejected(self):
        with isolated_cache():
            with self.assertRaises(ValueError):
                purge_archives(older_than_days=0, confirm=True)


class GraphWalConsistencyTests(TestCase):
    def test_graph_connect_uses_wal(self):
        with isolated_cache():
            pid = project.create("graph wal")
            graph.add_node(pid, "paper", "X", "X")
            con = sqlite3.connect(project.project_db_path(pid))
            try:
                mode = con.execute("PRAGMA journal_mode").fetchone()[0]
                self.assertEqual(mode.lower(), "wal")
            finally:
                con.close()


if __name__ == "__main__":
    raise SystemExit(run_tests(
        ArchiveAgeTests,
        ListArchivesTests,
        PurgeArchivesTests,
        GraphWalConsistencyTests,
    ))
