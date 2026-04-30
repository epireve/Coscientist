"""v0.192 — scout thin-harvest semantics: narrow_harvest at 5–49."""
from __future__ import annotations

from pathlib import Path

from tests.harness import TestCase, run_tests


_REPO = Path(__file__).resolve().parent.parent
_SCOUT_MD = _REPO / ".claude/agents/scout.md"


class V0192ScoutThinThresholdTests(TestCase):

    def test_persona_mentions_narrow_harvest(self):
        txt = _SCOUT_MD.read_text()
        self.assertIn("narrow_harvest", txt)

    def test_persona_no_longer_requires_50_minimum_as_failure(self):
        # Old line "If <50, the harvested shortlist was thin" is gone.
        txt = _SCOUT_MD.read_text()
        self.assertNotIn(
            "If <50, the harvested shortlist was thin",
            txt,
        )

    def test_persona_uses_5_paper_threshold_for_thin(self):
        txt = _SCOUT_MD.read_text()
        # New threshold language mentions 5 (truly thin) and 5–49 (narrow)
        self.assertIn("1–4", txt)
        self.assertIn("5–49", txt)

    def test_output_states_include_narrow_harvest(self):
        txt = _SCOUT_MD.read_text()
        # Output JSON example must include narrow_harvest as a state
        self.assertIn(
            'narrow_harvest', txt,
        )
        # And thin_harvest still present (truly thin case)
        self.assertIn("thin_harvest", txt)


if __name__ == "__main__":
    raise SystemExit(run_tests(V0192ScoutThinThresholdTests))
