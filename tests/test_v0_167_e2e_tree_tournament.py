"""v0.167 — D3 architect→mutator→ranker→prune end-to-end integration.

Exercises the full v0.156→v0.158 chain via the real CLIs:
  - record_hypothesis.py emits root + branches (architect)
  - record_hypothesis.py emits sub-branches under best (mutator)
  - record_match.py runs matches + final --auto-prune (ranker)
  - lib.idea_tree.get_tree confirms BFS ordering
  - prune drops the low-Elo mature subtree, surviving nodes still
    form a connected tree with the original root.

Elo trajectory engineered to fire pruning deterministically:
  root, ba, bc, baa, bac → high Elo (1300, mature)
  bb → low Elo (900, mature) — pruned
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

from lib.cache import run_db_path
from lib.idea_tree import get_tree
from tests.harness import TestCase, isolated_cache, run_tests

_REPO = Path(__file__).resolve().parents[1]
_REC_HYP = (_REPO / ".claude" / "skills" / "tournament"
            / "scripts" / "record_hypothesis.py")
_REC_MATCH = (_REPO / ".claude" / "skills" / "tournament"
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


def _run(script: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(script), *args],
        capture_output=True, text=True, cwd=str(_REPO),
    )


def _stamp_elo(db: Path, hyp_id: str, elo: float, n_matches: int) -> None:
    """Force Elo + n_matches post-insert. Mirrors how a tournament
    arrives at "mature, low-Elo" without us having to play 5 dummy
    matches per node."""
    con = sqlite3.connect(db)
    with con:
        con.execute(
            "UPDATE hypotheses SET elo=?, n_matches=? WHERE hyp_id=?",
            (elo, n_matches, hyp_id),
        )
    con.close()


def _emit_root(rid: str, hyp_id: str) -> subprocess.CompletedProcess:
    return _run(
        _REC_HYP,
        "--run-id", rid, "--agent-name", "architect",
        "--hyp-id", hyp_id, "--tree-root",
        "--statement", f"root: {hyp_id}",
    )


def _emit_child(rid: str, hyp_id: str, parent: str,
                agent: str = "architect") -> subprocess.CompletedProcess:
    return _run(
        _REC_HYP,
        "--run-id", rid, "--agent-name", agent,
        "--hyp-id", hyp_id, "--parent-hyp-id", parent,
        "--statement", f"child: {hyp_id}",
    )


class RootEmissionTests(TestCase):
    def test_root_emission_via_cli(self):
        with isolated_cache():
            _init_run()
            r = _emit_root("r1", "root")
            self.assertEqual(r.returncode, 0, msg=r.stderr)
            out = json.loads(r.stdout)
            self.assertEqual(out["tree_id"], "root")
            self.assertEqual(out["depth"], 0)
            self.assertEqual(out["branch_index"], 0)


class BranchEmissionTests(TestCase):
    def test_branch_emission_via_cli(self):
        with isolated_cache():
            _init_run()
            _emit_root("r1", "root")
            r = _emit_child("r1", "ba", "root")
            self.assertEqual(r.returncode, 0, msg=r.stderr)
            out = json.loads(r.stdout)
            self.assertEqual(out["tree_id"], "root")
            self.assertEqual(out["depth"], 1)


class SubBranchEmissionTests(TestCase):
    def test_subbranch_emission(self):
        """Mutator-style: pick best branch, add 2 sub-branches."""
        with isolated_cache():
            db = _init_run()
            _emit_root("r1", "root")
            _emit_child("r1", "ba", "root")
            _emit_child("r1", "bb", "root")
            _emit_child("r1", "bc", "root")
            # Seed Elo so ba is "best"
            _stamp_elo(db, "ba", 1400.0, 5)
            _stamp_elo(db, "bb", 1100.0, 5)
            _stamp_elo(db, "bc", 1200.0, 5)
            # Mutator emits 2 sub-branches under best (ba)
            r1 = _emit_child("r1", "baa", "ba", agent="mutator")
            r2 = _emit_child("r1", "bac", "ba", agent="mutator")
            self.assertEqual(r1.returncode, 0, msg=r1.stderr)
            self.assertEqual(r2.returncode, 0, msg=r2.stderr)
            out1 = json.loads(r1.stdout)
            out2 = json.loads(r2.stdout)
            self.assertEqual(out1["depth"], 2)
            self.assertEqual(out2["depth"], 2)
            self.assertEqual(out1["tree_id"], "root")
            self.assertEqual(out2["tree_id"], "root")


class GetTreeOrderingTests(TestCase):
    def test_get_tree_returns_ordered_nodes(self):
        with isolated_cache():
            db = _init_run()
            _emit_root("r1", "root")
            _emit_child("r1", "ba", "root")
            _emit_child("r1", "bb", "root")
            _emit_child("r1", "bc", "root")
            _emit_child("r1", "baa", "ba", agent="mutator")
            _emit_child("r1", "bac", "ba", agent="mutator")
            nodes = get_tree(db, "root")
            self.assertEqual(len(nodes), 6)
            ids = [n["hyp_id"] for n in nodes]
            # Depth 0 first, then depth 1, then depth 2.
            depths = [n["depth"] for n in nodes]
            self.assertEqual(depths, sorted(depths))
            self.assertEqual(ids[0], "root")
            # Within depth 1, ordered by branch_index (insertion order).
            self.assertEqual(ids[1:4], ["ba", "bb", "bc"])
            self.assertEqual(set(ids[4:]), {"baa", "bac"})


class RecordMatchPruneE2ETests(TestCase):
    def test_record_match_with_prune_drops_weak_subtree(self):
        """Full chain: build tree, seed Elo, run prune match.

        Setup: root + 3 branches (ba/bb/bc) + 2 sub-branches (baa/bac
        under ba). bb is weak + mature → must be pruned. ba/bc/root
        + their children survive.
        """
        with isolated_cache():
            db = _init_run()
            _emit_root("r1", "root")
            _emit_child("r1", "ba", "root")
            _emit_child("r1", "bb", "root")
            _emit_child("r1", "bc", "root")
            _emit_child("r1", "baa", "ba", agent="mutator")
            _emit_child("r1", "bac", "ba", agent="mutator")
            # Force Elo state: bb low+mature, others high+mature.
            _stamp_elo(db, "root", 1300.0, 5)
            _stamp_elo(db, "ba", 1300.0, 5)
            _stamp_elo(db, "bb", 900.0, 5)
            _stamp_elo(db, "bc", 1300.0, 5)
            _stamp_elo(db, "baa", 1300.0, 5)
            _stamp_elo(db, "bac", 1300.0, 5)
            # Final match w/ auto-prune. Match between ba+root —
            # neither is bb, but tree-pruning runs on the whole tree.
            r = _run(
                _REC_MATCH,
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
            # bb gone from DB.
            con = sqlite3.connect(db)
            row = con.execute(
                "SELECT 1 FROM hypotheses WHERE hyp_id='bb'"
            ).fetchone()
            con.close()
            self.assertEqual(row, None)
            # Survivors < 6 original nodes.
            remaining = get_tree(db, "root")
            self.assertTrue(len(remaining) < 6)
            # High-Elo survivors all present.
            survivor_ids = {n["hyp_id"] for n in remaining}
            for sid in ("root", "ba", "bc", "baa", "bac"):
                self.assertIn(sid, survivor_ids)


class TreeIntegrityPostPruneTests(TestCase):
    def test_surviving_nodes_form_connected_tree(self):
        """No orphans: every surviving non-root has its parent in the
        survivor set."""
        with isolated_cache():
            db = _init_run()
            _emit_root("r1", "root")
            _emit_child("r1", "ba", "root")
            _emit_child("r1", "bb", "root")
            _emit_child("r1", "bc", "root")
            _emit_child("r1", "baa", "ba", agent="mutator")
            _emit_child("r1", "bac", "ba", agent="mutator")
            _stamp_elo(db, "root", 1300.0, 5)
            _stamp_elo(db, "ba", 1300.0, 5)
            _stamp_elo(db, "bb", 900.0, 5)
            _stamp_elo(db, "bc", 1300.0, 5)
            _stamp_elo(db, "baa", 1300.0, 5)
            _stamp_elo(db, "bac", 1300.0, 5)
            r = _run(
                _REC_MATCH,
                "--run-id", "r1",
                "--hyp-a", "root", "--hyp-b", "ba",
                "--winner", "ba",
                "--auto-prune",
                "--prune-threshold", "1100.0",
                "--prune-min-matches", "3",
            )
            self.assertEqual(r.returncode, 0, msg=r.stderr)
            survivors = get_tree(db, "root")
            survivor_ids = {n["hyp_id"] for n in survivors}
            # Root present.
            self.assertIn("root", survivor_ids)
            # Every non-root survivor has its parent in survivors.
            for n in survivors:
                if n["hyp_id"] == "root":
                    continue
                parent = n.get("parent_hyp_id")
                self.assertTrue(
                    parent is not None,
                    msg=f"{n['hyp_id']} missing parent_hyp_id",
                )
                self.assertIn(
                    parent, survivor_ids,
                    msg=f"orphan: {n['hyp_id']} → parent {parent}",
                )


if __name__ == "__main__":
    raise SystemExit(run_tests(
        RootEmissionTests,
        BranchEmissionTests,
        SubBranchEmissionTests,
        GetTreeOrderingTests,
        RecordMatchPruneE2ETests,
        TreeIntegrityPostPruneTests,
    ))
