"""v0.55 A5 Tier A — gap-analyzer + contribution-mapper + venue-match."""

import sys
from pathlib import Path

from tests import _shim  # noqa: F401
from tests.harness import TestCase, run_tests

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from lib.contribution_mapper import (  # noqa: E402
    Anchor,
    closest_anchor,
    contribution_distance,
    decompose_contribution,
    jaccard,
    project_2d,
    render_landscape,
)
from lib.gap_analyzer import (  # noqa: E402
    analyze_gap,
    analyze_gaps,
)
from lib.gap_analyzer import (
    render_brief as render_gap_brief,
)
from lib.venue_match import (  # noqa: E402
    ManuscriptChars,
    list_venues,
    recommend,
    score_venue,
)
from lib.venue_match import (
    render_brief as render_venue_brief,
)

# =================================================================
# Gap analyzer
# =================================================================

class GapAnalyzerTests(TestCase):
    def _gap(self, **kw) -> dict:
        base = {
            "gap_id": "g1", "kind": "evidential", "claim": "no test",
            "supporting_ids": ["c1", "c2"],
            "cross_check_query": "did anyone test X?",
        }
        base.update(kw)
        return base

    def test_real_when_supported_and_cross_checked(self):
        a = analyze_gap(
            self._gap(),
            supporting_paper_confidences={"c1": 0.8, "c2": 0.85},
        )
        self.assertEqual(a.real_or_artifact, "real")

    def test_artifact_when_only_one_support(self):
        a = analyze_gap(self._gap(supporting_ids=["c1"]))
        self.assertEqual(a.real_or_artifact, "artifact")

    def test_uncertain_when_no_cross_check(self):
        a = analyze_gap(self._gap(cross_check_query=""))
        self.assertEqual(a.real_or_artifact, "uncertain")

    def test_evidential_addressable_default(self):
        a = analyze_gap(self._gap(kind="evidential"))
        self.assertTrue(a.addressable)

    def test_conceptual_needs_high_confidence(self):
        low = analyze_gap(
            self._gap(kind="conceptual"),
            supporting_paper_confidences={"c1": 0.3, "c2": 0.4},
        )
        self.assertFalse(low.addressable)
        high = analyze_gap(
            self._gap(kind="conceptual"),
            supporting_paper_confidences={"c1": 0.7, "c2": 0.8},
        )
        self.assertTrue(high.addressable)

    def test_publishability_tier_a_evidential(self):
        a = analyze_gap(
            self._gap(supporting_ids=["c1", "c2", "c3", "c4"]),
            supporting_paper_confidences={c: 0.9 for c in ("c1", "c2", "c3", "c4")},
        )
        self.assertEqual(a.publishability_tier, "A")

    def test_artifact_tier_none(self):
        a = analyze_gap(self._gap(supporting_ids=["c1"]))
        self.assertEqual(a.publishability_tier, "none")

    def test_finds_adjacent_field_analogues(self):
        a = analyze_gap(self._gap(claim="memory consolidation under sleep"))
        self.assertIn("sleep neuroscience", a.adjacent_field_analogues)

    def test_difficulty_artifact_low(self):
        a = analyze_gap(self._gap(supporting_ids=["c1"]))
        self.assertEqual(a.expected_difficulty, "low")

    def test_difficulty_conceptual_high(self):
        a = analyze_gap(self._gap(kind="conceptual"))
        self.assertEqual(a.expected_difficulty, "high")

    def test_render_brief_handles_empty(self):
        self.assertIn("no gaps", render_gap_brief([]))

    def test_render_brief_table(self):
        analyses = analyze_gaps([
            self._gap(),
            self._gap(gap_id="g2", kind="conceptual",
                      claim="why does forgetting happen"),
        ])
        out = render_gap_brief(analyses)
        self.assertIn("g1", out)
        self.assertIn("g2", out)


# =================================================================
# Contribution mapper
# =================================================================

class ContributionMapperTests(TestCase):
    def test_jaccard_disjoint(self):
        self.assertEqual(jaccard({"a"}, {"b"}), 0.0)

    def test_jaccard_identical(self):
        self.assertEqual(jaccard({"a", "b"}, {"a", "b"}), 1.0)

    def test_jaccard_partial(self):
        self.assertEqual(jaccard({"a", "b"}, {"a", "c"}), 1 / 3)

    def test_jaccard_both_empty(self):
        self.assertEqual(jaccard(set(), set()), 0.0)

    def test_decompose_extracts_axes(self):
        c = decompose_contribution(
            "C1",
            "We show that transformer scaling on language tasks "
            "matches power-law predictions",
        )
        self.assertIn("transformer", c.method)
        self.assertIn("language", c.domain)
        self.assertIn("power-law", c.finding)

    def test_distance_zero_when_anchor_matches(self):
        c = decompose_contribution(
            "C1", "transformer language scaling power-law"
        )
        a = Anchor.from_dict({
            "canonical_id": "vaswani_2017",
            "method": ["transformer"], "domain": ["language"],
            "finding": ["power-law", "scaling"],
        })
        dm, dd, df = contribution_distance(c, a)
        self.assertAlmostEqual(dm, 0.0, places=2)
        self.assertAlmostEqual(dd, 0.0, places=2)
        self.assertTrue(df < 0.5)

    def test_closest_anchor_picks_best(self):
        c = decompose_contribution(
            "C1", "transformer language scaling improvement"
        )
        anchors = [
            Anchor.from_dict({
                "canonical_id": "wrong",
                "method": ["convolution"], "domain": ["vision"],
                "finding": ["robustness"],
            }),
            Anchor.from_dict({
                "canonical_id": "right",
                "method": ["transformer"], "domain": ["language"],
                "finding": ["scaling"],
            }),
        ]
        best, _ = closest_anchor(c, anchors)
        self.assertEqual(best.canonical_id, "right")

    def test_closest_anchor_empty_returns_none(self):
        c = decompose_contribution("C1", "transformer")
        best, d = closest_anchor(c, [])
        self.assertIsNone(best)
        self.assertEqual(d, (1.0, 1.0, 1.0))

    def test_project_2d_returns_one_per_contribution(self):
        cs = [
            decompose_contribution("C1", "transformer language scaling"),
            decompose_contribution("C2", "convolution vision robust"),
        ]
        anchors = [Anchor.from_dict({
            "canonical_id": "a1",
            "method": ["transformer"], "domain": ["language"],
            "finding": ["scaling"],
        })]
        projections = project_2d(cs, anchors)
        self.assertEqual(len(projections), 2)
        # First contribution overlaps anchor → near origin
        self.assertTrue(projections[0][0] < 0.5)
        # Second contribution is far on both axes
        self.assertTrue(projections[1][0] > 0.5)
        self.assertTrue(projections[1][1] > 0.5)

    def test_render_landscape_includes_grid(self):
        cs = [decompose_contribution("C1", "transformer language scaling")]
        anchors = [Anchor.from_dict({
            "canonical_id": "a", "method": ["transformer"],
            "domain": ["language"], "finding": ["scaling"],
        })]
        out = render_landscape(cs, anchors)
        self.assertIn("Contribution landscape", out)
        self.assertIn("ASCII landscape", out)
        self.assertIn("`a`", out)


