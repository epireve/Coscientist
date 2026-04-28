"""Schema smoke tests."""

import sqlite3
from pathlib import Path

from tests import _shim  # noqa: F401
from tests.harness import TestCase, run_tests

SCHEMA = Path(__file__).resolve().parent.parent / "lib" / "sqlite_schema.sql"


class SchemaTests(TestCase):
    def _fresh(self) -> sqlite3.Connection:
        con = sqlite3.connect(":memory:")
        con.executescript(SCHEMA.read_text())
        con.row_factory = sqlite3.Row
        return con

    def test_loads_without_error(self):
        self._fresh()

    def test_deep_research_tables_present(self):
        con = self._fresh()
        names = {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )}
        for t in ["runs", "phases", "agents", "queries", "papers_in_run",
                  "claims", "citations", "breaks", "notes", "artifacts", "audit"]:
            self.assertIn(t, names, "deep-research table missing")

    def test_a5_tables_present(self):
        con = self._fresh()
        names = {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        for t in ["novelty_assessments", "publishability_verdicts",
                  "attack_findings", "hypotheses", "tournament_matches"]:
            self.assertIn(t, names, "A5 table missing")

    def test_refactor_tables_present(self):
        con = self._fresh()
        names = {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        for t in ["projects", "artifact_index", "graph_nodes", "graph_edges"]:
            self.assertIn(t, names, "refactor table missing")

    def test_runs_has_project_id_column(self):
        con = self._fresh()
        cols = {r[1] for r in con.execute("PRAGMA table_info(runs)")}
        self.assertIn("project_id", cols, "runs.project_id missing")

    def test_hypotheses_has_elo(self):
        con = self._fresh()
        cols = {r[1] for r in con.execute("PRAGMA table_info(hypotheses)")}
        for col in ["elo", "n_matches", "n_wins", "parent_hyp_id"]:
            self.assertIn(col, cols, f"hypotheses.{col} missing")

    def test_indexes_present(self):
        con = self._fresh()
        idx = {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        )}
        for needed in ["idx_phases_run", "idx_novelty_target",
                       "idx_publish_ms", "idx_hyp_elo", "idx_edges_from"]:
            self.assertIn(needed, idx)

    def test_foreign_keys_enforced(self):
        con = self._fresh()
        con.execute("PRAGMA foreign_keys=ON")
        # inserting a phase for a non-existent run should fail
        with self.assertRaises(sqlite3.IntegrityError):
            con.execute(
                "INSERT INTO phases (run_id, name, ordinal) VALUES (?, ?, ?)",
                ("nope", "social", 0),
            )


if __name__ == "__main__":
    import sys
    sys.exit(run_tests(SchemaTests))
