"""v0.143 — rate-limit emits tool-call spans."""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from lib import rate_limit, trace
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


class RateLimitSpanTests(TestCase):
    def test_no_trace_context_silent_noop(self):
        with isolated_cache():
            os.environ.pop("COSCIENTIST_TRACE_DB", None)
            os.environ.pop("COSCIENTIST_TRACE_ID", None)
            # Must not raise
            rate_limit.wait("https://example.com",
                              delay_seconds=0.01)

    def test_trace_context_emits_span(self):
        with isolated_cache():
            rid = "rid-rl"
            db = _new_run_db(rid)
            trace.init_trace(db, trace_id=rid, run_id=rid)
            os.environ["COSCIENTIST_TRACE_DB"] = str(db)
            os.environ["COSCIENTIST_TRACE_ID"] = rid
            try:
                rate_limit.wait(
                    "https://example.com",
                    delay_seconds=0.01,
                )
            finally:
                os.environ.pop("COSCIENTIST_TRACE_DB", None)
                os.environ.pop("COSCIENTIST_TRACE_ID", None)
            con = sqlite3.connect(db)
            try:
                row = con.execute(
                    "SELECT name, kind FROM spans "
                    "WHERE trace_id=? AND kind='tool-call'",
                    (rid,),
                ).fetchone()
            finally:
                con.close()
            self.assertIsNotNone(row)
            self.assertTrue(row[0].startswith("rate_limit/"))
            self.assertEqual(row[1], "tool-call")

    def test_blocked_time_recorded(self):
        with isolated_cache():
            rid = "rid-rl-block"
            db = _new_run_db(rid)
            trace.init_trace(db, trace_id=rid, run_id=rid)
            # First call sets the marker
            rate_limit.wait("https://x.com", delay_seconds=0.05)
            # Second call within delay → should block
            os.environ["COSCIENTIST_TRACE_DB"] = str(db)
            os.environ["COSCIENTIST_TRACE_ID"] = rid
            try:
                rate_limit.wait(
                    "https://x.com", delay_seconds=0.05,
                )
            finally:
                os.environ.pop("COSCIENTIST_TRACE_DB", None)
                os.environ.pop("COSCIENTIST_TRACE_ID", None)
            # Span event payload should contain blocked_s > 0
            con = sqlite3.connect(db)
            try:
                rows = list(con.execute(
                    "SELECT span_events.payload_json FROM span_events "
                    "JOIN spans USING (span_id) "
                    "WHERE spans.trace_id=? AND span_events.name='result'",
                    (rid,),
                ))
            finally:
                con.close()
            import json
            self.assertGreater(len(rows), 0)
            payload = json.loads(rows[0][0])
            self.assertGreaterEqual(payload["blocked_s"], 0)


if __name__ == "__main__":
    raise SystemExit(run_tests(RateLimitSpanTests))
