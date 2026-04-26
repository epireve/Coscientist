"""Tests for the retraction-watch skill."""
from __future__ import annotations

import importlib.util as _ilu
import json
import sqlite3
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))

from tests.harness import CoscientistTestCase, isolated_cache  # noqa


def _load(name: str):
    spec = _ilu.spec_from_file_location(
        name,
        _REPO_ROOT / ".claude/skills/retraction-watch/scripts" / f"{name}.py",
    )
    mod = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _make_project(cache: Path, project_id: str) -> Path:
    """Create a minimal project DB with retraction_flags table."""
    proj_dir = cache / "projects" / project_id
    proj_dir.mkdir(parents=True, exist_ok=True)
    db_path = proj_dir / "project.db"
    con = sqlite3.connect(db_path)
    con.executescript("""
        CREATE TABLE IF NOT EXISTS retraction_flags (
            flag_id      INTEGER PRIMARY KEY AUTOINCREMENT,
            canonical_id TEXT NOT NULL UNIQUE,
            retracted    INTEGER NOT NULL,
            source       TEXT NOT NULL,
            detail       TEXT,
            checked_at   TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS artifact_index (
            artifact_id TEXT, kind TEXT, project_id TEXT
        );
        CREATE TABLE IF NOT EXISTS manuscript_citations (
            citation_key TEXT, resolved_canonical_id TEXT
        );
        CREATE TABLE IF NOT EXISTS graph_nodes (
            node_id TEXT, kind TEXT
        );
    """)
    con.close()
    return proj_dir


def _seed_flags(cache: Path, project_id: str, rows: list[dict]) -> None:
    db = cache / "projects" / project_id / "project.db"
    con = sqlite3.connect(db)
    for r in rows:
        con.execute(
            "INSERT OR REPLACE INTO retraction_flags "
            "(canonical_id, retracted, source, detail, checked_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (r["canonical_id"], r.get("retracted", 0), r.get("source", "manual"),
             r.get("detail"), r.get("checked_at", datetime.now(UTC).isoformat())),
        )
    con.commit()
    con.close()


def _seed_papers(cache: Path, project_id: str, canonical_ids: list[str]) -> None:
    db = cache / "projects" / project_id / "project.db"
    con = sqlite3.connect(db)
    for cid in canonical_ids:
        con.execute(
            "INSERT INTO artifact_index (artifact_id, kind, project_id) VALUES (?, 'paper', ?)",
            (cid, project_id),
        )
    con.commit()
    con.close()


# ──────────────────────────────────────────────
# scan.py tests
# ──────────────────────────────────────────────

