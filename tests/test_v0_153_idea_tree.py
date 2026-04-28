"""v0.153 — schema migration v14 + idea-tree helpers + agent persona."""
from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from lib import idea_tree, migrations
from lib.cache import cache_root, run_db_path
from tests.harness import TestCase, isolated_cache, run_tests

_ROOT = Path(__file__).resolve().parent.parent
SCHEMA = (_ROOT / "lib" / "sqlite_schema.sql").read_text()
AGENT_FILE = _ROOT / ".claude" / "agents" / "idea-tree-generator.md"


def _build_run_db(run_id: str = "tree_test") -> Path:
    """Create a fresh run DB with the base schema applied + migrations
    forward. Returns its path."""
    db = run_db_path(run_id)
    db.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db)
    con.executescript(SCHEMA)
    con.close()
    migrations.ensure_current(db)
    return db


def _insert_hyp(db: Path, hyp_id: str, *, parent: str | None = None,
                run_id: str = "tree_test", agent: str = "idea-tree-generator",
                statement: str = "stmt") -> None:
    con = sqlite3.connect(db)
    try:
        con.execute(
            "INSERT INTO hypotheses (hyp_id, run_id, agent_name, "
            "parent_hyp_id, statement, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (hyp_id, run_id, agent, parent, statement,
             datetime.now(UTC).isoformat()),
        )
        # Insert run row to satisfy FK (runs.run_id PK)
        con.execute(
            "INSERT OR IGNORE INTO runs (run_id, question, started_at) "
            "VALUES (?, ?, ?)",
            (run_id, "q", datetime.now(UTC).isoformat()),
        )
        con.commit()
    finally:
        con.close()


class MigrationV14Tests(TestCase):
    def test_v14_in_all_versions(self):
        self.assertIn(14, migrations.ALL_VERSIONS)

    def test_v14_sql_file_exists(self):
        sql_dir = Path(migrations.__file__).parent / "migrations_sql"
        self.assertTrue((sql_dir / "v14.sql").exists())

    def test_v14_applies_when_hypotheses_exists(self):
        with isolated_cache():
            db = _build_run_db()
            applied = migrations.applied_versions(db)
            self.assertIn(14, applied)

    def test_v14_skipped_for_db_without_hypotheses(self):
        with isolated_cache():
            tmp = cache_root() / "no_hyp.db"
            tmp.parent.mkdir(parents=True, exist_ok=True)
            con = sqlite3.connect(tmp)
            con.execute("CREATE TABLE other (x INTEGER)")
            con.commit()
            con.close()
            applied = migrations.ensure_current(tmp, migrations=[])
            self.assertNotIn(14, applied)

    def test_v14_columns_added(self):
        with isolated_cache():
            db = _build_run_db()
            con = sqlite3.connect(db)
            cols = [r[1] for r in con.execute(
                "PRAGMA table_info(hypotheses)"
            )]
            con.close()
            self.assertIn("tree_id", cols)
            self.assertIn("depth", cols)
            self.assertIn("branch_index", cols)

    def test_v14_index_exists(self):
        with isolated_cache():
            db = _build_run_db()
            con = sqlite3.connect(db)
            row = con.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='index' AND name='idx_hypotheses_tree_depth'"
            ).fetchone()
            con.close()
            self.assertIsNotNone(row)


class RecordRootTests(TestCase):
    def test_record_root_assigns_tree_id_and_depth(self):
        with isolated_cache():
            db = _build_run_db()
            _insert_hyp(db, "h1")
            tree_id = idea_tree.record_root_hypothesis(db, "h1")
            self.assertEqual(tree_id, "h1")
            con = sqlite3.connect(db)
            row = con.execute(
                "SELECT tree_id, depth, branch_index FROM hypotheses "
                "WHERE hyp_id='h1'"
            ).fetchone()
            con.close()
            self.assertEqual(row[0], "h1")
            self.assertEqual(row[1], 0)
            self.assertEqual(row[2], 0)


class RecordChildTests(TestCase):
    def test_child_inherits_tree_increments_depth(self):
        with isolated_cache():
            db = _build_run_db()
            _insert_hyp(db, "root")
            idea_tree.record_root_hypothesis(db, "root")
            _insert_hyp(db, "c1", parent="root")
            idea_tree.record_child_hypothesis(db, "root", "c1")
            con = sqlite3.connect(db)
            row = con.execute(
                "SELECT tree_id, depth, branch_index FROM hypotheses "
                "WHERE hyp_id='c1'"
            ).fetchone()
            con.close()
            self.assertEqual(row[0], "root")
            self.assertEqual(row[1], 1)
            self.assertEqual(row[2], 0)

    def test_sibling_branch_index_increments(self):
        with isolated_cache():
            db = _build_run_db()
            _insert_hyp(db, "root")
            idea_tree.record_root_hypothesis(db, "root")
            for i, hid in enumerate(["c0", "c1", "c2"]):
                _insert_hyp(db, hid, parent="root")
                idea_tree.record_child_hypothesis(db, "root", hid)
            con = sqlite3.connect(db)
            rows = con.execute(
                "SELECT hyp_id, branch_index FROM hypotheses "
                "WHERE parent_hyp_id='root' ORDER BY branch_index"
            ).fetchall()
            con.close()
            self.assertEqual(rows, [("c0", 0), ("c1", 1), ("c2", 2)])

    def test_grandchild_depth_two(self):
        with isolated_cache():
            db = _build_run_db()
            _insert_hyp(db, "root")
            idea_tree.record_root_hypothesis(db, "root")
            _insert_hyp(db, "c0", parent="root")
            idea_tree.record_child_hypothesis(db, "root", "c0")
            _insert_hyp(db, "g0", parent="c0")
            idea_tree.record_child_hypothesis(db, "c0", "g0")
            con = sqlite3.connect(db)
            row = con.execute(
                "SELECT tree_id, depth FROM hypotheses WHERE hyp_id='g0'"
            ).fetchone()
            con.close()
            self.assertEqual(row[0], "root")
            self.assertEqual(row[1], 2)

    def test_missing_parent_raises(self):
        with isolated_cache():
            db = _build_run_db()
            _insert_hyp(db, "orphan", parent="nope")
            try:
                idea_tree.record_child_hypothesis(db, "nope", "orphan")
            except ValueError:
                return
            self.fail("expected ValueError for missing parent")


