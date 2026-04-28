"""v0.129 — field-trends time-series tests."""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from lib.cache import cache_root
from tests.harness import TestCase, isolated_cache, run_tests

_REPO = Path(__file__).resolve().parents[1]
_TRENDS = (_REPO / ".claude" / "skills" / "field-trends-analyzer"
            / "scripts" / "trends.py")


def _new_project_db(pid: str) -> Path:
    pdir = cache_root() / "projects" / pid
    pdir.mkdir(parents=True, exist_ok=True)
    db = pdir / "project.db"
    schema = (_REPO / "lib" / "sqlite_schema.sql").read_text()
    con = sqlite3.connect(db)
    con.executescript(schema)
    con.close()
    from lib.migrations import ensure_current
    ensure_current(db)
    return db


def _add_concept(db: Path, label: str) -> str:
    nid = f"concept:{label}"
    con = sqlite3.connect(db)
    try:
        with con:
            con.execute(
                "INSERT OR IGNORE INTO graph_nodes "
                "(node_id, kind, label, created_at) "
                "VALUES (?, 'concept', ?, ?)",
                (nid, label, datetime.now(UTC).isoformat()),
            )
    finally:
        con.close()
    return nid


def _add_paper_about(db: Path, paper_id: str, concept_id: str,
                     created_at: str):
    con = sqlite3.connect(db)
    try:
        with con:
            con.execute(
                "INSERT OR IGNORE INTO graph_nodes "
                "(node_id, kind, label, created_at) "
                "VALUES (?, 'paper', ?, ?)",
                (f"paper:{paper_id}", paper_id, created_at),
            )
            con.execute(
                "INSERT INTO graph_edges "
                "(from_node, to_node, relation, created_at) "
                "VALUES (?, ?, 'about', ?)",
                (f"paper:{paper_id}", concept_id, created_at),
            )
    finally:
        con.close()


def _run_trends(*args: str):
    return subprocess.run(
        [sys.executable, str(_TRENDS), *args],
        capture_output=True, text=True, cwd=str(_REPO),
    )


class SeriesTests(TestCase):
    def test_no_concepts_empty_result(self):
        with isolated_cache():
            _new_project_db("p1")
            r = _run_trends("series", "--project-id", "p1",
                             "--window-days", "30", "--buckets", "3")
            self.assertEqual(r.returncode, 0, r.stderr)
            out = json.loads(r.stdout)
            self.assertEqual(out["concepts"], [])

    def test_buckets_count_matches(self):
        with isolated_cache():
            db = _new_project_db("p2")
            cid = _add_concept(db, "scaling-laws")
            now = datetime.now(UTC)
            for i in range(6):
                ts = (now - timedelta(days=i * 30)).isoformat()
                _add_paper_about(db, f"p{i}", cid, ts)
            r = _run_trends("series", "--project-id", "p2",
                             "--window-days", "365", "--buckets", "12")
            self.assertEqual(r.returncode, 0, r.stderr)
            out = json.loads(r.stdout)
            self.assertEqual(out["buckets"], 12)
            scaling = next(
                c for c in out["concepts"]
                if c["concept"] == "scaling-laws"
            )
            self.assertEqual(len(scaling["buckets"]), 12)

    def test_rising_trend_detected(self):
        with isolated_cache():
            db = _new_project_db("p3")
            cid = _add_concept(db, "rising")
            now = datetime.now(UTC)
            # 1 paper in first half (300 days ago), 6 in second half
            _add_paper_about(
                db, "old1", cid,
                (now - timedelta(days=300)).isoformat(),
            )
            for i in range(6):
                ts = (now - timedelta(days=30 + i * 10)).isoformat()
                _add_paper_about(db, f"new{i}", cid, ts)
            r = _run_trends("series", "--project-id", "p3",
                             "--window-days", "365", "--buckets", "12")
            self.assertEqual(r.returncode, 0, r.stderr)
            out = json.loads(r.stdout)
            rising = next(
                c for c in out["concepts"] if c["concept"] == "rising"
            )
            self.assertEqual(rising["trend"], "rising")
            self.assertGreater(
                rising["last_half_count"],
                rising["first_half_count"],
            )

    def test_top_limit_respected(self):
        with isolated_cache():
            db = _new_project_db("p4")
            now = datetime.now(UTC)
            for i in range(5):
                cid = _add_concept(db, f"c{i}")
                for j in range(i + 1):
                    ts = (now - timedelta(days=10 * j)).isoformat()
                    _add_paper_about(
                        db, f"c{i}_p{j}", cid, ts,
                    )
            r = _run_trends("series", "--project-id", "p4",
                             "--window-days", "365",
                             "--buckets", "12", "--top", "2")
            self.assertEqual(r.returncode, 0, r.stderr)
            out = json.loads(r.stdout)
            self.assertEqual(len(out["concepts"]), 2)

    def test_bucket_starts_in_output(self):
        with isolated_cache():
            db = _new_project_db("p5")
            cid = _add_concept(db, "x")
            _add_paper_about(
                db, "p1", cid,
                datetime.now(UTC).isoformat(),
            )
            r = _run_trends("series", "--project-id", "p5",
                             "--buckets", "4")
            self.assertEqual(r.returncode, 0, r.stderr)
            out = json.loads(r.stdout)
            self.assertEqual(len(out["bucket_starts"]), 4)


if __name__ == "__main__":
    raise SystemExit(run_tests(SeriesTests))
