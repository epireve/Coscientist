"""Tests for reading-pace-analytics skill."""
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
        "pace",
        _REPO_ROOT / ".claude/skills/reading-pace-analytics/scripts/pace.py",
    )
    mod = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _make_project_db(cache: Path, project_id: str) -> Path:
    proj_dir = cache / "projects" / project_id
    proj_dir.mkdir(parents=True, exist_ok=True)
    db_path = proj_dir / "project.db"
    con = sqlite3.connect(db_path)
    con.executescript("""
        CREATE TABLE IF NOT EXISTS reading_state (
            state_id     INTEGER PRIMARY KEY AUTOINCREMENT,
            canonical_id TEXT NOT NULL,
            project_id   TEXT,
            state        TEXT NOT NULL,
            notes        TEXT,
            updated_at   TEXT NOT NULL,
            UNIQUE(canonical_id, project_id)
        );
    """)
    con.close()
    return db_path


def _seed(cache: Path, project_id: str, rows: list[dict]) -> None:
    db = cache / "projects" / project_id / "project.db"
    con = sqlite3.connect(db)
    for r in rows:
        con.execute(
            "INSERT INTO reading_state "
            "(canonical_id, project_id, state, updated_at) VALUES (?, ?, ?, ?)",
            (r["canonical_id"], project_id, r["state"], r["updated_at"]),
        )
    con.commit()
    con.close()


def _iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.isoformat()


class VelocityTests(CoscientistTestCase):
    def test_velocity_empty(self):
        with isolated_cache():
            mod = _load()
            import argparse, io, contextlib
            args = argparse.Namespace(project_id=None, days=28)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_velocity(args)
            result = json.loads(buf.getvalue())
            self.assertEqual(result["papers_read_in_window"], 0)
            self.assertEqual(result["papers_per_week"], 0)

    def test_velocity_counts_recent_reads(self):
        with isolated_cache() as cache:
            _make_project_db(cache, "p1")
            now = datetime.now(UTC)
            _seed(cache, "p1", [
                {"canonical_id": "a", "state": "read",
                 "updated_at": _iso(now - timedelta(days=2))},
                {"canonical_id": "b", "state": "read",
                 "updated_at": _iso(now - timedelta(days=10))},
                {"canonical_id": "c", "state": "annotated",
                 "updated_at": _iso(now - timedelta(days=15))},
            ])
            mod = _load()
            import argparse, io, contextlib
            args = argparse.Namespace(project_id="p1", days=28)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_velocity(args)
            result = json.loads(buf.getvalue())
            self.assertEqual(result["papers_read_in_window"], 3)

    def test_velocity_excludes_old(self):
        with isolated_cache() as cache:
            _make_project_db(cache, "p2")
            now = datetime.now(UTC)
            _seed(cache, "p2", [
                {"canonical_id": "old", "state": "read",
                 "updated_at": _iso(now - timedelta(days=100))},
            ])
            mod = _load()
            import argparse, io, contextlib
            args = argparse.Namespace(project_id="p2", days=28)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_velocity(args)
            self.assertEqual(json.loads(buf.getvalue())["papers_read_in_window"], 0)

    def test_velocity_excludes_to_read(self):
        with isolated_cache() as cache:
            _make_project_db(cache, "p3")
            now = datetime.now(UTC)
            _seed(cache, "p3", [
                {"canonical_id": "x", "state": "to-read",
                 "updated_at": _iso(now - timedelta(days=1))},
            ])
            mod = _load()
            import argparse, io, contextlib
            args = argparse.Namespace(project_id="p3", days=28)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_velocity(args)
            self.assertEqual(json.loads(buf.getvalue())["papers_read_in_window"], 0)

    def test_velocity_global_aggregates_projects(self):
        with isolated_cache() as cache:
            _make_project_db(cache, "pa")
            _make_project_db(cache, "pb")
            now = datetime.now(UTC)
            recent = _iso(now - timedelta(days=2))
            _seed(cache, "pa", [{"canonical_id": "x", "state": "read", "updated_at": recent}])
            _seed(cache, "pb", [{"canonical_id": "y", "state": "read", "updated_at": recent}])
            mod = _load()
            import argparse, io, contextlib
            args = argparse.Namespace(project_id=None, days=28)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_velocity(args)
            self.assertEqual(json.loads(buf.getvalue())["papers_read_in_window"], 2)


