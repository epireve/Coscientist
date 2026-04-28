"""v0.139 — second session digest regression."""
from __future__ import annotations

from pathlib import Path

from tests.harness import TestCase, run_tests


_REPO = Path(__file__).resolve().parents[1]
_DIGEST = _REPO / "docs" / "SESSION-DIGEST-v0.118-v0.138.md"


class DigestTests(TestCase):
    def test_digest_exists(self):
        self.assertTrue(_DIGEST.exists())

    def test_lists_all_versions(self):
        text = _DIGEST.read_text()
        for v in ("v0.118", "v0.123", "v0.127", "v0.131",
                   "v0.134", "v0.137", "v0.138"):
            self.assertIn(v, text, f"missing {v}")

    def test_has_operator_surface(self):
        text = _DIGEST.read_text()
        for cmd in ("trace_export", "persona_doc_check",
                     "hook_check", "test-like-ci",
                     "ci-status", "trends.py"):
            self.assertIn(cmd, text)

    def test_documents_deferred_items(self):
        text = _DIGEST.read_text()
        self.assertIn("deliberately NOT done", text)
        self.assertIn("Health cron", text)


if __name__ == "__main__":
    raise SystemExit(run_tests(DigestTests))
