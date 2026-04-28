"""v0.140 — run_all.py warns about missing pre-commit hook."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from tests.harness import TestCase, run_tests


_REPO = Path(__file__).resolve().parents[1]
_RUN_ALL = _REPO / "tests" / "run_all.py"


class HookWarningTests(TestCase):
    def test_run_all_no_warn_when_hook_installed(self):
        """When hook is correctly installed (current state),
        run_all.py should NOT print the pre-commit warning."""
        hook = _REPO / ".git" / "hooks" / "pre-commit"
        if not hook.is_symlink():
            return  # nothing to assert
        # Run a minimal check via importing run_all module-level
        # functions.
        from tests import run_all as runner
        # Capture stdout-equivalent
        import io
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            runner._maybe_warn_pre_commit_hook()
        out = buf.getvalue()
        self.assertNotIn("[pre-commit]", out)

    def test_run_all_warns_when_hook_missing(self):
        """Temporarily remove hook, verify warning appears."""
        from tests import run_all as runner
        hook = _REPO / ".git" / "hooks" / "pre-commit"
        if not hook.is_symlink():
            return
        target = os.readlink(hook)
        hook.unlink()
        try:
            import io
            import contextlib
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                runner._maybe_warn_pre_commit_hook()
            out = buf.getvalue()
            self.assertIn("[pre-commit]", out)
            self.assertIn("install_hooks.sh", out)
        finally:
            os.symlink(target, hook)


class IntegrationTests(TestCase):
    """Spawn run_all.py and verify it doesn't crash."""

    def test_run_all_imports_and_warn_works(self):
        # Quick smoke — import run_all + call helper. Don't run
        # full suite (too slow for inner test).
        r = subprocess.run(
            [sys.executable, "-c",
             "from tests import run_all; "
             "run_all._maybe_warn_pre_commit_hook(); print('ok')"],
            capture_output=True, text=True, cwd=str(_REPO),
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("ok", r.stdout)


if __name__ == "__main__":
    raise SystemExit(run_tests(HookWarningTests, IntegrationTests))
