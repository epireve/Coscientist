"""v0.93 — instrumentation hookup tests.

Verifies span emission from:
  - deep-research/db.py record-phase command
  - harvest.py write
  - publishability-check gate (ok + rejected)
  - MCP server _trace_emit helpers (env-context-aware)
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
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


class EnvTraceContextTests(TestCase):
    def test_no_env_returns_none(self):
        # Sanity: pristine env must yield None.
        if "COSCIENTIST_TRACE_ID" in os.environ:
            return  # don't run if user has it set in their shell
        db, tid = trace.env_trace_context()
        self.assertIsNone(db)
        self.assertIsNone(tid)

    def test_env_set_returns_path_and_id(self):
        os.environ["COSCIENTIST_TRACE_DB"] = "/tmp/x.db"
        os.environ["COSCIENTIST_TRACE_ID"] = "trace-abc"
        try:
            db, tid = trace.env_trace_context()
            self.assertEqual(str(db), "/tmp/x.db")
            self.assertEqual(tid, "trace-abc")
        finally:
            os.environ.pop("COSCIENTIST_TRACE_DB", None)
            os.environ.pop("COSCIENTIST_TRACE_ID", None)


class MaybeEmitToolCallTests(TestCase):
    def test_no_env_is_silent_noop(self):
        # Pre-condition: env unset. Should not raise + not write.
        os.environ.pop("COSCIENTIST_TRACE_DB", None)
        os.environ.pop("COSCIENTIST_TRACE_ID", None)
        # No exception = pass.
        trace.maybe_emit_tool_call("dummy_tool", args_summary={"x": 1})

    def test_env_set_writes_span(self):
        with isolated_cache():
            db = _new_run_db("emit_run")
            tid = "trace-emit"
            trace.init_trace(db, trace_id=tid, run_id="emit_run")
            os.environ["COSCIENTIST_TRACE_DB"] = str(db)
            os.environ["COSCIENTIST_TRACE_ID"] = tid
            try:
                trace.maybe_emit_tool_call(
                    "lookup_doi",
                    args_summary={"doi": "10.1/x"},
                    result_summary={"found": True},
                )
            finally:
                os.environ.pop("COSCIENTIST_TRACE_DB", None)
                os.environ.pop("COSCIENTIST_TRACE_ID", None)
            con = sqlite3.connect(db)
            try:
                row = con.execute(
                    "SELECT name, kind FROM spans "
                    "WHERE trace_id=? AND kind='tool-call'",
                    (tid,),
                ).fetchone()
            finally:
                con.close()
            self.assertEqual(row[0], "lookup_doi")
            self.assertEqual(row[1], "tool-call")


class GateTraceTests(TestCase):
    def test_emit_gate_span_no_run_id_is_noop(self):
        from lib.gate_trace import emit_gate_span
        # Should not raise.
        emit_gate_span(run_id=None, gate_name="x", verdict="ok")

    def test_emit_gate_span_writes(self):
        with isolated_cache():
            from lib.gate_trace import emit_gate_span
            rid = "gate_run"
            db = _new_run_db(rid)
            emit_gate_span(
                run_id=rid, gate_name="publishability-check",
                verdict="ok", target_id="ms-x",
            )
            con = sqlite3.connect(db)
            try:
                row = con.execute(
                    "SELECT name, kind, status FROM spans "
                    "WHERE trace_id=? AND kind='gate'",
                    (rid,),
                ).fetchone()
            finally:
                con.close()
            self.assertEqual(row[0], "publishability-check")
            self.assertEqual(row[2], "ok")

    def test_emit_gate_span_rejected_writes(self):
        with isolated_cache():
            from lib.gate_trace import emit_gate_span
            rid = "gate_rej"
            db = _new_run_db(rid)
            emit_gate_span(
                run_id=rid, gate_name="novelty-check",
                verdict="rejected", errors=["missing anchors"],
                target_id="paper-x",
            )
            con = sqlite3.connect(db)
            try:
                rows = con.execute(
                    "SELECT span_events.name, payload_json "
                    "FROM span_events JOIN spans USING (span_id) "
                    "WHERE spans.trace_id=? AND spans.kind='gate'",
                    (rid,),
                ).fetchall()
            finally:
                con.close()
            self.assertGreater(len(rows), 0)
            self.assertTrue(
                any(r[0] == "gate_rejected" for r in rows),
                f"expected gate_rejected event, got: {[r[0] for r in rows]}",
            )


class PhaseSpanCliTests(TestCase):
    """End-to-end: run db.py record-phase and verify a phase span lands."""

    def test_phase_start_emits_span(self):
        with isolated_cache():
            db_py = (_REPO / ".claude" / "skills" / "deep-research"
                     / "scripts" / "db.py")
            r = subprocess.run(
                [sys.executable, str(db_py), "init",
                 "--question", "test"],
                capture_output=True, text=True, cwd=str(_REPO),
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            # init prints the run_id (last whitespace-separated token).
            rid = r.stdout.strip().split()[-1]
            self.assertTrue(rid)
            # Mark scout phase started.
            r = subprocess.run(
                [sys.executable, str(db_py), "record-phase",
                 "--run-id", rid, "--phase", "scout", "--start"],
                capture_output=True, text=True, cwd=str(_REPO),
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            db = run_db_path(rid)
            con = sqlite3.connect(db)
            try:
                rows = con.execute(
                    "SELECT name, kind, status FROM spans "
                    "WHERE trace_id=? AND kind='phase'",
                    (rid,),
                ).fetchall()
            finally:
                con.close()
            self.assertGreater(len(rows), 0)
            self.assertEqual(rows[0][0], "scout")


if __name__ == "__main__":
    raise SystemExit(run_tests(
        EnvTraceContextTests,
        MaybeEmitToolCallTests,
        GateTraceTests,
        PhaseSpanCliTests,
    ))
