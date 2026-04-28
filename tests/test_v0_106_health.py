"""v0.106 — health dump tests."""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from tests.harness import TestCase, isolated_cache, run_tests
from lib import health, trace
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


class CollectTests(TestCase):
    def test_empty_root_returns_zero(self):
        with isolated_cache():
            r = health.collect()
            self.assertEqual(r["n_runs"], 0)
            self.assertEqual(r["active"], [])
            self.assertEqual(r["stale"], [])

    def test_active_run_listed(self):
        with isolated_cache():
            db = _new_run_db("rid-active")
            trace.init_trace(db, trace_id="rid-active",
                              run_id="rid-active")
            r = health.collect()
            self.assertEqual(r["n_runs"], 1)
            self.assertEqual(len(r["active"]), 1)
            self.assertEqual(r["active"][0]["trace_id"], "rid-active")

    def test_stale_span_picked_up(self):
        with isolated_cache():
            db = _new_run_db("rid-stale")
            old = datetime.now(UTC) - timedelta(hours=2)
            con = sqlite3.connect(db)
            try:
                with con:
                    con.execute(
                        "INSERT OR IGNORE INTO traces "
                        "(trace_id, run_id, started_at, status) "
                        "VALUES (?, ?, ?, 'running')",
                        ("rid-stale", "rid-stale", old.isoformat()),
                    )
                    con.execute(
                        "INSERT INTO spans "
                        "(span_id, trace_id, parent_span_id, kind, "
                        "name, started_at, status) "
                        "VALUES (?, ?, NULL, 'phase', 'scout', ?, "
                        "'running')",
                        ("span-old", "rid-stale", old.isoformat()),
                    )
            finally:
                con.close()
            r = health.collect(max_age_minutes=30)
            self.assertEqual(len(r["stale"]), 1)
            self.assertEqual(r["stale"][0]["span_id"], "span-old")

    def test_failed_spans_counted(self):
        with isolated_cache():
            db = _new_run_db("rid-fail")
            trace.init_trace(db, trace_id="rid-fail",
                              run_id="rid-fail")
            try:
                with trace.start_span(
                    db, "rid-fail", "phase", "scout",
                ):
                    raise ValueError("boom")
            except ValueError:
                pass
            r = health.collect()
            self.assertGreaterEqual(r["failed_spans_total"], 1)


class RenderMdTests(TestCase):
    def test_empty_report_renders(self):
        out = health.render_md({
            "n_runs": 0, "active": [], "stale": [],
            "tool_latency": {"by_tool": {}},
            "quality": {"by_agent": {}},
            "failed_spans_total": 0,
        })
        self.assertIn("Coscientist health", out)
        self.assertIn("No data", out)

    def test_active_runs_in_output(self):
        out = health.render_md({
            "n_runs": 1,
            "active": [{
                "trace_id": "rid-x",
                "started_at": "2026-04-28T00:00:00Z",
                "db_path": "/tmp/x.db",
                "run_id": "rid-x",
            }],
            "stale": [],
            "tool_latency": {"by_tool": {}},
            "quality": {"by_agent": {}},
            "failed_spans_total": 0,
        })
        self.assertIn("rid-x", out)
        self.assertIn("Active runs", out)


class CliTests(TestCase):
    def test_cli_json(self):
        with isolated_cache():
            r = subprocess.run(
                [sys.executable, "-m", "lib.health",
                 "--format", "json"],
                capture_output=True, text=True, cwd=str(_REPO),
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            payload = json.loads(r.stdout)
            self.assertIn("n_runs", payload)
            self.assertIn("active", payload)


if __name__ == "__main__":
    raise SystemExit(run_tests(
        CollectTests, RenderMdTests, CliTests,
    ))
