"""v0.101 — smoke-test runbook regression tests."""
from __future__ import annotations

from pathlib import Path

from tests.harness import TestCase, run_tests


_REPO = Path(__file__).resolve().parents[1]
_RUNBOOK = _REPO / "docs" / "SMOKE-TEST-RUNBOOK.md"


class RunbookTests(TestCase):
    def test_runbook_exists(self):
        self.assertTrue(
            _RUNBOOK.exists(),
            f"missing {_RUNBOOK}",
        )

    def test_runbook_has_required_sections(self):
        text = _RUNBOOK.read_text()
        required = [
            "## Step 1 — Start a run",
            "## Step 2 — Watch traces in real time",
            "## Step 3 — Render a full timeline",
            "## Step 4 — Find stale / hung spans",
            "## Step 5 — Inspect tool-call latency",
            "## Step 6 — Per-agent quality scores",
            "## Step 8 — Resume a paused run",
            "## Common failure patterns",
        ]
        for section in required:
            self.assertIn(section, text,
                           f"missing section: {section}")

    def test_runbook_references_key_modules(self):
        text = _RUNBOOK.read_text()
        for mod in ("lib.trace_status", "lib.trace_render",
                    "lib.agent_quality"):
            self.assertIn(mod, text, f"runbook never mentions {mod}")

    def test_runbook_mentions_each_cli_flag(self):
        text = _RUNBOOK.read_text()
        for flag in ("--stale-only", "--mark-error",
                     "--tool-latency", "--run-id", "--format"):
            self.assertIn(flag, text, f"runbook missing {flag}")


if __name__ == "__main__":
    raise SystemExit(run_tests(RunbookTests))
