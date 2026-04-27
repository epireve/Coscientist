"""v0.52.3 — empirical era inflection detection tests."""

from tests import _shim  # noqa: F401

import sys
from pathlib import Path

from tests.harness import TestCase, run_tests

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from lib.era_detection import (  # noqa: E402
    Inflection, _js_divergence, _tokenize, detect_inflections,
    render_summary,
)


class TokenizeTests(TestCase):
    def test_lowercases_and_strips_stopwords(self):
        toks = _tokenize("The Memory of Forgetting in Digital Systems")
        self.assertNotIn("the", toks)
        self.assertNotIn("of", toks)
        self.assertNotIn("in", toks)
        self.assertIn("memory", toks)
        self.assertIn("forgetting", toks)
        self.assertIn("digital", toks)
        self.assertIn("systems", toks)

    def test_drops_short_words(self):
        toks = _tokenize("an it of memory")
        # "an", "it", "of" all stopwords or len <= 2
        self.assertEqual(toks, ["memory"])


class JSDivergenceTests(TestCase):
    def test_identical_distributions_zero(self):
        p = {"a": 0.5, "b": 0.5}
        self.assertEqual(_js_divergence(p, p), 0.0)

    def test_disjoint_distributions_max(self):
        p = {"a": 1.0}
        q = {"b": 1.0}
        # JS for completely disjoint = 1.0 with log base 2
        self.assertAlmostEqual(_js_divergence(p, q), 1.0, places=4)

    def test_partial_overlap_intermediate(self):
        p = {"a": 0.5, "b": 0.5}
        q = {"b": 0.5, "c": 0.5}
        d = _js_divergence(p, q)
        self.assertTrue(0.0 < d < 1.0)

    def test_empty_distributions_zero(self):
        self.assertEqual(_js_divergence({}, {}), 0.0)


class DetectInflectionsTests(TestCase):
    def _make_papers(self) -> list[dict]:
        # Pre-2010 era talks "memex archive". Post-2010 talks
        # "lifelogging augmentation". Boundary should land at 2010→2015.
        old_era = [
            {"year": 2005, "abstract": "memex archive personal documents retrieval"},
            {"year": 2005, "abstract": "memex personal archive long term storage"},
            {"year": 2005, "abstract": "memex documents retrieval personal"},
            {"year": 2008, "abstract": "memex archive personal long-term retrieval"},
            {"year": 2008, "abstract": "memex personal documents archive"},
            {"year": 2008, "abstract": "memex archive personal documents"},
        ]
        new_era = [
            {"year": 2015, "abstract": "lifelogging augmentation cognitive memory"},
            {"year": 2015, "abstract": "lifelogging memory augmentation wearable"},
            {"year": 2015, "abstract": "lifelogging cognitive augmentation wearable"},
            {"year": 2020, "abstract": "lifelogging cognitive augmentation memory"},
            {"year": 2020, "abstract": "lifelogging wearable augmentation"},
            {"year": 2020, "abstract": "lifelogging memory augmentation cognitive"},
        ]
        return old_era + new_era

    def test_detects_known_shift(self):
        infls = detect_inflections(self._make_papers())
        self.assertTrue(len(infls) >= 1)
        # Top inflection should bridge the eras
        top = infls[0]
        self.assertEqual(top.year_before, 2008)
        self.assertEqual(top.year_after, 2015)
        # Divergence should be high (close to 1)
        self.assertGreater(top.divergence, 0.5)

    def test_rising_falling_terms_correct(self):
        infls = detect_inflections(self._make_papers())
        top = infls[0]
        # "lifelogging" should rise; "memex" should fall
        self.assertIn("lifelogging", top.rising_terms)
        self.assertIn("memex", top.falling_terms)

    def test_min_papers_filter(self):
        # Only 2 papers in 2005 — should be dropped at min=3
        sparse = [
            {"year": 2005, "abstract": "alpha beta"},
            {"year": 2005, "abstract": "alpha beta"},
            {"year": 2010, "abstract": "gamma delta"},
            {"year": 2010, "abstract": "gamma delta"},
            {"year": 2010, "abstract": "gamma delta"},
        ]
        infls = detect_inflections(sparse, min_papers_per_year=3)
        # Only 2010 eligible → no boundary possible
        self.assertEqual(infls, [])

    def test_empty_input(self):
        self.assertEqual(detect_inflections([]), [])

    def test_papers_without_year_or_abstract_skipped(self):
        papers = [
            {"abstract": "memex"},  # no year
            {"year": 2010},          # no abstract
            {"year": 2010, "abstract": ""},  # empty
        ]
        # All filtered → no eligible years
        self.assertEqual(detect_inflections(papers), [])


class RenderTests(TestCase):
    def test_render_empty(self):
        s = render_summary([])
        self.assertIn("No inflection", s)

    def test_render_with_inflections(self):
        infls = [Inflection(
            year_before=2006, year_after=2008, divergence=0.75,
            n_papers_before=10, n_papers_after=15,
            rising_terms=["forgetting", "feature"],
            falling_terms=["archive", "memex"],
        )]
        s = render_summary(infls)
        self.assertIn("2006 → 2008", s)
        self.assertIn("0.750", s)
        self.assertIn("forgetting", s)
        self.assertIn("memex", s)


if __name__ == "__main__":
    sys.exit(run_tests(
        TokenizeTests, JSDivergenceTests, DetectInflectionsTests, RenderTests,
    ))
