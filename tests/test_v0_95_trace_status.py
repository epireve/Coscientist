"""v0.95 — trace status summary tests."""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
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


class SummarizeTraceTests(TestCase):
    def test_missing_db_returns_not_found(self):
        with isolated_cache():
            db = run_db_path("does-not-exist")
            s = trace_status.summarize_trace(db, "trace-x")
            self.assertFalse(s["found"])
            self.assertIn("error", s)

    def test_missing_trace_returns_not_found(self):
        with isolated_cache():
            db = _new_run_db("rid-abc")
            s = trace_status.summarize_trace(db, "nope")
            self.assertFalse(s["found"])

    def test_summarize_counts_spans_by_kind_and_status(self):
        with isolated_cache():
            rid = "rid-1"
            db = _new_run_db(rid)
            trace.init_trace(db, trace_id=rid, run_id=rid)
            with trace.start_span(db, rid, "phase", "scout"):
                pass
            with trace.start_span(db, rid, "tool-call", "lookup"):
                pass
            try:
                with trace.start_span(db, rid, "gate", "novelty"):
                    raise ValueError("fatal in gate")
            except ValueError:
                pass
            s = trace_status.summarize_trace(db, rid)
            self.assertTrue(s["found"])
            self.assertEqual(s["n_spans"], 3)
            self.assertEqual(s["n_failed"], 1)
            self.assertEqual(s["n_ok"], 2)
            self.assertEqual(s["by_kind"]["phase"], 1)
            self.assertEqual(s["by_kind"]["tool-call"], 1)
            self.assertEqual(s["by_kind"]["gate"], 1)
            self.assertEqual(s["latest_phase"], "scout")
            self.assertIsNotNone(s["latest_error"])
            self.assertEqual(s["latest_error"]["kind"], "gate")


class SummarizeRunsTests(TestCase):
    def test_empty_root_returns_empty_list(self):
        with isolated_cache():
            out = trace_status.summarize_runs()
            self.assertEqual(out, [])

    def test_finds_traces_across_dbs(self):
        with isolated_cache():
            for rid in ("rid-a", "rid-b"):
                db = _new_run_db(rid)
                trace.init_trace(db, trace_id=rid, run_id=rid)
                with trace.start_span(db, rid, "phase", "scout"):
                    pass
            out = trace_status.summarize_runs()
            ids = sorted(s["trace_id"] for s in out if s.get("found"))
            self.assertEqual(ids, ["rid-a", "rid-b"])


class RenderMdTests(TestCase):
    def test_empty_renders_no_traces(self):
        out = trace_status.render_md([])
        self.assertIn("No traces found", out)

    def test_includes_run_status(self):
        s = {
            "found": True, "trace_id": "rid-1", "run_id": "rid-1",
            "status": "running", "n_spans": 5, "n_ok": 3,
            "n_running": 1, "n_failed": 1,
            "by_kind": {"phase": 2, "gate": 1},
            "latest_phase": "scout", "latest_error": None,
        }
        out = trace_status.render_md([s])
        self.assertIn("rid-1", out)
        self.assertIn("running", out)
        self.assertIn("phase=2", out)


class CliTests(TestCase):
    def test_run_id_format_json(self):
        with isolated_cache():
            rid = "rid-cli"
            db = _new_run_db(rid)
            trace.init_trace(db, trace_id=rid, run_id=rid)
            with trace.start_span(db, rid, "phase", "scout"):
                pass
            r = subprocess.run(
                [sys.executable, "-m", "lib.trace_status",
                 "--run-id", rid, "--format", "json"],
                capture_output=True, text=True, cwd=str(_REPO),
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            payload = json.loads(r.stdout)
            self.assertEqual(len(payload), 1)
            self.assertEqual(payload[0]["trace_id"], rid)


if __name__ == "__main__":
    raise SystemExit(run_tests(
        SummarizeTraceTests,
        SummarizeRunsTests,
        RenderMdTests,
        CliTests,
    ))
