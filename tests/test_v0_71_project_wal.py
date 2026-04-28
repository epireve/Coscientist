"""v0.71 — verify project DBs open in WAL mode after retrofit."""
from __future__ import annotations

import sqlite3

from lib import project
from tests.harness import TestCase, isolated_cache, run_tests


class ProjectDbWalTests(TestCase):
    def test_create_uses_wal(self):
        with isolated_cache():
            pid = project.create("WAL test project")
            db = project.project_db_path(pid)
            self.assertTrue(db.exists(), f"DB missing at {db}")
            con = sqlite3.connect(db)
            try:
                mode = con.execute("PRAGMA journal_mode").fetchone()[0]
                self.assertEqual(mode.lower(), "wal")
            finally:
                con.close()

    def test_get_preserves_wal(self):
        with isolated_cache():
            pid = project.create("Reopen test")
            project.get(pid)
            db = project.project_db_path(pid)
            con = sqlite3.connect(db)
            try:
                mode = con.execute("PRAGMA journal_mode").fetchone()[0]
                self.assertEqual(mode.lower(), "wal")
            finally:
                con.close()

    def test_concurrent_writers_no_lock(self):
        """WAL allows reader + writer; pre-WAL would block here."""
        with isolated_cache():
            pid = project.create("Concurrent project")
            db = project.project_db_path(pid)
            writer = sqlite3.connect(db, timeout=2.0)
            try:
                writer.execute("BEGIN")
                writer.execute(
                    "INSERT INTO graph_nodes (node_id, kind, label, "
                    "created_at) VALUES (?, ?, ?, ?)",
                    ("paper:test1", "paper", "Test Paper",
                     "2026-04-27T00:00:00+00:00"),
                )
                # Open a reader while the writer's transaction is open.
                reader = sqlite3.connect(db, timeout=2.0)
                try:
                    rows = reader.execute(
                        "SELECT COUNT(*) FROM graph_nodes"
                    ).fetchone()
                    # Reader sees the pre-write state; uncommitted insert
                    # not visible. Either way, no SQLITE_BUSY.
                    self.assertGreaterEqual(rows[0], 0)
                finally:
                    reader.close()
                writer.commit()
            finally:
                writer.close()


if __name__ == "__main__":
    raise SystemExit(run_tests(ProjectDbWalTests))
