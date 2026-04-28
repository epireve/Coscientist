"""v0.126 — per-project health threshold overlay tests."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from lib import health
from lib.cache import cache_root
from tests.harness import TestCase, isolated_cache, run_tests

_REPO = Path(__file__).resolve().parents[1]


def _write_config(path: Path, payload: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))


class PerProjectOverlayTests(TestCase):
    def test_project_overrides_global(self):
        with isolated_cache():
            global_path = cache_root() / "health_thresholds.json"
            project_path = (
                cache_root() / "projects" / "myproj" /
                "health_thresholds.json"
            )
            _write_config(global_path, {"max_failed_spans": 50})
            _write_config(project_path, {"max_failed_spans": 1})
            t = health.load_thresholds(project_id="myproj")
            self.assertEqual(t["max_failed_spans"], 1)

    def test_project_only_inherits_defaults(self):
        with isolated_cache():
            project_path = (
                cache_root() / "projects" / "p2" /
                "health_thresholds.json"
            )
            _write_config(project_path, {"max_failed_spans": 100})
            t = health.load_thresholds(project_id="p2")
            self.assertEqual(t["max_failed_spans"], 100)
            # Other keys inherit from DEFAULT_THRESHOLDS
            self.assertEqual(
                t["max_stale_spans"],
                health.DEFAULT_THRESHOLDS["max_stale_spans"],
            )

    def test_kwargs_beat_project(self):
        with isolated_cache():
            project_path = (
                cache_root() / "projects" / "p3" /
                "health_thresholds.json"
            )
            _write_config(project_path, {"max_failed_spans": 1})
            t = health.load_thresholds(
                project_id="p3",
                overrides={"max_failed_spans": 999},
            )
            self.assertEqual(t["max_failed_spans"], 999)

    def test_missing_project_config_falls_back(self):
        with isolated_cache():
            t = health.load_thresholds(project_id="never-exists")
            self.assertEqual(
                t["max_failed_spans"],
                health.DEFAULT_THRESHOLDS["max_failed_spans"],
            )

    def test_invalid_project_json_falls_back(self):
        with isolated_cache():
            project_path = (
                cache_root() / "projects" / "p4" /
                "health_thresholds.json"
            )
            project_path.parent.mkdir(parents=True, exist_ok=True)
            project_path.write_text("not json {{")
            t = health.load_thresholds(project_id="p4")
            self.assertEqual(
                t["max_failed_spans"],
                health.DEFAULT_THRESHOLDS["max_failed_spans"],
            )


class EvaluateProjectScopedTests(TestCase):
    def test_alerts_use_project_overlay(self):
        with isolated_cache():
            project_path = (
                cache_root() / "projects" / "tight" /
                "health_thresholds.json"
            )
            _write_config(project_path, {"max_failed_spans": 1})
            r = {
                "active": [], "stale": [],
                "failed_spans_total": 3,
                "tool_latency": {"by_tool": {}},
                "quality": {"by_agent": {}},
            }
            alerts = health.evaluate_alerts(r, project_id="tight")
            self.assertTrue(any(
                a["code"] == "failed_spans" for a in alerts
            ))

    def test_no_project_no_overlay(self):
        with isolated_cache():
            r = {
                "active": [], "stale": [],
                "failed_spans_total": 3,
                "tool_latency": {"by_tool": {}},
                "quality": {"by_agent": {}},
            }
            alerts = health.evaluate_alerts(r)  # default 5
            self.assertFalse(any(
                a["code"] == "failed_spans" for a in alerts
            ))


class CliTests(TestCase):
    def test_show_thresholds_with_project(self):
        with isolated_cache():
            project_path = (
                cache_root() / "projects" / "cliproj" /
                "health_thresholds.json"
            )
            _write_config(project_path, {"max_active_runs": 1})
            r = subprocess.run(
                [sys.executable, "-m", "lib.health",
                 "--show-thresholds",
                 "--project-id", "cliproj"],
                capture_output=True, text=True, cwd=str(_REPO),
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            payload = json.loads(r.stdout)
            self.assertEqual(payload["project_id"], "cliproj")
            self.assertTrue(payload["project_config_exists"])
            self.assertEqual(
                payload["thresholds"]["max_active_runs"], 1,
            )

    def test_show_thresholds_no_project_global_only(self):
        with isolated_cache():
            r = subprocess.run(
                [sys.executable, "-m", "lib.health",
                 "--show-thresholds"],
                capture_output=True, text=True, cwd=str(_REPO),
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            payload = json.loads(r.stdout)
            self.assertIsNone(payload["project_id"])
            self.assertFalse(payload["project_config_exists"])


if __name__ == "__main__":
    raise SystemExit(run_tests(
        PerProjectOverlayTests, EvaluateProjectScopedTests,
        CliTests,
    ))
