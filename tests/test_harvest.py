"""v0.46.1 tests for deep-research/scripts/harvest.py (Plan 5 Stage 2)."""

from tests import _shim  # noqa: F401

import json
import subprocess
import sys
from pathlib import Path

from tests.harness import TestCase, isolated_cache, run_tests

_ROOT = Path(__file__).resolve().parent.parent
HARVEST = _ROOT / ".claude/skills/deep-research/scripts/harvest.py"


def _run(*args: str, stdin: str = "") -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(HARVEST), *args],
        input=stdin, capture_output=True, text=True,
    )


def _sample_mcp_results() -> list[dict]:
    return [
        {"source": "consensus", "title": "Paper Alpha",
         "doi": "10.1/a", "year": 2024, "citation_count": 100,
         "authors": ["A1"], "abstract": "abs1"},
        {"source": "semantic-scholar", "title": "Paper Alpha",
         "doi": "10.1/a", "year": 2024, "citation_count": 100,
         "authors": ["A1"]},  # dup → merge
        {"source": "academic", "title": "Paper Beta",
         "arxiv_id": "2401.0001", "year": 2023, "authors": ["B1"]},
        {"source": "consensus", "title": "Paper Gamma",
         "year": 2025, "authors": ["C1"], "citation_count": 5},
    ]


class WriteTests(TestCase):
    def test_write_via_stdin_dedups_and_persists(self):
        with isolated_cache():
            r = _run(
                "write", "--run-id", "rT1",
                "--persona", "scout", "--phase", "phase0",
                "--query", "test question",
                stdin=json.dumps(_sample_mcp_results()),
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            out = json.loads(r.stdout)
            self.assertEqual(out["raw_count"], 4)
            self.assertEqual(out["deduped_count"], 3)
            self.assertEqual(out["kept_count"], 3)
            # Confirm shortlist file was written
            from lib.persona_input import load
            inp = load("rT1", "scout", "phase0")
            self.assertEqual(inp.query, "test question")
            self.assertEqual(len(inp.results), 3)

    def test_write_via_input_file(self):
        with isolated_cache() as cache_dir:
            input_file = cache_dir / "raw.json"
            input_file.write_text(json.dumps(_sample_mcp_results()))
            r = _run(
                "write", "--run-id", "rT2",
                "--persona", "cartographer", "--phase", "phase1",
                "--query", "q",
                "--input-file", str(input_file),
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            from lib.persona_input import exists
            self.assertTrue(exists("rT2", "cartographer", "phase1"))

    def test_write_results_object_form_accepted(self):
        """Orchestrator may pass {results: [...]} instead of bare array."""
        with isolated_cache():
            r = _run(
                "write", "--run-id", "rT3",
                "--persona", "scout", "--phase", "phase0",
                "--query", "q",
                stdin=json.dumps({"results": _sample_mcp_results()}),
            )
            self.assertEqual(r.returncode, 0, r.stderr)

    def test_write_max_papers_caps_results(self):
        with isolated_cache():
            r = _run(
                "write", "--run-id", "rT4",
                "--persona", "scout", "--phase", "phase0",
                "--query", "q", "--max-papers", "2",
                stdin=json.dumps(_sample_mcp_results()),
            )
            out = json.loads(r.stdout)
            self.assertEqual(out["kept_count"], 2)
            self.assertEqual(out["budget"]["max_papers"], 2)

    def test_write_unknown_persona_rejected(self):
        with isolated_cache():
            r = _run(
                "write", "--run-id", "rT5",
                "--persona", "nonexistent_persona", "--phase", "phase0",
                "--query", "q",
                stdin=json.dumps([]),
            )
            self.assertTrue(r.returncode != 0)

    def test_write_empty_input_writes_empty_shortlist(self):
        with isolated_cache():
            r = _run(
                "write", "--run-id", "rT6",
                "--persona", "scout", "--phase", "phase0",
                "--query", "q",
                stdin="[]",
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            out = json.loads(r.stdout)
            self.assertEqual(out["kept_count"], 0)

    def test_write_default_budget_applied(self):
        with isolated_cache():
            r = _run(
                "write", "--run-id", "rT7",
                "--persona", "cartographer", "--phase", "phase1",
                "--query", "q",
                stdin=json.dumps(_sample_mcp_results()),
            )
            out = json.loads(r.stdout)
            # PERSONA_BUDGETS["cartographer"]["max_papers"] = 30
            self.assertEqual(out["budget"]["max_papers"], 30)

    def test_write_invalid_json_rejected(self):
        with isolated_cache():
            r = _run(
                "write", "--run-id", "rT8",
                "--persona", "scout", "--phase", "phase0",
                "--query", "q",
                stdin="{not valid",
            )
            self.assertTrue(r.returncode != 0)

    def test_write_non_array_input_rejected(self):
        with isolated_cache():
            r = _run(
                "write", "--run-id", "rT9",
                "--persona", "scout", "--phase", "phase0",
                "--query", "q",
                stdin='"a string is not an array"',
            )
            self.assertTrue(r.returncode != 0)
            self.assertIn("array", r.stderr)


class StatusTests(TestCase):
    def test_status_lists_all_shortlists(self):
        with isolated_cache():
            for persona, phase in (
                ("scout", "phase0"),
                ("cartographer", "phase1"),
                ("chronicler", "phase1"),
            ):
                _run(
                    "write", "--run-id", "rS1",
                    "--persona", persona, "--phase", phase,
                    "--query", "q",
                    stdin=json.dumps(_sample_mcp_results()[:1]),
                )
            r = _run("status", "--run-id", "rS1")
            self.assertEqual(r.returncode, 0, r.stderr)
            out = json.loads(r.stdout)
            self.assertEqual(out["count"], 3)
            personas = {x["persona"] for x in out["shortlists"]}
            self.assertEqual(personas, {"scout", "cartographer", "chronicler"})

    def test_status_empty_run_returns_empty(self):
        with isolated_cache():
            r = _run("status", "--run-id", "rS_empty")
            self.assertEqual(r.returncode, 0, r.stderr)
            out = json.loads(r.stdout)
            self.assertEqual(out["count"], 0)


class ShowTests(TestCase):
    def test_show_returns_full_shortlist(self):
        with isolated_cache():
            _run(
                "write", "--run-id", "rSh1",
                "--persona", "scout", "--phase", "phase0",
                "--query", "the question",
                stdin=json.dumps(_sample_mcp_results()),
            )
            r = _run(
                "show", "--run-id", "rSh1",
                "--persona", "scout", "--phase", "phase0",
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            out = json.loads(r.stdout)
            self.assertEqual(out["query"], "the question")
            self.assertEqual(out["persona"], "scout")
            self.assertEqual(len(out["results"]), 3)

    def test_show_missing_shortlist_errors(self):
        with isolated_cache():
            r = _run(
                "show", "--run-id", "missing",
                "--persona", "scout", "--phase", "phase0",
            )
            self.assertTrue(r.returncode != 0)
            self.assertIn("no shortlist", r.stderr)


class CliTests(TestCase):
    def test_no_subcommand_errors(self):
        r = _run()
        self.assertTrue(r.returncode != 0)


if __name__ == "__main__":
    sys.exit(run_tests(WriteTests, StatusTests, ShowTests, CliTests))
