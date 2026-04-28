"""v0.69 — prune_writes retention tests."""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

from lib import skill_persist
from lib.cache import run_db_path
from lib.db_notify import prune_writes
from tests.harness import TestCase, isolated_cache, run_tests

_REPO = Path(__file__).resolve().parents[1]
_CLI = _REPO / ".claude" / "skills" / "audit-query" / "scripts" / "query.py"


def _new_run_db(rid: str) -> Path:
    db = run_db_path(rid)
    schema = (_REPO / "lib" / "sqlite_schema.sql").read_text()
    con = sqlite3.connect(db)
    con.executescript(schema)
    con.close()
    from lib.migrations import ensure_current
    ensure_current(db)
    return db


def _seed_writes(db: Path, rid: str, n: int):
    for i in range(n):
        skill_persist.persist_citation_resolution(
            db, run_id=rid, input_text=f"row-{i}",
            partial={}, matched=False, score=0.1, threshold=0.5,
        )


class PruneWritesUnitTests(TestCase):
    def test_no_args_returns_count(self):
        with isolated_cache():
            db = _new_run_db("none_run")
            _seed_writes(db, "none_run", 5)
            con = sqlite3.connect(db)
            try:
                result = prune_writes(con)
            finally:
                con.close()
            self.assertEqual(result["deleted"], 0)
            self.assertEqual(result["remaining"], 5)
            self.assertTrue(result["table_present"])

    def test_keep_last_n(self):
        with isolated_cache():
            db = _new_run_db("keep_run")
            _seed_writes(db, "keep_run", 10)
            con = sqlite3.connect(db)
            try:
                result = prune_writes(con, keep_last_n=3)
            finally:
                con.close()
            self.assertEqual(result["remaining"], 3)
            self.assertEqual(result["deleted"], 7)

    def test_keep_last_n_zero_clears_table(self):
        with isolated_cache():
            db = _new_run_db("zero_run")
            _seed_writes(db, "zero_run", 4)
            con = sqlite3.connect(db)
            try:
                result = prune_writes(con, keep_last_n=0)
            finally:
                con.close()
            self.assertEqual(result["remaining"], 0)
            self.assertEqual(result["deleted"], 4)

    def test_older_than(self):
        with isolated_cache():
            db = _new_run_db("old_run")
            _seed_writes(db, "old_run", 5)
            # Use a future timestamp -> all rows are older.
            con = sqlite3.connect(db)
            try:
                result = prune_writes(con, older_than="2099-01-01T00:00:00+00:00")
            finally:
                con.close()
            self.assertEqual(result["remaining"], 0)
            self.assertEqual(result["deleted"], 5)

    def test_older_than_keeps_recent(self):
        with isolated_cache():
            db = _new_run_db("recent_run")
            _seed_writes(db, "recent_run", 3)
            # Past timestamp -> nothing should be older.
            con = sqlite3.connect(db)
            try:
                result = prune_writes(con, older_than="1970-01-01T00:00:00+00:00")
            finally:
                con.close()
            self.assertEqual(result["remaining"], 3)
            self.assertEqual(result["deleted"], 0)

    def test_table_missing(self):
        with isolated_cache() as root:
            db = root / "tiny.db"
            con = sqlite3.connect(db)
            con.execute("CREATE TABLE x (y INTEGER)")
            con.commit()
            try:
                result = prune_writes(con, keep_last_n=10)
            finally:
                con.close()
            self.assertFalse(result["table_present"])
            self.assertEqual(result["deleted"], 0)


class PruneWritesCliTests(TestCase):
    def test_cli_no_args_reports_count(self):
        with isolated_cache():
            db = _new_run_db("cli_count")
            _seed_writes(db, "cli_count", 4)
            r = subprocess.run(
                [sys.executable, str(_CLI), "prune-writes",
                 "--db-path", str(db)],
                capture_output=True, text=True, cwd=str(_REPO),
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            data = json.loads(r.stdout)
            self.assertEqual(data["remaining"], 4)
            self.assertEqual(data["deleted"], 0)

    def test_cli_keep_last_n(self):
        with isolated_cache():
            db = _new_run_db("cli_keep")
            _seed_writes(db, "cli_keep", 8)
            r = subprocess.run(
                [sys.executable, str(_CLI), "prune-writes",
                 "--db-path", str(db), "--keep-last-n", "2"],
                capture_output=True, text=True, cwd=str(_REPO),
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            data = json.loads(r.stdout)
            self.assertEqual(data["remaining"], 2)
            self.assertEqual(data["deleted"], 6)


if __name__ == "__main__":
    raise SystemExit(run_tests(
        PruneWritesUnitTests,
        PruneWritesCliTests,
    ))
