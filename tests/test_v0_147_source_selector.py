"""v0.147 — source_selector tests."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from lib.source_selector import call_budget, select_source
from tests.harness import TestCase, run_tests


class SeedShortCircuitTests(TestCase):
    def test_seed_always_picks_openalex(self):
        for phase in ("discovery", "ingestion", "enrichment", "graph-walk"):
            r = select_source(phase=phase, has_seed=True)
            self.assertEqual(r.primary, "openalex")
            self.assertIn("seed", r.reasoning.lower())


class IngestionTests(TestCase):
    def test_ingestion_always_openalex(self):
        for mode in (None, "quick", "deep", "wide"):
            r = select_source(phase="ingestion", mode=mode)
            self.assertEqual(r.primary, "openalex")


class GraphWalkTests(TestCase):
    def test_graph_walk_openalex(self):
        r = select_source(phase="graph-walk")
        self.assertEqual(r.primary, "openalex")


class EnrichmentTests(TestCase):
    def test_enrichment_picks_s2(self):
        r = select_source(phase="enrichment", mode="deep")
        self.assertEqual(r.primary, "s2")
        self.assertIn("s2", r.reasoning.lower())


class DiscoveryTests(TestCase):
    def test_quick_mode_uses_s2(self):
        r = select_source(phase="discovery", mode="quick")
        self.assertEqual(r.primary, "s2")

    def test_free_budget_excludes_consensus(self):
        r = select_source(phase="discovery", mode="deep",
                          budget_tier="free")
        self.assertEqual(r.primary, "s2")
        self.assertNotIn("consensus", r.fallbacks)

    def test_wide_mode_uses_openalex(self):
        r = select_source(phase="discovery", mode="wide")
        self.assertEqual(r.primary, "openalex")

    def test_deep_open_question_uses_consensus(self):
        r = select_source(phase="discovery", mode="deep",
                          open_question=True)
        self.assertEqual(r.primary, "consensus")
        self.assertIn("triage", r.reasoning.lower())

    def test_concrete_query_uses_openalex(self):
        r = select_source(phase="discovery", mode="deep",
                          open_question=False)
        self.assertEqual(r.primary, "openalex")

    def test_default_safe_baseline(self):
        r = select_source(phase="discovery")
        self.assertEqual(r.primary, "openalex")


class ValidationTests(TestCase):
    def test_invalid_phase_raises(self):
        with self.assertRaises(ValueError):
            select_source(phase="bogus")  # type: ignore[arg-type]

    def test_invalid_mode_raises(self):
        with self.assertRaises(ValueError):
            select_source(phase="discovery", mode="fancy")  # type: ignore[arg-type]

    def test_invalid_budget_raises(self):
        with self.assertRaises(ValueError):
            select_source(phase="discovery",
                          budget_tier="cheap")  # type: ignore[arg-type]


class CallBudgetTests(TestCase):
    def test_quick_budget_no_paid(self):
        b = call_budget(mode="quick")
        self.assertEqual(b["total_paid"], 0)
        self.assertEqual(b["consensus"], 0)

    def test_deep_budget_has_consensus(self):
        b = call_budget(mode="deep")
        self.assertGreater(b["consensus"], 0)
        self.assertEqual(b["total_paid"], b["consensus"])

    def test_wide_scales_with_n(self):
        b1 = call_budget(mode="wide", n_candidates=10)
        b2 = call_budget(mode="wide", n_candidates=600)
        self.assertGreater(b2["s2"], b1["s2"])
        self.assertGreater(b2["openalex"], b1["openalex"])
        self.assertEqual(b2["total_paid"], 0)


class CliTests(TestCase):
    def _run(self, *args):
        repo = Path(__file__).resolve().parents[1]
        return subprocess.run(
            [sys.executable, "-m", "lib.source_selector", *args],
            capture_output=True, text=True, cwd=str(repo),
        )

    def test_cli_text_output(self):
        r = self._run("--phase", "discovery", "--mode", "deep")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), "consensus")

    def test_cli_json_output(self):
        import json as j
        r = self._run("--phase", "ingestion", "--format", "json")
        self.assertEqual(r.returncode, 0)
        d = j.loads(r.stdout)
        self.assertEqual(d["primary"], "openalex")

    def test_cli_seed_flag(self):
        r = self._run("--phase", "discovery", "--mode", "deep",
                      "--has-seed")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), "openalex")

    def test_cli_budget(self):
        import json as j
        r = self._run("--budget", "--mode", "deep", "--format", "json")
        self.assertEqual(r.returncode, 0)
        d = j.loads(r.stdout)
        self.assertEqual(d["total_paid"], d["consensus"])

    def test_cli_help(self):
        r = self._run("-h")
        self.assertEqual(r.returncode, 0)
        self.assertIn("--phase", r.stdout)


if __name__ == "__main__":
    raise SystemExit(run_tests(
        SeedShortCircuitTests, IngestionTests, GraphWalkTests,
        EnrichmentTests, DiscoveryTests, ValidationTests,
        CallBudgetTests, CliTests,
    ))
