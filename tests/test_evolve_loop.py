"""v0.38 tournament evolve-loop tests."""

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

from tests import _shim  # noqa: F401
from tests.harness import TestCase, isolated_cache, run_tests

_ROOT = Path(__file__).resolve().parent.parent
SCHEMA = (_ROOT / "lib" / "sqlite_schema.sql").read_text()

REC_HYP = _ROOT / ".claude/skills/tournament/scripts/record_hypothesis.py"
EVOLVE = _ROOT / ".claude/skills/tournament/scripts/evolve_loop.py"


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, *args], capture_output=True, text=True)


def _seed_run(cache_dir: Path, run_id: str = "evo_run") -> str:
    d = cache_dir / "runs"
    d.mkdir(parents=True, exist_ok=True)
    db = d / f"run-{run_id}.db"
    con = sqlite3.connect(db)
    con.executescript(SCHEMA)
    con.execute(
        "INSERT INTO runs (run_id, question, started_at) VALUES (?, ?, ?)",
        (run_id, "test q", "2026-04-27T00:00:00Z"),
    )
    con.commit()
    con.close()
    return run_id


def _add_hyp(run_id: str, hyp_id: str, parent: str | None = None) -> None:
    cmd = [
        str(REC_HYP), "--run-id", run_id, "--agent-name", "theorist",
        "--hyp-id", hyp_id, "--statement", f"stmt for {hyp_id}",
        "--falsifiers", '["fals"]',
    ]
    if parent:
        cmd += ["--parent-hyp-id", parent]
    r = _run(*cmd)
    assert r.returncode == 0, r.stderr


def _set_elo(cache_dir: Path, run_id: str, hyp_id: str, elo: float) -> None:
    db = cache_dir / "runs" / f"run-{run_id}.db"
    con = sqlite3.connect(db)
    con.execute("UPDATE hypotheses SET elo=? WHERE hyp_id=?", (elo, hyp_id))
    con.commit()
    con.close()


class OpenRoundTests(TestCase):
    def test_open_round_records_initial_top(self):
        with isolated_cache() as cache:
            run_id = _seed_run(cache)
            _add_hyp(run_id, "hyp-a")
            _add_hyp(run_id, "hyp-b")
            _set_elo(cache, run_id, "hyp-a", 1300)
            _set_elo(cache, run_id, "hyp-b", 1100)

            r = _run(str(EVOLVE), "open-round", "--run-id", run_id)
            self.assertEqual(r.returncode, 0, r.stderr)
            out = json.loads(r.stdout)
            self.assertEqual(out["round_index"], 0)
            self.assertEqual(out["top_hyp_id"], "hyp-a")
            self.assertEqual(out["n_hypotheses"], 2)

    def test_open_round_rejects_when_round_open(self):
        with isolated_cache() as cache:
            run_id = _seed_run(cache)
            _add_hyp(run_id, "hyp-a")
            r1 = _run(str(EVOLVE), "open-round", "--run-id", run_id)
            self.assertEqual(r1.returncode, 0)
            r2 = _run(str(EVOLVE), "open-round", "--run-id", run_id)
            self.assertFalse(r2.returncode == 0)
            self.assertIn("still open", r2.stderr)

    def test_open_round_requires_hypotheses(self):
        with isolated_cache() as cache:
            run_id = _seed_run(cache)
            r = _run(str(EVOLVE), "open-round", "--run-id", run_id)
            self.assertFalse(r.returncode == 0)


class CloseRoundTests(TestCase):
    def test_close_round_no_change_increments_plateau(self):
        with isolated_cache() as cache:
            run_id = _seed_run(cache)
            _add_hyp(run_id, "hyp-a")
            _add_hyp(run_id, "hyp-b")
            _set_elo(cache, run_id, "hyp-a", 1300)

            # round 0 — top opens as hyp-a, closes as hyp-a → plateau=1
            _run(str(EVOLVE), "open-round", "--run-id", run_id)
            r = _run(str(EVOLVE), "close-round", "--run-id", run_id,
                     "--plateau-threshold", "3")
            out = json.loads(r.stdout)
            self.assertEqual(out["plateau_count"], 1)
            self.assertFalse(out["top_changed"])

            # round 1 — top still hyp-a
            _run(str(EVOLVE), "open-round", "--run-id", run_id)
            r = _run(str(EVOLVE), "close-round", "--run-id", run_id,
                     "--plateau-threshold", "3")
            out = json.loads(r.stdout)
            self.assertEqual(out["plateau_count"], 2)
            self.assertFalse(out["should_stop"])

            # round 2 — still hyp-a → plateau=3 hits threshold
            _run(str(EVOLVE), "open-round", "--run-id", run_id)
            r = _run(str(EVOLVE), "close-round", "--run-id", run_id,
                     "--plateau-threshold", "3")
            out = json.loads(r.stdout)
            self.assertEqual(out["plateau_count"], 3)
            self.assertTrue(out["should_stop"])

    def test_close_round_top_change_resets_plateau(self):
        with isolated_cache() as cache:
            run_id = _seed_run(cache)
            _add_hyp(run_id, "hyp-a")
            _add_hyp(run_id, "hyp-b")
            _set_elo(cache, run_id, "hyp-a", 1300)
            _set_elo(cache, run_id, "hyp-b", 1100)

            _run(str(EVOLVE), "open-round", "--run-id", run_id)
            _run(str(EVOLVE), "close-round", "--run-id", run_id)
            _run(str(EVOLVE), "open-round", "--run-id", run_id)
            r = _run(str(EVOLVE), "close-round", "--run-id", run_id)
            self.assertEqual(json.loads(r.stdout)["plateau_count"], 2)

            # Open next round (top still hyp-a), then flip elo before close
            _run(str(EVOLVE), "open-round", "--run-id", run_id)
            _set_elo(cache, run_id, "hyp-b", 1500)
            r = _run(str(EVOLVE), "close-round", "--run-id", run_id)
            out = json.loads(r.stdout)
            self.assertTrue(out["top_changed"])
            self.assertEqual(out["plateau_count"], 0)
            self.assertEqual(out["top_hyp_id"], "hyp-b")

    def test_close_round_counts_new_children(self):
        with isolated_cache() as cache:
            run_id = _seed_run(cache)
            _add_hyp(run_id, "hyp-a")
            _run(str(EVOLVE), "open-round", "--run-id", run_id)
            # Add child after round opens
            _add_hyp(run_id, "hyp-a-child", parent="hyp-a")
            r = _run(str(EVOLVE), "close-round", "--run-id", run_id)
            out = json.loads(r.stdout)
            self.assertEqual(out["n_new_children"], 1)

    def test_close_round_rejects_when_no_round_open(self):
        with isolated_cache() as cache:
            run_id = _seed_run(cache)
            _add_hyp(run_id, "hyp-a")
            r = _run(str(EVOLVE), "close-round", "--run-id", run_id)
            self.assertFalse(r.returncode == 0)


