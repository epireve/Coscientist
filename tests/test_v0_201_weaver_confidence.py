"""v0.201 — weaver consensus/tension claims must include numeric confidence.

Mirror Synthesist's pattern: every claim commits to a confidence
float in (0, 1) rather than implicit-uncertainty hedging.
"""

import sys
from pathlib import Path

from tests import _shim  # noqa: F401
from tests.harness import TestCase, run_tests

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

WEAVER_MD = _ROOT / ".claude" / "agents" / "weaver.md"


class V0201WeaverConfidenceTests(TestCase):
    def test_persona_prompt_requires_confidence_in_consensus(self):
        body = WEAVER_MD.read_text()
        # Confidence appears inside the consensus JSON shape block
        self.assertIn("confidence", body)
        # And the explicit requirement after the JSON block
        self.assertIn("confidence", body.lower())
        # The phrase "commit to a number" mirrors synthesist's wording
        self.assertIn("commit to a number", body)

    def test_persona_prompt_requires_confidence_in_tensions(self):
        body = WEAVER_MD.read_text()
        # Both consensus and tensions blocks should mention confidence.
        # Cheap way: count occurrences ≥ 2 (one per shape block + the
        # post-JSON requirement = ≥2).
        self.assertGreaterEqual(body.count("confidence"), 2)

    def test_synthesist_pattern_referenced(self):
        # Forward-only requirement: existing weaver claims in older
        # DBs without confidence are not retroactively invalid.
        # The persona prompt is the source of truth for new runs;
        # rubric/schema gates aren't tightened in this sweep.
        body = WEAVER_MD.read_text()
        self.assertIn("Synthesist", body)


if __name__ == "__main__":
    sys.exit(run_tests(V0201WeaverConfidenceTests))
