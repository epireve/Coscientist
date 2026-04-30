"""v0.200 — supporting_ids decoupled from hyp_ids + claim-ids."""
from __future__ import annotations

import json
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
PLUGIN_SCHEMA = (
    _ROOT / "plugin" / "coscientist-graph-query-mcp" / "lib" / "sqlite_schema.sql"
)


def _build_run_db(run_id: str = "v200_test") -> Path:
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
         "--run-id", run_id, "--agent-name", "inquisitor",
         "--text", "Tension X", "--kind", "tension", *extra],
        capture_output=True, text=True,
    )


class V200SupportingIdsTests(TestCase):
    def test_targets_hyp_id_persists(self):
        with isolated_cache():
            _build_run_db("r1")
            r = _record_claim("r1", "--targets-hyp-id", "hyp-arch-001")
            self.assertEqual(r.returncode, 0, r.stderr)
            con = sqlite3.connect(run_db_path("r1"))
            row = con.execute(
                "SELECT targets_hyp_id FROM claims"
            ).fetchone()
            con.close()
            self.assertEqual(row[0], "hyp-arch-001")

    def test_references_claim_ids_csv_to_json(self):
        with isolated_cache():
            _build_run_db("r2")
            r = _record_claim(
                "r2", "--references-claim-ids", "12,34,56"
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            con = sqlite3.connect(run_db_path("r2"))
            row = con.execute(
                "SELECT references_claim_ids FROM claims"
            ).fetchone()
            con.close()
            self.assertEqual(json.loads(row[0]), [12, 34, 56])

    def test_references_claim_ids_non_integer_rejected(self):
        with isolated_cache():
            _build_run_db("r3")
            r = _record_claim(
                "r3", "--references-claim-ids", "abc,def"
            )
            self.assertTrue(r.returncode != 0)

    def test_supporting_ids_rejects_hyp_prefix(self):
        with isolated_cache():
            _build_run_db("r4")
            r = _record_claim(
                "r4", "--supporting-ids", "paper_a,hyp-arch-001"
            )
            self.assertTrue(r.returncode != 0)
            self.assertIn("hyp", (r.stderr + r.stdout).lower())

    def test_supporting_ids_paper_only_succeeds(self):
        with isolated_cache():
            _build_run_db("r5")
            r = _record_claim(
                "r5", "--supporting-ids", "paper_a,paper_b"
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            con = sqlite3.connect(run_db_path("r5"))
            row = con.execute(
                "SELECT supporting_ids FROM claims"
            ).fetchone()
            con.close()
            self.assertEqual(json.loads(row[0]), ["paper_a", "paper_b"])

    def test_all_three_id_fields_independently_nullable(self):
        with isolated_cache():
            _build_run_db("r6")
            r = _record_claim("r6")
            self.assertEqual(r.returncode, 0, r.stderr)
            con = sqlite3.connect(run_db_path("r6"))
            row = con.execute(
                "SELECT supporting_ids, targets_hyp_id, references_claim_ids "
                "FROM claims"
            ).fetchone()
            con.close()
            self.assertEqual(row, (None, None, None))

    def test_schema_mirror_in_plugin(self):
        """plugin/coscientist-graph-query-mcp/lib/sqlite_schema.sql mirrors lib/."""
        plugin_text = PLUGIN_SCHEMA.read_text()
        for col in ("side", "paired_claim_id",
                    "targets_hyp_id", "references_claim_ids"):
            self.assertIn(col, plugin_text,
                          f"plugin schema missing column reference {col}")


class V17MigrationTests(TestCase):
    def test_v17_sql_file_exists(self):
        self.assertTrue(
            (_ROOT / "lib" / "migrations_sql" / "v17.sql").exists()
        )

    def test_v17_sql_file_in_plugin(self):
        self.assertTrue(
            (_ROOT / "plugin" / "coscientist-graph-query-mcp" /
             "lib" / "migrations_sql" / "v17.sql").exists()
        )

    def test_v17_idempotent_on_old_db(self):
        """Pre-existing DB without claims columns gets them via migration,
        and re-running migration is a no-op."""
        with isolated_cache():
            db = run_db_path("legacy_run")
            db.parent.mkdir(parents=True, exist_ok=True)
            # Build an old-shape DB: claims without v17 columns.
            con = sqlite3.connect(db)
            con.executescript("""
                CREATE TABLE runs (
                    run_id TEXT PRIMARY KEY, question TEXT,
                    started_at TEXT NOT NULL
                );
                CREATE TABLE claims (
                    claim_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    canonical_id TEXT, agent_name TEXT,
                    text TEXT NOT NULL, kind TEXT,
                    confidence REAL, supporting_ids TEXT
                );
            """)
            con.execute(
                "INSERT INTO runs VALUES (?, ?, ?)",
                ("legacy_run", "q", datetime.now(UTC).isoformat()),
            )
            con.execute(
                "INSERT INTO claims (run_id, text, kind) VALUES (?, ?, ?)",
                ("legacy_run", "old claim", "finding"),
            )
            con.commit()
            con.close()

            applied = migrations.ensure_current(db)
            self.assertIn(17, applied)

            con = sqlite3.connect(db)
            cols = {r[1] for r in con.execute("PRAGMA table_info(claims)")}
            n = con.execute("SELECT COUNT(*) FROM claims").fetchone()[0]
            con.close()
            self.assertEqual(n, 1, "existing rows preserved")
            for needed in ("side", "paired_claim_id",
                           "targets_hyp_id", "references_claim_ids"):
                self.assertIn(needed, cols)

            # Idempotent: re-run is a no-op.
            again = migrations.ensure_current(db)
            self.assertEqual(again, [])


if __name__ == "__main__":
    run_tests(V200SupportingIdsTests, V17MigrationTests)
