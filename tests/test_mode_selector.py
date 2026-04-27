"""v0.53.6 — mode auto-selector tests."""

from tests import _shim  # noqa: F401

import sys
from pathlib import Path

from tests.harness import TestCase, run_tests

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from lib.mode_selector import (  # noqa: E402
    ModeRecommendation, select_mode,
)


def _items(n: int) -> list[dict]:
    return [{"canonical_id": f"p{i}", "title": f"P{i}"} for i in range(n)]


class ItemDrivenTests(TestCase):
    def test_wide_threshold_exact(self):
        r = select_mode("Q", items=_items(10))
        self.assertEqual(r.mode, "wide")
        self.assertEqual(r.n_items, 10)

    def test_wide_typical(self):
        r = select_mode("Q", items=_items(50))
        self.assertEqual(r.mode, "wide")

    def test_wide_max_inclusive(self):
        r = select_mode("Q", items=_items(250))
        self.assertEqual(r.mode, "wide")

    def test_above_wide_max_redirects_systematic_review(self):
        r = select_mode("Q", items=_items(251))
        self.assertEqual(r.mode, "systematic-review")
        self.assertIn("systematic-review", r.reasoning.lower())

    def test_below_threshold_concrete_to_quick(self):
        r = select_mode("summarize these", items=_items(5))
        self.assertEqual(r.mode, "quick")

    def test_below_threshold_open_question_to_deep(self):
        r = select_mode(
            "How do these papers relate to memory consolidation?",
            items=_items(5),
        )
        self.assertEqual(r.mode, "deep")

    def test_empty_items_list_treated_as_no_items(self):
        r = select_mode("How does X work?", items=[])
        self.assertEqual(r.n_items, 0)
        self.assertTrue(any("empty" in w.lower() for w in r.warnings))


class QuestionDrivenTests(TestCase):
    def test_no_items_open_question_to_deep(self):
        r = select_mode(
            "What is the role of attention in transformer scaling?",
        )
        self.assertEqual(r.mode, "deep")

    def test_no_items_concrete_to_quick(self):
        r = select_mode("summarize this paper")
        self.assertEqual(r.mode, "quick")

    def test_short_question_to_quick(self):
        r = select_mode("list venues")
        self.assertEqual(r.mode, "quick")

    def test_empty_question_falls_to_deep(self):
        r = select_mode("")
        self.assertEqual(r.mode, "deep")


class ExplicitOverrideTests(TestCase):
    def test_explicit_wide_with_too_few_items_warns(self):
        r = select_mode("Q", items=_items(3), explicit_mode="wide")
        self.assertEqual(r.mode, "wide")
        self.assertTrue(
            any("refuse at decompose" in w for w in r.warnings)
        )

    def test_explicit_quick_with_many_items_warns(self):
        r = select_mode("Q", items=_items(50), explicit_mode="quick")
        self.assertEqual(r.mode, "quick")
        self.assertTrue(
            any("benefit from Wide" in w for w in r.warnings)
        )

    def test_explicit_deep_no_warnings_normal(self):
        r = select_mode("How does X work?", explicit_mode="deep")
        self.assertEqual(r.mode, "deep")
        self.assertEqual(r.warnings, [])

    def test_explicit_wide_above_max_warns(self):
        r = select_mode("Q", items=_items(300), explicit_mode="wide")
        self.assertTrue(
            any("systematic-review" in w for w in r.warnings)
        )

    def test_explicit_deep_with_huge_corpus_warns(self):
        r = select_mode("Q", items=_items(300), explicit_mode="deep")
        self.assertTrue(any("sequentially" in w for w in r.warnings))


class ConfidenceTests(TestCase):
    def test_explicit_confidence_full(self):
        r = select_mode("Q", items=_items(50), explicit_mode="deep")
        self.assertEqual(r.confidence, 1.0)

    def test_wide_high_confidence(self):
        r = select_mode("Q", items=_items(50))
        self.assertGreaterEqual(r.confidence, 0.9)

    def test_to_dict_has_required_keys(self):
        r = select_mode("Q", items=_items(50))
        d = r.to_dict()
        for k in ("mode", "confidence", "reasoning", "warnings",
                  "n_items", "detected_shape"):
            self.assertIn(k, d)


if __name__ == "__main__":
    sys.exit(run_tests(
        ItemDrivenTests, QuestionDrivenTests,
        ExplicitOverrideTests, ConfidenceTests,
    ))
