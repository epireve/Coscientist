"""v0.102 — persona output schema validator tests."""
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


class ScoutSchemaTests(TestCase):
    """v0.103 — scout shape corrected to dict (papers_seeded etc)."""

    def test_valid_scout_passes(self):
        d = {
            "papers_seeded": 10, "shortlist_size": 10,
            "duplicates_dropped": 0, "stopped_because": "ok",
        }
        p = _write_json(d)
        try:
            res = persona_schema.validate("scout", p)
            self.assertTrue(res.ok, res.error)
        finally:
            p.unlink()

    def test_scout_missing_field_rejected(self):
        d = {"papers_seeded": 10}  # missing rest
        p = _write_json(d)
        try:
            res = persona_schema.validate("scout", p)
            self.assertFalse(res.ok)
            self.assertIn("missing", res.error)
        finally:
            p.unlink()

    def test_scout_list_top_rejected(self):
        p = _write_json([{"papers_seeded": 10}])
        try:
            res = persona_schema.validate("scout", p)
            self.assertFalse(res.ok)
            self.assertIn("expected dict", res.error)
        finally:
            p.unlink()


class WeaverDictSchemaTests(TestCase):
    """v0.103 — weaver shape corrected to consensus/tensions."""

    def test_valid_weaver_passes(self):
        p = _write_json({
            "phase": "weaver",
            "summary": "x",
            "sharpened_question": "y",
            "consensus": [],
            "tensions": [],
        })
        try:
            res = persona_schema.validate("weaver", p)
            self.assertTrue(res.ok, res.error)
        finally:
            p.unlink()

    def test_weaver_missing_key_rejected(self):
        p = _write_json({"phase": "weaver", "summary": "x"})
        try:
            res = persona_schema.validate("weaver", p)
            self.assertFalse(res.ok)
            self.assertIn("missing", res.error)
        finally:
            p.unlink()

    def test_weaver_list_top_rejected(self):
        p = _write_json([])
        try:
            res = persona_schema.validate("weaver", p)
            self.assertFalse(res.ok)
            self.assertIn("expected dict", res.error)
        finally:
            p.unlink()


class UnknownAgentTests(TestCase):
    def test_unknown_agent_passes_with_payload(self):
        p = _write_json({"anything": "goes"})
        try:
            res = persona_schema.validate("nobody", p)
            self.assertTrue(res.ok)
            self.assertEqual(res.payload, {"anything": "goes"})
        finally:
            p.unlink()


class FileErrorTests(TestCase):
    def test_missing_file(self):
        res = persona_schema.validate(
            "scout", Path("/nonexistent/path.json"),
        )
        self.assertFalse(res.ok)
        self.assertIn("not found", res.error)

    def test_invalid_json(self):
        tf = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False,
        )
        tf.write("not json {")
        tf.close()
        try:
            res = persona_schema.validate("scout", Path(tf.name))
            self.assertFalse(res.ok)
            self.assertIn("JSON parse error", res.error)
        finally:
            Path(tf.name).unlink()


class CliTests(TestCase):
    def test_cli_passes(self):
        d = {
            "papers_seeded": 10, "shortlist_size": 10,
            "duplicates_dropped": 0, "stopped_because": "ok",
        }
        p = _write_json(d)
        try:
            r = subprocess.run(
                [sys.executable, "-m", "lib.persona_schema",
                 "validate",
                 "--agent", "scout",
                 "--artifact-path", str(p)],
                capture_output=True, text=True, cwd=str(_REPO),
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn('"ok": true', r.stdout)
        finally:
            p.unlink()

    def test_cli_fails_with_exit_1(self):
        p = _write_json({})  # missing all required fields
        try:
            r = subprocess.run(
                [sys.executable, "-m", "lib.persona_schema",
                 "validate",
                 "--agent", "scout",
                 "--artifact-path", str(p)],
                capture_output=True, text=True, cwd=str(_REPO),
            )
            self.assertEqual(r.returncode, 1)
            self.assertIn('"ok": false', r.stdout)
        finally:
            p.unlink()


class IntegrationWithAutoQualityTests(TestCase):
    """v0.102 — invalid shape skips rubric, emits schema-gate span."""

    def test_invalid_shape_emits_schema_error_span(self):
        with isolated_cache():
            db_py = (_REPO / ".claude" / "skills" / "deep-research"
                     / "scripts" / "db.py")
            r = subprocess.run(
                [sys.executable, str(db_py), "init",
                 "--question", "test"],
                capture_output=True, text=True, cwd=str(_REPO),
            )
            rid = r.stdout.strip().split()[-1]
            # Malformed scout output: missing 'source' field.
            bad = _write_json([
                {"canonical_id": "p1", "title": "T"},
            ])
            try:
                for flag in ("--start", "--complete"):
                    args = [sys.executable, str(db_py),
                            "record-phase", "--run-id", rid,
                            "--phase", "scout", flag]
                    if flag == "--complete":
                        args += ["--output-json", str(bad)]
                    subprocess.run(args, capture_output=True,
                                    text=True, cwd=str(_REPO),
                                    check=True)
                db = run_db_path(rid)
                con = sqlite3.connect(db)
                try:
                    # No agent_quality row should exist.
                    n_quality = con.execute(
                        "SELECT COUNT(*) FROM agent_quality "
                        "WHERE run_id=?", (rid,),
                    ).fetchone()[0]
                    # Schema-gate span should exist.
                    n_schema = con.execute(
                        "SELECT COUNT(*) FROM spans "
                        "WHERE trace_id=? AND name=?",
                        (rid, "schema-scout"),
                    ).fetchone()[0]
                finally:
                    con.close()
                self.assertEqual(n_quality, 0)
                self.assertEqual(n_schema, 1)
            finally:
                bad.unlink()


if __name__ == "__main__":
    raise SystemExit(run_tests(
        ScoutSchemaTests, WeaverDictSchemaTests,
        UnknownAgentTests, FileErrorTests, CliTests,
        IntegrationWithAutoQualityTests,
    ))
