"""v0.156 — record_hypothesis tree-positioning flags."""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from lib.cache import run_db_path
from tests.harness import TestCase, isolated_cache, run_tests

_REPO = Path(__file__).resolve().parents[1]
_SCRIPT = (_REPO / ".claude" / "skills" / "tournament"
           / "scripts" / "record_hypothesis.py")


def _init_run(rid: str = "r1") -> Path:
    """Make a run DB with hypotheses table populated by base schema +
    v14 tree columns. Mirrors how db.py init scaffolds."""
    db = run_db_path(rid)
    db.parent.mkdir(parents=True, exist_ok=True)
    schema = (_REPO / "lib" / "sqlite_schema.sql").read_text()
    con = sqlite3.connect(db)
    con.executescript(schema)
    # runs row needed by FK
    con.execute(
        "INSERT INTO runs (run_id, question, started_at, status) "
        "VALUES (?, ?, ?, ?)",
        (rid, "q", "now", "running"),
    )
    con.commit()
    con.close()
    return db


def _run_script(*args: str) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["COSCIENTIST_CACHE_DIR"] = os.environ.get(
        "COSCIENTIST_CACHE_DIR", "")
    return subprocess.run(
        [sys.executable, str(_SCRIPT), *args],
        capture_output=True, text=True, cwd=str(_REPO), env=env,
    )


class TreeRootTests(TestCase):
    def test_tree_root_stamps_columns(self):
        with isolated_cache():
            _init_run()
            r = _run_script(
                "--run-id", "r1", "--agent-name", "architect",
                "--hyp-id", "hyp-1", "--tree-root",
                "--statement", "root claim",
            )
            self.assertEqual(r.returncode, 0, msg=r.stderr)
            out = json.loads(r.stdout)
            self.assertEqual(out["tree_id"], "hyp-1")
            self.assertEqual(out["depth"], 0)
            self.assertEqual(out["branch_index"], 0)


class ParentChildTests(TestCase):
    def test_child_inherits_tree_id_and_depth(self):
        with isolated_cache():
            _init_run()
            _run_script(
                "--run-id", "r1", "--agent-name", "architect",
                "--hyp-id", "hyp-root", "--tree-root",
                "--statement", "root",
            )
            r = _run_script(
                "--run-id", "r1", "--agent-name", "architect",
                "--hyp-id", "hyp-c1", "--parent-hyp-id", "hyp-root",
                "--statement", "child",
            )
            self.assertEqual(r.returncode, 0, msg=r.stderr)
            out = json.loads(r.stdout)
            self.assertEqual(out["tree_id"], "hyp-root")
            self.assertEqual(out["depth"], 1)

    def test_branch_index_override(self):
        with isolated_cache():
            _init_run()
            _run_script(
                "--run-id", "r1", "--agent-name", "architect",
                "--hyp-id", "hyp-r", "--tree-root",
                "--statement", "root",
            )
            r = _run_script(
                "--run-id", "r1", "--agent-name", "architect",
                "--hyp-id", "hyp-c", "--parent-hyp-id", "hyp-r",
                "--branch-index", "5",
                "--statement", "child",
            )
            self.assertEqual(r.returncode, 0)
            out = json.loads(r.stdout)
            self.assertEqual(out["branch_index"], 5)


class MutualExclusionTests(TestCase):
    def test_root_and_parent_rejected(self):
        with isolated_cache():
            _init_run()
            r = _run_script(
                "--run-id", "r1", "--agent-name", "architect",
                "--hyp-id", "hyp-x", "--tree-root",
                "--parent-hyp-id", "hyp-other",
                "--statement", "x",
            )
            self.assertTrue(r.returncode != 0)
            self.assertIn("mutually exclusive", r.stderr)


class FlatBackcompatTests(TestCase):
    def test_no_flags_leaves_tree_columns_null(self):
        with isolated_cache():
            db = _init_run()
            r = _run_script(
                "--run-id", "r1", "--agent-name", "theorist",
                "--hyp-id", "hyp-flat",
                "--statement", "flat insert",
            )
            self.assertEqual(r.returncode, 0, msg=r.stderr)
            out = json.loads(r.stdout)
            self.assertNotIn("tree_id", out)
            con = sqlite3.connect(db)
            row = con.execute(
                "SELECT tree_id, depth, branch_index "
                "FROM hypotheses WHERE hyp_id=?", ("hyp-flat",),
            ).fetchone()
            con.close()
            self.assertEqual(row[0], None)


class AgentChoicesTests(TestCase):
    def test_architect_visionary_mutator_accepted(self):
        for name in ("architect", "visionary", "mutator",
                     "idea-tree-generator"):
            with isolated_cache():
                _init_run()
                r = _run_script(
                    "--run-id", "r1", "--agent-name", name,
                    "--hyp-id", f"hyp-{name}", "--tree-root",
                    "--statement", "x",
                )
                self.assertEqual(r.returncode, 0,
                                 msg=f"{name} rejected: {r.stderr}")


if __name__ == "__main__":
    raise SystemExit(run_tests(
        TreeRootTests, ParentChildTests, MutualExclusionTests,
        FlatBackcompatTests, AgentChoicesTests,
    ))
