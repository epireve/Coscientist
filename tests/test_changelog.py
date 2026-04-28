"""v0.79 — CHANGELOG.md parity tests."""
from __future__ import annotations

from pathlib import Path

from lib.changelog import _version_key, parse_roadmap, render_changelog
from tests.harness import TestCase, run_tests

_REPO = Path(__file__).resolve().parents[1]
_ROADMAP = _REPO / "ROADMAP.md"
_CHANGELOG = _REPO / "CHANGELOG.md"


class ChangelogParserTests(TestCase):
    def test_parses_simple_heading(self):
        text = (
            "## Shipped\n\n"
            "### v0.78 — title here ✅ (2026-04-28)\n\n"
            "body content here.\n"
        )
        entries = parse_roadmap(text)
        self.assertEqual(len(entries), 1)
        e = entries[0]
        self.assertEqual(e.version, "v0.78")
        self.assertEqual(e.title, "title here")
        self.assertEqual(e.date, "2026-04-28")
        self.assertIn("body content", e.body)

    def test_no_date_ok(self):
        text = "### v0.50 — minimal title\nbody"
        entries = parse_roadmap(text)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].date, "")

    def test_real_roadmap_parses(self):
        entries = parse_roadmap(_ROADMAP.read_text())
        # Roadmap has many shipped versions.
        self.assertGreater(len(entries), 20)


class VersionKeyTests(TestCase):
    def test_sortable(self):
        from lib.changelog import ChangelogEntry as E
        a = E("v0.78", "", "", "")
        b = E("v0.78a", "", "", "")
        c = E("v0.79", "", "", "")
        self.assertLess(_version_key(a), _version_key(b))
        self.assertLess(_version_key(b), _version_key(c))

    def test_three_digit_minor_sorts_after_two_digit(self):
        """v0.99: regression pin — v0.100 must sort after v0.99
        (defeats string-sort surprise where '100' < '99'
        lexicographically)."""
        from lib.changelog import ChangelogEntry as E
        v10 = E("v0.10", "", "", "")
        v99 = E("v0.99", "", "", "")
        v100 = E("v0.100", "", "", "")
        v98a = E("v0.98a", "", "", "")
        self.assertLess(_version_key(v10), _version_key(v98a))
        self.assertLess(_version_key(v98a), _version_key(v99))
        self.assertLess(_version_key(v99), _version_key(v100))
        # And full sort matches numeric expectation.
        sorted_versions = sorted(
            [v100, v10, v99, v98a], key=_version_key,
        )
        self.assertEqual(
            [e.version for e in sorted_versions],
            ["v0.10", "v0.98a", "v0.99", "v0.100"],
        )


class ChangelogParityTests(TestCase):
    def test_changelog_md_exists(self):
        self.assertTrue(
            _CHANGELOG.exists(),
            "CHANGELOG.md missing — regenerate via "
            "`uv run python -m lib.changelog > CHANGELOG.md`",
        )

    def test_changelog_md_matches_generator(self):
        if not _CHANGELOG.exists():
            return
        actual = _CHANGELOG.read_text()
        expected = render_changelog(parse_roadmap(_ROADMAP.read_text()))
        if actual != expected:
            actual_lines = actual.splitlines()
            expected_lines = expected.splitlines()
            for i, (a, b) in enumerate(zip(actual_lines, expected_lines)):
                if a != b:
                    self.assertEqual(
                        a, b,
                        f"CHANGELOG.md drift at line {i+1}. "
                        f"Regenerate via `uv run python -m lib.changelog "
                        f"> CHANGELOG.md`",
                    )
                    break
            else:
                self.assertEqual(
                    len(actual_lines), len(expected_lines),
                    f"line count differs: {len(actual_lines)} != "
                    f"{len(expected_lines)}",
                )


if __name__ == "__main__":
    raise SystemExit(run_tests(
        ChangelogParserTests,
        VersionKeyTests,
        ChangelogParityTests,
    ))
