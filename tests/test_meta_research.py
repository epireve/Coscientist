"""Tests for the meta-research skill."""
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
        "meta",
        _REPO_ROOT / ".claude/skills/meta-research/scripts/meta.py",
    )
    mod = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _make_project(cache: Path, pid: str, name="P", archived=None):
    proj = cache / "projects" / pid
    proj.mkdir(parents=True, exist_ok=True)
    db = proj / "project.db"
    con = sqlite3.connect(db)
    con.executescript("""
        CREATE TABLE IF NOT EXISTS projects (
            project_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            question TEXT,
            description TEXT,
            style_profile_path TEXT,
            calibration_path TEXT,
            zotero_collection TEXT,
            created_at TEXT NOT NULL,
            archived_at TEXT
        );
        CREATE TABLE IF NOT EXISTS artifact_index (
            artifact_id TEXT,
            kind TEXT,
            project_id TEXT,
            state TEXT,
            path TEXT,
            created_at TEXT,
            updated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS graph_nodes (
            node_id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            label TEXT NOT NULL,
            data_json TEXT,
            created_at TEXT NOT NULL
        );
    """)
    con.execute(
        "INSERT INTO projects (project_id, name, created_at, archived_at) VALUES (?, ?, ?, ?)",
        (pid, name, datetime.now(UTC).isoformat(), archived),
    )
    con.commit()
    con.close()
    return db


def _add_artifact(cache, pid, kind, state, created_at=None, updated_at=None, artifact_id=None):
    db = cache / "projects" / pid / "project.db"
    con = sqlite3.connect(db)
    now = datetime.now(UTC).isoformat()
    con.execute(
        "INSERT INTO artifact_index "
        "(artifact_id, kind, project_id, state, path, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (artifact_id or f"art_{kind}_{pid}", kind, pid, state, "/tmp",
         created_at or now, updated_at or now),
    )
    con.commit()
    con.close()


def _add_concept(cache, pid, label):
    db = cache / "projects" / pid / "project.db"
    con = sqlite3.connect(db)
    con.execute(
        "INSERT OR REPLACE INTO graph_nodes "
        "(node_id, kind, label, data_json, created_at) VALUES (?, ?, ?, ?, ?)",
        (f"concept:{pid}:{label}", "concept", label, None, datetime.now(UTC).isoformat()),
    )
    con.commit()
    con.close()


class TrajectoryTests(CoscientistTestCase):
    def test_trajectory_empty(self):
        with isolated_cache():
            mod = _load()
            import argparse, io, contextlib
            args = argparse.Namespace(years=5)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_trajectory(args)
            r = json.loads(buf.getvalue())
            self.assertEqual(r["total_manuscripts"], 0)

    def test_trajectory_counts_manuscripts(self):
        with isolated_cache() as cache:
            _make_project(cache, "p1")
            _add_artifact(cache, "p1", "manuscript", "drafted")
            _add_artifact(cache, "p1", "manuscript", "submitted")
            _add_artifact(cache, "p1", "manuscript", "published")
            mod = _load()
            import argparse, io, contextlib
            args = argparse.Namespace(years=5)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_trajectory(args)
            r = json.loads(buf.getvalue())
            self.assertEqual(r["total_manuscripts"], 3)

    def test_trajectory_excludes_old(self):
        with isolated_cache() as cache:
            _make_project(cache, "p1")
            old = (datetime.now(UTC) - timedelta(days=365 * 10)).isoformat()
            _add_artifact(cache, "p1", "manuscript", "published", created_at=old)
            mod = _load()
            import argparse, io, contextlib
            args = argparse.Namespace(years=5)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_trajectory(args)
            self.assertEqual(json.loads(buf.getvalue())["total_manuscripts"], 0)


