"""v0.113 — alert thresholds in health dump."""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from tests.harness import TestCase, isolated_cache, run_tests
from lib import health
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


class EvaluateAlertsTests(TestCase):
    def test_no_alerts_for_clean_report(self):
        r = {
            "active": [], "stale": [], "failed_spans_total": 0,
            "tool_latency": {"by_tool": {}},
            "quality": {"by_agent": {}},
        }
        self.assertEqual(health.evaluate_alerts(r), [])

    def test_stale_spans_fires_warn(self):
        r = {
            "active": [], "stale": [{"span_id": "x"}],
            "failed_spans_total": 0,
            "tool_latency": {"by_tool": {}},
            "quality": {"by_agent": {}},
        }
        a = health.evaluate_alerts(r)
        self.assertEqual(len(a), 1)
        self.assertEqual(a[0]["code"], "stale_spans")
        self.assertEqual(a[0]["severity"], "warn")

    def test_failed_spans_fires_crit(self):
        r = {
            "active": [], "stale": [],
            "failed_spans_total": 10,
            "tool_latency": {"by_tool": {}},
            "quality": {"by_agent": {}},
        }
        a = health.evaluate_alerts(r)
        self.assertTrue(any(
            x["code"] == "failed_spans" and x["severity"] == "crit"
            for x in a
        ))

    def test_tool_error_rate_fires_crit(self):
        r = {
            "active": [], "stale": [], "failed_spans_total": 0,
            "tool_latency": {
                "by_tool": {
                    "lookup_doi": {
                        "n": 10, "n_errors": 4,
                        "mean_ms": 100, "p50_ms": 100,
                        "p95_ms": 200, "max_ms": 200,
                    },
                },
            },
            "quality": {"by_agent": {}},
        }
        a = health.evaluate_alerts(r)
        codes = [x["code"] for x in a]
        self.assertIn("tool_error_rate", codes)

    def test_low_quality_fires_warn(self):
        r = {
            "active": [], "stale": [], "failed_spans_total": 0,
            "tool_latency": {"by_tool": {}},
            "quality": {
                "by_agent": {
                    "scout": {
                        "n": 5, "mean": 0.3, "min": 0.2,
                        "max": 0.4, "n_runs": 5,
                    },
                },
            },
        }
        a = health.evaluate_alerts(r)
        self.assertTrue(any(x["code"] == "low_quality" for x in a))

    def test_custom_thresholds_override(self):
        r = {
            "active": [], "stale": [],
            "failed_spans_total": 3,
            "tool_latency": {"by_tool": {}},
            "quality": {"by_agent": {}},
        }
        # default max_failed_spans=5; bump to 1 to fire
        a = health.evaluate_alerts(
            r, thresholds={"max_failed_spans": 1},
        )
        self.assertTrue(any(x["code"] == "failed_spans" for x in a))


class RenderTests(TestCase):
    def test_alerts_banner_in_md(self):
        r = {
            "n_runs": 0, "active": [], "stale": [],
            "tool_latency": {"by_tool": {}},
            "quality": {"by_agent": {}},
            "failed_spans_total": 0,
        }
        alerts = [{
            "severity": "crit", "code": "failed_spans",
            "message": "10 failed", "value": 10, "threshold": 5,
        }]
        out = health.render_md(r, alerts=alerts)
        self.assertIn("## Alerts", out)
        self.assertIn("🚨", out)
        self.assertIn("failed_spans", out)


class CliExitCodeTests(TestCase):
    def test_clean_exit_zero(self):
        with isolated_cache():
            r = subprocess.run(
                [sys.executable, "-m", "lib.health",
                 "--format", "json"],
                capture_output=True, text=True, cwd=str(_REPO),
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            payload = json.loads(r.stdout)
            self.assertEqual(payload["alerts"], [])

    def test_no_alerts_flag_skips_evaluation(self):
        with isolated_cache():
            r = subprocess.run(
                [sys.executable, "-m", "lib.health",
                 "--format", "json", "--no-alerts"],
                capture_output=True, text=True, cwd=str(_REPO),
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            payload = json.loads(r.stdout)
            self.assertEqual(payload["alerts"], [])


if __name__ == "__main__":
    raise SystemExit(run_tests(
        EvaluateAlertsTests, RenderTests, CliExitCodeTests,
    ))
