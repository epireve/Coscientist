"""v0.166 — manuscript-reflect hedge-word regression test.

The reflect gate already enforces hedge-word rejection in committed
verdicts (see `.claude/skills/manuscript-reflect/scripts/gate.py`).
These tests pin that behaviour so a future edit removing the gate
fails loudly.

Design choice (documented per task instructions): the gate's existing
heuristic is to scan the four key prose fields (`thesis`, `conclusion`,
`weakest_link.why`, `one_experiment.description`) AFTER stripping
quoted spans. Quoted text is allowed to contain hedge words because
it's a verbatim citation, not a verdict from the agent. Tests below
cover both the positive cases (hedge in committed prose → reject) and
the quoted-allowance edge case.
"""

from __future__ import annotations

import sys
from pathlib import Path

from tests import _shim  # noqa: F401
from tests.harness import TestCase, run_tests

_REPO = Path(__file__).resolve().parent.parent
_GATE = _REPO / ".claude" / "skills" / "manuscript-reflect" / "scripts"
if str(_GATE) not in sys.path:
    sys.path.insert(0, str(_GATE))

import gate as reflect_gate  # noqa: E402


def _base_report() -> dict:
    """Minimal valid report — no hedge words anywhere."""
    return {
        "manuscript_id": "m-test-166",
        "argument_structure": {
            "thesis": "Method X improves accuracy on benchmark B by 12%.",
            "premises": [
                "Premise alpha holds under condition C.",
                "Premise beta is observed in dataset D.",
            ],
            "evidence_chain": [
                {"claim": "Method X scores 0.84 on B.",
                 "evidence": ["self"], "strength": 0.8},
            ],
            "conclusion": "Therefore Method X is the right tool for B.",
        },
        "implicit_assumptions": [
            {"assumption": "Benchmark B reflects real distribution.",
             "fragility": "medium",
             "consequence_if_false": "External validity drops."},
            {"assumption": "Hyperparameters generalize across seeds.",
             "fragility": "low",
             "consequence_if_false": "Variance widens."},
        ],
        "weakest_link": {
            "what": "External validity of B",
            "why": "B was constructed from a single source domain.",
        },
        "one_experiment": {
            "description": "Re-run Method X on benchmark E from a disjoint domain.",
            "expected_impact": "Bounds external-validity claim.",
            "cost_estimate": "2 weeks",
        },
    }


class ReflectHedgeRegressionTests(TestCase):
    """Pin the gate's hedge-word rejection behaviour (v0.166)."""

    def test_clean_report_passes(self):
        """Report with no hedge words → zero validation errors."""
        errors = reflect_gate.validate(_base_report())
        self.assertEqual(errors, [],
                         f"clean report should pass; got {errors}")

    def test_hedge_might_be_rejected(self):
        """'might be' in conclusion → flagged."""
        report = _base_report()
        report["argument_structure"]["conclusion"] = (
            "Method X might be the right tool for B."
        )
        errors = reflect_gate.validate(report)
        self.assertTrue(
            any("hedge word" in e for e in errors),
            f"'might be' must trigger hedge-word error; got {errors}",
        )

    def test_hedge_could_potentially_rejected(self):
        """'could potentially' (and 'potentially' alone) → flagged.

        Pattern matches `\bpotentially\b` so 'could potentially' is
        caught via the 'potentially' branch.
        """
        report = _base_report()
        report["argument_structure"]["thesis"] = (
            "Method X could potentially improve accuracy on B."
        )
        errors = reflect_gate.validate(report)
        self.assertTrue(
            any("hedge word" in e for e in errors),
            f"'could potentially' must trigger hedge-word error; got {errors}",
        )

    def test_hedge_seems_to_rejected(self):
        """'seems to' in weakest_link.why → flagged."""
        report = _base_report()
        report["weakest_link"]["why"] = (
            "Method X seems to overfit when training data is sparse."
        )
        errors = reflect_gate.validate(report)
        self.assertTrue(
            any("hedge word" in e for e in errors),
            f"'seems to' must trigger hedge-word error; got {errors}",
        )

    def test_hedge_inside_quoted_string_allowed(self):
        """Quoted citation text is exempt — gate strips quotes first.

        Edge case from task: 'Smith claims "this may work"' should NOT
        trigger because the hedge is verbatim citation, not the agent's
        own verdict. The gate's `_strip_quoted` removes quoted spans
        before the hedge regex runs.

        Note: 'may' alone isn't in the hedge regex (pattern is
        'might be'/'could be'/'seems to'/...), so we use 'might be'
        inside quotes to exercise the stripping logic specifically.
        """
        report = _base_report()
        report["argument_structure"]["conclusion"] = (
            'Smith claims "this might be useful" but our data refutes it.'
        )
        errors = reflect_gate.validate(report)
        self.assertEqual(
            [e for e in errors if "hedge word" in e], [],
            f"quoted hedge should be stripped; got {errors}",
        )


if __name__ == "__main__":
    sys.exit(run_tests(ReflectHedgeRegressionTests))