class GetTreeTests(TestCase):
    def test_get_tree_returns_ordered_nodes(self):
        with isolated_cache():
            db = _build_run_db()
            _insert_hyp(db, "root")
            idea_tree.record_root_hypothesis(db, "root")
            _insert_hyp(db, "b", parent="root")
            idea_tree.record_child_hypothesis(db, "root", "b")
            _insert_hyp(db, "a", parent="root")
            idea_tree.record_child_hypothesis(db, "root", "a")
            _insert_hyp(db, "g", parent="b")
            idea_tree.record_child_hypothesis(db, "b", "g")
            tree = idea_tree.get_tree(db, "root")
            ids_in_order = [n["hyp_id"] for n in tree]
            self.assertEqual(ids_in_order[0], "root")
            # depth 1 nodes precede depth 2 nodes
            depths = [n["depth"] for n in tree]
            self.assertEqual(depths, sorted(depths))

    def test_get_tree_empty_for_missing_id(self):
        with isolated_cache():
            db = _build_run_db()
            self.assertEqual(idea_tree.get_tree(db, "nope"), [])


class GetSubtreeTests(TestCase):
    def test_subtree_bfs(self):
        with isolated_cache():
            db = _build_run_db()
            _insert_hyp(db, "root")
            idea_tree.record_root_hypothesis(db, "root")
            _insert_hyp(db, "b1", parent="root")
            idea_tree.record_child_hypothesis(db, "root", "b1")
            _insert_hyp(db, "b2", parent="root")
            idea_tree.record_child_hypothesis(db, "root", "b2")
            _insert_hyp(db, "g11", parent="b1")
            idea_tree.record_child_hypothesis(db, "b1", "g11")
            sub = idea_tree.get_subtree(db, "b1")
            ids = [n["hyp_id"] for n in sub]
            self.assertEqual(ids[0], "b1")
            self.assertIn("g11", ids)
            self.assertNotIn("root", ids)
            self.assertNotIn("b2", ids)


class PruneSubtreeTests(TestCase):
    def test_prune_removes_subtree(self):
        with isolated_cache():
            db = _build_run_db()
            _insert_hyp(db, "root")
            idea_tree.record_root_hypothesis(db, "root")
            _insert_hyp(db, "b1", parent="root")
            idea_tree.record_child_hypothesis(db, "root", "b1")
            _insert_hyp(db, "g11", parent="b1")
            idea_tree.record_child_hypothesis(db, "b1", "g11")
            _insert_hyp(db, "b2", parent="root")
            idea_tree.record_child_hypothesis(db, "root", "b2")
            n = idea_tree.prune_subtree(db, "b1")
            self.assertEqual(n, 2)  # b1 + g11
            con = sqlite3.connect(db)
            ids = [r[0] for r in con.execute(
                "SELECT hyp_id FROM hypotheses ORDER BY hyp_id"
            )]
            con.close()
            self.assertEqual(ids, ["b2", "root"])

    def test_prune_missing_returns_zero(self):
        with isolated_cache():
            db = _build_run_db()
            self.assertEqual(idea_tree.prune_subtree(db, "nope"), 0)


class AgentPersonaTests(TestCase):
    def test_agent_file_exists(self):
        self.assertTrue(AGENT_FILE.exists())

    def test_agent_frontmatter(self):
        text = AGENT_FILE.read_text()
        self.assertTrue(text.startswith("---\n"))
        # Required frontmatter keys
        self.assertIn("name: idea-tree-generator", text)
        self.assertIn("description:", text)
        self.assertIn("tools:", text)
        self.assertIn("model: claude-opus-4-7", text)
        # Body mentions key concepts
        self.assertIn("tree_id", text)
        self.assertIn("depth", text)
        self.assertIn("branch_index", text)


if __name__ == "__main__":
    raise SystemExit(run_tests(
        MigrationV14Tests,
        RecordRootTests,
        RecordChildTests,
        GetTreeTests,
        GetSubtreeTests,
        PruneSubtreeTests,
        AgentPersonaTests,
    ))
