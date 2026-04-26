"""Tests for field-trends-analyzer skill."""
from __future__ import annotations

import importlib.util as _ilu
import json
import sqlite3
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))

from tests.harness import CoscientistTestCase, isolated_cache  # noqa


def _load():
    spec = _ilu.spec_from_file_location(
        "trends",
        _REPO_ROOT / ".claude/skills/field-trends-analyzer/scripts/trends.py",
    )
    mod = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _make_graph(cache: Path, project_id: str) -> Path:
    proj = cache / "projects" / project_id
    proj.mkdir(parents=True, exist_ok=True)
    db = proj / "project.db"
    con = sqlite3.connect(db)
    con.executescript("""
        CREATE TABLE IF NOT EXISTS graph_nodes (
            node_id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            label TEXT NOT NULL,
            data_json TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS graph_edges (
            edge_id INTEGER PRIMARY KEY AUTOINCREMENT,
            from_node TEXT NOT NULL,
            to_node TEXT NOT NULL,
            relation TEXT NOT NULL,
            weight REAL DEFAULT 1.0,
            data_json TEXT,
            created_at TEXT NOT NULL
        );
    """)
    con.close()
    return db


def _add_node(cache: Path, pid: str, node_id: str, kind: str, label: str, ts=None):
    db = cache / "projects" / pid / "project.db"
    con = sqlite3.connect(db)
    con.execute(
        "INSERT OR REPLACE INTO graph_nodes "
        "(node_id, kind, label, data_json, created_at) VALUES (?, ?, ?, ?, ?)",
        (node_id, kind, label, None, ts or datetime.now(UTC).isoformat()),
    )
    con.commit()
    con.close()


def _add_edge(cache: Path, pid: str, from_node: str, to_node: str, relation: str):
    db = cache / "projects" / pid / "project.db"
    con = sqlite3.connect(db)
    con.execute(
        "INSERT INTO graph_edges "
        "(from_node, to_node, relation, weight, data_json, created_at) "
        "VALUES (?, ?, ?, 1.0, NULL, ?)",
        (from_node, to_node, relation, datetime.now(UTC).isoformat()),
    )
    con.commit()
    con.close()


class ConceptsTests(CoscientistTestCase):
    def test_concepts_empty(self):
        with isolated_cache() as cache:
            _make_graph(cache, "p1")
            mod = _load()
            import argparse, io, contextlib
            args = argparse.Namespace(project_id="p1", top=20)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_concepts(args)
            self.assertEqual(json.loads(buf.getvalue())["concepts"], [])

    def test_concepts_ranked_by_paper_count(self):
        with isolated_cache() as cache:
            _make_graph(cache, "p1")
            _add_node(cache, "p1", "concept:transformers", "concept", "transformers")
            _add_node(cache, "p1", "concept:rl", "concept", "reinforcement-learning")
            _add_node(cache, "p1", "paper:a", "paper", "Paper A")
            _add_node(cache, "p1", "paper:b", "paper", "Paper B")
            _add_node(cache, "p1", "paper:c", "paper", "Paper C")
            _add_edge(cache, "p1", "paper:a", "concept:transformers", "about")
            _add_edge(cache, "p1", "paper:b", "concept:transformers", "about")
            _add_edge(cache, "p1", "paper:c", "concept:rl", "about")
            mod = _load()
            import argparse, io, contextlib
            args = argparse.Namespace(project_id="p1", top=10)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_concepts(args)
            r = json.loads(buf.getvalue())
            self.assertEqual(r["concepts"][0]["concept"], "transformers")
            self.assertEqual(r["concepts"][0]["paper_count"], 2)


class PapersTests(CoscientistTestCase):
    def test_papers_in_degree(self):
        with isolated_cache() as cache:
            _make_graph(cache, "p1")
            _add_node(cache, "p1", "paper:cited", "paper", "Highly Cited")
            _add_node(cache, "p1", "paper:a", "paper", "A")
            _add_node(cache, "p1", "paper:b", "paper", "B")
            _add_edge(cache, "p1", "paper:a", "paper:cited", "cites")
            _add_edge(cache, "p1", "paper:b", "paper:cited", "cites")
            mod = _load()
            import argparse, io, contextlib
            args = argparse.Namespace(project_id="p1", top=10)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_papers(args)
            r = json.loads(buf.getvalue())
            top = r["papers"][0]
            self.assertEqual(top["label"], "Highly Cited")
            self.assertEqual(top["in_degree"], 2)


