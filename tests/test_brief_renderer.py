"""v0.54 — brief renderer tests."""

from tests import _shim  # noqa: F401

import sys
from pathlib import Path

from tests.harness import TestCase, run_tests

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from lib.brief_renderer import (  # noqa: E402
    render_discussion_questions,
    render_evidence_table,
    render_hypothesis_cards,
    render_run_recovery_doc,
)


class HypothesisCardsTests(TestCase):
    def test_empty_returns_placeholder(self):
        out = render_hypothesis_cards([], top_k=5)
        self.assertIn("no hypotheses", out)

    def test_card_renders_all_fields(self):
        rows = [{
            "hyp_id": "hyp-001",
            "agent_name": "architect",
            "statement": "Forgetting follows a power-law",
            "method_sketch": "Fit power-law to recall curves",
            "predicted_observables": '["recall@7d > 50%"]',
            "falsifiers": '["recall@1y == recall@7d"]',
            "supporting_ids": '["smith_2020_x", "jones_2021_y"]',
            "elo": 1450.0,
            "n_matches": 10, "n_wins": 7,
        }]
        out = render_hypothesis_cards(rows, top_k=5)
        self.assertIn("hyp-001", out)
        self.assertIn("Forgetting follows a power-law", out)
        self.assertIn("Power-law" in out or "power-law" in out, [True])
        self.assertIn("recall@7d > 50%", out)
        self.assertIn("recall@1y == recall@7d", out)
        self.assertIn("smith_2020_x", out)
        self.assertIn("Elo 1450", out)
        self.assertIn("7/10", out)

    def test_sorted_by_elo_desc(self):
        rows = [
            {"hyp_id": "h_low", "statement": "S1", "elo": 1200},
            {"hyp_id": "h_high", "statement": "S2", "elo": 1700},
            {"hyp_id": "h_mid", "statement": "S3", "elo": 1400},
        ]
        out = render_hypothesis_cards(rows, top_k=3)
        i_high = out.index("h_high")
        i_mid = out.index("h_mid")
        i_low = out.index("h_low")
        self.assertTrue(i_high < i_mid < i_low)

    def test_top_k_truncates(self):
        rows = [
            {"hyp_id": f"h{i}", "statement": "x", "elo": 1200 + i}
            for i in range(10)
        ]
        out = render_hypothesis_cards(rows, top_k=3)
        # Only top 3 should appear
        self.assertIn("h9", out)
        self.assertIn("h8", out)
        self.assertIn("h7", out)
        self.assertNotIn("h0", out)

    def test_handles_already_parsed_lists(self):
        rows = [{
            "hyp_id": "x", "statement": "y", "elo": 1300,
            "predicted_observables": ["A", "B"],
            "falsifiers": ["F1"],
            "supporting_ids": ["cid1"],
        }]
        out = render_hypothesis_cards(rows)
        for s in ("A", "B", "F1", "cid1"):
            self.assertIn(s, out)

    def test_missing_optional_fields_ok(self):
        rows = [{"hyp_id": "x", "statement": "minimal"}]
        out = render_hypothesis_cards(rows)
        self.assertIn("minimal", out)


class EvidenceTableTests(TestCase):
    def test_empty_claims_returns_placeholder(self):
        out = render_evidence_table([])
        self.assertIn("no claims", out)

    def test_groups_by_section_heading(self):
        rows = [
            {"text": "Consensus claim",
             "kind": "finding", "canonical_id": "p1", "confidence": 0.9},
            {"text": "Tension claim",
             "kind": "tension", "canonical_id": "p2", "confidence": 0.7},
            {"text": "Gap claim",
             "kind": "gap", "canonical_id": "p3", "confidence": 0.5},
        ]
        out = render_evidence_table(rows)
        self.assertIn("What the field agrees on", out)
        self.assertIn("Where the field disagrees", out)
        self.assertIn("Genuine gaps", out)

    def test_truncates_long_claim_text(self):
        long = "x" * 200
        rows = [{
            "text": long, "kind": "finding",
            "canonical_id": "c", "confidence": 0.5,
        }]
        out = render_evidence_table(rows, text_truncate=50)
        self.assertIn("…", out)
        self.assertNotIn("x" * 100, out)

    def test_pipe_in_claim_escaped(self):
        rows = [{
            "text": "claim with | pipe",
            "kind": "finding", "canonical_id": "c", "confidence": 0.5,
        }]
        out = render_evidence_table(rows)
        self.assertIn(r"\|", out)

    def test_unknown_kind_lands_in_other(self):
        rows = [{
            "text": "weird", "kind": "exotic",
            "canonical_id": "c", "confidence": 0.5,
        }]
        out = render_evidence_table(rows)
        self.assertIn("Other", out)

    def test_sort_by_confidence_within_section(self):
        rows = [
            {"text": "low_conf", "kind": "finding",
             "canonical_id": "p1", "confidence": 0.2},
            {"text": "high_conf", "kind": "finding",
             "canonical_id": "p2", "confidence": 0.9},
        ]
        out = render_evidence_table(rows)
        self.assertTrue(out.index("high_conf") < out.index("low_conf"))


class DiscussionQuestionsTests(TestCase):
    def test_returns_n_questions(self):
        q = "How does sleep consolidate episodic memory?"
        out = render_discussion_questions(q, n=6)
        # Numbered 1.-6.
        for i in range(1, 7):
            self.assertIn(f"{i}.", out)

    def test_facets_drawn_from_question(self):
        q = "How does adaptive forgetting serve human memory?"
        out = render_discussion_questions(q)
        # At least one of these unigrams or bigrams should appear
        signals = ("forgetting", "memory", "adaptive forgetting",
                   "human memory")
        self.assertTrue(any(s in out for s in signals))

    def test_empty_question_safe(self):
        out = render_discussion_questions("", n=3)
        self.assertIn("research question", out)

    def test_n_caps_at_template_count(self):
        out = render_discussion_questions("X Y Z", n=20)
        # Renderer caps at len(_QUESTION_TEMPLATES)=6
        # (specifically n=min(n, len(templates)))
        # Count numbered lines:
        nums = sum(
            1 for line in out.splitlines() if line and line[0].isdigit()
        )
        self.assertTrue(nums <= 6)


class RunRecoveryTests(TestCase):
    def test_substitutes_run_id(self):
        tmpl = "Run {{run_id}}\nDB=run-{{run_id}}.db"
        out = render_run_recovery_doc(tmpl, "abc123")
        self.assertNotIn("{{run_id}}", out)
        self.assertIn("abc123", out)
        self.assertEqual(out.count("abc123"), 2)

    def test_no_placeholders_idempotent(self):
        tmpl = "no template here"
        out = render_run_recovery_doc(tmpl, "x")
        self.assertEqual(out, tmpl)


if __name__ == "__main__":
    sys.exit(run_tests(
        HypothesisCardsTests, EvidenceTableTests,
        DiscussionQuestionsTests, RunRecoveryTests,
    ))
