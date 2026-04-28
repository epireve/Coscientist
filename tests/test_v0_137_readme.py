"""v0.137 — README freshness regression tests."""
from __future__ import annotations

from pathlib import Path

from tests.harness import TestCase, run_tests


_REPO = Path(__file__).resolve().parents[1]
_README = _REPO / "README.md"


class WhatItDoesTests(TestCase):
    def test_mentions_observability(self):
        text = _README.read_text()
        self.assertIn("Observability", text)
        self.assertIn("v0.89", text)

    def test_mentions_tournament_integration(self):
        text = _README.read_text()
        self.assertIn("Tournament", text)
        self.assertIn("v0.123", text)

    def test_mentions_critical_judgment(self):
        text = _README.read_text()
        self.assertIn("Critical judgment", text)
        self.assertIn("debate", text.lower())

    def test_lists_subsystems_beyond_pipeline(self):
        text = _README.read_text()
        # full-lifecycle subsystems must be referenced
        for marker in ("Manuscripts", "Experiments", "Datasets",
                        "Wide Research"):
            self.assertIn(marker, text)


class QuickStartTests(TestCase):
    def test_quick_start_section_exists(self):
        text = _README.read_text()
        self.assertIn("## Quick start", text)

    def test_quick_start_covers_clone_install_configure(self):
        text = _README.read_text()
        for marker in ("git clone", "uv sync", ".mcp.json.example",
                        "install_hooks.sh", "tests/run_all.py",
                        "lib.health"):
            self.assertIn(marker, text, f"missing: {marker}")


class RecentLandingsTests(TestCase):
    def test_covers_v0_120_through_v0_134(self):
        text = _README.read_text()
        for v in ("v0.120", "v0.124", "v0.127", "v0.128",
                   "v0.130", "v0.134"):
            self.assertIn(v, text, f"missing {v}")

    def test_observability_section_lists_health_command(self):
        text = _README.read_text()
        self.assertIn("## Observability + diagnostics", text)
        self.assertIn("lib.health", text)
        self.assertIn("trace_render", text)
        self.assertIn("ci-status.sh", text)


class ReferenceIntegrityTests(TestCase):
    def test_runbook_referenced(self):
        text = _README.read_text()
        self.assertIn("SMOKE-TEST-RUNBOOK", text)

    def test_changelog_referenced(self):
        text = _README.read_text()
        self.assertIn("CHANGELOG.md", text)


if __name__ == "__main__":
    raise SystemExit(run_tests(
        WhatItDoesTests, QuickStartTests, RecentLandingsTests,
        ReferenceIntegrityTests,
    ))
