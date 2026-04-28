"""v0.97 — stale-span detection tests."""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from tests.harness import TestCase, isolated_cache, run_tests
from lib import trace, trace_status
from lib.cache import run_db_path


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


def _insert_running_span(db: Path, *, trace_id: str, span_id: str,
                         name: str, started_at: str,
                         kind: str = "phase"):
    con = sqlite3.connect(db)
    try:
        with con:
            con.execute(
                "INSERT OR IGNORE INTO traces "
                "(trace_id, run_id, started_at, status) "
                "VALUES (?, ?, ?, 'running')",
                (trace_id, trace_id, started_at),
            )
            con.execute(
                "INSERT INTO spans "
                "(span_id, trace_id, parent_span_id, kind, name, "
                "started_at, status) VALUES (?, ?, NULL, ?, ?, ?, "
                "'running')",
                (span_id, trace_id, kind, name, started_at),
            )
    finally:
        con.close()


class FindStaleSpansTests(TestCase):
    def test_no_db_returns_empty(self):
        with isolated_cache():
            db = run_db_path("absent")
            self.assertEqual(trace_status.find_stale_spans(db), [])

    def test_recent_running_not_stale(self):
        with isolated_cache():
            db = _new_run_db("rid-1")
            now = datetime.now(UTC)
            _insert_running_span(
                db, trace_id="rid-1", span_id="span-recent",
                name="scout", started_at=now.isoformat(),
            )
            stale = trace_status.find_stale_spans(
                db, max_age_minutes=30,
            )
            self.assertEqual(stale, [])

    def test_old_running_is_stale(self):
        with isolated_cache():
            db = _new_run_db("rid-2")
            old = datetime.now(UTC) - timedelta(hours=2)
            _insert_running_span(
                db, trace_id="rid-2", span_id="span-old",
                name="scout", started_at=old.isoformat(),
            )
            stale = trace_status.find_stale_spans(
                db, max_age_minutes=30,
            )
            self.assertEqual(len(stale), 1)
            self.assertEqual(stale[0]["span_id"], "span-old")
            self.assertGreaterEqual(stale[0]["age_minutes"], 60)

    def test_completed_span_not_returned(self):
        with isolated_cache():
            db = _new_run_db("rid-3")
            trace.init_trace(db, trace_id="rid-3", run_id="rid-3")
            with trace.start_span(db, "rid-3", "phase", "scout"):
                pass  # completes ok
            stale = trace_status.find_stale_spans(
                db, max_age_minutes=0,  # even 0 should not catch ok
            )
            self.assertEqual(stale, [])


class CliTests(TestCase):
    def test_stale_only_flag_emits_json(self):
        with isolated_cache():
            db = _new_run_db("rid-cli")
            old = datetime.now(UTC) - timedelta(hours=2)
            _insert_running_span(
                db, trace_id="rid-cli", span_id="span-old",
                name="scout", started_at=old.isoformat(),
            )
            r = subprocess.run(
                [sys.executable, "-m", "lib.trace_status",
                 "--stale-only", "--run-id", "rid-cli",
                 "--format", "json", "--max-age", "30"],
                capture_output=True, text=True, cwd=str(_REPO),
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            payload = json.loads(r.stdout)
            self.assertEqual(len(payload), 1)
            self.assertEqual(payload[0]["name"], "scout")


class MarkStaleErrorTests(TestCase):
    """v0.98 — auto-close stale running spans."""

    def test_no_stale_returns_empty(self):
        with isolated_cache():
            db = _new_run_db("rid-empty")
            out = trace_status.mark_stale_error(
                db, max_age_minutes=30,
            )
            self.assertEqual(out, [])

    def test_marks_status_error_with_reason(self):
        with isolated_cache():
            db = _new_run_db("rid-mark")
            old = datetime.now(UTC) - timedelta(hours=2)
            _insert_running_span(
                db, trace_id="rid-mark", span_id="span-old",
                name="scout", started_at=old.isoformat(),
            )
            out = trace_status.mark_stale_error(
                db, max_age_minutes=30, reason="phase crashed",
            )
            self.assertEqual(len(out), 1)
            con = sqlite3.connect(db)
            try:
                row = con.execute(
                    "SELECT status, error_kind, error_msg, ended_at "
                    "FROM spans WHERE span_id=?",
                    ("span-old",),
                ).fetchone()
            finally:
                con.close()
            self.assertEqual(row[0], "error")
            self.assertEqual(row[1], "stale")
            self.assertEqual(row[2], "phase crashed")
            self.assertIsNotNone(row[3])

    def test_completed_span_not_touched(self):
        with isolated_cache():
            db = _new_run_db("rid-keep")
            trace.init_trace(db, trace_id="rid-keep", run_id="rid-keep")
            with trace.start_span(db, "rid-keep", "phase", "scout"):
                pass
            out = trace_status.mark_stale_error(
                db, max_age_minutes=0,
            )
            self.assertEqual(out, [])
            con = sqlite3.connect(db)
            try:
                row = con.execute(
                    "SELECT status FROM spans "
                    "WHERE trace_id='rid-keep'",
                ).fetchone()
            finally:
                con.close()
            self.assertEqual(row[0], "ok")


class MarkErrorCliTests(TestCase):
    def test_cli_mark_error(self):
        with isolated_cache():
            db = _new_run_db("rid-cli2")
            old = datetime.now(UTC) - timedelta(hours=2)
            _insert_running_span(
                db, trace_id="rid-cli2", span_id="span-old2",
                name="scout", started_at=old.isoformat(),
            )
            r = subprocess.run(
                [sys.executable, "-m", "lib.trace_status",
                 "--stale-only", "--mark-error",
                 "--run-id", "rid-cli2",
                 "--format", "json", "--max-age", "30",
                 "--reason", "test-reason"],
                capture_output=True, text=True, cwd=str(_REPO),
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            payload = json.loads(r.stdout)
            self.assertEqual(len(payload), 1)
            self.assertIn("closed_at", payload[0])
            con = sqlite3.connect(db)
            try:
                row = con.execute(
                    "SELECT status, error_msg FROM spans "
                    "WHERE span_id='span-old2'",
                ).fetchone()
            finally:
                con.close()
            self.assertEqual(row[0], "error")
            self.assertEqual(row[1], "test-reason")


if __name__ == "__main__":
    raise SystemExit(run_tests(
        FindStaleSpansTests, CliTests,
        MarkStaleErrorTests, MarkErrorCliTests,
    ))