class ConceptsTests(CoscientistTestCase):
    def test_concepts_no_overlap(self):
        with isolated_cache() as cache:
            _make_project(cache, "p1")
            _make_project(cache, "p2")
            _add_concept(cache, "p1", "concept-A")
            _add_concept(cache, "p2", "concept-B")
            mod = _load()
            import argparse, io, contextlib
            args = argparse.Namespace(min_projects=2)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_concepts(args)
            self.assertEqual(json.loads(buf.getvalue())["total_shared"], 0)

    def test_concepts_finds_overlap(self):
        with isolated_cache() as cache:
            _make_project(cache, "p1")
            _make_project(cache, "p2")
            _make_project(cache, "p3")
            _add_concept(cache, "p1", "shared")
            _add_concept(cache, "p2", "shared")
            _add_concept(cache, "p3", "shared")
            _add_concept(cache, "p1", "p1-only")
            mod = _load()
            import argparse, io, contextlib
            args = argparse.Namespace(min_projects=2)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_concepts(args)
            r = json.loads(buf.getvalue())
            self.assertEqual(r["total_shared"], 1)
            self.assertEqual(r["shared_concepts"][0]["concept"], "shared")
            self.assertEqual(r["shared_concepts"][0]["project_count"], 3)

    def test_concepts_min_projects_filter(self):
        with isolated_cache() as cache:
            _make_project(cache, "p1")
            _make_project(cache, "p2")
            _add_concept(cache, "p1", "two-projects")
            _add_concept(cache, "p2", "two-projects")
            mod = _load()
            import argparse, io, contextlib
            args = argparse.Namespace(min_projects=3)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_concepts(args)
            self.assertEqual(json.loads(buf.getvalue())["total_shared"], 0)


class ProductivityTests(CoscientistTestCase):
    def test_productivity_lists_projects(self):
        with isolated_cache() as cache:
            _make_project(cache, "p1", name="Project One")
            _add_artifact(cache, "p1", "paper", "read")
            _add_artifact(cache, "p1", "manuscript", "drafted")
            mod = _load()
            import argparse, io, contextlib
            args = argparse.Namespace(include_archived=False)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_productivity(args)
            r = json.loads(buf.getvalue())
            self.assertEqual(r["total"], 1)
            self.assertEqual(r["projects"][0]["total_artifacts"], 2)

    def test_productivity_excludes_archived_by_default(self):
        with isolated_cache() as cache:
            _make_project(cache, "p1", archived=datetime.now(UTC).isoformat())
            _make_project(cache, "p2")
            mod = _load()
            import argparse, io, contextlib
            args = argparse.Namespace(include_archived=False)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_productivity(args)
            r = json.loads(buf.getvalue())
            self.assertEqual(r["total"], 1)

    def test_productivity_includes_archived_with_flag(self):
        with isolated_cache() as cache:
            _make_project(cache, "p1", archived=datetime.now(UTC).isoformat())
            _make_project(cache, "p2")
            mod = _load()
            import argparse, io, contextlib
            args = argparse.Namespace(include_archived=True)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_productivity(args)
            r = json.loads(buf.getvalue())
            self.assertEqual(r["total"], 2)


class SummaryTests(CoscientistTestCase):
    def test_summary_combines_all(self):
        with isolated_cache() as cache:
            _make_project(cache, "p1")
            _add_artifact(cache, "p1", "manuscript", "submitted")
            _add_concept(cache, "p1", "topic")
            mod = _load()
            import argparse, io, contextlib
            args = argparse.Namespace(years=5, format="json")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_summary(args)
            r = json.loads(buf.getvalue())
            self.assertIn("trajectory", r)
            self.assertIn("concepts", r)
            self.assertIn("productivity", r)
            self.assertIn("active_project_id", r)

    def test_summary_md_format(self):
        with isolated_cache() as cache:
            _make_project(cache, "p1", name="MD Test")
            _add_artifact(cache, "p1", "manuscript", "published")
            mod = _load()
            import argparse, io, contextlib
            args = argparse.Namespace(years=5, format="md")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_summary(args)
            output = buf.getvalue()
            self.assertIn("# Meta-research Summary", output)
            self.assertIn("MD Test", output)


class ReadOnlyContractTests(CoscientistTestCase):
    def test_does_not_modify_db(self):
        with isolated_cache() as cache:
            db = _make_project(cache, "p1")
            _add_artifact(cache, "p1", "manuscript", "drafted")
            mtime_before = db.stat().st_mtime
            mod = _load()
            import argparse, io, contextlib
            args = argparse.Namespace(years=5)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_trajectory(args)
            self.assertEqual(mtime_before, db.stat().st_mtime)
