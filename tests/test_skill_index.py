"""v0.67 — SKILLS.md index parity tests.

Asserts:
  1. Every .claude/skills/<dir>/SKILL.md is discovered.
  2. Every SkillEntry has non-empty name + description + when_to_use.
  3. SKILLS.md at repo root is byte-identical to the generator output
     (regression net for stale index).
  4. SkillEntry name field matches directory name (no rename drift).
"""
from __future__ import annotations

from pathlib import Path

from tests.harness import TestCase, run_tests
from lib.skill_index import discover_skills, render_index


_REPO = Path(__file__).resolve().parents[1]
_SKILLS_ROOT = _REPO / ".claude" / "skills"
_SKILLS_MD = _REPO / "SKILLS.md"


class SkillIndexDiscoveryTests(TestCase):
    def test_discovers_at_least_60_skills(self):
        entries = discover_skills(_SKILLS_ROOT)
        # Hard floor — silently losing skills should fail loud.
        self.assertGreaterEqual(
            len(entries), 60,
            f"only {len(entries)} skills discovered — likely missing SKILL.md",
        )

    def test_every_entry_has_name(self):
        for e in discover_skills(_SKILLS_ROOT):
            self.assertTrue(e.name, f"empty name in {e.path}")

    def test_every_entry_has_description(self):
        empty = [e for e in discover_skills(_SKILLS_ROOT) if not e.description]
        self.assertEqual(
            empty, [],
            f"skills missing description: {[e.path.name for e in empty]}",
        )

    def test_every_entry_has_when_to_use(self):
        empty = [
            e for e in discover_skills(_SKILLS_ROOT) if not e.when_to_use
        ]
        self.assertEqual(
            empty, [],
            f"skills missing when_to_use: "
            f"{[str(e.path.relative_to(_REPO)) for e in empty]}",
        )

    def test_name_matches_directory(self):
        for e in discover_skills(_SKILLS_ROOT):
            dir_name = e.path.parent.name
            self.assertEqual(
                e.name, dir_name,
                f"frontmatter name {e.name!r} != dir {dir_name!r} "
                f"in {e.path}",
            )

    def test_no_duplicate_names(self):
        entries = discover_skills(_SKILLS_ROOT)
        names = [e.name for e in entries]
        self.assertEqual(
            len(names), len(set(names)),
            "duplicate skill names in discovery",
        )


class SkillsMdParityTests(TestCase):
    def test_skills_md_exists(self):
        self.assertTrue(
            _SKILLS_MD.exists(),
            "SKILLS.md missing at repo root — regenerate via "
            "`uv run python -m lib.skill_index > SKILLS.md`",
        )

    def test_skills_md_matches_generator(self):
        if not _SKILLS_MD.exists():
            return  # covered by test_skills_md_exists
        actual = _SKILLS_MD.read_text()
        expected = render_index(discover_skills(_SKILLS_ROOT))
        if actual != expected:
            # Show first divergent line for debuggability.
            actual_lines = actual.splitlines()
            expected_lines = expected.splitlines()
            for i, (a, b) in enumerate(zip(actual_lines, expected_lines)):
                if a != b:
                    self.assertEqual(
                        a, b,
                        f"SKILLS.md drift at line {i+1}. "
                        f"Regenerate via `uv run python -m lib.skill_index "
                        f"> SKILLS.md`. First diff: actual={a!r} "
                        f"expected={b!r}",
                    )
                    break
            else:
                # No mid-line diff — must be length mismatch.
                self.assertEqual(
                    len(actual_lines), len(expected_lines),
                    f"SKILLS.md line count differs: "
                    f"actual={len(actual_lines)} expected={len(expected_lines)}",
                )


if __name__ == "__main__":
    raise SystemExit(run_tests(
        SkillIndexDiscoveryTests,
        SkillsMdParityTests,
    ))
