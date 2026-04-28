"""v0.100 — tool-call latency aggregation tests."""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
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


def _insert_tool_span(db: Path, *, trace_id: str, span_id: str,
                      name: str, duration_ms: int,
                      status: str = "ok"):
    con = sqlite3.connect(db)
    try:
        with con:
            con.execute(
                "INSERT OR IGNORE INTO traces "
                "(trace_id, run_id, started_at, status) "
                "VALUES (?, ?, '2026-04-28T00:00:00Z', 'running')",
                (trace_id, trace_id),
            )
            con.execute(
                "INSERT INTO spans "
                "(span_id, trace_id, parent_span_id, kind, name, "
                "started_at, ended_at, duration_ms, status) "
                "VALUES (?, ?, NULL, 'tool-call', ?, "
                "'2026-04-28T00:00:00Z', '2026-04-28T00:00:01Z', "
                "?, ?)",
                (span_id, trace_id, name, duration_ms, status),
            )
    finally:
        con.close()


class ToolLatencyTests(TestCase):
    def test_no_db_returns_empty(self):
        with isolated_cache():
            db = run_db_path("absent")
            out = trace_status.tool_call_latency(db)
            self.assertEqual(out["n_rows"], 0)

    def test_aggregates_by_name(self):
        with isolated_cache():
            db = _new_run_db("rid-lat")
            for i, dur in enumerate([100, 200, 300, 400, 500]):
                _insert_tool_span(
                    db, trace_id="rid-lat",
                    span_id=f"span-{i}", name="lookup_doi",
                    duration_ms=dur,
                )
            _insert_tool_span(
                db, trace_id="rid-lat", span_id="span-err",
                name="lookup_doi", duration_ms=50, status="error",
            )
            out = trace_status.tool_call_latency(db)
            self.assertEqual(out["n_rows"], 6)
            d = out["by_tool"]["lookup_doi"]
            self.assertEqual(d["n"], 6)
            self.assertEqual(d["n_errors"], 1)
            self.assertEqual(d["max_ms"], 500)
            self.assertGreater(d["mean_ms"], 200)
            self.assertGreater(d["p95_ms"], d["p50_ms"])

    def test_filters_by_trace_id(self):
        with isolated_cache():
            db = _new_run_db("rid-x")
            _insert_tool_span(
                db, trace_id="trace-a", span_id="s-a",
                name="t1", duration_ms=100,
            )
            _insert_tool_span(
                db, trace_id="trace-b", span_id="s-b",
                name="t2", duration_ms=200,
            )
            out = trace_status.tool_call_latency(
                db, trace_id="trace-a",
            )
            self.assertEqual(out["n_rows"], 1)
            self.assertIn("t1", out["by_tool"])
            self.assertNotIn("t2", out["by_tool"])


class CrossRunsTests(TestCase):
    def test_empty_root_returns_empty(self):
        with isolated_cache():
            out = trace_status.tool_call_latency_across_runs()
            self.assertEqual(out["n_dbs"], 0)
            self.assertEqual(out["n_rows"], 0)

    def test_aggregates_across_dbs(self):
        with isolated_cache():
            db1 = _new_run_db("rid-1")
            db2 = _new_run_db("rid-2")
            _insert_tool_span(
                db1, trace_id="rid-1", span_id="s1",
                name="t1", duration_ms=100,
            )
            _insert_tool_span(
                db2, trace_id="rid-2", span_id="s2",
                name="t1", duration_ms=300,
            )
            out = trace_status.tool_call_latency_across_runs()
            self.assertEqual(out["n_dbs"], 2)
            self.assertEqual(out["n_rows"], 2)
            self.assertEqual(out["by_tool"]["t1"]["n"], 2)
            self.assertAlmostEqual(
                out["by_tool"]["t1"]["mean_ms"], 200.0,
            )


class CliTests(TestCase):
    def test_cli_tool_latency_json(self):
        with isolated_cache():
            db = _new_run_db("rid-cli100")
            _insert_tool_span(
                db, trace_id="rid-cli100", span_id="s1",
                name="lookup_doi", duration_ms=150,
            )
            r = subprocess.run(
                [sys.executable, "-m", "lib.trace_status",
                 "--tool-latency", "--run-id", "rid-cli100",
                 "--format", "json"],
                capture_output=True, text=True, cwd=str(_REPO),
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            payload = json.loads(r.stdout)
            self.assertIn("lookup_doi", payload["by_tool"])


if __name__ == "__main__":
    raise SystemExit(run_tests(
        ToolLatencyTests, CrossRunsTests, CliTests,
    ))
