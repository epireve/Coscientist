"""v0.193 — consensus auth-aware budgeting in source_selector.call_budget."""
from __future__ import annotations

import os
from pathlib import Path

from lib.source_selector import call_budget
from tests.harness import TestCase, run_tests


_REPO = Path(__file__).resolve().parent.parent
_RUBRIC = _REPO / "docs/SOURCE-SELECTOR-RUBRIC.md"


class V0193ConsensusAuthBudgetTests(TestCase):

    def setUp(self):
        # Clear env to make defaults predictable.
        self._prev = os.environ.pop("CONSENSUS_API_KEY", None)

    def tearDown(self):
        if self._prev is not None:
            os.environ["CONSENSUS_API_KEY"] = self._prev
        else:
            os.environ.pop("CONSENSUS_API_KEY", None)

    def test_default_unauthed_consensus_is_3_results(self):
        b = call_budget(mode="deep", consensus_authed=False)
        self.assertEqual(b["consensus_results_per_call"], 3)
        self.assertEqual(b["consensus_authed"], False)

    def test_authed_consensus_is_10_results(self):
        b = call_budget(mode="deep", consensus_authed=True)
        self.assertEqual(b["consensus_results_per_call"], 10)
        self.assertEqual(b["consensus_authed"], True)

    def test_env_var_detected_as_authed(self):
        os.environ["CONSENSUS_API_KEY"] = "fake-key-xyz"
        b = call_budget(mode="deep")  # consensus_authed=None → auto
        self.assertEqual(b["consensus_authed"], True)
        self.assertEqual(b["consensus_results_per_call"], 10)

    def test_deep_mode_extra_consensus_call_when_unauthed(self):
        # Unauthed deep budget bumps consensus calls (3 vs 2) to partly
        # compensate for the 3-result cap.
        unauthed = call_budget(mode="deep", consensus_authed=False)
        authed = call_budget(mode="deep", consensus_authed=True)
        self.assertEqual(unauthed["consensus"], 3)
        self.assertEqual(authed["consensus"], 2)

    def test_back_compat_signature_still_works(self):
        # Call with only mode= (existing signature) — must not crash.
        b = call_budget(mode="quick")
        self.assertEqual(b["consensus"], 0)
        self.assertIn("consensus_results_per_call", b)

    def test_rubric_doc_mentions_3_result_cap(self):
        txt = _RUBRIC.read_text()
        self.assertIn("3-result", txt.lower().replace(" ", "-")
                      .replace("3 result", "3-result"))
        # Mentions the auth flag
        self.assertIn("consensus_authed", txt)


if __name__ == "__main__":
    raise SystemExit(run_tests(V0193ConsensusAuthBudgetTests))
