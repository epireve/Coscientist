"""Tests for overnight mode (v0.28).

Drives both db.py (--overnight flag, is_overnight helper) and
overnight.py (queue-break, digest, status subcommands) without invoking
any sub-agent or MCP.

Classes
-------
OvernightInitTests   (4 tests) — db.py --overnight flag, is_overnight helper
QueueBreakTests      (4 tests) — queue-break subcommand behaviour
DigestTests          (5 tests) — digest.md generation + status subcommand
CliEdgeTests         (4 tests) — missing-arg + --help edge cases

Total: 17 tests.
"""

import sqlite3
import subprocess
import sys
from pathlib import Path

from tests import _shim  # noqa: F401
from tests.harness import TestCase, isolated_cache, run_tests

_ROOT = Path(__file__).resolve().parent.parent
DB = _ROOT / ".claude/skills/deep-research/scripts/db.py"
OVERNIGHT = _ROOT / ".claude/skills/deep-research/scripts/overnight.py"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_db(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(DB), *args],
        capture_output=True, text=True,
    )


def _run_overnight(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(OVERNIGHT), *args],
        capture_output=True, text=True,
    )


def _init(question: str = "Test question", overnight: bool = False) -> str:
    args = ["init", "--question", question]
    if overnight:
        args.append("--overnight")
    r = _run_db(*args)
    assert r.returncode == 0, f"db.py init failed: {r.stderr}"
    return r.stdout.strip()


def _run_db_path(cache_dir: Path, run_id: str) -> Path:
    return cache_dir / "runs" / f"run-{run_id}.db"


# ---------------------------------------------------------------------------
# OvernightInitTests
# ---------------------------------------------------------------------------

class OvernightInitTests(TestCase):
    def test_overnight_flag_stored_in_db(self):
        """--overnight stores overnight=1 in the runs table."""
        with isolated_cache() as cache_dir:
            run_id = _init(overnight=True)
            con = sqlite3.connect(_run_db_path(cache_dir, run_id))
            row = con.execute(
                "SELECT overnight FROM runs WHERE run_id=?", (run_id,)
            ).fetchone()
            con.close()
            self.assertEqual(row[0], 1)

    def test_default_run_is_not_overnight(self):
        """A run created without --overnight has overnight=0."""
        with isolated_cache() as cache_dir:
            run_id = _init(overnight=False)
            con = sqlite3.connect(_run_db_path(cache_dir, run_id))
            row = con.execute(
                "SELECT overnight FROM runs WHERE run_id=?", (run_id,)
            ).fetchone()
            con.close()
            self.assertEqual(row[0], 0)

    def test_is_overnight_helper_returns_correct_bool(self):
        """is_overnight() returns True for overnight runs, False otherwise."""
        with isolated_cache() as cache_dir:
            on_id = _init(overnight=True)
            off_id = _init(overnight=False)

            on_db = _run_db_path(cache_dir, on_id)
            off_db = _run_db_path(cache_dir, off_id)

            con_on = sqlite3.connect(on_db)
            con_on.row_factory = sqlite3.Row
            con_off = sqlite3.connect(off_db)
            con_off.row_factory = sqlite3.Row

            import importlib.util as ilu
            spec = ilu.spec_from_file_location("db_overnight_test", DB)
            db_mod = ilu.module_from_spec(spec)
            spec.loader.exec_module(db_mod)

            self.assertTrue(db_mod.is_overnight(con_on, on_id))
            self.assertFalse(db_mod.is_overnight(con_off, off_id))
            con_on.close()
            con_off.close()

    def test_run_id_is_returned(self):
        """db.py init --overnight still prints a valid 8-char hex run_id."""
        with isolated_cache():
            run_id = _init(overnight=True)
            self.assertTrue(len(run_id) == 8,
                            f"expected 8-char run_id, got {run_id!r}")


# ---------------------------------------------------------------------------
# QueueBreakTests
# ---------------------------------------------------------------------------

class QueueBreakTests(TestCase):
    def test_queue_break_writes_resolved_at(self):
        """queue-break sets resolved_at on the break row."""
        with isolated_cache() as cache_dir:
            run_id = _init(overnight=True)
            r = _run_overnight("queue-break", "--run-id", run_id, "--break-number", "0")
            self.assertEqual(r.returncode, 0, f"queue-break failed: {r.stderr}")
            con = sqlite3.connect(_run_db_path(cache_dir, run_id))
            row = con.execute(
                "SELECT resolved_at FROM breaks WHERE run_id=? AND break_number=0",
                (run_id,)
            ).fetchone()
            con.close()
            self.assertTrue(row is not None, "break row should exist after queue-break")
            self.assertTrue(row[0] is not None, "resolved_at should be set")

    def test_queue_break_sets_overnight_placeholder_text(self):
        """queue-break stores the overnight placeholder string in user_input."""
        with isolated_cache() as cache_dir:
            run_id = _init(overnight=True)
            _run_overnight("queue-break", "--run-id", run_id, "--break-number", "1")
            con = sqlite3.connect(_run_db_path(cache_dir, run_id))
            row = con.execute(
                "SELECT user_input FROM breaks WHERE run_id=? AND break_number=1",
                (run_id,)
            ).fetchone()
            con.close()
            self.assertIn("overnight", row[0].lower())

    def test_queuing_break_0_allows_queuing_break_1(self):
        """queue-break can be called for each break independently."""
        with isolated_cache() as cache_dir:
            run_id = _init(overnight=True)
            r0 = _run_overnight("queue-break", "--run-id", run_id, "--break-number", "0")
            r1 = _run_overnight("queue-break", "--run-id", run_id, "--break-number", "1")
            self.assertEqual(r0.returncode, 0, f"queue-break 0 failed: {r0.stderr}")
            self.assertEqual(r1.returncode, 0, f"queue-break 1 failed: {r1.stderr}")
            con = sqlite3.connect(_run_db_path(cache_dir, run_id))
            count = con.execute(
                "SELECT COUNT(*) FROM breaks WHERE run_id=? AND resolved_at IS NOT NULL",
                (run_id,)
            ).fetchone()[0]
            con.close()
            self.assertEqual(count, 2)

    def test_queuing_same_break_twice_errors(self):
        """Calling queue-break on an already-resolved break should fail."""
        with isolated_cache():
            run_id = _init(overnight=True)
            _run_overnight("queue-break", "--run-id", run_id, "--break-number", "0")
            r = _run_overnight("queue-break", "--run-id", run_id, "--break-number", "0")
            self.assertTrue(r.returncode != 0,
                            "second queue-break on resolved break should error")


