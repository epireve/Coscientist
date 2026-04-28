"""v0.52.1 — search-strategy framework selection tests."""

import sys
from pathlib import Path

from tests import _shim  # noqa: F401
from tests.harness import TestCase, run_tests

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from lib.search_framework import (  # noqa: E402
    FRAMEWORK_TEMPLATES,
    SearchStrategy,
    SubArea,
    suggest_framework,
    template_for,
)


class TemplateTests(TestCase):
    def test_pico_has_4_components(self):
        self.assertEqual(len(template_for("pico")), 4)
        names = {c["component"] for c in template_for("pico")}
        self.assertEqual(names, {"P", "I", "C", "O"})

    def test_spider_has_5_components(self):
        self.assertEqual(len(template_for("spider")), 5)

    def test_decomposition_has_4_components(self):
        self.assertEqual(len(template_for("decomposition")), 4)
        names = {c["component"] for c in template_for("decomposition")}
        self.assertEqual(names, {"M", "A", "L", "C"})

    def test_hybrid_returns_empty(self):
        self.assertEqual(template_for("hybrid"), [])

    def test_all_templates_have_required_keys(self):
        for fw, components in FRAMEWORK_TEMPLATES.items():
            for c in components:
                self.assertIn("component", c, f"missing component in {fw}")
                self.assertIn("name", c, f"missing name in {fw}")
                self.assertIn("prompt", c, f"missing prompt in {fw}")


class SuggestFrameworkTests(TestCase):
    def test_clinical_question_picks_pico(self):
        fw, _ = suggest_framework(
            "Does intervention A improve outcome in patients with depression?"
        )
        self.assertEqual(fw, "pico")

    def test_qualitative_question_picks_spider(self):
        fw, _ = suggest_framework(
            "How do nurses experience moral distress in palliative care?"
        )
        # Has "experience" keyword
        self.assertIn(fw, ("spider", "hybrid"))

    def test_technology_question_picks_decomposition(self):
        fw, _ = suggest_framework(
            "Adaptive forgetting algorithm in neural network architecture"
        )
        self.assertEqual(fw, "decomposition")

    def test_no_keyword_defaults_pico(self):
        fw, rationale = suggest_framework("scientific quibbles galore")
        self.assertEqual(fw, "pico")
        self.assertIn("default", rationale.lower())

    def test_multi_signal_picks_hybrid(self):
        # Has clinical + technology signals
        fw, _ = suggest_framework(
            "RCT of digital intervention algorithm for patient education"
        )
        # Should be hybrid given multiple keyword hits
        self.assertIn(fw, ("hybrid", "pico"))


class SearchStrategyTests(TestCase):
    def _make(self) -> SearchStrategy:
        return SearchStrategy(
            framework="decomposition",
            rationale="Question is technology-focused.",
            sub_areas=[
                SubArea("M", "Core mechanism", "spaced rep + ML unlearning",
                        assigned_persona="cartographer"),
                SubArea("A", "Applications", "memory aids lifelogging",
                        assigned_persona="chronicler"),
            ],
            cross_cutting="Neuroscience analogues",
        )

    def test_round_trip(self):
        s = self._make()
        d = s.to_dict()
        s2 = SearchStrategy.from_dict(d)
        self.assertEqual(s2.framework, s.framework)
        self.assertEqual(len(s2.sub_areas), len(s.sub_areas))
        self.assertEqual(s2.sub_areas[0].assigned_persona, "cartographer")
        self.assertEqual(s2.cross_cutting, "Neuroscience analogues")

    def test_render_table_has_all_components(self):
        s = self._make()
        md = s.render_table()
        self.assertIn("DECOMPOSITION", md)
        self.assertIn("Core mechanism", md)
        self.assertIn("cartographer", md)
        self.assertIn("Cross-cutting", md)
        self.assertIn("Neuroscience analogues", md)

    def test_render_unassigned_persona(self):
        s = SearchStrategy(
            framework="pico", rationale="x",
            sub_areas=[SubArea("P", "x", "y")],
        )
        md = s.render_table()
        self.assertIn("_unassigned_", md)


if __name__ == "__main__":
    sys.exit(run_tests(
        TemplateTests, SuggestFrameworkTests, SearchStrategyTests,
    ))
