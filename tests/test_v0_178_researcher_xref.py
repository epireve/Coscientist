"""v0.178 — RESEARCHER cross-reference doc shape regression."""
from __future__ import annotations

from pathlib import Path

from tests.harness import TestCase, run_tests

_REPO = Path(__file__).resolve().parents[1]
_DOC = _REPO / "docs" / "RESEARCHER-CROSS-REF.md"


class V0178ResearcherXrefTests(TestCase):
    def test_doc_exists_and_non_empty(self):
        self.assertTrue(_DOC.exists(), "RESEARCHER-CROSS-REF.md missing")
        self.assertGreater(
            len(_DOC.read_text()), 500,
            "RESEARCHER-CROSS-REF.md unexpectedly small",
        )

    def test_table_has_all_principles(self):
        text = _DOC.read_text()
        # Each principle row starts with `| <n> |` — count them.
        for n in range(1, 11):  # 10 principles minimum
            self.assertIn(
                f"| {n} |", text,
                f"principle {n} row missing from cross-ref table",
            )

    def test_name_five_has_at_least_one_agent(self):
        text = _DOC.read_text()
        # The principle 6 row must mention architect (we know it does).
        # Find the line containing "Name Five" and check architect on it.
        for line in text.splitlines():
            if "Name Five" in line and line.startswith("| 6 |"):
                self.assertIn(
                    "architect", line,
                    "Name Five row missing architect reference",
                )
                return
        raise AssertionError("Name Five row not found in table")


if __name__ == "__main__":
    run_tests(V0178ResearcherXrefTests)
