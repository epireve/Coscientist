"""v0.203 — auto-tournament hook between inquisitor and weaver.

Closes the architectural gap from dogfood run 86926630: ranker never
dispatched, tournament_matches stayed empty, brief degraded to v0.199
fallback. Tests cover lib.auto_tournament + db.py record-phase wiring.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from lib import auto_tournament, idea_tree, migrations
from lib.cache import run_db_path
from tests.harness import TestCase, isolated_cache, run_tests

_ROOT = Path(__file__).resolve().parent.parent
SCHEMA = (_ROOT / "lib" / "sqlite_schema.sql").read_text()
DB_CLI = _ROOT / ".claude" / "skills" / "deep-research" / "scripts" / "db.py"


def _build_run_db(run_id: str = "v203_test") -> Path:
    db = run_db_path(run_id)
    db.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db)
    con.executescript(SCHEMA)
    con.close()
    migrations.ensure_current(db)
    # Seed runs row + standard phase rows for record-phase calls.
    con = sqlite3.connect(db)
    try:
        now = datetime.now(UTC).isoformat()
        con.execute(
            "INSERT INTO runs (run_id, question, started_at) VALUES (?, ?, ?)",
            (run_id, "test question", now),
        )
        for i, ph in enumerate(("scout", "cartographer", "chronicler",
                                 "surveyor", "synthesist", "architect",
                                 "inquisitor", "weaver", "visionary",
                                 "steward")):
            con.execute(
                "INSERT INTO phases (run_id, name, ordinal) "
                "VALUES (?, ?, ?)",
                (run_id, ph, i),
            )
        con.commit()
    finally:
        con.close()
    return db


def _insert_hyp(db: Path, hyp_id: str, *, run_id: str = "v203_test",
                parent: str | None = None, elo: float = 1200.0,
                n_matches: int = 0, falsifiers: str | None = None,
                supporting_ids: str | None = None) -> None:
    con = sqlite3.connect(db)
    try:
        con.execute(
            "INSERT INTO hypotheses (hyp_id, run_id, agent_name, "
            "parent_hyp_id, statement, elo, n_matches, falsifiers, "
            "supporting_ids, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (hyp_id, run_id, "architect", parent, f"stmt-{hyp_id}",
             elo, n_matches, falsifiers, supporting_ids,
             datetime.now(UTC).isoformat()),
        )
        con.commit()
    finally:
        con.close()


def _build_simple_tree(db: Path) -> str:
    """root + 3 children, all with tree_id stamped via idea_tree."""
    _insert_hyp(db, "root", elo=1250.0, n_matches=5)
    idea_tree.record_root_hypothesis(db, "root")
    for cid, e in (("c1", 1300.0), ("c2", 1100.0), ("c3", 1200.0)):
        _insert_hyp(db, cid, parent="root", elo=e, n_matches=5)
        idea_tree.record_child_hypothesis(db, "root", cid)
    return "root"


def _flat_hyps(db: Path) -> None:
    """Hypotheses without tree_id — should not trigger auto-tournament."""
    _insert_hyp(db, "f1")
    _insert_hyp(db, "f2")


class ShouldAutoTournamentTests(TestCase):
    def test_env_var_set_with_tree(self):
        with isolated_cache():
            db = _build_run_db()
            _build_simple_tree(db)
            os.environ["COSCIENTIST_AUTO_TOURNAMENT"] = "1"
            try:
                self.assertTrue(auto_tournament.should_auto_tournament(db))
            finally:
                os.environ.pop("COSCIENTIST_AUTO_TOURNAMENT", None)

    def test_no_env_var(self):
        with isolated_cache():
            db = _build_run_db()
            _build_simple_tree(db)
            os.environ.pop("COSCIENTIST_AUTO_TOURNAMENT", None)
            self.assertFalse(auto_tournament.should_auto_tournament(db))

    def test_env_var_set_but_no_trees(self):
        with isolated_cache():
            db = _build_run_db()
            _flat_hyps(db)
            os.environ["COSCIENTIST_AUTO_TOURNAMENT"] = "1"
            try:
                self.assertFalse(auto_tournament.should_auto_tournament(db))
            finally:
                os.environ.pop("COSCIENTIST_AUTO_TOURNAMENT", None)


class JudgePairTests(TestCase):
    def test_higher_elo_wins(self):
        a = {"hyp_id": "a", "elo": 1300.0, "falsifiers": "x",
             "supporting_ids": None}
        b = {"hyp_id": "b", "elo": 1100.0, "falsifiers": "x",
             "supporting_ids": None}
        self.assertEqual(auto_tournament._judge_pair(a, b, 42), "a")
        self.assertEqual(auto_tournament._judge_pair(b, a, 42), "a")

    def test_tiebreak_falsifier_then_supporting_then_alpha(self):
        # Same Elo, longer falsifiers wins.
        a = {"hyp_id": "a", "elo": 1200.0,
             "falsifiers": "long-detailed-falsifier-text",
             "supporting_ids": None}
        b = {"hyp_id": "b", "elo": 1200.0, "falsifiers": "x",
             "supporting_ids": None}
        self.assertEqual(auto_tournament._judge_pair(a, b, 42), "a")

        # Same Elo, same falsifier-len, more supporting_ids wins.
        a = {"hyp_id": "a", "elo": 1200.0, "falsifiers": "x",
             "supporting_ids": json.dumps(["p1", "p2", "p3"])}
        b = {"hyp_id": "b", "elo": 1200.0, "falsifiers": "x",
             "supporting_ids": json.dumps(["p1"])}
        self.assertEqual(auto_tournament._judge_pair(a, b, 42), "a")

        # Full tie → alphabetical hyp_id wins (lower).
        a = {"hyp_id": "alpha", "elo": 1200.0, "falsifiers": "x",
             "supporting_ids": None}
        b = {"hyp_id": "beta", "elo": 1200.0, "falsifiers": "x",
             "supporting_ids": None}
        self.assertEqual(auto_tournament._judge_pair(a, b, 42), "alpha")

    def test_deterministic_same_seed(self):
        a = {"hyp_id": "x", "elo": 1200.0, "falsifiers": "f",
             "supporting_ids": None}
        b = {"hyp_id": "y", "elo": 1200.0, "falsifiers": "f",
             "supporting_ids": None}
        w1 = auto_tournament._judge_pair(a, b, 42)
        w2 = auto_tournament._judge_pair(a, b, 42)
        self.assertEqual(w1, w2)


class RunAutoTournamentTests(TestCase):
    def test_records_matches(self):
        with isolated_cache():
            db = _build_run_db()
            _build_simple_tree(db)
            result = auto_tournament.run_auto_tournament(db)
            self.assertEqual(result["trees_processed"], 1)
            self.assertGreater(result["matches_recorded"], 0)
            con = sqlite3.connect(db)
            n = con.execute(
                "SELECT COUNT(*) FROM tournament_matches"
            ).fetchone()[0]
            con.close()
            self.assertEqual(n, result["matches_recorded"])

    def test_updates_elo_on_participants(self):
        with isolated_cache():
            db = _build_run_db()
            _build_simple_tree(db)
            con = sqlite3.connect(db)
            before = dict(con.execute(
                "SELECT hyp_id, n_matches FROM hypotheses "
                "WHERE tree_id IS NOT NULL").fetchall())
            con.close()
            auto_tournament.run_auto_tournament(db)
            con = sqlite3.connect(db)
            after = dict(con.execute(
                "SELECT hyp_id, n_matches FROM hypotheses "
                "WHERE tree_id IS NOT NULL").fetchall())
            con.close()
            # Every participant that survived pruning should have
            # at least one more match. Pruned rows are gone.
            self.assertGreater(len(after), 0)
            for hid, n_after in after.items():
                self.assertGreater(n_after, before[hid])

    def test_prunes_low_elo_subtree(self):
        with isolated_cache():
            db = _build_run_db()
            # Build a tree where one branch is deeply weak with mature
            # n_matches so the prune step fires after the sweep.
            _insert_hyp(db, "root", elo=1250.0, n_matches=5)
            idea_tree.record_root_hypothesis(db, "root")
            _insert_hyp(db, "good", parent="root", elo=1300.0,
                        n_matches=5)
            idea_tree.record_child_hypothesis(db, "root", "good")
            _insert_hyp(db, "bad", parent="root", elo=900.0,
                        n_matches=5)
            idea_tree.record_child_hypothesis(db, "root", "bad")
            _insert_hyp(db, "bad-child", parent="bad", elo=900.0,
                        n_matches=5)
            idea_tree.record_child_hypothesis(db, "bad", "bad-child")
            result = auto_tournament.run_auto_tournament(
                db, prune_threshold=1100.0, prune_min_matches=3)
            # The "bad" subtree should land below threshold even after
            # the sweep mutates Elo a bit.
            self.assertIn("bad", result["pruned"])
            con = sqlite3.connect(db)
            remaining = {r[0] for r in con.execute(
                "SELECT hyp_id FROM hypotheses").fetchall()}
            con.close()
            self.assertNotIn("bad", remaining)
            self.assertNotIn("bad-child", remaining)

    def test_no_trees_returns_empty(self):
        with isolated_cache():
            db = _build_run_db()
            _flat_hyps(db)
            result = auto_tournament.run_auto_tournament(db)
            self.assertEqual(result["trees_processed"], 0)
            self.assertEqual(result["matches_recorded"], 0)


def _run_db_cli(*args: str, env_extra: dict | None = None) -> tuple[int, str, str]:
    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    proc = subprocess.run(
        [sys.executable, str(DB_CLI), *args],
        capture_output=True, text=True, cwd=str(_ROOT), env=env,
    )
    return proc.returncode, proc.stdout, proc.stderr


class RecordPhaseHookTests(TestCase):
    def test_inquisitor_complete_with_flag_runs_tournament(self):
        with isolated_cache():
            db = _build_run_db()
            _build_simple_tree(db)
            rc, out, err = _run_db_cli(
                "record-phase", "--run-id", "v203_test",
                "--phase", "inquisitor", "--complete",
                "--auto-tournament",
            )
            self.assertEqual(rc, 0, msg=f"rc={rc} stderr={err}")
            con = sqlite3.connect(db)
            n = con.execute(
                "SELECT COUNT(*) FROM tournament_matches"
            ).fetchone()[0]
            con.close()
            self.assertGreater(n, 0)

    def test_inquisitor_complete_no_flag_leaves_tournament_empty(self):
        with isolated_cache():
            db = _build_run_db()
            _build_simple_tree(db)
            # Make sure env var is unset so the hook stays dormant.
            env = {"COSCIENTIST_AUTO_TOURNAMENT": ""}
            rc, _, err = _run_db_cli(
                "record-phase", "--run-id", "v203_test",
                "--phase", "inquisitor", "--complete",
                env_extra=env,
            )
            self.assertEqual(rc, 0, msg=f"rc={rc} stderr={err}")
            con = sqlite3.connect(db)
            n = con.execute(
                "SELECT COUNT(*) FROM tournament_matches"
            ).fetchone()[0]
            con.close()
            self.assertEqual(n, 0)

    def test_other_phase_complete_with_flag_does_not_run(self):
        with isolated_cache():
            db = _build_run_db()
            _build_simple_tree(db)
            # --auto-tournament on a non-inquisitor phase: hook MUST
            # NOT fire. Architect is the predecessor; skip silently.
            rc, _, err = _run_db_cli(
                "record-phase", "--run-id", "v203_test",
                "--phase", "architect", "--complete",
                "--auto-tournament",
            )
            self.assertEqual(rc, 0, msg=f"rc={rc} stderr={err}")
            con = sqlite3.connect(db)
            n = con.execute(
                "SELECT COUNT(*) FROM tournament_matches"
            ).fetchone()[0]
            con.close()
            self.assertEqual(n, 0)


if __name__ == "__main__":
    raise SystemExit(run_tests(
        ShouldAutoTournamentTests,
        JudgePairTests,
        RunAutoTournamentTests,
        RecordPhaseHookTests,
    ))
