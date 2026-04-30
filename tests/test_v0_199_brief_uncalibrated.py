"""v0.199 — uncalibrated-tournament fallback in hypothesis-cards renderer.

When the tournament hasn't run (every hypothesis carries n_matches=0),
the brief should still render the cards section, sorted by created_at,
with an uncalibrated tag. Previously the "drop n_matches==0" rule
(steward prose) wiped the section.
"""

import sys
from pathlib import Path

from tests import _shim  # noqa: F401
from tests.harness import TestCase, run_tests

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from lib.brief_renderer import (  # noqa: E402
    UNCALIBRATED_TAG,
    render_hypothesis_cards,
)


class V0199UncalibratedTests(TestCase):
    def test_all_zero_renders_uncalibrated_in_created_order(self):
        rows = [
            {"hyp_id": "h_b", "statement": "second", "elo": 1700,
             "n_matches": 0, "created_at": "2026-04-30T10:00:00"},
            {"hyp_id": "h_a", "statement": "first", "elo": 1200,
             "n_matches": 0, "created_at": "2026-04-30T09:00:00"},
            {"hyp_id": "h_c", "statement": "third", "elo": 1500,
             "n_matches": 0, "created_at": "2026-04-30T11:00:00"},
        ]
        out = render_hypothesis_cards(rows, top_k=5)
        # Tag present
        self.assertIn(UNCALIBRATED_TAG, out)
        # All hypotheses present (none dropped)
        for hid in ("h_a", "h_b", "h_c"):
            self.assertIn(hid, out)
        # Order by created_at ASC: a, b, c (NOT elo desc which would
        # be b, c, a)
        i_a = out.index("h_a")
        i_b = out.index("h_b")
        i_c = out.index("h_c")
        self.assertTrue(i_a < i_b < i_c)

    def test_mixed_drops_zero_match_back_compat(self):
        rows = [
            {"hyp_id": "h_zero", "statement": "no matches",
             "elo": 1800, "n_matches": 0},
            {"hyp_id": "h_played", "statement": "played",
             "elo": 1400, "n_matches": 5, "n_wins": 3},
        ]
        out = render_hypothesis_cards(rows, top_k=5)
        self.assertIn("h_played", out)
        self.assertNotIn("h_zero", out)
        # Calibrated path → no uncalibrated tag
        self.assertNotIn(UNCALIBRATED_TAG, out)

    def test_all_matched_normal_elo_sort(self):
        rows = [
            {"hyp_id": "h_low", "statement": "S1",
             "elo": 1200, "n_matches": 4},
            {"hyp_id": "h_high", "statement": "S2",
             "elo": 1700, "n_matches": 8},
            {"hyp_id": "h_mid", "statement": "S3",
             "elo": 1400, "n_matches": 6},
        ]
        out = render_hypothesis_cards(rows, top_k=3)
        self.assertNotIn(UNCALIBRATED_TAG, out)
        i_high = out.index("h_high")
        i_mid = out.index("h_mid")
        i_low = out.index("h_low")
        self.assertTrue(i_high < i_mid < i_low)

    def test_empty_table_no_section_marker(self):
        out = render_hypothesis_cards([], top_k=5)
        # No uncalibrated tag emitted on empty input — that case
        # falls through to the placeholder.
        self.assertNotIn(UNCALIBRATED_TAG, out)
        self.assertIn("no hypotheses", out)

    def test_uncalibrated_tag_exact_match(self):
        # Defensive against future rename; if this test breaks,
        # update RUN-RECOVERY.md / steward.md / brief template
        # references too.
        self.assertEqual(
            UNCALIBRATED_TAG,
            "## Hypothesis cards (uncalibrated — no tournament run)",
        )


if __name__ == "__main__":
    sys.exit(run_tests(V0199UncalibratedTests))
