"""v0.155 — tree-aware ranker (lib.tree_ranker + CLI)."""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from lib import idea_tree, migrations, tree_ranker
from lib.cache import run_db_path
from tests.harness import TestCase, isolated_cache, run_tests

_ROOT = Path(__file__).resolve().parent.parent
SCHEMA = (_ROOT / "lib" / "sqlite_schema.sql").read_text()
CLI = _ROOT / ".claude" / "skills" / "tournament" / "scripts" / "tree_ranker.py"


def _build_run_db(run_id: str = "tr_test") -> Path:
    db = run_db_path(run_id)
    db.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db)
    con.executescript(SCHEMA)
    con.close()
    migrations.ensure_current(db)
    return db


def _insert_hyp(db: Path, hyp_id: str, *, parent: str | None = None,
                run_id: str = "tr_test", elo: float = 1200.0,
                n_matches: int = 0) -> None:
    con = sqlite3.connect(db)
    try:
        con.execute(
            "INSERT OR IGNORE INTO runs (run_id, question, started_at) "
            "VALUES (?, ?, ?)",
            (run_id, "q", datetime.now(UTC).isoformat()),
        )
        con.execute(
            "INSERT INTO hypotheses (hyp_id, run_id, agent_name, "
            "parent_hyp_id, statement, elo, n_matches, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (hyp_id, run_id, "idea-tree-generator", parent,
             f"stmt-{hyp_id}", elo, n_matches,
             datetime.now(UTC).isoformat()),
        )
        con.commit()
    finally:
        con.close()


def _build_tree(db: Path, *, weak_subtree_elo: float = 900.0,
                weak_matches: int = 5,
                strong_elo: float = 1300.0) -> str:
    """Tree shape:
        root
        ├── A (strong)
        │   └── A1
        └── B (weak subtree)
            ├── B1
            └── B2
    Returns root tree_id.
    """
    _insert_hyp(db, "root", elo=1250.0, n_matches=weak_matches)
    idea_tree.record_root_hypothesis(db, "root")
    _insert_hyp(db, "A", parent="root", elo=strong_elo,
                n_matches=weak_matches)
    idea_tree.record_child_hypothesis(db, "root", "A")
    _insert_hyp(db, "A1", parent="A", elo=strong_elo,
                n_matches=weak_matches)
    idea_tree.record_child_hypothesis(db, "A", "A1")
    _insert_hyp(db, "B", parent="root", elo=weak_subtree_elo,
                n_matches=weak_matches)
    idea_tree.record_child_hypothesis(db, "root", "B")
    _insert_hyp(db, "B1", parent="B", elo=weak_subtree_elo,
                n_matches=weak_matches)
    idea_tree.record_child_hypothesis(db, "B", "B1")
    _insert_hyp(db, "B2", parent="B", elo=weak_subtree_elo,
                n_matches=weak_matches)
    idea_tree.record_child_hypothesis(db, "B", "B2")
    return "root"


class TreePairsTests(TestCase):
    def test_siblings(self):
        with isolated_cache():
            db = _build_run_db()
            tree_id = _build_tree(db)
            pairs = tree_ranker.tree_pairs(db, tree_id, strategy="siblings")
            # siblings: (A,B) under root; (B1,B2) under B
            self.assertIn(("A", "B"), pairs)
            self.assertIn(("B1", "B2"), pairs)
            self.assertEqual(len(pairs), 2)

    def test_round_robin(self):
        with isolated_cache():
            db = _build_run_db()
            _build_tree(db)
            pairs = tree_ranker.tree_pairs(db, "root", strategy="round-robin")
            # 6 nodes -> C(6,2) = 15
            self.assertEqual(len(pairs), 15)

    def test_depth_bands(self):
        with isolated_cache():
            db = _build_run_db()
            _build_tree(db)
            pairs = tree_ranker.tree_pairs(db, "root", strategy="depth-bands")
            # depth 0: just root (no pair)
            # depth 1: A, B -> (A,B)
            # depth 2: A1, B1, B2 -> 3 pairs
            self.assertEqual(len(pairs), 4)
            self.assertIn(("A", "B"), pairs)

    def test_empty_tree(self):
        with isolated_cache():
            db = _build_run_db()
            pairs = tree_ranker.tree_pairs(db, "missing", strategy="siblings")
            self.assertEqual(pairs, [])

    def test_unknown_strategy(self):
        with isolated_cache():
            db = _build_run_db()
            _build_tree(db)
            self.assertEqual(
                tree_ranker.tree_pairs(db, "root", strategy="bogus"), [])