# ---------------------------------------------------------------------------
# DigestTests
# ---------------------------------------------------------------------------

class DigestTests(TestCase):
    def test_digest_md_is_created(self):
        """digest subcommand creates digest.md in the run directory."""
        with isolated_cache() as cache_dir:
            run_id = _init(overnight=True)
            _run_overnight("queue-break", "--run-id", run_id, "--break-number", "0")
            r = _run_overnight("digest", "--run-id", run_id)
            self.assertEqual(r.returncode, 0, f"digest failed: {r.stderr}")
            digest_path = Path(r.stdout.strip())
            self.assertTrue(digest_path.exists(), "digest.md should exist on disk")

    def test_digest_contains_overnight(self):
        """digest.md mentions overnight mode."""
        with isolated_cache():
            run_id = _init(overnight=True)
            r = _run_overnight("digest", "--run-id", run_id)
            self.assertEqual(r.returncode, 0, f"digest failed: {r.stderr}")
            content = Path(r.stdout.strip()).read_text()
            self.assertIn("overnight", content.lower())

    def test_digest_contains_break_prompt_text(self):
        """digest.md includes the standard break prompt text for queued breaks."""
        with isolated_cache():
            run_id = _init(overnight=True)
            _run_overnight("queue-break", "--run-id", run_id, "--break-number", "0")
            r = _run_overnight("digest", "--run-id", run_id)
            self.assertEqual(r.returncode, 0, f"digest failed: {r.stderr}")
            content = Path(r.stdout.strip()).read_text()
            # The standard break-0 prompt references "source pool" or "Social"
            self.assertTrue(
                "source pool" in content.lower() or "break 0" in content.lower(),
                "digest should mention break 0 or source pool"
            )

    def test_digest_is_idempotent(self):
        """Calling digest twice overwrites without error."""
        with isolated_cache():
            run_id = _init(overnight=True)
            r1 = _run_overnight("digest", "--run-id", run_id)
            r2 = _run_overnight("digest", "--run-id", run_id)
            self.assertEqual(r1.returncode, 0, f"first digest failed: {r1.stderr}")
            self.assertEqual(r2.returncode, 0, f"second digest failed: {r2.stderr}")
            # Both calls should return the same path
            self.assertEqual(r1.stdout.strip(), r2.stdout.strip())

    def test_status_subcommand_lists_queued_breaks(self):
        """status output mentions queued breaks after queue-break is called."""
        with isolated_cache():
            run_id = _init(overnight=True)
            _run_overnight("queue-break", "--run-id", run_id, "--break-number", "0")
            r = _run_overnight("status", "--run-id", run_id)
            self.assertEqual(r.returncode, 0, f"status failed: {r.stderr}")
            out = r.stdout
            self.assertIn("queued", out.lower())


# ---------------------------------------------------------------------------
# CliEdgeTests
# ---------------------------------------------------------------------------

class CliEdgeTests(TestCase):
    def test_queue_break_missing_run_id_errors(self):
        """queue-break without --run-id should fail with non-zero exit."""
        with isolated_cache():
            r = _run_overnight("queue-break", "--break-number", "0")
            self.assertTrue(r.returncode != 0,
                            "missing --run-id should produce an error exit")

    def test_queue_break_missing_break_number_errors(self):
        """queue-break without --break-number should fail with non-zero exit."""
        with isolated_cache():
            run_id = _init(overnight=True)
            r = _run_overnight("queue-break", "--run-id", run_id)
            self.assertTrue(r.returncode != 0,
                            "missing --break-number should produce an error exit")

    def test_digest_missing_run_id_errors(self):
        """digest without --run-id should fail with non-zero exit."""
        with isolated_cache():
            r = _run_overnight("digest")
            self.assertTrue(r.returncode != 0,
                            "missing --run-id should produce an error exit")

    def test_help_lists_subcommands(self):
        """--help output should mention the three subcommands."""
        r = _run_overnight("--help")
        # argparse exits 0 for --help
        out = r.stdout + r.stderr
        self.assertIn("queue-break", out)
        self.assertIn("digest", out)
        self.assertIn("status", out)


if __name__ == "__main__":
    sys.exit(run_tests(
        OvernightInitTests,
        QueueBreakTests,
        DigestTests,
        CliEdgeTests,
    ))
