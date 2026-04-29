"""v0.158 — record_match --auto-prune integration."""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

from lib.cache import run_db_path
from lib.idea_tree import (
    record_child_hypothesis,
    record_root_hypothesis,
)
from tests.harness import TestCase, isolated_cache, run_tests

_REPO = Path(__file__).resolve().parents[1]
_REC = (_REPO / ".claude" / "skills" / "tournament"
        / "scripts" / "record_match.py")


def _init_run(rid: str = "r1") -> Path:
    db = run_db_path(rid)
    db.parent.mkdir(parents=True, exist_ok=True)
    schema = (_REPO / "lib" / "sqlite_schema.sql").read_text()
    con = sqlite3.connect(db)
    con.executescript(schema)
    con.execute(
        "INSERT INTO runs (run_id, question, started_at, status) "
        "VALUES (?, ?, ?, ?)", (rid, "q", "now", "running"),
    )
    con.commit()
    con.close()
    return db


def _seed_hyp(db: Path, hyp_id: str, elo: float, n_matches: int = 0):
    con = sqlite3.connect(db)
    with con:
        con.execute(
            "INSERT INTO hypotheses "
            "(hyp_id, run_id, agent_name, statement, elo, "
            "n_matches, n_wins, n_losses, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 0, 0, ?)",
            (hyp_id, "r1", "architect", "x", elo, n_matches, "now"),
        )
    con.close()


def _run_match(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(_REC), *args],
        capture_output=True, text=True, cwd=str(_REPO),
    )


class AutoPruneTests(TestCase):
    def test_auto_prune_drops_low_elo_subtree(self):
        with isolated_cache():
            db = _init_run()
            # root + 2 branches; branch B is low-Elo + mature
            _seed_hyp(db, "root", 1300.0, n_matches=5)
            _seed_hyp(db, "ba", 1300.0, n_matches=5)
            _seed_hyp(db, "bb", 900.0, n_matches=5)
            record_root_hypothesis(db, "root")
            record_child_hypothesis(db, "root", "ba")
            record_child_hypothesis(db, "root", "bb")
            r = _run_match(
                "--run-id", "r1",
                "--hyp-a", "root", "--hyp-b", "ba",
                "--winner", "ba",
                "--auto-prune",
                "--prune-threshold", "1100.0",
                "--prune-min-matches", "3",
            )
            self.assertEqual(r.returncode, 0, msg=r.stderr)
            out = json.loads(r.stdout)
            self.assertIn("pruned", out)
            self.assertIn("bb", out["pruned"])
            con = sqlite3.connect(db)
            row = con.execute(
                "SELECT 1 FROM hypotheses WHERE hyp_id='bb'"
            ).fetchone()
            con.close()
            self.assertEqual(row, None)

    def test_no_auto_prune_flag_keeps_subtrees(self):
        with isolated_cache():
            db = _init_run()
            _seed_hyp(db, "root", 1300.0, n_matches=5)
            _seed_hyp(db, "ba", 1300.0, n_matches=5)
            _seed_hyp(db, "bb", 900.0, n_matches=5)
            record_root_hypothesis(db, "root")
            record_child_hypothesis(db, "root", "ba")
            record_child_hypothesis(db, "root", "bb")
            r = _run_match(
                "--run-id", "r1",
                "--hyp-a", "root", "--hyp-b", "ba",
                "--winner", "ba",
            )
            self.assertEqual(r.returncode, 0)
            out = json.loads(r.stdout)
            self.assertNotIn("pruned", out)

    def test_auto_prune_skips_immature_subtrees(self):
        with isolated_cache():
            db = _init_run()
            _seed_hyp(db, "root", 1300.0, n_matches=5)
            _seed_hyp(db, "ba", 1300.0, n_matches=5)
            _seed_hyp(db, "bb", 900.0, n_matches=1)  # immature
            record_root_hypothesis(db, "root")
            record_child_hypothesis(db, "root", "ba")
            record_child_hypothesis(db, "root", "bb")
            r = _run_match(
                "--run-id", "r1",
                "--hyp-a", "root", "--hyp-b", "ba",
                "--winner", "ba",
                "--auto-prune",
                "--prune-min-matches", "3",
            )
            self.assertEqual(r.returncode, 0)
            out = json.loads(r.stdout)
            self.assertNotIn("pruned", out)


class FlatHypothesesIgnoredTests(TestCase):
    def test_flat_hypotheses_no_prune_attempt(self):
        """Non-tree hypotheses don't trigger prune even with flag."""
        with isolated_cache():
            db = _init_run()
            _seed_hyp(db, "h1", 1200.0, n_matches=5)
            _seed_hyp(db, "h2", 1200.0, n_matches=5)
            r = _run_match(
                "--run-id", "r1",
                "--hyp-a", "h1", "--hyp-b", "h2",
                "--winner", "h1",
                "--auto-prune",
            )
            self.assertEqual(r.returncode, 0, msg=r.stderr)
            out = json.loads(r.stdout)
            self.assertNotIn("pruned", out)


if __name__ == "__main__":
    raise SystemExit(run_tests(
        AutoPruneTests, FlatHypothesesIgnoredTests,
    ))
