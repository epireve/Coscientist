"""v0.117 — OTLP hex ID compliance tests."""
from __future__ import annotations

import json
import sqlite3
import string
from pathlib import Path

from tests.harness import TestCase, isolated_cache, run_tests
from lib import trace, trace_render
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


class ToHexIdTests(TestCase):
    def test_strips_trace_prefix(self):
        out = trace_render._to_hex_id("trace-abc123def456",
                                       length=32)
        self.assertEqual(len(out), 32)
        self.assertTrue(all(c in "0123456789abcdef" for c in out))

    def test_strips_span_prefix(self):
        out = trace_render._to_hex_id("span-deadbeef", length=16)
        self.assertEqual(len(out), 16)
        self.assertTrue(out.endswith("deadbeef"))

    def test_short_input_padded_with_zeros(self):
        out = trace_render._to_hex_id("span-ab", length=16)
        self.assertEqual(len(out), 16)
        self.assertTrue(out.startswith("0" * 14))
        self.assertTrue(out.endswith("ab"))

    def test_long_input_truncated(self):
        out = trace_render._to_hex_id("span-" + "a" * 50,
                                       length=16)
        self.assertEqual(out, "a" * 16)

    def test_empty_returns_zeros(self):
        self.assertEqual(
            trace_render._to_hex_id(None, length=16), "0" * 16,
        )
        self.assertEqual(
            trace_render._to_hex_id("", length=32), "0" * 32,
        )

    def test_non_hex_chars_substituted(self):
        out = trace_render._to_hex_id("span-XYZ", length=16)
        self.assertTrue(all(c in "0123456789abcdef" for c in out))


class OtlpComplianceTests(TestCase):
    def test_trace_id_is_32_hex(self):
        with isolated_cache():
            rid = "rid-c"
            db = _new_run_db(rid)
            trace.init_trace(db, trace_id=rid, run_id=rid)
            with trace.start_span(db, rid, "phase", "scout"):
                pass
            payload = trace.get_trace(db, rid)
            otlp = json.loads(trace_render.render_otlp(payload))
            spans = otlp["resourceSpans"][0]["scopeSpans"][0]["spans"]
            for s in spans:
                self.assertEqual(len(s["traceId"]), 32,
                                  f"traceId not 32 chars: {s['traceId']}")
                self.assertTrue(
                    all(c in string.hexdigits.lower()
                         for c in s["traceId"]),
                    f"non-hex in traceId: {s['traceId']}",
                )

    def test_span_id_is_16_hex(self):
        with isolated_cache():
            rid = "rid-s"
            db = _new_run_db(rid)
            trace.init_trace(db, trace_id=rid, run_id=rid)
            with trace.start_span(db, rid, "phase", "scout"):
                pass
            payload = trace.get_trace(db, rid)
            otlp = json.loads(trace_render.render_otlp(payload))
            spans = otlp["resourceSpans"][0]["scopeSpans"][0]["spans"]
            for s in spans:
                self.assertEqual(len(s["spanId"]), 16)
                self.assertTrue(
                    all(c in string.hexdigits.lower()
                         for c in s["spanId"]),
                )

    def test_parent_span_id_when_present_also_hex(self):
        with isolated_cache():
            rid = "rid-p"
            db = _new_run_db(rid)
            trace.init_trace(db, trace_id=rid, run_id=rid)
            with trace.start_span(db, rid, "phase", "outer") as outer:
                with trace.start_span(
                    db, rid, "tool-call", "inner",
                    parent_span_id=outer.span_id,
                ):
                    pass
            payload = trace.get_trace(db, rid)
            otlp = json.loads(trace_render.render_otlp(payload))
            spans = otlp["resourceSpans"][0]["scopeSpans"][0]["spans"]
            # Find the inner one
            inner = next(s for s in spans if s["name"] == "inner")
            self.assertEqual(len(inner["parentSpanId"]), 16)
            # Parent ID should differ from all-zeros (real parent)
            self.assertTrue(
                set(inner["parentSpanId"]) != {"0"},
                f"parentSpanId is all zeros: {inner['parentSpanId']}",
            )

    def test_raw_ids_preserved_in_attributes(self):
        with isolated_cache():
            rid = "rid-rt"
            db = _new_run_db(rid)
            trace.init_trace(db, trace_id=rid, run_id=rid)
            with trace.start_span(db, rid, "phase", "scout"):
                pass
            payload = trace.get_trace(db, rid)
            raw_span_id = payload["spans"][0]["span_id"]
            otlp = json.loads(trace_render.render_otlp(payload))
            # Resource attrs should include coscientist.trace_id
            res_attrs = otlp["resourceSpans"][0]["resource"][
                "attributes"
            ]
            keys = {a["key"] for a in res_attrs}
            self.assertIn("coscientist.trace_id", keys)
            # Span attrs should include coscientist.span_id matching
            # the raw ID (round-trip).
            span_attrs = otlp["resourceSpans"][0]["scopeSpans"][0][
                "spans"
            ][0]["attributes"]
            cs_span_id = next(
                a["value"]["stringValue"] for a in span_attrs
                if a["key"] == "coscientist.span_id"
            )
            self.assertEqual(cs_span_id, raw_span_id)


if __name__ == "__main__":
    raise SystemExit(run_tests(
        ToHexIdTests, OtlpComplianceTests,
    ))
