"""v0.118 — session digest doc tests."""
from __future__ import annotations

from pathlib import Path

from tests.harness import TestCase, run_tests

_REPO = Path(__file__).resolve().parents[1]
_DIGEST = _REPO / "docs" / "SESSION-DIGEST-v0.97-v0.117.md"


class DigestTests(TestCase):
    def test_digest_exists(self):
        self.assertTrue(_DIGEST.exists())

    def test_lists_all_versions(self):
        text = _DIGEST.read_text()
        for v in (
            "v0.97", "v0.98", "v0.99", "v0.100",
            "v0.101", "v0.102", "v0.103", "v0.104",
            "v0.105", "v0.106", "v0.107", "v0.108",
            "v0.109", "v0.110", "v0.111", "v0.112",
            "v0.113", "v0.114", "v0.115", "v0.116",
            "v0.117",
        ):
            self.assertIn(v, text, f"missing {v}")

    def test_has_operator_surface(self):
        text = _DIGEST.read_text()
        for cmd in ("lib.health", "lib.trace_render",
                     "lib.trace_status", "lib.agent_quality",
                     "--prune", "--stale-only", "--tool-latency"):
            self.assertIn(cmd, text)

    def test_has_next_steps_section(self):
        text = _DIGEST.read_text()
        self.assertIn("What to do next session", text)


if __name__ == "__main__":
    raise SystemExit(run_tests(DigestTests))
