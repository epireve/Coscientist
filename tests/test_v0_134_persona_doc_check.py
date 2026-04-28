"""v0.134 — persona doc static check tests."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from lib import persona_doc_check, persona_schema
from tests.harness import TestCase, run_tests

_REPO = Path(__file__).resolve().parents[1]


class ExtractJsonExampleTests(TestCase):
    def test_extracts_first_block(self):
        md = "intro\n```json\n{\"a\": 1}\n```\nmore"
        out = persona_doc_check.extract_json_example(md)
        self.assertEqual(out, {"a": 1})

    def test_no_block_returns_none(self):
        out = persona_doc_check.extract_json_example("plain text")
        self.assertIsNone(out)

    def test_placeholder_substitution(self):
        md = "```json\n{\"x\": <int>, \"y\": <cid>}\n```"
        out = persona_doc_check.extract_json_example(md)
        self.assertEqual(out, {"x": None, "y": None})

    def test_invalid_json_returns_none(self):
        md = "```json\n{not json{\n```"
        out = persona_doc_check.extract_json_example(md)
        self.assertIsNone(out)

    def test_strips_line_comments(self):
        md = "```json\n{\"a\": 1 // comment\n}\n```"
        out = persona_doc_check.extract_json_example(md)
        self.assertEqual(out, {"a": 1})


class CheckPersonaTests(TestCase):
    def test_all_registered_personas_pass(self):
        """Regression: every persona in SCHEMAS must have a
        valid JSON example block in its .md."""
        for agent in persona_schema.SCHEMAS:
            r = persona_doc_check.check_persona(agent)
            self.assertTrue(
                r["ok"],
                f"{agent} drifted: {r['error']}",
            )

    def test_unknown_persona_skipped_ok(self):
        """Personas without a registered schema return ok=True
        with skip note."""
        r = persona_doc_check.check_persona("debate-pro")
        self.assertTrue(r["ok"])
        self.assertIn("no schema", r["error"])

    def test_missing_md_reports_error(self):
        r = persona_doc_check.check_persona("nonexistent-persona")
        self.assertFalse(r["ok"])
        self.assertIn("missing", r["error"])


class CheckAllTests(TestCase):
    def test_returns_one_per_schema_persona(self):
        out = persona_doc_check.check_all()
        names = {r["agent"] for r in out}
        self.assertEqual(names, set(persona_schema.SCHEMAS.keys()))

    def test_all_pass_when_docs_aligned(self):
        out = persona_doc_check.check_all()
        for r in out:
            self.assertTrue(r["ok"], r)


class CliTests(TestCase):
    def test_cli_clean_exit_0(self):
        r = subprocess.run(
            [sys.executable, "-m", "lib.persona_doc_check"],
            capture_output=True, text=True, cwd=str(_REPO),
        )
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_cli_json_format(self):
        r = subprocess.run(
            [sys.executable, "-m", "lib.persona_doc_check",
             "--format", "json"],
            capture_output=True, text=True, cwd=str(_REPO),
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertIn("results", out)
        self.assertEqual(out["n_failed"], 0)

    def test_cli_single_agent(self):
        r = subprocess.run(
            [sys.executable, "-m", "lib.persona_doc_check",
             "--agent", "scout", "--format", "json"],
            capture_output=True, text=True, cwd=str(_REPO),
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual(len(out["results"]), 1)
        self.assertEqual(out["results"][0]["agent"], "scout")


if __name__ == "__main__":
    raise SystemExit(run_tests(
        ExtractJsonExampleTests, CheckPersonaTests,
        CheckAllTests, CliTests,
    ))
