"""v0.198 — claims dual-side tension support."""
from __future__ import annotations

import sqlite3
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from lib import migrations
from lib.cache import run_db_path
from tests.harness import TestCase, isolated_cache, run_tests

_ROOT = Path(__file__).resolve().parent.parent
SCHEMA = (_ROOT / "lib" / "sqlite_schema.sql").read_text()
DB_CLI = _ROOT / ".claude" / "skills" / "deep-research" / "scripts" / "db.py"


def _build_run_db(run_id: str = "v198_test") -> Path:
    db = run_db_path(run_id)
    db.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db)
    con.executescript(SCHEMA)
    con.execute(
        "INSERT INTO runs (run_id, question, started_at) VALUES (?, ?, ?)",
        (run_id, "q", datetime.now(UTC).isoformat()),
    )
    con.commit()
    con.close()
    migrations.ensure_current(db)
    return db


def _record_claim(run_id: str, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(DB_CLI), "record-claim",
         "--run-id", run_id, "--agent-name", "weaver",
         "--text", "X tension Y", "--kind", "tension",
         *extra],
        capture_output=True, text=True,
    )


class V198ClaimsSidesTests(TestCase):
    def test_v17_in_all_versions(self):
        self.assertIn(17, migrations.ALL_VERSIONS)

    def test_v17_columns_present(self):
        with isolated_cache():
            db = _build_run_db()
            con = sqlite3.connect(db)
            cols = {r[1] for r in con.execute("PRAGMA table_info(claims)")}
            con.close()
            for needed in ("side", "paired_claim_id",
                           "targets_hyp_id", "references_claim_ids"):
                self.assertIn(needed, cols, f"missing column {needed}")

    def test_paired_side_a_b_insert(self):
        with isolated_cache():
            _build_run_db("rid1")
            r1 = _record_claim("rid1", "--side", "a")
            self.assertEqual(r1.returncode, 0, r1.stderr)
            r2 = _record_claim("rid1", "--side", "b", "--paired-claim-id", "1")
            self.assertEqual(r2.returncode, 0, r2.stderr)
            con = sqlite3.connect(run_db_path("rid1"))
            rows = con.execute(
                "SELECT claim_id, side, paired_claim_id FROM claims ORDER BY claim_id"
            ).fetchall()
            con.close()
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0][1], "a")
            self.assertEqual(rows[1][1], "b")
            self.assertEqual(rows[1][2], 1)

    def test_invalid_side_rejected(self):
        with isolated_cache():
            _build_run_db("rid2")
            r = _record_claim("rid2", "--side", "c")
            # argparse choices=('a','b') rejects with returncode 2
            self.assertTrue(r.returncode != 0)

    def test_null_side_back_compat(self):
        """Existing rows pre-migration carry NULL side; insert with no
        --side flag preserves that."""
        with isolated_cache():
            _build_run_db("rid3")
            r = _record_claim("rid3")
            self.assertEqual(r.returncode, 0, r.stderr)
            con = sqlite3.connect(run_db_path("rid3"))
            row = con.execute(
                "SELECT side, paired_claim_id FROM claims"
            ).fetchone()
            con.close()
            self.assertEqual(row[0], None)
            self.assertEqual(row[1], None)

    def test_migration_idempotent(self):
        with isolated_cache():
            db = _build_run_db("rid4")
            again = migrations.ensure_current(db)
            self.assertEqual(again, [])


if __name__ == "__main__":
    run_tests(V198ClaimsSidesTests)
