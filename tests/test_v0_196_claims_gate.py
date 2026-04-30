"""v0.196 — claims gate validates supporting_ids exist in run DB.

Default = warn + accept (back-compat). --strict-supporting-ids rejects.
Same validation extended to --references-claim-ids and --targets-hyp-id.
"""
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


def _build_run_db(run_id: str = "v196_test") -> Path:
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


def _add_paper(run_id: str, cid: str) -> None:
    con = sqlite3.connect(run_db_path(run_id))
    con.execute(
        "INSERT INTO papers_in_run (run_id, canonical_id, added_in_phase) "
        "VALUES (?, ?, ?)",
        (run_id, cid, "scout"),
    )
    con.commit()
    con.close()


def _add_hyp(run_id: str, hyp_id: str) -> None:
    con = sqlite3.connect(run_db_path(run_id))
    con.execute(
        "INSERT INTO hypotheses "
        "(hyp_id, run_id, agent_name, statement, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (hyp_id, run_id, "theorist", "h", datetime.now(UTC).isoformat()),
    )
    con.commit()
    con.close()


def _add_claim(run_id: str, text: str = "seed") -> int:
    con = sqlite3.connect(run_db_path(run_id))
    cur = con.execute(
        "INSERT INTO claims (run_id, agent_name, text, kind) "
        "VALUES (?, ?, ?, ?)",
        (run_id, "tester", text, "finding"),
    )
    cid = cur.lastrowid
    con.commit()
    con.close()
    return cid


def _record_claim(run_id: str, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(DB_CLI), "record-claim",
         "--run-id", run_id, "--agent-name", "weaver",
         "--text", "claim X", "--kind", "finding", *extra],
        capture_output=True, text=True,
    )


class V196ClaimsGateTests(TestCase):
    def test_valid_supporting_ids_accepted_clean(self):
        with isolated_cache():
            _build_run_db("c1")
            _add_paper("c1", "paper_a")
            _add_paper("c1", "paper_b")
            r = _record_claim("c1", "--supporting-ids", "paper_a,paper_b")
            self.assertEqual(r.returncode, 0, r.stderr)
            # No warning when all valid
            self.assertEqual(r.stderr.strip(), "")

    def test_missing_supporting_ids_warn_accept_default(self):
        with isolated_cache():
            _build_run_db("c2")
            _add_paper("c2", "paper_a")
            r = _record_claim(
                "c2", "--supporting-ids", "paper_a,ghost_x",
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("warning", r.stderr.lower())
            self.assertIn("ghost_x", r.stderr)
            # Row still inserted
            con = sqlite3.connect(run_db_path("c2"))
            n = con.execute("SELECT COUNT(*) FROM claims").fetchone()[0]
            con.close()
            self.assertEqual(n, 1)

    def test_missing_supporting_ids_strict_rejected(self):
        with isolated_cache():
            _build_run_db("c3")
            _add_paper("c3", "paper_a")
            r = _record_claim(
                "c3", "--supporting-ids", "paper_a,ghost_x",
                "--strict-supporting-ids",
            )
            self.assertTrue(r.returncode != 0)
            self.assertIn("missing", (r.stderr + r.stdout).lower())

    def test_strict_mode_preserves_db_integrity(self):
        with isolated_cache():
            _build_run_db("c4")
            _add_paper("c4", "paper_a")
            r = _record_claim(
                "c4", "--supporting-ids", "ghost_x",
                "--strict-supporting-ids",
            )
            self.assertTrue(r.returncode != 0)
            con = sqlite3.connect(run_db_path("c4"))
            n = con.execute("SELECT COUNT(*) FROM claims").fetchone()[0]
            con.close()
            self.assertEqual(n, 0, "rejection must roll back / not insert")

    def test_references_claim_ids_missing_warns(self):
        with isolated_cache():
            _build_run_db("c5")
            real_id = _add_claim("c5", "anchor")
            r = _record_claim(
                "c5", "--references-claim-ids", f"{real_id},9999",
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("warning", r.stderr.lower())
            self.assertIn("9999", r.stderr)

    def test_targets_hyp_id_missing_warns(self):
        with isolated_cache():
            _build_run_db("c6")
            r = _record_claim(
                "c6", "--targets-hyp-id", "hyp-ghost-999",
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("warning", r.stderr.lower())
            self.assertIn("hyp-ghost-999", r.stderr)

    def test_targets_hyp_id_valid_accepted_clean(self):
        with isolated_cache():
            _build_run_db("c7")
            _add_hyp("c7", "hyp-real-001")
            r = _record_claim(
                "c7", "--targets-hyp-id", "hyp-real-001",
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(r.stderr.strip(), "")

    def test_empty_supporting_ids_no_warn(self):
        with isolated_cache():
            _build_run_db("c8")
            r = _record_claim("c8")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(r.stderr.strip(), "")


if __name__ == "__main__":
    run_tests(V196ClaimsGateTests)
