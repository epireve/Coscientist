"""v0.108 — harvest summary aggregation tests."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from lib import health, trace, trace_status
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


def _emit_harvest(db: Path, *, trace_id: str, persona: str,
                  phase: str, raw: int, deduped: int,
                  kept: int, queries: int):
    trace.init_trace(db, trace_id=trace_id, run_id=trace_id)
    with trace.start_span(
        db, trace_id, "harvest", f"{persona}/{phase}",
        attrs={"persona": persona, "phase": phase},
    ) as sp:
        sp.event("harvest_write", {
            "raw_count": raw, "deduped_count": deduped,
            "kept_count": kept, "queries_sent": queries,
        })


class HarvestSummaryTests(TestCase):
    def test_no_db_returns_empty(self):
        with isolated_cache():
            db = run_db_path("absent")
            s = trace_status.harvest_summary(db)
            self.assertEqual(s["n_harvests"], 0)
            self.assertEqual(s["totals"]["raw"], 0)

    def test_aggregates_by_persona(self):
        with isolated_cache():
            db = _new_run_db("rid-h")
            _emit_harvest(db, trace_id="rid-h", persona="scout",
                           phase="phase0", raw=100, deduped=80,
                           kept=50, queries=3)
            _emit_harvest(db, trace_id="rid-h",
                           persona="cartographer",
                           phase="phase1", raw=200, deduped=150,
                           kept=80, queries=5)
            s = trace_status.harvest_summary(db)
            self.assertEqual(s["n_harvests"], 2)
            self.assertEqual(s["totals"]["raw"], 300)
            self.assertEqual(s["totals"]["kept"], 130)
            self.assertEqual(s["by_persona"]["scout"]["kept"], 50)
            self.assertEqual(
                s["by_persona"]["cartographer"]["queries"], 5,
            )

    def test_filter_by_trace_id(self):
        with isolated_cache():
            db = _new_run_db("rid-multi")
            _emit_harvest(db, trace_id="trace-a", persona="scout",
                           phase="p0", raw=10, deduped=10,
                           kept=10, queries=1)
            _emit_harvest(db, trace_id="trace-b", persona="scout",
                           phase="p0", raw=99, deduped=99,
                           kept=99, queries=9)
            s = trace_status.harvest_summary(db, trace_id="trace-a")
            self.assertEqual(s["totals"]["raw"], 10)
            # filtered correctly — does not include trace-b's 99
            self.assertEqual(len(s["by_persona"]), 1)


class HarvestAcrossRunsTests(TestCase):
    def test_empty_root_returns_empty(self):
        with isolated_cache():
            s = trace_status.harvest_summary_across_runs()
            self.assertEqual(s["n_harvests"], 0)
            self.assertEqual(s["n_dbs"], 0)

    def test_multi_db_aggregation(self):
        with isolated_cache():
            db1 = _new_run_db("rid-1")
            db2 = _new_run_db("rid-2")
            _emit_harvest(db1, trace_id="rid-1", persona="scout",
                           phase="p0", raw=10, deduped=10,
                           kept=10, queries=1)
            _emit_harvest(db2, trace_id="rid-2", persona="scout",
                           phase="p0", raw=20, deduped=20,
                           kept=20, queries=2)
            s = trace_status.harvest_summary_across_runs()
            self.assertEqual(s["n_dbs"], 2)
            self.assertEqual(s["n_harvests"], 2)
            self.assertEqual(s["totals"]["kept"], 30)
            self.assertEqual(s["by_persona"]["scout"]["kept"], 30)


class HealthIntegrationTests(TestCase):
    def test_health_includes_harvests_section(self):
        with isolated_cache():
            db = _new_run_db("rid-health")
            _emit_harvest(db, trace_id="rid-health",
                           persona="scout", phase="p0",
                           raw=50, deduped=40, kept=30, queries=2)
            r = health.collect()
            self.assertIn("harvests", r)
            self.assertEqual(
                r["harvests"]["totals"]["kept"], 30,
            )
            md = health.render_md(r)
            self.assertIn("Harvest activity", md)
            self.assertIn("scout", md)


if __name__ == "__main__":
    raise SystemExit(run_tests(
        HarvestSummaryTests, HarvestAcrossRunsTests,
        HealthIntegrationTests,
    ))
