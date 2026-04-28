"""v0.116 — OTLP-compatible trace export tests."""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

from lib import trace, trace_render
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


class IsoToNanoTests(TestCase):
    def test_known_timestamp(self):
        # 2026-04-28T00:00:00+00:00 = 1777334400 sec since epoch
        n = trace_render._iso_to_nano("2026-04-28T00:00:00+00:00")
        self.assertEqual(n, 1777334400 * 1_000_000_000)

    def test_z_suffix_handled(self):
        n = trace_render._iso_to_nano("2026-04-28T00:00:00Z")
        self.assertEqual(n, 1777334400 * 1_000_000_000)

    def test_empty_returns_zero(self):
        self.assertEqual(trace_render._iso_to_nano(None), 0)
        self.assertEqual(trace_render._iso_to_nano(""), 0)

    def test_invalid_returns_zero(self):
        self.assertEqual(
            trace_render._iso_to_nano("not a timestamp"), 0,
        )


class RenderOtlpTests(TestCase):
    def test_none_payload_returns_empty_resource(self):
        out = trace_render.render_otlp(None)
        payload = json.loads(out)
        self.assertEqual(payload, {"resourceSpans": []})

    def test_basic_trace_round_trip(self):
        with isolated_cache():
            rid = "rid-otlp"
            db = _new_run_db(rid)
            trace.init_trace(db, trace_id=rid, run_id=rid)
            with trace.start_span(db, rid, "phase", "scout") as sp:
                sp.event("step", {"n": 1})
            with trace.start_span(db, rid, "tool-call", "lookup") as sp:
                pass
            try:
                with trace.start_span(db, rid, "gate", "novelty"):
                    raise ValueError("not enough anchors")
            except ValueError:
                pass
            payload = trace.get_trace(db, rid)
            otlp = json.loads(trace_render.render_otlp(payload))
            spans = otlp["resourceSpans"][0]["scopeSpans"][0]["spans"]
            self.assertEqual(len(spans), 3)
            kinds = {s["name"]: s["kind"] for s in spans}
            self.assertEqual(kinds["lookup"], 3)  # CLIENT
            self.assertEqual(kinds["scout"], 1)   # INTERNAL
            self.assertEqual(kinds["novelty"], 1)
            statuses = {s["name"]: s["status"]["code"]
                          for s in spans}
            self.assertEqual(statuses["scout"], 1)   # OK
            self.assertEqual(statuses["lookup"], 1)
            self.assertEqual(statuses["novelty"], 2)  # ERROR

    def test_resource_attributes_include_service_name(self):
        with isolated_cache():
            rid = "rid-svc"
            db = _new_run_db(rid)
            trace.init_trace(db, trace_id=rid, run_id=rid)
            payload = trace.get_trace(db, rid)
            otlp = json.loads(trace_render.render_otlp(payload))
            res_attrs = otlp["resourceSpans"][0]["resource"]["attributes"]
            keys = {a["key"] for a in res_attrs}
            self.assertIn("service.name", keys)
            self.assertIn("coscientist.run_id", keys)

    def test_span_events_preserved(self):
        with isolated_cache():
            rid = "rid-evt"
            db = _new_run_db(rid)
            trace.init_trace(db, trace_id=rid, run_id=rid)
            with trace.start_span(db, rid, "phase", "scout") as sp:
                sp.event("custom_event", {"foo": "bar"})
            payload = trace.get_trace(db, rid)
            otlp = json.loads(trace_render.render_otlp(payload))
            span = otlp["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
            self.assertEqual(len(span["events"]), 1)
            self.assertEqual(
                span["events"][0]["name"], "custom_event",
            )


class CliTests(TestCase):
    def test_otlp_format_via_cli(self):
        with isolated_cache():
            rid = "rid-cli"
            db = _new_run_db(rid)
            trace.init_trace(db, trace_id=rid, run_id=rid)
            with trace.start_span(db, rid, "phase", "scout"):
                pass
            r = subprocess.run(
                [sys.executable, "-m", "lib.trace_render",
                 "--db", str(db), "--trace-id", rid,
                 "--format", "otlp"],
                capture_output=True, text=True, cwd=str(_REPO),
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            payload = json.loads(r.stdout)
            self.assertIn("resourceSpans", payload)


if __name__ == "__main__":
    raise SystemExit(run_tests(
        IsoToNanoTests, RenderOtlpTests, CliTests,
    ))
