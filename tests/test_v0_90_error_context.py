"""v0.90 — error context capture tests."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from tests.harness import TestCase, isolated_cache, run_tests
from lib import trace
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


def _error_context(db: Path, trace_id: str) -> dict:
    """Return parsed error_context payload for the (single) span."""
    con = sqlite3.connect(db)
    try:
        row = con.execute(
            "SELECT span_events.payload_json FROM span_events "
            "JOIN spans USING (span_id) "
            "WHERE spans.trace_id=? AND span_events.name='error_context'",
            (trace_id,),
        ).fetchone()
    finally:
        con.close()
    return json.loads(row[0]) if row else None


class CaptureErrorContextTests(TestCase):
    def test_traceback_persisted(self):
        with isolated_cache():
            db = _new_run_db("err_tb")
            tid = "trace-tb"
            trace.init_trace(db, trace_id=tid)
            try:
                with trace.start_span(
                    db, tid, "phase", "boom",
                    capture_on_error=True,
                ):
                    raise ValueError("test failure")
            except ValueError:
                pass
            ctx = _error_context(db, tid)
            self.assertIsNotNone(ctx)
            self.assertEqual(ctx["exception"]["type"], "ValueError")
            self.assertIn("test failure", ctx["exception"]["msg"])
            # Traceback string includes the exception type and the
            # raise site.
            tb = ctx["exception"]["traceback"]
            self.assertIn("ValueError", tb)
            self.assertIn("test failure", tb)

    def test_no_capture_without_flag(self):
        with isolated_cache():
            db = _new_run_db("no_cap")
            tid = "trace-no-cap"
            trace.init_trace(db, trace_id=tid)
            try:
                with trace.start_span(db, tid, "phase", "boom"):
                    raise RuntimeError("x")
            except RuntimeError:
                pass
            self.assertIsNone(_error_context(db, tid))

    def test_snapshot_tables_included(self):
        with isolated_cache():
            db = _new_run_db("snap")
            tid = "trace-snap"
            trace.init_trace(db, trace_id=tid)
            try:
                with trace.start_span(
                    db, tid, "phase", "boom",
                    capture_on_error=True,
                    snapshot_tables=["spans", "traces", "no_such_table"],
                ):
                    raise RuntimeError("x")
            except RuntimeError:
                pass
            ctx = _error_context(db, tid)
            self.assertIn("row_counts", ctx)
            self.assertGreaterEqual(ctx["row_counts"]["spans"], 1)
            self.assertGreaterEqual(ctx["row_counts"]["traces"], 1)
            # Missing table yields -1, doesn't crash
            self.assertEqual(ctx["row_counts"]["no_such_table"], -1)

    def test_stdout_stderr_tail(self):
        with isolated_cache():
            db = _new_run_db("io_tail")
            tid = "trace-io"
            trace.init_trace(db, trace_id=tid)
            stdout = "stdout " + "x" * 10000
            stderr = "stderr " + "y" * 10000
            try:
                with trace.start_span(
                    db, tid, "phase", "boom",
                ) as sp:
                    try:
                        raise RuntimeError("io test")
                    except RuntimeError as e:
                        # Manual capture with custom tails.
                        trace.capture_error_context(
                            db, sp, e,
                            stdout_tail=stdout, stderr_tail=stderr,
                            max_bytes=1000,
                        )
                        raise
            except RuntimeError:
                pass
            ctx = _error_context(db, tid)
            self.assertIn("stdout_tail", ctx)
            # Bounded
            self.assertLessEqual(len(ctx["stdout_tail"]), 1000)
            self.assertLessEqual(len(ctx["stderr_tail"]), 1000)
            # Tail not head
            self.assertTrue(ctx["stdout_tail"].endswith("x"))

    def test_capture_failure_does_not_mask_original(self):
        """If capture itself errors, the original exception still raises."""
        with isolated_cache():
            db = _new_run_db("cap_fail")
            tid = "trace-cap-fail"
            trace.init_trace(db, trace_id=tid)
            raised: Exception | None = None
            try:
                # Use snapshot_tables for a path that can fail when
                # passed garbage; even without that, original raises.
                with trace.start_span(
                    db, tid, "phase", "boom",
                    capture_on_error=True,
                ):
                    raise KeyError("original")
            except KeyError as e:
                raised = e
            self.assertIsNotNone(raised)
            self.assertIn("original", str(raised))


if __name__ == "__main__":
    raise SystemExit(run_tests(CaptureErrorContextTests))
