"""v0.173 — cost dashboard tests."""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from lib import cost_dashboard
from lib.cache import run_db_path
from tests.harness import TestCase, isolated_cache, run_tests

_REPO = Path(__file__).resolve().parents[1]
SCHEMA = (_REPO / "lib" / "sqlite_schema.sql").read_text()


def _new_run_db(rid: str) -> Path:
    db = run_db_path(rid)
    con = sqlite3.connect(db)
    con.executescript(SCHEMA)
    con.close()
    from lib.migrations import ensure_current
    ensure_current(db)
    return db


def _seed_trace(db: Path, trace_id: str = "t1") -> None:
    con = sqlite3.connect(db)
    try:
        con.execute(
            "INSERT OR IGNORE INTO traces "
            "(trace_id, run_id, started_at, status) "
            "VALUES (?, NULL, ?, 'ok')",
            (trace_id, datetime.now(UTC).isoformat()),
        )
        con.commit()
    finally:
        con.close()


def _insert_tool_call(db: Path, *, name: str, started_at: str,
                       trace_id: str = "t1") -> None:
    con = sqlite3.connect(db)
    try:
        con.execute(
            "INSERT INTO spans "
            "(span_id, trace_id, kind, name, started_at, status) "
            "VALUES (?, ?, 'tool-call', ?, ?, 'ok')",
            (uuid.uuid4().hex, trace_id, name, started_at),
        )
        con.commit()
    finally:
        con.close()


def _ago(days: int) -> str:
    return (datetime.now(UTC) - timedelta(days=days)).isoformat()


class CostDashboardTests(TestCase):
    def test_empty_returns_zero(self):
        with isolated_cache():
            report = cost_dashboard.collect()
            self.assertEqual(report["n_calls_total"], 0)
            self.assertEqual(report["totals"]["cost_all"], 0.0)
            self.assertEqual(report["totals"]["n_all"], 0)

    def test_consensus_calls_cost(self):
        with isolated_cache():
            db = _new_run_db("c1")
            _seed_trace(db)
            for _ in range(5):
                _insert_tool_call(db,
                                   name="mcp__consensus__search",
                                   started_at=_ago(1))
            report = cost_dashboard.collect()
            cs = report["per_server"]["consensus"]
            self.assertEqual(cs["n_7d"], 5)
            self.assertEqual(cs["n_all"], 5)
            self.assertAlmostEqual(cs["cost_all"], 0.50, places=4)
            self.assertAlmostEqual(
                report["totals"]["cost_all"], 0.50, places=4,
            )

    def test_free_mcp_zero_cost(self):
        with isolated_cache():
            db = _new_run_db("c2")
            _seed_trace(db)
            for _ in range(3):
                _insert_tool_call(db,
                                   name="mcp__openalex__search",
                                   started_at=_ago(1))
            for _ in range(2):
                _insert_tool_call(
                    db, name="mcp__paper-search__search_arxiv",
                    started_at=_ago(1),
                )
            report = cost_dashboard.collect()
            self.assertEqual(
                report["per_server"]["openalex"]["n_all"], 3,
            )
            self.assertEqual(
                report["per_server"]["paper-search"]["n_all"], 2,
            )
            self.assertEqual(
                report["per_server"]["openalex"]["cost_all"], 0.0,
            )
            self.assertEqual(
                report["per_server"]["paper-search"]["cost_all"], 0.0,
            )
            self.assertEqual(report["totals"]["cost_all"], 0.0)

    def test_window_filter_excludes_old(self):
        with isolated_cache():
            db = _new_run_db("c3")
            _seed_trace(db)
            # 3 calls within 7d, 2 calls 20d ago.
            for _ in range(3):
                _insert_tool_call(db,
                                   name="mcp__consensus__search",
                                   started_at=_ago(1))
            for _ in range(2):
                _insert_tool_call(db,
                                   name="mcp__consensus__search",
                                   started_at=_ago(20))
            report = cost_dashboard.collect(window_days=7)
            cs = report["per_server"]["consensus"]
            self.assertEqual(cs["n_7d"], 3)
            self.assertEqual(cs["n_30d"], 5)
            self.assertEqual(cs["n_all"], 5)

    def test_30d_window(self):
        with isolated_cache():
            db = _new_run_db("c4")
            _seed_trace(db)
            for _ in range(2):
                _insert_tool_call(db,
                                   name="mcp__consensus__search",
                                   started_at=_ago(40))
            for _ in range(3):
                _insert_tool_call(db,
                                   name="mcp__consensus__search",
                                   started_at=_ago(20))
            report = cost_dashboard.collect(window_days=7)
            cs = report["per_server"]["consensus"]
            self.assertEqual(cs["n_7d"], 0)
            self.assertEqual(cs["n_30d"], 3)
            self.assertEqual(cs["n_all"], 5)

    def test_cli_json_and_text(self):
        with isolated_cache() as cache_root:
            db = _new_run_db("c5")
            _seed_trace(db)
            _insert_tool_call(db,
                               name="mcp__consensus__search",
                               started_at=_ago(1))
            runs_root = db.parent
            r_json = subprocess.run(
                [sys.executable, "-m", "lib.cost_dashboard",
                 "--root", str(runs_root), "--format", "json"],
                cwd=str(_REPO),
                capture_output=True, text=True,
            )
            self.assertEqual(r_json.returncode, 0, r_json.stderr)
            payload = json.loads(r_json.stdout)
            self.assertEqual(
                payload["per_server"]["consensus"]["n_all"], 1,
            )
            r_txt = subprocess.run(
                [sys.executable, "-m", "lib.cost_dashboard",
                 "--root", str(runs_root), "--format", "text"],
                cwd=str(_REPO),
                capture_output=True, text=True,
            )
            self.assertEqual(r_txt.returncode, 0, r_txt.stderr)
            self.assertIn("consensus", r_txt.stdout)
            self.assertIn("MCP cost dashboard", r_txt.stdout)

    def test_cli_help(self):
        r = subprocess.run(
            [sys.executable, "-m", "lib.cost_dashboard", "--help"],
            cwd=str(_REPO),
            capture_output=True, text=True,
        )
        self.assertEqual(r.returncode, 0)
        self.assertIn("--format", r.stdout)
        self.assertIn("--window-days", r.stdout)


if __name__ == "__main__":
    raise SystemExit(run_tests(CostDashboardTests))
