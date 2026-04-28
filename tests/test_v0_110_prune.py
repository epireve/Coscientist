"""v0.110 — trace pruning tests."""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from lib import trace_status
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


def _insert_old_trace(db: Path, *, trace_id: str,
                      days_ago: int, status: str = "ok"):
    """Direct insert with custom timestamps."""
    when = (datetime.now(UTC) - timedelta(days=days_ago)).isoformat()
    con = sqlite3.connect(db)
    try:
        with con:
            con.execute(
                "INSERT OR IGNORE INTO traces "
                "(trace_id, run_id, started_at, completed_at, "
                "status) VALUES (?, ?, ?, ?, ?)",
                (trace_id, trace_id, when, when, status),
            )
            con.execute(
                "INSERT INTO spans "
                "(span_id, trace_id, parent_span_id, kind, name, "
                "started_at, ended_at, duration_ms, status) "
                "VALUES (?, ?, NULL, 'phase', 'scout', ?, ?, "
                "100, ?)",
                (f"span-{trace_id}", trace_id, when, when, status),
            )
            con.execute(
                "INSERT INTO span_events "
                "(span_id, name, payload_json, at) "
                "VALUES (?, ?, ?, ?)",
                (f"span-{trace_id}", "evt", "{}", when),
            )
    finally:
        con.close()


class PruneTests(TestCase):
    def test_no_db_returns_zero(self):
        with isolated_cache():
            db = run_db_path("absent")
            r = trace_status.prune_old_traces(db, max_age_days=30)
            self.assertEqual(r["n_traces"], 0)

    def test_dry_run_does_not_delete(self):
        with isolated_cache():
            db = _new_run_db("rid-old")
            _insert_old_trace(db, trace_id="rid-old", days_ago=60)
            r = trace_status.prune_old_traces(
                db, max_age_days=30, dry_run=True,
            )
            self.assertEqual(r["n_traces"], 1)
            self.assertEqual(r["n_spans"], 1)
            self.assertEqual(r["n_events"], 1)
            self.assertTrue(r["dry_run"])
            # verify still present
            con = sqlite3.connect(db)
            try:
                n = con.execute(
                    "SELECT COUNT(*) FROM traces",
                ).fetchone()[0]
            finally:
                con.close()
            self.assertEqual(n, 1)

    def test_actual_prune_deletes_old(self):
        with isolated_cache():
            db = _new_run_db("rid-prune")
            _insert_old_trace(db, trace_id="old", days_ago=60)
            _insert_old_trace(db, trace_id="recent", days_ago=5)
            r = trace_status.prune_old_traces(db, max_age_days=30)
            self.assertEqual(r["n_traces"], 1)
            con = sqlite3.connect(db)
            try:
                rows = con.execute(
                    "SELECT trace_id FROM traces",
                ).fetchall()
                events = con.execute(
                    "SELECT COUNT(*) FROM span_events",
                ).fetchone()[0]
            finally:
                con.close()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0][0], "recent")
            self.assertEqual(events, 1)

    def test_running_traces_never_pruned(self):
        with isolated_cache():
            db = _new_run_db("rid-active")
            # very old but still running
            old = (datetime.now(UTC) - timedelta(days=90)).isoformat()
            con = sqlite3.connect(db)
            try:
                with con:
                    con.execute(
                        "INSERT INTO traces "
                        "(trace_id, run_id, started_at, status) "
                        "VALUES (?, ?, ?, 'running')",
                        ("rid-active", "rid-active", old),
                    )
            finally:
                con.close()
            r = trace_status.prune_old_traces(db, max_age_days=30)
            self.assertEqual(r["n_traces"], 0)


class CliTests(TestCase):
    def test_prune_dry_run_cli(self):
        with isolated_cache():
            db = _new_run_db("rid-cli")
            _insert_old_trace(db, trace_id="old", days_ago=60)
            r = subprocess.run(
                [sys.executable, "-m", "lib.trace_status",
                 "--prune", "--run-id", "rid-cli",
                 "--prune-days", "30", "--dry-run",
                 "--format", "json"],
                capture_output=True, text=True, cwd=str(_REPO),
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            payload = json.loads(r.stdout)
            self.assertEqual(payload[0]["n_traces"], 1)
            self.assertTrue(payload[0]["dry_run"])

    def test_prune_actual_cli(self):
        with isolated_cache():
            db = _new_run_db("rid-cli2")
            _insert_old_trace(db, trace_id="old", days_ago=60)
            r = subprocess.run(
                [sys.executable, "-m", "lib.trace_status",
                 "--prune", "--run-id", "rid-cli2",
                 "--prune-days", "30",
                 "--format", "json"],
                capture_output=True, text=True, cwd=str(_REPO),
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            payload = json.loads(r.stdout)
            self.assertFalse(payload[0]["dry_run"])
            con = sqlite3.connect(db)
            try:
                n = con.execute(
                    "SELECT COUNT(*) FROM traces",
                ).fetchone()[0]
            finally:
                con.close()
            self.assertEqual(n, 0)


if __name__ == "__main__":
    raise SystemExit(run_tests(PruneTests, CliTests))