# =================================================================
# Venue match
# =================================================================

class VenueMatchTests(TestCase):
    def test_list_venues_nonempty(self):
        self.assertTrue(len(list_venues()) >= 10)

    def test_score_ml_paper_at_neurips(self):
        chars = ManuscriptChars(
            domains=("ml",), kind="empirical",
            novelty_score=0.8, rigor_score=0.8,
        )
        venues = {v.name: v for v in list_venues()}
        score = score_venue(venues["NeurIPS"], chars)
        self.assertTrue(score >= 0.7)

    def test_score_low_novelty_loses_a_tier(self):
        chars_high = ManuscriptChars(
            domains=("ml",), kind="empirical",
            novelty_score=0.9, rigor_score=0.9,
        )
        chars_low = ManuscriptChars(
            domains=("ml",), kind="empirical",
            novelty_score=0.2, rigor_score=0.9,
        )
        venues = {v.name: v for v in list_venues()}
        v_high = score_venue(venues["NeurIPS"], chars_high)
        v_low = score_venue(venues["NeurIPS"], chars_low)
        self.assertTrue(v_high > v_low)

    def test_recommend_returns_top_k(self):
        chars = ManuscriptChars(
            domains=("ml",), kind="empirical",
            novelty_score=0.8, rigor_score=0.8,
        )
        recs = recommend(chars, top_k=3)
        self.assertEqual(len(recs), 3)
        # Sorted desc by score
        for a, b in zip(recs, recs[1:]):
            self.assertTrue(a.score >= b.score)

    def test_require_tier_filters_lower(self):
        chars = ManuscriptChars(
            domains=("ml",), kind="empirical",
            novelty_score=0.8, rigor_score=0.8,
            require_tier="A",
        )
        recs = recommend(chars, top_k=10)
        for r in recs:
            self.assertEqual(r.venue.tier, "A")

    def test_oa_intent_boosts_oa_venues(self):
        chars_oa = ManuscriptChars(
            domains=("biology",), kind="empirical",
            novelty_score=0.7, rigor_score=0.8,
            open_science_intent=True,
        )
        venues = {v.name: v for v in list_venues()}
        elife_score = score_venue(venues["eLife"], chars_oa)
        nature_score = score_venue(venues["Nature"], chars_oa)
        # eLife is OA, Nature is not — OA intent should narrow gap
        self.assertTrue(elife_score - nature_score > 0)

    def test_review_kind_routes_to_review_venues(self):
        chars = ManuscriptChars(
            domains=("biology",), kind="review",
            novelty_score=0.5, rigor_score=0.7,
        )
        recs = recommend(chars, top_k=3)
        # At least one should accept reviews
        self.assertTrue(
            any("review" in r.venue.accepts_kinds for r in recs)
        )

    def test_deadline_filter(self):
        chars = ManuscriptChars(
            domains=("ml",), kind="empirical",
            novelty_score=0.8, rigor_score=0.8,
            deadline_days=30,
        )
        recs = recommend(chars, top_k=5)
        # arXiv (0d) should rank reasonably; NeurIPS (120d) misses deadline
        names = [r.venue.name for r in recs]
        # Either arXiv shows up or top venues that beat deadline do
        within = [r for r in recs
                  if r.venue.review_turnaround_days <= 30]
        self.assertTrue(len(within) >= 1)

    def test_render_brief_includes_table_and_per_venue(self):
        chars = ManuscriptChars(
            domains=("ml",), kind="empirical",
            novelty_score=0.7, rigor_score=0.8,
        )
        out = render_venue_brief(recommend(chars, top_k=2))
        self.assertIn("Venue recommendations", out)
        self.assertIn("Per-venue tradeoffs", out)

    def test_render_brief_empty(self):
        self.assertIn("no venue", render_venue_brief([]))


if __name__ == "__main__":
    sys.exit(run_tests(
        GapAnalyzerTests, ContributionMapperTests, VenueMatchTests,
    ))
