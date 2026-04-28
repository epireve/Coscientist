"""v0.91 — trace renderer tests."""
from __future__ import annotations

import json
import sqlite3
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


def _seed_trace(db: Path, tid: str = "trace-r"):
    trace.init_trace(db, trace_id=tid, run_id="r1")
    with trace.start_span(db, tid, "phase", "scout") as scout:
        scout.event("harvest_loaded", {"n": 30})
        scout.set_attrs({"n_papers": 30})
        with trace.start_span(
            db, tid, "tool-call", "lookup_doi",
            parent_span_id=scout.span_id,
        ):
            pass
    try:
        with trace.start_span(
            db, tid, "phase", "boom",
            capture_on_error=True,
        ):
            raise ValueError("kaboom")
    except ValueError:
        pass
    trace.end_trace(db, tid, status="error")
    return tid


class RenderMermaidTests(TestCase):
    def test_empty_trace(self):
        out = trace_render.render_mermaid(None)
        self.assertIn("graph TD", out)
        self.assertIn("no trace found", out)

    def test_root_node(self):
        with isolated_cache():
            db = _new_run_db("rm")
            tid = _seed_trace(db)
            payload = trace.get_trace(db, tid)
            out = trace_render.render_mermaid(payload)
            self.assertIn("graph TD", out)
            self.assertIn(tid[:16], out)

    def test_failed_spans_painted(self):
        with isolated_cache():
            db = _new_run_db("rmfail")
            tid = _seed_trace(db)
            payload = trace.get_trace(db, tid)
            out = trace_render.render_mermaid(payload)
            self.assertIn("classDef failed", out)
            # Failed span name must be present somewhere.
            self.assertIn("boom", out)


class RenderMarkdownTests(TestCase):
    def test_empty_trace(self):
        out = trace_render.render_markdown(None)
        self.assertIn("not found", out)

    def test_renders_spans_in_order(self):
        with isolated_cache():
            db = _new_run_db("rmd")
            tid = _seed_trace(db)
            payload = trace.get_trace(db, tid)
            out = trace_render.render_markdown(payload)
            # Title.
            self.assertIn(tid, out)
            # Phase + tool-call + boom span all present.
            self.assertIn("scout", out)
            self.assertIn("lookup_doi", out)
            self.assertIn("boom", out)
            # Status emoji shows.
            self.assertIn("❌", out)

    def test_event_payload_in_output(self):
        with isolated_cache():
            db = _new_run_db("evtmd")
            tid = _seed_trace(db)
            payload = trace.get_trace(db, tid)
            out = trace_render.render_markdown(payload)
            self.assertIn("harvest_loaded", out)


class RenderJsonTests(TestCase):
    def test_round_trip(self):
        with isolated_cache():
            db = _new_run_db("rjs")
            tid = _seed_trace(db)
            payload = trace.get_trace(db, tid)
            out = trace_render.render_mermaid(payload)
            self.assertIsNotNone(out)
            # JSON path
            j = trace_render.render(payload, "json")
            parsed = json.loads(j)
            self.assertEqual(parsed["trace"]["trace_id"], tid)


class CliInvariantTests(TestCase):
    def test_invalid_format_rejected(self):
        with self.assertRaises(ValueError):
            trace_render.render({}, "garbage")


if __name__ == "__main__":
    raise SystemExit(run_tests(
        RenderMermaidTests,
        RenderMarkdownTests,
        RenderJsonTests,
        CliInvariantTests,
    ))
