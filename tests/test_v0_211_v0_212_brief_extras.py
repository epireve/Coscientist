"""v0.211 + v0.212 — audience-aware exec summary + tensions table."""
from __future__ import annotations

from lib.brief_renderer import (
    render_executive_summary,
    render_tensions_table,
    strip_jargon_for_novice,
)
from tests.harness import TestCase, run_tests


# ---------- v0.212 tensions table ----------


class TensionsTableTests(TestCase):
    def test_returns_empty_when_fewer_than_three(self):
        rows = [
            {"claim_id": 1, "kind": "tension", "text": "A vs B"},
            {"claim_id": 2, "kind": "tension", "text": "C vs D"},
        ]
        self.assertEqual(render_tensions_table(rows), "")

    def test_renders_three_unpaired_tensions(self):
        rows = [
            {"claim_id": i, "kind": "tension",
             "text": f"tension {i}", "confidence": 0.7}
            for i in range(1, 4)
        ]
        out = render_tensions_table(rows)
        self.assertIn("| # | Side A | Side B | Methodology", out)
        self.assertIn("tension 1", out)
        self.assertIn("tension 3", out)
        self.assertIn("0.70", out)

    def test_renders_paired_dual_side(self):
        rows = [
            {"claim_id": 10, "kind": "tension", "side": "a",
             "paired_claim_id": 11,
             "text": "Side A: isolation helps",
             "confidence": 0.8},
            {"claim_id": 11, "kind": "tension", "side": "b",
             "paired_claim_id": 10,
             "text": "Side B: isolation hurts",
             "confidence": 0.8},
            {"claim_id": 12, "kind": "tension",
             "text": "Solo tension"},
            {"claim_id": 13, "kind": "tension",
             "text": "Another solo"},
        ]
        out = render_tensions_table(rows)
        # Pair joined into one row.
        self.assertIn("isolation helps", out)
        self.assertIn("isolation hurts", out)
        # Solo rows show "—" in Side B.
        self.assertIn("Solo tension", out)
        # Data rows = 3 (1 paired + 2 solo). Header adds 1 more "\n|".
        self.assertEqual(out.count("\n|"), 4)

    def test_methodology_hint_extracted(self):
        rows = [
            {"claim_id": i, "kind": "tension",
             "text": f"different {kw} matters"}
            for i, kw in enumerate(["era", "method", "dataset"])
        ]
        out = render_tensions_table(rows)
        for kw in ("era", "method", "dataset"):
            self.assertIn(f"| {kw} |", out)

    def test_pipe_in_text_escaped(self):
        rows = [
            {"claim_id": i, "kind": "tension",
             "text": f"text with | pipe {i}"}
            for i in range(3)
        ]
        out = render_tensions_table(rows)
        self.assertIn("\\|", out)

    def test_only_tension_kind_included(self):
        rows = [
            {"claim_id": 1, "kind": "tension", "text": "real tension"},
            {"claim_id": 2, "kind": "finding", "text": "not tension"},
            {"claim_id": 3, "kind": "tension", "text": "second tension"},
            {"claim_id": 4, "kind": "tension", "text": "third tension"},
        ]
        out = render_tensions_table(rows)
        self.assertIn("real tension", out)
        self.assertTrue("not tension" not in out)


# ---------- v0.211 audience-aware ----------


class JargonStripTests(TestCase):
    def test_strips_known_jargon(self):
        text = "The study shows statistically significant effect size."
        out = strip_jargon_for_novice(text)
        self.assertIn("reliably non-random", out)
        self.assertIn("strength of the effect", out)

    def test_idempotent(self):
        text = "It is peer-reviewed and uses meta-analysis."
        once = strip_jargon_for_novice(text)
        twice = strip_jargon_for_novice(once)
        self.assertEqual(once, twice)

    def test_unknown_text_unchanged(self):
        text = "no jargon here at all"
        self.assertEqual(strip_jargon_for_novice(text), text)


class ExecutiveSummaryTests(TestCase):
    def test_expert_audience_keeps_jargon(self):
        out = render_executive_summary(
            question="Does X work?",
            proven="The meta-analysis shows reliable effect size.",
            open_problem="Heterogeneity across RCTs.",
            real_world_implication="Treatment Y should be standard.",
            audience="expert",
        )
        self.assertIn("TL;DR", out)
        self.assertIn("meta-analysis", out)  # untouched
        self.assertIn("RCTs", out)

    def test_novice_audience_strips_jargon(self):
        out = render_executive_summary(
            question="Does X work?",
            proven="The meta-analysis shows reliable effect size results.",
            open_problem="Heterogeneity across RCTs.",
            real_world_implication="Treatment Y should be standard.",
            audience="novice",
        )
        self.assertIn("Executive summary", out)
        self.assertIn("combined-study analysis", out)
        self.assertIn("strength of the effect", out)

    def test_question_always_present(self):
        out = render_executive_summary(
            question="My specific question?",
            proven="x", open_problem="y", real_world_implication="z",
        )
        self.assertIn("My specific question?", out)


if __name__ == "__main__":
    raise SystemExit(run_tests(
        TensionsTableTests, JargonStripTests, ExecutiveSummaryTests,
    ))
