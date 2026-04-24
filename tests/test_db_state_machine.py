"""Deep-research db.py state machine tests."""

from tests import _shim  # noqa: F401

import subprocess
import sys
from pathlib import Path

from tests.harness import TestCase, isolated_cache, run_tests

DB = Path(__file__).resolve().parent.parent / ".claude/skills/deep-research/scripts/db.py"


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(DB), *args], capture_output=True, text=True)


class DbTests(TestCase):
    def test_init_returns_run_id(self):
        with isolated_cache():
            r = _run("init", "--question", "Test q")
            self.assertEqual(r.returncode, 0, f"stderr={r.stderr}")
            rid = r.stdout.strip()
            self.assertTrue(len(rid) >= 4)

    def test_next_phase_sequence(self):
        with isolated_cache():
            rid = _run("init", "--question", "Q").stdout.strip()

            # Initial: next phase is social
            r = _run("next-phase", "--run-id", rid)
            self.assertEqual(r.stdout.strip(), "social")

            # Start + complete social
            _run("record-phase", "--run-id", rid, "--phase", "social", "--start")
            _run("record-phase", "--run-id", rid, "--phase", "social", "--complete")

            # Should be BREAK_0
            r = _run("next-phase", "--run-id", rid)
            self.assertEqual(r.stdout.strip(), "BREAK_0")

            # Prompt + resolve the break
            _run("record-break", "--run-id", rid, "--break-number", "0", "--prompt")
            _run("record-break", "--run-id", rid, "--break-number", "0", "--resolve", "--user-input", "ok")

            # Now grounder
            r = _run("next-phase", "--run-id", rid)
            self.assertEqual(r.stdout.strip(), "grounder")

    def test_resume_round_trip(self):
        with isolated_cache():
            rid = _run("init", "--question", "Q").stdout.strip()
            r = _run("resume", "--run-id", rid)
            self.assertEqual(r.returncode, 0)
            self.assertIn("social", r.stdout)
            self.assertIn("scribe", r.stdout)

    def test_full_pipeline_reaches_done(self):
        with isolated_cache():
            rid = _run("init", "--question", "Q").stdout.strip()
            phases = ["social", "grounder", "historian", "gaper",
                      "vision", "theorist", "rude", "synthesizer",
                      "thinker", "scribe"]
            breaks_expected = {"social": 0, "gaper": 1, "synthesizer": 2}
            for p in phases:
                _run("record-phase", "--run-id", rid, "--phase", p, "--start")
                _run("record-phase", "--run-id", rid, "--phase", p, "--complete")
                if p in breaks_expected:
                    bn = breaks_expected[p]
                    _run("record-break", "--run-id", rid, "--break-number", str(bn), "--prompt")
                    _run("record-break", "--run-id", rid, "--break-number", str(bn), "--resolve", "--user-input", "ok")
            r = _run("next-phase", "--run-id", rid)
            self.assertEqual(r.stdout.strip(), "DONE")


if __name__ == "__main__":
    sys.exit(run_tests(DbTests))
