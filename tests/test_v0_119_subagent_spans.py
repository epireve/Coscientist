"""v0.119 — sub-agent span emission via record-subagent CLI."""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

from tests.harness import TestCase, isolated_cache, run_tests
from lib.cache import run_db_path


_REPO = Path(__file__).resolve().parents[1]
_DB_PY = (_REPO / ".claude" / "skills" / "deep-research"
           / "scripts" / "db.py")


def _init_run() -> str:
    r = subprocess.run(
        [sys.executable, str(_DB_PY), "init",
         "--question", "test"],
        capture_output=True, text=True, cwd=str(_REPO),
    )
    assert r.returncode == 0, r.stderr
    return r.stdout.strip().split()[-1]


def _run_subagent(rid: str, persona: str, *flags: str):
    args = [sys.executable, str(_DB_PY), "record-subagent",
            "--run-id", rid, "--persona", persona, *flags]
    r = subprocess.run(args, capture_output=True, text=True,
                        cwd=str(_REPO))
    return r


class StartEndTests(TestCase):
    def test_start_creates_running_span(self):
        with isolated_cache():
            rid = _init_run()
            r = _run_subagent(rid, "scout", "--start")
            self.assertEqual(r.returncode, 0, r.stderr)
            payload = json.loads(r.stdout)
            self.assertTrue(payload["ok"])
            self.assertIn("span_id", payload)
            db = run_db_path(rid)
            con = sqlite3.connect(db)
            try:
                row = con.execute(
                    "SELECT kind, name, status FROM spans "
                    "WHERE trace_id=? AND name='scout'",
                    (rid,),
                ).fetchone()
            finally:
                con.close()
            self.assertEqual(row[0], "sub-agent")
            self.assertEqual(row[1], "scout")
            self.assertEqual(row[2], "running")

    def test_end_closes_span_with_duration(self):
        with isolated_cache():
            rid = _init_run()
            _run_subagent(rid, "scout", "--start")
            r = _run_subagent(rid, "scout", "--end")
            self.assertEqual(r.returncode, 0, r.stderr)
            payload = json.loads(r.stdout)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["status"], "ok")
            self.assertGreaterEqual(payload["duration_ms"], 0)
            db = run_db_path(rid)
            con = sqlite3.connect(db)
            try:
                row = con.execute(
                    "SELECT status, ended_at, duration_ms "
                    "FROM spans WHERE trace_id=? AND name='scout'",
                    (rid,),
                ).fetchone()
            finally:
                con.close()
            self.assertEqual(row[0], "ok")
            self.assertIsNotNone(row[1])
            self.assertGreaterEqual(row[2], 0)

    def test_end_with_error_marks_status_error(self):
        with isolated_cache():
            rid = _init_run()
            _run_subagent(rid, "scout", "--start")
            r = _run_subagent(rid, "scout", "--end",
                                "--error", "scout crashed")
            self.assertEqual(r.returncode, 0, r.stderr)
            db = run_db_path(rid)
            con = sqlite3.connect(db)
            try:
                row = con.execute(
                    "SELECT status, error_msg, error_kind "
                    "FROM spans WHERE trace_id=? AND name='scout'",
                    (rid,),
                ).fetchone()
            finally:
                con.close()
            self.assertEqual(row[0], "error")
            self.assertEqual(row[1], "scout crashed")
            self.assertEqual(row[2], "sub-agent-error")

    def test_end_without_start_errors(self):
        with isolated_cache():
            rid = _init_run()
            r = _run_subagent(rid, "scout", "--end")
            self.assertEqual(r.returncode, 1)
            payload = json.loads(r.stdout)
            self.assertFalse(payload["ok"])
            self.assertIn("no open sub-agent span", payload["error"])

    def test_concurrent_personas_independent(self):
        with isolated_cache():
            rid = _init_run()
            _run_subagent(rid, "scout", "--start")
            _run_subagent(rid, "cartographer", "--start")
            _run_subagent(rid, "scout", "--end")
            _run_subagent(rid, "cartographer", "--end")
            db = run_db_path(rid)
            con = sqlite3.connect(db)
            try:
                rows = con.execute(
                    "SELECT name, status FROM spans "
                    "WHERE trace_id=? AND kind='sub-agent' "
                    "ORDER BY name",
                    (rid,),
                ).fetchall()
            finally:
                con.close()
            names = {r[0]: r[1] for r in rows}
            self.assertEqual(names["scout"], "ok")
            self.assertEqual(names["cartographer"], "ok")


if __name__ == "__main__":
    raise SystemExit(run_tests(StartEndTests))
