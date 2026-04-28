"""v0.107 — health skill registration + runbook reference tests."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from tests.harness import TestCase, run_tests


_REPO = Path(__file__).resolve().parents[1]
_SKILL = _REPO / ".claude" / "skills" / "health" / "SKILL.md"
_SCRIPT = _REPO / ".claude" / "skills" / "health" / "scripts" / "health.py"
_RUNBOOK = _REPO / "docs" / "SMOKE-TEST-RUNBOOK.md"


class HealthSkillTests(TestCase):
    def test_skill_md_exists(self):
        self.assertTrue(_SKILL.exists())

    def test_skill_has_required_frontmatter(self):
        text = _SKILL.read_text()
        self.assertIn("name: health", text)
        self.assertIn("when_to_use:", text)
        self.assertIn("description:", text)

    def test_skill_mentions_lib_health(self):
        text = _SKILL.read_text()
        self.assertIn("lib.health", text)
        self.assertIn("--max-age", text)

    def test_wrapper_script_exists(self):
        self.assertTrue(_SCRIPT.exists())

    def test_wrapper_script_runs(self):
        r = subprocess.run(
            [sys.executable, str(_SCRIPT), "--format", "json"],
            capture_output=True, text=True, cwd=str(_REPO),
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("n_runs", r.stdout)


class RunbookReferenceTests(TestCase):
    def test_runbook_mentions_health(self):
        text = _RUNBOOK.read_text()
        self.assertIn("lib.health", text)


if __name__ == "__main__":
    raise SystemExit(run_tests(HealthSkillTests, RunbookReferenceTests))
