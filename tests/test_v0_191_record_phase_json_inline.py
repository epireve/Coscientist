"""v0.191 — db.py record-phase --output-json inline-vs-file heuristic."""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

from tests.harness import TestCase, isolated_cache, run_tests

REPO_ROOT = Path(__file__).resolve().parents[1]
DB_PY = (
    REPO_ROOT / ".claude" / "skills" / "deep-research"
    / "scripts" / "db.py"
)


def _run(cache: Path, *args: str) -> subprocess.CompletedProcess:
    env = {
        "COSCIENTIST_CACHE_DIR": str(cache),
        "PATH": "/usr/bin:/bin",
    }
    return subprocess.run(
        [sys.executable, str(DB_PY), *args],
        env=env, capture_output=True, text=True,
    )


def _init_run(cache: Path) -> str:
    r = _run(
        cache, "init",
        "--question", "test question",
    )
    if r.returncode != 0:
        raise RuntimeError(
            f"init failed: stdout={r.stdout!r} stderr={r.stderr!r}"
        )
    return r.stdout.strip().splitlines()[-1]


def _phase_output(cache: Path, run_id: str, phase: str) -> str | None:
    db = cache / "runs" / f"run-{run_id}.db"
    con = sqlite3.connect(db)
    try:
        row = con.execute(
            "SELECT output_json FROM phases "
            "WHERE run_id=? AND name=?",
            (run_id, phase),
        ).fetchone()
    finally:
        con.close()
    return row[0] if row else None


class RecordPhaseJsonInlineTests(TestCase):
    def test_inline_json_object_accepted(self):
        with isolated_cache() as cache:
            rid = _init_run(cache)
            r = _run(
                cache, "record-phase",
                "--run-id", rid, "--phase", "scout",
                "--complete",
                "--output-json", '{"papers_seeded": 6}',
            )
            self.assertEqual(
                r.returncode, 0,
                msg=f"stderr={r.stderr!r}",
            )
            stored = _phase_output(cache, rid, "scout")
            self.assertEqual(json.loads(stored), {"papers_seeded": 6})

    def test_inline_json_array_accepted(self):
        with isolated_cache() as cache:
            rid = _init_run(cache)
            r = _run(
                cache, "record-phase",
                "--run-id", rid, "--phase", "scout",
                "--complete",
                "--output-json", '[1, 2, 3]',
            )
            self.assertEqual(r.returncode, 0, msg=r.stderr)
            stored = _phase_output(cache, rid, "scout")
            self.assertEqual(json.loads(stored), [1, 2, 3])

    def test_file_path_accepted_back_compat(self):
        with isolated_cache() as cache:
            rid = _init_run(cache)
            tmp = cache / "out.json"
            tmp.write_text(json.dumps({"x": 1}))
            r = _run(
                cache, "record-phase",
                "--run-id", rid, "--phase", "scout",
                "--complete",
                "--output-json", str(tmp),
            )
            self.assertEqual(r.returncode, 0, msg=r.stderr)
            stored = _phase_output(cache, rid, "scout")
            self.assertEqual(json.loads(stored), {"x": 1})

    def test_whitespace_before_brace_accepted(self):
        with isolated_cache() as cache:
            rid = _init_run(cache)
            r = _run(
                cache, "record-phase",
                "--run-id", rid, "--phase", "scout",
                "--complete",
                "--output-json", '   {"a": "b"}',
            )
            self.assertEqual(r.returncode, 0, msg=r.stderr)
            stored = _phase_output(cache, rid, "scout")
            self.assertEqual(json.loads(stored), {"a": "b"})

    def test_garbage_rejected_with_clear_error(self):
        with isolated_cache() as cache:
            rid = _init_run(cache)
            r = _run(
                cache, "record-phase",
                "--run-id", rid, "--phase", "scout",
                "--complete",
                "--output-json", "not-a-file-not-json",
            )
            self.assertTrue(r.returncode != 0)
            self.assertIn("--output-json", r.stderr)

    def test_empty_string_rejected(self):
        with isolated_cache() as cache:
            rid = _init_run(cache)
            r = _run(
                cache, "record-phase",
                "--run-id", rid, "--phase", "scout",
                "--complete",
                "--output-json", "   ",
            )
            self.assertTrue(r.returncode != 0)

    def test_quality_artifact_inline_json_accepted(self):
        with isolated_cache() as cache:
            rid = _init_run(cache)
            # Use scout phase which has a rubric registered.
            r = _run(
                cache, "record-phase",
                "--run-id", rid, "--phase", "scout",
                "--complete",
                "--output-json", '{"papers_seeded": 1}',
                "--quality-artifact", '{"shortlist": []}',
            )
            # Both flags should accept inline JSON. Failure here
            # would indicate quality-artifact still treats arg as
            # a path.
            self.assertEqual(r.returncode, 0, msg=r.stderr)


if __name__ == "__main__":
    raise SystemExit(run_tests(RecordPhaseJsonInlineTests))