class ScanTests(CoscientistTestCase):
    def test_list_all_papers_empty(self):
        with isolated_cache() as cache:
            _make_project(cache, "proj1")
            mod = _load("scan")
            result = mod._all_cited_papers(sqlite3.connect(
                str(cache / "projects" / "proj1" / "project.db")
            ))
            self.assertEqual(result, [])

    def test_list_all_papers_from_artifact_index(self):
        with isolated_cache() as cache:
            _make_project(cache, "proj2")
            _seed_papers(cache, "proj2", ["paper_a", "paper_b"])
            mod = _load("scan")
            con = sqlite3.connect(str(cache / "projects" / "proj2" / "project.db"))
            con.row_factory = sqlite3.Row
            result = mod._all_cited_papers(con)
            self.assertIn("paper_a", result)
            self.assertIn("paper_b", result)

    def test_list_all_papers_from_manuscript_citations(self):
        with isolated_cache() as cache:
            _make_project(cache, "proj3")
            db = cache / "projects" / "proj3" / "project.db"
            con_w = sqlite3.connect(str(db))
            con_w.execute(
                "INSERT INTO manuscript_citations (citation_key, resolved_canonical_id) VALUES (?, ?)",
                ("wang2020", "wang_2020_paper_abc123"),
            )
            con_w.commit()
            con_w.close()
            mod = _load("scan")
            con = sqlite3.connect(str(db))
            con.row_factory = sqlite3.Row
            result = mod._all_cited_papers(con)
            self.assertIn("wang_2020_paper_abc123", result)

    def test_needs_check_no_flag(self):
        mod = _load("scan")
        self.assertTrue(mod._needs_check(None, max_age_days=7))

    def test_needs_check_fresh_flag(self):
        mod = _load("scan")
        # Build a Row-like object via sqlite3
        con = sqlite3.connect(":memory:")
        con.row_factory = sqlite3.Row
        con.execute(
            "CREATE TABLE t (canonical_id TEXT, retracted INT, source TEXT, detail TEXT, checked_at TEXT)"
        )
        now = datetime.now(UTC).isoformat()
        con.execute("INSERT INTO t VALUES (?, ?, ?, ?, ?)", ("cid", 0, "manual", None, now))
        row = con.execute("SELECT * FROM t").fetchone()
        self.assertFalse(mod._needs_check(row, max_age_days=7))

    def test_needs_check_stale_flag(self):
        mod = _load("scan")
        con = sqlite3.connect(":memory:")
        con.row_factory = sqlite3.Row
        con.execute(
            "CREATE TABLE t (canonical_id TEXT, retracted INT, source TEXT, detail TEXT, checked_at TEXT)"
        )
        old = (datetime.now(UTC) - timedelta(days=10)).isoformat()
        con.execute("INSERT INTO t VALUES (?, ?, ?, ?, ?)", ("cid", 0, "manual", None, old))
        row = con.execute("SELECT * FROM t").fetchone()
        self.assertTrue(mod._needs_check(row, max_age_days=7))

    def test_persist_upserts_flags(self):
        with isolated_cache() as cache:
            _make_project(cache, "proj4")
            mod = _load("scan")
            # Build a temp input file
            items = [
                {"canonical_id": "paper_x", "retracted": False, "source": "semantic-scholar",
                 "detail": "clean"},
                {"canonical_id": "paper_y", "retracted": True, "source": "retraction-watch",
                 "detail": "fraud"},
            ]
            input_path = cache / "results.json"
            input_path.write_text(json.dumps(items))

            import argparse
            args = argparse.Namespace(project_id="proj4", input=str(input_path))
            # Redirect stdout
            import io, contextlib
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_persist(args)
            result = json.loads(buf.getvalue())
            self.assertEqual(result["saved"], 2)
            self.assertEqual(result["errors"], [])

            db = cache / "projects" / "proj4" / "project.db"
            con = sqlite3.connect(str(db))
            row = con.execute(
                "SELECT retracted FROM retraction_flags WHERE canonical_id='paper_y'"
            ).fetchone()
            self.assertEqual(row[0], 1)

    def test_persist_creates_table_if_missing(self):
        """Table may not exist in very old DBs — persist creates it."""
        with isolated_cache() as cache:
            proj_dir = cache / "projects" / "proj5"
            proj_dir.mkdir(parents=True)
            db_path = proj_dir / "project.db"
            # DB with NO retraction_flags table
            con = sqlite3.connect(str(db_path))
            con.executescript("CREATE TABLE artifact_index (artifact_id TEXT, kind TEXT, project_id TEXT);")
            con.close()

            mod = _load("scan")
            items = [{"canonical_id": "paper_z", "retracted": False, "source": "manual"}]
            input_path = cache / "results2.json"
            input_path.write_text(json.dumps(items))

            import argparse, io, contextlib
            args = argparse.Namespace(project_id="proj5", input=str(input_path))
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_persist(args)
            result = json.loads(buf.getvalue())
            self.assertEqual(result["saved"], 1)

    def test_dry_run_lists_papers(self):
        with isolated_cache() as cache:
            _make_project(cache, "proj6")
            _seed_papers(cache, "proj6", ["paper_a", "paper_b", "paper_c"])
            mod = _load("scan")

            import argparse, io, contextlib
            args = argparse.Namespace(
                project_id="proj6", canonical_id=None,
                max_age_days=7, dry_run=True, input=None
            )
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_list(args)
            result = json.loads(buf.getvalue())
            self.assertEqual(result["total_papers"], 3)
            self.assertEqual(len(result["to_check"]), 3)

    def test_dry_run_skips_fresh_papers(self):
        with isolated_cache() as cache:
            _make_project(cache, "proj7")
            _seed_papers(cache, "proj7", ["paper_a"])
            _seed_flags(cache, "proj7", [
                {"canonical_id": "paper_a", "retracted": 0, "source": "manual"}
            ])
            mod = _load("scan")

            import argparse, io, contextlib
            args = argparse.Namespace(
                project_id="proj7", canonical_id=None,
                max_age_days=7, dry_run=True, input=None
            )
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_list(args)
            result = json.loads(buf.getvalue())
            self.assertEqual(result["already_current"], 1)
            self.assertEqual(len(result["to_check"]), 0)


# ──────────────────────────────────────────────
# alert.py tests
# ──────────────────────────────────────────────

