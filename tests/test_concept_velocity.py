"""v0.52.6 — concept-velocity metric tests."""

import sys
from pathlib import Path

from tests import _shim  # noqa: F401
from tests.harness import TestCase, run_tests

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from lib.concept_velocity import (  # noqa: E402
    ConceptTrend,
    _ols_slope,
    _tokenize_with_bigrams,
    compute_velocities,
    render_summary,
)


class TokenizeTests(TestCase):
    def test_unigrams_and_bigrams(self):
        toks = _tokenize_with_bigrams("memory augmentation lifelogging")
        self.assertIn("memory", toks)
        self.assertIn("augmentation", toks)
        self.assertIn("memory augmentation", toks)
        self.assertIn("augmentation lifelogging", toks)

    def test_drops_stopwords(self):
        toks = _tokenize_with_bigrams("the memory of forgetting")
        self.assertNotIn("the", toks)
        # bigrams skip stopwords too because we filter unigrams first
        self.assertIn("memory forgetting", toks)


class OLSTests(TestCase):
    def test_perfect_positive_slope(self):
        xs = [1, 2, 3, 4]
        ys = [2.0, 4.0, 6.0, 8.0]  # y = 2x
        slope, intercept = _ols_slope(xs, ys)
        self.assertAlmostEqual(slope, 2.0)
        self.assertAlmostEqual(intercept, 0.0)

    def test_negative_slope(self):
        xs = [1, 2, 3, 4]
        ys = [10.0, 8.0, 6.0, 4.0]  # y = -2x + 12
        slope, intercept = _ols_slope(xs, ys)
        self.assertAlmostEqual(slope, -2.0)
        self.assertAlmostEqual(intercept, 12.0)

    def test_zero_variance_xs(self):
        xs = [5, 5, 5]
        ys = [1.0, 2.0, 3.0]
        slope, intercept = _ols_slope(xs, ys)
        self.assertEqual(slope, 0.0)
        self.assertAlmostEqual(intercept, 2.0)


class ComputeVelocitiesTests(TestCase):
    def _corpus(self) -> list[dict]:
        # "machine unlearning" rises across 2020-2025
        # "memex archive" falls across same period
        # Mostly used for shape verification.
        rising = "machine unlearning"
        falling = "memex archive"

        papers = []
        # 2020: 5 papers, 1 with rising, 4 with falling
        for _ in range(1):
            papers.append({"year": 2020,
                            "abstract": f"{rising} early work novel"})
        for _ in range(4):
            papers.append({"year": 2020,
                            "abstract": f"{falling} traditional documents"})
        # 2022: 5 papers, 3 rising, 2 falling
        for _ in range(3):
            papers.append({"year": 2022,
                            "abstract": f"{rising} growing field important"})
        for _ in range(2):
            papers.append({"year": 2022,
                            "abstract": f"{falling} declining traditional"})
        # 2024: 5 papers, 5 rising, 0 falling
        for _ in range(5):
            papers.append({"year": 2024,
                            "abstract": f"{rising} dominant standard"})
        return papers

    def test_emerging_term_detected(self):
        trends = compute_velocities(self._corpus(),
                                      min_papers_per_term=3,
                                      min_years_per_term=2)
        emerging_terms = {t.term for t in trends if t.direction == "emerging"}
        # Bigram OR unigram could be detected
        self.assertTrue(any("machine" in t or "unlearning" in t
                              for t in emerging_terms),
                          f"expected machine/unlearning emerging, got {emerging_terms}")

    def test_deprecated_term_detected(self):
        trends = compute_velocities(self._corpus(),
                                      min_papers_per_term=3,
                                      min_years_per_term=2)
        deprecated_terms = {t.term for t in trends if t.direction == "deprecated"}
        self.assertTrue(any("memex" in t or "archive" in t
                              for t in deprecated_terms),
                          f"expected memex/archive deprecated, got {deprecated_terms}")

    def test_min_papers_filter(self):
        # Term appearing in only 1 paper → filtered
        sparse = [{"year": 2020, "abstract": "rare unique once-only"}]
        trends = compute_velocities(sparse, min_papers_per_term=3)
        self.assertEqual(trends, [])

    def test_min_years_filter(self):
        # Term in 5 papers but only 1 year → filtered
        single_year = [
            {"year": 2020, "abstract": "common term here"},
            {"year": 2020, "abstract": "common term here"},
            {"year": 2020, "abstract": "common term here"},
            {"year": 2020, "abstract": "common term here"},
            {"year": 2020, "abstract": "common term here"},
        ]
        trends = compute_velocities(single_year, min_years_per_term=2)
        self.assertEqual(trends, [])

    def test_empty_corpus(self):
        self.assertEqual(compute_velocities([]), [])


class RenderTests(TestCase):
    def test_empty(self):
        s = render_summary([])
        self.assertIn("No concept-velocity", s)

    def test_with_emerging_and_deprecated(self):
        trends = [
            ConceptTrend(term="machine unlearning", slope=0.05,
                          intercept=0.0, total_papers=10, n_years=4,
                          first_year=2020, last_year=2024,
                          direction="emerging"),
            ConceptTrend(term="memex archive", slope=-0.04,
                          intercept=0.0, total_papers=8, n_years=3,
                          first_year=2018, last_year=2022,
                          direction="deprecated"),
        ]
        s = render_summary(trends)
        self.assertIn("Emerging terms", s)
        self.assertIn("Deprecated terms", s)
        self.assertIn("machine unlearning", s)
        self.assertIn("memex archive", s)
        self.assertIn("+0.0500", s)
        self.assertIn("-0.0400", s)


if __name__ == "__main__":
    sys.exit(run_tests(
        TokenizeTests, OLSTests, ComputeVelocitiesTests, RenderTests,
    ))
