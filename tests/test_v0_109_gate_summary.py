"""v0.109 — gate-decision summary tests."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from tests.harness import TestCase, isolated_cache, run_tests
from lib import trace, trace_status, health
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


def _emit_gate(db: Path, *, trace_id: str, name: str,
               verdict: str, error_msg: str | None = None):
    trace.init_trace(db, trace_id=trace_id, run_id=trace_id)
    if verdict == "ok":
        with trace.start_span(
            db, trace_id, "gate", name,
            attrs={"verdict": "ok"},
        ):
            pass
    else:
        try:
            with trace.start_span(
                db, trace_id, "gate", name,
                attrs={"verdict": "rejected"},
            ):
                raise RuntimeError(error_msg or "rejected")
        except RuntimeError:
            pass


class GateSummaryTests(TestCase):
    def test_no_db_returns_empty(self):
        with isolated_cache():
            db = run_db_path("absent")
            s = trace_status.gate_summary(db)
            self.assertEqual(s["n_gates"], 0)

    def test_aggregates_by_name(self):
        with isolated_cache():
            db = _new_run_db("rid-g")
            _emit_gate(db, trace_id="rid-g",
                        name="publishability", verdict="ok")
            _emit_gate(db, trace_id="rid-g",
                        name="publishability", verdict="rejected",
                        error_msg="missing kill criterion")
            _emit_gate(db, trace_id="rid-g",
                        name="novelty", verdict="ok")
            s = trace_status.gate_summary(db)
            self.assertEqual(s["n_gates"], 3)
            pub = s["by_gate"]["publishability"]
            self.assertEqual(pub["n_total"], 2)
            self.assertEqual(pub["n_ok"], 1)
            self.assertEqual(pub["n_rejected"], 1)
            self.assertEqual(s["by_gate"]["novelty"]["n_ok"], 1)

    def test_recent_errors_captured(self):
        with isolated_cache():
            db = _new_run_db("rid-e")
            _emit_gate(db, trace_id="rid-e",
                        name="publishability", verdict="rejected",
                        error_msg="missing factor")
            s = trace_status.gate_summary(db)
            errs = s["by_gate"]["publishability"]["recent_errors"]
            self.assertGreater(len(errs), 0)


class GateAcrossRunsTests(TestCase):
    def test_empty(self):
        with isolated_cache():
            s = trace_status.gate_summary_across_runs()
            self.assertEqual(s["n_gates"], 0)

    def test_multi_db(self):
        with isolated_cache():
            db1 = _new_run_db("rid-1")
            db2 = _new_run_db("rid-2")
            _emit_gate(db1, trace_id="rid-1", name="novelty",
                        verdict="ok")
            _emit_gate(db2, trace_id="rid-2", name="novelty",
                        verdict="rejected",
                        error_msg="under 5 anchors")
            s = trace_status.gate_summary_across_runs()
            self.assertEqual(s["n_dbs"], 2)
            self.assertEqual(s["by_gate"]["novelty"]["n_ok"], 1)
            self.assertEqual(
                s["by_gate"]["novelty"]["n_rejected"], 1,
            )


class HealthIntegrationTests(TestCase):
    def test_health_includes_gates(self):
        with isolated_cache():
            db = _new_run_db("rid-h")
            _emit_gate(db, trace_id="rid-h",
                        name="publishability", verdict="rejected",
                        error_msg="x")
            r = health.collect()
            self.assertIn("gates", r)
            self.assertEqual(
                r["gates"]["by_gate"]["publishability"]["n_rejected"],
                1,
            )
            md = health.render_md(r)
            self.assertIn("Gate decisions", md)
            self.assertIn("publishability", md)


if __name__ == "__main__":
    raise SystemExit(run_tests(
        GateSummaryTests, GateAcrossRunsTests,
        HealthIntegrationTests,
    ))
