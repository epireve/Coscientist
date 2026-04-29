"""v0.170 — health extended (tree summary + thinking-trace coverage)."""
from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from lib import health, idea_tree, migrations
from lib.cache import run_db_path
from tests.harness import TestCase, isolated_cache, run_tests

_REPO = Path(__file__).resolve().parents[1]
SCHEMA = (_REPO / "lib" / "sqlite_schema.sql").read_text()


def _new_run_db(rid: str) -> Path:
    db = run_db_path(rid)
    con = sqlite3.connect(db)
    con.executescript(SCHEMA)
    con.close()
    migrations.ensure_current(db)
    return db


def _seed_run(db: Path, run_id: str) -> None:
    con = sqlite3.connect(db)
    try:
        con.execute(
            "INSERT OR IGNORE INTO runs (run_id, question, started_at) "
            "VALUES (?, ?, ?)",
            (run_id, "q", datetime.now(UTC).isoformat()),
        )
        con.commit()
    finally:
        con.close()


def _insert_hyp(db: Path, hyp_id: str, *, run_id: str,
                 parent: str | None = None,
                 elo: float = 1200.0,
                 thinking: str | None = None) -> None:
    con = sqlite3.connect(db)
    try:
        con.execute(
            "INSERT INTO hypotheses (hyp_id, run_id, agent_name, "
            "parent_hyp_id, statement, elo, thinking_log_json, "
            "created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (hyp_id, run_id, "agent", parent,
             f"stmt-{hyp_id}", elo, thinking,
             datetime.now(UTC).isoformat()),
        )
        con.commit()
    finally:
        con.close()


def _insert_match(db: Path, *, run_id: str,
                   hyp_a: str, hyp_b: str, winner: str) -> None:
    con = sqlite3.connect(db)
    try:
        con.execute(
            "INSERT INTO tournament_matches "
            "(run_id, hyp_a, hyp_b, winner, at) "
            "VALUES (?, ?, ?, ?, ?)",
            (run_id, hyp_a, hyp_b, winner,
             datetime.now(UTC).isoformat()),
        )
        con.commit()
    finally:
        con.close()


def _insert_attack(db: Path, *, n: int, n_with_trace: int) -> None:
    con = sqlite3.connect(db)
    try:
        for i in range(n):
            tlog = json.dumps([{"step": "x"}]) if i < n_with_trace else None
            con.execute(
                "INSERT INTO attack_findings "
                "(target_canonical_id, attack, severity, evidence, "
                "thinking_log_json, at) VALUES (?, ?, ?, ?, ?, ?)",
                (f"paper-{i}", "p-hacking", "minor", "ev",
                 tlog, datetime.now(UTC).isoformat()),
            )
        con.commit()
    finally:
        con.close()


class HealthExtendedTests(TestCase):
    def test_tree_summary_with_trees(self):
        with isolated_cache():
            db = _new_run_db("htr1")
            _seed_run(db, "htr1")
            _insert_hyp(db, "root", run_id="htr1", elo=1300.0)
            idea_tree.record_root_hypothesis(db, "root")
            _insert_hyp(db, "child", run_id="htr1",
                         parent="root", elo=1100.0)
            idea_tree.record_child_hypothesis(db, "root", "child")
            trees = health.trees_summary_across_runs()
            self.assertEqual(trees["n_trees_total"], 1)
            run_entry = trees["by_run"][0]
            self.assertEqual(run_entry["n_trees"], 1)
            top = run_entry["top_per_tree"][0]
            self.assertEqual(top["top_hyp_id"], "root")

    def test_tree_summary_empty(self):
        with isolated_cache():
            trees = health.trees_summary_across_runs()
            self.assertEqual(trees["n_trees_total"], 0)
            self.assertEqual(trees["by_run"], [])

    def test_pruned_count_detected(self):
        with isolated_cache():
            db = _new_run_db("htr2")
            _seed_run(db, "htr2")
            _insert_hyp(db, "a", run_id="htr2")
            _insert_hyp(db, "b", run_id="htr2")
            _insert_hyp(db, "c", run_id="htr2")
            _insert_match(db, run_id="htr2",
                           hyp_a="a", hyp_b="b", winner="a")
            _insert_match(db, run_id="htr2",
                           hyp_a="b", hyp_b="c", winner="b")
            # Now delete b (simulated prune).
            con = sqlite3.connect(db)
            con.execute("DELETE FROM hypotheses WHERE hyp_id='b'")
            con.commit()
            con.close()
            trees = health.trees_summary_across_runs()
            self.assertEqual(trees["n_pruned_total"], 1)

    def test_thinking_coverage_correct(self):
        with isolated_cache():
            db = _new_run_db("htr3")
            _seed_run(db, "htr3")
            # 4 of 10 attack findings have a trace -> 40%
            _insert_attack(db, n=10, n_with_trace=4)
            cov = health.thinking_coverage_across_runs()
            af = cov["by_table"]["attack_findings"]
            self.assertEqual(af["n_total"], 10)
            self.assertEqual(af["n_with_trace"], 4)
            self.assertAlmostEqual(af["coverage"], 0.4, places=3)

    def test_coverage_alert_below_threshold(self):
        with isolated_cache():
            db = _new_run_db("htr4")
            _seed_run(db, "htr4")
            _insert_attack(db, n=10, n_with_trace=2)  # 20%
            report = health.collect()
            alerts = health.evaluate_alerts(report)
            codes = [a["code"] for a in alerts]
            self.assertIn("thinking_coverage_low", codes)

    def test_coverage_alert_silent_above_threshold(self):
        with isolated_cache():
            db = _new_run_db("htr5")
            _seed_run(db, "htr5")
            _insert_attack(db, n=10, n_with_trace=8)  # 80%
            report = health.collect()
            alerts = health.evaluate_alerts(report)
            codes = [a["code"] for a in alerts]
            self.assertNotIn("thinking_coverage_low", codes)

    def test_coverage_alert_silent_few_rows(self):
        with isolated_cache():
            db = _new_run_db("htr6")
            _seed_run(db, "htr6")
            # Only 4 rows total, all empty trace — under min row floor.
            _insert_attack(db, n=4, n_with_trace=0)
            report = health.collect()
            alerts = health.evaluate_alerts(report)
            codes = [a["code"] for a in alerts]
            self.assertNotIn("thinking_coverage_low", codes)

    def test_md_and_json_include_new_sections(self):
        with isolated_cache():
            db = _new_run_db("htr7")
            _seed_run(db, "htr7")
            _insert_hyp(db, "root", run_id="htr7", elo=1300.0)
            idea_tree.record_root_hypothesis(db, "root")
            _insert_attack(db, n=10, n_with_trace=8)
            report = health.collect()
            md = health.render_md(report)
            self.assertIn("Tree tournaments", md)
            self.assertIn("Thinking-trace coverage", md)
            self.assertIn("attack_findings", md)
            # JSON path: collect() output is the json payload itself.
            self.assertIn("trees", report)
            self.assertIn("thinking", report)
            self.assertIn(
                "attack_findings",
                report["thinking"]["by_table"],
            )

    def test_existing_alerts_still_work(self):
        # Non-thinking, non-tree alerts should still fire as before.
        with isolated_cache():
            report = {
                "active": [], "stale": [{"a": 1}],
                "failed_spans_total": 0,
                "tool_latency": {"by_tool": {}},
                "quality": {"by_agent": {}},
            }
            alerts = health.evaluate_alerts(report)
            codes = [a["code"] for a in alerts]
            self.assertIn("stale_spans", codes)


if __name__ == "__main__":
    raise SystemExit(run_tests(HealthExtendedTests))
