"""Tests for v0.63 citation_resolutions persistence."""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

from tests.harness import TestCase, isolated_cache, run_tests

from lib import skill_persist
from lib.cache import cache_root, run_db_path
from lib.migrations import ensure_current


_REPO = Path(__file__).resolve().parents[1]
_RESOLVE_CLI = _REPO / ".claude" / "skills" / "resolve-citation" / "scripts" / "resolve.py"


def _new_run_db(rid: str) -> Path:
    """Initialize a coscientist DB so v9/v10 migrations apply."""
    db = run_db_path(rid)
    schema = (_REPO / "lib" / "sqlite_schema.sql").read_text()
    con = sqlite3.connect(db)
    con.executescript(schema)
    con.close()
    ensure_current(db)
    return db


class MigrationV10Tests(TestCase):
    def test_v10_creates_citation_resolutions(self):
        with isolated_cache():
            db = _new_run_db("test_v10_run")
            con = sqlite3.connect(db)
            try:
                rows = con.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name='citation_resolutions'"
                ).fetchall()
                self.assertEqual(len(rows), 1)
                cols = {r[1] for r in con.execute(
                    "PRAGMA table_info(citation_resolutions)")}
                expected = {
                    "resolution_id", "run_id", "project_id", "input_text",
                    "partial_json", "matched", "score", "threshold",
                    "canonical_id", "doi", "title", "year", "candidate_json",
                    "at",
                }
                self.assertEqual(cols, expected)
            finally:
                con.close()

    def test_v10_idempotent(self):
        with isolated_cache():
            db = _new_run_db("test_v10_idem")
            applied1 = ensure_current(db)
            applied2 = ensure_current(db)
            self.assertEqual(applied2, [])
            self.assertNotIn(10, applied2)


class PersistCitationResolutionTests(TestCase):
    def test_matched_row_inserted(self):
        with isolated_cache():
            db = _new_run_db("ptest_run")
            note = skill_persist.persist_citation_resolution(
                db,
                run_id="ptest_run",
                input_text="Vaswani 2017 Attention",
                partial={"authors": ["Vaswani"], "year": 2017,
                         "title_tokens": ["attention"]},
                matched=True,
                score=0.91,
                threshold=0.5,
                canonical_id="vaswani_2017_attention_abc",
                doi="10.48550/arXiv.1706.03762",
                title="Attention Is All You Need",
                year=2017,
                candidate={"title": "Attention Is All You Need"},
            )
            self.assertEqual(note["target_table"], "citation_resolutions")
            self.assertEqual(note["n_rows"], 1)
            con = sqlite3.connect(db)
            try:
                row = con.execute(
                    "SELECT matched, score, canonical_id, year "
                    "FROM citation_resolutions WHERE run_id=?",
                    ("ptest_run",),
                ).fetchone()
                self.assertEqual(row[0], 1)
                self.assertAlmostEqual(row[1], 0.91, places=4)
                self.assertEqual(row[2], "vaswani_2017_attention_abc")
                self.assertEqual(row[3], 2017)
            finally:
                con.close()

    def test_below_threshold_row_inserted(self):
        with isolated_cache():
            db = _new_run_db("below_run")
            skill_persist.persist_citation_resolution(
                db,
                run_id="below_run",
                input_text="some 2020 thing",
                partial={"year": 2020},
                matched=False,
                score=0.21,
                threshold=0.5,
            )
            con = sqlite3.connect(db)
            try:
                row = con.execute(
                    "SELECT matched, canonical_id "
                    "FROM citation_resolutions WHERE run_id=?",
                    ("below_run",),
                ).fetchone()
                self.assertEqual(row[0], 0)
                self.assertIsNone(row[1])
            finally:
                con.close()

    def test_db_writes_audit_row(self):
        with isolated_cache():
            db = _new_run_db("audit_run")
            skill_persist.persist_citation_resolution(
                db,
                run_id="audit_run",
                input_text="x",
                partial={},
                matched=True,
                score=0.7,
                threshold=0.5,
                canonical_id="x_2020",
            )
            con = sqlite3.connect(db)
            try:
                row = con.execute(
                    "SELECT target_table, skill_or_lib, n_rows "
                    "FROM db_writes WHERE skill_or_lib='resolve-citation'"
                ).fetchone()
                self.assertEqual(row[0], "citation_resolutions")
                self.assertEqual(row[1], "resolve-citation")
                self.assertEqual(row[2], 1)
            finally:
                con.close()


class ResolveCliPersistTests(TestCase):
    def test_persist_db_writes_row(self):
        with isolated_cache() as root:
            rid = "cli_persist_run"
            db = _new_run_db(rid)
            cand_path = root / "candidates.json"
            cand_path.write_text(json.dumps([
                {
                    "title": "Attention Is All You Need",
                    "year": 2017,
                    "authors": [{"name": "Ashish Vaswani"}],
                    "doi": "10.48550/arXiv.1706.03762",
                },
                {
                    "title": "Some Other Paper",
                    "year": 2010,
                    "authors": [{"name": "Other Author"}],
                },
            ]))
            cmd = [
                sys.executable, str(_RESOLVE_CLI),
                "--text", "Vaswani 2017 Attention",
                "--candidates", str(cand_path),
                "--persist-db",
                "--run-id", rid,
            ]
            r = subprocess.run(cmd, capture_output=True, text=True,
                               cwd=str(_REPO))
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("[db-notify]", r.stderr)
            con = sqlite3.connect(db)
            try:
                rows = con.execute(
                    "SELECT matched, canonical_id "
                    "FROM citation_resolutions WHERE run_id=?",
                    (rid,),
                ).fetchall()
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0][0], 1)
                self.assertTrue(rows[0][1])
            finally:
                con.close()

    def test_persist_db_without_target_errors(self):
        with isolated_cache() as root:
            cand_path = root / "candidates.json"
            cand_path.write_text("[]")
            r = subprocess.run(
                [sys.executable, str(_RESOLVE_CLI),
                 "--text", "Smith 2020",
                 "--candidates", str(cand_path),
                 "--persist-db"],
                capture_output=True, text=True, cwd=str(_REPO),
            )
            self.assertEqual(r.returncode, 2)
            self.assertIn("requires", r.stderr)


if __name__ == "__main__":
    raise SystemExit(run_tests(
        MigrationV10Tests,
        PersistCitationResolutionTests,
        ResolveCliPersistTests,
    ))
