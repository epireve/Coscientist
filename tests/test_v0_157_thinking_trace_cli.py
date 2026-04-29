"""v0.157 — thinking_trace CLI subcommand."""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

from lib.cache import run_db_path
from lib.thinking_trace import get_thinking
from tests.harness import TestCase, isolated_cache, run_tests

_REPO = Path(__file__).resolve().parents[1]


def _init_run(rid: str = "r1") -> Path:
    db = run_db_path(rid)
    db.parent.mkdir(parents=True, exist_ok=True)
    schema = (_REPO / "lib" / "sqlite_schema.sql").read_text()
    con = sqlite3.connect(db)
    con.executescript(schema)
    con.execute(
        "INSERT INTO runs (run_id, question, started_at, status) "
        "VALUES (?, ?, ?, ?)", (rid, "q", "now", "running"),
    )
    # seed an attack_findings row so we have a target
    con.execute(
        "INSERT INTO attack_findings "
        "(run_id, target_canonical_id, attack, severity, at) "
        "VALUES (?, ?, ?, ?, ?)",
        (rid, "p1", "p-hacking", "minor", "now"),
    )
    con.commit()
    con.close()
    return db


def _run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "lib.thinking_trace", *args],
        capture_output=True, text=True, cwd=str(_REPO),
    )


class CliRecordTests(TestCase):
    def test_record_persists_log(self):
        with isolated_cache():
            db = _init_run()
            log = {"considered": ["a", "b"], "chose": "minor",
                   "rationale": "evidence weak but present"}
            r = _run_cli(
                "record",
                "--run-db", str(db),
                "--table", "attack_findings",
                "--row-id-col", "finding_id",
                "--row-id", "1",
                "--log-json", json.dumps(log),
            )
            self.assertEqual(r.returncode, 0, msg=r.stderr + r.stdout)
            got = get_thinking(db, "attack_findings", "finding_id", 1)
            self.assertEqual(got["chose"], "minor")
            self.assertEqual(got["considered"], ["a", "b"])

    def test_record_rejects_unknown_table(self):
        with isolated_cache():
            db = _init_run()
            r = _run_cli(
                "record", "--run-db", str(db),
                "--table", "bogus_table",
                "--row-id-col", "id", "--row-id", "1",
                "--log-json", "{}",
            )
            self.assertTrue(r.returncode != 0)

    def test_record_rejects_invalid_json(self):
        with isolated_cache():
            db = _init_run()
            r = _run_cli(
                "record", "--run-db", str(db),
                "--table", "attack_findings",
                "--row-id-col", "finding_id", "--row-id", "1",
                "--log-json", "not json {",
            )
            self.assertTrue(r.returncode != 0)
            self.assertIn("invalid", r.stdout)

    def test_record_rejects_non_object_log(self):
        with isolated_cache():
            db = _init_run()
            r = _run_cli(
                "record", "--run-db", str(db),
                "--table", "attack_findings",
                "--row-id-col", "finding_id", "--row-id", "1",
                "--log-json", "[1, 2, 3]",
            )
            self.assertTrue(r.returncode != 0)
            self.assertIn("object", r.stdout)


class CliHelpTests(TestCase):
    def test_help_lists_subcommand(self):
        r = _run_cli("--help")
        self.assertEqual(r.returncode, 0)
        self.assertIn("record", r.stdout)

    def test_unknown_subcommand_errors(self):
        r = _run_cli("bogus")
        self.assertTrue(r.returncode != 0)


if __name__ == "__main__":
    raise SystemExit(run_tests(CliRecordTests, CliHelpTests))
