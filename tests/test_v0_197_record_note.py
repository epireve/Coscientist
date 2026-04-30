"""v0.197 — db.py record-note subcommand.

Closes dogfood finding #11. Weaver should not insert into notes via raw
SQL — provides a CLI primitive instead.
"""
from __future__ import annotations

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


def _run(cache: Path, *args: str, stdin: str | None = None
         ) -> subprocess.CompletedProcess:
    env = {
        "COSCIENTIST_CACHE_DIR": str(cache),
        "PATH": "/usr/bin:/bin",
    }
    return subprocess.run(
        [sys.executable, str(DB_PY), *args],
        env=env, capture_output=True, text=True, input=stdin,
    )


def _init_run(cache: Path) -> str:
    r = _run(cache, "init", "--question", "test")
    if r.returncode != 0:
        raise RuntimeError(f"init failed: {r.stderr!r}")
    return r.stdout.strip().splitlines()[-1]


def _fetch_notes(cache: Path, run_id: str) -> list[dict]:
    db = cache / "runs" / f"run-{run_id}.db"
    con = sqlite3.connect(db)
    try:
        rows = con.execute(
            "SELECT note_id, run_id, phase_id, author, text, at "
            "FROM notes WHERE run_id=? ORDER BY note_id",
            (run_id,),
        ).fetchall()
    finally:
        con.close()
    return [
        {"note_id": r[0], "run_id": r[1], "phase_id": r[2],
         "author": r[3], "text": r[4], "at": r[5]}
        for r in rows
    ]


class RecordNoteTests(TestCase):
    def test_happy_path(self):
        with isolated_cache() as cache:
            rid = _init_run(cache)
            r = _run(cache, "record-note", "--run-id", rid,
                      "--author", "weaver",
                      "--text", "Tension noted between A and B.")
            self.assertEqual(r.returncode, 0, msg=r.stderr)
            notes = _fetch_notes(cache, rid)
            self.assertEqual(len(notes), 1)
            self.assertEqual(notes[0]["author"], "weaver")
            self.assertEqual(
                notes[0]["text"], "Tension noted between A and B.",
            )
            self.assertIsNone(notes[0]["phase_id"])

    def test_empty_text_rejected(self):
        with isolated_cache() as cache:
            rid = _init_run(cache)
            r = _run(cache, "record-note", "--run-id", rid,
                      "--author", "weaver", "--text", "   ")
            self.assertTrue(r.returncode != 0)

    def test_missing_required_arg_rejected(self):
        with isolated_cache() as cache:
            rid = _init_run(cache)
            # No --text
            r = _run(cache, "record-note", "--run-id", rid,
                      "--author", "weaver")
            self.assertTrue(r.returncode != 0)
            # No --author
            r = _run(cache, "record-note", "--run-id", rid,
                      "--text", "x")
            self.assertTrue(r.returncode != 0)

    def test_stdin_multiline(self):
        with isolated_cache() as cache:
            rid = _init_run(cache)
            payload = "line one\nline two\nline three"
            r = _run(cache, "record-note", "--run-id", rid,
                      "--author", "weaver", "--text", "-",
                      stdin=payload)
            self.assertEqual(r.returncode, 0, msg=r.stderr)
            notes = _fetch_notes(cache, rid)
            self.assertEqual(len(notes), 1)
            self.assertEqual(notes[0]["text"], payload)

    def test_phase_id_optional(self):
        with isolated_cache() as cache:
            rid = _init_run(cache)
            # Without --phase-id (already covered in happy path).
            # With --phase-id (must resolve as integer in DB).
            db = cache / "runs" / f"run-{rid}.db"
            con = sqlite3.connect(db)
            phase_row_id = con.execute(
                "SELECT phase_id FROM phases WHERE run_id=? "
                "AND name='scout'", (rid,),
            ).fetchone()[0]
            con.close()
            r = _run(cache, "record-note", "--run-id", rid,
                      "--author", "weaver",
                      "--text", "phase-tagged note",
                      "--phase-id", str(phase_row_id))
            self.assertEqual(r.returncode, 0, msg=r.stderr)
            notes = _fetch_notes(cache, rid)
            self.assertEqual(notes[0]["phase_id"], phase_row_id)


if __name__ == "__main__":
    sys.exit(run_tests(RecordNoteTests))
