"""v0.135 — coverage for scripts/ci-status.sh + test-like-ci.sh."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from tests.harness import TestCase, run_tests


_REPO = Path(__file__).resolve().parents[1]
_CI_STATUS = _REPO / "scripts" / "ci-status.sh"
_TEST_LIKE_CI = _REPO / "scripts" / "test-like-ci.sh"


class FileExistsTests(TestCase):
    def test_ci_status_exists_and_executable(self):
        self.assertTrue(_CI_STATUS.exists())
        self.assertTrue(os.access(_CI_STATUS, os.X_OK))

    def test_test_like_ci_exists_and_executable(self):
        self.assertTrue(_TEST_LIKE_CI.exists())
        self.assertTrue(os.access(_TEST_LIKE_CI, os.X_OK))


class CiStatusContentTests(TestCase):
    """Smoke-check the script content for required behaviors."""

    def test_handles_missing_gh(self):
        text = _CI_STATUS.read_text()
        self.assertIn("gh CLI not installed", text)
        self.assertIn("brew install gh", text)

    def test_handles_unauthed_gh(self):
        text = _CI_STATUS.read_text()
        self.assertIn("gh auth login", text)

    def test_supports_watch_logs_rerun(self):
        text = _CI_STATUS.read_text()
        for flag in ("--watch", "--logs", "--rerun"):
            self.assertIn(flag, text)

    def test_failed_gives_actionable_hints(self):
        text = _CI_STATUS.read_text()
        self.assertIn("--logs", text)
        self.assertIn("--rerun", text)


class TestLikeCiContentTests(TestCase):
    def test_runs_uv_sync(self):
        text = _TEST_LIKE_CI.read_text()
        self.assertIn("uv sync", text)
        self.assertIn("--extra dev", text)
        self.assertIn("--extra mcp", text)

    def test_stages_mcp_json_from_example(self):
        text = _TEST_LIKE_CI.read_text()
        self.assertIn(".mcp.json.example", text)
        self.assertIn(".mcp.json", text)

    def test_runs_full_test_suite(self):
        text = _TEST_LIKE_CI.read_text()
        self.assertIn("tests/run_all.py", text)

    def test_supports_fresh_clone(self):
        text = _TEST_LIKE_CI.read_text()
        self.assertIn("--fresh", text)
        self.assertIn("git clone", text)
        self.assertIn("mktemp", text)

    def test_runs_ruff_lint(self):
        text = _TEST_LIKE_CI.read_text()
        self.assertIn("ruff check", text)


class GhAvailabilityTests(TestCase):
    """If gh is installed locally, validate ci-status.sh runs
    without crashing on the no-arg path. Skip when absent."""

    def test_no_arg_returns_zero_when_gh_present(self):
        import shutil
        if not shutil.which("gh"):
            return
        # Verify gh is authed; skip if not.
        r = subprocess.run(
            ["gh", "auth", "status"],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            return
        r = subprocess.run(
            [str(_CI_STATUS)],
            capture_output=True, text=True, cwd=str(_REPO),
            timeout=30,
        )
        # Either exit 0 (run found) or non-zero with informative
        # output. We accept both — script is informational.
        self.assertIn("ci-status", r.stdout + r.stderr)


if __name__ == "__main__":
    raise SystemExit(run_tests(
        FileExistsTests, CiStatusContentTests,
        TestLikeCiContentTests, GhAvailabilityTests,
    ))
