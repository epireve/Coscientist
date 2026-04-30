"""v0.188 — degraded-source health flag + source_selector skip-degraded."""
from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from lib.health import (
    collect,
    evaluate_alerts,
    mcp_error_rates,
)
from lib.source_selector import (
    is_source_degraded,
    select_source,
)
from tests.harness import TestCase, isolated_cache, run_tests


def _make_db(path: Path, spans: list[tuple[str, str, str]]) -> None:
    """spans: list of (name, status, started_at_iso)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.execute(
        "CREATE TABLE traces (trace_id TEXT, run_id TEXT, "
        "status TEXT, started_at TEXT)"
    )
    con.execute(
        "CREATE TABLE spans (span_id TEXT, trace_id TEXT, "
        "kind TEXT, name TEXT, status TEXT, "
        "started_at TEXT, ended_at TEXT, duration_ms INTEGER)"
    )
    for i, (name, status, sat) in enumerate(spans):
        con.execute(
            "INSERT INTO spans VALUES (?, 'tid', 'tool-call', "
            "?, ?, ?, NULL, 100)",
            (f"sp-{i}", name, status, sat),
        )
    con.commit()
    con.close()


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _ago(hours: float) -> str:
    return (
        datetime.now(UTC) - timedelta(hours=hours)
    ).isoformat()


class DegradedSourceTests(TestCase):
    def test_error_rates_aggregates_correctly(self):
        with isolated_cache() as cache:
            db = cache / "runs" / "run-1.db"
            spans = [
                ("mcp__semantic-scholar__search_papers", "error", _now()),
                ("mcp__semantic-scholar__search_papers", "error", _now()),
                ("mcp__semantic-scholar__search_papers", "ok", _now()),
                ("mcp__openalex__list_works", "ok", _now()),
                ("mcp__openalex__list_works", "ok", _now()),
            ]
            _make_db(db, spans)
            r = mcp_error_rates()
            self.assertIn("semantic-scholar", r)
            self.assertEqual(r["semantic-scholar"]["n_calls"], 3)
            self.assertEqual(r["semantic-scholar"]["n_errors"], 2)
            self.assertAlmostEqual(
                r["semantic-scholar"]["error_rate"], 2 / 3, places=3,
            )
            self.assertIn("openalex", r)
            self.assertEqual(r["openalex"]["n_errors"], 0)

    def test_window_filter_excludes_old_spans(self):
        with isolated_cache() as cache:
            db = cache / "runs" / "run-1.db"
            spans = [
                ("mcp__consensus__search", "error", _ago(1)),
                ("mcp__consensus__search", "error", _ago(48)),
                ("mcp__consensus__search", "error", _ago(72)),
            ]
            _make_db(db, spans)
            r = mcp_error_rates(window_hours=24)
            self.assertIn("consensus", r)
            self.assertEqual(r["consensus"]["n_calls"], 1)

    def test_empty_span_table_returns_empty(self):
        with isolated_cache() as cache:
            db = cache / "runs" / "run-1.db"
            _make_db(db, [])
            r = mcp_error_rates()
            self.assertEqual(r, {})

    def test_alert_fires_above_threshold(self):
        with isolated_cache() as cache:
            db = cache / "runs" / "run-1.db"
            spans = [
                ("mcp__semantic-scholar__x", "error", _now())
                for _ in range(6)
            ] + [
                ("mcp__semantic-scholar__x", "ok", _now()),
            ]
            _make_db(db, spans)
            r = collect()
            alerts = evaluate_alerts(r)
            codes = [a["code"] for a in alerts]
            self.assertIn("mcp_degraded", codes)

    def test_alert_silent_below_threshold(self):
        with isolated_cache() as cache:
            db = cache / "runs" / "run-1.db"
            spans = [
                ("mcp__openalex__x", "ok", _now()) for _ in range(10)
            ]
            _make_db(db, spans)
            r = collect()
            alerts = evaluate_alerts(r)
            codes = [a["code"] for a in alerts]
            self.assertNotIn("mcp_degraded", codes)

    def test_alert_silent_below_n_calls_floor(self):
        with isolated_cache() as cache:
            db = cache / "runs" / "run-1.db"
            spans = [
                ("mcp__semantic-scholar__x", "error", _now())
                for _ in range(3)
            ]
            _make_db(db, spans)
            r = collect()
            alerts = evaluate_alerts(r)
            codes = [a["code"] for a in alerts]
            self.assertNotIn("mcp_degraded", codes)

    def test_is_source_degraded_high_error_rate(self):
        with isolated_cache() as cache:
            db = cache / "runs" / "run-1.db"
            spans = [
                ("mcp__semantic-scholar__x", "error", _now())
                for _ in range(6)
            ] + [("mcp__semantic-scholar__x", "ok", _now())]
            _make_db(db, spans)
            self.assertTrue(is_source_degraded("semantic-scholar"))

    def test_is_source_degraded_healthy_source(self):
        with isolated_cache() as cache:
            db = cache / "runs" / "run-1.db"
            spans = [
                ("mcp__openalex__x", "ok", _now()) for _ in range(10)
            ]
            _make_db(db, spans)
            self.assertFalse(is_source_degraded("openalex"))

    def test_is_source_degraded_no_data_fail_open(self):
        with isolated_cache():
            self.assertFalse(is_source_degraded("consensus"))
            self.assertFalse(is_source_degraded("semantic-scholar"))

    def test_select_source_skip_degraded_falls_through(self):
        with isolated_cache() as cache:
            db = cache / "runs" / "run-1.db"
            # Degrade Consensus
            spans = [
                ("mcp__consensus__search", "error", _now())
                for _ in range(6)
            ]
            _make_db(db, spans)
            rec = select_source(
                phase="discovery", mode="deep",
                open_question=True, skip_degraded=True,
            )
            # Original primary "consensus" should be replaced.
            self.assertTrue(rec.primary != "consensus")
            self.assertIn("v0.188", rec.reasoning)

    def test_select_source_skip_degraded_false_preserves_v0_147(self):
        with isolated_cache() as cache:
            db = cache / "runs" / "run-1.db"
            spans = [
                ("mcp__consensus__search", "error", _now())
                for _ in range(6)
            ]
            _make_db(db, spans)
            rec = select_source(
                phase="discovery", mode="deep",
                open_question=True, skip_degraded=False,
            )
            self.assertEqual(rec.primary, "consensus")


if __name__ == "__main__":
    raise SystemExit(run_tests(DegradedSourceTests))
