"""v0.96 — cross-run agent quality leaderboard tests."""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

from lib import agent_quality
from lib.cache import run_db_path
from tests.harness import TestCase, isolated_cache, run_tests

_REPO = Path(__file__).resolve().parents[1]


def _new_run_db(rid: str) -> Path:
    db = run_db_path(rid)
    schema = (_REPO / "lib" / "sqlite_schema.sql").read_text()
    con = sqlite3.connect(db)
    con.executescript(schema)
    con.close()
    from lib.migrations import ensure_current
    ensure_current(db)
    return db


def _insert_quality(db: Path, *, run_id: str, agent: str,
                    score: float, at: str = "2026-04-28T00:00:00Z"):
    con = sqlite3.connect(db)
    try:
        with con:
            con.execute(
                "INSERT INTO agent_quality "
                "(run_id, span_id, agent_name, rubric_version, "
                "score_total, criteria_json, judge, artifact_path, "
                "reasoning, notes, at) "
                "VALUES (?, NULL, ?, '0.1', ?, '[]', "
                "'auto-rubric', NULL, NULL, NULL, ?)",
                (run_id, agent, score, at),
            )
    finally:
        con.close()


class LeaderboardTests(TestCase):
    def test_empty_root_returns_empty(self):
        with isolated_cache():
            out = agent_quality.leaderboard()
            self.assertEqual(out["n_rows"], 0)
            self.assertEqual(out["n_dbs"], 0)
            self.assertEqual(out["by_agent"], {})

    def test_aggregates_across_dbs(self):
        with isolated_cache():
            db1 = _new_run_db("rid-1")
            db2 = _new_run_db("rid-2")
            _insert_quality(db1, run_id="rid-1", agent="scout",
                             score=0.6)
            _insert_quality(db1, run_id="rid-1", agent="scout",
                             score=0.8, at="2026-04-28T01:00:00Z")
            _insert_quality(db2, run_id="rid-2", agent="scout",
                             score=0.4)
            _insert_quality(db2, run_id="rid-2", agent="surveyor",
                             score=0.9)
            out = agent_quality.leaderboard()
            self.assertEqual(out["n_rows"], 4)
            self.assertEqual(out["n_dbs"], 2)
            scout = out["by_agent"]["scout"]
            self.assertEqual(scout["n"], 3)
            self.assertEqual(scout["n_runs"], 2)
            self.assertAlmostEqual(scout["mean"], 0.6, places=2)
            self.assertEqual(scout["min"], 0.4)
            self.assertEqual(scout["max"], 0.8)
            self.assertEqual(scout["latest_score"], 0.8)
            sv = out["by_agent"]["surveyor"]
            self.assertEqual(sv["n"], 1)
            self.assertEqual(sv["n_runs"], 1)

    def test_pre_v12_db_skipped(self):
        with isolated_cache():
            from lib.cache import runs_dir
            d = runs_dir()
            d.mkdir(parents=True, exist_ok=True)
            stale = d / "run-stale.db"
            con = sqlite3.connect(stale)
            con.execute("CREATE TABLE x (y INTEGER)")
            con.close()
            out = agent_quality.leaderboard()
            # No agent_quality table → skipped, n_dbs stays 0.
            self.assertEqual(out["n_dbs"], 0)


class CliTests(TestCase):
    def test_leaderboard_cli(self):
        with isolated_cache():
            db = _new_run_db("rid-cli")
            _insert_quality(db, run_id="rid-cli", agent="scout",
                             score=0.7)
            r = subprocess.run(
                [sys.executable, "-m", "lib.agent_quality",
                 "leaderboard"],
                capture_output=True, text=True, cwd=str(_REPO),
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            out = json.loads(r.stdout)
            self.assertEqual(out["n_rows"], 1)
            self.assertIn("scout", out["by_agent"])


if __name__ == "__main__":
    raise SystemExit(run_tests(LeaderboardTests, CliTests))