class AlertTests(CoscientistTestCase):
    def test_retracted_papers_empty(self):
        with isolated_cache() as cache:
            _make_project(cache, "pa1")
            mod = _load("alert")
            result = mod._retracted_papers("pa1")
            self.assertEqual(result, [])

    def test_retracted_papers_filters_correctly(self):
        with isolated_cache() as cache:
            _make_project(cache, "pa2")
            _seed_flags(cache, "pa2", [
                {"canonical_id": "p1", "retracted": 1, "source": "manual"},
                {"canonical_id": "p2", "retracted": 0, "source": "manual"},
            ])
            mod = _load("alert")
            result = mod._retracted_papers("pa2")
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0]["canonical_id"], "p1")

    def test_write_alerts_creates_file(self):
        with isolated_cache() as cache:
            _make_project(cache, "pa3")
            mod = _load("alert")
            retracted = [{"canonical_id": "p1", "source": "manual",
                          "detail": "data fraud", "checked_at": "2026-01-01T00:00:00+00:00"}]
            output = cache / "alerts.json"
            alert = mod._write_alerts("pa3", retracted, output)
            self.assertTrue(output.exists())
            self.assertEqual(alert["retracted_count"], 1)

    def test_write_alerts_idempotent(self):
        with isolated_cache() as cache:
            _make_project(cache, "pa4")
            mod = _load("alert")
            retracted = [{"canonical_id": "p1", "source": "manual",
                          "detail": "fraud", "checked_at": "2026-01-01T00:00:00+00:00"}]
            output = cache / "alerts2.json"
            mod._write_alerts("pa4", retracted, output)
            mod._write_alerts("pa4", retracted, output)
            data = json.loads(output.read_text())
            self.assertEqual(data["retracted_count"], 1)

    def test_journal_body_no_retractions(self):
        mod = _load("alert")
        body = mod._journal_body("proj_x", [])
        self.assertIn("0 retracted", body)

    def test_journal_body_with_retraction(self):
        mod = _load("alert")
        body = mod._journal_body("proj_x", [
            {"canonical_id": "paper_y", "source": "retraction-watch",
             "detail": "fabricated data", "checked_at": "2026-01-01"}
        ])
        self.assertIn("paper_y", body)
        self.assertIn("fabricated data", body)


# ──────────────────────────────────────────────
# status.py tests
# ──────────────────────────────────────────────

class StatusTests(CoscientistTestCase):
    def test_status_empty(self):
        with isolated_cache() as cache:
            _make_project(cache, "ps1")
            mod = _load("status")
            result = mod.get_status("ps1")
            self.assertEqual(result["total_checked"], 0)
            self.assertEqual(result["retracted_count"], 0)

    def test_status_counts(self):
        with isolated_cache() as cache:
            _make_project(cache, "ps2")
            _seed_flags(cache, "ps2", [
                {"canonical_id": "p1", "retracted": 1, "source": "manual"},
                {"canonical_id": "p2", "retracted": 0, "source": "semantic-scholar"},
                {"canonical_id": "p3", "retracted": 0, "source": "semantic-scholar"},
            ])
            mod = _load("status")
            result = mod.get_status("ps2")
            self.assertEqual(result["total_checked"], 3)
            self.assertEqual(result["retracted_count"], 1)
            self.assertEqual(result["not_retracted_count"], 2)

    def test_status_table_format(self):
        with isolated_cache() as cache:
            _make_project(cache, "ps3")
            _seed_flags(cache, "ps3", [
                {"canonical_id": "paper_abc123", "retracted": 1,
                 "source": "retraction-watch", "detail": "fraud"},
            ])
            mod = _load("status")
            result = mod.get_status("ps3")
            table = mod._render_table(result)
            self.assertIn("paper_abc123", table)
            self.assertIn("YES", table)

    def test_status_no_db_raises(self):
        with isolated_cache():
            mod = _load("status")
            with self.assertRaises(SystemExit):
                mod.get_status("nonexistent_project")

    def test_status_missing_table_returns_empty(self):
        """Old DB without retraction_flags table returns empty, not error."""
        with isolated_cache() as cache:
            proj_dir = cache / "projects" / "ps4"
            proj_dir.mkdir(parents=True)
            db_path = proj_dir / "project.db"
            con = sqlite3.connect(str(db_path))
            con.executescript("CREATE TABLE artifact_index (artifact_id TEXT);")
            con.close()
            mod = _load("status")
            result = mod.get_status("ps4")
            self.assertEqual(result["total_checked"], 0)