class StatusTests(TestCase):
    def test_status_lists_all_rounds(self):
        with isolated_cache() as cache:
            run_id = _seed_run(cache)
            _add_hyp(run_id, "hyp-a")
            _run(str(EVOLVE), "open-round", "--run-id", run_id)
            _run(str(EVOLVE), "close-round", "--run-id", run_id)
            _run(str(EVOLVE), "open-round", "--run-id", run_id)
            _run(str(EVOLVE), "close-round", "--run-id", run_id)
            r = _run(str(EVOLVE), "status", "--run-id", run_id)
            out = json.loads(r.stdout)
            self.assertEqual(len(out["rounds"]), 2)
            self.assertEqual(out["current_top_hyp_id"], "hyp-a")


class LineageTests(TestCase):
    def test_lineage_renders_tree(self):
        with isolated_cache() as cache:
            run_id = _seed_run(cache)
            _add_hyp(run_id, "hyp-root")
            _add_hyp(run_id, "hyp-child", parent="hyp-root")
            _add_hyp(run_id, "hyp-grand", parent="hyp-child")
            r = _run(str(EVOLVE), "lineage", "--run-id", run_id)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("hyp-root", r.stdout)
            self.assertIn("hyp-child", r.stdout)
            self.assertIn("hyp-grand", r.stdout)


REC_MATCH = _ROOT / ".claude/skills/tournament/scripts/record_match.py"


def _record_match(run_id: str, a: str, b: str, winner: str) -> None:
    r = _run(str(REC_MATCH), "--run-id", run_id, "--hyp-a", a, "--hyp-b", b,
             "--winner", winner, "--judge-reasoning", "test")
    assert r.returncode == 0, r.stderr


class IntegrationTests(TestCase):
    """Full rank → evolve → re-rank cycle exercising real Elo + ledger."""

    def test_full_cycle_top_changes_after_mutation(self):
        with isolated_cache() as cache:
            run_id = _seed_run(cache, "integ_run")
            # Seed 4 hypotheses, all default Elo 1200
            for h in ("hyp-1", "hyp-2", "hyp-3", "hyp-4"):
                _add_hyp(run_id, h)

            # Round 0: hyp-1 dominates via 3 wins
            _run(str(EVOLVE), "open-round", "--run-id", run_id)
            _record_match(run_id, "hyp-1", "hyp-2", "hyp-1")
            _record_match(run_id, "hyp-1", "hyp-3", "hyp-1")
            _record_match(run_id, "hyp-1", "hyp-4", "hyp-1")
            r = _run(str(EVOLVE), "close-round", "--run-id", run_id)
            out = json.loads(r.stdout)
            self.assertEqual(out["top_hyp_id"], "hyp-1")
            self.assertEqual(out["n_matches"], 3)

            # Round 1: same matches confirm — plateau increments
            _run(str(EVOLVE), "open-round", "--run-id", run_id)
            _record_match(run_id, "hyp-1", "hyp-2", "hyp-1")
            r = _run(str(EVOLVE), "close-round", "--run-id", run_id)
            out = json.loads(r.stdout)
            self.assertEqual(out["top_hyp_id"], "hyp-1")
            self.assertGreaterEqual(out["plateau_count"], 1)

            # Round 2: evolver mutates hyp-1 → hyp-1-mut, which sweeps
            _run(str(EVOLVE), "open-round", "--run-id", run_id)
            _add_hyp(run_id, "hyp-1-mut", parent="hyp-1")
            _record_match(run_id, "hyp-1-mut", "hyp-1", "hyp-1-mut")
            _record_match(run_id, "hyp-1-mut", "hyp-2", "hyp-1-mut")
            _record_match(run_id, "hyp-1-mut", "hyp-3", "hyp-1-mut")
            _record_match(run_id, "hyp-1-mut", "hyp-4", "hyp-1-mut")
            r = _run(str(EVOLVE), "close-round", "--run-id", run_id)
            out = json.loads(r.stdout)
            self.assertEqual(out["top_hyp_id"], "hyp-1-mut")
            self.assertTrue(out["top_changed"])
            self.assertEqual(out["plateau_count"], 0)
            self.assertEqual(out["n_new_children"], 1)

            # Lineage walks the parent edge
            r = _run(str(EVOLVE), "lineage", "--run-id", run_id)
            self.assertIn("hyp-1-mut", r.stdout)
            self.assertIn("hyp-1", r.stdout)


if __name__ == "__main__":
    import sys
    sys.exit(run_tests(OpenRoundTests, CloseRoundTests, StatusTests,
                       LineageTests, IntegrationTests))
