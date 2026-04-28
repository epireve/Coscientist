"""v0.65g — connect_wal tests.

Verifies the lib.cache.connect_wal helper:
  - returns a usable sqlite3 connection
  - sets journal_mode=WAL persistently
  - sets busy_timeout
  - is idempotent (second call doesn't downgrade WAL)
  - creates parent dir if missing
"""
from __future__ import annotations

import sqlite3

from tests.harness import TestCase, isolated_cache, run_tests
from lib.cache import connect_wal


class ConnectWalTests(TestCase):
    def test_returns_sqlite_connection(self):
        with isolated_cache() as root:
            db = root / "test.db"
            con = connect_wal(db)
            try:
                self.assertIsInstance(con, sqlite3.Connection)
            finally:
                con.close()

    def test_sets_wal_journal_mode(self):
        with isolated_cache() as root:
            db = root / "wal.db"
            con = connect_wal(db)
            try:
                mode = con.execute("PRAGMA journal_mode").fetchone()[0]
                self.assertEqual(mode.lower(), "wal")
            finally:
                con.close()

    def test_wal_persists_across_connections(self):
        with isolated_cache() as root:
            db = root / "wal_persist.db"
            con1 = connect_wal(db)
            con1.close()
            # Second connection (plain sqlite3) sees the persisted mode.
            con2 = sqlite3.connect(db)
            try:
                mode = con2.execute("PRAGMA journal_mode").fetchone()[0]
                self.assertEqual(mode.lower(), "wal")
            finally:
                con2.close()

    def test_busy_timeout_set(self):
        with isolated_cache() as root:
            db = root / "busy.db"
            con = connect_wal(db, timeout=5.0)
            try:
                bt = con.execute("PRAGMA busy_timeout").fetchone()[0]
                self.assertEqual(bt, 5000)
            finally:
                con.close()

    def test_idempotent_on_existing_wal_db(self):
        with isolated_cache() as root:
            db = root / "idem.db"
            con1 = connect_wal(db)
            con1.execute("CREATE TABLE t (x INTEGER)")
            con1.commit()
            con1.close()
            # Re-open via connect_wal: should still be WAL, table preserved.
            con2 = connect_wal(db)
            try:
                mode = con2.execute("PRAGMA journal_mode").fetchone()[0]
                self.assertEqual(mode.lower(), "wal")
                rows = con2.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
                self.assertIn(("t",), rows)
            finally:
                con2.close()

    def test_creates_parent_dir(self):
        with isolated_cache() as root:
            nested = root / "deep" / "nested" / "path" / "db.db"
            con = connect_wal(nested)
            try:
                self.assertTrue(nested.exists())
            finally:
                con.close()

    def test_concurrent_readers_allowed(self):
        """WAL mode should allow concurrent open reader + writer."""
        with isolated_cache() as root:
            db = root / "concurrent.db"
            writer = connect_wal(db)
            try:
                writer.execute("CREATE TABLE t (x INTEGER)")
                writer.execute("INSERT INTO t VALUES (1)")
                writer.commit()
                # Open a reader while writer connection is still alive.
                reader = sqlite3.connect(db, timeout=2.0)
                try:
                    rows = reader.execute("SELECT * FROM t").fetchall()
                    self.assertEqual(rows, [(1,)])
                finally:
                    reader.close()
            finally:
                writer.close()


if __name__ == "__main__":
    raise SystemExit(run_tests(ConnectWalTests))
