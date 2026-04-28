"""v0.127 — quality drift time-series tests."""
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


def _insert(db: Path, *, run_id: str, agent: str,
            score: float, at: str):
    con = sqlite3.connect(db)
    try:
        with con:
            con.execute(
                "INSERT INTO agent_quality "
                "(run_id, span_id, agent_name, rubric_version, "
                "score_total, criteria_json, judge, "
                "artifact_path, reasoning, notes, at) "
                "VALUES (?, NULL, ?, '0.1', ?, '[]', "
                "'auto-rubric', NULL, NULL, NULL, ?)",
                (run_id, agent, score, at),
            )
    finally:
        con.close()


class QualityDriftTests(TestCase):
    def test_empty_root_returns_zero(self):
        with isolated_cache():
            out = agent_quality.quality_drift()
            self.assertEqual(out["n_rows"], 0)
            self.assertEqual(out["by_agent"], {})

    def test_insufficient_data_marks_insufficient(self):
        with isolated_cache():
            db = _new_run_db("rid-i")
            for i in range(3):
                _insert(db, run_id="rid-i", agent="scout",
                         score=0.7,
                         at=f"2026-04-2{i}T00:00:00Z")
            out = agent_quality.quality_drift(window=5)
            scout = out["by_agent"]["scout"]
            self.assertEqual(scout["direction"], "insufficient")
            self.assertEqual(scout["n_total"], 3)

    def test_declining_trend_detected(self):
        with isolated_cache():
            db = _new_run_db("rid-d")
            # 5 prior scores high (0.9), 5 latest low (0.4)
            for i in range(5):
                _insert(db, run_id="rid-d", agent="scout",
                         score=0.9,
                         at=f"2026-04-{i+1:02d}T00:00:00Z")
            for i in range(5):
                _insert(db, run_id="rid-d", agent="scout",
                         score=0.4,
                         at=f"2026-04-{i+10:02d}T00:00:00Z")
            out = agent_quality.quality_drift(window=5)
            scout = out["by_agent"]["scout"]
            self.assertEqual(scout["direction"], "declining")
            self.assertLess(scout["delta_mean"], -0.4)

    def test_improving_trend_detected(self):
        with isolated_cache():
            db = _new_run_db("rid-up")
            for i in range(5):
                _insert(db, run_id="rid-up", agent="scout",
                         score=0.3,
                         at=f"2026-04-{i+1:02d}T00:00:00Z")
            for i in range(5):
                _insert(db, run_id="rid-up", agent="scout",
                         score=0.85,
                         at=f"2026-04-{i+10:02d}T00:00:00Z")
            out = agent_quality.quality_drift(window=5)
            scout = out["by_agent"]["scout"]
            self.assertEqual(scout["direction"], "improving")
            self.assertGreater(scout["delta_mean"], 0.4)

    def test_stable_trend_detected(self):
        with isolated_cache():
            db = _new_run_db("rid-s")
            for i in range(10):
                _insert(db, run_id="rid-s", agent="scout",
                         score=0.7 + (i * 0.001),
                         at=f"2026-04-{i+1:02d}T00:00:00Z")
            out = agent_quality.quality_drift(window=5)
            scout = out["by_agent"]["scout"]
            self.assertEqual(scout["direction"], "stable")

    def test_chronological_split(self):
        """Latest window must contain newest scores."""
        with isolated_cache():
            db = _new_run_db("rid-c")
            # Insert in random order
            scores_by_at = [
                ("2026-04-05", 0.5),
                ("2026-04-01", 0.3),
                ("2026-04-10", 0.9),
                ("2026-04-03", 0.4),
                ("2026-04-08", 0.7),
                ("2026-04-02", 0.35),
                ("2026-04-09", 0.85),
                ("2026-04-04", 0.45),
                ("2026-04-07", 0.6),
                ("2026-04-06", 0.55),
            ]
            for at, score in scores_by_at:
                _insert(db, run_id="rid-c", agent="scout",
                         score=score, at=f"{at}T00:00:00Z")
            out = agent_quality.quality_drift(window=5)
            scout = out["by_agent"]["scout"]
            # Latest 5: 04-06 to 04-10 → scores 0.55, 0.6, 0.7, 0.85, 0.9
            self.assertAlmostEqual(
                scout["latest_window"]["mean"], 0.72, places=2,
            )
            # Prior 5: 04-01 to 04-05 → 0.3, 0.35, 0.4, 0.45, 0.5
            self.assertAlmostEqual(
                scout["prior_window"]["mean"], 0.4, places=2,
            )

    def test_multiple_agents_independent(self):
        with isolated_cache():
            db = _new_run_db("rid-m")
            for i in range(10):
                _insert(db, run_id="rid-m", agent="scout",
                         score=0.9,
                         at=f"2026-04-{i+1:02d}T00:00:00Z")
                _insert(db, run_id="rid-m", agent="surveyor",
                         score=0.4,
                         at=f"2026-04-{i+1:02d}T00:00:00Z")
            out = agent_quality.quality_drift(window=5)
            self.assertIn("scout", out["by_agent"])
            self.assertIn("surveyor", out["by_agent"])


class CliTests(TestCase):
    def test_drift_subcommand(self):
        with isolated_cache():
            db = _new_run_db("rid-cli")
            for i in range(10):
                _insert(db, run_id="rid-cli", agent="scout",
                         score=0.7,
                         at=f"2026-04-{i+1:02d}T00:00:00Z")
            r = subprocess.run(
                [sys.executable, "-m", "lib.agent_quality",
                 "drift", "--window", "5"],
                capture_output=True, text=True, cwd=str(_REPO),
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            out = json.loads(r.stdout)
            self.assertIn("scout", out["by_agent"])
            self.assertEqual(out["window"], 5)


if __name__ == "__main__":
    raise SystemExit(run_tests(QualityDriftTests, CliTests))
