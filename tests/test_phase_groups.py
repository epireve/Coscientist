"""v0.51 — phase-group concurrency tests."""

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

from tests import _shim  # noqa: F401
from tests.harness import TestCase, isolated_cache, run_tests

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from lib.phase_groups import batchable, group_for  # noqa: E402


class GroupForTests(TestCase):
    def test_phase1_personas_share_group(self):
        g = group_for("cartographer")
        self.assertIsNotNone(g)
        self.assertIn("chronicler", g)
        self.assertIn("surveyor", g)

    def test_sequential_phases_no_group(self):
        self.assertIsNone(group_for("scout"))
        self.assertIsNone(group_for("synthesist"))
        self.assertIsNone(group_for("steward"))


class BatchableTests(TestCase):
    def test_empty_input(self):
        self.assertEqual(batchable([]), [])

    def test_single_sequential_phase(self):
        self.assertEqual(batchable(["scout"]), ["scout"])

    def test_full_phase1_group(self):
        self.assertEqual(
            batchable(["cartographer", "chronicler", "surveyor",
                       "synthesist"]),
            ["cartographer", "chronicler", "surveyor"],
        )

    def test_partial_phase1_group(self):
        # Resume scenario: cartographer already done
        self.assertEqual(
            batchable(["chronicler", "surveyor", "synthesist"]),
            ["chronicler", "surveyor"],
        )

    def test_sequential_after_group(self):
        self.assertEqual(
            batchable(["synthesist", "architect"]),
            ["synthesist"],
        )

    def test_no_cross_group_merging(self):
        # Hypothetical: even if synthesist were grouped, the boundary
        # holds. Here we just verify no group leakage.
        self.assertEqual(batchable(["weaver", "visionary"]), ["weaver"])


class CmdNextPhaseBatchTests(TestCase):
    """End-to-end CLI test for db.py next-phase-batch."""

    def _cli(self, *args: str) -> tuple[int, str, str]:
        cli = (_ROOT / ".claude/skills/deep-research/scripts/db.py")
        r = subprocess.run(
            [sys.executable, str(cli), *args],
            capture_output=True, text=True,
        )
        return r.returncode, r.stdout, r.stderr

    def _init_run(self) -> str:
        rc, out, err = self._cli("init", "--question", "Q")
        self.assertEqual(rc, 0, err)
        return out.strip()

    def _connect(self, run_id: str) -> sqlite3.Connection:
        from lib.cache import run_db_path
        return sqlite3.connect(run_db_path(run_id))

    def _complete_phase(self, run_id: str, name: str) -> None:
        rc, _, err = self._cli(
            "record-phase", "--run-id", run_id, "--phase", name,
            "--start",
        )
        self.assertEqual(rc, 0, err)
        rc, _, err = self._cli(
            "record-phase", "--run-id", run_id, "--phase", name,
            "--complete",
        )
        self.assertEqual(rc, 0, err)

    def _resolve_break(self, run_id: str, n: int) -> None:
        # next-phase-batch emits {"action":"break"...}; resolve it
        rc, _, err = self._cli(
            "record-break", "--run-id", run_id, "--break-number", str(n),
            "--prompt",
        )
        self.assertEqual(rc, 0, err)
        rc, _, err = self._cli(
            "record-break", "--run-id", run_id, "--break-number", str(n),
            "--resolve", "--user-input", "ok",
        )
        self.assertEqual(rc, 0, err)

    def test_first_call_returns_scout(self):
        with isolated_cache():
            run_id = self._init_run()
            rc, out, _ = self._cli("next-phase-batch", "--run-id", run_id)
            self.assertEqual(rc, 0)
            d = json.loads(out)
            self.assertEqual(d, {"action": "run", "phases": ["scout"]})

    def test_break_after_scout(self):
        with isolated_cache():
            run_id = self._init_run()
            self._complete_phase(run_id, "scout")
            rc, out, _ = self._cli("next-phase-batch", "--run-id", run_id)
            d = json.loads(out)
            self.assertEqual(d, {"action": "break", "break_number": 0})

    def test_phase1_returns_full_batch(self):
        with isolated_cache():
            run_id = self._init_run()
            self._complete_phase(run_id, "scout")
            self._resolve_break(run_id, 0)
            rc, out, _ = self._cli("next-phase-batch", "--run-id", run_id)
            d = json.loads(out)
            self.assertEqual(d["action"], "run")
            self.assertEqual(
                d["phases"],
                ["cartographer", "chronicler", "surveyor"],
            )

    def test_phase1_partial_complete_returns_remainder(self):
        with isolated_cache():
            run_id = self._init_run()
            self._complete_phase(run_id, "scout")
            self._resolve_break(run_id, 0)
            self._complete_phase(run_id, "cartographer")
            rc, out, _ = self._cli("next-phase-batch", "--run-id", run_id)
            d = json.loads(out)
            self.assertEqual(
                d["phases"], ["chronicler", "surveyor"],
            )

    def test_phase1_complete_then_break_after_surveyor(self):
        with isolated_cache():
            run_id = self._init_run()
            self._complete_phase(run_id, "scout")
            self._resolve_break(run_id, 0)
            for p in ("cartographer", "chronicler", "surveyor"):
                self._complete_phase(run_id, p)
            rc, out, _ = self._cli("next-phase-batch", "--run-id", run_id)
            d = json.loads(out)
            self.assertEqual(d, {"action": "break", "break_number": 1})

    def test_synthesist_alone_after_break1(self):
        with isolated_cache():
            run_id = self._init_run()
            self._complete_phase(run_id, "scout")
            self._resolve_break(run_id, 0)
            for p in ("cartographer", "chronicler", "surveyor"):
                self._complete_phase(run_id, p)
            self._resolve_break(run_id, 1)
            rc, out, _ = self._cli("next-phase-batch", "--run-id", run_id)
            d = json.loads(out)
            self.assertEqual(d, {"action": "run", "phases": ["synthesist"]})

    def test_done_when_all_complete(self):
        with isolated_cache():
            run_id = self._init_run()
            phases = [
                "scout", "cartographer", "chronicler", "surveyor",
                "synthesist", "architect", "inquisitor", "weaver",
                "visionary", "steward",
            ]
            for i, p in enumerate(phases):
                self._complete_phase(run_id, p)
                # Resolve breaks where they fall
                if p == "scout":
                    self._resolve_break(run_id, 0)
                elif p == "surveyor":
                    self._resolve_break(run_id, 1)
                elif p == "weaver":
                    self._resolve_break(run_id, 2)
            rc, out, _ = self._cli("next-phase-batch", "--run-id", run_id)
            d = json.loads(out)
            self.assertEqual(d, {"action": "done"})

    def test_error_short_circuits(self):
        with isolated_cache():
            run_id = self._init_run()
            self._complete_phase(run_id, "scout")
            self._resolve_break(run_id, 0)
            # Mark cartographer errored
            rc, _, err = self._cli(
                "record-phase", "--run-id", run_id,
                "--phase", "cartographer", "--error", "boom",
            )
            self.assertEqual(rc, 0, err)
            rc, out, _ = self._cli("next-phase-batch", "--run-id", run_id)
            d = json.loads(out)
            self.assertEqual(d["action"], "error")
            self.assertEqual(d["phase"], "cartographer")
            self.assertEqual(d["error"], "boom")


if __name__ == "__main__":
    sys.exit(run_tests(
        GroupForTests, BatchableTests, CmdNextPhaseBatchTests,
    ))
