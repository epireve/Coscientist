"""v0.112 — maybe_emit_tool_call sets status=error when error= given."""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from lib import trace
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


class ToolCallErrorTests(TestCase):
    def test_error_sets_status_and_msg(self):
        with isolated_cache():
            rid = "rid-tc"
            db = _new_run_db(rid)
            trace.init_trace(db, trace_id=rid, run_id=rid)
            os.environ["COSCIENTIST_TRACE_DB"] = str(db)
            os.environ["COSCIENTIST_TRACE_ID"] = rid
            try:
                trace.maybe_emit_tool_call(
                    "lookup_doi",
                    args_summary={"doi": "x"},
                    error="HTTP 404",
                )
            finally:
                del os.environ["COSCIENTIST_TRACE_DB"]
                del os.environ["COSCIENTIST_TRACE_ID"]
            con = sqlite3.connect(db)
            try:
                row = con.execute(
                    "SELECT status, error_msg, error_kind "
                    "FROM spans WHERE trace_id=? AND name=?",
                    (rid, "lookup_doi"),
                ).fetchone()
            finally:
                con.close()
            self.assertIsNotNone(row)
            self.assertEqual(row[0], "error")
            self.assertEqual(row[1], "HTTP 404")
            self.assertEqual(row[2], "_ToolCallError")

    def test_success_path_unchanged_status_ok(self):
        with isolated_cache():
            rid = "rid-ok"
            db = _new_run_db(rid)
            trace.init_trace(db, trace_id=rid, run_id=rid)
            os.environ["COSCIENTIST_TRACE_DB"] = str(db)
            os.environ["COSCIENTIST_TRACE_ID"] = rid
            try:
                trace.maybe_emit_tool_call(
                    "lookup_doi",
                    args_summary={"doi": "x"},
                    result_summary={"found": True},
                )
            finally:
                del os.environ["COSCIENTIST_TRACE_DB"]
                del os.environ["COSCIENTIST_TRACE_ID"]
            con = sqlite3.connect(db)
            try:
                row = con.execute(
                    "SELECT status FROM spans "
                    "WHERE trace_id=? AND name=?",
                    (rid, "lookup_doi"),
                ).fetchone()
            finally:
                con.close()
            self.assertEqual(row[0], "ok")


class ToolLatencyErrorIntegrationTests(TestCase):
    def test_error_span_counted_in_n_errors(self):
        from lib import trace_status
        with isolated_cache():
            rid = "rid-int"
            db = _new_run_db(rid)
            trace.init_trace(db, trace_id=rid, run_id=rid)
            os.environ["COSCIENTIST_TRACE_DB"] = str(db)
            os.environ["COSCIENTIST_TRACE_ID"] = rid
            try:
                trace.maybe_emit_tool_call(
                    "lookup_doi", args_summary={"doi": "x"},
                )
                trace.maybe_emit_tool_call(
                    "lookup_doi", args_summary={"doi": "y"},
                    error="HTTP 500",
                )
            finally:
                del os.environ["COSCIENTIST_TRACE_DB"]
                del os.environ["COSCIENTIST_TRACE_ID"]
            out = trace_status.tool_call_latency(db, trace_id=rid)
            self.assertEqual(out["n_rows"], 2)
            self.assertEqual(
                out["by_tool"]["lookup_doi"]["n_errors"], 1,
            )


if __name__ == "__main__":
    raise SystemExit(run_tests(
        ToolCallErrorTests, ToolLatencyErrorIntegrationTests,
    ))
