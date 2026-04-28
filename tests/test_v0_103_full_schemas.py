"""v0.103 — full persona schemas + record-phase split tests."""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

from lib import persona_schema
from lib.cache import run_db_path
from tests.harness import TestCase, isolated_cache, run_tests

_REPO = Path(__file__).resolve().parents[1]


def _write_json(payload, suffix=".json"):
    tf = tempfile.NamedTemporaryFile(
        mode="w", suffix=suffix, delete=False,
    )
    json.dump(payload, tf)
    tf.close()
    return Path(tf.name)


class FullSchemaTests(TestCase):
    def test_all_personas_registered(self):
        expected = {
            "scout", "surveyor", "architect", "synthesist", "weaver",
            "cartographer", "chronicler", "inquisitor", "visionary",
            "steward",
        }
        self.assertTrue(
            expected.issubset(set(persona_schema.SCHEMAS.keys())),
            f"missing: {expected - set(persona_schema.SCHEMAS.keys())}",
        )

    def test_scout_dict_shape(self):
        p = _write_json({
            "papers_seeded": 50,
            "shortlist_size": 50,
            "duplicates_dropped": 5,
            "stopped_because": "ok",
        })
        try:
            res = persona_schema.validate("scout", p)
            self.assertTrue(res.ok, res.error)
        finally:
            p.unlink()

    def test_cartographer_passes(self):
        p = _write_json({
            "phase": "cartographer",
            "summary": "Field has clear ancestry.",
            "seminals": [],
        })
        try:
            res = persona_schema.validate("cartographer", p)
            self.assertTrue(res.ok, res.error)
        finally:
            p.unlink()

    def test_inquisitor_missing_evaluations(self):
        p = _write_json({
            "phase": "inquisitor",
            "summary": "x",
            # no evaluations
        })
        try:
            res = persona_schema.validate("inquisitor", p)
            self.assertFalse(res.ok)
            self.assertIn("evaluations", res.error)
        finally:
            p.unlink()

    def test_steward_full_shape(self):
        p = _write_json({
            "phase": "steward",
            "brief_path": "/tmp/brief.md",
            "map_path": "/tmp/map.md",
            "claims_cited": 10,
            "papers_cited": 30,
            "eval_passed": True,
        })
        try:
            res = persona_schema.validate("steward", p)
            self.assertTrue(res.ok, res.error)
        finally:
            p.unlink()


class ListCliTests(TestCase):
    def test_list_subcommand(self):
        r = subprocess.run(
            [sys.executable, "-m", "lib.persona_schema", "list"],
            capture_output=True, text=True, cwd=str(_REPO),
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertIn("scout", out)
        self.assertIn("steward", out)
        self.assertEqual(out["scout"]["top_kind"], "dict")
        self.assertGreater(len(out), 5)


class RecordPhaseSplitTests(TestCase):
    """v0.103 — schema gate uses output_json; rubric uses
    --quality-artifact only (no fallback)."""

    def test_quality_artifact_separate_from_output_json(self):
        with isolated_cache():
            db_py = (_REPO / ".claude" / "skills" / "deep-research"
                     / "scripts" / "db.py")
            r = subprocess.run(
                [sys.executable, str(db_py), "init",
                 "--question", "test"],
                capture_output=True, text=True, cwd=str(_REPO),
            )
            rid = r.stdout.strip().split()[-1]
            # output_json: scout dict shape (passes schema)
            output = _write_json({
                "papers_seeded": 50,
                "shortlist_size": 50,
                "duplicates_dropped": 0,
                "stopped_because": "ok",
            })
            # quality-artifact: list-of-papers (rubric target)
            sources = ["s2", "consensus", "arxiv"]
            quality = _write_json([
                {"canonical_id": f"p{i}", "title": f"T{i}",
                 "source": sources[i % 3]}
                for i in range(30)
            ])
            try:
                for flag in ("--start", "--complete"):
                    args = [sys.executable, str(db_py),
                            "record-phase", "--run-id", rid,
                            "--phase", "scout", flag]
                    if flag == "--complete":
                        args += ["--output-json", str(output),
                                  "--quality-artifact", str(quality)]
                    r = subprocess.run(args, capture_output=True,
                                        text=True, cwd=str(_REPO))
                    self.assertEqual(r.returncode, 0, r.stderr)
                db = run_db_path(rid)
                con = sqlite3.connect(db)
                try:
                    n_quality = con.execute(
                        "SELECT COUNT(*) FROM agent_quality "
                        "WHERE run_id=?", (rid,),
                    ).fetchone()[0]
                    n_schema_err = con.execute(
                        "SELECT COUNT(*) FROM spans "
                        "WHERE trace_id=? AND name=?",
                        (rid, "schema-scout"),
                    ).fetchone()[0]
                finally:
                    con.close()
                # Quality row written from quality-artifact
                self.assertEqual(n_quality, 1)
                # Schema gate did NOT fire (output_json valid)
                self.assertEqual(n_schema_err, 0)
            finally:
                output.unlink()
                quality.unlink()

    def test_no_quality_artifact_no_rubric(self):
        with isolated_cache():
            db_py = (_REPO / ".claude" / "skills" / "deep-research"
                     / "scripts" / "db.py")
            r = subprocess.run(
                [sys.executable, str(db_py), "init",
                 "--question", "test"],
                capture_output=True, text=True, cwd=str(_REPO),
            )
            rid = r.stdout.strip().split()[-1]
            output = _write_json({
                "papers_seeded": 50,
                "shortlist_size": 50,
                "duplicates_dropped": 0,
                "stopped_because": "ok",
            })
            try:
                for flag in ("--start", "--complete"):
                    args = [sys.executable, str(db_py),
                            "record-phase", "--run-id", rid,
                            "--phase", "scout", flag]
                    if flag == "--complete":
                        args += ["--output-json", str(output)]
                    r = subprocess.run(args, capture_output=True,
                                        text=True, cwd=str(_REPO))
                    self.assertEqual(r.returncode, 0, r.stderr)
                db = run_db_path(rid)
                con = sqlite3.connect(db)
                try:
                    n_quality = con.execute(
                        "SELECT COUNT(*) FROM agent_quality "
                        "WHERE run_id=?", (rid,),
                    ).fetchone()[0]
                finally:
                    con.close()
                # No --quality-artifact → no rubric run
                self.assertEqual(n_quality, 0)
            finally:
                output.unlink()


if __name__ == "__main__":
    raise SystemExit(run_tests(
        FullSchemaTests, ListCliTests, RecordPhaseSplitTests,
    ))
