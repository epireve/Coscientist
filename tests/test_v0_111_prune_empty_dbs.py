"""v0.111 — prune empty run DBs tests."""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

from lib import trace, trace_status
from lib.cache import run_db_path
from tests.harness import TestCase, isolated_cache, run_tests

_REPO = Path(__file__).resolve().parents[1]


def _new_run_db(rid: str) -> Path:
    db = run_db_path(rid)
    schema = (_REPO / "lib" / "sqlite_schema.sql").read_text()
    con = sqlite3.connect(db)
    con.executescript(schema)
    con.close()
    from lib.migrations import ensure_current
    ensure_current(db)
    return db


def _add_phase(db: Path, *, run_id: str, name: str = "scout"):
    con = sqlite3.connect(db)
    try:
        with con:
            con.execute(
                "INSERT INTO runs (run_id, question, started_at) "
                "VALUES (?, 'q', '2026-04-28T00:00:00Z')",
                (run_id,),
            )
            con.execute(
                "INSERT INTO phases (run_id, name, ordinal) "
                "VALUES (?, ?, 0)",
                (run_id, name),
            )
    finally:
        con.close()


class PruneEmptyDbsTests(TestCase):
    def test_no_dbs_returns_zero(self):
        with isolated_cache():
            r = trace_status.prune_empty_run_dbs()
            self.assertEqual(r["n_deleted"], 0)

    def test_empty_db_deleted(self):
        with isolated_cache():
            db = _new_run_db("rid-empty")
            self.assertTrue(db.exists())
            r = trace_status.prune_empty_run_dbs()
            self.assertEqual(r["n_deleted"], 1)
            self.assertFalse(db.exists())

    def test_db_with_traces_skipped(self):
        with isolated_cache():
            db = _new_run_db("rid-has-trace")
            trace.init_trace(db, trace_id="rid-has-trace",
                              run_id="rid-has-trace")
            r = trace_status.prune_empty_run_dbs()
            self.assertEqual(r["n_deleted"], 0)
            self.assertEqual(len(r["skipped"]), 1)
            self.assertTrue(db.exists())

    def test_db_with_phases_skipped(self):
        with isolated_cache():
            db = _new_run_db("rid-has-phase")
            _add_phase(db, run_id="rid-has-phase")
            r = trace_status.prune_empty_run_dbs()
            self.assertEqual(r["n_deleted"], 0)
            self.assertTrue(db.exists())

    def test_dry_run_does_not_delete(self):
        with isolated_cache():
            db = _new_run_db("rid-dry")
            r = trace_status.prune_empty_run_dbs(dry_run=True)
            self.assertEqual(r["n_deleted"], 1)
            self.assertTrue(r["dry_run"])
            self.assertTrue(db.exists())

    def test_mixed_dbs_only_empty_deleted(self):
        with isolated_cache():
            empty_db = _new_run_db("rid-empty1")
            full_db = _new_run_db("rid-full")
            trace.init_trace(full_db, trace_id="rid-full",
                              run_id="rid-full")
            r = trace_status.prune_empty_run_dbs()
            self.assertEqual(r["n_deleted"], 1)
            self.assertFalse(empty_db.exists())
            self.assertTrue(full_db.exists())


class CliTests(TestCase):
    def test_cli_dry_run(self):
        with isolated_cache():
            db = _new_run_db("rid-cli")
            r = subprocess.run(
                [sys.executable, "-m", "lib.trace_status",
                 "--prune-empty-dbs", "--dry-run",
                 "--format", "json"],
                capture_output=True, text=True, cwd=str(_REPO),
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            payload = json.loads(r.stdout)
            self.assertEqual(payload["n_deleted"], 1)
            self.assertTrue(db.exists())

    def test_cli_actual(self):
        with isolated_cache():
            db = _new_run_db("rid-cli2")
            r = subprocess.run(
                [sys.executable, "-m", "lib.trace_status",
                 "--prune-empty-dbs",
                 "--format", "json"],
                capture_output=True, text=True, cwd=str(_REPO),
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertFalse(db.exists())


if __name__ == "__main__":
    raise SystemExit(run_tests(PruneEmptyDbsTests, CliTests))
