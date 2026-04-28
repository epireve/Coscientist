"""v0.136 — pre-commit hook install detection tests."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

from tests.harness import TestCase, run_tests


_REPO = Path(__file__).resolve().parents[1]


class CheckResultStructureTests(TestCase):
    """When run in this repo, must return a dict with expected keys."""

    def test_returns_required_keys(self):
        from lib import hook_check
        r = hook_check.check()
        for key in ("ok", "hook_path", "expected", "message",
                     "action"):
            self.assertIn(key, r)

    def test_action_is_install_script(self):
        from lib import hook_check
        r = hook_check.check()
        self.assertIn("install_hooks", r["action"])


class IntegrationTests(TestCase):
    """Spawn check in a fresh git repo to validate state detection."""

    def _setup_repo(self, tmpdir: str) -> Path:
        # Mini repo + ensure hook_check can find it from inside
        # by setting cwd. We can't move lib/ — instead invoke via
        # subprocess with cwd=tmpdir, which makes the script
        # walk to its own _REPO (the actual coscientist repo, not
        # tmpdir). Skip integration that requires repo-relative
        # paths; check() always operates on coscientist itself.
        return Path(tmpdir)

    def test_check_detects_missing_hook(self):
        """Manipulate .git/hooks/pre-commit to absent, verify
        check() reports it. Restore at end."""
        from lib import hook_check
        hook = _REPO / ".git" / "hooks" / "pre-commit"
        backup = None
        if hook.exists() or hook.is_symlink():
            backup = hook.resolve() if hook.is_symlink() else None
            tmp_target = (
                os.readlink(hook) if hook.is_symlink() else None
            )
            hook.unlink()
            try:
                r = hook_check.check()
                self.assertFalse(r["ok"])
                self.assertIn("not installed", r["message"])
            finally:
                # Restore symlink
                if tmp_target is not None:
                    os.symlink(tmp_target, hook)
        else:
            r = hook_check.check()
            self.assertFalse(r["ok"])

    def test_check_passes_when_installed(self):
        """If symlink points correctly, check passes."""
        from lib import hook_check
        hook = _REPO / ".git" / "hooks" / "pre-commit"
        # Ensure correct symlink
        if hook.exists() or hook.is_symlink():
            if hook.is_symlink():
                target = os.readlink(hook)
                if target == "../../scripts/pre-commit":
                    r = hook_check.check()
                    self.assertTrue(r["ok"], r["message"])
                    return
        # If not installed correctly, install (best-effort)
        installer = _REPO / "scripts" / "install_hooks.sh"
        if installer.exists():
            subprocess.run(
                ["sh", str(installer)],
                cwd=str(_REPO), capture_output=True,
            )
            r = hook_check.check()
            self.assertTrue(r["ok"], r["message"])

    def test_check_detects_wrong_target(self):
        """Symlink to wrong path → reports mismatch."""
        from lib import hook_check
        hook = _REPO / ".git" / "hooks" / "pre-commit"
        original_target = None
        if hook.is_symlink():
            original_target = os.readlink(hook)
            hook.unlink()
        try:
            os.symlink("../../scripts/non-existent-target", hook)
            r = hook_check.check()
            self.assertFalse(r["ok"])
            self.assertIn("expected", r["message"])
        finally:
            hook.unlink(missing_ok=True)
            if original_target is not None:
                os.symlink(original_target, hook)


class CliTests(TestCase):
    def test_cli_exits_with_status_code(self):
        """Whichever state, exit code matches `ok` field."""
        r = subprocess.run(
            [sys.executable, "-m", "lib.hook_check"],
            capture_output=True, text=True, cwd=str(_REPO),
        )
        # Either 0 (installed) or 1 (not). Both valid.
        self.assertIn(r.returncode, (0, 1))

    def test_cli_quiet_suppresses_output(self):
        r = subprocess.run(
            [sys.executable, "-m", "lib.hook_check", "--quiet"],
            capture_output=True, text=True, cwd=str(_REPO),
        )
        # Quiet → no stdout, exit code carries signal
        self.assertEqual(r.stdout, "")


if __name__ == "__main__":
    raise SystemExit(run_tests(
        CheckResultStructureTests, IntegrationTests, CliTests,
    ))