class AuthorsTests(CoscientistTestCase):
    def test_authors_paper_count(self):
        with isolated_cache() as cache:
            _make_graph(cache, "p1")
            _add_node(cache, "p1", "author:smith", "author", "Smith")
            _add_node(cache, "p1", "paper:a", "paper", "A")
            _add_node(cache, "p1", "paper:b", "paper", "B")
            _add_edge(cache, "p1", "paper:a", "author:smith", "authored-by")
            _add_edge(cache, "p1", "paper:b", "author:smith", "authored-by")
            mod = _load()
            import argparse, io, contextlib
            args = argparse.Namespace(project_id="p1", top=10)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_authors(args)
            r = json.loads(buf.getvalue())
            self.assertEqual(r["authors"][0]["paper_count"], 2)


class MomentumTests(CoscientistTestCase):
    def test_momentum_rising(self):
        with isolated_cache() as cache:
            _make_graph(cache, "p1")
            now = datetime.now(UTC)
            recent_ts = (now - timedelta(days=10)).isoformat()
            past_ts = (now - timedelta(days=200)).isoformat()
            _add_node(cache, "p1", "concept:c1", "concept", "rising-topic")
            # 3 recent papers, 1 past
            _add_node(cache, "p1", "paper:r1", "paper", "R1", ts=recent_ts)
            _add_node(cache, "p1", "paper:r2", "paper", "R2", ts=recent_ts)
            _add_node(cache, "p1", "paper:r3", "paper", "R3", ts=recent_ts)
            _add_node(cache, "p1", "paper:p1", "paper", "P1", ts=past_ts)
            _add_edge(cache, "p1", "paper:r1", "concept:c1", "about")
            _add_edge(cache, "p1", "paper:r2", "concept:c1", "about")
            _add_edge(cache, "p1", "paper:r3", "concept:c1", "about")
            _add_edge(cache, "p1", "paper:p1", "concept:c1", "about")
            mod = _load()
            import argparse, io, contextlib
            args = argparse.Namespace(
                project_id="p1", window_recent=90, window_past=365, top=10
            )
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_momentum(args)
            r = json.loads(buf.getvalue())
            self.assertEqual(len(r["concepts"]), 1)
            c = r["concepts"][0]
            self.assertEqual(c["recent_count"], 3)
            self.assertEqual(c["past_count"], 1)
            self.assertEqual(c["verdict"], "rising")

    def test_momentum_no_data(self):
        with isolated_cache() as cache:
            _make_graph(cache, "p1")
            mod = _load()
            import argparse, io, contextlib
            args = argparse.Namespace(
                project_id="p1", window_recent=90, window_past=365, top=10
            )
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_momentum(args)
            self.assertEqual(json.loads(buf.getvalue())["concepts"], [])


class SummaryTests(CoscientistTestCase):
    def test_summary_counts(self):
        with isolated_cache() as cache:
            _make_graph(cache, "p1")
            _add_node(cache, "p1", "paper:a", "paper", "A")
            _add_node(cache, "p1", "paper:b", "paper", "B")
            _add_node(cache, "p1", "concept:c", "concept", "C")
            _add_node(cache, "p1", "author:s", "author", "Smith")
            _add_edge(cache, "p1", "paper:a", "paper:b", "cites")
            mod = _load()
            import argparse, io, contextlib
            args = argparse.Namespace(project_id="p1")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_summary(args)
            r = json.loads(buf.getvalue())
            self.assertEqual(r["node_counts"]["paper"], 2)
            self.assertEqual(r["node_counts"]["concept"], 1)
            self.assertEqual(r["node_counts"]["author"], 1)
            self.assertEqual(r["edge_count"], 1)

    def test_no_db_raises(self):
        with isolated_cache():
            mod = _load()
            import argparse
            args = argparse.Namespace(project_id="nonexistent")
            with self.assertRaises(SystemExit):
                mod.cmd_summary(args)


class ReadOnlyTests(CoscientistTestCase):
    def test_read_only_no_modification(self):
        with isolated_cache() as cache:
            db = _make_graph(cache, "p1")
            _add_node(cache, "p1", "concept:x", "concept", "X")
            mtime_before = db.stat().st_mtime
            mod = _load()
            import argparse, io, contextlib
            args = argparse.Namespace(project_id="p1", top=20)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_concepts(args)
            self.assertEqual(mtime_before, db.stat().st_mtime)