class SubtreeMeanEloTests(TestCase):
    def test_mean(self):
        with isolated_cache():
            db = _build_run_db()
            _build_tree(db, weak_subtree_elo=900.0, strong_elo=1300.0)
            # subtree(B) = {B=900, B1=900, B2=900} mean=900
            self.assertAlmostEqual(
                tree_ranker.subtree_mean_elo(db, "B"), 900.0, delta=0.001)
            # subtree(A) = {A=1300, A1=1300} mean=1300
            self.assertAlmostEqual(
                tree_ranker.subtree_mean_elo(db, "A"), 1300.0, delta=0.001)

    def test_missing_root(self):
        with isolated_cache():
            db = _build_run_db()
            self.assertEqual(
                tree_ranker.subtree_mean_elo(db, "ghost"), 1200.0)


class PruneLowEloTests(TestCase):
    def test_prunes_weak_subtree(self):
        with isolated_cache():
            db = _build_run_db()
            _build_tree(db, weak_subtree_elo=900.0, weak_matches=5,
                        strong_elo=1300.0)
            pruned = tree_ranker.prune_low_elo_subtrees(
                db, "root", threshold=1100.0, min_matches=3)
            # B subtree pruned (mean 900 < 1100); A kept.
            self.assertIn("B", pruned)
            # A subtree was strong, not pruned.
            self.assertNotIn("A", pruned)
            # B1, B2 are descendants of B — not reported separately.
            self.assertNotIn("B1", pruned)
            self.assertNotIn("B2", pruned)
            # Verify rows actually deleted.
            con = sqlite3.connect(db)
            remaining = {r[0] for r in con.execute(
                "SELECT hyp_id FROM hypotheses")}
            con.close()
            self.assertNotIn("B", remaining)
            self.assertNotIn("B1", remaining)
            self.assertNotIn("B2", remaining)
            self.assertIn("A", remaining)
            self.assertIn("root", remaining)

    def test_skips_immature(self):
        with isolated_cache():
            db = _build_run_db()
            # weak_matches=1 — below default min_matches=3
            _build_tree(db, weak_subtree_elo=900.0, weak_matches=1,
                        strong_elo=1300.0)
            pruned = tree_ranker.prune_low_elo_subtrees(
                db, "root", threshold=1100.0, min_matches=3)
            self.assertEqual(pruned, [])

    def test_does_not_prune_root(self):
        with isolated_cache():
            db = _build_run_db()
            # everything weak — root would be tempting to prune
            _build_tree(db, weak_subtree_elo=500.0, weak_matches=5,
                        strong_elo=500.0)
            # also override root + A path to weak
            con = sqlite3.connect(db)
            con.execute("UPDATE hypotheses SET elo=500.0 WHERE hyp_id IN "
                        "('root','A','A1')")
            con.commit()
            con.close()
            pruned = tree_ranker.prune_low_elo_subtrees(
                db, "root", threshold=1100.0, min_matches=3)
            self.assertNotIn("root", pruned)
            con = sqlite3.connect(db)
            self.assertEqual(
                con.execute("SELECT COUNT(*) FROM hypotheses "
                            "WHERE hyp_id='root'").fetchone()[0], 1)
            con.close()

    def test_returns_pruned_list_type(self):
        with isolated_cache():
            db = _build_run_db()
            _build_tree(db, weak_subtree_elo=900.0, weak_matches=5,
                        strong_elo=1300.0)
            pruned = tree_ranker.prune_low_elo_subtrees(
                db, "root", threshold=1100.0, min_matches=3)
            self.assertTrue(isinstance(pruned, list))
            self.assertTrue(all(isinstance(x, str) for x in pruned))

    def test_idempotent(self):
        with isolated_cache():
            db = _build_run_db()
            _build_tree(db, weak_subtree_elo=900.0, weak_matches=5,
                        strong_elo=1300.0)
            tree_ranker.prune_low_elo_subtrees(
                db, "root", threshold=1100.0, min_matches=3)
            second = tree_ranker.prune_low_elo_subtrees(
                db, "root", threshold=1100.0, min_matches=3)
            self.assertEqual(second, [])

    def test_threshold_strict_lt(self):
        with isolated_cache():
            db = _build_run_db()
            # exactly at threshold: 1100 — strict < so NOT pruned
            _build_tree(db, weak_subtree_elo=1100.0, weak_matches=5,
                        strong_elo=1300.0)
            pruned = tree_ranker.prune_low_elo_subtrees(
                db, "root", threshold=1100.0, min_matches=3)
            self.assertNotIn("B", pruned)


