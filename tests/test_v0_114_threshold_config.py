"""v0.114 — health_thresholds.json config file tests."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from tests.harness import TestCase, isolated_cache, run_tests
from lib import health


_REPO = Path(__file__).resolve().parents[1]


def _write_config(payload):
    tf = tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False,
    )
    json.dump(payload, tf)
    tf.close()
    return Path(tf.name)


class LoadThresholdsTests(TestCase):
    def test_defaults_when_no_config(self):
        with isolated_cache():
            t = health.load_thresholds()
            self.assertEqual(
                t["max_failed_spans"],
                health.DEFAULT_THRESHOLDS["max_failed_spans"],
            )

    def test_config_file_overrides_defaults(self):
        cfg = _write_config({"max_failed_spans": 100})
        try:
            t = health.load_thresholds(config_path=cfg)
            self.assertEqual(t["max_failed_spans"], 100)
            # other keys unaffected
            self.assertEqual(
                t["max_stale_spans"],
                health.DEFAULT_THRESHOLDS["max_stale_spans"],
            )
        finally:
            cfg.unlink()

    def test_kwargs_override_config_file(self):
        cfg = _write_config({"max_failed_spans": 100})
        try:
            t = health.load_thresholds(
                config_path=cfg,
                overrides={"max_failed_spans": 1},
            )
            self.assertEqual(t["max_failed_spans"], 1)
        finally:
            cfg.unlink()

    def test_unknown_keys_ignored(self):
        cfg = _write_config({"unknown_key": 999})
        try:
            t = health.load_thresholds(config_path=cfg)
            self.assertNotIn("unknown_key", t)
        finally:
            cfg.unlink()

    def test_invalid_json_falls_back_to_defaults(self):
        tf = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False,
        )
        tf.write("not json {{{")
        tf.close()
        try:
            t = health.load_thresholds(config_path=Path(tf.name))
            self.assertEqual(
                t["max_failed_spans"],
                health.DEFAULT_THRESHOLDS["max_failed_spans"],
            )
        finally:
            Path(tf.name).unlink()

    def test_wrong_type_rejected(self):
        cfg = _write_config({"max_failed_spans": "five"})
        try:
            t = health.load_thresholds(config_path=cfg)
            # default kept (string ignored)
            self.assertEqual(
                t["max_failed_spans"],
                health.DEFAULT_THRESHOLDS["max_failed_spans"],
            )
        finally:
            cfg.unlink()

    def test_int_accepted_for_float_field(self):
        cfg = _write_config({"max_tool_error_rate": 1})
        try:
            t = health.load_thresholds(config_path=cfg)
            self.assertEqual(t["max_tool_error_rate"], 1.0)
        finally:
            cfg.unlink()


class EvaluateWithConfigTests(TestCase):
    def test_alerts_use_config_overrides(self):
        cfg = _write_config({"max_failed_spans": 1})
        try:
            r = {
                "active": [], "stale": [],
                "failed_spans_total": 3,
                "tool_latency": {"by_tool": {}},
                "quality": {"by_agent": {}},
            }
            alerts = health.evaluate_alerts(r, config_path=cfg)
            self.assertTrue(any(
                a["code"] == "failed_spans" for a in alerts
            ))
        finally:
            cfg.unlink()


class CliShowThresholdsTests(TestCase):
    def test_show_thresholds_subcommand(self):
        with isolated_cache():
            r = subprocess.run(
                [sys.executable, "-m", "lib.health",
                 "--show-thresholds"],
                capture_output=True, text=True, cwd=str(_REPO),
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            payload = json.loads(r.stdout)
            self.assertIn("thresholds", payload)
            # v0.126: renamed to global_config_path
            self.assertIn("global_config_path", payload)
            self.assertIn("max_failed_spans",
                           payload["thresholds"])


if __name__ == "__main__":
    raise SystemExit(run_tests(
        LoadThresholdsTests, EvaluateWithConfigTests,
        CliShowThresholdsTests,
    ))
