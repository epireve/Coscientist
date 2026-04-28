"""Tests for v0.64 audit-query resolutions subcommand."""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

from lib import skill_persist
from lib.cache import run_db_path
from lib.migrations import ensure_current
from tests.harness import TestCase, isolated_cache, run_tests

_REPO = Path(__file__).resolve().parents[1]
_QUERY_CLI = _REPO / ".claude" / "skills" / "audit-query" / "scripts" / "query.py"


def _new_run_db(rid: str) -> Path:
    db = run_db_path(rid)
    schema = (_REPO / "lib" / "sqlite_schema.sql").read_text()
    con = sqlite3.connect(db)
    con.executescript(schema)
    con.close()
    ensure_current(db)
    return db


def _seed_resolutions(db: Path, rid: str, n_matched: int, n_below: int):
    for i in range(n_matched):
        skill_persist.persist_citation_resolution(
            db, run_id=rid, input_text=f"matched-{i}",
            partial={"year": 2020}, matched=True, score=0.85 + i * 0.01,
            threshold=0.5, canonical_id=f"cid_{i}",
            title=f"Title {i}", year=2020,
        )
    for i in range(n_below):
        skill_persist.persist_citation_resolution(
            db, run_id=rid, input_text=f"below-{i}",
            partial={}, matched=False, score=0.2 + i * 0.05,
            threshold=0.5,
        )


def _run_cli(*args) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(_QUERY_CLI), *args]
    return subprocess.run(cmd, capture_output=True, text=True, cwd=str(_REPO))


class ResolutionsCmdTests(TestCase):
    def test_empty_table_present(self):
        with isolated_cache():
            db = _new_run_db("empty_run")
            r = _run_cli("resolutions", "--db-path", str(db))
            self.assertEqual(r.returncode, 0, r.stderr)
            data = json.loads(r.stdout)
            self.assertTrue(data["table_present"])
            self.assertEqual(data["total"], 0)
            self.assertEqual(data["match_rate"], 0.0)

    def test_table_missing(self):
        # A non-coscientist DB — no citation_resolutions table.
        with isolated_cache() as root:
            db = root / "tiny.db"
            con = sqlite3.connect(db)
            con.execute("CREATE TABLE foo (x INTEGER)")
            con.close()
            r = _run_cli("resolutions", "--db-path", str(db))
            self.assertEqual(r.returncode, 0, r.stderr)
            data = json.loads(r.stdout)
            self.assertFalse(data["table_present"])
            self.assertEqual(data["total"], 0)

    def test_summary_with_data(self):
        with isolated_cache():
            db = _new_run_db("data_run")
            _seed_resolutions(db, "data_run", n_matched=3, n_below=2)
            r = _run_cli("resolutions", "--db-path", str(db))
            self.assertEqual(r.returncode, 0, r.stderr)
            data = json.loads(r.stdout)
            self.assertEqual(data["total"], 5)
            self.assertEqual(data["matched"], 3)
            self.assertEqual(data["unmatched"], 2)
            self.assertAlmostEqual(data["match_rate"], 0.6, places=4)
            self.assertGreaterEqual(data["score_buckets"][">=0.9"], 0)
            self.assertGreaterEqual(data["score_buckets"]["<0.3"], 1)
            self.assertEqual(len(data["recent"]), 5)

    def test_matched_only_filter(self):
        with isolated_cache():
            db = _new_run_db("mo_run")
            _seed_resolutions(db, "mo_run", n_matched=2, n_below=3)
            r = _run_cli(
                "resolutions", "--db-path", str(db),
                "--matched-only", "--limit", "10",
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            data = json.loads(r.stdout)
            self.assertEqual(data["total"], 2)
            self.assertEqual(data["matched"], 2)
            self.assertEqual(data["unmatched"], 0)

    def test_run_id_filter(self):
        with isolated_cache():
            db1 = _new_run_db("filter_run_a")
            _seed_resolutions(db1, "filter_run_a", n_matched=2, n_below=0)
            _seed_resolutions(db1, "filter_run_b", n_matched=4, n_below=1)
            r = _run_cli(
                "resolutions", "--db-path", str(db1),
                "--run-id", "filter_run_b",
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            data = json.loads(r.stdout)
            self.assertEqual(data["total"], 5)
            self.assertEqual(data["matched"], 4)


if __name__ == "__main__":
    raise SystemExit(run_tests(ResolutionsCmdTests))
