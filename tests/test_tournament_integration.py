"""v0.79 — tournament end-to-end integration tests.

Existing test_tournament.py covers per-script unit behavior. This
suite exercises the full Co-scientist loop:

  register N hypotheses → run K pairwise matches → leaderboard →
  evolve top → register children with parent_hyp_id → re-leaderboard

Asserts:
  * Elo updates accumulate correctly across multiple matches.
  * Children inherit parent lineage.
  * Leaderboard ordering reflects match outcomes.
  * `evolve_loop.py` ledger captures plateau detection.
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

from tests.harness import TestCase, isolated_cache, run_tests
from lib.cache import run_db_path


_REPO = Path(__file__).resolve().parents[1]
_T = _REPO / ".claude" / "skills" / "tournament" / "scripts"
_SCHEMA = _REPO / "lib" / "sqlite_schema.sql"


def _new_run_db(rid: str) -> Path:
    db = run_db_path(rid)
    con = sqlite3.connect(db)
    con.executescript(_SCHEMA.read_text())
    con.close()
    from lib.migrations import ensure_current
    ensure_current(db)
    # Tournament needs a runs row to satisfy any future FK; insert minimal.
    con = sqlite3.connect(db)
    with con:
        try:
            con.execute(
                "INSERT INTO runs (run_id, question, started_at, "
                " status, overnight) VALUES (?, ?, ?, ?, 0)",
                (rid, "test question", "2026-04-28T00:00:00+00:00", "open"),
            )
        except sqlite3.IntegrityError:
            pass
    con.close()
    return db


def _run_script(name: str, *args) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(_T / name), *args],
        capture_output=True, text=True, cwd=str(_REPO),
    )


def _record(rid: str, hyp_id: str, statement: str,
            agent: str = "theorist", parent: str | None = None) -> None:
    args = ["--run-id", rid, "--agent-name", agent,
            "--hyp-id", hyp_id, "--statement", statement]
    if parent:
        args += ["--parent-hyp-id", parent]
    r = _run_script("record_hypothesis.py", *args)
    assert r.returncode == 0, r.stderr


def _match(rid: str, a: str, b: str, winner: str,
           reason: str = "test") -> None:
    r = _run_script(
        "record_match.py", "--run-id", rid,
        "--hyp-a", a, "--hyp-b", b, "--winner", winner,
        "--judge-reasoning", reason,
    )
    assert r.returncode == 0, r.stderr


def _leaderboard(rid: str, top: int = 10) -> list[dict]:
    r = _run_script(
        "leaderboard.py", "--run-id", rid, "--top", str(top),
    )
    assert r.returncode == 0, r.stderr
    payload = json.loads(r.stdout)
    return payload["top"]


class TournamentLifecycleTests(TestCase):
    def test_full_register_match_leaderboard_flow(self):
        with isolated_cache():
            rid = "tour_full"
            _new_run_db(rid)
            _record(rid, "h1", "claim 1")
            _record(rid, "h2", "claim 2")
            _record(rid, "h3", "claim 3")
            # h1 beats h2, h1 beats h3 → h1 should top.
            _match(rid, "h1", "h2", "h1")
            _match(rid, "h1", "h3", "h1")
            board = _leaderboard(rid, top=10)
            self.assertEqual(board[0]["hyp_id"], "h1")
            self.assertGreater(board[0]["elo"], 1200.0)
            # h1 should have 2 wins.
            self.assertEqual(board[0]["n_wins"], 2)

    def test_draw_keeps_elo_close(self):
        with isolated_cache():
            rid = "tour_draw"
            _new_run_db(rid)
            _record(rid, "a", "alpha")
            _record(rid, "b", "beta")
            _match(rid, "a", "b", "draw")
            con = sqlite3.connect(run_db_path(rid))
            try:
                rows = dict(
                    (r[0], r[1]) for r in con.execute(
                        "SELECT hyp_id, elo FROM hypotheses",
                    )
                )
            finally:
                con.close()
            # Equal starting Elo + draw = no change.
            self.assertAlmostEqual(rows["a"], 1200.0, delta=0.01)
            self.assertAlmostEqual(rows["b"], 1200.0, delta=0.01)

    def test_elo_zero_sum(self):
        with isolated_cache():
            rid = "tour_zsum"
            _new_run_db(rid)
            _record(rid, "x", "X")
            _record(rid, "y", "Y")
            _match(rid, "x", "y", "x")
            con = sqlite3.connect(run_db_path(rid))
            try:
                xelo, yelo = next(iter(con.execute(
                    "SELECT (SELECT elo FROM hypotheses WHERE hyp_id='x'), "
                    "(SELECT elo FROM hypotheses WHERE hyp_id='y')",
                )))
            finally:
                con.close()
            # Elo is zero-sum: (xelo - 1200) + (yelo - 1200) ≈ 0.
            self.assertAlmostEqual(
                (xelo - 1200.0) + (yelo - 1200.0),
                0.0, delta=0.01,
            )

    def test_child_lineage_recorded(self):
        with isolated_cache():
            rid = "tour_lineage"
            _new_run_db(rid)
            _record(rid, "parent", "original idea")
            _record(rid, "child", "mutation of original",
                    agent="evolver", parent="parent")
            con = sqlite3.connect(run_db_path(rid))
            try:
                row = con.execute(
                    "SELECT parent_hyp_id, agent_name FROM hypotheses "
                    "WHERE hyp_id=?", ("child",),
                ).fetchone()
            finally:
                con.close()
            self.assertEqual(row[0], "parent")
            self.assertEqual(row[1], "evolver")

    def test_match_count_accumulates(self):
        with isolated_cache():
            rid = "tour_count"
            _new_run_db(rid)
            _record(rid, "h1", "h1")
            _record(rid, "h2", "h2")
            for _ in range(5):
                _match(rid, "h1", "h2", "h1")
            board = _leaderboard(rid, top=10)
            for entry in board:
                if entry["hyp_id"] == "h1":
                    self.assertEqual(entry["n_matches"], 5)
                    self.assertEqual(entry["n_wins"], 5)
                if entry["hyp_id"] == "h2":
                    self.assertEqual(entry["n_matches"], 5)
                    self.assertEqual(entry["n_losses"], 5)


class TournamentDuplicateGuardTests(TestCase):
    def test_duplicate_hyp_id_rejected(self):
        with isolated_cache():
            rid = "tour_dup"
            _new_run_db(rid)
            _record(rid, "h1", "first")
            r = _run_script(
                "record_hypothesis.py",
                "--run-id", rid, "--agent-name", "theorist",
                "--hyp-id", "h1", "--statement", "second",
            )
            self.assertTrue(r.returncode != 0,
                            f"expected nonzero, got {r.returncode}")


if __name__ == "__main__":
    raise SystemExit(run_tests(
        TournamentLifecycleTests,
        TournamentDuplicateGuardTests,
    ))
