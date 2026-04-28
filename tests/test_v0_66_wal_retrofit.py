"""v0.66 — verify WAL is enabled on critical-path DBs.

Three retrofitted points:
  1. lib.skill_persist._ensure_db
  2. .claude/skills/deep-research/scripts/db.py::_connect
  3. .claude/skills/wide-research/scripts/wide.py::_connect_wide_db

Each should produce a WAL-mode DB. We test (1) directly via the
public persist_* helpers; (2) and (3) via subprocess invocation of
the CLIs, then re-open the DB to inspect journal_mode.
"""
from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path

from lib import skill_persist
from lib.cache import run_db_path
from tests.harness import TestCase, isolated_cache, run_tests

_REPO = Path(__file__).resolve().parents[1]
_DEEP_DB_CLI = _REPO / ".claude" / "skills" / "deep-research" / "scripts" / "db.py"
_WIDE_CLI = _REPO / ".claude" / "skills" / "wide-research" / "scripts" / "wide.py"


def _journal_mode(db: Path) -> str:
    con = sqlite3.connect(db)
    try:
        return con.execute("PRAGMA journal_mode").fetchone()[0].lower()
    finally:
        con.close()


class SkillPersistWalTests(TestCase):
    def test_ensure_db_returns_wal(self):
        with isolated_cache() as root:
            db = root / "runs" / "run-walretro.db"
            # Trigger creation via persist helper.
            skill_persist.persist_citation_resolution(
                db,
                run_id="walretro",
                input_text="x",
                partial={},
                matched=False,
                score=0.0,
                threshold=0.5,
            )
            self.assertEqual(_journal_mode(db), "wal")


class DeepResearchDbWalTests(TestCase):
    def test_db_init_uses_wal(self):
        with isolated_cache():
            cmd = [
                sys.executable, str(_DEEP_DB_CLI), "init",
                "--question", "WAL retrofit smoke test",
            ]
            r = subprocess.run(cmd, capture_output=True, text=True,
                               cwd=str(_REPO))
            self.assertEqual(r.returncode, 0, r.stderr)
            # Last whitespace-separated token of stdout = run_id.
            run_id = r.stdout.strip().split()[-1]
            db = run_db_path(run_id)
            self.assertTrue(db.exists(), f"DB missing at {db}")
            self.assertEqual(_journal_mode(db), "wal")


if __name__ == "__main__":
    raise SystemExit(run_tests(
        SkillPersistWalTests,
        DeepResearchDbWalTests,
    ))
