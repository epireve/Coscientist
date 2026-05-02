"""v0.107 — health skill registration + runbook reference tests.

v0.207 — `test_wrapper_script_runs` now uses isolated_cache + passes
COSCIENTIST_CACHE_DIR to subprocess. Previously it inherited the real
~/.cache/coscientist where stale spans from dev work triggered v0.114
alert exit-codes (>0). Test was effectively env-dependent.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from tests.harness import TestCase, isolated_cache, run_tests

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
        # v0.207 — isolate from real cache so stale spans in dev cache
        # don't trigger v0.114 alert exit-codes during this assertion.
        with isolated_cache() as cache:
            env = os.environ.copy()
            env["COSCIENTIST_CACHE_DIR"] = str(cache)
            r = subprocess.run(
                [sys.executable, str(_SCRIPT), "--format", "json"],
                capture_output=True, text=True, cwd=str(_REPO), env=env,
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("n_runs", r.stdout)


class RunbookReferenceTests(TestCase):
    def test_runbook_mentions_health(self):
        text = _RUNBOOK.read_text()
        self.assertIn("lib.health", text)


if __name__ == "__main__":
    raise SystemExit(run_tests(HealthSkillTests, RunbookReferenceTests))
