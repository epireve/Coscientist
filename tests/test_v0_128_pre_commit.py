"""v0.128 — pre-commit hook installer + script tests."""
from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

from tests.harness import TestCase, run_tests

_REPO = Path(__file__).resolve().parents[1]
_HOOK = _REPO / "scripts" / "pre-commit"
_INSTALLER = _REPO / "scripts" / "install_hooks.sh"


class HookFilesTests(TestCase):
    def test_pre_commit_exists(self):
        self.assertTrue(_HOOK.exists())

    def test_pre_commit_executable(self):
        self.assertTrue(os.access(_HOOK, os.X_OK))

    def test_installer_exists(self):
        self.assertTrue(_INSTALLER.exists())

    def test_installer_executable(self):
        self.assertTrue(os.access(_INSTALLER, os.X_OK))

    def test_pre_commit_handles_no_changes(self):
        text = _HOOK.read_text()
        self.assertIn("regen_count", text)
        self.assertIn("no generated artifacts need refresh", text)

    def test_pre_commit_detects_plugin_changes(self):
        text = _HOOK.read_text()
        self.assertIn("plugin_checksums", text)

    def test_pre_commit_detects_skill_changes(self):
        text = _HOOK.read_text()
        self.assertIn("skill_index", text)

    def test_pre_commit_detects_roadmap_changes(self):
        text = _HOOK.read_text()
        self.assertIn("CHANGELOG.md", text)
        self.assertIn("lib.changelog", text)

    def test_bypass_documented(self):
        text = _HOOK.read_text()
        self.assertIn("--no-verify", text)


class HookExecutionTests(TestCase):
    """Run the hook against a temp git repo to verify it works."""

    def test_hook_runs_clean_when_no_changes_match(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            r = subprocess.run(
                ["git", "init", "-q", tmpdir],
                capture_output=True, text=True,
            )
            self.assertEqual(r.returncode, 0)
            # Configure
            subprocess.run(
                ["git", "config", "user.email", "test@x.com"],
                cwd=tmpdir, check=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "test"],
                cwd=tmpdir, check=True,
            )
            # Add unrelated file
            (Path(tmpdir) / "README.md").write_text("hi")
            subprocess.run(
                ["git", "add", "README.md"],
                cwd=tmpdir, check=True,
            )
            # Run hook directly (not via git, so nothing executes
            # uv — just verify exit 0 path).
            env = dict(os.environ)
            r = subprocess.run(
                ["sh", str(_HOOK)],
                cwd=tmpdir, capture_output=True, text=True, env=env,
            )
            # Should exit 0 (no matched changes)
            self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    raise SystemExit(run_tests(HookFilesTests, HookExecutionTests))