class BacklogTests(CoscientistTestCase):
    def test_backlog_counts_per_state(self):
        with isolated_cache() as cache:
            _make_project_db(cache, "b1")
            now = datetime.now(UTC)
            _seed(cache, "b1", [
                {"canonical_id": "a", "state": "to-read", "updated_at": _iso(now)},
                {"canonical_id": "b", "state": "to-read", "updated_at": _iso(now)},
                {"canonical_id": "c", "state": "reading", "updated_at": _iso(now)},
                {"canonical_id": "d", "state": "read", "updated_at": _iso(now)},
            ])
            mod = _load()
            import argparse, io, contextlib
            args = argparse.Namespace(project_id="b1")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_backlog(args)
            result = json.loads(buf.getvalue())
            self.assertEqual(result["counts_by_state"]["to-read"], 2)
            self.assertEqual(result["counts_by_state"]["reading"], 1)
            self.assertEqual(result["counts_by_state"]["read"], 1)

    def test_backlog_untouched_count(self):
        with isolated_cache() as cache:
            _make_project_db(cache, "b2")
            now = datetime.now(UTC)
            _seed(cache, "b2", [
                {"canonical_id": "stale", "state": "to-read",
                 "updated_at": _iso(now - timedelta(days=60))},
                {"canonical_id": "fresh", "state": "to-read",
                 "updated_at": _iso(now - timedelta(days=5))},
            ])
            mod = _load()
            import argparse, io, contextlib
            args = argparse.Namespace(project_id="b2")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_backlog(args)
            result = json.loads(buf.getvalue())
            self.assertEqual(result["untouched_to_read_count"], 1)
            self.assertTrue(result["oldest_to_read_age_days"] >= 59)


class TrendTests(CoscientistTestCase):
    def test_trend_buckets_by_week(self):
        with isolated_cache() as cache:
            _make_project_db(cache, "t1")
            now = datetime.now(UTC)
            _seed(cache, "t1", [
                {"canonical_id": "w0_a", "state": "read", "updated_at": _iso(now - timedelta(days=2))},
                {"canonical_id": "w0_b", "state": "read", "updated_at": _iso(now - timedelta(days=5))},
                {"canonical_id": "w1", "state": "read", "updated_at": _iso(now - timedelta(days=10))},
                {"canonical_id": "w3", "state": "read", "updated_at": _iso(now - timedelta(days=24))},
            ])
            mod = _load()
            import argparse, io, contextlib
            args = argparse.Namespace(project_id="t1", weeks=12)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_trend(args)
            result = json.loads(buf.getvalue())
            self.assertEqual(result["total_in_window"], 4)
            # weekly_read_counts is oldest-first; current week is last
            self.assertEqual(result["weekly_read_counts_oldest_first"][-1], 2)

    def test_trend_rolling_avg_length_matches(self):
        with isolated_cache():
            mod = _load()
            import argparse, io, contextlib
            args = argparse.Namespace(project_id=None, weeks=8)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_trend(args)
            result = json.loads(buf.getvalue())
            self.assertEqual(len(result["weekly_read_counts_oldest_first"]), 8)
            self.assertEqual(len(result["rolling_avg_4w"]), 8)


class SummaryTests(CoscientistTestCase):
    def test_summary_empty(self):
        with isolated_cache():
            mod = _load()
            import argparse, io, contextlib
            args = argparse.Namespace(project_id=None)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_summary(args)
            result = json.loads(buf.getvalue())
            self.assertEqual(result["total_tracked_rows"], 0)

    def test_summary_with_data(self):
        with isolated_cache() as cache:
            _make_project_db(cache, "s1")
            now = datetime.now(UTC)
            _seed(cache, "s1", [
                {"canonical_id": "a", "state": "read",
                 "updated_at": _iso(now - timedelta(days=3))},
                {"canonical_id": "b", "state": "to-read",
                 "updated_at": _iso(now - timedelta(days=10))},
                {"canonical_id": "c", "state": "cited",
                 "updated_at": _iso(now - timedelta(days=200))},
            ])
            mod = _load()
            import argparse, io, contextlib
            args = argparse.Namespace(project_id="s1")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_summary(args)
            result = json.loads(buf.getvalue())
            self.assertEqual(result["total_tracked_rows"], 3)
            self.assertEqual(result["to_read_backlog"], 1)
            self.assertEqual(result["total_read_all_time"], 2)  # read + cited
            self.assertEqual(result["papers_read_28d"], 1)


class ReadOnlyContractTests(CoscientistTestCase):
    def test_velocity_does_not_modify_db(self):
        with isolated_cache() as cache:
            _make_project_db(cache, "ro")
            now = datetime.now(UTC)
            _seed(cache, "ro", [{"canonical_id": "x", "state": "read", "updated_at": _iso(now)}])
            db = cache / "projects" / "ro" / "project.db"
            mtime_before = db.stat().st_mtime

            mod = _load()
            import argparse, io, contextlib
            args = argparse.Namespace(project_id="ro", days=28)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_velocity(args)

            mtime_after = db.stat().st_mtime
            # Read-only — file mtime should not change
            self.assertEqual(mtime_before, mtime_after)

    def test_handles_missing_table_gracefully(self):
        with isolated_cache() as cache:
            proj_dir = cache / "projects" / "no_table"
            proj_dir.mkdir(parents=True)
            con = sqlite3.connect(proj_dir / "project.db")
            con.execute("CREATE TABLE artifact_index (id TEXT)")
            con.close()
            mod = _load()
            import argparse, io, contextlib
            args = argparse.Namespace(project_id="no_table", days=28)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_velocity(args)
            self.assertEqual(json.loads(buf.getvalue())["papers_read_in_window"], 0)
