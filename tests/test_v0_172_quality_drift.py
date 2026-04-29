"""v0.172 — quality drift CLI extensions (window/threshold/format)."""
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


def _seed_drop(db: Path, run_id: str, agent: str,
                prior: float, latest: float, n: int = 10):
    """n prior scores at `prior`, then n latest at `latest`."""
    for i in range(n):
        _insert(db, run_id=run_id, agent=agent, score=prior,
                 at=f"2026-04-{i+1:02d}T00:00:00Z")
    for i in range(n):
        _insert(db, run_id=run_id, agent=agent, score=latest,
                 at=f"2026-05-{i+1:02d}T00:00:00Z")


class QualityDriftCLITests(TestCase):
    def test_drift_detected_above_threshold(self):
        with isolated_cache():
            db = _new_run_db("d1")
            _seed_drop(db, "d1", "scout", prior=0.85, latest=0.55, n=10)
            out = agent_quality.quality_drift(
                window=10, threshold=0.1,
            )
            scout = out["by_agent"]["scout"]
            self.assertEqual(scout["direction"], "declining")
            self.assertTrue(scout["delta_mean"] < -0.1)

    def test_no_drift_when_stable(self):
        with isolated_cache():
            db = _new_run_db("d2")
            _seed_drop(db, "d2", "scout", prior=0.70, latest=0.71, n=10)
            out = agent_quality.quality_drift(
                window=10, threshold=0.1,
            )
            scout = out["by_agent"]["scout"]
            self.assertEqual(scout["direction"], "stable")

    def test_insufficient_below_window(self):
        with isolated_cache():
            db = _new_run_db("d3")
            for i in range(4):
                _insert(db, run_id="d3", agent="scout",
                         score=0.7,
                         at=f"2026-04-{i+1:02d}T00:00:00Z")
            out = agent_quality.quality_drift(
                window=10, threshold=0.1,
            )
            scout = out["by_agent"]["scout"]
            self.assertEqual(scout["direction"], "insufficient")

    def test_custom_window_override(self):
        with isolated_cache():
            db = _new_run_db("d4")
            # 6 points: 3 prior@0.9, 3 latest@0.4 — window=3 finds drift
            for i in range(3):
                _insert(db, run_id="d4", agent="scout",
                         score=0.9,
                         at=f"2026-04-{i+1:02d}T00:00:00Z")
            for i in range(3):
                _insert(db, run_id="d4", agent="scout",
                         score=0.4,
                         at=f"2026-05-{i+1:02d}T00:00:00Z")
            out = agent_quality.quality_drift(
                window=3, threshold=0.1,
            )
            scout = out["by_agent"]["scout"]
            self.assertEqual(scout["direction"], "declining")

    def test_custom_threshold_override(self):
        with isolated_cache():
            db = _new_run_db("d5")
            # Drop of 0.08 — should be 'declining' under 0.05
            # threshold but 'stable' under 0.1.
            _seed_drop(db, "d5", "scout",
                        prior=0.80, latest=0.72, n=10)
            out_low = agent_quality.quality_drift(
                window=10, threshold=0.05,
            )
            out_high = agent_quality.quality_drift(
                window=10, threshold=0.1,
            )
            self.assertEqual(
                out_low["by_agent"]["scout"]["direction"], "declining",
            )
            self.assertEqual(
                out_high["by_agent"]["scout"]["direction"], "stable",
            )

    def test_cli_format_json_and_text(self):
        with isolated_cache() as cache_root:
            db = _new_run_db("d6")
            _seed_drop(db, "d6", "scout",
                        prior=0.85, latest=0.55, n=10)
            runs_root = db.parent
            r_json = subprocess.run(
                [sys.executable, "-m", "lib.agent_quality", "drift",
                 "--root", str(runs_root),
                 "--window", "10", "--threshold", "0.1",
                 "--format", "json"],
                cwd=str(_REPO),
                capture_output=True, text=True,
            )
            self.assertEqual(r_json.returncode, 0, r_json.stderr)
            payload = json.loads(r_json.stdout)
            self.assertIn("by_agent", payload)
            self.assertIn("scout", payload["by_agent"])

            r_txt = subprocess.run(
                [sys.executable, "-m", "lib.agent_quality", "drift",
                 "--root", str(runs_root),
                 "--window", "10", "--threshold", "0.1",
                 "--format", "text"],
                cwd=str(_REPO),
                capture_output=True, text=True,
            )
            self.assertEqual(r_txt.returncode, 0, r_txt.stderr)
            self.assertIn("scout", r_txt.stdout)
            self.assertIn("declining", r_txt.stdout)


if __name__ == "__main__":
    raise SystemExit(run_tests(QualityDriftCLITests))
