"""v0.46 tests for lib.persona_input."""

import json
import sys

from tests import _shim  # noqa: F401
from tests.harness import TestCase, isolated_cache, run_tests


class RoundTripTests(TestCase):
    def test_save_then_load_preserves_fields(self):
        with isolated_cache():
            from lib.persona_input import PersonaInput, load, save
            inp = PersonaInput(
                run_id="r1", persona="social", phase="phase0",
                query="how does X cause Y",
                results=[{"source": "consensus", "title": "P1", "year": 2024}],
                budget={"max_papers": 50},
                harvested_by="orchestrator",
                notes="6 angles harvested",
            )
            save(inp)
            out = load("r1", "social", "phase0")
            self.assertEqual(out.run_id, "r1")
            self.assertEqual(out.persona, "social")
            self.assertEqual(out.phase, "phase0")
            self.assertEqual(out.query, "how does X cause Y")
            self.assertEqual(len(out.results), 1)
            self.assertEqual(out.results[0]["title"], "P1")
            self.assertEqual(out.budget, {"max_papers": 50})
            self.assertEqual(out.notes, "6 angles harvested")

    def test_save_writes_atomic(self):
        """The tmp + rename pattern: no half-written file ever lands at
        the final path."""
        with isolated_cache():
            from lib.persona_input import PersonaInput, save
            inp = PersonaInput("r2", "grounder", "phase1",
                                query="q", results=[{"x": 1}])
            path = save(inp)
            # No .json.tmp left behind
            tmp = path.with_suffix(".json.tmp")
            self.assertFalse(tmp.exists())
            # Final file is parseable JSON
            json.loads(path.read_text())

    def test_save_overwrites_existing(self):
        with isolated_cache():
            from lib.persona_input import PersonaInput, load, save
            save(PersonaInput("r3", "social", "p0", query="q", results=[]))
            save(PersonaInput("r3", "social", "p0", query="q",
                               results=[{"a": 1}]))
            self.assertEqual(len(load("r3", "social", "p0").results), 1)

    def test_harvested_at_auto_filled(self):
        with isolated_cache():
            from lib.persona_input import PersonaInput, load, save
            save(PersonaInput("r4", "social", "p0", query="q", results=[]))
            out = load("r4", "social", "p0")
            self.assertGreater(len(out.harvested_at), 10)


class ErrorHandlingTests(TestCase):
    def test_load_missing_file_errors(self):
        with isolated_cache():
            from lib.persona_input import PersonaInputError, load
            try:
                load("nope", "social", "p0")
            except PersonaInputError as e:
                self.assertIn("no shortlist", str(e))
                return
            raise AssertionError("expected PersonaInputError")

    def test_load_corrupt_json_errors(self):
        with isolated_cache():
            from lib.persona_input import (
                PersonaInputError,
                input_path,
                load,
            )
            p = input_path("rc", "social", "p0")
            p.write_text("{not valid json")
            try:
                load("rc", "social", "p0")
            except PersonaInputError as e:
                self.assertIn("corrupt shortlist", str(e))
                return
            raise AssertionError("expected PersonaInputError")

    def test_load_schema_version_mismatch_errors(self):
        with isolated_cache():
            from lib.persona_input import (
                PersonaInputError,
                input_path,
                load,
            )
            p = input_path("rsv", "social", "p0")
            p.write_text(json.dumps({
                "schema_version": 999,
                "run_id": "rsv", "persona": "social", "phase": "p0",
                "query": "q", "results": [],
            }))
            try:
                load("rsv", "social", "p0")
            except PersonaInputError as e:
                self.assertIn("schema_version", str(e))
                return
            raise AssertionError("expected PersonaInputError")

    def test_load_missing_required_field_errors(self):
        with isolated_cache():
            from lib.persona_input import (
                SCHEMA_VERSION,
                PersonaInputError,
                input_path,
                load,
            )
            p = input_path("rmf", "social", "p0")
            p.write_text(json.dumps({
                "schema_version": SCHEMA_VERSION,
                "run_id": "rmf", "persona": "social", "phase": "p0",
                # missing query + results
            }))
            try:
                load("rmf", "social", "p0")
            except PersonaInputError as e:
                self.assertIn("missing required", str(e))
                return
            raise AssertionError("expected PersonaInputError")

    def test_load_results_not_list_errors(self):
        with isolated_cache():
            from lib.persona_input import (
                SCHEMA_VERSION,
                PersonaInputError,
                input_path,
                load,
            )
            p = input_path("rl", "social", "p0")
            p.write_text(json.dumps({
                "schema_version": SCHEMA_VERSION,
                "run_id": "rl", "persona": "social", "phase": "p0",
                "query": "q", "results": "not-a-list",
            }))
            try:
                load("rl", "social", "p0")
            except PersonaInputError as e:
                self.assertIn("must be a list", str(e))
                return
            raise AssertionError("expected PersonaInputError")

    def test_input_path_rejects_empty_args(self):
        from lib.persona_input import PersonaInputError, input_path
        for args in (("", "social", "p0"), ("r", "", "p0"), ("r", "x", "")):
            try:
                input_path(*args)
            except PersonaInputError:
                continue
            raise AssertionError(f"expected PersonaInputError for {args!r}")


class DiscoveryTests(TestCase):
    def test_exists_returns_false_when_absent(self):
        with isolated_cache():
            from lib.persona_input import exists
            self.assertFalse(exists("r5", "social", "p0"))

    def test_exists_returns_true_after_save(self):
        with isolated_cache():
            from lib.persona_input import PersonaInput, exists, save
            save(PersonaInput("r6", "social", "p0", query="q", results=[]))
            self.assertTrue(exists("r6", "social", "p0"))

    def test_list_for_run_returns_all_shortlists(self):
        with isolated_cache():
            from lib.persona_input import PersonaInput, list_for_run, save
            save(PersonaInput("r7", "social", "p0", query="q", results=[]))
            save(PersonaInput("r7", "grounder", "p1", query="q", results=[]))
            save(PersonaInput("r7", "historian", "p1", query="q", results=[]))
            paths = list_for_run("r7")
            self.assertEqual(len(paths), 3)
            names = sorted(p.name for p in paths)
            self.assertEqual(names, [
                "grounder-p1.json", "historian-p1.json", "social-p0.json",
            ])

    def test_list_for_run_empty_dir_returns_empty(self):
        with isolated_cache():
            from lib.persona_input import list_for_run
            self.assertEqual(list_for_run("never_used"), [])


class LayoutTests(TestCase):
    def test_input_path_lives_under_run_dir(self):
        with isolated_cache():
            from lib.persona_input import input_path
            p = input_path("r8", "social", "phase0")
            self.assertEqual(p.name, "social-phase0.json")
            self.assertEqual(p.parent.name, "inputs")
            self.assertEqual(p.parent.parent.name, "run-r8")


if __name__ == "__main__":
    sys.exit(run_tests(
        RoundTripTests, ErrorHandlingTests, DiscoveryTests, LayoutTests,
    ))
