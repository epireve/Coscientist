"""v0.189 — arXiv relevance fix: SKILL.md doc + source_selector demote."""
from __future__ import annotations

from pathlib import Path

from lib.source_selector import (
    _is_arxiv_relevance_query,
    select_source,
)
from tests.harness import TestCase, run_tests


_REPO = Path(__file__).resolve().parent.parent
_SKILL_MD = _REPO / ".claude/skills/paper-discovery/SKILL.md"


class V0189ArxivRelevanceTests(TestCase):

    def test_skill_md_documents_arxiv_date_bias(self):
        txt = _SKILL_MD.read_text()
        self.assertIn("date-sorted", txt)
        self.assertIn("arxiv", txt.lower())
        # Mentions OpenAlex/Consensus as relevance fallback
        ok = "openalex" in txt.lower() or "consensus" in txt.lower()
        if not ok:
            raise AssertionError("SKILL.md should mention fallback sources")

    def test_demote_paper_search_for_open_ended_discovery(self):
        # has_seed=True is the only path putting paper-search in fallbacks.
        # Demote should push it to last position when query is topical.
        rec = select_source(
            phase="discovery",
            mode="deep",
            has_seed=True,  # produces fallbacks=["s2", "paper-search"]
            query="multi-agent LLM context isolation reliability",
        )
        # paper-search should still be present, but at the end
        self.assertIn("paper-search", rec.fallbacks)
        self.assertEqual(rec.fallbacks[-1], "paper-search",
                         "paper-search should be demoted to last")
        self.assertIn("v0.189", rec.reasoning)

    def test_keep_paper_search_for_arxiv_id_query(self):
        # Concrete arXiv ID — caller wants exact paper, no demote
        rec = select_source(
            phase="discovery",
            mode="deep",
            has_seed=True,
            query="paper 2401.00123 details",
        )
        self.assertIn("paper-search", rec.fallbacks)
        # The original order has paper-search at index 1; demote should NOT
        # have fired, so reasoning shouldn't contain v0.189 marker.
        self.assertNotIn("v0.189", rec.reasoning)

    def test_select_source_back_compat_no_query(self):
        # No query passed — behaviour unchanged from v0.188.
        rec = select_source(
            phase="discovery", mode="deep", has_seed=True,
        )
        self.assertIn("paper-search", rec.fallbacks)
        self.assertNotIn("v0.189", rec.reasoning)

    def test_arxiv_id_heuristic_positive_cases(self):
        # arXiv IDs in various contexts → False (skip demote)
        cases = [
            "2401.12345",
            "look at 2401.12345 for context",
            "compare 1706.03762 and 2005.14165",
            "old: 1234.5678",
        ]
        for q in cases:
            self.assertEqual(
                _is_arxiv_relevance_query(q), False,
                f"expected False for {q!r}",
            )

    def test_arxiv_id_heuristic_negative_cases(self):
        # Topical queries / no IDs → True (apply demote)
        cases = [
            "multi-agent LLM context isolation reliability",
            "transformer attention mechanisms",
            "year 2026 review of agents",  # 2026 alone isn't an arXiv ID
        ]
        for q in cases:
            self.assertEqual(
                _is_arxiv_relevance_query(q), True,
                f"expected True for {q!r}",
            )
        # Empty / None — False (no opinion)
        self.assertEqual(_is_arxiv_relevance_query(""), False)
        self.assertEqual(_is_arxiv_relevance_query(None), False)
        self.assertEqual(_is_arxiv_relevance_query("   "), False)


if __name__ == "__main__":
    raise SystemExit(run_tests(V0189ArxivRelevanceTests))