class TreeLeaderboardTests(TestCase):
    def test_ordered_desc(self):
        with isolated_cache():
            db = _build_run_db()
            _build_tree(db, weak_subtree_elo=900.0, strong_elo=1300.0)
            rows = tree_ranker.tree_leaderboard(db, "root")
            self.assertEqual(len(rows), 6)
            elos = [r["elo"] for r in rows]
            self.assertEqual(elos, sorted(elos, reverse=True))
            # Surfaces depth + parent
            self.assertIn("depth", rows[0])
            self.assertIn("parent_hyp_id", rows[0])

    def test_empty(self):
        with isolated_cache():
            db = _build_run_db()
            self.assertEqual(tree_ranker.tree_leaderboard(db, "ghost"), [])


def _run_cli(*args: str) -> tuple[int, str, str]:
    proc = subprocess.run(
        [sys.executable, str(CLI), *args],
        capture_output=True, text=True, cwd=str(_ROOT),
    )
    return proc.returncode, proc.stdout, proc.stderr


class CLITests(TestCase):
    def test_help(self):
        rc, out, err = _run_cli("-h")
        self.assertEqual(rc, 0)
        self.assertIn("pairs", out)
        self.assertIn("prune", out)
        self.assertIn("leaderboard", out)

    def test_pairs_subcommand(self):
        with isolated_cache():
            db = _build_run_db()
            _build_tree(db)
            rc, out, _ = _run_cli(
                "pairs", "--run-db", str(db), "--tree-id", "root",
                "--strategy", "siblings",
            )
            self.assertEqual(rc, 0)
            data = json.loads(out)
            self.assertEqual(data["tree_id"], "root")
            self.assertEqual(data["strategy"], "siblings")
            self.assertEqual(data["n_pairs"], 2)
            self.assertTrue(isinstance(data["pairs"], list))

    def test_prune_subcommand(self):
        with isolated_cache():
            db = _build_run_db()
            _build_tree(db, weak_subtree_elo=900.0, weak_matches=5,
                        strong_elo=1300.0)
            rc, out, _ = _run_cli(
                "prune", "--run-db", str(db), "--tree-id", "root",
                "--threshold", "1100", "--min-matches", "3",
            )
            self.assertEqual(rc, 0)
            data = json.loads(out)
            self.assertIn("B", data["pruned"])

    def test_leaderboard_subcommand(self):
        with isolated_cache():
            db = _build_run_db()
            _build_tree(db, weak_subtree_elo=900.0, strong_elo=1300.0)
            rc, out, _ = _run_cli(
                "leaderboard", "--run-db", str(db), "--tree-id", "root",
            )
            self.assertEqual(rc, 0)
            data = json.loads(out)
            self.assertEqual(data["n"], 6)
            elos = [r["elo"] for r in data["leaderboard"]]
            self.assertEqual(elos, sorted(elos, reverse=True))


if __name__ == "__main__":
    raise SystemExit(run_tests(
        TreePairsTests,
        SubtreeMeanEloTests,
        PruneLowEloTests,
        TreeLeaderboardTests,
        CLITests,
    ))
