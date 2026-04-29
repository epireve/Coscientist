"""v0.171 — tree-viz mermaid renderer tests."""
from __future__ import annotations

import sqlite3
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from lib import idea_tree, migrations, tree_viz
from lib.cache import run_db_path
from tests.harness import TestCase, isolated_cache, run_tests

_ROOT = Path(__file__).resolve().parent.parent
SCHEMA = (_ROOT / "lib" / "sqlite_schema.sql").read_text()


def _build_run_db(run_id: str = "tv_test") -> Path:
    db = run_db_path(run_id)
    db.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db)
    con.executescript(SCHEMA)
    con.close()
    migrations.ensure_current(db)
    return db


def _insert_hyp(db: Path, hyp_id: str, *, parent: str | None = None,
                run_id: str = "tv_test", elo: float = 1200.0) -> None:
    con = sqlite3.connect(db)
    try:
        con.execute(
            "INSERT OR IGNORE INTO runs (run_id, question, started_at) "
            "VALUES (?, ?, ?)",
            (run_id, "q", datetime.now(UTC).isoformat()),
        )
        con.execute(
            "INSERT INTO hypotheses (hyp_id, run_id, agent_name, "
            "parent_hyp_id, statement, elo, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (hyp_id, run_id, "agent", parent,
             f"stmt-{hyp_id}", elo,
             datetime.now(UTC).isoformat()),
        )
        con.commit()
    finally:
        con.close()


class TreeVizTests(TestCase):
    def test_single_root_renders(self):
        with isolated_cache():
            db = _build_run_db()
            _insert_hyp(db, "root", elo=1250.0)
            idea_tree.record_root_hypothesis(db, "root")
            out = tree_viz.render_tree(db, "root")
            self.assertIn("```mermaid", out)
            self.assertIn("graph TD", out)
            self.assertIn("root", out)
            self.assertIn("Elo 1250", out)

    def test_multibranch_edges(self):
        with isolated_cache():
            db = _build_run_db()
            _insert_hyp(db, "root", elo=1250.0)
            idea_tree.record_root_hypothesis(db, "root")
            _insert_hyp(db, "A", parent="root", elo=1300.0)
            idea_tree.record_child_hypothesis(db, "root", "A")
            _insert_hyp(db, "B", parent="root", elo=1100.0)
            idea_tree.record_child_hypothesis(db, "root", "B")
            out = tree_viz.render_tree(db, "root")
            # Two edges from root.
            edge_count = out.count("-->")
            self.assertEqual(edge_count, 2)

    def test_missing_tree_error(self):
        with isolated_cache():
            db = _build_run_db()
            out = tree_viz.render_tree(db, "no-such-tree")
            self.assertIn("error", out)
            self.assertIn("not found", out)

    def test_missing_db_error(self):
        out = tree_viz.render_tree(Path("/nonexistent/x.db"), "t")
        self.assertIn("error", out)

    def test_elo_color_classes(self):
        with isolated_cache():
            db = _build_run_db()
            _insert_hyp(db, "root", elo=1250.0)  # mid
            idea_tree.record_root_hypothesis(db, "root")
            _insert_hyp(db, "high", parent="root", elo=1400.0)  # green
            idea_tree.record_child_hypothesis(db, "root", "high")
            _insert_hyp(db, "low", parent="root", elo=900.0)  # red
            idea_tree.record_child_hypothesis(db, "root", "low")
            out = tree_viz.render_tree(db, "root")
            self.assertIn(":::elo_high", out)
            self.assertIn(":::elo_low", out)
            self.assertIn(":::elo_mid", out)
            self.assertIn("classDef elo_high", out)
            self.assertIn("classDef elo_low", out)

    def test_cli_outputs_mermaid_block(self):
        with isolated_cache():
            db = _build_run_db()
            _insert_hyp(db, "root", elo=1200.0)
            idea_tree.record_root_hypothesis(db, "root")
            r = subprocess.run(
                [sys.executable, "-m", "lib.tree_viz",
                 "--run-db", str(db), "--tree-id", "root"],
                cwd=str(_ROOT),
                capture_output=True, text=True,
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("```mermaid", r.stdout)
            self.assertIn("graph TD", r.stdout)

    def test_cli_help(self):
        r = subprocess.run(
            [sys.executable, "-m", "lib.tree_viz", "--help"],
            cwd=str(_ROOT),
            capture_output=True, text=True,
        )
        self.assertEqual(r.returncode, 0)
        self.assertIn("--run-db", r.stdout)
        self.assertIn("--tree-id", r.stdout)


if __name__ == "__main__":
    raise SystemExit(run_tests(TreeVizTests))
