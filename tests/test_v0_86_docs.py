"""v0.86 — docs presence + content invariants."""
from __future__ import annotations

from pathlib import Path

from tests.harness import TestCase, run_tests


_REPO = Path(__file__).resolve().parents[1]


class ArchitectureDocTests(TestCase):
    PATH = _REPO / "docs" / "architecture.md"

    def test_present(self):
        self.assertTrue(self.PATH.exists())

    def test_covers_core_layers(self):
        text = self.PATH.read_text()
        for needle in (
            "Two-tier mental model",
            "Artifact contract",
            "SQLite scopes",
            "Migration framework",
            "Sub-agent phases",
            "Plugin distribution",
            "Test discipline",
        ):
            self.assertIn(needle, text,
                          f"docs/architecture.md missing: {needle}")


class ResearchLoopDocTests(TestCase):
    PATH = _REPO / "docs" / "research-loop.md"

    def test_present(self):
        self.assertTrue(self.PATH.exists())

    def test_covers_pipeline(self):
        text = self.PATH.read_text()
        for needle in (
            "Phase 0", "Phase 1", "Phase 2", "Phase 3",
            "Scout", "Cartographer", "Chronicler", "Surveyor",
            "Synthesist", "Architect", "Inquisitor", "Weaver",
            "Visionary", "Steward",
            "BREAK 0", "BREAK 1", "BREAK 2",
        ):
            self.assertIn(needle, text,
                          f"research-loop.md missing: {needle}")

    def test_lists_three_modes(self):
        text = self.PATH.read_text()
        for mode in ("Quick", "Deep", "Wide"):
            self.assertIn(mode, text)


class CodeOfConductTests(TestCase):
    PATH = _REPO / "CODE_OF_CONDUCT.md"

    def test_present(self):
        self.assertTrue(self.PATH.exists())

    def test_has_enforcement_contact(self):
        text = self.PATH.read_text()
        self.assertIn("@", text)  # email contact
        self.assertIn("Enforcement", text)


class SecurityDocTests(TestCase):
    PATH = _REPO / "SECURITY.md"

    def test_present(self):
        self.assertTrue(self.PATH.exists())

    def test_has_reporting_channel(self):
        text = self.PATH.read_text()
        self.assertIn("@", text)
        self.assertIn("Reporting", text)

    def test_lists_scope_and_hardening(self):
        text = self.PATH.read_text()
        self.assertIn("Scope", text)
        self.assertIn("CHECKSUMS", text)


if __name__ == "__main__":
    raise SystemExit(run_tests(
        ArchitectureDocTests,
        ResearchLoopDocTests,
        CodeOfConductTests,
        SecurityDocTests,
    ))
