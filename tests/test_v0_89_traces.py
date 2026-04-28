"""v0.89 — execution-trace span tests."""
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


class MigrationV11Tests(TestCase):
    def test_v11_creates_three_tables(self):
        with isolated_cache():
            db = _new_run_db("trace_v11")
            con = sqlite3.connect(db)
            try:
                tables = {
                    r[0] for r in con.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                }
            finally:
                con.close()
            for t in ("traces", "spans", "span_events"):
                self.assertIn(t, tables)


class TraceLifecycleTests(TestCase):
    def test_init_then_end(self):
        with isolated_cache():
            db = _new_run_db("trace_life")
            tid = "trace-life-1"
            trace.init_trace(db, trace_id=tid, run_id="trace_life")
            trace.end_trace(db, tid, status="ok")
            con = sqlite3.connect(db)
            try:
                row = con.execute(
                    "SELECT trace_id, run_id, status, completed_at "
                    "FROM traces WHERE trace_id=?", (tid,),
                ).fetchone()
            finally:
                con.close()
            self.assertEqual(row[0], tid)
            self.assertEqual(row[1], "trace_life")
            self.assertEqual(row[2], "ok")
            self.assertIsNotNone(row[3])

    def test_init_idempotent(self):
        with isolated_cache():
            db = _new_run_db("idem")
            trace.init_trace(db, trace_id="t1", run_id="r1")
            trace.init_trace(db, trace_id="t1", run_id="r1")  # again
            con = sqlite3.connect(db)
            try:
                n = con.execute(
                    "SELECT COUNT(*) FROM traces WHERE trace_id='t1'"
                ).fetchone()[0]
            finally:
                con.close()
            self.assertEqual(n, 1)

    def test_invalid_end_status_rejected(self):
        with isolated_cache():
            db = _new_run_db("invalid")
            trace.init_trace(db, trace_id="bad")
            with self.assertRaises(ValueError):
                trace.end_trace(db, "bad", status="weird")


class SpanContextManagerTests(TestCase):
    def test_ok_span_records_duration(self):
        with isolated_cache():
            db = _new_run_db("span_ok")
            tid = "trace-ok"
            trace.init_trace(db, trace_id=tid)
            with trace.start_span(db, tid, "phase", "scout") as sp:
                self.assertTrue(sp.span_id.startswith("span-"))
            con = sqlite3.connect(db)
            try:
                row = con.execute(
                    "SELECT status, duration_ms, ended_at FROM spans "
                    "WHERE trace_id=?", (tid,),
                ).fetchone()
            finally:
                con.close()
            self.assertEqual(row[0], "ok")
            self.assertGreaterEqual(row[1], 0)
            self.assertIsNotNone(row[2])

    def test_error_span_persists_traceback(self):
        with isolated_cache():
            db = _new_run_db("span_err")
            tid = "trace-err"
            trace.init_trace(db, trace_id=tid)
            try:
                with trace.start_span(db, tid, "phase", "boom"):
                    raise RuntimeError("kaboom")
            except RuntimeError:
                pass
            con = sqlite3.connect(db)
            try:
                row = con.execute(
                    "SELECT status, error_kind, error_msg FROM spans "
                    "WHERE trace_id=?", (tid,),
                ).fetchone()
            finally:
                con.close()
            self.assertEqual(row[0], "error")
            self.assertEqual(row[1], "RuntimeError")
            self.assertIn("kaboom", row[2])

    def test_invalid_kind_rejected(self):
        with isolated_cache():
            db = _new_run_db("kindbad")
            trace.init_trace(db, trace_id="x")
            with self.assertRaises(ValueError):
                with trace.start_span(db, "x", "garbage", "y"):
                    pass

    def test_nested_span_records_parent(self):
        with isolated_cache():
            db = _new_run_db("nested")
            tid = "trace-nested"
            trace.init_trace(db, trace_id=tid)
            with trace.start_span(db, tid, "phase", "outer") as outer:
                with trace.start_span(
                    db, tid, "tool-call", "inner",
                    parent_span_id=outer.span_id,
                ):
                    pass
            con = sqlite3.connect(db)
            try:
                rows = con.execute(
                    "SELECT name, parent_span_id FROM spans "
                    "WHERE trace_id=? ORDER BY started_at",
                    (tid,),
                ).fetchall()
            finally:
                con.close()
            self.assertEqual(len(rows), 2)
            outer_id = next(r for r in rows if r[0] == "outer")
            inner = next(r for r in rows if r[0] == "inner")
            self.assertIsNone(outer_id[1])
            self.assertIsNotNone(inner[1])

    def test_event_persists_payload(self):
        with isolated_cache():
            db = _new_run_db("evt")
            tid = "trace-evt"
            trace.init_trace(db, trace_id=tid)
            with trace.start_span(db, tid, "phase", "with_event") as sp:
                sp.event("loaded", {"path": "/x.json", "n": 42})
            con = sqlite3.connect(db)
            try:
                row = con.execute(
                    "SELECT span_events.name, payload_json "
                    "FROM span_events JOIN spans USING (span_id) "
                    "WHERE spans.trace_id=?",
                    (tid,),
                ).fetchone()
            finally:
                con.close()
            self.assertEqual(row[0], "loaded")
            payload = json.loads(row[1])
            self.assertEqual(payload["n"], 42)

    def test_attrs_persisted(self):
        with isolated_cache():
            db = _new_run_db("attrs")
            tid = "trace-attrs"
            trace.init_trace(db, trace_id=tid)
            with trace.start_span(
                db, tid, "phase", "with_attrs",
                attrs={"start_attr": 1},
            ) as sp:
                sp.set_attrs({"mid_attr": 2})
            con = sqlite3.connect(db)
            try:
                row = con.execute(
                    "SELECT attrs_json FROM spans WHERE trace_id=?",
                    (tid,),
                ).fetchone()
            finally:
                con.close()
            attrs = json.loads(row[0])
            self.assertEqual(attrs["start_attr"], 1)
            self.assertEqual(attrs["mid_attr"], 2)


class GetTraceTests(TestCase):
    def test_full_round_trip(self):
        with isolated_cache():
            db = _new_run_db("rt")
            tid = "trace-rt"
            trace.init_trace(db, trace_id=tid, run_id="rt")
            with trace.start_span(db, tid, "phase", "p1") as sp:
                sp.event("e1", {"x": 1})
                with trace.start_span(
                    db, tid, "tool-call", "t1",
                    parent_span_id=sp.span_id,
                ):
                    pass
            trace.end_trace(db, tid, status="ok")
            payload = trace.get_trace(db, tid)
            self.assertIsNotNone(payload)
            self.assertEqual(payload["trace"]["trace_id"], tid)
            self.assertEqual(len(payload["spans"]), 2)
            phase_span = next(
                s for s in payload["spans"] if s["name"] == "p1"
            )
            self.assertEqual(len(phase_span["events"]), 1)

    def test_missing_trace_returns_none(self):
        with isolated_cache():
            db = _new_run_db("none")
            self.assertIsNone(trace.get_trace(db, "no-such"))


if __name__ == "__main__":
    raise SystemExit(run_tests(
        MigrationV11Tests,
        TraceLifecycleTests,
        SpanContextManagerTests,
        GetTraceTests,
    ))
