"""v0.45.9 edge-case tests for lib.transaction.multi_db_tx.

Existing TransactionTests (in test_v0_13_infrastructure.py) cover the
two-DB happy-path commit and the two-DB rollback. These tests add the
edge cases that weren't pinned: empty path list, single DB, three DBs,
non-default isolation level, and connection-close survival when an
exception is raised.
"""

from tests import _shim  # noqa: F401

import sqlite3
import sys
from pathlib import Path

from tests.harness import TestCase, isolated_cache, run_tests


def _make_db(path: Path) -> None:
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE log (id INTEGER PRIMARY KEY, msg TEXT)")
    con.commit()
    con.close()


def _count(path: Path) -> int:
    con = sqlite3.connect(path)
    n = con.execute("SELECT COUNT(*) FROM log").fetchone()[0]
    con.close()
    return n


class CardinalityTests(TestCase):
    def test_empty_path_list_yields_empty(self):
        from lib.transaction import multi_db_tx
        with multi_db_tx([]) as cons:
            self.assertEqual(cons, [])

    def test_single_db_commits_on_success(self):
        with isolated_cache() as cache_dir:
            from lib.transaction import multi_db_tx
            db = cache_dir / "single.db"
            _make_db(db)
            with multi_db_tx([db]) as (con,):
                con.execute("INSERT INTO log (msg) VALUES ('only')")
            self.assertEqual(_count(db), 1)

    def test_single_db_rolls_back_on_error(self):
        with isolated_cache() as cache_dir:
            from lib.transaction import multi_db_tx
            db = cache_dir / "single.db"
            _make_db(db)
            try:
                with multi_db_tx([db]) as (con,):
                    con.execute("INSERT INTO log (msg) VALUES ('x')")
                    raise RuntimeError("boom")
            except RuntimeError:
                pass
            self.assertEqual(_count(db), 0)

    def test_three_dbs_all_committed(self):
        with isolated_cache() as cache_dir:
            from lib.transaction import multi_db_tx
            dbs = [cache_dir / f"db{i}.db" for i in range(3)]
            for d in dbs:
                _make_db(d)
            with multi_db_tx(dbs) as cons:
                for i, c in enumerate(cons):
                    c.execute("INSERT INTO log (msg) VALUES (?)", (f"r{i}",))
            for d in dbs:
                self.assertEqual(_count(d), 1)

    def test_three_dbs_all_rolled_back(self):
        with isolated_cache() as cache_dir:
            from lib.transaction import multi_db_tx
            dbs = [cache_dir / f"db{i}.db" for i in range(3)]
            for d in dbs:
                _make_db(d)
            try:
                with multi_db_tx(dbs) as cons:
                    for i, c in enumerate(cons):
                        c.execute(
                            "INSERT INTO log (msg) VALUES (?)", (f"r{i}",),
                        )
                    raise ValueError("nope")
            except ValueError:
                pass
            for d in dbs:
                self.assertEqual(_count(d), 0)


class IsolationLevelTests(TestCase):
    def test_immediate_isolation_level_accepted(self):
        with isolated_cache() as cache_dir:
            from lib.transaction import multi_db_tx
            db = cache_dir / "imm.db"
            _make_db(db)
            with multi_db_tx([db], isolation_level="IMMEDIATE") as (con,):
                con.execute("INSERT INTO log (msg) VALUES ('imm')")
            self.assertEqual(_count(db), 1)

    def test_exclusive_isolation_level_accepted(self):
        with isolated_cache() as cache_dir:
            from lib.transaction import multi_db_tx
            db = cache_dir / "exc.db"
            _make_db(db)
            with multi_db_tx([db], isolation_level="EXCLUSIVE") as (con,):
                con.execute("INSERT INTO log (msg) VALUES ('exc')")
            self.assertEqual(_count(db), 1)

    def test_invalid_isolation_level_errors_at_begin(self):
        """SQLite rejects unknown isolation levels at BEGIN; the
        exception must bubble out of the context manager so the caller
        sees the misuse instead of swallowing it."""
        with isolated_cache() as cache_dir:
            from lib.transaction import multi_db_tx
            db = cache_dir / "bad.db"
            _make_db(db)
            try:
                with multi_db_tx([db], isolation_level="GARBAGE"):
                    pass
            except sqlite3.OperationalError:
                return
            raise AssertionError("expected sqlite3.OperationalError")


class IsolationBetweenContextsTests(TestCase):
    """Two sequential multi_db_tx contexts must not see each other's
    open transaction state — important for resume scenarios."""

    def test_second_tx_sees_first_committed_state(self):
        with isolated_cache() as cache_dir:
            from lib.transaction import multi_db_tx
            db = cache_dir / "seq.db"
            _make_db(db)
            with multi_db_tx([db]) as (con,):
                con.execute("INSERT INTO log (msg) VALUES ('first')")
            with multi_db_tx([db]) as (con,):
                rows = con.execute("SELECT msg FROM log").fetchall()
                self.assertEqual([r[0] for r in rows], ["first"])
                con.execute("INSERT INTO log (msg) VALUES ('second')")
            self.assertEqual(_count(db), 2)

    def test_second_tx_after_rollback_sees_no_first_writes(self):
        with isolated_cache() as cache_dir:
            from lib.transaction import multi_db_tx
            db = cache_dir / "rb.db"
            _make_db(db)
            try:
                with multi_db_tx([db]) as (con,):
                    con.execute("INSERT INTO log (msg) VALUES ('lost')")
                    raise RuntimeError("rollback")
            except RuntimeError:
                pass
            with multi_db_tx([db]) as (con,):
                self.assertEqual(_count(db), 0)


if __name__ == "__main__":
    sys.exit(run_tests(
        CardinalityTests, IsolationLevelTests,
        IsolationBetweenContextsTests,
    ))
